from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from core.map_context import TileKey
from minimap_tile_cache import MinimapTileCache
from minimap_tile_geometry import url_tile_to_map_pixel


@dataclass(frozen=True)
class SiftFeatureRecord:
    region_id: str
    tile_x: int
    tile_y: int
    global_x: float
    global_y: float
    local_x: float
    local_y: float
    size: float
    angle: float
    response: float
    descriptor: np.ndarray


def expanded_local_to_global_pixel(
    *,
    tile_x: int,
    tile_y: int,
    tile_size: int,
    overlap: int,
    expanded_local_x: float,
    expanded_local_y: float,
) -> tuple[float, float]:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    global_x = tile_x * tile_size + expanded_local_x - overlap
    global_y = tile_y * tile_size + expanded_local_y - overlap
    return float(global_x), float(global_y)


def expanded_local_to_map_pixel(
    *,
    tile_x: int,
    tile_y: int,
    tile_size: int,
    overlap: int,
    expanded_local_x: float,
    expanded_local_y: float,
) -> tuple[float, float]:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    local_x = float(expanded_local_x) - float(overlap)
    local_y = float(expanded_local_y) - float(overlap)
    return url_tile_to_map_pixel(tile_x, tile_y, local_x, local_y, tile_size=tile_size)


def expanded_local_to_stitched_pixel(
    *,
    tile_x: int,
    tile_y: int,
    origin_tile_x: int,
    origin_tile_y: int,
    tile_size: int,
    overlap: int,
    expanded_local_x: float,
    expanded_local_y: float,
) -> tuple[float, float]:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    stitched_x = (tile_x - origin_tile_x) * tile_size + expanded_local_x - overlap
    stitched_y = (origin_tile_y - tile_y) * tile_size + expanded_local_y - overlap
    return float(stitched_x), float(stitched_y)


def is_feature_owned_by_core_tile(
    *,
    tile_size: int,
    overlap: int,
    expanded_local_x: float,
    expanded_local_y: float,
) -> bool:
    return (
        overlap <= expanded_local_x < overlap + tile_size
        and overlap <= expanded_local_y < overlap + tile_size
    )


def create_sift_detector():
    if not hasattr(cv2, "SIFT_create"):
        raise RuntimeError("OpenCV SIFT is unavailable in this environment")
    return cv2.SIFT_create()


def extract_owned_sift_features_from_expanded_tile(
    *,
    region_id: str,
    tile_x: int,
    tile_y: int,
    expanded_bgr: np.ndarray,
    tile_size: int,
    overlap: int,
    origin_tile_x: int | None = None,
    origin_tile_y: int | None = None,
) -> list[SiftFeatureRecord]:
    detector = create_sift_detector()
    keypoints, descriptors = detector.detectAndCompute(expanded_bgr, None)
    if descriptors is None:
        return []

    records: list[SiftFeatureRecord] = []
    for keypoint, descriptor in zip(keypoints, descriptors):
        local_x, local_y = keypoint.pt
        if not is_feature_owned_by_core_tile(
            tile_size=tile_size,
            overlap=overlap,
            expanded_local_x=local_x,
            expanded_local_y=local_y,
        ):
            continue
        if origin_tile_x is None or origin_tile_y is None:
            global_x, global_y = expanded_local_to_map_pixel(
                tile_x=tile_x,
                tile_y=tile_y,
                tile_size=tile_size,
                overlap=overlap,
                expanded_local_x=local_x,
                expanded_local_y=local_y,
            )
        else:
            global_x, global_y = expanded_local_to_stitched_pixel(
                tile_x=tile_x,
                tile_y=tile_y,
                origin_tile_x=origin_tile_x,
                origin_tile_y=origin_tile_y,
                tile_size=tile_size,
                overlap=overlap,
                expanded_local_x=local_x,
                expanded_local_y=local_y,
            )
        records.append(
            SiftFeatureRecord(
                region_id=str(region_id),
                tile_x=int(tile_x),
                tile_y=int(tile_y),
                global_x=float(global_x),
                global_y=float(global_y),
                local_x=float(local_x),
                local_y=float(local_y),
                size=float(keypoint.size),
                angle=float(keypoint.angle),
                response=float(keypoint.response),
                descriptor=descriptor.astype(np.float32),
            )
        )
    return records


def resolve_tile_image_path(cache_root: Path, key: TileKey) -> Path:
    """Resolve both runtime cache layout and legacy flat tile exports."""
    root = Path(cache_root)
    runtime_path = MinimapTileCache(root).tile_path(key)
    if runtime_path.exists():
        return runtime_path

    z_part = "base" if key.z_level is None else str(key.z_level)
    candidates = [
        root / f"{key.area_id}_{key.layer_id}_{key.x}_{key.y}.png",
        root / f"{key.x}_{key.y}.png",
        root / key.area_id / key.layer_id / f"{key.area_id}_{key.layer_id}_{key.x}_{key.y}.png",
        root / key.area_id / key.layer_id / f"{key.x}_{key.y}.png",
        root / key.area_id / key.kind / key.layer_id / z_part / f"{key.x}_{key.y}.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return runtime_path


def _read_tile_or_blank(path: Path, tile_size: int) -> np.ndarray:
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
    return image


def compose_expanded_tile_from_cache(
    *,
    cache_root: Path,
    key: TileKey,
    tile_size: int,
    overlap: int,
    allowed_neighbor_xy: set[tuple[int, int]] | None = None,
) -> np.ndarray:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap > tile_size:
        raise ValueError("overlap must not exceed tile_size")

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
            tile = _read_tile_or_blank(resolve_tile_image_path(Path(cache_root), neighbor), tile_size)
            left = (nx - (key.x - 1)) * tile_size
            top = (origin_y - ny) * tile_size
            canvas[top:top + tile_size, left:left + tile_size] = tile

    crop_left = tile_size - overlap
    crop_top = tile_size - overlap
    crop_right = tile_size * 2 + overlap
    crop_bottom = tile_size * 2 + overlap
    return canvas[crop_top:crop_bottom, crop_left:crop_right].copy()
