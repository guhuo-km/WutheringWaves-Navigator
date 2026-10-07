import inspect
import json

import cv2
import numpy as np

from core.map_context import MapContext, TileKey
from minimap_index_store import CURRENT_TILE_INDEX_VERSION, MinimapIndexStore
from minimap_retrieval_index import CandidateWindow, RetrievalHit
from minimap_roi import NormalizedMinimap
from minimap_sift_index import SiftFeatureRecord
from minimap_stitched_resources import StitchedManifest
from minimap_tile_index_state import (
    COARSE_WINDOW_SIZE,
    TileIndexStateStore,
    TileIndexStatus,
    canonical_tile_key,
)
from minimap_visual_locator import (
    HISTORY_SHORTCUT_RADIUS_PX,
    MinimapVisualLocator,
    VisualMatchConfig,
    _BoundedMapping,
    _COMBINED_SIFT_CACHE_LIMIT,
    _EXISTING_SIFT_ARRAY_CACHE_LIMIT,
    _ROUGH_ENTRIES_CACHE_LIMIT,
    _safe_tile_index_name,
)


def _version2_rough_payload(
    tile_key: TileKey,
    *,
    left: int = 0,
    top: int = 0,
    vector: tuple[float, float, float] = (1.0, 0.0, 0.0),
) -> dict:
    return {
        "version": 2,
        "work_key": f"rough|{canonical_tile_key(tile_key)}",
        "kind": "rough_window",
        "left": int(left),
        "top": int(top),
        "width": COARSE_WINDOW_SIZE,
        "height": COARSE_WINDOW_SIZE,
        "tile_keys": [canonical_tile_key(tile_key)],
        "vector": list(vector),
    }


class _RecordingOrbQuery:
    """Stand-in for OrbQueryIndex: returns fixed document scores and records calls."""

    def __init__(self, scores: dict[str, float], error: Exception | None = None) -> None:
        self._scores = dict(scores)
        self._error = error
        self.calls: list[str] = []

    def score(self, path, image):
        self.calls.append(str(path))
        if self._error is not None:
            raise self._error
        keys = tuple(self._scores)
        return keys, np.array([self._scores[key] for key in keys], dtype=np.float32)


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

    assert config.rough_candidate_limit == 72
    assert config.sift_min_inliers == 5
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
    (root / "stale.json").write_text(json.dumps(_version2_rough_payload(key)), encoding="utf-8")
    MinimapIndexStore(tmp_path, "906").set_area_index_version("906", CURRENT_TILE_INDEX_VERSION)
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
    rough_path.write_text(json.dumps(_version2_rough_payload(key)), encoding="utf-8")
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((16, 16, 3), dtype=np.uint8))
    store = MinimapIndexStore(tmp_path, "906")
    store.set_area_index_version("906", CURRENT_TILE_INDEX_VERSION)
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


def test_visual_locator_cached_rough_entries_do_not_rescan_directory(tmp_path, monkeypatch):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    rough_root = tmp_path / "906" / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    (rough_root / "candidate.json").write_text(json.dumps(_version2_rough_payload(key)), encoding="utf-8")
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((16, 16, 3), dtype=np.uint8))
    store = MinimapIndexStore(tmp_path, "906")
    store.set_area_index_version("906", CURRENT_TILE_INDEX_VERSION)
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_rough_ready(key)

    locator = MinimapVisualLocator(tile_root=tmp_path)
    assert len(locator._load_tile_rough_entries("906")) == 1
    monkeypatch.setattr(
        type(rough_root),
        "glob",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rescanned rough directory")),
    )

    assert len(locator._load_tile_rough_entries("906")) == 1


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
    (rough_root / "candidate.json").write_text(json.dumps(_version2_rough_payload(key)), encoding="utf-8")
    index_store = MinimapIndexStore(tmp_path, "906")
    index_store.set_area_index_version("906", CURRENT_TILE_INDEX_VERSION)
    index_store.set_area_orb_ready("906", True)
    monkeypatch.setattr("minimap_visual_locator.OrbQueryIndex", lambda: _RecordingOrbQuery({}))
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


def test_rough_entry_sift_rect_only_version2_and_coarse_window_size(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    assert locator._rough_entry_sift_rect({"version": 2, "left": -384, "top": -384, "width": COARSE_WINDOW_SIZE, "height": COARSE_WINDOW_SIZE}) == (-384, -384, COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE)
    assert locator._rough_entry_sift_rect({"version": 2, "left": 0, "top": 0, "width": COARSE_WINDOW_SIZE, "height": COARSE_WINDOW_SIZE}) == (0, 0, COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE)
    assert locator._rough_entry_sift_rect({"version": 1, "left": 0, "top": 0, "width": COARSE_WINDOW_SIZE, "height": COARSE_WINDOW_SIZE}) is None
    assert locator._rough_entry_sift_rect({"version": 2, "left": 0, "top": 0, "width": 512, "height": 512}) is None
    assert locator._rough_entry_sift_rect({"version": 2, "left": 0, "top": 0, "width": 384, "height": 384}) is None
    assert locator._rough_entry_sift_rect({"version": 2, "left": 0, "top": 0}) is None
    assert locator._rough_entry_sift_rect({"left": 0, "top": 0, "width": COARSE_WINDOW_SIZE, "height": COARSE_WINDOW_SIZE}) is None


def test_region_feature_indices_boundary_negative_and_cross_tile(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    gx = np.array([[-384, -384], [-1, -1], [0, 0], [-385, -100], [-100, -385]], dtype=np.float32)
    assert locator._region_feature_indices(gx, (-384, -384, 384, 384)).tolist() == [0, 1]
    gx2 = np.array([[1000, 0], [1030, 0], [1383, 0], [1384, 0], [999, 0]], dtype=np.float32)
    assert locator._region_feature_indices(gx2, (1000, 0, 384, 384)).tolist() == [0, 1, 2]
    assert locator._region_feature_indices(np.empty((0, 2), dtype=np.float32), (0, 0, 384, 384)).tolist() == []


def test_region_feature_indices_keeps_descriptor_and_xy_rows_aligned(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    gx = np.array([[0, 0], [10, 10], [500, 500], [20, 20]], dtype=np.float32)
    desc = np.arange(4 * 128, dtype=np.float32).reshape(4, 128)
    idx = locator._region_feature_indices(gx, (0, 0, 384, 384))
    assert idx.tolist() == [0, 1, 3]
    assert np.array_equal(desc[idx], np.vstack([desc[0], desc[1], desc[3]]))
    assert np.array_equal(gx[idx], np.array([[0, 0], [10, 10], [20, 20]], dtype=np.float32))


def test_rough_entries_unavailable_when_area_version_not_current(tmp_path):
    area = "906"
    key = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    rough_root = tmp_path / area / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    (rough_root / "c.json").write_text(json.dumps(_version2_rough_payload(key)), encoding="utf-8")
    tile_path = tmp_path / area / "standard" / "default" / "base" / "2_-1.png"
    tile_path.parent.mkdir(parents=True)
    cv2.imwrite(str(tile_path), np.zeros((16, 16, 3), dtype=np.uint8))
    store = MinimapIndexStore(tmp_path, area)
    store.set_area_index_version(area, 0)
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_rough_ready(key)

    locator = MinimapVisualLocator(tile_root=tmp_path)

    assert locator._load_tile_rough_entries(area) == []
    store.set_area_index_version(area, CURRENT_TILE_INDEX_VERSION)
    assert len(locator._load_tile_rough_entries(area)) == 1
    store.set_area_index_version(area, 0)
    assert locator._load_tile_rough_entries(area) == []


def test_rough_entries_exclude_legacy_and_wrong_size_records(tmp_path):
    area = "906"
    good = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=2, y=-1)
    legacy = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=3, y=-1)
    wrong = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=4, y=-1)
    rough_root = tmp_path / area / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    store = MinimapIndexStore(tmp_path, area)
    store.set_area_index_version(area, CURRENT_TILE_INDEX_VERSION)
    for key in (good, legacy, wrong):
        tile_path = tmp_path / area / "standard" / "default" / "base" / f"{key.x}_{key.y}.png"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(tile_path), np.zeros((16, 16, 3), dtype=np.uint8))
        store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
        store.mark_rough_ready(key)
    (rough_root / "good.json").write_text(json.dumps(_version2_rough_payload(good)), encoding="utf-8")
    legacy_payload = dict(_version2_rough_payload(legacy))
    legacy_payload["version"] = 1
    (rough_root / "legacy.json").write_text(json.dumps(legacy_payload), encoding="utf-8")
    wrong_payload = dict(_version2_rough_payload(wrong))
    wrong_payload["width"] = 512
    wrong_payload["height"] = 512
    (rough_root / "wrong.json").write_text(json.dumps(wrong_payload), encoding="utf-8")

    locator = MinimapVisualLocator(tile_root=tmp_path)
    entries = locator._load_tile_rough_entries(area)

    assert len(entries) == 1
    assert entries[0]["version"] == 2
    assert canonical_tile_key(good) in entries[0]["tile_keys"]


def test_match_restricts_candidates_to_region_and_computes_query_sift_once(tmp_path, monkeypatch):
    area = "906"
    tile = 1024
    k0 = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=0, y=0)
    k1 = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=1, y=0)
    layer_key = TileKey(area_id=area, layer_id="2", z_level=1, kind="standard", x=0, y=0)
    store = MinimapIndexStore(tmp_path, area)
    store.set_area_index_version(area, CURRENT_TILE_INDEX_VERSION)
    store.set_area_orb_ready(area, True)
    orb_query = _RecordingOrbQuery({})
    monkeypatch.setattr("minimap_visual_locator.OrbQueryIndex", lambda: orb_query)
    rough_root = tmp_path / area / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    single_tile_entry = _version2_rough_payload(k0)
    cross_tile_entry = _version2_rough_payload(k0)
    cross_tile_entry["tile_keys"] = [canonical_tile_key(k0), canonical_tile_key(k1)]
    layer_entry = _version2_rough_payload(layer_key, vector=(0.8, 0.6, 0.0))
    for name, payload in (("r0.json", single_tile_entry), ("r1.json", cross_tile_entry), ("r2.json", layer_entry)):
        (rough_root / name).write_text(json.dumps(payload), encoding="utf-8")
    sift_root = tmp_path / area / "indexes" / "sift_tiles"
    sift_root.mkdir(parents=True)
    # Tile (x=0) spans map pixels [-1024, 0) and tile (x=1) spans [0, 1024), y spans [0, 1024).
    tile_features = {
        k0: np.array([[-900, 10], [-500, 200], [-10, 900]], dtype=np.float32),
        k1: np.array([[10, 10], [200, 200], [900, 100], [5000, 5000]], dtype=np.float32),
        # (10, 10) belongs to the neighbour tile of the default plane, so the layer
        # group must not select it.
        layer_key: np.array([[-900, 10], [-500, 200], [-10, 20], [10, 10]], dtype=np.float32),
    }
    for key, global_xy in tile_features.items():
        npz = sift_root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
        np.savez_compressed(
            npz,
            descriptors=np.ones((len(global_xy), 128), dtype=np.float32),
            global_xy=global_xy,
        )
        z_part = "base" if key.z_level is None else str(key.z_level)
        tile_path = tmp_path / area / key.kind / key.layer_id / z_part / f"{key.x}_{key.y}.png"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(tile_path), np.zeros((tile, tile, 3), dtype=np.uint8))
        store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
        store.mark_rough_ready(key)
        store.mark_sift_ready(key, sift_path=str(npz), feature_count=int(len(global_xy)))

    detect_calls = {"count": 0}

    class FakeDetector:
        def detectAndCompute(self, image, mask):
            detect_calls["count"] += 1
            keypoints = [
                cv2.KeyPoint(5.0, 5.0, 1.0),
                cv2.KeyPoint(10.0, 10.0, 1.0),
                cv2.KeyPoint(15.0, 15.0, 1.0),
            ]
            return keypoints, np.ones((3, 128), dtype=np.float32)

    matched_sizes: list[int] = []

    class CountingMatcher:
        def __init__(self, *args, **kwargs):
            pass

        def knnMatch(self, query, candidate, k=2):
            matched_sizes.append(int(np.asarray(candidate).shape[0]))
            return []

    monkeypatch.setattr("minimap_visual_locator.create_sift_detector", lambda: FakeDetector())
    monkeypatch.setattr(
        "minimap_visual_locator.compute_hsv_texture_descriptor",
        lambda image, mask=None: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr(cv2, "BFMatcher", lambda *args, **kwargs: CountingMatcher())
    orb_query = _RecordingOrbQuery({})
    monkeypatch.setattr("minimap_visual_locator.OrbQueryIndex", lambda: orb_query)
    store.set_area_orb_ready(area, True)

    locator = MinimapVisualLocator(tile_root=tmp_path)
    context = MapContext(
        area_id=area,
        layer_id="default",
        tile_size=tile,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    normalized = NormalizedMinimap(
        exact_image=np.zeros((64, 64, 3), dtype=np.uint8),
        mask=np.full((64, 64), 255, dtype=np.uint8),
        rough_color_image=np.zeros((16, 16, 3), dtype=np.uint8),
    )

    assert locator.match(normalized, normalized.mask, context) is None
    assert detect_calls["count"] == 1
    # One round per plane group: the two overlapping HSV windows share a single union,
    # the point outside both tiles is excluded, and the other layer matches independently.
    assert matched_sizes == [6, 3]
    assert orb_query.calls == [str(tmp_path / area / "indexes" / "orb_index.npz")]
    assert locator.last_trace["hsv_candidates_used"] == 3
    assert locator.last_trace["orb_candidates_used"] == 0
    assert locator.last_trace["orb_status"] == "ready"

    group_traces = locator.last_trace["rough_hits"]
    assert [trace["rank"] for trace in group_traces] == [1, 2]
    assert [trace["work_key"] for trace in group_traces] == [
        f"region|{area}|standard|default|base",
        f"region|{area}|standard|2|1",
    ]
    assert [trace["sources"] for trace in group_traces] == [["hsv"], ["hsv"]]
    assert group_traces[0]["source_scores"] == {"hsv": 1.0, "orb": None}
    assert group_traces[1]["source_scores"]["orb"] is None
    assert group_traces[0]["score"] == 1.0
    assert abs(group_traces[1]["score"] - 0.8) < 1e-6
    assert abs(group_traces[1]["source_scores"]["hsv"] - 0.8) < 1e-6
    assert group_traces[0]["tile_keys"] == [canonical_tile_key(k0), canonical_tile_key(k1)]
    assert group_traces[0]["rectangles"] == [(-1024, 0, tile, tile), (0, 0, tile, tile)]
    assert group_traces[0]["feature_count"] == 6
    assert group_traces[1]["tile_keys"] == [canonical_tile_key(layer_key)]
    assert group_traces[1]["rectangles"] == [(-1024, 0, tile, tile)]
    assert group_traces[1]["feature_count"] == 3


def test_match_merges_orb_only_window_into_hsv_region_group(tmp_path, monkeypatch):
    area = "906"
    tile = 1024
    key = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=0, y=0)
    store = MinimapIndexStore(tmp_path, area)
    store.set_area_index_version(area, CURRENT_TILE_INDEX_VERSION)
    store.set_area_orb_ready(area, True)
    rough_root = tmp_path / area / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    hsv_entry = _version2_rough_payload(key, vector=(1.0, 0.0, 0.0))
    orb_entry = _version2_rough_payload(key, left=0, top=100, vector=(0.0, 1.0, 0.0))
    orb_entry["work_key"] = "rough|orb-only-window"
    (rough_root / "a_hsv.json").write_text(json.dumps(hsv_entry), encoding="utf-8")
    (rough_root / "b_orb.json").write_text(json.dumps(orb_entry), encoding="utf-8")

    sift_root = tmp_path / area / "indexes" / "sift_tiles"
    sift_root.mkdir(parents=True)
    # Tile (x=0) spans [-1024, 0); (10, 200) is only inside the ORB window (0, 100, 384, 384),
    # (10, 900) and (5000, 5000) are inside neither rectangle.
    global_xy = np.array([[-900, 10], [-10, 900], [10, 200], [10, 900], [5000, 5000]], dtype=np.float32)
    npz = sift_root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
    np.savez_compressed(npz, descriptors=np.ones((len(global_xy), 128), dtype=np.float32), global_xy=global_xy)
    tile_path = tmp_path / area / key.kind / key.layer_id / "base" / f"{key.x}_{key.y}.png"
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(tile_path), np.zeros((tile, tile, 3), dtype=np.uint8))
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_rough_ready(key)
    store.mark_sift_ready(key, sift_path=str(npz), feature_count=int(len(global_xy)))

    matched_sizes: list[int] = []

    class FakeDetector:
        def detectAndCompute(self, image, mask):
            return (
                [cv2.KeyPoint(5.0, 5.0, 1.0), cv2.KeyPoint(10.0, 10.0, 1.0), cv2.KeyPoint(15.0, 15.0, 1.0)],
                np.ones((3, 128), dtype=np.float32),
            )

    class CountingMatcher:
        def __init__(self, *args, **kwargs):
            pass

        def knnMatch(self, query, candidate, k=2):
            matched_sizes.append(int(np.asarray(candidate).shape[0]))
            return []

    orb_query = _RecordingOrbQuery({hsv_entry["work_key"]: 0.0, orb_entry["work_key"]: 0.5})
    monkeypatch.setattr("minimap_visual_locator.create_sift_detector", lambda: FakeDetector())
    monkeypatch.setattr(
        "minimap_visual_locator.compute_hsv_texture_descriptor",
        lambda image, mask=None: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("minimap_visual_locator.OrbQueryIndex", lambda: orb_query)
    monkeypatch.setattr(cv2, "BFMatcher", lambda *args, **kwargs: CountingMatcher())

    locator = MinimapVisualLocator(
        tile_root=tmp_path,
        config=VisualMatchConfig(rough_candidate_limit=1),
    )
    context = MapContext(
        area_id=area,
        layer_id="default",
        tile_size=tile,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    normalized = NormalizedMinimap(
        exact_image=np.zeros((64, 64, 3), dtype=np.uint8),
        mask=np.full((64, 64), 255, dtype=np.uint8),
        rough_color_image=np.zeros((16, 16, 3), dtype=np.uint8),
    )

    assert locator.match(normalized, normalized.mask, context) is None
    assert matched_sizes == [3]
    assert orb_query.calls == [str(tmp_path / area / "indexes" / "orb_index.npz")]
    assert locator.last_trace["hsv_candidates_used"] == 1
    assert locator.last_trace["orb_candidates_used"] == 1
    assert locator.last_trace["orb_status"] == "ready"

    group_trace = locator.last_trace["rough_hits"][0]
    assert group_trace["rank"] == 1
    assert group_trace["work_key"] == f"region|{area}|standard|default|base"
    assert group_trace["tile_keys"] == [canonical_tile_key(key)]
    assert group_trace["sources"] == ["hsv", "orb"]
    assert group_trace["source_scores"] == {"hsv": 1.0, "orb": 0.5}
    assert group_trace["score"] == 1.0
    assert group_trace["rectangles"] == [(-1024, 0, tile, tile), (0, 100, COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE)]
    assert group_trace["feature_count"] == 3


def _run_hsv_only_match(tmp_path, monkeypatch, orb_query, *, orb_ready: bool):
    """Localize a single-tile area whose only rough window comes from HSV."""
    area = "906"
    key = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=0, y=0)
    store = MinimapIndexStore(tmp_path, area)
    store.set_area_index_version(area, CURRENT_TILE_INDEX_VERSION)
    if orb_ready:
        store.set_area_orb_ready(area, True)
    rough_root = tmp_path / area / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    (rough_root / "a_hsv.json").write_text(json.dumps(_version2_rough_payload(key)), encoding="utf-8")
    sift_root = tmp_path / area / "indexes" / "sift_tiles"
    sift_root.mkdir(parents=True)
    npz = sift_root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
    # Tile (x=0) spans map pixels [-1024, 0); (5000, 5000) is outside that tile.
    global_xy = np.array(
        [[-500, 100], [-480, 100], [-480, 120], [-500, 120], [5000, 5000]],
        dtype=np.float32,
    )
    np.savez_compressed(npz, descriptors=np.ones((len(global_xy), 128), dtype=np.float32), global_xy=global_xy)
    tile_path = tmp_path / area / key.kind / key.layer_id / "base" / f"{key.x}_{key.y}.png"
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(tile_path), np.zeros((1024, 1024, 3), dtype=np.uint8))
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_rough_ready(key)
    store.mark_sift_ready(key, sift_path=str(npz), feature_count=int(len(global_xy)))

    detect_calls = {"count": 0}
    matched_sizes: list[int] = []

    class FakeDetector:
        def detectAndCompute(self, image, mask):
            detect_calls["count"] += 1
            keypoints = [
                cv2.KeyPoint(0.0, 0.0, 1.0),
                cv2.KeyPoint(20.0, 0.0, 1.0),
                cv2.KeyPoint(20.0, 20.0, 1.0),
                cv2.KeyPoint(0.0, 20.0, 1.0),
            ]
            return keypoints, np.ones((4, 128), dtype=np.float32)

    class TranslatingMatcher:
        """Match region row i onto query keypoint i with a ratio-test-passing pair."""

        def __init__(self, *args, **kwargs):
            pass

        def knnMatch(self, query, candidate, k=2):
            rows = int(np.asarray(candidate).shape[0])
            matched_sizes.append(rows)
            return [
                [
                    cv2.DMatch(_queryIdx=index, _trainIdx=index, _distance=10.0),
                    cv2.DMatch(_queryIdx=index, _trainIdx=index, _distance=100.0),
                ]
                for index in range(rows)
            ]

    monkeypatch.setattr("minimap_visual_locator.create_sift_detector", lambda: FakeDetector())
    monkeypatch.setattr(
        "minimap_visual_locator.compute_hsv_texture_descriptor",
        lambda image, mask=None: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr("minimap_visual_locator.OrbQueryIndex", lambda: orb_query)
    monkeypatch.setattr(cv2, "BFMatcher", lambda *args, **kwargs: TranslatingMatcher())

    # 这个 helper 验的是 "ORB 索引不可用时仍能定位"，不是 SIFT 内点门槛。
    # 假数据只产生 4 个内点，门槛阈值由调用方显式给，避免跟着产品默认值漂。
    locator = MinimapVisualLocator(
        tile_root=tmp_path, config=VisualMatchConfig(sift_min_inliers=3)
    )
    context = MapContext(
        area_id=area,
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    normalized = NormalizedMinimap(
        exact_image=np.zeros((64, 64, 3), dtype=np.uint8),
        mask=np.full((64, 64), 255, dtype=np.uint8),
        rough_color_image=np.zeros((16, 16, 3), dtype=np.uint8),
    )

    result = locator.match(normalized, normalized.mask, context)
    trace = locator.last_trace
    group_trace = trace["rough_hits"][0]
    assert detect_calls["count"] == 1
    assert matched_sizes == [4]
    assert group_trace["tile_keys"] == [canonical_tile_key(key)]
    assert group_trace["rectangles"] == [(-1024, 0, 1024, 1024)]
    assert group_trace["sources"] == ["hsv"]
    assert group_trace["source_scores"] == {"hsv": 1.0, "orb": None}
    assert group_trace["score"] == 1.0
    assert group_trace["feature_count"] == 4
    assert group_trace["accepted"] is True
    assert trace["hsv_candidates_used"] == 1
    assert trace["orb_candidates_used"] == 0
    return result, trace


def test_match_runs_hsv_only_when_area_orb_index_not_ready(tmp_path, monkeypatch):
    orb_query = _RecordingOrbQuery({})

    result, trace = _run_hsv_only_match(tmp_path, monkeypatch, orb_query, orb_ready=False)

    assert trace["orb_status"] == "not_ready"
    assert orb_query.calls == []
    assert result is not None
    assert result.candidate.x == -5
    assert result.candidate.y == 1
    assert result.candidate.source == "visual"
    assert result.candidate.reason == "tile_index_sift"
    assert result.sift["inlier_count"] == 4


def test_match_runs_hsv_only_when_area_orb_product_unreadable(tmp_path, monkeypatch):
    orb_query = _RecordingOrbQuery({}, error=FileNotFoundError("orb_index.npz missing"))

    result, trace = _run_hsv_only_match(tmp_path, monkeypatch, orb_query, orb_ready=True)

    assert trace["orb_status"] == "unavailable:FileNotFoundError"
    assert orb_query.calls == [str(tmp_path / "906" / "indexes" / "orb_index.npz")]
    assert result is not None
    assert result.sift["inlier_count"] == 4


def test_rough_entries_cache_evicts_least_recently_used_key_beyond_limit(monkeypatch):
    cache = _BoundedMapping(_ROUGH_ENTRIES_CACHE_LIMIT)
    monkeypatch.setattr(MinimapVisualLocator, "_GLOBAL_TILE_ROUGH_ENTRIES_CACHE", cache)
    keys = [
        ("root", "8", CURRENT_TILE_INDEX_VERSION, f"state-{stamp}", f"db-{stamp}")
        for stamp in range(_ROUGH_ENTRIES_CACHE_LIMIT + 2)
    ]

    for index, key in enumerate(keys):
        cache[key] = [{"work_key": f"window-{index}"}]

    assert len(cache) == _ROUGH_ENTRIES_CACHE_LIMIT
    assert keys[0] not in cache
    assert keys[1] not in cache
    assert keys[-1] in cache

    for _ in range(_ROUGH_ENTRIES_CACHE_LIMIT + 2):
        assert cache.get(keys[-1]) == [{"work_key": f"window-{len(keys) - 1}"}]

    assert len(cache) == _ROUGH_ENTRIES_CACHE_LIMIT
    assert keys[-2] in cache
    assert keys[-3] in cache


def test_existing_sift_array_cache_evicts_least_recently_used_key_beyond_limit(monkeypatch):
    cache = _BoundedMapping(_EXISTING_SIFT_ARRAY_CACHE_LIMIT)
    monkeypatch.setattr(MinimapVisualLocator, "_GLOBAL_EXISTING_SIFT_ARRAY_CACHE", cache)
    keys = [("root", stamp, stamp * 4096) for stamp in range(_EXISTING_SIFT_ARRAY_CACHE_LIMIT + 2)]
    values = [{"descriptors": np.zeros((1, 4), dtype=np.float32)} for _ in keys]

    for key, value in zip(keys, values):
        cache[key] = value

    assert len(cache) == _EXISTING_SIFT_ARRAY_CACHE_LIMIT
    assert keys[0] not in cache
    assert cache.get(keys[-1]) is values[-1]

    for _ in range(_EXISTING_SIFT_ARRAY_CACHE_LIMIT + 2):
        assert cache.get(keys[-1]) is values[-1]

    assert len(cache) == _EXISTING_SIFT_ARRAY_CACHE_LIMIT
    assert keys[-2] in cache


def test_combined_sift_cache_evicts_least_recently_used_key_beyond_limit(tmp_path):
    locator = MinimapVisualLocator(tmp_path)
    cache = locator._combined_sift_cache
    assert cache.limit == _COMBINED_SIFT_CACHE_LIMIT
    keys = [("8", f"tiles-{stamp}", ("state", stamp), ("db", stamp)) for stamp in range(_COMBINED_SIFT_CACHE_LIMIT + 2)]
    values = [
        {
            "descriptors": np.zeros((2, 128), dtype=np.float32),
            "global_xy": np.zeros((2, 2), dtype=np.float32),
        }
        for _ in keys
    ]

    for key, value in zip(keys, values):
        cache[key] = value

    assert len(cache) == _COMBINED_SIFT_CACHE_LIMIT
    assert keys[0] not in cache
    assert keys[1] not in cache
    assert cache.get(keys[-1]) is values[-1]

    for _ in range(_COMBINED_SIFT_CACHE_LIMIT + 2):
        assert cache.get(keys[-1]) is values[-1]

    assert len(cache) == _COMBINED_SIFT_CACHE_LIMIT
    assert keys[-2] in cache


# scaleX = scaleY = 1.0 in the history fixture, so a shortcut centre in map pixels is
# the game coordinate times 100.
_HISTORY_AREA = "906"
_HISTORY_ACCEPT_GAME_XY = (-2.9, 1.1)
_HISTORY_TOO_FEW_GAME_XY = (-3.8, 4.7)
_HISTORY_EMPTY_GAME_XY = (50.0, 50.0)


def _install_history_shortcut_area(tmp_path, monkeypatch, *, match_pairs: bool):
    """Index one tile holding two feature clusters inside its coarse window.

    Four features sit within 300 map pixels of (-290, 110), two within 300 of (-380, 470),
    and one far outside both the tile and every circle.
    """
    area = _HISTORY_AREA
    key = TileKey(area_id=area, layer_id="default", z_level=None, kind="standard", x=0, y=0)
    store = MinimapIndexStore(tmp_path, area)
    store.set_area_index_version(area, CURRENT_TILE_INDEX_VERSION)
    rough_root = tmp_path / area / "indexes" / "rough_windows"
    rough_root.mkdir(parents=True)
    (rough_root / "a_hsv.json").write_text(
        json.dumps(_version2_rough_payload(key, left=-400, top=0)),
        encoding="utf-8",
    )
    sift_root = tmp_path / area / "indexes" / "sift_tiles"
    sift_root.mkdir(parents=True)
    global_xy = np.array(
        [
            [-300.0, 100.0],
            [-280.0, 100.0],
            [-280.0, 120.0],
            [-300.0, 120.0],
            [-350.0, 500.0],
            [-340.0, 510.0],
            [5000.0, 5000.0],
        ],
        dtype=np.float32,
    )
    npz = sift_root / f"{_safe_tile_index_name('sift|' + canonical_tile_key(key))}.npz"
    np.savez_compressed(npz, descriptors=np.ones((len(global_xy), 128), dtype=np.float32), global_xy=global_xy)
    tile_path = tmp_path / area / key.kind / key.layer_id / "base" / f"{key.x}_{key.y}.png"
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(tile_path), np.zeros((1024, 1024, 3), dtype=np.uint8))
    store.record_tile_available(key, png_path=str(tile_path), mtime_ns=1, size=2)
    store.mark_rough_ready(key)
    store.mark_sift_ready(key, sift_path=str(npz), feature_count=int(len(global_xy)))

    hsv_descriptor_calls = {"count": 0}

    class FakeDetector:
        def detectAndCompute(self, image, mask):
            keypoints = [
                cv2.KeyPoint(float(point[0]) + 300.0, float(point[1]) + 300.0, 1.0)
                for point in global_xy
            ]
            return keypoints, np.ones((len(global_xy), 128), dtype=np.float32)

    class FixtureMatcher:
        """Pair candidate row i with query keypoint i, or with nothing when match_pairs is false."""

        def __init__(self, *args, **kwargs):
            pass

        def knnMatch(self, query, candidate, k=2):
            if not match_pairs:
                return []
            rows = int(np.asarray(candidate).shape[0])
            return [
                [
                    cv2.DMatch(_queryIdx=index, _trainIdx=index, _distance=10.0),
                    cv2.DMatch(_queryIdx=index, _trainIdx=index, _distance=100.0),
                ]
                for index in range(rows)
            ]

    def counting_hsv_descriptor(image, mask=None):
        hsv_descriptor_calls["count"] += 1
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)

    monkeypatch.setattr("minimap_visual_locator.create_sift_detector", lambda: FakeDetector())
    monkeypatch.setattr("minimap_visual_locator.compute_hsv_texture_descriptor", counting_hsv_descriptor)
    monkeypatch.setattr(cv2, "BFMatcher", lambda *args, **kwargs: FixtureMatcher())
    return hsv_descriptor_calls


def _history_context_and_image():
    context = MapContext(
        area_id=_HISTORY_AREA,
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    normalized = NormalizedMinimap(
        exact_image=np.zeros((64, 64, 3), dtype=np.uint8),
        mask=np.full((64, 64), 255, dtype=np.uint8),
        rough_color_image=np.zeros((16, 16, 3), dtype=np.uint8),
    )
    return context, normalized


def test_game_xy_to_tile_global_pixel_inverts_tile_global_pixel_to_game_xy(tmp_path):
    locator = MinimapVisualLocator(tile_root=tmp_path)
    scale = 1024.0 / 85000.0
    context = MapContext(
        area_id="8",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": scale, "scaleY": scale, "offsetX": 0.0, "offsetY": 0.0},
    )

    center_px = locator._game_xy_to_tile_global_pixel(context, 2404, 3611)
    back_to_game = locator._tile_global_pixel_to_game_xy(context, center_px[0], center_px[1])

    assert abs(center_px[0] - 2896.112941176471) < 1e-6
    assert abs(center_px[1] - 4350.19294117647) < 1e-6
    assert abs(back_to_game[0] - 2404.0) < 1e-6
    assert abs(back_to_game[1] - 3611.0) < 1e-6


def test_full_acceptance_switches_next_frame_to_history_shortcut(tmp_path, monkeypatch):
    hsv_descriptor_calls = _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    # 验的是 "完全接受后下一帧走快捷路径且不重算 HSV"，与内点门槛默认值无关，故显式给定。
    locator = MinimapVisualLocator(
        tile_root=tmp_path, config=VisualMatchConfig(sift_min_inliers=3)
    )
    context, normalized = _history_context_and_image()

    first = locator.match(normalized, normalized.mask, context)
    first_descriptor_calls = hsv_descriptor_calls["count"]

    assert first is not None
    assert locator.last_trace["match_path"] == "full"
    assert first_descriptor_calls >= 1
    assert locator.last_trace["rough_hits"][0]["feature_count"] == 6

    second = locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_ACCEPT_GAME_XY)
    group_trace = locator.last_trace["rough_hits"][0]

    assert second is not None
    assert locator.last_trace["match_path"] == "history_shortcut"
    assert hsv_descriptor_calls["count"] == first_descriptor_calls
    assert locator.last_trace["hsv_candidates_used"] == 0
    assert abs(locator.last_trace["history_center_px"][0] - (-290.0)) < 1e-6
    assert abs(locator.last_trace["history_center_px"][1] - 110.0) < 1e-6
    assert locator.last_trace["history_radius_px"] == HISTORY_SHORTCUT_RADIUS_PX
    assert group_trace["feature_count"] == 4
    assert group_trace["accepted"] is True


def test_history_shortcut_uses_configured_radius(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    locator = MinimapVisualLocator(
        tile_root=tmp_path,
        config=VisualMatchConfig(history_shortcut_radius_px=400.0),
    )
    context, normalized = _history_context_and_image()

    assert locator.match(normalized, normalized.mask, context) is not None
    result = locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_ACCEPT_GAME_XY)

    assert result is not None
    assert locator.last_trace["match_path"] == "history_shortcut"
    assert locator.last_trace["history_radius_px"] == 400.0


def test_history_shortcut_acceptance_keeps_shortcut_state(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    # 验的是 "快捷路径激活后保持得住"，与内点门槛默认值无关，故显式给定。
    locator = MinimapVisualLocator(
        tile_root=tmp_path, config=VisualMatchConfig(sift_min_inliers=3)
    )
    context, normalized = _history_context_and_image()

    assert locator.match(normalized, normalized.mask, context) is not None
    assert locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_ACCEPT_GAME_XY) is not None
    third = locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_ACCEPT_GAME_XY)

    assert third is not None
    assert locator.last_trace["match_path"] == "history_shortcut"


def test_history_shortcut_rejected_group_yields_no_candidate_and_forces_full(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context, normalized = _history_context_and_image()

    assert locator.match(normalized, normalized.mask, context) is not None
    rejected = locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_TOO_FEW_GAME_XY)
    group_trace = locator.last_trace["rough_hits"][0]

    assert rejected is None
    assert locator.last_trace["match_path"] == "history_shortcut"
    assert group_trace["feature_count"] == 2
    assert group_trace["accepted"] is False
    assert group_trace["skip_reason"] == "too_few_features"

    next_frame = locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_TOO_FEW_GAME_XY)

    assert next_frame is not None
    assert locator.last_trace["match_path"] == "full"


def test_history_shortcut_without_overlapping_window_yields_no_candidate_and_forces_full(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context, normalized = _history_context_and_image()

    assert locator.match(normalized, normalized.mask, context) is not None
    assert locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_EMPTY_GAME_XY) is None
    assert locator.last_trace["match_path"] == "history_shortcut"
    assert locator.last_trace["rough_hits"] == []
    assert locator.last_trace["rough_candidates_used"] == 0

    next_frame = locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_EMPTY_GAME_XY)

    assert next_frame is not None
    assert locator.last_trace["match_path"] == "full"


def test_history_shortcut_not_used_without_active_game_xy(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context, normalized = _history_context_and_image()

    assert locator.match(normalized, normalized.mask, context) is not None
    assert locator.match(normalized, normalized.mask, context) is not None

    assert locator.last_trace["match_path"] == "full"


def test_full_rejection_does_not_enter_history_shortcut(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=False)
    locator = MinimapVisualLocator(tile_root=tmp_path)
    context, normalized = _history_context_and_image()

    assert locator.match(normalized, normalized.mask, context) is None
    assert locator.last_trace["rough_hits"][0]["accepted"] is False
    assert locator.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_ACCEPT_GAME_XY) is None

    assert locator.last_trace["match_path"] == "full"


def test_history_shortcut_state_is_only_of_the_current_locator_instance(tmp_path, monkeypatch):
    _install_history_shortcut_area(tmp_path, monkeypatch, match_pairs=True)
    context, normalized = _history_context_and_image()
    locator = MinimapVisualLocator(tile_root=tmp_path)

    assert locator.match(normalized, normalized.mask, context) is not None
    rebuilt = MinimapVisualLocator(tile_root=tmp_path)
    assert rebuilt.match(normalized, normalized.mask, context, active_game_xy=_HISTORY_ACCEPT_GAME_XY) is not None

    assert rebuilt.last_trace["match_path"] == "full"
