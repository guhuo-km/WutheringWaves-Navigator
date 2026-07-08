from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from core.map_context import TileKey
from minimap_tile_geometry import map_pixel_to_url_tile
from minimap_tile_cache import MinimapTileCache


@dataclass(frozen=True)
class TileDownloadInput:
    key: TileKey
    url: str
    expected_size: int | None = None


@dataclass(frozen=True)
class TileDownloadResult:
    changed_area_ids: set[str]
    downloaded_sizes: dict[TileKey, int]
    failures: dict[TileKey, str]
    input_count: int = 0
    skipped_count: int = 0


def plan_missing_tiles(keys: Iterable[TileKey], cache_root: Path) -> list[TileKey]:
    cache = MinimapTileCache(cache_root)
    return [key for key in keys if not cache.tile_path(key).exists()]


def plan_missing_tiles_with_sizes(
    expected: dict[TileKey, int | None],
    cache_root: Path,
) -> list[TileKey]:
    cache = MinimapTileCache(cache_root)
    missing: list[TileKey] = []
    for key, size in expected.items():
        if not cache.is_same_cached_tile(key, size):
            missing.append(key)
    return missing


def _read_int(tile: dict[str, Any], name: str, default: int | None = None) -> int | None:
    raw = tile.get(name, default)
    if raw is None:
        return None
    return int(raw)


def _read_size(tile: dict[str, Any]) -> int | None:
    raw = tile.get("size", tile.get("expectedSize", tile.get("contentLength")))
    if raw is None:
        return None
    size = int(raw)
    return size if size >= 0 else None


def _convert_tile(tile: dict[str, Any], kind: str) -> TileDownloadInput:
    area_id = str(tile["regionId"])
    layer_id = str(tile.get("layerId") or "default")
    z_level = _read_int(tile, "zLevel", None)
    if kind == "standard":
        layer_id = "default"
        z_level = None
    elif kind == "gravity" and z_level is None:
        z_level = 0

    key = TileKey(
        area_id=area_id,
        layer_id=layer_id,
        z_level=z_level,
        kind=kind,
        x=int(tile["x"]),
        y=int(tile["y"]),
        leaflet_x=_read_int(tile, "leafletTileX", None),
        leaflet_y=_read_int(tile, "leafletTileY", None),
        leaflet_z=_read_int(tile, "leafletTileZ", None),
    )
    return TileDownloadInput(key=key, url=str(tile["url"]), expected_size=_read_size(tile))


def convert_tile_snapshot_to_download_inputs(snapshot: dict[str, Any]) -> list[TileDownloadInput]:
    inputs: list[TileDownloadInput] = []
    for tile in snapshot.get("standardTiles", []) or []:
        inputs.append(_convert_tile(tile, "standard"))
    for tile in snapshot.get("layeredTiles", []) or []:
        inputs.append(_convert_tile(tile, "layered"))
    for tile in snapshot.get("gravityTiles", []) or []:
        inputs.append(_convert_tile(tile, "gravity"))
    return inputs


def generate_standard_tile_inputs_for_game_xy(
    area_id: str,
    game_xy: tuple[float, float],
    coord_transform: dict[str, Any],
    tile_size: int,
    tile_base_url: str,
    oss_params: str | None = None,
    radius: int = 0,
) -> list[TileDownloadInput]:
    game_x, game_y = game_xy
    json_x = game_x * 100
    json_y = game_y * 100
    map_x = json_x * float(coord_transform["scaleX"])
    map_y = json_y * float(coord_transform["scaleY"])
    center_x, center_y, _, _ = map_pixel_to_url_tile(map_x, map_y, tile_size)

    base_url = tile_base_url.rstrip("/")
    query = ""
    if oss_params:
        query = oss_params if oss_params.startswith("?") else f"?{oss_params}"

    inputs: list[TileDownloadInput] = []
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            key = TileKey(area_id=str(area_id), layer_id="default", z_level=None, kind="standard", x=x, y=y)
            url = f"{base_url}/{area_id}/{area_id}_{x}_{y}.png{query}"
            inputs.append(TileDownloadInput(key=key, url=url))
    return inputs


def _fetch_url_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "WutheringWaves-Navigator/TileCache"})
    with urlopen(request, timeout=20) as response:
        return response.read()


def download_missing_tiles(
    inputs: Iterable[TileDownloadInput],
    cache_root: Path,
    fetch_bytes: Callable[[str], bytes] = _fetch_url_bytes,
    refresh_changed_regions: Callable[[set[str]], None] | None = None,
) -> TileDownloadResult:
    cache = MinimapTileCache(cache_root)
    changed_area_ids: set[str] = set()
    downloaded_sizes: dict[TileKey, int] = {}
    failures: dict[TileKey, str] = {}
    input_count = 0
    skipped_count = 0

    for item in inputs:
        input_count += 1
        path = cache.tile_path(item.key)
        if cache.is_same_cached_tile(item.key, item.expected_size):
            skipped_count += 1
            continue

        tmp_path = path.with_name(f"{path.name}.tmp")
        try:
            data = fetch_bytes(item.url)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(data)
            tmp_path.replace(path)
            cache.record_tile_size(item.key, len(data))
            changed_area_ids.add(item.key.area_id)
            downloaded_sizes[item.key] = len(data)
        except Exception as exc:
            failures[item.key] = str(exc)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    if changed_area_ids and refresh_changed_regions is not None:
        try:
            refresh_changed_regions(changed_area_ids)
        except Exception as exc:
            failures[TileKey("refresh", "default", None, "refresh", 0, 0)] = str(exc)

    return TileDownloadResult(
        changed_area_ids=changed_area_ids,
        downloaded_sizes=downloaded_sizes,
        failures=failures,
        input_count=input_count,
        skipped_count=skipped_count,
    )
