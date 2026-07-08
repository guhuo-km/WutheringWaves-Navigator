from __future__ import annotations

import math

from minimap_stitched_resources import StitchedManifest
from minimap_tile_geometry import map_pixel_to_url_tile, url_tile_to_map_pixel


def _require_number(value: int | float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"missing_stitched_projection:{name}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"missing_stitched_projection:{name}")
    return number


def stitched_pixel_to_leaflet_lat_lng(
    manifest: StitchedManifest,
    pixel_x: int | float,
    pixel_y: int | float,
) -> tuple[float, float]:
    units_x = _require_number(manifest.map_units_per_tile_x, "map_units_per_tile_x")
    units_y = _require_number(manifest.map_units_per_tile_y, "map_units_per_tile_y")
    tile_size = _require_number(manifest.tile_size, "tile_size")
    if tile_size <= 0:
        raise ValueError("missing_stitched_projection:tile_size")

    origin_x = manifest.origin_leaflet_tile_x
    origin_y = manifest.origin_leaflet_tile_y
    if origin_x is None:
        origin_x = manifest.origin_tile_x
    if origin_y is None:
        origin_y = manifest.origin_tile_y

    tile_x = _require_number(origin_x, "origin_tile_x")
    tile_y = _require_number(origin_y, "origin_tile_y")
    if manifest.origin_leaflet_tile_x is None or manifest.origin_leaflet_tile_y is None:
        lng, lat = url_tile_to_map_pixel(
            int(tile_x),
            int(tile_y),
            pixel_x,
            pixel_y,
            int(tile_size),
        )
    else:
        lng = (tile_x * units_x) + (float(pixel_x) * units_x / tile_size)
        lat = (tile_y * units_y) + (float(pixel_y) * units_y / tile_size)
    return lat, lng


def leaflet_lat_lng_to_game_xy(
    lat: float,
    lng: float,
    coord_transform: dict,
) -> tuple[float, float]:
    scale_x = _require_number(coord_transform.get("scaleX"), "coord_transform.scaleX")
    scale_y = _require_number(coord_transform.get("scaleY"), "coord_transform.scaleY")
    if scale_x == 0 or scale_y == 0:
        raise ValueError("missing_stitched_projection:coord_transform.scale")

    json_x = float(lng) / scale_x
    json_y = float(lat) / scale_y
    return json_x / 100.0, json_y / 100.0


def game_xy_to_leaflet_lat_lng(
    game_x: int | float,
    game_y: int | float,
    coord_transform: dict,
) -> tuple[float, float]:
    scale_x = _require_number(coord_transform.get("scaleX"), "coord_transform.scaleX")
    scale_y = _require_number(coord_transform.get("scaleY"), "coord_transform.scaleY")

    json_x = float(game_x) * 100.0
    json_y = float(game_y) * 100.0
    lng = json_x * scale_x
    lat = json_y * scale_y
    return lat, lng


def game_xy_to_stitched_pixel(
    manifest: StitchedManifest,
    game_x: int | float,
    game_y: int | float,
) -> tuple[float, float]:
    lat, lng = game_xy_to_leaflet_lat_lng(game_x, game_y, manifest.coord_transform)
    units_x = _require_number(manifest.map_units_per_tile_x, "map_units_per_tile_x")
    units_y = _require_number(manifest.map_units_per_tile_y, "map_units_per_tile_y")
    tile_size = _require_number(manifest.tile_size, "tile_size")
    if tile_size <= 0:
        raise ValueError("missing_stitched_projection:tile_size")

    origin_x = manifest.origin_leaflet_tile_x
    origin_y = manifest.origin_leaflet_tile_y
    if origin_x is None:
        origin_x = manifest.origin_tile_x
    if origin_y is None:
        origin_y = manifest.origin_tile_y

    tile_x = _require_number(origin_x, "origin_tile_x")
    tile_y = _require_number(origin_y, "origin_tile_y")
    if manifest.origin_leaflet_tile_x is None or manifest.origin_leaflet_tile_y is None:
        origin_map_x, origin_map_y = url_tile_to_map_pixel(
            int(tile_x),
            int(tile_y),
            0,
            0,
            int(tile_size),
        )
        pixel_x = lng - origin_map_x
        pixel_y = lat - origin_map_y
    else:
        if units_x == 0 or units_y == 0:
            raise ValueError("missing_stitched_projection:map_units_per_tile")
        pixel_x = (lng - tile_x * units_x) * tile_size / units_x
        pixel_y = (lat - tile_y * units_y) * tile_size / units_y
    return pixel_x, pixel_y


def stitched_pixel_to_game_xy(
    manifest: StitchedManifest,
    pixel_x: int | float,
    pixel_y: int | float,
) -> tuple[float, float]:
    lat, lng = stitched_pixel_to_leaflet_lat_lng(manifest, pixel_x, pixel_y)
    return leaflet_lat_lng_to_game_xy(lat, lng, manifest.coord_transform)
