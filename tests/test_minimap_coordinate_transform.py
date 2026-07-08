import pytest

from minimap_coordinate_transform import (
    game_xy_to_stitched_pixel,
    map_pixel_to_url_tile,
    stitched_pixel_to_game_xy,
    url_tile_to_map_pixel,
)
from minimap_stitched_resources import StitchedManifest


def _manifest(**overrides):
    data = {
        "area_id": "906",
        "candidate_type": "base",
        "layer_id": "default",
        "z_level": None,
        "tile_size": 100,
        "origin_tile_x": 10,
        "origin_tile_y": 20,
        "width": 200,
        "height": 100,
        "coord_transform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        "fine_gray_path": "906/base/fine_gray.png",
        "rough_color_path": "906/base/rough_color.png",
        "manifest_path": "906/base/manifest.json",
        "origin_leaflet_tile_x": 9,
        "origin_leaflet_tile_y": -20,
        "map_units_per_tile_x": 20.0,
        "map_units_per_tile_y": 20.0,
    }
    data.update(overrides)
    return StitchedManifest(**data)


def test_stitched_pixel_to_game_xy_uses_leaflet_tile_origin_and_coord_transform():
    x, y = stitched_pixel_to_game_xy(_manifest(), pixel_x=50, pixel_y=25)

    assert x == pytest.approx(1.9)
    assert y == pytest.approx(-3.95)


def test_stitched_pixel_to_game_xy_uses_url_tile_pixels_without_leaflet_tile_coords():
    manifest = _manifest(
        tile_size=1024,
        origin_tile_x=1,
        origin_tile_y=3,
        origin_leaflet_tile_x=None,
        origin_leaflet_tile_y=None,
        map_units_per_tile_x=1024.0,
        map_units_per_tile_y=-1024.0,
        coord_transform={
            "scaleX": 0.01204705882352941,
            "scaleY": 0.01204705882352941,
            "offsetX": 1024.0,
            "offsetY": 0.0,
        },
    )

    x, y = stitched_pixel_to_game_xy(manifest, pixel_x=512, pixel_y=512)

    assert x == pytest.approx(425.0)
    assert y == pytest.approx(-2125.0)


def test_game_xy_to_stitched_pixel_is_inverse_for_url_tile_pixels():
    manifest = _manifest(
        tile_size=1024,
        origin_tile_x=1,
        origin_tile_y=3,
        origin_leaflet_tile_x=None,
        origin_leaflet_tile_y=None,
        map_units_per_tile_x=1024.0,
        map_units_per_tile_y=-1024.0,
        coord_transform={
            "scaleX": 0.01204705882352941,
            "scaleY": 0.01204705882352941,
            "offsetX": 1024.0,
            "offsetY": 0.0,
        },
    )

    pixel_x, pixel_y = game_xy_to_stitched_pixel(manifest, game_x=425.0, game_y=-2125.0)

    assert pixel_x == pytest.approx(512.0)
    assert pixel_y == pytest.approx(512.0)


def test_url_tile_coordinate_demo_semantics():
    assert map_pixel_to_url_tile(1025, 1025, tile_size=1024) == (2, -1, 1, 1)
    assert map_pixel_to_url_tile(-1, -1, tile_size=1024) == (0, 1, 1023, 1023)
    assert url_tile_to_map_pixel(2, -1, 1, 1, tile_size=1024) == (1025, 1025)
    assert url_tile_to_map_pixel(0, 0, 1024, 0, tile_size=1024) == (0, 0)


def test_game_xy_to_stitched_pixel_uses_factor_without_offset_or_y_flip():
    manifest = _manifest(
        tile_size=1024,
        origin_tile_x=-2,
        origin_tile_y=1,
        origin_leaflet_tile_x=None,
        origin_leaflet_tile_y=None,
        map_units_per_tile_x=1024.0,
        map_units_per_tile_y=-1024.0,
        coord_transform={
            "scaleX": 0.01204705882352941,
            "scaleY": 0.01204705882352941,
            "offsetX": 1024.0,
            "offsetY": 0.0,
        },
    )

    pixel_x, pixel_y = game_xy_to_stitched_pixel(manifest, game_x=-1318, game_y=433)

    assert pixel_x == pytest.approx(1484.197647, abs=1e-6)
    assert pixel_y == pytest.approx(1545.637647, abs=1e-6)


def test_stitched_pixel_to_game_xy_rejects_manifest_without_runtime_projection():
    manifest = _manifest(map_units_per_tile_x=None)

    with pytest.raises(ValueError, match="missing_stitched_projection"):
        stitched_pixel_to_game_xy(manifest, pixel_x=50, pixel_y=25)
