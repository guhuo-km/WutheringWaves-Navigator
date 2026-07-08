from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import hashlib
import json
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from core.map_context import CoordinateCandidate, MapContext, TileKey
from minimap_index_store import MinimapIndexStore
from minimap_coordinate_transform import game_xy_to_stitched_pixel, stitched_pixel_to_game_xy
from minimap_retrieval_index import CandidateDescriptor, CandidateWindow, build_candidate_windows, compute_hsv_texture_descriptor, retrieve_top_k
from minimap_sift_index import create_sift_detector, extract_owned_sift_features_from_expanded_tile, resolve_tile_image_path
from minimap_sift_matcher import estimate_similarity_from_matches, filter_ratio_matches, select_best_sift_candidate
from minimap_stitched_resources import StitchedManifest
from minimap_tile_index_state import TileIndexStateStore, TileIndexStatus, canonical_tile_key, parse_canonical_tile_key


@dataclass(frozen=True)
class VisualMatchEvidence:
    location: tuple[int, int]
    raw_score: float
    normalized_confidence: float
    threshold: float


@dataclass(frozen=True)
class VisualLocalizationResult:
    candidate: CoordinateCandidate
    manifest: StitchedManifest
    rough: VisualMatchEvidence
    exact: VisualMatchEvidence
    sift: dict[str, Any] | None = None


@dataclass(frozen=True)
class VisualMatchConfig:
    rough_candidate_limit: int = 20
    sift_min_inliers: int = 3
    sift_ratio: float = 0.75
    sift_window_size: int = 512
    sift_stride: int = 256


class MinimapVisualLocator:
    _GLOBAL_TILE_SIFT_CACHE: dict[tuple, dict[str, np.ndarray]] = {}
    _GLOBAL_ROUGH_DESCRIPTOR_CACHE: dict[tuple[str, int, int, int, int], list[CandidateDescriptor]] = {}
    _GLOBAL_TILE_ROUGH_ENTRIES_CACHE: dict[tuple, list[dict[str, Any]]] = {}
    _GLOBAL_EXISTING_SIFT_ARRAY_CACHE: dict[tuple, dict[str, np.ndarray]] = {}

    def __init__(self, tile_root: Path, config: VisualMatchConfig | None = None):
        self.tile_root = Path(tile_root)
        self.config = config or VisualMatchConfig()
        self.last_trace: dict[str, Any] = {"manifests": []}
        self._last_rough_index_source = ""
        self._last_sift_index_source = ""

    def search_root(self, context: MapContext) -> Path:
        return self.tile_root / context.area_id / context.layer_id

    def _manifest_paths(self, context: MapContext) -> list[Path]:
        area_root = self.tile_root / context.area_id
        if not area_root.exists():
            return []
        return sorted(area_root.glob("*/manifest.json"))

    def _load_manifest(self, path: Path) -> StitchedManifest:
        return StitchedManifest(**json.loads(path.read_text(encoding="utf-8")))

    def _index_root(self, area_id: str) -> Path:
        root = self.tile_root / str(area_id) / "indexes"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def _file_stamp(self, path: Path) -> dict[str, int | str]:
        try:
            stat = path.stat()
            return {"path": str(path), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except OSError:
            return {"path": str(path), "mtime_ns": 0, "size": 0}

    def _file_stamp_tuple(self, path: Path) -> tuple[str, int, int]:
        stamp = self._file_stamp(path)
        return (str(stamp["path"]), int(stamp["mtime_ns"]), int(stamp["size"]))

    def _write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _write_npz_atomic(self, path: Path, **arrays) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(path)

    def _manifest_can_match(
        self,
        manifest: StitchedManifest,
        active_game_xy: tuple[int | float, int | float] | None,
    ) -> bool:
        if manifest.candidate_type == "base":
            return True
        if active_game_xy is None:
            return False
        bounds = (
            manifest.active_pixel_left,
            manifest.active_pixel_top,
            manifest.active_pixel_right,
            manifest.active_pixel_bottom,
        )
        if any(value is None for value in bounds):
            return False
        pixel_x, pixel_y = game_xy_to_stitched_pixel(manifest, active_game_xy[0], active_game_xy[1])
        left, top, right, bottom = (float(value) for value in bounds)
        return left <= pixel_x < right and top <= pixel_y < bottom

    def _query_color_and_mask(
        self,
        normalized_minimap_image: Any,
        minimap_mask: Any,
    ) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint8]]:
        exact_source = getattr(normalized_minimap_image, "exact_image", normalized_minimap_image)
        image = np.asarray(exact_source)
        if image.ndim == 2:
            color = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            color = image[:, :, :3]
        return color, np.asarray(minimap_mask, dtype=np.uint8)

    def _rough_retrieval_hits(
        self,
        *,
        manifest: StitchedManifest,
        rough: npt.NDArray[np.uint8],
        query_color: npt.NDArray[np.uint8],
        query_mask: npt.NDArray[np.uint8],
    ):
        rough_h, rough_w = rough.shape[:2]
        window_size = min(max(1, int(self.config.sift_window_size)), rough_w, rough_h)
        stride = min(max(1, int(self.config.sift_stride)), window_size)
        rough_path = self.tile_root / manifest.rough_color_path
        try:
            stat = rough_path.stat()
            descriptor_key = (
                str(rough_path),
                int(stat.st_mtime_ns),
                int(stat.st_size),
                int(window_size),
                int(stride),
            )
        except OSError:
            descriptor_key = (str(rough_path), 0, int(rough.size), int(window_size), int(stride))
        cached_descriptors = self._GLOBAL_ROUGH_DESCRIPTOR_CACHE.get(descriptor_key)
        if cached_descriptors is not None:
            self._last_rough_index_source = "memory"
            query_vector = compute_hsv_texture_descriptor(query_color, mask=query_mask)
            return retrieve_top_k(
                query_vector,
                cached_descriptors,
                top_k=max(1, int(self.config.rough_candidate_limit)),
            )
        persisted_descriptors = self._load_persisted_rough_descriptors(
            manifest=manifest,
            rough_path=rough_path,
            rough_shape=rough.shape,
            window_size=window_size,
            stride=stride,
        )
        if persisted_descriptors is not None:
            self._last_rough_index_source = "disk"
            self._GLOBAL_ROUGH_DESCRIPTOR_CACHE[descriptor_key] = persisted_descriptors
            query_vector = compute_hsv_texture_descriptor(query_color, mask=query_mask)
            return retrieve_top_k(
                query_vector,
                persisted_descriptors,
                top_k=max(1, int(self.config.rough_candidate_limit)),
            )
        rough_tile_size = max(1, int(manifest.tile_size) // max(1, int(manifest.rough_downsample)))
        self._last_rough_index_source = "rebuilt"
        windows = build_candidate_windows(
            region_id=manifest.area_id,
            map_left=0,
            map_top=0,
            map_width=rough_w,
            map_height=rough_h,
            window_size=window_size,
            stride=stride,
            tile_size=rough_tile_size,
        )
        descriptors: list[CandidateDescriptor] = []
        for window in windows:
            patch = rough[window.top:window.top + window.height, window.left:window.left + window.width]
            if patch.shape[:2] != (window.height, window.width):
                continue
            descriptors.append(CandidateDescriptor(window, compute_hsv_texture_descriptor(patch)))
        self._GLOBAL_ROUGH_DESCRIPTOR_CACHE[descriptor_key] = descriptors
        self._persist_rough_descriptors(
            manifest=manifest,
            rough_path=rough_path,
            rough_shape=rough.shape,
            window_size=window_size,
            stride=stride,
            descriptors=descriptors,
        )
        if not descriptors:
            return []
        query_vector = compute_hsv_texture_descriptor(query_color, mask=query_mask)
        return retrieve_top_k(query_vector, descriptors, top_k=max(1, int(self.config.rough_candidate_limit)))

    def _rough_index_payload(
        self,
        *,
        manifest: StitchedManifest,
        rough_path: Path,
        rough_shape: tuple[int, ...],
        window_size: int,
        stride: int,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "index_type": "rough",
            "area_id": manifest.area_id,
            "candidate_type": manifest.candidate_type,
            "layer_id": manifest.layer_id,
            "z_level": manifest.z_level,
            "tile_size": manifest.tile_size,
            "rough_downsample": manifest.rough_downsample,
            "rough_shape": [int(value) for value in rough_shape],
            "window_size": int(window_size),
            "stride": int(stride),
            "rough_file": self._file_stamp(rough_path),
        }

    def _rough_index_paths(
        self,
        *,
        manifest: StitchedManifest,
        rough_path: Path,
        rough_shape: tuple[int, ...],
        window_size: int,
        stride: int,
    ) -> tuple[Path, Path, dict[str, Any]]:
        payload = self._rough_index_payload(
            manifest=manifest,
            rough_path=rough_path,
            rough_shape=rough_shape,
            window_size=window_size,
            stride=stride,
        )
        digest = self._hash_payload(payload)
        root = self._index_root(manifest.area_id)
        return root / f"rough_{digest}.npz", root / f"rough_{digest}.json", payload

    def _load_persisted_rough_descriptors(
        self,
        *,
        manifest: StitchedManifest,
        rough_path: Path,
        rough_shape: tuple[int, ...],
        window_size: int,
        stride: int,
    ) -> list[CandidateDescriptor] | None:
        npz_path, json_path, payload = self._rough_index_paths(
            manifest=manifest,
            rough_path=rough_path,
            rough_shape=rough_shape,
            window_size=window_size,
            stride=stride,
        )
        if not npz_path.exists() or not json_path.exists():
            return None
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        if meta.get("payload") != payload:
            return None
        data = np.load(npz_path)
        vectors = data["vectors"].astype(np.float32)
        windows = meta.get("windows", [])
        if len(windows) != len(vectors):
            return None
        return [CandidateDescriptor(CandidateWindow(**window), vectors[index]) for index, window in enumerate(windows)]

    def _persist_rough_descriptors(
        self,
        *,
        manifest: StitchedManifest,
        rough_path: Path,
        rough_shape: tuple[int, ...],
        window_size: int,
        stride: int,
        descriptors: list[CandidateDescriptor],
    ) -> None:
        npz_path, json_path, payload = self._rough_index_paths(
            manifest=manifest,
            rough_path=rough_path,
            rough_shape=rough_shape,
            window_size=window_size,
            stride=stride,
        )
        vectors = (
            np.vstack([item.vector.astype(np.float32) for item in descriptors])
            if descriptors
            else np.empty((0, 0), dtype=np.float32)
        )
        windows = [item.candidate.__dict__ for item in descriptors]
        self._write_npz_atomic(npz_path, vectors=vectors)
        self._write_json_atomic(json_path, {"payload": payload, "windows": windows})

    def _tile_kind_for_manifest(self, manifest: StitchedManifest) -> str:
        return "standard" if manifest.candidate_type == "base" else manifest.candidate_type

    def _tile_keys_for_rough_hit(self, manifest: StitchedManifest, hit) -> list[TileKey]:
        scale = max(1, int(manifest.rough_downsample))
        left = int(hit.candidate.left) * scale
        top = int(hit.candidate.top) * scale
        right = left + int(hit.candidate.width) * scale
        bottom = top + int(hit.candidate.height) * scale
        tile_size = max(1, int(manifest.tile_size))
        min_col = max(0, left // tile_size)
        max_col = min(max(0, int(np.ceil(manifest.width / tile_size)) - 1), (right - 1) // tile_size)
        min_row = max(0, top // tile_size)
        max_row = min(max(0, int(np.ceil(manifest.height / tile_size)) - 1), (bottom - 1) // tile_size)
        kind = self._tile_kind_for_manifest(manifest)
        layer_id = "default" if kind == "standard" else manifest.layer_id
        z_level = None if kind == "standard" else manifest.z_level
        keys: list[TileKey] = []
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                keys.append(
                    TileKey(
                        area_id=manifest.area_id,
                        layer_id=layer_id,
                        z_level=z_level,
                        kind=kind,
                        x=int(manifest.origin_tile_x + col),
                        y=int(manifest.origin_tile_y - row),
                    )
                )
        return keys

    def _read_tile_image_or_blank(self, key: TileKey, tile_size: int) -> npt.NDArray[np.uint8]:
        path = resolve_tile_image_path(self.tile_root, key)
        image = None
        if path.exists():
            data = np.fromfile(str(path), dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if image is None:
            return np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        if image.shape[:2] != (tile_size, tile_size):
            image = cv2.resize(image, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
        return image[:, :, :3]

    def _read_candidate_tile_or_blank(self, manifest: StitchedManifest, key: TileKey, tile_size: int) -> npt.NDArray[np.uint8]:
        if manifest.candidate_type == "base":
            return self._read_tile_image_or_blank(key, tile_size)
        base_key = TileKey(
            area_id=key.area_id,
            layer_id="default",
            z_level=None,
            kind="standard",
            x=key.x,
            y=key.y,
        )
        base = self._read_tile_image_or_blank(base_key, tile_size)
        layer_path = resolve_tile_image_path(self.tile_root, key)
        layer = None
        if layer_path.exists():
            data = np.fromfile(str(layer_path), dtype=np.uint8)
            layer = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if layer is None:
            return np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
        if layer.shape[:2] != (tile_size, tile_size):
            layer = cv2.resize(layer, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
        if layer.ndim == 2:
            return cv2.cvtColor(layer, cv2.COLOR_GRAY2BGR)
        if layer.shape[2] == 4:
            layer_bgr = layer[:, :, :3].astype(np.float32)
            alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
            return np.clip(layer_bgr * alpha + base.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)
        return layer[:, :, :3]

    def _compose_expanded_candidate_tile(
        self,
        manifest: StitchedManifest,
        key: TileKey,
        *,
        allowed_neighbor_xy: set[tuple[int, int]] | None,
        overlap: int,
    ) -> npt.NDArray[np.uint8]:
        tile_size = int(manifest.tile_size)
        canvas = np.zeros((tile_size * 3, tile_size * 3, 3), dtype=np.uint8)
        origin_y = key.y + 1
        for nx in range(key.x - 1, key.x + 2):
            for ny in range(key.y - 1, key.y + 2):
                if (nx, ny) != (key.x, key.y) and allowed_neighbor_xy is not None and (nx, ny) not in allowed_neighbor_xy:
                    continue
                neighbor = TileKey(
                    area_id=key.area_id,
                    layer_id=key.layer_id,
                    z_level=key.z_level,
                    kind=key.kind,
                    x=nx,
                    y=ny,
                )
                tile = self._read_candidate_tile_or_blank(manifest, neighbor, tile_size)
                left = (nx - (key.x - 1)) * tile_size
                top = (origin_y - ny) * tile_size
                canvas[top:top + tile_size, left:left + tile_size] = tile
        crop_left = tile_size - overlap
        crop_top = tile_size - overlap
        crop_right = tile_size * 2 + overlap
        crop_bottom = tile_size * 2 + overlap
        return canvas[crop_top:crop_bottom, crop_left:crop_right].copy()

    def _tile_sift_cache_key(
        self,
        manifest: StitchedManifest,
        keys: list[TileKey],
        *,
        overlap: int,
    ) -> tuple:
        parts = [manifest.area_id, manifest.candidate_type, manifest.layer_id, manifest.z_level, int(overlap)]
        for key in keys:
            path = resolve_tile_image_path(self.tile_root, key)
            try:
                stat = path.stat()
                stamp = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                stamp = (0, 0)
            parts.append((key.kind, key.layer_id, key.z_level, key.x, key.y, stamp))
            if manifest.candidate_type != "base":
                base = TileKey(key.area_id, "default", None, "standard", key.x, key.y)
                base_path = resolve_tile_image_path(self.tile_root, base)
                try:
                    base_stat = base_path.stat()
                    base_stamp = (int(base_stat.st_mtime_ns), int(base_stat.st_size))
                except OSError:
                    base_stamp = (0, 0)
                parts.append(("standard", "default", None, key.x, key.y, base_stamp))
        return tuple(parts)

    def _load_or_build_tile_sift_index(
        self,
        manifest: StitchedManifest,
        keys: list[TileKey],
    ) -> dict[str, np.ndarray]:
        overlap = min(64, max(0, int(manifest.tile_size) // 16))
        keys = sorted(keys, key=lambda key: (key.y, key.x, key.kind, key.layer_id, key.z_level or 0), reverse=True)
        cache_key = self._tile_sift_cache_key(manifest, keys, overlap=overlap)
        if cache_key in self._GLOBAL_TILE_SIFT_CACHE:
            self._last_sift_index_source = "memory"
            return self._GLOBAL_TILE_SIFT_CACHE[cache_key]
        persisted = self._load_persisted_tile_sift_index(manifest, keys, overlap=overlap)
        if persisted is not None:
            self._last_sift_index_source = "disk"
            self._GLOBAL_TILE_SIFT_CACHE[cache_key] = persisted
            return persisted
        self._last_sift_index_source = "rebuilt"
        allowed_xy = {(key.x, key.y) for key in keys} if manifest.candidate_type != "base" else None
        descriptors: list[np.ndarray] = []
        global_xy: list[tuple[float, float]] = []
        for key in keys:
            expanded = self._compose_expanded_candidate_tile(
                manifest,
                key,
                allowed_neighbor_xy=allowed_xy,
                overlap=overlap,
            )
            records = extract_owned_sift_features_from_expanded_tile(
                region_id=manifest.area_id,
                tile_x=key.x,
                tile_y=key.y,
                expanded_bgr=expanded,
                tile_size=int(manifest.tile_size),
                overlap=overlap,
                origin_tile_x=int(manifest.origin_tile_x),
                origin_tile_y=int(manifest.origin_tile_y),
            )
            for record in records:
                descriptors.append(record.descriptor.astype(np.float32))
                global_xy.append((float(record.global_x), float(record.global_y)))
        if descriptors:
            data = {
                "descriptors": np.vstack(descriptors).astype(np.float32),
                "global_xy": np.array(global_xy, dtype=np.float32),
            }
        else:
            data = {
                "descriptors": np.empty((0, 128), dtype=np.float32),
                "global_xy": np.empty((0, 2), dtype=np.float32),
            }
        self._GLOBAL_TILE_SIFT_CACHE[cache_key] = data
        self._persist_tile_sift_index(manifest, keys, overlap=overlap, data=data)
        return data

    def _tile_sift_payload(self, manifest: StitchedManifest, keys: list[TileKey], *, overlap: int) -> dict[str, Any]:
        tile_entries: list[dict[str, Any]] = []
        for key in keys:
            path = resolve_tile_image_path(self.tile_root, key)
            entry = {
                "kind": key.kind,
                "layer_id": key.layer_id,
                "z_level": key.z_level,
                "x": key.x,
                "y": key.y,
                "file": self._file_stamp(path),
            }
            if manifest.candidate_type != "base":
                base = TileKey(key.area_id, "default", None, "standard", key.x, key.y)
                entry["base_file"] = self._file_stamp(resolve_tile_image_path(self.tile_root, base))
            tile_entries.append(entry)
        return {
            "version": 1,
            "index_type": "sift",
            "area_id": manifest.area_id,
            "candidate_type": manifest.candidate_type,
            "layer_id": manifest.layer_id,
            "z_level": manifest.z_level,
            "tile_size": manifest.tile_size,
            "origin_tile_x": manifest.origin_tile_x,
            "origin_tile_y": manifest.origin_tile_y,
            "overlap": int(overlap),
            "tiles": tile_entries,
        }

    def _tile_sift_index_paths(
        self,
        manifest: StitchedManifest,
        keys: list[TileKey],
        *,
        overlap: int,
    ) -> tuple[Path, Path, dict[str, Any]]:
        payload = self._tile_sift_payload(manifest, keys, overlap=overlap)
        digest = self._hash_payload(payload)
        root = self._index_root(manifest.area_id)
        return root / f"sift_{digest}.npz", root / f"sift_{digest}.json", payload

    def _load_persisted_tile_sift_index(
        self,
        manifest: StitchedManifest,
        keys: list[TileKey],
        *,
        overlap: int,
    ) -> dict[str, np.ndarray] | None:
        npz_path, json_path, payload = self._tile_sift_index_paths(manifest, keys, overlap=overlap)
        if not npz_path.exists() or not json_path.exists():
            return None
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        if meta.get("payload") != payload:
            return None
        data = np.load(npz_path)
        return {
            "descriptors": data["descriptors"].astype(np.float32),
            "global_xy": data["global_xy"].astype(np.float32),
        }

    def _persist_tile_sift_index(
        self,
        manifest: StitchedManifest,
        keys: list[TileKey],
        *,
        overlap: int,
        data: dict[str, np.ndarray],
    ) -> None:
        npz_path, json_path, payload = self._tile_sift_index_paths(manifest, keys, overlap=overlap)
        self._write_npz_atomic(
            npz_path,
            descriptors=data["descriptors"].astype(np.float32),
            global_xy=data["global_xy"].astype(np.float32),
        )
        self._write_json_atomic(json_path, {"payload": payload})

    def _candidate_feature_indices(
        self,
        global_xy: np.ndarray,
        hit,
        manifest: StitchedManifest,
    ) -> np.ndarray:
        scale = max(1, int(manifest.rough_downsample))
        raw = hit.candidate
        left = float(raw.left) * scale
        top = float(raw.top) * scale
        right = left + float(raw.width) * scale
        bottom = top + float(raw.height) * scale
        mask = (
            (global_xy[:, 0] >= left)
            & (global_xy[:, 0] < right)
            & (global_xy[:, 1] >= top)
            & (global_xy[:, 1] < bottom)
        )
        return np.flatnonzero(mask)

    def _match_with_sift(
        self,
        normalized_minimap_image: Any,
        minimap_mask: Any,
        context: MapContext,
        active_game_xy: tuple[int | float, int | float] | None,
    ) -> VisualLocalizationResult | None:
        self.last_trace = {"manifests": []}
        query_color, query_mask = self._query_color_and_mask(normalized_minimap_image, minimap_mask)
        detector = create_sift_detector()
        query_keypoints, query_descriptors = detector.detectAndCompute(query_color, query_mask)
        if query_descriptors is None or len(query_keypoints) < 3:
            return None
        query_descriptors = query_descriptors.astype(np.float32)

        candidate_rows: list[dict[str, Any]] = []
        for manifest_path in self._manifest_paths(context):
            manifest = self._load_manifest(manifest_path)
            if not self._manifest_can_match(manifest, active_game_xy):
                continue
            manifest_trace = {
                "area_id": manifest.area_id,
                "candidate_type": manifest.candidate_type,
                "layer_id": manifest.layer_id,
                "z_level": manifest.z_level,
                "rough_index_source": "",
                "rough_hits": [],
            }
            self.last_trace["manifests"].append(manifest_trace)
            rough = cv2.imread(str(self.tile_root / manifest.rough_color_path), cv2.IMREAD_COLOR)
            if rough is None:
                manifest_trace["failure"] = "missing_rough_color"
                continue

            hits = self._rough_retrieval_hits(
                manifest=manifest,
                rough=rough,
                query_color=query_color,
                query_mask=query_mask,
            )
            manifest_trace["rough_index_source"] = self._last_rough_index_source
            matcher = cv2.BFMatcher(cv2.NORM_L2)
            for hit in hits:
                tile_keys = self._tile_keys_for_rough_hit(manifest, hit)
                hit_trace = {
                    "rank": int(hit.rank),
                    "score": float(hit.score),
                    "window": {
                        "left": int(hit.candidate.left),
                        "top": int(hit.candidate.top),
                        "width": int(hit.candidate.width),
                        "height": int(hit.candidate.height),
                    },
                    "tile_keys": [
                        f"{key.kind}/{key.layer_id}/{'base' if key.z_level is None else key.z_level}/{key.x}_{key.y}"
                        for key in tile_keys
                    ],
                    "sift_index_source": "",
                    "feature_count": 0,
                    "raw_match_count": 0,
                    "good_match_count": 0,
                    "inlier_count": 0,
                    "accepted": False,
                }
                manifest_trace["rough_hits"].append(hit_trace)
                if not tile_keys:
                    continue
                index = self._load_or_build_tile_sift_index(manifest, tile_keys)
                hit_trace["sift_index_source"] = self._last_sift_index_source
                descriptors = index["descriptors"]
                global_xy = index["global_xy"]
                hit_trace["feature_count"] = int(len(descriptors))
                if len(descriptors) < 3:
                    continue
                indices = self._candidate_feature_indices(global_xy, hit, manifest)
                if len(indices) < 3:
                    continue
                candidate_descriptors = descriptors[indices]
                candidate_global_xy = global_xy[indices]
                knn = matcher.knnMatch(query_descriptors, candidate_descriptors, k=2)
                good = filter_ratio_matches(knn, ratio=float(self.config.sift_ratio))
                hit_trace["raw_match_count"] = int(len(knn))
                hit_trace["good_match_count"] = int(len(good))
                estimate = estimate_similarity_from_matches(
                    query_keypoints,
                    candidate_global_xy,
                    good,
                    query_width=int(query_color.shape[1]),
                    query_height=int(query_color.shape[0]),
                )
                inlier_matches = estimate["inlier_matches"]
                hit_trace["inlier_count"] = int(len(inlier_matches))
                if len(inlier_matches) < int(self.config.sift_min_inliers):
                    continue
                center_x = estimate["estimated_center_x"]
                center_y = estimate["estimated_center_y"]
                if center_x is None or center_y is None:
                    continue
                hit_trace["accepted"] = True
                game_x, game_y = stitched_pixel_to_game_xy(manifest, center_x, center_y)
                confidence = min(1.0, float(len(inlier_matches)) / 20.0)
                candidate_rows.append(
                    {
                        "rank": int(hit.rank),
                        "rough_score": float(hit.score),
                        "raw_match_count": len(knn),
                        "good_match_count": len(good),
                        "inlier_count": len(inlier_matches),
                        "candidate": CoordinateCandidate(
                            x=int(round(game_x)),
                            y=int(round(game_y)),
                            z=None,
                            source="visual",
                            confidence=confidence,
                            reason="sift",
                        ),
                        "manifest": manifest,
                        "estimate": {
                            key: value
                            for key, value in estimate.items()
                            if key != "inlier_matches"
                        },
                        "rough": VisualMatchEvidence(
                            location=(int(hit.candidate.left), int(hit.candidate.top)),
                            raw_score=float(hit.score),
                            normalized_confidence=max(0.0, min(1.0, float(hit.score))),
                            threshold=0.0,
                        ),
                        "exact": VisualMatchEvidence(
                            location=(int(round(center_x)), int(round(center_y))),
                            raw_score=float(len(good)),
                            normalized_confidence=confidence,
                            threshold=float(self.config.sift_min_inliers),
                        ),
                    }
                )

        selected = select_best_sift_candidate(candidate_rows)
        if selected is None:
            return None
        return VisualLocalizationResult(
            candidate=selected["candidate"],
            manifest=selected["manifest"],
            rough=selected["rough"],
            exact=selected["exact"],
            sift={
                "rank": selected["rank"],
                "rough_score": selected["rough_score"],
                "raw_match_count": selected["raw_match_count"],
                "good_match_count": selected["good_match_count"],
                "inlier_count": selected["inlier_count"],
                **selected["estimate"],
            },
        )

    def match(
        self,
        normalized_minimap_image: Any,
        minimap_mask: Any,
        context: MapContext,
        active_game_xy: tuple[int | float, int | float] | None = None,
    ):
        # OCR coordinates and precomputed scale are deliberately not inputs to SIFT localization.
        return self._match_with_tile_indexes(
            normalized_minimap_image,
            minimap_mask,
            context,
        )

    def _match_with_tile_indexes(
        self,
        normalized_minimap_image: Any,
        minimap_mask: Any,
        context: MapContext,
    ) -> VisualLocalizationResult | None:
        self.last_trace = {
            "rough_index_source": "tile_index",
            "rough_candidates_available": 0,
            "rough_candidates_used": 0,
            "rough_candidates_skipped_missing": 0,
            "rough_hits": [],
        }
        query_color, query_mask = self._query_color_and_mask(normalized_minimap_image, minimap_mask)
        rough_entries = self._load_tile_rough_entries(context.area_id)
        self.last_trace["rough_candidates_available"] = len(rough_entries)
        if not rough_entries:
            return None

        query_vector = compute_hsv_texture_descriptor(query_color, mask=query_mask)
        scored = []
        for entry in rough_entries:
            vector = np.asarray(entry.get("vector", []), dtype=np.float32)
            if vector.size == 0:
                continue
            vector_norm = float(np.linalg.norm(vector))
            query_norm = float(np.linalg.norm(query_vector))
            if vector_norm > 0:
                vector = vector / vector_norm
            query = query_vector / query_norm if query_norm > 0 else query_vector
            scored.append((float(np.dot(query, vector)), entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        hits = scored[: max(1, int(self.config.rough_candidate_limit))]
        self.last_trace["rough_candidates_used"] = len(hits)
        if not hits:
            return None

        detector = create_sift_detector()
        query_keypoints, query_descriptors = detector.detectAndCompute(query_color, query_mask)
        if query_descriptors is None or len(query_keypoints) < 3:
            return None
        query_descriptors = query_descriptors.astype(np.float32)
        matcher = cv2.BFMatcher(cv2.NORM_L2)
        candidate_rows: list[dict[str, Any]] = []

        for rank, (score, entry) in enumerate(hits, start=1):
            tile_keys = [
                key
                for key in (parse_canonical_tile_key(raw) for raw in entry.get("tile_keys", []))
                if key is not None
            ]
            hit_trace = {
                "rank": rank,
                "score": score,
                "work_key": entry.get("work_key", ""),
                "tile_keys": [canonical_tile_key(key) for key in tile_keys],
                "sift_index_source": "tile_index",
                "feature_count": 0,
                "raw_match_count": 0,
                "good_match_count": 0,
                "inlier_count": 0,
                "accepted": False,
                "skip_reason": "",
            }
            self.last_trace["rough_hits"].append(hit_trace)
            index = self._load_existing_sift_tiles(context.area_id, tile_keys)
            if index is None:
                hit_trace["skip_reason"] = "missing_sift_index"
                self.last_trace["rough_candidates_skipped_missing"] += 1
                continue
            descriptors = index["descriptors"]
            global_xy = index["global_xy"]
            hit_trace["feature_count"] = int(len(descriptors))
            if len(descriptors) < 3:
                hit_trace["skip_reason"] = "too_few_features"
                continue
            knn = matcher.knnMatch(query_descriptors, descriptors, k=2)
            good = filter_ratio_matches(knn, ratio=float(self.config.sift_ratio))
            hit_trace["raw_match_count"] = int(len(knn))
            hit_trace["good_match_count"] = int(len(good))
            estimate = estimate_similarity_from_matches(
                query_keypoints,
                global_xy,
                good,
                query_width=int(query_color.shape[1]),
                query_height=int(query_color.shape[0]),
            )
            inlier_matches = estimate["inlier_matches"]
            hit_trace["inlier_count"] = int(len(inlier_matches))
            if len(inlier_matches) < int(self.config.sift_min_inliers):
                hit_trace["skip_reason"] = "too_few_inliers"
                continue
            center_x = estimate["estimated_center_x"]
            center_y = estimate["estimated_center_y"]
            if center_x is None or center_y is None:
                hit_trace["skip_reason"] = "missing_center"
                continue
            hit_trace["accepted"] = True
            game_x, game_y = self._tile_global_pixel_to_game_xy(context, center_x, center_y)
            confidence = min(1.0, float(len(inlier_matches)) / 20.0)
            candidate_rows.append(
                {
                    "rank": rank,
                    "rough_score": score,
                    "raw_match_count": len(knn),
                    "good_match_count": len(good),
                    "inlier_count": len(inlier_matches),
                    "candidate": CoordinateCandidate(
                        x=int(round(game_x)),
                        y=int(round(game_y)),
                        z=None,
                        source="visual",
                        confidence=confidence,
                        reason="tile_index_sift",
                    ),
                    "manifest": self._synthetic_manifest_for_tile_index(context),
                    "estimate": {key: value for key, value in estimate.items() if key != "inlier_matches"},
                    "rough": VisualMatchEvidence(
                        location=(0, 0),
                        raw_score=float(score),
                        normalized_confidence=max(0.0, min(1.0, float(score))),
                        threshold=0.0,
                    ),
                    "exact": VisualMatchEvidence(
                        location=(int(round(center_x)), int(round(center_y))),
                        raw_score=float(len(good)),
                        normalized_confidence=confidence,
                        threshold=float(self.config.sift_min_inliers),
                    ),
                }
            )
        selected = select_best_sift_candidate(candidate_rows)
        if selected is None:
            return None
        return VisualLocalizationResult(
            candidate=selected["candidate"],
            manifest=selected["manifest"],
            rough=selected["rough"],
            exact=selected["exact"],
            sift={
                "rank": selected["rank"],
                "rough_score": selected["rough_score"],
                "raw_match_count": selected["raw_match_count"],
                "good_match_count": selected["good_match_count"],
                "inlier_count": selected["inlier_count"],
                **selected["estimate"],
            },
        )

    def _load_tile_rough_entries(self, area_id: str) -> list[dict[str, Any]]:
        root = self.tile_root / str(area_id) / "indexes" / "rough_windows"
        if not root.exists():
            return []
        rough_paths = tuple(sorted(root.glob("*.json")))
        index_root = self.tile_root / str(area_id) / "indexes"
        cache_key = (
            str(self.tile_root.resolve()),
            str(area_id),
            tuple(self._file_stamp_tuple(path) for path in rough_paths),
            self._file_stamp_tuple(index_root / "tile_index_state.json"),
            self._file_stamp_tuple(index_root / "minimap_index.sqlite3"),
        )
        cached = self._GLOBAL_TILE_ROUGH_ENTRIES_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)
        state = TileIndexStateStore(self.tile_root, str(area_id))
        index_store = MinimapIndexStore(self.tile_root, str(area_id))
        entries: list[dict[str, Any]] = []
        for path in rough_paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            tile_keys = [
                key
                for key in (parse_canonical_tile_key(value) for value in raw.get("tile_keys", []))
                if key is not None
            ]
            if not tile_keys:
                continue
            skip_entry = False
            for key in tile_keys:
                if not self._tile_rough_ready(key, state, index_store):
                    skip_entry = True
                    break
            if skip_entry:
                continue
            entries.append(raw)
        self._GLOBAL_TILE_ROUGH_ENTRIES_CACHE[cache_key] = list(entries)
        return entries

    def _load_existing_sift_tiles(self, area_id: str, tile_keys: list[TileKey]) -> dict[str, np.ndarray] | None:
        root = self.tile_root / str(area_id) / "indexes" / "sift_tiles"
        state = TileIndexStateStore(self.tile_root, str(area_id))
        index_store = MinimapIndexStore(self.tile_root, str(area_id))
        descriptors: list[np.ndarray] = []
        global_xy: list[np.ndarray] = []
        repaired: list[tuple[TileKey, TileIndexStatus]] = []
        for key in tile_keys:
            path = root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
            sqlite_status = index_store.get_tile_status(key)
            if sqlite_status.exists:
                if not sqlite_status.tile_present or not sqlite_status.sift_ready or sqlite_status.stale_reason:
                    return None
                if sqlite_status.sift_path:
                    candidate_path = Path(sqlite_status.sift_path)
                    if candidate_path.exists():
                        path = candidate_path
            else:
                status = state.get_tile_status(key)
                if status.sift_stale_reason:
                    return None
                tile_path = resolve_tile_image_path(self.tile_root, key)
                tile_stamp = self._file_stamp(tile_path)
                if not status.sift_indexed:
                    if int(tile_stamp["size"]) <= 0:
                        return None
                    repaired.append(
                        (
                            key,
                            TileIndexStatus(
                                tile_present=True,
                                rough_indexed=status.rough_indexed,
                                sift_indexed=True,
                                sift_stale_reason="",
                                file_mtime_ns=int(tile_stamp["mtime_ns"]),
                                file_size=int(tile_stamp["size"]),
                            ),
                        )
                    )
            if not path.exists():
                return None
            sift_arrays = self._load_sift_arrays_cached(path)
            descriptors.append(sift_arrays["descriptors"])
            global_xy.append(sift_arrays["global_xy"])
        if not descriptors:
            return None
        if repaired:
            for key, status in repaired:
                state.set_tile_status(key, status)
            state.save()
        return {
            "descriptors": np.vstack(descriptors).astype(np.float32),
            "global_xy": np.vstack(global_xy).astype(np.float32),
        }

    def _load_sift_arrays_cached(self, path: Path) -> dict[str, np.ndarray]:
        cache_key = self._file_stamp_tuple(path)
        cached = self._GLOBAL_EXISTING_SIFT_ARRAY_CACHE.get(cache_key)
        if cached is not None:
            return {
                "descriptors": cached["descriptors"],
                "global_xy": cached["global_xy"],
            }
        with np.load(path) as data:
            arrays = {
                "descriptors": data["descriptors"].astype(np.float32),
                "global_xy": data["global_xy"].astype(np.float32),
            }
        self._GLOBAL_EXISTING_SIFT_ARRAY_CACHE[cache_key] = arrays
        return {
            "descriptors": arrays["descriptors"],
            "global_xy": arrays["global_xy"],
        }

    def _tile_rough_ready(
        self,
        key: TileKey,
        state: TileIndexStateStore,
        index_store: MinimapIndexStore,
    ) -> bool:
        sqlite_status = index_store.get_tile_status(key)
        if sqlite_status.exists:
            return sqlite_status.tile_present and sqlite_status.rough_ready
        status = state.get_tile_status(key)
        return status.tile_present and status.rough_indexed

    def _tile_global_pixel_to_game_xy(self, context: MapContext, pixel_x: float, pixel_y: float) -> tuple[float, float]:
        scale_x = float(context.coord_transform.get("scaleX", 1.0) or 1.0)
        scale_y = float(context.coord_transform.get("scaleY", 1.0) or 1.0)
        return float(pixel_x) / scale_x / 100.0, float(pixel_y) / scale_y / 100.0

    def _synthetic_manifest_for_tile_index(self, context: MapContext) -> StitchedManifest:
        return StitchedManifest(
            area_id=context.area_id,
            candidate_type="base",
            layer_id=context.layer_id,
            z_level=None,
            tile_size=context.tile_size,
            origin_tile_x=0,
            origin_tile_y=0,
            width=0,
            height=0,
            coord_transform=dict(context.coord_transform),
            fine_gray_path="",
            rough_color_path="",
            manifest_path="",
            rough_downsample=1,
            map_units_per_tile_x=context.map_units_per_tile_x,
            map_units_per_tile_y=context.map_units_per_tile_y,
        )


def _safe_tile_index_name(value: str) -> str:
    return value.replace("|", "__").replace("/", "_").replace(":", "_")
