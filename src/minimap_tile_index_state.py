from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time

from core.map_context import TileKey

# The production coarse index cuts every map plane on a stride-W lattice of
# ``COARSE_WINDOW_SIZE`` windows in the un-anchored map-pixel basis that
# ``minimap_tile_geometry.url_tile_to_map_pixel`` defines and that the SIFT npz
# ``global_xy`` already uses. ``COARSE_PHASES`` is the four-fold shift of that
# lattice (none, half a window in X, half a window in Y, half a window in both) and
# is the production equivalent of the lab's ``CROP_PHASES``, whose four phase sets
# carry exactly these four shift pairs. Within one phase the stride equals the
# window size, so that phase tiles the plane with no overlap and cuts every map
# coordinate exactly once. The four phases are half-window translates of each other,
# so their *windows* overlap: a map coordinate is sampled once per phase, roughly
# four times overall. Only the window centres are pairwise distinct, which is what
# makes a document unique per phase.
COARSE_WINDOW_SIZE = 400
COARSE_PHASES = (
    (0, 0),
    (1, 0),
    (0, 1),
    (1, 1),
)
# Number of tile images a single generation pass may hold at once. A full-area
# rebuild runs on the index queue's only worker and visits thousands of tiles, so
# the cache is a bounded FIFO rather than the whole plane.
COARSE_TILE_CACHE_LIMIT = 24


@dataclass(frozen=True)
class TileIndexStatus:
    tile_present: bool = False
    rough_indexed: bool = False
    sift_indexed: bool = False
    sift_stale_reason: str = ""
    file_mtime_ns: int = 0
    file_size: int = 0


def canonical_tile_key(key: TileKey) -> str:
    z_part = "base" if key.z_level is None else str(key.z_level)
    return f"{key.area_id}|{key.kind}|{key.layer_id}|{z_part}|{int(key.x)}|{int(key.y)}"


def coarse_lattice_base(tile_size: int, window_size: int, shift: int) -> int:
    """Map pixel of index 0's window edge for one axis of one phase."""
    half = int(window_size) // 2
    return int(shift) * half - half + int(tile_size) // 2


def coarse_window_left_top(
    tile_size: int,
    window_size: int,
    *,
    shift_x: int,
    shift_y: int,
    index_x: int,
    index_y: int,
) -> tuple[int, int]:
    """Top-left map pixel of one lattice window, in the SIFT ``global_xy`` basis.

    ``shift_x``/``shift_y`` are half-window units, so phase B is ``shift_x=1``.
    A window whose centre is ``(offset, offset)`` in the anchored lattice starts at
    ``centre - window/2 + tile/2`` once the half-tile anchor is removed, which is the
    ``tile_size // 2 - window_size // 2`` term below.
    """
    base_x = coarse_lattice_base(tile_size, window_size, shift_x)
    base_y = coarse_lattice_base(tile_size, window_size, shift_y)
    return base_x + int(window_size) * int(index_x), base_y + int(window_size) * int(index_y)


def coarse_tile_origin(x: int, y: int, tile_size: int) -> tuple[int, int]:
    """Map pixel of a tile's top-left corner in the SIFT ``global_xy`` basis."""
    return (int(x) - 1) * int(tile_size), -int(y) * int(tile_size)


def coarse_tile_span(start: int, length: int, tile_size: int) -> range:
    """Tile indices covered by ``[start, start + length)`` on one axis."""
    size = int(tile_size)
    return range(int(start) // size, (int(start) + int(length) - 1) // size + 1)


def coarse_window_index_span(left: int, right: int, base: int, window_size: int) -> range:
    """Lattice indices whose windows can overlap ``[left, right)`` on one axis."""
    size = int(window_size)
    return range(
        (int(left) - int(base)) // size - 1,
        (int(right) - int(base)) // size + 2,
    )


def canonical_coarse_window_key(key: TileKey, left: int, top: int) -> str:
    """Window identity: the plane plus the absolute map-pixel rectangle.

    Tile membership is deliberately absent. Two windows over the same map rectangle
    of the same plane are the same document even if tiles appeared or disappeared
    between generating them, so a regenerated window replaces its own file instead of
    leaving a second geometry-derived file behind.
    """
    z_part = "base" if key.z_level is None else str(key.z_level)
    return f"{key.area_id}|{key.kind}|{key.layer_id}|{z_part}|{int(left)}_{int(top)}"


def coarse_window_rects_for_tile(
    x: int,
    y: int,
    *,
    tile_size: int,
    window_size: int,
) -> list[tuple[int, int]]:
    """Every lattice window of every phase that overlaps one tile.

    These are exactly the windows whose content or tile membership a newly written
    tile can change, which makes them the complete incremental update set for that
    tile.
    """
    tile_left, tile_top = coarse_tile_origin(x, y, tile_size)
    tile_right = tile_left + int(tile_size)
    tile_bottom = tile_top + int(tile_size)
    rects: list[tuple[int, int]] = []
    for shift_x, shift_y in COARSE_PHASES:
        base_x = coarse_lattice_base(tile_size, window_size, shift_x)
        base_y = coarse_lattice_base(tile_size, window_size, shift_y)
        for index_x in coarse_window_index_span(tile_left, tile_right, base_x, window_size):
            left = base_x + int(window_size) * index_x
            if left >= tile_right or left + int(window_size) <= tile_left:
                continue
            for index_y in coarse_window_index_span(tile_top, tile_bottom, base_y, window_size):
                top = base_y + int(window_size) * index_y
                if top >= tile_bottom or top + int(window_size) <= tile_top:
                    continue
                rects.append((left, top))
    return rects


class TileIndexStateStore:
    def __init__(self, tile_root: Path, area_id: str):
        self.tile_root = Path(tile_root)
        self.area_id = str(area_id)
        self.path = self.tile_root / self.area_id / "indexes" / "tile_index_state.json"
        self._tile_status: dict[str, TileIndexStatus] = {}
        self._load()

    def get_tile_status(self, key: TileKey) -> TileIndexStatus:
        return self._tile_status.get(canonical_tile_key(key), TileIndexStatus())

    def tile_status_items(self) -> list[tuple[str, TileIndexStatus]]:
        return list(self._tile_status.items())

    def set_tile_status(self, key: TileKey, status: TileIndexStatus) -> None:
        self._tile_status[canonical_tile_key(key)] = status

    def mark_adjacent_sift_stale(self, changed_key: TileKey, *, reason: str) -> list[str]:
        stale: list[str] = []
        for raw_key, status in list(self._tile_status.items()):
            parsed = _parse_canonical_tile_key(raw_key)
            if parsed is None:
                continue
            if parsed.area_id != changed_key.area_id or parsed.kind != changed_key.kind:
                continue
            if parsed.layer_id != changed_key.layer_id or parsed.z_level != changed_key.z_level:
                continue
            dx = abs(int(parsed.x) - int(changed_key.x))
            dy = abs(int(parsed.y) - int(changed_key.y))
            if dx == 0 and dy == 0:
                continue
            if max(dx, dy) != 1:
                continue
            self._tile_status[raw_key] = TileIndexStatus(
                tile_present=status.tile_present,
                rough_indexed=status.rough_indexed,
                sift_indexed=False,
                sift_stale_reason=reason,
                file_mtime_ns=status.file_mtime_ns,
                file_size=status.file_size,
            )
            stale.append(raw_key)
        return stale

    def clear(self) -> None:
        self._tile_status = {}
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "area_id": self.area_id,
            "tiles": {key: asdict(status) for key, status in sorted(self._tile_status.items())},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _replace_with_retry(tmp, self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            tiles = payload.get("tiles", {})
            if not isinstance(tiles, dict):
                return
            for key, value in tiles.items():
                if isinstance(value, dict):
                    self._tile_status[str(key)] = TileIndexStatus(
                        tile_present=bool(value.get("tile_present", False)),
                        rough_indexed=bool(value.get("rough_indexed", False)),
                        sift_indexed=bool(value.get("sift_indexed", False)),
                        sift_stale_reason=str(value.get("sift_stale_reason", "") or ""),
                        file_mtime_ns=int(value.get("file_mtime_ns", 0) or 0),
                        file_size=int(value.get("file_size", 0) or 0),
                    )
        except Exception:
            self._tile_status = {}


def _parse_canonical_tile_key(raw: str) -> TileKey | None:
    parts = raw.split("|")
    if len(parts) != 6:
        return None
    area_id, kind, layer_id, z_part, x, y = parts
    z_level = None if z_part == "base" else int(z_part)
    return TileKey(area_id=area_id, kind=kind, layer_id=layer_id, z_level=z_level, x=int(x), y=int(y))


def parse_canonical_tile_key(raw: str) -> TileKey | None:
    return _parse_canonical_tile_key(raw)


def _replace_with_retry(source: Path, target: Path, *, attempts: int = 5, delay_seconds: float = 0.05) -> None:
    last_error: OSError | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            source.replace(target)
            return
        except OSError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(float(delay_seconds))
    if last_error is not None:
        raise last_error
