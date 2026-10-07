from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from core.map_context import TileKey
from minimap_tile_geometry import url_tile_to_map_pixel
from minimap_tile_index_state import parse_canonical_tile_key

RegionRect = tuple[int, int, int, int]
PlaneKey = tuple[str, str, str, int | None]


def select_region_feature_indices(
    global_xy: np.ndarray,
    rectangles: Sequence[tuple[int, int, int, int]],
) -> np.ndarray:
    """Return ascending row indices of features inside the union of rectangles.

    ``rectangles`` are ``(left, top, width, height)`` in absolute map pixels of a
    single map plane, with half-open bounds: ``left``/``top`` inclusive and the
    right/bottom edges exclusive. Callers MUST split per plane and load features
    once per tile.
    """
    points = np.asarray(global_xy, dtype=np.float64)
    if points.size == 0 or len(rectangles) == 0:
        return np.empty(0, dtype=np.int64)

    xs = points[:, 0]
    ys = points[:, 1]
    inside = np.zeros(xs.shape[0], dtype=bool)
    for left, top, width, height in rectangles:
        inside |= (
            (xs >= left)
            & (xs < left + width)
            & (ys >= top)
            & (ys < top + height)
        )
    return np.flatnonzero(inside).astype(np.int64)


def select_radius_feature_indices(
    global_xy: np.ndarray,
    center_px: tuple[float, float],
    radius_px: float,
) -> np.ndarray:
    """Return ascending row indices of features inside one map-pixel circle.

    ``global_xy`` is ``N x 2`` absolute map pixels of a single map plane and
    ``center_px``/``radius_px`` are the circle in that same basis. The circle is
    closed: a point whose squared distance equals ``radius_px ** 2`` is selected.
    """
    points = np.asarray(global_xy, dtype=np.float64)
    if points.size == 0:
        return np.empty(0, dtype=np.int64)

    radius = max(0.0, float(radius_px))
    dx = points[:, 0] - float(center_px[0])
    dy = points[:, 1] - float(center_px[1])
    inside = dx * dx + dy * dy <= radius * radius
    return np.flatnonzero(inside).astype(np.int64)


@dataclass
class CandidateRegionGroup:
    tile_keys: list[TileKey]
    rectangles: list[RegionRect]


def _entry_tile_keys(entry: Mapping[str, Any]) -> list[TileKey]:
    return [
        key
        for key in (parse_canonical_tile_key(raw) for raw in entry.get("tile_keys", []))
        if key is not None
    ]


def _plane_key(key: TileKey) -> PlaneKey:
    return (key.area_id, key.kind, key.layer_id, key.z_level)


def build_candidate_regions(
    hsv_entries: Sequence[Mapping[str, Any]],
    orb_entries: Sequence[Mapping[str, Any]],
    tile_size: int = 1024,
) -> dict[PlaneKey, CandidateRegionGroup]:
    """Group coarse hits into per-plane rectangle unions for feature selection.

    Each HSV entry contributes the full tile rectangle of every key it already
    carries; each ORB entry contributes its own window rectangle plus its keys.
    Only keys present on the entries are used, and input order is preserved.
    """
    tiles_by_plane: dict[PlaneKey, dict[TileKey, None]] = {}
    rects_by_plane: dict[PlaneKey, dict[RegionRect, None]] = {}

    def add(key: TileKey, rect: RegionRect) -> None:
        plane = _plane_key(key)
        tiles_by_plane.setdefault(plane, {})[key] = None
        rects_by_plane.setdefault(plane, {})[rect] = None

    for entry in hsv_entries:
        for key in _entry_tile_keys(entry):
            left, top = url_tile_to_map_pixel(key.x, key.y, 0, 0, tile_size)
            add(key, (int(left), int(top), int(tile_size), int(tile_size)))
    for entry in orb_entries:
        rect: RegionRect = (
            int(entry["left"]),
            int(entry["top"]),
            int(entry["width"]),
            int(entry["height"]),
        )
        for key in _entry_tile_keys(entry):
            add(key, rect)

    return {
        plane: CandidateRegionGroup(list(tiles), list(rects_by_plane[plane]))
        for plane, tiles in tiles_by_plane.items()
    }


def build_radius_regions(
    entries: Sequence[Mapping[str, Any]],
    center_px: tuple[float, float],
    radius_px: float,
) -> dict[PlaneKey, CandidateRegionGroup]:
    """Group the coarse windows that overlap a circle into per-plane rectangle unions.

    ``entries`` are coarse window entries of any scheme, each carrying its absolute
    map-pixel window rectangle and its tile keys. A window contributes when its
    rectangle intersects the circle's bounding box, so the union is conservative and
    never smaller than the circle. Unlike ``build_candidate_regions`` no scheme
    expands to whole tile rectangles: every entry keeps its own window geometry.
    The planes are exactly those present on the contributing entries.
    """
    radius = max(0.0, float(radius_px))
    box_left = float(center_px[0]) - radius
    box_top = float(center_px[1]) - radius
    box_right = float(center_px[0]) + radius
    box_bottom = float(center_px[1]) + radius

    tiles_by_plane: dict[PlaneKey, dict[TileKey, None]] = {}
    rects_by_plane: dict[PlaneKey, dict[RegionRect, None]] = {}

    for entry in entries:
        rect: RegionRect = (
            int(entry["left"]),
            int(entry["top"]),
            int(entry["width"]),
            int(entry["height"]),
        )
        left, top, width, height = rect
        if left > box_right or left + width < box_left:
            continue
        if top > box_bottom or top + height < box_top:
            continue
        for key in _entry_tile_keys(entry):
            plane = _plane_key(key)
            tiles_by_plane.setdefault(plane, {})[key] = None
            rects_by_plane.setdefault(plane, {})[rect] = None

    return {
        plane: CandidateRegionGroup(list(tiles), list(rects_by_plane[plane]))
        for plane, tiles in tiles_by_plane.items()
    }
