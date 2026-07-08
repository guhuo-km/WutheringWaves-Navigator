import cv2
import numpy as np
import pytest

from core.map_context import MapContext, TileKey
from minimap_tile_cache import MinimapTileCache
from minimap_stitched_resources import (
    StitchedResourceBuilder,
    missing_stitched_manifest_area_ids,
    publish_stitched_resources_from_snapshot,
)


def _write_tile(cache_root, key, value):
    cache = MinimapTileCache(cache_root)
    path = cache.tile_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((2, 2, 3), value, dtype=np.uint8))
    return path


def _context():
    return MapContext(
        area_id="906",
        layer_id="default",
        tile_size=2,
        coord_transform={"scaleX": 1, "scaleY": 1, "offsetX": 0, "offsetY": 0},
        map_units_per_tile_x=20.0,
        map_units_per_tile_y=20.0,
    )


def test_publish_base_region_stitches_tiles_and_manifest(tmp_path):
    cache_root = tmp_path / "cache"
    out_root = tmp_path / "stitched"
    left = TileKey("906", "default", None, "standard", 10, 20, leaflet_x=9, leaflet_y=-20)
    right = TileKey("906", "default", None, "standard", 11, 20, leaflet_x=10, leaflet_y=-20)
    _write_tile(cache_root, left, 50)
    _write_tile(cache_root, right, 200)

    manifest = StitchedResourceBuilder(cache_root, out_root, tile_size=2, rough_downsample=2).publish_base_region(
        _context(),
        [left, right],
    )

    fine = cv2.imread(str(out_root / manifest.fine_gray_path), cv2.IMREAD_GRAYSCALE)
    rough = cv2.imread(str(out_root / manifest.rough_color_path), cv2.IMREAD_COLOR)
    assert fine.shape == (2, 4)
    assert rough.shape == (1, 2, 3)
    assert fine[:, :2].mean() == 50
    assert fine[:, 2:].mean() == 200
    assert manifest.origin_tile_x == 10
    assert manifest.origin_tile_y == 20
    assert manifest.origin_leaflet_tile_x == 9
    assert manifest.origin_leaflet_tile_y == -20
    assert manifest.map_units_per_tile_x == 20.0
    assert manifest.map_units_per_tile_y == 20.0
    assert manifest.rough_downsample == 2
    assert (out_root / manifest.manifest_path).exists()
    assert "fine_gray_" in manifest.fine_gray_path
    assert "rough_color_" in manifest.rough_color_path


def test_publish_layered_candidate_composes_only_existing_layer_tiles(tmp_path):
    cache_root = tmp_path / "cache"
    out_root = tmp_path / "stitched"
    unrelated_base = TileKey("906", "default", None, "standard", 10, 20)
    left_base = TileKey("906", "default", None, "standard", 11, 20)
    right_base = TileKey("906", "default", None, "standard", 12, 20)
    left_layer = TileKey("906", "2", -1, "layered", 11, 20)
    right_layer = TileKey("906", "2", -1, "layered", 12, 20)
    _write_tile(cache_root, unrelated_base, 50)
    _write_tile(cache_root, left_base, 100)
    _write_tile(cache_root, right_base, 110)
    _write_tile(cache_root, left_layer, 210)
    _write_tile(cache_root, right_layer, 220)

    manifest = StitchedResourceBuilder(cache_root, out_root, tile_size=2).publish_layered_candidate(
        _context(),
        [unrelated_base, left_base, right_base],
        [left_layer, right_layer],
        candidate_type="layered",
        layer_id="2",
        z_level=-1,
    )

    fine = cv2.imread(str(out_root / manifest.fine_gray_path), cv2.IMREAD_GRAYSCALE)
    assert fine.shape == (2, 4)
    assert fine[:, :2].mean() == 210
    assert fine[:, 2:].mean() == 220
    assert manifest.candidate_type == "layered"
    assert manifest.layer_id == "2"
    assert manifest.z_level == -1
    assert manifest.origin_tile_x == 11
    assert manifest.origin_tile_y == 20
    assert manifest.active_pixel_left == 0
    assert manifest.active_pixel_top == 0
    assert manifest.active_pixel_right == 4
    assert manifest.active_pixel_bottom == 2


def test_publish_layered_candidate_skips_layer_tile_without_matching_base(tmp_path):
    cache_root = tmp_path / "cache"
    out_root = tmp_path / "stitched"
    base = TileKey("906", "default", None, "standard", 11, 20)
    matched_layer = TileKey("906", "2", -1, "layered", 11, 20)
    missing_base_layer = TileKey("906", "2", -1, "layered", 12, 20)
    _write_tile(cache_root, base, 100)
    _write_tile(cache_root, matched_layer, 210)
    _write_tile(cache_root, missing_base_layer, 220)

    manifest = StitchedResourceBuilder(cache_root, out_root, tile_size=2).publish_layered_candidate(
        _context(),
        [base],
        [matched_layer, missing_base_layer],
        candidate_type="layered",
        layer_id="2",
        z_level=-1,
    )

    fine = cv2.imread(str(out_root / manifest.fine_gray_path), cv2.IMREAD_GRAYSCALE)
    assert fine.shape == (2, 2)
    assert fine.mean() == 210
    assert manifest.width == 2
    assert manifest.height == 2
    assert manifest.active_pixel_left == 0
    assert manifest.active_pixel_top == 0
    assert manifest.active_pixel_right == 2
    assert manifest.active_pixel_bottom == 2


def test_publish_failure_keeps_previous_manifest_pointing_to_previous_images(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    out_root = tmp_path / "stitched"
    key = TileKey("906", "default", None, "standard", 10, 20)
    _write_tile(cache_root, key, 50)
    builder = StitchedResourceBuilder(cache_root, out_root, tile_size=2)
    first = builder.publish_base_region(_context(), [key])
    first_manifest_path = out_root / first.manifest_path
    first_manifest_text = first_manifest_path.read_text(encoding="utf-8")

    _write_tile(cache_root, key, 200)
    original_write_image_atomic = builder._write_image_atomic

    def fail_on_rough(path, image):
        if path.name.startswith("rough_color_"):
            raise ValueError("rough_write_failed")
        return original_write_image_atomic(path, image)

    monkeypatch.setattr(builder, "_write_image_atomic", fail_on_rough)

    with pytest.raises(ValueError, match="rough_write_failed"):
        builder.publish_base_region(_context(), [key])

    assert first_manifest_path.read_text(encoding="utf-8") == first_manifest_text
    fine = cv2.imread(str(out_root / first.fine_gray_path), cv2.IMREAD_GRAYSCALE)
    assert fine.mean() == 50


def test_publish_stitched_resources_from_snapshot_refreshes_base_and_layer(tmp_path):
    cache_root = tmp_path / "cache"
    out_root = tmp_path / "stitched"
    base = TileKey("906", "default", None, "standard", 10, 20)
    layer = TileKey("906", "2", -1, "layered", 10, 20)
    _write_tile(cache_root, base, 100)
    _write_tile(cache_root, layer, 250)
    snapshot = {
        "standardTiles": [{"regionId": "906", "x": 10, "y": 20, "url": "base"}],
        "layeredTiles": [{"regionId": "906", "layerId": "2", "zLevel": -1, "x": 10, "y": 20, "url": "layer"}],
        "gravityTiles": [],
    }

    manifests = publish_stitched_resources_from_snapshot(
        snapshot,
        context=_context(),
        cache_root=cache_root,
        output_root=out_root,
        changed_area_ids={"906"},
        tile_size=2,
    )

    assert [manifest.candidate_type for manifest in manifests] == ["base", "layered"]
    assert (out_root / "906" / "base" / "manifest.json").exists()
    assert (out_root / "906" / "layered_2_z_-1" / "manifest.json").exists()


def test_publish_stitched_resources_keeps_gravity_candidate_type(tmp_path):
    cache_root = tmp_path / "cache"
    out_root = tmp_path / "stitched"
    base = TileKey("906", "default", None, "standard", 10, 20)
    gravity = TileKey("906", "9", 0, "gravity", 10, 20)
    _write_tile(cache_root, base, 100)
    _write_tile(cache_root, gravity, 240)
    snapshot = {
        "standardTiles": [{"regionId": "906", "x": 10, "y": 20, "url": "base"}],
        "layeredTiles": [],
        "gravityTiles": [{"regionId": "906", "layerId": "9", "x": 10, "y": 20, "url": "gravity"}],
    }

    manifests = publish_stitched_resources_from_snapshot(
        snapshot,
        context=_context(),
        cache_root=cache_root,
        output_root=out_root,
        changed_area_ids={"906"},
        tile_size=2,
    )

    assert [manifest.candidate_type for manifest in manifests] == ["base", "gravity"]
    assert (out_root / "906" / "gravity_9_z_0" / "manifest.json").exists()


def test_missing_stitched_manifest_area_ids_detects_unpublished_snapshot_candidates(tmp_path):
    snapshot = {
        "standardTiles": [{"regionId": "906", "x": 10, "y": 20, "url": "base"}],
        "layeredTiles": [{"regionId": "906", "layerId": "2", "zLevel": -1, "x": 10, "y": 20, "url": "layer"}],
        "gravityTiles": [{"regionId": "906", "layerId": "9", "x": 11, "y": 20, "url": "gravity"}],
    }

    missing = missing_stitched_manifest_area_ids(snapshot, context=_context(), output_root=tmp_path / "stitched")

    assert missing == {"906"}


def test_missing_stitched_manifest_area_ids_ignores_area_when_all_manifests_exist(tmp_path):
    out_root = tmp_path / "stitched"
    (out_root / "906" / "base").mkdir(parents=True)
    (out_root / "906" / "layered_2_z_-1").mkdir(parents=True)
    (out_root / "906" / "gravity_9_z_0").mkdir(parents=True)
    for path in (
        out_root / "906" / "base" / "manifest.json",
        out_root / "906" / "layered_2_z_-1" / "manifest.json",
        out_root / "906" / "gravity_9_z_0" / "manifest.json",
    ):
        path.write_text("{}", encoding="utf-8")
    snapshot = {
        "standardTiles": [{"regionId": "906", "x": 10, "y": 20, "url": "base"}],
        "layeredTiles": [{"regionId": "906", "layerId": "2", "zLevel": -1, "x": 10, "y": 20, "url": "layer"}],
        "gravityTiles": [{"regionId": "906", "layerId": "9", "x": 11, "y": 20, "url": "gravity"}],
    }

    missing = missing_stitched_manifest_area_ids(snapshot, context=_context(), output_root=out_root)

    assert missing == set()
