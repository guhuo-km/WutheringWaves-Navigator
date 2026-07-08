from __future__ import annotations

import math


def map_pixel_to_url_tile(
    map_x: int | float,
    map_y: int | float,
    tile_size: int = 1024,
) -> tuple[int, int, float, float]:
    size = float(tile_size)
    if size <= 0:
        raise ValueError("invalid_tile_size")
    tile_x = math.floor(float(map_x) / size) + 1
    tile_y = -math.floor(float(map_y) / size)
    local_x = float(map_x) - ((tile_x - 1) * size)
    local_y = float(map_y) - (-tile_y * size)
    return int(tile_x), int(tile_y), local_x, local_y


def url_tile_to_map_pixel(
    tile_x: int,
    tile_y: int,
    local_x: int | float,
    local_y: int | float,
    tile_size: int = 1024,
) -> tuple[float, float]:
    size = float(tile_size)
    if size <= 0:
        raise ValueError("invalid_tile_size")
    map_x = (int(tile_x) - 1) * size + float(local_x)
    map_y = -int(tile_y) * size + float(local_y)
    return map_x, map_y
