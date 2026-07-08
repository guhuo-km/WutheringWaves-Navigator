#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline debug harness for one screenshot frame.

This script consumes a provided image path. It does not capture the live game
window, so it cannot interfere with the main application screenshot path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.map_context import CoordinateCandidate, MapContext  # noqa: E402
from coordinate_continuity import ContinuityState  # noqa: E402
from minimap_frame_package import read_minimap_frame_package  # noqa: E402
from minimap_observation_pipeline import run_observation_paths  # noqa: E402
from minimap_legacy_tiles import import_legacy_tile_tree  # noqa: E402
from minimap_roi import (  # noqa: E402
    MinimapRoi,
    build_minimap_texture_match_mask,
    crop_minimap_from_frame,
    detect_minimap_circle_roi,
    normalize_minimap_crop,
)
from minimap_stitched_resources import StitchedResourceBuilder  # noqa: E402
from minimap_tile_downloader import download_missing_tiles, generate_standard_tile_inputs_for_game_xy  # noqa: E402


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _read_image(path: str | Path):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _load_map_context(data: dict[str, Any] | None) -> MapContext | None:
    if data is None:
        return None
    tile_projection = data.get("tileProjection") if isinstance(data.get("tileProjection"), dict) else {}
    map_units_per_tile_x = tile_projection.get("mapUnitsPerTileX")
    map_units_per_tile_y = tile_projection.get("mapUnitsPerTileY")
    if "areaId" in data:
        return MapContext(
            area_id=str(data["areaId"]),
            layer_id=str(data.get("layerId", "default")),
            tile_size=int(data.get("tileSize", 1024)),
            coord_transform=dict(data.get("coordTransform") or {}),
            map_units_per_tile_x=float(map_units_per_tile_x) if map_units_per_tile_x is not None else None,
            map_units_per_tile_y=float(map_units_per_tile_y) if map_units_per_tile_y is not None else None,
        )
    if "area_id" in data:
        return MapContext(
            area_id=str(data["area_id"]),
            layer_id=str(data.get("layer_id", "default")),
            tile_size=int(data.get("tile_size", 1024)),
            coord_transform=dict(data.get("coord_transform") or {}),
            map_units_per_tile_x=float(data["map_units_per_tile_x"]) if data.get("map_units_per_tile_x") is not None else None,
            map_units_per_tile_y=float(data["map_units_per_tile_y"]) if data.get("map_units_per_tile_y") is not None else None,
        )
    return None


def _load_roi(data: dict[str, Any] | None) -> MinimapRoi | None:
    if data is None:
        return None
    return MinimapRoi(
        x=int(data["x"]),
        y=int(data["y"]),
        width=int(data["width"]),
        height=int(data["height"]),
        shape=str(data.get("shape", "circle")),
        source=str(data.get("source", "manual")),
    )


def _load_coordinate_candidate(data: dict[str, Any] | None) -> CoordinateCandidate | None:
    if data is None:
        return None
    if data.get("x") is None or data.get("y") is None:
        return None
    return CoordinateCandidate(
        int(data["x"]),
        int(data["y"]),
        int(data["z"]) if data.get("z") is not None else None,
        source=str(data.get("source", "ocr")),
        confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
        reason=str(data.get("reason", "")),
    )


def _auto_detect_roi(frame) -> MinimapRoi | None:
    frame_height, frame_width = frame.shape[:2]
    search_rect = (0, 0, max(1, int(frame_width / 8)), max(1, int(frame_height / 4)))
    return detect_minimap_circle_roi(frame, search_rect)


def _safe_debug_stem(image_path: Path) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", image_path.stem).strip("_") or "sample"


def _write_roi_debug_images(
    frame,
    roi: MinimapRoi,
    normalized,
    output_dir: Path,
    stem: str,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay = frame.copy()
    cv2.rectangle(overlay, (roi.x, roi.y), (roi.x + roi.width, roi.y + roi.height), (0, 255, 255), 2)
    center = (roi.x + roi.width // 2, roi.y + roi.height // 2)
    axes = (max(1, roi.width // 2), max(1, roi.height // 2))
    if roi.shape == "ellipse":
        cv2.ellipse(overlay, center, axes, 0, 0, 360, (0, 255, 0), 2)
    else:
        cv2.circle(overlay, center, max(1, min(roi.width, roi.height) // 2), (0, 255, 0), 2)

    crop = crop_minimap_from_frame(frame, roi)
    masked_rgb = cv2.bitwise_and(normalized.exact_image, normalized.exact_image, mask=normalized.mask)
    masked = cv2.cvtColor(masked_rgb, cv2.COLOR_BGR2BGRA)
    masked[:, :, 3] = normalized.mask
    outputs = [
        output_dir / f"{stem}_roi_overlay.png",
        output_dir / f"{stem}_roi_crop.png",
        output_dir / f"{stem}_roi_masked.png",
    ]
    for path, image in zip(outputs, (overlay, crop, masked)):
        if not cv2.imwrite(str(path), image):
            raise ValueError(f"roi_debug_image_write_failed:{path}")
    return outputs


def _crop_image_with_padding(image, left: int, top: int, width: int, height: int):
    if image.ndim == 2:
        canvas = np.zeros((height, width), dtype=image.dtype)
    else:
        canvas = np.zeros((height, width, image.shape[2]), dtype=image.dtype)
    src_left = max(0, left)
    src_top = max(0, top)
    src_right = min(image.shape[1], left + width)
    src_bottom = min(image.shape[0], top + height)
    if src_right <= src_left or src_bottom <= src_top:
        return canvas
    dst_left = src_left - left
    dst_top = src_top - top
    canvas[dst_top:dst_top + (src_bottom - src_top), dst_left:dst_left + (src_right - src_left)] = image[src_top:src_bottom, src_left:src_right]
    return canvas


def _draw_rect(image, left: int, top: int, right: int, bottom: int, color: tuple[int, int, int], thickness: int = 2):
    if image.ndim == 2:
        canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        canvas = image.copy()
    cv2.rectangle(canvas, (int(left), int(top)), (int(right), int(bottom)), color, thickness)
    return canvas


def _write_image_or_fail(path: Path, image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise ValueError(f"debug_image_write_failed:{path}")


def _relative_debug_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_coordinate_filename(path: str | Path) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(-?\d+),(-?\d+),(-?\d+)", Path(path).stem)
    if not match:
        return None
    return tuple(int(value) for value in match.groups())


def format_report(result: dict[str, Any]) -> str:
    visual_result = result.get("visual_result")
    visual_lines: list[str] = []
    if isinstance(visual_result, dict):
        manifest = visual_result.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        visual_lines.append(
            f"visual match: area={manifest.get('area_id')} type={manifest.get('candidate_type')} "
            f"layer={manifest.get('layer_id')} z={manifest.get('z_level')}"
        )
        for name in ("rough", "exact"):
            evidence = visual_result.get(name)
            if isinstance(evidence, dict):
                visual_lines.append(
                    f"{name}: location={evidence.get('location')} "
                    f"confidence={evidence.get('normalized_confidence')}"
                )
    lines = [
        "=== Minimap observation debug report ===",
        f"OCR candidate: {result.get('ocr_candidate')}",
        f"minimap ROI: {result.get('minimap_roi')}",
        f"normalized minimap size: {result.get('normalized_minimap_size')}",
        f"visual candidate: {result.get('visual_candidate')}",
        *visual_lines,
        f"heading candidate: {result.get('heading_candidate')}",
        f"heading failure reason: {result.get('heading_failure_reason')}",
        f"continuity status: {result.get('continuity_status')}",
        f"decision: {result.get('decision')}",
        "=== end ===",
    ]
    return "\n".join(lines)


def _prepare_legacy_stitched_resources(args: argparse.Namespace, map_context: MapContext | None) -> int:
    if not args.legacy_tile_tree:
        return 0
    if map_context is None:
        print("ERROR: --legacy-tile-tree requires --map-context-json", file=sys.stderr)
        return 1
    if not args.tile_root:
        print("ERROR: --legacy-tile-tree requires --tile-root as stitched output root", file=sys.stderr)
        return 1
    if not args.legacy_cache_root:
        print("ERROR: --legacy-tile-tree requires --legacy-cache-root for imported cache files", file=sys.stderr)
        return 1

    imported = import_legacy_tile_tree(
        Path(args.legacy_tile_tree),
        Path(args.legacy_cache_root),
        map_context.area_id,
        include_layered=not args.legacy_base_only,
    )
    standard_keys = [key for key in imported if key.kind == "standard"]
    if not standard_keys:
        print(f"ERROR: legacy tile tree has no standard tiles for area {map_context.area_id}", file=sys.stderr)
        return 1

    builder = StitchedResourceBuilder(
        Path(args.legacy_cache_root),
        Path(args.tile_root),
        tile_size=map_context.tile_size,
    )
    manifests = [builder.publish_base_region(map_context, standard_keys)]

    layer_groups: dict[tuple[str, int], list] = {}
    for key in imported:
        if key.kind != "layered":
            continue
        z_level = 0 if key.z_level is None else int(key.z_level)
        layer_groups.setdefault((key.layer_id, z_level), []).append(key)
    for (layer_id, z_level), layer_keys in sorted(layer_groups.items()):
        manifests.append(
            builder.publish_layered_candidate(
                map_context,
                standard_keys,
                layer_keys,
                candidate_type="layered",
                layer_id=layer_id,
                z_level=z_level,
            )
        )

    print(f"legacy stitched resources: imported {len(imported)} tiles, published {len(manifests)} manifests")
    return 0


def _prepare_current_stitched_resources(
    args: argparse.Namespace,
    map_context: MapContext | None,
    ocr_candidate: CoordinateCandidate | None,
) -> int:
    if not args.current_tile_base_url:
        return 0
    if map_context is None:
        print("ERROR: --current-tile-base-url requires --map-context-json", file=sys.stderr)
        return 1
    if ocr_candidate is None:
        print("ERROR: --current-tile-base-url requires OCR XY from --ocr-from-filename or --ocr-x/--ocr-y", file=sys.stderr)
        return 1
    if not args.current_cache_root:
        print("ERROR: --current-tile-base-url requires --current-cache-root", file=sys.stderr)
        return 1
    if not args.tile_root:
        print("ERROR: --current-tile-base-url requires --tile-root as stitched output root", file=sys.stderr)
        return 1

    inputs = generate_standard_tile_inputs_for_game_xy(
        map_context.area_id,
        ocr_candidate.as_xy_tuple(),
        map_context.coord_transform,
        map_context.tile_size,
        args.current_tile_base_url,
        oss_params=args.current_oss_params,
        radius=int(args.current_tile_radius),
    )
    result = download_missing_tiles(inputs, Path(args.current_cache_root))
    if result.failures:
        print(f"ERROR: current tile download failed for {len(result.failures)} tiles", file=sys.stderr)
        return 1

    standard_keys = [item.key for item in inputs if item.key.kind == "standard"]
    builder = StitchedResourceBuilder(
        Path(args.current_cache_root),
        Path(args.tile_root),
        tile_size=map_context.tile_size,
    )
    manifest = builder.publish_base_region(map_context, standard_keys)
    print(
        "current stitched resources: "
        f"tiles={len(standard_keys)} downloaded={len(result.downloaded_sizes)} "
        f"manifest={manifest.manifest_path}"
    )
    return 0


def _run_one_image(image_path: Path, args: argparse.Namespace, package_data: dict[str, Any] | None = None) -> int:
    frame = _read_image(image_path)
    if frame is None or frame.size == 0:
        print(f"ERROR: could not decode image: {image_path}", file=sys.stderr)
        return 1

    map_context = _load_map_context(_load_json(args.map_context_json))
    if map_context is None and package_data is not None:
        map_context = _load_map_context(package_data.get("mapContext"))
    roi = _load_roi(_load_json(args.roi_json))
    if roi is None and package_data is not None:
        roi = _load_roi(package_data.get("roi"))
    if roi is None and args.auto_roi:
        roi = _auto_detect_roi(frame)
    tile_root = Path(args.tile_root) if args.tile_root else None
    if tile_root is None and package_data is not None and package_data.get("tileRoot"):
        tile_root = Path(str(package_data["tileRoot"]))
    prepare_exit = _prepare_legacy_stitched_resources(args, map_context)
    if prepare_exit != 0:
        return prepare_exit

    ocr_candidate = _load_coordinate_candidate(package_data.get("ocrCandidate")) if package_data is not None else None
    ocr_x = args.ocr_x
    ocr_y = args.ocr_y
    ocr_z = args.ocr_z
    if args.ocr_from_filename:
        parsed = _parse_coordinate_filename(image_path)
        if parsed is None:
            print(f"ERROR: image filename is not X,Y,Z: {image_path.name}", file=sys.stderr)
            return 1
        ocr_x, ocr_y, ocr_z = parsed
    if ocr_x is not None and ocr_y is not None:
        ocr_candidate = CoordinateCandidate(ocr_x, ocr_y, ocr_z, source="ocr")

    prepare_current_exit = _prepare_current_stitched_resources(args, map_context, ocr_candidate)
    if prepare_current_exit != 0:
        return prepare_current_exit

    if roi is not None and args.roi_debug_dir:
        crop = crop_minimap_from_frame(frame, roi)
        normalized = normalize_minimap_crop(crop, roi.shape)
        written = _write_roi_debug_images(
            frame,
            roi,
            normalized,
            Path(args.roi_debug_dir),
            _safe_debug_stem(image_path),
        )
        print(f"roi debug images: {[str(path) for path in written]}")

    continuity = ContinuityState()
    if args.previous_x is not None and args.previous_y is not None:
        continuity.accept((args.previous_x, args.previous_y, args.previous_z))

    result = run_observation_paths(
        frame,
        map_context=map_context,
        roi=roi,
        tile_root=tile_root,
        ocr_candidate=ocr_candidate,
        continuity=continuity,
    )
    print(format_report(result))
    return 0


def _iter_image_paths(args: argparse.Namespace) -> list[Path]:
    if args.frame_package:
        package = read_minimap_frame_package(args.frame_package)
        return [Path(str(package["framePath"]))]
    if args.sample_dir:
        return sorted(Path(args.sample_dir).glob("*.png"))
    if args.image:
        return [Path(args.image)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug minimap localization on one screenshot or sample directory")
    parser.add_argument("--image")
    parser.add_argument("--sample-dir")
    parser.add_argument("--frame-package")
    parser.add_argument("--map-context-json")
    parser.add_argument("--roi-json")
    parser.add_argument("--roi-debug-dir")
    parser.add_argument("--visual-debug-dir")
    parser.add_argument("--visual-trace-dir")
    parser.add_argument("--auto-roi", action="store_true")
    parser.add_argument("--tile-root")
    parser.add_argument("--legacy-tile-tree")
    parser.add_argument("--legacy-cache-root")
    parser.add_argument("--legacy-base-only", action="store_true")
    parser.add_argument("--current-tile-base-url")
    parser.add_argument("--current-oss-params")
    parser.add_argument("--current-cache-root")
    parser.add_argument("--current-tile-radius", type=int, default=1)
    parser.add_argument("--ocr-x", type=int)
    parser.add_argument("--ocr-y", type=int)
    parser.add_argument("--ocr-z", type=int, default=0)
    parser.add_argument("--ocr-from-filename", action="store_true")
    parser.add_argument("--previous-x", type=int)
    parser.add_argument("--previous-y", type=int)
    parser.add_argument("--previous-z", type=int, default=0)
    args = parser.parse_args(argv)

    image_paths = _iter_image_paths(args)
    if not image_paths:
        print("ERROR: provide --image or --sample-dir with at least one PNG image", file=sys.stderr)
        return 1

    package_data = read_minimap_frame_package(args.frame_package) if args.frame_package else None
    for image_path in image_paths:
        if args.sample_dir:
            print(f"sample image: {image_path}")
        if args.frame_package:
            print(f"frame package: {package_data.get('packagePath') if package_data else args.frame_package}")
        exit_code = _run_one_image(image_path, args, package_data)
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
