import inspect
import json

import cv2
import numpy as np

from core.map_context import MapContext, TileKey
from minimap_index_store import MinimapIndexStore
from minimap_retrieval_index import CandidateWindow, RetrievalHit
from minimap_roi import NormalizedMinimap
from minimap_sift_index import SiftFeatureRecord
from minimap_stitched_resources import StitchedManifest
from minimap_tile_index_state import TileIndexStateStore, TileIndexStatus, canonical_tile_key
from minimap_visual_locator import (
    MinimapVisualLocator,
    VisualMatchConfig,
    _safe_tile_index_name,
)


def test_visual_locator_match_signature_has_no_ocr_coordinate_input():
    params = inspect.signature(MinimapVisualLocator.match).parameters
    assert "ocr_coord" not in params
    assert "ocr_candidate" not in params


def test_visual_locator_requires_area_context(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    ctx = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1, "scaleY": 1, "offsetX": 0, "offsetY": 0},
    )
    assert locator.search_root(ctx) == tmp_path / "906" / "default"


def test_visual_locator_match_does_not_take_ocr_anchor():
    params = inspect.signature(MinimapVisualLocator.match).parameters
    assert "ocr_xy" not in params
    assert "ocr_anchor" not in params
    assert "previous_ocr" not in params


def test_visual_match_config_defaults_to_sift_retrieval():
    config = VisualMatchConfig()

    assert config.rough_candidate_limit == 20
    assert config.sift_min_inliers == 3
    assert config.sift_ratio == 0.75


def test_visual_locator_has_no_full_fine_sift_index_builder():
    assert not hasattr(MinimapVisualLocator, "_load_or_build_sift_index")


def test_visual_locator_maps_rough_hit_to_base_tile_keys(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    manifest = StitchedManifest(
        area_id="906",
        candidate_type="base",
        layer_id="default",
        z_level=None,
        tile_size=1024,
        origin_tile_x=-4,
        origin_tile_y=5,
        width=4096,
        height=4096,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        fine_gray_path="906/base/fine_gray.png",
        rough_color_path="906/base/rough_color.png",
        manifest_path="906/base/manifest.json",
        rough_downsample=4,
    )
    hit = RetrievalHit(
        candidate=CandidateWindow(
            region_id="906",
            window_id="906:0:0:256:256",
            left=256,
            top=256,
            width=512,
            height=512,
            center_x=512.0,
            center_y=512.0,
            tile_min_x=1,
            tile_max_x=2,
            tile_min_y=1,
            tile_max_y=2,
        ),
        score=0.9,
        rank=1,
    )

    keys = locator._tile_keys_for_rough_hit(manifest, hit)

    assert [(key.kind, key.layer_id, key.z_level, key.x, key.y) for key in keys] == [
        ("standard", "default", None, -3, 4),
        ("standard", "default", None, -2, 4),
        ("standard", "default", None, -3, 3),
        ("standard", "default", None, -2, 3),
    ]


def test_visual_locator_persists_rough_descriptor_index(tmp_path, monkeypatch):
    manifest = StitchedManifest(
        area_id="906",
        candidate_type="base",
        layer_id="default",
        z_level=None,
        tile_size=16,
        origin_tile_x=0,
        origin_tile_y=0,
        width=64,
        height=64,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        fine_gray_path="906/base/fine_gray.png",
        rough_color_path="906/base/rough_color.png",
        manifest_path="906/base/manifest.json",
        rough_downsample=1,
    )
    rough_path = tmp_path / manifest.rough_color_path
    rough_path.parent.mkdir(parents=True)
    rough = np.zeros((64, 64, 3), dtype=np.uint8)
    rough[16:48, 16:48] = (0, 200, 0)
    cv2.imwrite(str(rough_path), rough)
    query = rough[16:48, 16:48].copy()
    mask = np.full((32, 32), 255, dtype=np.uint8)

    locator = MinimapVisualLocator(tmp_path, VisualMatchConfig(sift_window_size=32, sift_stride=16))
    first = locator._rough_retrieval_hits(manifest=manifest, rough=rough, query_color=query, query_mask=mask)
    assert first
    assert list((tmp_path / "906" / "indexes").glob("rough_*.npz"))
    assert list((tmp_path / "906" / "indexes").glob("rough_*.json"))

    MinimapVisualLocator._GLOBAL_ROUGH_DESCRIPTOR_CACHE.clear()
    monkeypatch.setattr("minimap_visual_locator.build_candidate_windows", lambda **kwargs: (_ for _ in ()).throw(AssertionError("rebuilt rough index")))
    second = MinimapVisualLocator(tmp_path, VisualMatchConfig(sift_window_size=32, sift_stride=16))._rough_retrieval_hits(
        manifest=manifest,
        rough=rough,
        query_color=query,
        query_mask=mask,
    )

    assert [hit.candidate.window_id for hit in second] == [hit.candidate.window_id for hit in first]


def test_visual_locator_persists_tile_sift_index(tmp_path, monkeypatch):
    manifest = StitchedManifest(
        area_id="906",
        candidate_type="base",
        layer_id="default",
        z_level=None,
        tile_size=16,
        origin_tile_x=0,
        origin_tile_y=0,
        width=16,
        height=16,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        fine_gray_path="906/base/fine_gray.png",
        rough_color_path="906/base/rough_color.png",
        manifest_path="906/base/manifest.json",
        rough_downsample=1,
    )
    key = TileKey(
        area_id="906",
        layer_id="default",
        z_level=None,
        kind="standard",
        x=0,
        y=0,
    )
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "0_0.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.full((16, 16, 3), 120, dtype=np.uint8))

    def fake_extract(**kwargs):
        return [
            SiftFeatureRecord(
                region_id="906",
                tile_x=0,
                tile_y=0,
                global_x=5.0,
                global_y=6.0,
                local_x=5.0,
                local_y=6.0,
                size=1.0,
                angle=0.0,
                response=1.0,
                descriptor=np.ones(128, dtype=np.float32),
            )
        ]

    monkeypatch.setattr("minimap_visual_locator.extract_owned_sift_features_from_expanded_tile", fake_extract)
    locator = MinimapVisualLocator(tmp_path)
    first = locator._load_or_build_tile_sift_index(manifest, [key])
    assert first["descriptors"].shape == (1, 128)
    assert list((tmp_path / "906" / "indexes").glob("sift_*.npz"))
    assert list((tmp_path / "906" / "indexes").glob("sift_*.json"))

    MinimapVisualLocator._GLOBAL_TILE_SIFT_CACHE.clear()
    monkeypatch.setattr(
        "minimap_visual_locator.extract_owned_sift_features_from_expanded_tile",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("rebuilt sift index")),
    )
    second = MinimapVisualLocator(tmp_path)._load_or_build_tile_sift_index(manifest, [key])

    assert second["descriptors"].shape == (1, 128)
    assert second["global_xy"].tolist() == [[5.0, 6.0]]


def test_visual_locator_extracts_query_color_and_mask(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    exact_image = np.zeros((260, 260, 3), dtype=np.uint8)
    rough_color_image = np.full((52, 52, 3), 200, dtype=np.uint8)
    mask = np.full((260, 260), 255, dtype=np.uint8)
    normalized = NormalizedMinimap(
        exact_image=exact_image,
        mask=mask,
        rough_color_image=rough_color_image,
    )

    color, out_mask = locator._query_color_and_mask(normalized, mask)

    assert color.shape == (260, 260, 3)
    assert out_mask.shape == (260, 260)


def test_visual_locator_match_does_not_build_sift_during_recognition(tmp_path, monkeypatch):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=32,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    normalized = NormalizedMinimap(
        exact_image=np.zeros((64, 64, 3), dtype=np.uint8),
        mask=np.full((64, 64), 255, dtype=np.uint8),
        rough_color_image=np.zeros((16, 16, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        "minimap_visual_locator.extract_owned_sift_features_from_expanded_tile",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("recognition built sift")),
    )
    monkeypatch.setattr(
        "minimap_visual_locator.build_candidate_windows",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("recognition built rough windows")),
    )

    assert locator.match(normalized, normalized.mask, context) is None
    assert locator.last_trace.get("rough_index_source") == "tile_index"


def test_visual_locator_skips_stale_tile_sift_index(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    root = tmp_path / "906" / "indexes" / "sift_tiles"
    root.mkdir(parents=True)
    np.savez_compressed(
        root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz",
        descriptors=np.ones((3, 128), dtype=np.float32),
        global_xy=np.ones((3, 2), dtype=np.float32),
    )
    store = TileIndexStateStore(tmp_path, "906")
    store.set_tile_status(
        key,
        TileIndexStatus(
            tile_present=True,
            rough_indexed=True,
            sift_indexed=False,
            sift_stale_reason="neighbor_added",
            file_mtime_ns=1,
            file_size=2,
        ),
    )
    store.save()

    locator = MinimapVisualLocator(tile_root=tmp_path)

    assert locator._load_existing_sift_tiles("906", [key]) is None


def test_visual_locator_recovers_sift_state_when_npz_and_tile_exist(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((32, 32, 3), dtype=np.uint8))

    root = tmp_path / "906" / "indexes" / "sift_tiles"
    root.mkdir(parents=True)
    np.savez_compressed(
        root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz",
        descriptors=np.ones((3, 128), dtype=np.float32),
        global_xy=np.ones((3, 2), dtype=np.float32),
    )
    store = TileIndexStateStore(tmp_path, "906")
    store.set_tile_status(
        key,
        TileIndexStatus(
            tile_present=True,
            rough_indexed=True,
            sift_indexed=False,
            file_mtime_ns=0,
            file_size=0,
        ),
    )
    store.save()

    locator = MinimapVisualLocator(tile_root=tmp_path)

    index = locator._load_existing_sift_tiles("906", [key])

    assert index is not None
    assert index["descriptors"].shape == (3, 128)
    status = TileIndexStateStore(tmp_path, "906").get_tile_status(key)
    assert status.sift_indexed is True
    assert status.file_size > 0
    assert status.file_mtime_ns > 0


def test_visual_locator_loads_sift_when_sqlite_ready_even_if_json_stale(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((32, 32, 3), dtype=np.uint8))
    sift_root = tmp_path / "906" / "indexes" / "sift_tiles"
    sift_root.mkdir(parents=True)
    sift_path = sift_root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
    np.savez_compressed(
        sift_path,
        descriptors=np.ones((3, 128), dtype=np.float32),
        global_xy=np.ones((3, 2), dtype=np.float32),
    )
    store = MinimapIndexStore(tmp_path, "906")
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_sift_ready(key, sift_path=str(sift_path), feature_count=3)
    json_store = TileIndexStateStore(tmp_path, "906")
    json_store.set_tile_status(
        key,
        TileIndexStatus(
            tile_present=True,
            rough_indexed=True,
            sift_indexed=False,
            sift_stale_reason="neighbor_added",
            file_mtime_ns=1,
            file_size=2,
        ),
    )
    json_store.save()

    index = MinimapVisualLocator(tile_root=tmp_path)._load_existing_sift_tiles("906", [key])

    assert index is not None
    assert index["descriptors"].shape == (3, 128)


def test_visual_locator_skips_rough_entries_without_indexed_tile_state(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    root = tmp_path / "906" / "indexes" / "rough_windows"
    root.mkdir(parents=True)
    (root / "stale.json").write_text(
        json.dumps(
            {
                "version": 1,
                "work_key": "rough|stale",
                "window_type": "tile",
                "tile_keys": [canonical_tile_key(key)],
                "vector": [1.0, 0.0, 0.0],
            }
        ),
        encoding="utf-8",
    )
    store = TileIndexStateStore(tmp_path, "906")
    store.set_tile_status(
        key,
        TileIndexStatus(
            tile_present=True,
            rough_indexed=False,
            sift_indexed=True,
            file_mtime_ns=1,
            file_size=2,
        ),
    )
    store.save()

    locator = MinimapVisualLocator(tile_root=tmp_path)

    assert locator._load_tile_rough_entries("906") == []


def test_visual_locator_caches_ready_rough_entries_until_index_files_change(tmp_path, monkeypatch):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    rough_root = tmp_path / "906" / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    rough_path = rough_root / "candidate.json"
    rough_path.write_text(
        json.dumps(
            {
                "version": 1,
                "work_key": "rough|candidate",
                "window_type": "tile",
                "tile_keys": [canonical_tile_key(key)],
                "vector": [1.0, 0.0, 0.0],
            }
        ),
        encoding="utf-8",
    )
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((16, 16, 3), dtype=np.uint8))
    store = MinimapIndexStore(tmp_path, "906")
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_rough_ready(key)

    read_calls = []
    original_read_text = type(rough_path).read_text

    def counting_read_text(self, *args, **kwargs):
        if self == rough_path:
            read_calls.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(rough_path), "read_text", counting_read_text)
    locator = MinimapVisualLocator(tile_root=tmp_path)

    first = locator._load_tile_rough_entries("906")
    second = locator._load_tile_rough_entries("906")

    assert len(first) == 1
    assert second == first
    assert read_calls == [str(rough_path)]


def test_visual_locator_caches_sift_npz_until_file_changes(tmp_path, monkeypatch):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((32, 32, 3), dtype=np.uint8))
    sift_root = tmp_path / "906" / "indexes" / "sift_tiles"
    sift_root.mkdir(parents=True)
    sift_path = sift_root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
    np.savez_compressed(
        sift_path,
        descriptors=np.ones((3, 128), dtype=np.float32),
        global_xy=np.ones((3, 2), dtype=np.float32),
    )
    store = MinimapIndexStore(tmp_path, "906")
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_sift_ready(key, sift_path=str(sift_path), feature_count=3)

    load_calls = []
    original_np_load = np.load

    def counting_np_load(path, *args, **kwargs):
        if str(path) == str(sift_path):
            load_calls.append(str(path))
        return original_np_load(path, *args, **kwargs)

    monkeypatch.setattr("minimap_visual_locator.np.load", counting_np_load)
    locator = MinimapVisualLocator(tile_root=tmp_path)

    first = locator._load_existing_sift_tiles("906", [key])
    second = locator._load_existing_sift_tiles("906", [key])

    assert first is not None
    assert second is not None
    assert second["descriptors"].shape == (3, 128)
    assert load_calls == [str(sift_path)]


def test_visual_locator_match_does_not_write_sift_index_files(tmp_path, monkeypatch):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    rough_root = tmp_path / "906" / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    (rough_root / "candidate.json").write_text(
        json.dumps(
            {
                "version": 1,
                "work_key": "rough|candidate",
                "window_type": "tile",
                "tile_keys": [canonical_tile_key(key)],
                "vector": [1.0, 0.0, 0.0],
            }
        ),
        encoding="utf-8",
    )
    store = TileIndexStateStore(tmp_path, "906")
    store.set_tile_status(
        key,
        TileIndexStatus(
            tile_present=True,
            rough_indexed=True,
            sift_indexed=False,
            file_mtime_ns=1,
            file_size=2,
        ),
    )
    store.save()

    class FakeDetector:
        def detectAndCompute(self, image, mask):
            keypoints = [
                cv2.KeyPoint(10.0, 10.0, 1.0),
                cv2.KeyPoint(20.0, 20.0, 1.0),
                cv2.KeyPoint(30.0, 30.0, 1.0),
            ]
            descriptors = np.ones((3, 128), dtype=np.float32)
            return keypoints, descriptors

    monkeypatch.setattr("minimap_visual_locator.create_sift_detector", lambda: FakeDetector())
    monkeypatch.setattr(
        "minimap_visual_locator.compute_hsv_texture_descriptor",
        lambda image, mask=None: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr(
        "minimap_visual_locator.extract_owned_sift_features_from_expanded_tile",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("recognition built sift")),
    )
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    normalized = NormalizedMinimap(
        exact_image=np.zeros((64, 64, 3), dtype=np.uint8),
        mask=np.full((64, 64), 255, dtype=np.uint8),
        rough_color_image=np.zeros((16, 16, 3), dtype=np.uint8),
    )

    assert locator.match(normalized, normalized.mask, context) is None
    assert not list((tmp_path / "906" / "indexes" / "sift_tiles").glob("*.npz"))


def test_visual_locator_selects_best_confidence_across_base_and_layer_candidates(tmp_path):
    def write_candidate(name: str, patch_value: int, candidate_type: str, layer_id: str, z_level: int | None) -> None:
        fine = np.zeros((100, 100), dtype=np.uint8)
        fine[40:50, 30:40] = patch_value
        rough = cv2.cvtColor(cv2.resize(fine, (50, 50), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)

        resource_dir = tmp_path / "906" / name
        resource_dir.mkdir(parents=True)
        cv2.imwrite(str(resource_dir / "fine_gray.png"), fine)
        cv2.imwrite(str(resource_dir / "rough_color.png"), rough)
        manifest = {
            "area_id": "906",
            "candidate_type": candidate_type,
            "layer_id": layer_id,
            "z_level": z_level,
            "tile_size": 100,
            "origin_tile_x": 1,
            "origin_tile_y": 1,
            "width": 100,
            "height": 100,
            "coord_transform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
            "fine_gray_path": f"906/{name}/fine_gray.png",
            "rough_color_path": f"906/{name}/rough_color.png",
            "manifest_path": f"906/{name}/manifest.json",
            "origin_leaflet_tile_x": 0,
            "origin_leaflet_tile_y": 0,
            "map_units_per_tile_x": 100.0,
            "map_units_per_tile_y": 100.0,
        }
        if candidate_type == "layered":
            manifest.update(
                {
                    "active_pixel_left": 20,
                    "active_pixel_top": 30,
                    "active_pixel_right": 50,
                    "active_pixel_bottom": 60,
                }
            )
        (resource_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    write_candidate("base", 220, "base", "default", None)
    write_candidate("layer_2_z_1", 255, "layered", "2", 1)
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=100,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    manifest = locator._load_manifest(tmp_path / "906" / "layer_2_z_1" / "manifest.json")

    assert locator._manifest_can_match(manifest, active_game_xy=(0.35, 0.45)) is True


def test_visual_locator_excludes_layer_candidates_without_active_game_xy(tmp_path):
    def write_candidate(
        name: str,
        patch_left: int,
        patch_value: int,
        candidate_type: str,
        extra: dict | None = None,
    ) -> None:
        fine = np.zeros((100, 100), dtype=np.uint8)
        fine[40:50, patch_left:patch_left + 10] = patch_value
        rough = cv2.cvtColor(cv2.resize(fine, (50, 50), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
        resource_dir = tmp_path / "906" / name
        resource_dir.mkdir(parents=True)
        cv2.imwrite(str(resource_dir / "fine_gray.png"), fine)
        cv2.imwrite(str(resource_dir / "rough_color.png"), rough)
        manifest = {
            "area_id": "906",
            "candidate_type": candidate_type,
            "layer_id": "default" if candidate_type == "base" else "2",
            "z_level": None if candidate_type == "base" else 1,
            "tile_size": 100,
            "origin_tile_x": 1,
            "origin_tile_y": 0,
            "width": 100,
            "height": 100,
            "coord_transform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
            "fine_gray_path": f"906/{name}/fine_gray.png",
            "rough_color_path": f"906/{name}/rough_color.png",
            "manifest_path": f"906/{name}/manifest.json",
            "origin_leaflet_tile_x": None,
            "origin_leaflet_tile_y": None,
            "map_units_per_tile_x": 100.0,
            "map_units_per_tile_y": -100.0,
        }
        if extra:
            manifest.update(extra)
        (resource_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    write_candidate("base", 30, 220, "base")
    write_candidate(
        "layer_2_z_1",
        70,
        255,
        "layered",
        {
            "active_pixel_left": 60,
            "active_pixel_top": 30,
            "active_pixel_right": 90,
            "active_pixel_bottom": 70,
        },
    )
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=100,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    manifest = locator._load_manifest(tmp_path / "906" / "layer_2_z_1" / "manifest.json")

    assert locator._manifest_can_match(manifest, active_game_xy=None) is False


def test_visual_locator_includes_layer_candidate_when_active_game_xy_is_inside_layer_bounds(tmp_path):
    def write_candidate(name: str, patch_left: int, patch_value: int, candidate_type: str) -> None:
        fine = np.zeros((100, 100), dtype=np.uint8)
        fine[40:50, patch_left:patch_left + 10] = patch_value
        rough = cv2.cvtColor(cv2.resize(fine, (50, 50), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
        resource_dir = tmp_path / "906" / name
        resource_dir.mkdir(parents=True)
        cv2.imwrite(str(resource_dir / "fine_gray.png"), fine)
        cv2.imwrite(str(resource_dir / "rough_color.png"), rough)
        manifest = {
            "area_id": "906",
            "candidate_type": candidate_type,
            "layer_id": "default" if candidate_type == "base" else "2",
            "z_level": None if candidate_type == "base" else 1,
            "tile_size": 100,
            "origin_tile_x": 1,
            "origin_tile_y": 0,
            "width": 100,
            "height": 100,
            "coord_transform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
            "fine_gray_path": f"906/{name}/fine_gray.png",
            "rough_color_path": f"906/{name}/rough_color.png",
            "manifest_path": f"906/{name}/manifest.json",
            "origin_leaflet_tile_x": None,
            "origin_leaflet_tile_y": None,
            "map_units_per_tile_x": 100.0,
            "map_units_per_tile_y": -100.0,
        }
        if candidate_type == "layered":
            manifest.update(
                {
                    "active_pixel_left": 60,
                    "active_pixel_top": 30,
                    "active_pixel_right": 90,
                    "active_pixel_bottom": 70,
                }
            )
        (resource_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    write_candidate("base", 30, 220, "base")
    write_candidate("layer_2_z_1", 70, 255, "layered")
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=100,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    manifest = locator._load_manifest(tmp_path / "906" / "layer_2_z_1" / "manifest.json")

    assert locator._manifest_can_match(manifest, active_game_xy=(0.75, 0.45)) is True
