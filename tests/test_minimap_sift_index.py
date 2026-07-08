import cv2
import numpy as np
import pytest

from core.map_context import TileKey
from minimap_sift_index import (
    compose_expanded_tile_from_cache,
    expanded_local_to_global_pixel,
    expanded_local_to_map_pixel,
    expanded_local_to_stitched_pixel,
    extract_owned_sift_features_from_expanded_tile,
    is_feature_owned_by_core_tile,
    resolve_tile_image_path,
)


def test_expanded_local_to_global_pixel_removes_overlap_offset():
    assert expanded_local_to_global_pixel(
        tile_x=5,
        tile_y=3,
        tile_size=1024,
        overlap=32,
        expanded_local_x=100,
        expanded_local_y=80,
    ) == (5188.0, 3120.0)


def test_expanded_local_to_map_pixel_uses_official_url_tile_geometry():
    assert expanded_local_to_map_pixel(
        tile_x=2,
        tile_y=-1,
        tile_size=1024,
        overlap=32,
        expanded_local_x=33,
        expanded_local_y=33,
    ) == (1025.0, 1025.0)


def test_expanded_local_to_stitched_pixel_uses_stitched_origin_and_y_direction():
    assert expanded_local_to_stitched_pixel(
        tile_x=-1,
        tile_y=0,
        origin_tile_x=-3,
        origin_tile_y=2,
        tile_size=1024,
        overlap=64,
        expanded_local_x=100,
        expanded_local_y=80,
    ) == (2084.0, 2064.0)


def test_core_ownership_rejects_neighbor_context_features():
    assert is_feature_owned_by_core_tile(
        tile_size=1024,
        overlap=32,
        expanded_local_x=32,
        expanded_local_y=32,
    )
    assert not is_feature_owned_by_core_tile(
        tile_size=1024,
        overlap=32,
        expanded_local_x=12,
        expanded_local_y=32,
    )


def test_extract_owned_sift_features_from_synthetic_tile():
    if not hasattr(cv2, "SIFT_create"):
        pytest.skip("SIFT unavailable")

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.circle(image, (64, 64), 20, (255, 255, 255), thickness=-1)
    cv2.line(image, (20, 20), (108, 108), (180, 180, 180), thickness=3)

    records = extract_owned_sift_features_from_expanded_tile(
        region_id="8",
        tile_x=1,
        tile_y=0,
        expanded_bgr=image,
        tile_size=96,
        overlap=16,
    )

    assert all(record.descriptor.shape == (128,) for record in records)
    assert all(0 <= record.global_x < 96 for record in records)
    assert all(0 <= record.global_y < 96 for record in records)


def test_compose_expanded_tile_from_cache_uses_neighbor_edges(tmp_path):
    tile_size = 8
    root = tmp_path
    base = root / "8" / "standard" / "default" / "base"
    base.mkdir(parents=True)
    colors = {
        (0, 1): (255, 0, 0),
        (1, 1): (0, 255, 0),
        (2, 1): (0, 0, 255),
        (1, 2): (255, 255, 0),
        (1, 0): (0, 255, 255),
    }
    for (x, y), color in colors.items():
        image = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
        image[:, :] = color
        cv2.imwrite(str(base / f"{x}_{y}.png"), image)

    expanded = compose_expanded_tile_from_cache(
        cache_root=root,
        key=TileKey(area_id="8", layer_id="default", z_level=None, kind="standard", x=1, y=1),
        tile_size=tile_size,
        overlap=2,
    )

    assert expanded.shape == (12, 12, 3)
    assert tuple(expanded[2, 2]) == (0, 255, 0)
    assert tuple(expanded[2, 0]) == (255, 0, 0)
    assert tuple(expanded[2, -1]) == (0, 0, 255)
    assert tuple(expanded[0, 2]) == (255, 255, 0)
    assert tuple(expanded[-1, 2]) == (0, 255, 255)


def test_compose_expanded_tile_can_limit_neighbors_to_existing_layer_tiles(tmp_path):
    tile_size = 8
    root = tmp_path
    layer = root / "8" / "layered" / "2" / "-1"
    layer.mkdir(parents=True)
    colors = {
        (0, 1): (255, 0, 0),
        (1, 1): (0, 255, 0),
        (2, 1): (0, 0, 255),
        (1, 2): (255, 255, 0),
    }
    for (x, y), color in colors.items():
        image = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
        image[:, :] = color
        cv2.imwrite(str(layer / f"{x}_{y}.png"), image)

    expanded = compose_expanded_tile_from_cache(
        cache_root=root,
        key=TileKey(area_id="8", layer_id="2", z_level=-1, kind="layered", x=1, y=1),
        tile_size=tile_size,
        overlap=2,
        allowed_neighbor_xy={(2, 1)},
    )

    assert expanded.shape == (12, 12, 3)
    assert tuple(expanded[2, 2]) == (0, 255, 0)
    assert tuple(expanded[2, -1]) == (0, 0, 255)
    assert tuple(expanded[2, 0]) == (0, 0, 0)
    assert tuple(expanded[0, 2]) == (0, 0, 0)


def test_compose_expanded_tile_from_legacy_flat_layer_directory(tmp_path):
    tile_size = 8
    root = tmp_path / "processed_layered_tiles" / "8" / "0"
    root.mkdir(parents=True)
    colors = {
        (0, 1): (255, 0, 0),
        (1, 1): (0, 255, 0),
        (2, 1): (0, 0, 255),
        (1, 2): (255, 255, 0),
        (1, 0): (0, 255, 255),
    }
    for (x, y), color in colors.items():
        image = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
        image[:, :] = color
        cv2.imwrite(str(root / f"8_0_{x}_{y}.png"), image)

    key = TileKey(area_id="8", layer_id="0", z_level=None, kind="standard", x=1, y=1)
    assert resolve_tile_image_path(root, key).name == "8_0_1_1.png"

    expanded = compose_expanded_tile_from_cache(
        cache_root=root,
        key=key,
        tile_size=tile_size,
        overlap=2,
    )

    assert expanded.shape == (12, 12, 3)
    assert tuple(expanded[2, 2]) == (0, 255, 0)
    assert tuple(expanded[2, 0]) == (255, 0, 0)
    assert tuple(expanded[2, -1]) == (0, 0, 255)
    assert tuple(expanded[0, 2]) == (255, 255, 0)
    assert tuple(expanded[-1, 2]) == (0, 255, 255)


def test_extract_owned_sift_features_passes_color_image_to_sift(monkeypatch):
    seen = {}

    class FakeDetector:
        def detectAndCompute(self, image, mask):
            seen["shape"] = image.shape
            keypoint = cv2.KeyPoint(20.0, 20.0, 8.0)
            descriptor = np.ones((1, 128), dtype=np.float32)
            return [keypoint], descriptor

    monkeypatch.setattr("minimap_sift_index.create_sift_detector", lambda: FakeDetector())
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    image[:, :, 1] = 255

    records = extract_owned_sift_features_from_expanded_tile(
        region_id="8",
        tile_x=0,
        tile_y=0,
        expanded_bgr=image,
        tile_size=20,
        overlap=10,
    )

    assert seen["shape"] == (40, 40, 3)
    assert len(records) == 1
