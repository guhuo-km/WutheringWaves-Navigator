from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.map_context import TileKey  # noqa: E402
from minimap_sift_index import (  # noqa: E402
    compose_expanded_tile_from_cache,
    create_sift_detector,
    extract_owned_sift_features_from_expanded_tile,
    resolve_tile_image_path,
)
from minimap_retrieval_index import (  # noqa: E402
    CandidateDescriptor,
    CandidateWindow,
    build_candidate_windows,
    compute_hsv_texture_descriptor,
    retrieve_top_k,
)
from minimap_roi import (  # noqa: E402
    build_minimap_texture_match_mask,
    crop_minimap_from_frame,
    detect_minimap_circle_roi,
    normalize_minimap_crop,
)

BANNER = """MINIMAP RETRIEVAL SIFT EXPERIMENT ONLY
This script does not validate production behavior.
Human confirmation is required for all real-sample results."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline minimap retrieval/SIFT experiment runner.")
    parser.add_argument("--sample-dir", type=Path)
    parser.add_argument("--sample-image", type=Path)
    parser.add_argument("--map-context-json", type=Path)
    parser.add_argument("--tile-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--window-size", type=int, default=512)
    parser.add_argument("--stride", type=int, default=256)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--sift-overlap", type=int, default=64)
    parser.add_argument(
        "--mode",
        choices=("rough-index", "rough-query", "sift-index", "sift-query", "full-experiment"),
        required=True,
    )
    return parser


def _path_to_text(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _write_run_config(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "sample_dir": _path_to_text(args.sample_dir),
        "sample_image": _path_to_text(args.sample_image),
        "map_context_json": _path_to_text(args.map_context_json),
        "tile_root": _path_to_text(args.tile_root),
        "output_dir": str(output_dir),
        "window_size": int(args.window_size),
        "stride": int(args.stride),
        "top_k": int(args.top_k),
        "sift_overlap": int(args.sift_overlap),
        "mode": str(args.mode),
        "production_validation": False,
        "requires_human_confirmation": True,
    }
    config_path = output_dir / "run_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"json_not_object:{path}")
    return data


def _read_image(path: Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None:
        raise ValueError(f"image_not_readable:{path}")
    return image


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"image_encode_failed:{path}")
    encoded.tofile(str(path))


def _manifest_paths(tile_root: Path) -> list[Path]:
    root = Path(tile_root)
    if root.is_file() and root.name == "manifest.json":
        return [root]
    return sorted(root.glob("**/manifest.json"))


def _load_first_rough_manifest(tile_root: Path) -> tuple[dict, Path, np.ndarray]:
    manifests = _manifest_paths(tile_root)
    if not manifests:
        raise ValueError(f"no_manifest_json_under:{tile_root}")
    manifest_path = manifests[0]
    manifest = _read_json(manifest_path)
    rough_rel = manifest.get("rough_color_path")
    if not isinstance(rough_rel, str) or not rough_rel:
        raise ValueError(f"manifest_missing_rough_color_path:{manifest_path}")
    root = Path(tile_root)
    if root.is_file():
        root = root.parent.parent.parent if len(root.parts) >= 3 else root.parent
    rough_path = root / rough_rel
    if not rough_path.exists():
        rough_path = manifest_path.parent / Path(rough_rel).name
    rough = _read_image(rough_path, cv2.IMREAD_COLOR)
    return manifest, rough_path, rough


def _build_cache_backed_rough_source(cache_root: Path, output_dir: Path) -> tuple[dict, Path, np.ndarray]:
    keys = _scan_cache_tile_keys(cache_root, kind="standard")
    if not keys:
        raise ValueError(f"no_manifest_or_standard_tiles_under:{cache_root}")
    tile_size = 1024
    rough_downsample = 4
    rough_tile_size = tile_size // rough_downsample
    min_x = min(key.x for key in keys)
    max_x = max(key.x for key in keys)
    min_y = min(key.y for key in keys)
    max_y = max(key.y for key in keys)
    origin_y = max_y
    width = (max_x - min_x + 1) * rough_tile_size
    height = (max_y - min_y + 1) * rough_tile_size
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    for key in keys:
        path = resolve_tile_image_path(cache_root, key)
        if not path.exists():
            continue
        tile = _read_image(path, cv2.IMREAD_COLOR)
        if tile.shape[:2] != (tile_size, tile_size):
            tile = cv2.resize(tile, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
        rough_tile = cv2.resize(tile, (rough_tile_size, rough_tile_size), interpolation=cv2.INTER_AREA)
        left = (key.x - min_x) * rough_tile_size
        top = (origin_y - key.y) * rough_tile_size
        canvas[top:top + rough_tile_size, left:left + rough_tile_size] = rough_tile

    rough_path = output_dir / "experimental_cache_rough_color.png"
    _write_image(rough_path, canvas)
    manifest = {
        "area_id": keys[0].area_id,
        "candidate_type": "base",
        "layer_id": keys[0].layer_id,
        "z_level": None,
        "tile_size": tile_size,
        "origin_tile_x": min_x,
        "origin_tile_y": origin_y,
        "width": width * rough_downsample,
        "height": height * rough_downsample,
        "rough_color_path": str(rough_path),
        "manifest_path": str(output_dir / "experimental_cache_manifest.json"),
        "rough_downsample": rough_downsample,
        "source": "cache_backed_experiment",
    }
    (output_dir / "experimental_cache_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest, rough_path, canvas


def _load_or_build_rough_source(tile_root: Path, output_dir: Path) -> tuple[dict, Path, np.ndarray]:
    if _manifest_paths(tile_root):
        return _load_first_rough_manifest(tile_root)
    return _build_cache_backed_rough_source(tile_root, output_dir)


def _descriptor_windows(
    image_bgr: np.ndarray,
    windows: list[CandidateWindow],
) -> list[CandidateDescriptor]:
    descriptors: list[CandidateDescriptor] = []
    for window in windows:
        patch = image_bgr[
            window.top:window.top + window.height,
            window.left:window.left + window.width,
        ]
        if patch.shape[0] != window.height or patch.shape[1] != window.width:
            continue
        descriptors.append(
            CandidateDescriptor(
                candidate=window,
                vector=compute_hsv_texture_descriptor(patch),
            )
        )
    return descriptors


def _save_retrieval_index(output_dir: Path, descriptors: list[CandidateDescriptor]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if descriptors:
        vectors = np.stack([item.vector for item in descriptors]).astype(np.float32)
    else:
        vectors = np.empty((0, 0), dtype=np.float32)
    window_ids = np.array([item.candidate.window_id for item in descriptors], dtype=object)
    np.savez_compressed(output_dir / "retrieval_index.npz", vectors=vectors, window_ids=window_ids)


def _save_windows_json(
    output_dir: Path,
    *,
    manifest: dict,
    rough_image_path: Path,
    windows: list[CandidateWindow],
    window_size: int,
    stride: int,
    rough_tile_size: int,
    rough_downsample: int,
) -> None:
    payload = {
        "region_id": str(manifest.get("area_id", "")),
        "source_manifest": str(manifest.get("manifest_path", "")),
        "rough_image_path": str(rough_image_path),
        "rough_downsample": int(rough_downsample),
        "origin_tile_x": manifest.get("origin_tile_x"),
        "origin_tile_y": manifest.get("origin_tile_y"),
        "fine_width": manifest.get("width"),
        "fine_height": manifest.get("height"),
        "window_size": int(window_size),
        "stride": int(stride),
        "tile_size": int(rough_tile_size),
        "window_count": len(windows),
        "windows": [asdict(window) for window in windows],
    }
    (output_dir / "retrieval_windows.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _make_contact_sheet(
    image_bgr: np.ndarray,
    windows: list[CandidateWindow],
    *,
    label_prefix: str = "",
    max_items: int = 64,
    thumb_size: int = 128,
) -> np.ndarray:
    selected = windows[:max_items]
    if not selected:
        return np.zeros((thumb_size, thumb_size, 3), dtype=np.uint8)
    cols = min(8, len(selected))
    rows = int(np.ceil(len(selected) / cols))
    sheet = np.zeros((rows * thumb_size, cols * thumb_size, 3), dtype=np.uint8)
    for index, window in enumerate(selected):
        patch = image_bgr[
            window.top:window.top + window.height,
            window.left:window.left + window.width,
        ]
        if patch.size == 0:
            continue
        thumb = cv2.resize(patch, (thumb_size, thumb_size), interpolation=cv2.INTER_AREA)
        row = index // cols
        col = index % cols
        top = row * thumb_size
        left = col * thumb_size
        sheet[top:top + thumb_size, left:left + thumb_size] = thumb
        label = f"{label_prefix}{index + 1}"
        cv2.putText(
            sheet,
            label,
            (left + 5, top + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
    return sheet


def _make_image_contact_sheet(
    images: list[np.ndarray],
    *,
    labels: list[str] | None = None,
    max_items: int = 36,
    thumb_size: int = 128,
) -> np.ndarray:
    selected = images[:max_items]
    if not selected:
        return np.zeros((thumb_size, thumb_size, 3), dtype=np.uint8)
    cols = min(6, len(selected))
    rows = int(np.ceil(len(selected) / cols))
    sheet = np.zeros((rows * thumb_size, cols * thumb_size, 3), dtype=np.uint8)
    labels = labels or []
    for index, image in enumerate(selected):
        thumb = cv2.resize(image, (thumb_size, thumb_size), interpolation=cv2.INTER_AREA)
        row = index // cols
        col = index % cols
        top = row * thumb_size
        left = col * thumb_size
        sheet[top:top + thumb_size, left:left + thumb_size] = thumb
        if index < len(labels):
            cv2.putText(
                sheet,
                labels[index],
                (left + 5, top + 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )
    return sheet


def _load_windows_and_vectors(output_dir: Path) -> tuple[list[CandidateWindow], np.ndarray]:
    windows_data = _read_json(output_dir / "retrieval_windows.json")
    windows = [CandidateWindow(**item) for item in windows_data.get("windows", [])]
    index_data = np.load(output_dir / "retrieval_index.npz", allow_pickle=True)
    vectors = index_data["vectors"].astype(np.float32)
    return windows, vectors


def _load_rough_image_for_query(output_dir: Path, tile_root: Path | None) -> np.ndarray:
    windows_data = _read_json(output_dir / "retrieval_windows.json")
    rough_image_path = windows_data.get("rough_image_path")
    if isinstance(rough_image_path, str) and rough_image_path:
        rough_path = Path(rough_image_path)
        if rough_path.exists():
            return _read_image(rough_path, cv2.IMREAD_COLOR)
        candidate = output_dir / rough_path.name
        if candidate.exists():
            return _read_image(candidate, cv2.IMREAD_COLOR)
    if tile_root is None:
        raise ValueError("rough image unavailable and --tile-root was not provided")
    _, _, rough = _load_first_rough_manifest(tile_root)
    return rough


def _auto_minimap_roi(frame: np.ndarray):
    height, width = frame.shape[:2]
    search_rect = (0, 0, max(1, width // 8), max(1, height // 4))
    return detect_minimap_circle_roi(frame, search_rect)


def _run_rough_index(args: argparse.Namespace) -> None:
    if args.tile_root is None:
        raise ValueError("--tile-root is required for rough-index")
    output_dir = Path(args.output_dir)
    manifest, rough_image_path, rough = _load_or_build_rough_source(Path(args.tile_root), output_dir)
    downsample = int(manifest.get("rough_downsample", 4) or 4)
    rough_tile_size = max(1, int(manifest.get("tile_size", 1024)) // max(1, downsample))
    windows = build_candidate_windows(
        region_id=str(manifest.get("area_id", "")),
        map_left=0,
        map_top=0,
        map_width=int(rough.shape[1]),
        map_height=int(rough.shape[0]),
        window_size=int(args.window_size),
        stride=int(args.stride),
        tile_size=rough_tile_size,
    )
    descriptors = _descriptor_windows(rough, windows)
    _save_retrieval_index(output_dir, descriptors)
    _save_windows_json(
        output_dir,
        manifest=manifest,
        rough_image_path=rough_image_path,
        windows=[item.candidate for item in descriptors],
        window_size=int(args.window_size),
        stride=int(args.stride),
        rough_tile_size=rough_tile_size,
        rough_downsample=downsample,
    )
    _write_image(output_dir / "window_contact_sheet.png", _make_contact_sheet(rough, windows))
    print(f"retrieval_index: {output_dir / 'retrieval_index.npz'}")
    print(f"retrieval_windows: {output_dir / 'retrieval_windows.json'}")
    print(f"window_contact_sheet: {output_dir / 'window_contact_sheet.png'}")


def _run_rough_query(args: argparse.Namespace) -> None:
    if args.sample_image is None:
        raise ValueError("--sample-image is required for rough-query")
    if args.tile_root is None:
        raise ValueError("--tile-root is required for rough-query")
    output_dir = Path(args.output_dir)
    windows, vectors = _load_windows_and_vectors(output_dir)
    if len(windows) != len(vectors):
        raise ValueError("retrieval_windows and retrieval_index length mismatch")

    rough = _load_rough_image_for_query(output_dir, Path(args.tile_root) if args.tile_root is not None else None)
    frame = _read_image(Path(args.sample_image), cv2.IMREAD_COLOR)
    roi = _auto_minimap_roi(frame)
    if roi is None:
        raise ValueError("auto_minimap_roi_failed")
    crop = crop_minimap_from_frame(frame, roi)
    normalized = normalize_minimap_crop(crop, roi.shape)
    query_mask = build_minimap_texture_match_mask(normalized.mask)
    query = cv2.bitwise_and(normalized.exact_image, normalized.exact_image, mask=query_mask)
    query_vector = compute_hsv_texture_descriptor(normalized.exact_image, mask=query_mask)
    descriptors = [
        CandidateDescriptor(candidate=window, vector=vector)
        for window, vector in zip(windows, vectors)
    ]
    hits = retrieve_top_k(query_vector, descriptors, top_k=int(args.top_k))
    hit_windows = [hit.candidate for hit in hits]

    _write_image(output_dir / "query_minimap.png", query)
    _write_image(
        output_dir / "topK_contact_sheet.png",
        _make_contact_sheet(rough, hit_windows, label_prefix="#", max_items=int(args.top_k)),
    )
    payload = {
        "sample_image": str(args.sample_image),
        "roi": asdict(roi),
        "top_k": int(args.top_k),
        "rough_to_fine_scale": int(_read_json(output_dir / "retrieval_windows.json").get("rough_downsample", 4) or 4),
        "hits": [
            {
                "rank": hit.rank,
                "score": hit.score,
                "candidate": asdict(hit.candidate),
            }
            for hit in hits
        ],
        "human_confirmation_required": True,
    }
    (output_dir / "topK_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"query_minimap: {output_dir / 'query_minimap.png'}")
    print(f"topK_contact_sheet: {output_dir / 'topK_contact_sheet.png'}")
    print(f"topK_results: {output_dir / 'topK_results.json'}")
    print("Human confirmation is required before interpreting these candidates.")


def _extract_query_sift(frame_path: Path):
    frame = _read_image(frame_path, cv2.IMREAD_COLOR)
    roi = _auto_minimap_roi(frame)
    if roi is None:
        raise ValueError("auto_minimap_roi_failed")
    crop = crop_minimap_from_frame(frame, roi)
    normalized = normalize_minimap_crop(crop, roi.shape)
    detector = create_sift_detector()
    keypoints, descriptors = detector.detectAndCompute(normalized.exact_image, normalized.mask)
    if descriptors is None:
        descriptors = np.empty((0, 128), dtype=np.float32)
        keypoints = []
    return normalized.exact_image, roi, list(keypoints), descriptors.astype(np.float32)


def _load_sift_index(output_dir: Path) -> dict[str, np.ndarray]:
    path = output_dir / "sift_features.npz"
    if not path.exists():
        raise ValueError(f"sift_features_missing:{path}")
    data = np.load(path)
    return {
        "descriptors": data["descriptors"].astype(np.float32),
        "global_xy": data["global_xy"].astype(np.float32),
        "tile_xy": data["tile_xy"].astype(np.int32),
    }


def _candidate_feature_indices(global_xy: np.ndarray, candidate: dict, rough_to_fine_scale: int) -> np.ndarray:
    raw = candidate["candidate"]
    left = float(raw["left"]) * rough_to_fine_scale
    top = float(raw["top"]) * rough_to_fine_scale
    right = left + float(raw["width"]) * rough_to_fine_scale
    bottom = top + float(raw["height"]) * rough_to_fine_scale
    mask = (
        (global_xy[:, 0] >= left)
        & (global_xy[:, 0] < right)
        & (global_xy[:, 1] >= top)
        & (global_xy[:, 1] < bottom)
    )
    return np.flatnonzero(mask)


def _draw_query_keypoints(query_image: np.ndarray, keypoints) -> np.ndarray:
    return cv2.drawKeypoints(
        query_image,
        keypoints,
        None,
        flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
    )


def _draw_candidate_keypoints(candidate_patch: np.ndarray, keypoints) -> np.ndarray:
    return cv2.drawKeypoints(
        candidate_patch,
        keypoints,
        None,
        flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
    )


def _match_query_to_candidate(
    *,
    query_descriptors: np.ndarray,
    candidate_descriptors: np.ndarray,
):
    if len(query_descriptors) < 2 or len(candidate_descriptors) < 2:
        return [], []
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    knn = matcher.knnMatch(query_descriptors, candidate_descriptors, k=2)
    from minimap_sift_matcher import filter_ratio_matches

    return knn, filter_ratio_matches(knn, ratio=0.75)


def _estimate_translation_from_matches(
    query_keypoints,
    candidate_global_xy: np.ndarray,
    good_matches,
) -> tuple[float | None, float | None, list]:
    if len(good_matches) < 3:
        return None, None, []
    offsets = []
    for match in good_matches:
        qx, qy = query_keypoints[match.queryIdx].pt
        gx, gy = candidate_global_xy[match.trainIdx]
        offsets.append((float(gx - qx), float(gy - qy)))
    offsets_array = np.array(offsets, dtype=np.float32)
    median = np.median(offsets_array, axis=0)
    distances = np.max(np.abs(offsets_array - median), axis=1)
    inlier_matches = [
        match
        for match, distance in zip(good_matches, distances)
        if float(distance) <= 25.0
    ]
    return float(median[0]), float(median[1]), inlier_matches


def _estimate_similarity_from_matches(
    query_keypoints,
    candidate_global_xy: np.ndarray,
    good_matches,
    *,
    query_width: int,
    query_height: int,
) -> dict:
    if len(good_matches) < 3:
        return {
            "estimated_global_x": None,
            "estimated_global_y": None,
            "estimated_center_x": None,
            "estimated_center_y": None,
            "query_to_map_scale_x": None,
            "query_to_map_scale_y": None,
            "query_to_map_matrix": None,
            "inlier_matches": [],
        }

    query_points = np.array(
        [query_keypoints[match.queryIdx].pt for match in good_matches],
        dtype=np.float32,
    )
    map_points = np.array(
        [candidate_global_xy[match.trainIdx] for match in good_matches],
        dtype=np.float32,
    )
    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        query_points,
        map_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=12.0,
        maxIters=2000,
        confidence=0.99,
        refineIters=10,
    )
    if matrix is None:
        estimated_x, estimated_y, inlier_matches = _estimate_translation_from_matches(
            query_keypoints,
            candidate_global_xy,
            good_matches,
        )
        return {
            "estimated_global_x": estimated_x,
            "estimated_global_y": estimated_y,
            "estimated_center_x": None,
            "estimated_center_y": None,
            "query_to_map_scale_x": None,
            "query_to_map_scale_y": None,
            "query_to_map_matrix": None,
            "inlier_matches": inlier_matches,
        }

    if inlier_mask is None:
        inlier_matches = list(good_matches)
    else:
        flat_mask = inlier_mask.reshape(-1).astype(bool)
        inlier_matches = [
            match
            for match, keep in zip(good_matches, flat_mask)
            if bool(keep)
        ]

    top_left = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    center = np.array([float(query_width) / 2.0, float(query_height) / 2.0, 1.0], dtype=np.float64)
    estimated_top_left = matrix @ top_left
    estimated_center = matrix @ center
    scale_x = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    scale_y = float(np.hypot(matrix[0, 1], matrix[1, 1]))
    return {
        "estimated_global_x": float(estimated_top_left[0]),
        "estimated_global_y": float(estimated_top_left[1]),
        "estimated_center_x": float(estimated_center[0]),
        "estimated_center_y": float(estimated_center[1]),
        "query_to_map_scale_x": scale_x,
        "query_to_map_scale_y": scale_y,
        "query_to_map_matrix": matrix.astype(float).tolist(),
        "inlier_matches": inlier_matches,
    }


def _select_best_sift_candidate(results: list[dict]) -> dict | None:
    if not results:
        return None
    return max(
        results,
        key=lambda item: (
            int(item.get("inlier_count") or 0),
            int(item.get("good_match_count") or 0),
            -int(item.get("rank") or 999999),
        ),
    )


def _candidate_patch_from_rough(rough_image: np.ndarray, hit: dict) -> np.ndarray:
    raw = hit["candidate"]
    left = int(raw["left"])
    top = int(raw["top"])
    width = int(raw["width"])
    height = int(raw["height"])
    patch = rough_image[top:top + height, left:left + width]
    if patch.shape[:2] != (height, width):
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        canvas[:patch.shape[0], :patch.shape[1]] = patch
        return canvas
    return patch.copy()


def _candidate_keypoints_for_rough_patch(
    candidate_global_xy: np.ndarray,
    hit: dict,
    rough_to_fine_scale: int,
):
    raw = hit["candidate"]
    left = float(raw["left"])
    top = float(raw["top"])
    scale = float(rough_to_fine_scale)
    return [
        cv2.KeyPoint(
            float(point[0] / scale - left),
            float(point[1] / scale - top),
            3,
        )
        for point in candidate_global_xy
    ]


def _write_match_image(
    path: Path,
    *,
    query_image: np.ndarray,
    query_keypoints,
    candidate_patch: np.ndarray,
    candidate_keypoints,
    matches,
    label: str,
) -> None:
    if matches:
        image = cv2.drawMatches(
            query_image,
            query_keypoints,
            candidate_patch,
            candidate_keypoints,
            list(matches),
            None,
            flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
        )
    else:
        query_vis = query_image.copy()
        if query_vis.shape[0] != candidate_patch.shape[0]:
            scale = candidate_patch.shape[0] / max(1, query_vis.shape[0])
            query_vis = cv2.resize(
                query_vis,
                (max(1, int(round(query_vis.shape[1] * scale))), candidate_patch.shape[0]),
                interpolation=cv2.INTER_AREA,
            )
        image = np.zeros(
            (
                max(query_vis.shape[0], candidate_patch.shape[0]),
                query_vis.shape[1] + candidate_patch.shape[1],
                3,
            ),
            dtype=np.uint8,
        )
        image[:query_vis.shape[0], :query_vis.shape[1]] = query_vis
        image[:candidate_patch.shape[0], query_vis.shape[1]:] = candidate_patch
    cv2.putText(image, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
    _write_image(path, image)


def _run_sift_query(args: argparse.Namespace) -> None:
    if args.sample_image is None:
        raise ValueError("--sample-image is required for sift-query")
    output_dir = Path(args.output_dir)
    topk_path = output_dir / "topK_results.json"
    if not topk_path.exists():
        raise ValueError(f"topK_results_missing:{topk_path}")
    topk = _read_json(topk_path)
    rough_to_fine_scale = int(topk.get("rough_to_fine_scale", 4) or 4)
    hits = topk.get("hits", [])
    if not isinstance(hits, list):
        raise ValueError("topK_results hits must be a list")

    query_image, roi, query_keypoints, query_descriptors = _extract_query_sift(Path(args.sample_image))
    _write_image(output_dir / "sift_query_keypoints.png", _draw_query_keypoints(query_image, query_keypoints))
    rough_image = _load_rough_image_for_query(output_dir, Path(args.tile_root) if args.tile_root is not None else None)
    index = _load_sift_index(output_dir)
    descriptors = index["descriptors"]
    global_xy = index["global_xy"]

    results = []
    for hit in hits[: int(args.top_k)]:
        rank = int(hit.get("rank", len(results) + 1))
        candidate_id = str(hit.get("candidate", {}).get("window_id", f"candidate_{rank}"))
        indices = _candidate_feature_indices(global_xy, hit, rough_to_fine_scale)
        candidate_descriptors = descriptors[indices] if len(indices) else np.empty((0, 128), dtype=np.float32)
        candidate_global_xy = global_xy[indices] if len(indices) else np.empty((0, 2), dtype=np.float32)
        knn, good = _match_query_to_candidate(
            query_descriptors=query_descriptors,
            candidate_descriptors=candidate_descriptors,
        )
        estimate = _estimate_similarity_from_matches(
            query_keypoints,
            candidate_global_xy,
            good,
            query_width=int(query_image.shape[1]),
            query_height=int(query_image.shape[0]),
        )
        inlier_matches = estimate["inlier_matches"]
        inlier_count = len(inlier_matches)
        reason = "raw_evidence_only"
        if len(candidate_descriptors) == 0:
            reason = "no_candidate_features"
        elif len(query_descriptors) == 0:
            reason = "no_query_features"
        elif len(good) < 3:
            reason = "not_enough_good_matches"
        match_path = output_dir / f"sift_candidate_{rank:03d}_matches.png"
        inlier_path = output_dir / f"sift_candidate_{rank:03d}_inliers.png"
        patch_path = output_dir / f"sift_candidate_{rank:03d}_patch.png"
        keypoints_path = output_dir / f"sift_candidate_{rank:03d}_keypoints.png"
        candidate_patch = _candidate_patch_from_rough(rough_image, hit)
        candidate_keypoints = _candidate_keypoints_for_rough_patch(
            candidate_global_xy,
            hit,
            rough_to_fine_scale,
        )
        _write_image(patch_path, candidate_patch)
        _write_image(keypoints_path, _draw_candidate_keypoints(candidate_patch, candidate_keypoints))
        _write_match_image(
            match_path,
            query_image=query_image,
            query_keypoints=query_keypoints,
            candidate_patch=candidate_patch,
            candidate_keypoints=candidate_keypoints,
            matches=good,
            label=f"rank {rank} raw={len(knn)} good={len(good)}",
        )
        _write_match_image(
            inlier_path,
            query_image=query_image,
            query_keypoints=query_keypoints,
            candidate_patch=candidate_patch,
            candidate_keypoints=candidate_keypoints,
            matches=inlier_matches,
            label=f"rank {rank} inliers={inlier_count}",
        )
        results.append(
            {
                "candidate_id": candidate_id,
                "rank": rank,
                "raw_match_count": len(knn),
                "good_match_count": len(good),
                "inlier_count": inlier_count,
                "estimated_global_x": estimate["estimated_global_x"],
                "estimated_global_y": estimate["estimated_global_y"],
                "estimated_center_x": estimate["estimated_center_x"],
                "estimated_center_y": estimate["estimated_center_y"],
                "query_to_map_scale_x": estimate["query_to_map_scale_x"],
                "query_to_map_scale_y": estimate["query_to_map_scale_y"],
                "query_to_map_matrix": estimate["query_to_map_matrix"],
                "homography": None,
                "reason": reason,
                "candidate_feature_count": int(len(candidate_descriptors)),
                "candidate_patch_image": str(patch_path),
                "candidate_keypoints_image": str(keypoints_path),
                "match_image": str(match_path),
                "inlier_image": str(inlier_path),
            }
        )

    selected = _select_best_sift_candidate(results)
    payload = {
        "sample_image": str(args.sample_image),
        "roi": asdict(roi),
        "query_keypoint_count": len(query_keypoints),
        "results": results,
        "best_candidate_by_match_counts": selected,
        "human_confirmation_required": True,
    }
    (output_dir / "sift_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"sift_query_keypoints: {output_dir / 'sift_query_keypoints.png'}")
    print(f"sift_results: {output_dir / 'sift_results.json'}")
    for item in results:
        print(
            "sift_candidate "
            f"rank={item['rank']} raw={item['raw_match_count']} "
            f"good={item['good_match_count']} inliers={item['inlier_count']} "
            f"patch={item['candidate_patch_image']} "
            f"keypoints={item['candidate_keypoints_image']} "
            f"matches={item['match_image']} inliers_image={item['inlier_image']}"
        )
    print("Human confirmation is required before interpreting SIFT evidence.")


def _copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        raise ValueError(f"required_experiment_input_missing:{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _sample_images_from_args(args: argparse.Namespace) -> list[Path]:
    if args.sample_image is not None:
        return [Path(args.sample_image)]
    if args.sample_dir is None:
        raise ValueError("--sample-image or --sample-dir is required for full-experiment")
    sample_dir = Path(args.sample_dir)
    if not sample_dir.exists():
        raise ValueError(f"sample_dir_missing:{sample_dir}")
    if not sample_dir.is_dir():
        raise ValueError(f"sample_dir_not_directory:{sample_dir}")
    suffixes = {".png", ".jpg", ".jpeg", ".bmp"}
    samples = sorted(
        (
            path
            for path in sample_dir.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        ),
        key=lambda path: path.name,
    )
    if not samples:
        raise ValueError(f"no_sample_images_under:{sample_dir}")
    return samples


def _run_full_experiment_for_sample(args: argparse.Namespace, sample_image: Path, timestamp: str) -> Path:
    source_dir = Path(args.output_dir)
    sample_name = sample_image.stem
    bundle_dir = source_dir / timestamp / sample_name
    bundle_dir.mkdir(parents=True, exist_ok=True)

    for name in (
        "retrieval_index.npz",
        "retrieval_windows.json",
        "sift_features.npz",
        "sift_tiles.json",
        "sift_feature_count_by_tile.json",
    ):
        _copy_if_exists(source_dir / name, bundle_dir / name)

    bundle_args = argparse.Namespace(**vars(args))
    bundle_args.sample_image = sample_image
    bundle_args.output_dir = bundle_dir
    _write_run_config(bundle_args)
    _run_rough_query(bundle_args)
    _copy_if_exists(bundle_dir / "topK_contact_sheet.png", bundle_dir / "rough_topK_contact_sheet.png")
    _copy_if_exists(bundle_dir / "topK_results.json", bundle_dir / "rough_topK_results.json")
    _run_sift_query(bundle_args)
    sift_payload = _read_json(bundle_dir / "sift_results.json")
    sift_results = sift_payload.get("results", [])
    if not isinstance(sift_results, list):
        raise ValueError("sift_results results must be a list")
    review_manifest = {
        "human_confirmation_required": True,
        "script_made_success_decision": False,
        "sample_image": str(sample_image),
        "query_minimap": str(bundle_dir / "query_minimap.png"),
        "rough_topK_contact_sheet": str(bundle_dir / "rough_topK_contact_sheet.png"),
        "rough_topK_results": str(bundle_dir / "rough_topK_results.json"),
        "sift_query_keypoints": str(bundle_dir / "sift_query_keypoints.png"),
        "sift_results": str(bundle_dir / "sift_results.json"),
        "candidate_count": len(sift_results),
        "candidate_files": [
            {
                "rank": item.get("rank"),
                "raw_match_count": item.get("raw_match_count"),
                "good_match_count": item.get("good_match_count"),
                "inlier_count": item.get("inlier_count"),
                "candidate_patch_image": item.get("candidate_patch_image"),
                "candidate_keypoints_image": item.get("candidate_keypoints_image"),
                "match_image": item.get("match_image"),
                "inlier_image": item.get("inlier_image"),
                "reason": item.get("reason"),
            }
            for item in sift_results
        ],
    }
    (bundle_dir / "review_manifest.json").write_text(
        json.dumps(review_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    readme = (
        "This bundle is for human review.\n"
        "The script did not decide whether recognition succeeded.\n"
        "Please inspect rough_topK_contact_sheet.png and sift_candidate_* images.\n"
        "\n"
        "File guide:\n"
        "- query_minimap.png: cropped minimap image used as the query.\n"
        "- rough_topK_contact_sheet.png: rough retrieval candidates in rank order.\n"
        "- rough_topK_results.json: raw rough candidate metadata and scores.\n"
        "- sift_query_keypoints.png: query minimap with detected SIFT keypoints drawn.\n"
        "- sift_candidate_###_patch.png: candidate patch passed to SIFT visualization.\n"
        "- sift_candidate_###_keypoints.png: candidate patch with indexed SIFT keypoints drawn.\n"
        "- sift_candidate_###_matches.png: query-to-candidate good matches after ratio filtering.\n"
        "- sift_candidate_###_inliers.png: subset marked by the current translation-consistency filter.\n"
        "- sift_results.json: raw counts and file paths for each candidate.\n"
        "- review_manifest.json: machine-readable index of the review bundle.\n"
    )
    (bundle_dir / "README_FOR_USER_REVIEW.txt").write_text(readme, encoding="utf-8")

    rough_sheet = bundle_dir / "rough_topK_contact_sheet.png"
    rough_results = bundle_dir / "rough_topK_results.json"
    sift_results_path = bundle_dir / "sift_results.json"
    print(f"bundle_directory: {bundle_dir}")
    print(f"query_image: {bundle_dir / 'query_minimap.png'}")
    print(f"rough_topK_contact_sheet: {rough_sheet}")
    print(f"rough_topK_results: {rough_results}")
    print(f"SIFT_result_JSON: {sift_results_path}")
    print(f"review_manifest: {bundle_dir / 'review_manifest.json'}")
    for path in sorted(bundle_dir.glob("sift_candidate_*_matches.png")):
        print(f"SIFT_match_image: {path}")
    for path in sorted(bundle_dir.glob("sift_candidate_*_inliers.png")):
        print(f"SIFT_inlier_image: {path}")
    for path in sorted(bundle_dir.glob("sift_candidate_*_patch.png")):
        print(f"SIFT_candidate_patch: {path}")
    for path in sorted(bundle_dir.glob("sift_candidate_*_keypoints.png")):
        print(f"SIFT_candidate_keypoints: {path}")
    print("Human confirmation is required before interpreting this bundle.")
    return bundle_dir


def _run_full_experiment(args: argparse.Namespace) -> None:
    samples = _sample_images_from_args(args)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_dirs = [
        _run_full_experiment_for_sample(args, sample_image, timestamp)
        for sample_image in samples
    ]
    summary = {
        "human_confirmation_required": True,
        "script_made_success_decision": False,
        "sample_count": len(samples),
        "samples": [
            {
                "sample_image": str(sample),
                "bundle_dir": str(bundle_dir),
                "review_manifest": str(bundle_dir / "review_manifest.json"),
            }
            for sample, bundle_dir in zip(samples, bundle_dirs)
        ],
    }
    summary_path = Path(args.output_dir) / timestamp / "batch_review_manifest.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"batch_review_manifest: {summary_path}")
    print("Human confirmation is required before interpreting any batch bundle.")


def _parse_tile_key_from_cache_path(cache_root: Path, path: Path) -> TileKey | None:
    try:
        rel = path.relative_to(cache_root)
    except ValueError:
        return None
    if len(rel.parts) == 1:
        match = re.fullmatch(r"(?:(-?\d+)_(-?\d+)_)?(-?\d+)_(-?\d+)\.png", rel.parts[0])
        if not match:
            return None
        area_id = match.group(1) or path.parent.parent.name
        layer_id = match.group(2) or path.parent.name
        return TileKey(
            area_id=area_id,
            layer_id=layer_id,
            z_level=None,
            kind="standard",
            x=int(match.group(3)),
            y=int(match.group(4)),
        )
    if len(rel.parts) != 5:
        return None
    area_id, kind, layer_id, z_part, name = rel.parts
    match = re.fullmatch(r"(-?\d+)_(-?\d+)\.png", name)
    if not match:
        return None
    z_level = None if z_part == "base" else int(z_part)
    return TileKey(
        area_id=area_id,
        layer_id=layer_id,
        z_level=z_level,
        kind=kind,
        x=int(match.group(1)),
        y=int(match.group(2)),
    )


def _scan_cache_tile_keys(cache_root: Path, *, kind: str = "standard") -> list[TileKey]:
    keys: list[TileKey] = []
    for path in sorted(Path(cache_root).glob("**/*.png")):
        key = _parse_tile_key_from_cache_path(Path(cache_root), path)
        if key is not None and key.kind == kind:
            keys.append(key)
    return keys


def _write_sift_index(
    output_dir: Path,
    *,
    records,
    tile_counts: dict[str, int],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if records:
        descriptors = np.stack([record.descriptor for record in records]).astype(np.float32)
        global_xy = np.array([[record.global_x, record.global_y] for record in records], dtype=np.float32)
        tile_xy = np.array([[record.tile_x, record.tile_y] for record in records], dtype=np.int32)
        response = np.array([record.response for record in records], dtype=np.float32)
        size = np.array([record.size for record in records], dtype=np.float32)
        angle = np.array([record.angle for record in records], dtype=np.float32)
    else:
        descriptors = np.empty((0, 128), dtype=np.float32)
        global_xy = np.empty((0, 2), dtype=np.float32)
        tile_xy = np.empty((0, 2), dtype=np.int32)
        response = np.empty((0,), dtype=np.float32)
        size = np.empty((0,), dtype=np.float32)
        angle = np.empty((0,), dtype=np.float32)
    np.savez_compressed(
        output_dir / "sift_features.npz",
        descriptors=descriptors,
        global_xy=global_xy,
        tile_xy=tile_xy,
        response=response,
        size=size,
        angle=angle,
    )
    (output_dir / "sift_feature_count_by_tile.json").write_text(
        json.dumps(tile_counts, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tiles_payload = {
        "tile_count": len(tile_counts),
        "feature_count": int(len(records)),
        "human_confirmation_required": True,
        "tiles": [
            {"tile": name, "feature_count": count}
            for name, count in sorted(tile_counts.items())
        ],
    }
    (output_dir / "sift_tiles.json").write_text(
        json.dumps(tiles_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_sift_index(args: argparse.Namespace) -> None:
    if args.tile_root is None:
        raise ValueError("--tile-root is required for sift-index")
    cache_root = Path(args.tile_root)
    output_dir = Path(args.output_dir)
    keys = _scan_cache_tile_keys(cache_root, kind="standard")
    if not keys:
        raise ValueError(f"no_standard_tile_pngs_under:{cache_root}")
    windows_path = Path(args.output_dir) / "retrieval_windows.json"
    if not windows_path.exists():
        raise ValueError(f"retrieval_windows_missing_for_stitched_origin:{windows_path}")
    windows_data = _read_json(windows_path)
    origin_tile_x = windows_data.get("origin_tile_x")
    origin_tile_y = windows_data.get("origin_tile_y")
    if origin_tile_x is None or origin_tile_y is None:
        raise ValueError("retrieval_windows_missing_origin_tile_x_or_y")
    origin_tile_x = int(origin_tile_x)
    origin_tile_y = int(origin_tile_y)

    records = []
    tile_counts: dict[str, int] = {}
    debug_images: list[np.ndarray] = []
    debug_labels: list[str] = []
    tile_size = 1024
    for key in keys:
        expanded = compose_expanded_tile_from_cache(
            cache_root=cache_root,
            key=key,
            tile_size=tile_size,
            overlap=int(args.sift_overlap),
        )
        tile_records = extract_owned_sift_features_from_expanded_tile(
            region_id=key.area_id,
            tile_x=key.x,
            tile_y=key.y,
            expanded_bgr=expanded,
            tile_size=tile_size,
            overlap=int(args.sift_overlap),
            origin_tile_x=origin_tile_x,
            origin_tile_y=origin_tile_y,
        )
        records.extend(tile_records)
        tile_name = f"{key.area_id}/{key.kind}/{key.layer_id}/{key.z_level if key.z_level is not None else 'base'}/{key.x}_{key.y}"
        tile_counts[tile_name] = len(tile_records)
        if len(debug_images) < 36:
            debug_images.append(expanded)
            debug_labels.append(f"{key.x},{key.y}:{len(tile_records)}")

    _write_sift_index(output_dir, records=records, tile_counts=tile_counts)
    _write_image(
        output_dir / "sift_tile_debug_contact_sheet.png",
        _make_image_contact_sheet(debug_images, labels=debug_labels),
    )
    print(f"sift_features: {output_dir / 'sift_features.npz'}")
    print(f"sift_tiles: {output_dir / 'sift_tiles.json'}")
    print(f"sift_feature_count_by_tile: {output_dir / 'sift_feature_count_by_tile.json'}")
    print(f"sift_tile_debug_contact_sheet: {output_dir / 'sift_tile_debug_contact_sheet.png'}")
    print("Human confirmation is required before interpreting SIFT feature counts or debug images.")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    print(BANNER)
    config_path = _write_run_config(args)
    print(f"run_config: {config_path}")
    if args.mode == "rough-index":
        _run_rough_index(args)
    elif args.mode == "rough-query":
        _run_rough_query(args)
    elif args.mode == "sift-index":
        _run_sift_index(args)
    elif args.mode == "sift-query":
        _run_sift_query(args)
    elif args.mode == "full-experiment":
        _run_full_experiment(args)
    else:
        print(f"mode_not_implemented_yet: {args.mode}")
    print("No production visual validation was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
