import json

import cv2
import numpy as np

from core.map_context import TileKey
from minimap_index_store import (
    CURRENT_TILE_INDEX_VERSION,
    UNAVAILABLE_TILE_INDEX_VERSION,
    MinimapIndexStore,
    MinimapIndexTileStatus,
)
from minimap_tile_cache import MinimapTileCache
from minimap_tile_index_state import (
    COARSE_WINDOW_SIZE,
    TileIndexStateStore,
    TileIndexStatus,
    canonical_coarse_window_key,
    canonical_tile_key,
    coarse_tile_origin,
    coarse_window_rects_for_tile,
)
from minimap_tile_indexer import TileIndexQueue, TileIndexWork, _safe_name
from minimap_orb_index import OrbInvertedIndex
from minimap_orb_store import (
    ORB_AREA_INDEX_NAME,
    OrbAreaIndex,
    load_orb_area_index,
    save_orb_area_index,
)

AREA = "8"


def _tile(x: int, y: int, *, kind: str = "standard", layer_id: str = "default", z_level=None) -> TileKey:
    return TileKey(area_id=AREA, layer_id=layer_id, z_level=z_level, kind=kind, x=x, y=y)


def _write_tile(root, key: TileKey, color=(0, 255, 0), tile_size=32):
    path = MinimapTileCache(root).tile_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
    image[:, :] = color
    cv2.imwrite(str(path), image)
    return path


def _write_layer_tile(root, key: TileKey, bgr=(110, 120, 130), alpha=128, tile_size=32):
    path = MinimapTileCache(root).tile_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((tile_size, tile_size, 4), dtype=np.uint8)
    image[:, :, :3] = bgr
    image[:, :, 3] = alpha
    cv2.imwrite(str(path), image)
    return path


def _mark_area_current(root, area_id: str = AREA) -> None:
    """Declare the area current so an incremental enqueue is allowed to run at all."""
    MinimapIndexStore(root, area_id).set_area_index_version(area_id, CURRENT_TILE_INDEX_VERSION)


def _rebuild_work(area_id: str = AREA) -> TileIndexWork:
    return TileIndexWork(kind="area_rebuild", work_key=f"area_rebuild|{area_id}", tile_keys=(), area_id=area_id)


def _rough_records(root, area_id: str = AREA) -> list[dict]:
    folder = root / area_id / "indexes" / "rough_windows"
    if not folder.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


def _sift_files(root, area_id: str = AREA) -> list:
    folder = root / area_id / "indexes" / "sift_tiles"
    if not folder.exists():
        return []
    return sorted(folder.glob("*.npz"))


def _orb_file(root, work_key: str, area_id: str = AREA):
    return root / area_id / "indexes" / "orb_descriptors" / f"{_safe_name(work_key)}.npy"


def _write_orb_product(path, vocabulary: np.ndarray) -> None:
    """Write a stand-in area ORB product carrying the given vocabulary centers."""
    rows = int(vocabulary.shape[0])
    index = OrbAreaIndex(
        document_keys=("rough|placeholder",),
        vocabulary=np.asarray(vocabulary, dtype=np.uint8),
        inverted_index=OrbInvertedIndex(
            word_offsets=np.zeros(rows + 1, dtype=np.int64),
            document_ids=np.zeros(0, dtype=np.int32),
            weights=np.zeros(0, dtype=np.float32),
            idf=np.zeros(rows, dtype=np.float32),
            document_count=0,
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    save_orb_area_index(path, index)


def _no_features(monkeypatch):
    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", lambda **kwargs: [])


def _recording_descriptor(monkeypatch):
    seen: list[np.ndarray] = []
    vector = np.arange(6, dtype=np.float32)

    def fake_descriptor(image):
        seen.append(image)
        return vector

    monkeypatch.setattr("minimap_tile_indexer.compute_hsv_texture_descriptor", fake_descriptor)
    return seen, vector


def _own_window_rects(key: TileKey, tile_size: int = 32) -> set[tuple[int, int]]:
    return set(coarse_window_rects_for_tile(key.x, key.y, tile_size=tile_size, window_size=COARSE_WINDOW_SIZE))


def test_enqueue_changed_tile_adds_absolute_windows_and_own_sift_work(tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_changed_tile(key)

    rough_works = [work for work in result.queued if work.kind == "rough_window"]
    sift_works = [work for work in result.queued if work.kind == "sift_tile"]
    assert [work.tile_keys for work in sift_works if work.tile_keys == (key,)]
    assert {work.rect[:2] for work in rough_works} == _own_window_rects(key)
    for work in rough_works:
        assert work.rect == (work.rect[0], work.rect[1], COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE)
        assert work.work_key == f"rough|{canonical_coarse_window_key(key, work.rect[0], work.rect[1])}"
        assert all(tile.area_id == AREA for tile in work.tile_keys)
    status = TileIndexStateStore(tmp_path, AREA).get_tile_status(key)
    assert status.tile_present is True
    assert status.file_size > 0


def test_changed_tile_in_legacy_area_requests_full_rebuild_instead_of_incremental_work(tmp_path):
    first = _tile(10, 20)
    second = _tile(11, 20)
    _write_tile(tmp_path, first)
    _write_tile(tmp_path, second)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_changed_tile(first)
    during = queue.enqueue_changed_tile(second)

    assert result.queued == ()
    assert during.queued == ()
    assert queue.pending_count == 1
    assert _rough_records(tmp_path) == []
    assert MinimapIndexStore(tmp_path, AREA).get_tile_status(first).exists is False
    assert MinimapIndexStore(tmp_path, AREA).get_area_index_version(AREA) == UNAVAILABLE_TILE_INDEX_VERSION


def test_windows_over_the_same_map_rect_are_one_document_across_tiles(tmp_path):
    left_tile = _tile(10, 20)
    right_tile = _tile(11, 20)
    _write_tile(tmp_path, left_tile)
    _write_tile(tmp_path, right_tile)
    _mark_area_current(tmp_path)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    first = queue.enqueue_changed_tile(left_tile)
    from_right = queue._coarse_works_for_tile(right_tile)
    second = queue.enqueue_changed_tile(right_tile)

    first_rough_keys = {work.work_key for work in first.queued if work.kind == "rough_window"}
    # Two tiles one 32 map pixel apart sit inside the same 384 lattice window, so the
    # window the right tile computes is already the document the left tile queued.
    assert {work.work_key for work in from_right} == first_rough_keys
    assert [work for work in second.queued if work.kind == "rough_window"] == []
    assert queue.pending_count == len(first_rough_keys) + 2
    for work in first.queued:
        if work.kind == "rough_window":
            assert set(work.tile_keys) == {left_tile, right_tile}


def test_process_work_marks_rough_and_sift_ready_in_sqlite(monkeypatch, tmp_path):
    key = _tile(16, -13)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    _no_features(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(key)

    for work in result.queued:
        queue.process_work(work)

    status = MinimapIndexStore(tmp_path, AREA).get_tile_status(key)
    assert status.rough_ready is True
    assert status.sift_ready is True


def test_rough_window_document_uses_the_agreed_version_two_field_set(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    seen, vector = _recording_descriptor(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    rough_work = next(work for work in queue.enqueue_changed_tile(key).queued if work.kind == "rough_window")

    queue.process_work(rough_work)

    records = _rough_records(tmp_path)
    assert len(records) == 1
    payload = records[0]
    assert set(payload) == {
        "version",
        "left",
        "top",
        "width",
        "height",
        "tile_keys",
        "vector",
        "work_key",
        "kind",
    }
    assert payload["version"] == 2
    assert payload["kind"] == "rough_window"
    assert payload["work_key"] == rough_work.work_key
    assert (payload["left"], payload["top"], payload["width"], payload["height"]) == rough_work.rect
    assert payload["width"] == payload["height"] == COARSE_WINDOW_SIZE
    assert payload["tile_keys"] == [canonical_tile_key(tile) for tile in rough_work.tile_keys]
    assert payload["vector"] == vector.tolist()
    assert seen[0].shape == (COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE, 3)
    orb_path = _orb_file(tmp_path, rough_work.work_key)
    assert orb_path.exists()
    descriptors = np.load(orb_path)
    assert descriptors.dtype == np.uint8
    assert descriptors.ndim == 2
    assert descriptors.shape[1] == 32


def test_all_black_window_drops_rough_json_and_orb_npy_but_keeps_readiness(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    _recording_descriptor(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    rough_work = next(work for work in queue.enqueue_changed_tile(key).queued if work.kind == "rough_window")

    queue.process_work(rough_work)

    json_path = tmp_path / AREA / "indexes" / "rough_windows" / f"{_safe_name(rough_work.work_key)}.json"
    orb_path = _orb_file(tmp_path, rough_work.work_key)
    assert json_path.exists() and orb_path.exists()

    _write_tile(tmp_path, key, color=(0, 0, 0))
    second = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    second.process_work(rough_work)

    assert json_path.exists() is False
    assert orb_path.exists() is False
    status = MinimapIndexStore(tmp_path, AREA).get_tile_status(key)
    assert status.rough_ready is True
    assert TileIndexStateStore(tmp_path, AREA).get_tile_status(key).rough_indexed is True


def test_coarse_window_image_zero_fills_map_area_without_tiles(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key, color=(7, 11, 13))
    _mark_area_current(tmp_path)
    _recording_descriptor(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    rough_work = next(work for work in queue.enqueue_changed_tile(key).queued if work.kind == "rough_window")

    image = queue._compose_coarse_window_image(rough_work)

    tile_left, tile_top = coarse_tile_origin(key.x, key.y, 32)
    row = tile_top - rough_work.rect[1]
    column = tile_left - rough_work.rect[0]
    assert image.shape == (COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE, 3)
    assert 0 < row and 0 < column and row + 32 < COARSE_WINDOW_SIZE and column + 32 < COARSE_WINDOW_SIZE
    assert tuple(int(value) for value in image[row, column]) == (7, 11, 13)
    assert tuple(int(value) for value in image[row + 31, column + 31]) == (7, 11, 13)
    assert tuple(int(value) for value in image[row - 1, column]) == (0, 0, 0)
    assert tuple(int(value) for value in image[row, column - 1]) == (0, 0, 0)
    assert int(image.sum()) == 32 * 32 * sum((7, 11, 13))


def test_layered_window_whose_overlay_is_everywhere_transparent_is_not_indexed(tmp_path):
    base = _tile(10, 20)
    hidden = _tile(10, 20, kind="layered", layer_id="2", z_level=-1)
    shown = _tile(10, 20, kind="layered", layer_id="3", z_level=-1)
    _write_tile(tmp_path, base)
    _write_layer_tile(tmp_path, hidden, alpha=0)
    _write_layer_tile(tmp_path, shown, alpha=90)
    _mark_area_current(tmp_path)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    hidden_result = queue.enqueue_changed_tile(hidden)
    shown_result = queue.enqueue_changed_tile(shown)

    assert [work for work in hidden_result.queued if work.kind == "rough_window"] == []
    assert [work for work in hidden_result.queued if work.kind == "sift_tile"]
    rough_shown = [work for work in shown_result.queued if work.kind == "rough_window"]
    assert {work.rect[:2] for work in rough_shown} == _own_window_rects(shown)
    for work in rough_shown:
        assert work.tile_keys == (shown,)


def test_layered_rough_window_image_composites_the_matching_base_tile(tmp_path):
    base = _tile(10, 20)
    layer = _tile(10, 20, kind="layered", layer_id="2", z_level=-1)
    _write_tile(tmp_path, base, color=(10, 20, 30))
    _write_layer_tile(tmp_path, layer, bgr=(110, 120, 130), alpha=128)
    _mark_area_current(tmp_path)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(layer)
    rough_work = next(work for work in result.queued if work.kind == "rough_window")

    image = queue._compose_coarse_window_image(rough_work)

    tile_left, tile_top = coarse_tile_origin(layer.x, layer.y, 32)
    assert tuple(int(value) for value in image[tile_top - rough_work.rect[1], tile_left - rough_work.rect[0]]) == (
        60,
        70,
        80,
    )


def test_enqueue_stale_sift_tiles_skips_an_area_that_is_being_rebuilt(tmp_path):
    key = _tile(8, -6)
    _write_tile(tmp_path, key)
    store = TileIndexStateStore(tmp_path, AREA)
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
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    queue.enqueue_changed_tile(key)

    result = queue.enqueue_stale_sift_tiles(AREA)

    assert result.queued == ()
    assert queue.pending_count == 1


def test_enqueue_stale_sift_tiles_requeues_existing_stale_entries(tmp_path):
    key = _tile(8, -6)
    _write_tile(tmp_path, key)
    store = TileIndexStateStore(tmp_path, AREA)
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
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_stale_sift_tiles(AREA)

    assert result.queued_count == 1
    assert result.queued[0].kind == "sift_tile"
    assert result.queued[0].tile_keys == (key,)


def test_enqueue_missing_indexes_for_area_requests_one_rebuild_per_area(tmp_path):
    key = _tile(16, -13)
    _write_tile(tmp_path, key)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_missing_indexes_for_area(AREA)
    again = queue.enqueue_missing_indexes_for_area(AREA)

    assert result.queued_count == 1
    assert result.queued[0].kind == "area_rebuild"
    assert result.queued[0].area_id == AREA
    assert again.queued == ()
    assert queue.pending_count == 1


def test_enqueue_missing_indexes_for_tiles_only_checks_given_keys(tmp_path):
    current = _tile(16, -13)
    historical = _tile(99, 99)
    _write_tile(tmp_path, current)
    _write_tile(tmp_path, historical)
    _mark_area_current(tmp_path)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_missing_indexes_for_tiles([current])

    assert result.queued_count >= 2
    assert result.incomplete_tiles == (current,)
    queued_tile_keys = {work.tile_keys[0] for work in result.queued if work.tile_keys}
    assert current in queued_tile_keys
    assert historical not in queued_tile_keys
    assert MinimapIndexStore(tmp_path, AREA).get_tile_status(current).tile_present is True
    assert MinimapIndexStore(tmp_path, AREA).get_tile_status(historical).exists is False


def test_enqueue_missing_indexes_batches_status_queries_per_area(monkeypatch, tmp_path):
    area8 = _tile(16, -13)
    area906 = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=3)
    _write_tile(tmp_path, area8)
    _write_tile(tmp_path, area906)
    created = []
    queried = []

    class FakeStore:
        def __init__(self, tile_root, area_id):
            created.append(str(area_id))

        def get_tile_statuses(self, keys):
            keys = list(keys)
            queried.append([canonical_tile_key(key) for key in keys])
            return {
                canonical_tile_key(key): MinimapIndexTileStatus(
                    tile_key=canonical_tile_key(key),
                    tile_present=True,
                    rough_ready=True,
                    sift_ready=True,
                )
                for key in keys
            }

    monkeypatch.setattr("minimap_tile_indexer.MinimapIndexStore", FakeStore)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_missing_indexes_for_tiles([area8, area906])

    assert result.queued_count == 0
    assert created == [AREA, "906"]
    assert len(queried) == 2


def test_process_one_work_passes_color_image_to_sift(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    seen = {}

    def fake_extract(**kwargs):
        seen["shape"] = kwargs["expanded_bgr"].shape
        return []

    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", fake_extract)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(key)
    sift_work = next(work for work in result.queued if work.kind == "sift_tile")

    queue.process_work(sift_work)

    assert seen["shape"][2] == 3


def test_process_sift_work_repairs_zero_file_stamp(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    _no_features(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(key)
    sift_work = next(work for work in result.queued if work.kind == "sift_tile")
    store = TileIndexStateStore(tmp_path, AREA)
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

    queue.process_work(sift_work)

    status = TileIndexStateStore(tmp_path, AREA).get_tile_status(key)
    assert status.sift_indexed is True
    assert status.file_mtime_ns > 0
    assert status.file_size > 0


def test_area_rebuild_clears_legacy_artifacts_and_regenerates_the_whole_plane(monkeypatch, tmp_path):
    left = _tile(10, 20)
    right = _tile(11, 20)
    png_left = _write_tile(tmp_path, left)
    png_right = _write_tile(tmp_path, right)
    _no_features(monkeypatch)
    _recording_descriptor(monkeypatch)
    index_root = tmp_path / AREA / "indexes"
    (index_root / "rough_windows").mkdir(parents=True)
    legacy_json = index_root / "rough_windows" / "rough__legacy.json"
    legacy_json.write_text(json.dumps({"work_key": "rough|legacy", "vector": [0.0]}), encoding="utf-8")
    (index_root / "sift_tiles").mkdir(parents=True)
    legacy_npz = index_root / "sift_tiles" / "sift__legacy.npz"
    legacy_npz.write_bytes(b"legacy")
    (index_root / "orb_descriptors").mkdir(parents=True)
    legacy_npy = index_root / "orb_descriptors" / "orb__legacy.npy"
    legacy_npy.write_bytes(b"legacy")
    state = TileIndexStateStore(tmp_path, AREA)
    state.set_tile_status(left, TileIndexStatus(tile_present=True, rough_indexed=True, sift_indexed=True, file_mtime_ns=1, file_size=1))
    state.save()
    MinimapIndexStore(tmp_path, AREA).mark_rough_ready(left, rough_count=9)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    queue.process_work(_rebuild_work())

    assert legacy_json.exists() is False
    assert legacy_npz.exists() is False
    assert legacy_npy.exists() is False
    assert png_left.exists() and png_right.exists()
    expected_rects = _own_window_rects(left) | _own_window_rects(right)
    records = _rough_records(tmp_path)
    assert len(records) == len(expected_rects)
    assert {(record["left"], record["top"]) for record in records} == expected_rects
    assert {canonical_coarse_window_key(left, record["left"], record["top"]) for record in records} == {
        record["work_key"].removeprefix("rough|") for record in records
    }
    for record in records:
        assert set(record["tile_keys"]) == {canonical_tile_key(left), canonical_tile_key(right)}
    assert len(_sift_files(tmp_path)) == 2
    store = MinimapIndexStore(tmp_path, AREA)
    assert store.get_area_index_version(AREA) == CURRENT_TILE_INDEX_VERSION
    assert store.is_area_orb_ready(AREA) is True
    assert (index_root / "orb_index.npz").exists()
    assert store.health_summary()["failed"] == 0
    for key in (left, right):
        status = store.get_tile_status(key)
        assert status.tile_present is True
        assert status.rough_ready is True
        assert status.sift_ready is True
        reloaded = TileIndexStateStore(tmp_path, AREA).get_tile_status(key)
        assert reloaded.rough_indexed is True
        assert reloaded.sift_indexed is True


def test_area_rebuild_keeps_the_area_unavailable_when_a_window_fails(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _no_features(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    failing = {queue._coarse_works_for_tile(key)[0].work_key}
    original_process = queue.process_work

    def run_works_with_one_failure(work):
        if work.kind == "rough_window" and work.work_key in failing:
            raise RuntimeError("no descriptor")
        original_process(work)

    monkeypatch.setattr(queue, "process_work", run_works_with_one_failure)
    errors: list[str] = []
    queue.on_error = errors.append

    queue._process_area_rebuild(_rebuild_work())

    store = MinimapIndexStore(tmp_path, AREA)
    assert store.get_area_index_version(AREA) == UNAVAILABLE_TILE_INDEX_VERSION
    assert any("area_rebuild_incomplete" in message for message in errors)
    assert any(failing.intersection(message.split(":")) for message in errors)
    # The windows that did succeed stay on disk; the area version is what keeps a query
    # away from a half rebuilt area.
    assert store.get_tile_status(key).rough_ready is True
    retried = queue.enqueue_changed_tile(key)
    assert retried.queued == ()
    assert queue.pending_count == 1


def test_area_rebuild_does_not_publish_orb_ready_when_builder_fails(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _no_features(monkeypatch)
    _recording_descriptor(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    def boom(index_root, **kwargs):
        raise RuntimeError("orb build failed")

    monkeypatch.setattr("minimap_tile_indexer.build_area_orb_index", boom)
    errors: list[str] = []
    queue.on_error = errors.append

    queue._execute_work(_rebuild_work())

    store = MinimapIndexStore(tmp_path, AREA)
    assert store.get_area_index_version(AREA) == UNAVAILABLE_TILE_INDEX_VERSION
    assert store.is_area_orb_ready(AREA) is False
    assert (tmp_path / AREA / "indexes" / "orb_index.npz").exists() is False
    assert any("orb build failed" in message for message in errors)


def test_area_orb_build_work_publishes_index_and_sets_ready(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _no_features(monkeypatch)
    _recording_descriptor(monkeypatch)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    for work in queue.enqueue_changed_tile(key).queued:
        queue.process_work(work)
    orb_work = TileIndexWork(
        kind="area_orb_build",
        work_key=f"area_orb_build|{AREA}",
        tile_keys=(),
        area_id=AREA,
    )

    queue._execute_work(orb_work)

    store = MinimapIndexStore(tmp_path, AREA)
    assert (tmp_path / AREA / "indexes" / "orb_index.npz").exists()
    assert store.is_area_orb_ready(AREA) is True


def test_enqueue_changed_tile_marks_area_orb_not_ready(tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    store = MinimapIndexStore(tmp_path, AREA)
    store.set_area_orb_ready(AREA, True)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    queue.enqueue_changed_tile(key)

    assert store.is_area_orb_ready(AREA) is False


def test_area_reconcile_publishes_area_orb_when_current_but_not_ready(tmp_path):
    _mark_area_current(tmp_path)
    store = MinimapIndexStore(tmp_path, AREA)
    assert store.is_area_orb_ready(AREA) is False
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    reconcile = TileIndexWork(kind="area_reconcile", work_key="area_reconcile", tile_keys=())

    queue._execute_work(reconcile)

    orb_builds = [work for work in queue._pending if work.kind == "area_orb_build"]
    assert len(orb_builds) == 1
    assert orb_builds[0].work_key == f"area_orb_build|{AREA}"
    assert orb_builds[0].area_id == AREA


def test_area_reconcile_skips_area_orb_when_already_ready(tmp_path):
    _mark_area_current(tmp_path)
    store = MinimapIndexStore(tmp_path, AREA)
    store.set_area_orb_ready(AREA, True)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    reconcile = TileIndexWork(kind="area_reconcile", work_key="area_reconcile", tile_keys=())

    queue._execute_work(reconcile)

    orb_builds = [work for work in queue._pending if work.kind == "area_orb_build"]
    assert len(orb_builds) == 0


def test_incremental_area_orb_publishes_once_after_last_window_work(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    _no_features(monkeypatch)
    _recording_descriptor(monkeypatch)
    store = MinimapIndexStore(tmp_path, AREA)
    store.set_area_orb_ready(AREA, True)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_changed_tile(key)
    assert store.is_area_orb_ready(AREA) is False

    for work in result.queued:
        queue._run_work(work)

    orb_builds = [work for work in queue._pending if work.kind == "area_orb_build"]
    assert len(orb_builds) == 1
    assert orb_builds[0].work_key == f"area_orb_build|{AREA}"
    assert orb_builds[0].area_id == AREA

    queue._run_work(orb_builds[0])

    assert (tmp_path / AREA / "indexes" / "orb_index.npz").exists()
    assert store.is_area_orb_ready(AREA) is True


def test_area_orb_build_reuses_existing_vocabulary_and_trains_when_unreadable(monkeypatch, tmp_path):
    work = TileIndexWork(
        kind="area_orb_build",
        work_key=f"area_orb_build|{AREA}",
        tile_keys=(),
        area_id=AREA,
    )
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    store = MinimapIndexStore(tmp_path, AREA)
    path = tmp_path / AREA / "indexes" / ORB_AREA_INDEX_NAME
    existing_vocabulary = np.arange(3 * 32, dtype=np.uint8).reshape(3, 32)
    received: dict[str, object] = {}

    def stub_build(_index_root, *, vocabulary=None, **_kwargs):
        received["vocabulary"] = vocabulary
        rows = int(vocabulary.shape[0]) if vocabulary is not None else 1
        return OrbAreaIndex(
            document_keys=("rough|placeholder",),
            vocabulary=(np.asarray(vocabulary, dtype=np.uint8) if vocabulary is not None else np.zeros((1, 32), dtype=np.uint8)),
            inverted_index=OrbInvertedIndex(
                word_offsets=np.zeros(rows + 1, dtype=np.int64),
                document_ids=np.zeros(0, dtype=np.int32),
                weights=np.zeros(0, dtype=np.float32),
                idf=np.zeros(rows, dtype=np.float32),
                document_count=0,
            ),
        )

    monkeypatch.setattr("minimap_tile_indexer.build_area_orb_index", stub_build)

    # Segment 1: an existing product lets the incremental build reuse its vocabulary.
    _write_orb_product(path, existing_vocabulary)
    queue._process_area_orb_build(work)
    assert received["vocabulary"] is not None
    assert np.array_equal(received["vocabulary"], existing_vocabulary)

    # Segment 2: an existing product that cannot be read trains from scratch.
    _write_orb_product(path, existing_vocabulary)
    received.clear()

    def unreadable(_path):
        raise RuntimeError("damaged")

    monkeypatch.setattr("minimap_tile_indexer.load_orb_area_index", unreadable)
    queue._process_area_orb_build(work)

    assert received["vocabulary"] is None
    assert path.exists()
    assert store.is_area_orb_ready(AREA) is True


def test_startup_reconcile_rebuilds_every_legacy_area_in_the_background(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    other_area = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=2, y=3)
    _write_tile(tmp_path, other_area)
    _no_features(monkeypatch)
    errors: list[str] = []
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True, on_error=errors.append)

    assert queue.wait_until_idle(timeout=10.0)
    queue.shutdown()

    assert errors == []
    assert MinimapIndexStore(tmp_path, AREA).get_area_index_version(AREA) == CURRENT_TILE_INDEX_VERSION
    assert MinimapIndexStore(tmp_path, "906").get_area_index_version("906") == CURRENT_TILE_INDEX_VERSION
    assert _rough_records(tmp_path)
    assert len(_sift_files(tmp_path)) == 1


def test_auto_started_work_is_removed_from_pending_and_can_be_requeued(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    _no_features(monkeypatch)
    expected_works = 1 + len(_own_window_rects(key))
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True)

    first = queue.enqueue_changed_tile(key)
    assert first.queued_count == expected_works
    assert queue.wait_until_idle(timeout=5.0)
    assert queue.pending_count == 0

    second = queue.enqueue_changed_tile(key)
    assert second.queued_count == expected_works
    assert queue.wait_until_idle(timeout=5.0)
    assert queue.pending_count == 0
    queue.shutdown()


def test_failed_work_is_removed_from_pending_and_can_be_requeued(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)

    def failing_extract(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", failing_extract)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True)
    expected_works = 1 + len(_own_window_rects(key))

    first = queue.enqueue_changed_tile(key)
    assert first.queued_count == expected_works
    assert queue.wait_until_idle(timeout=5.0)
    assert queue.pending_count == 0

    second = queue.enqueue_changed_tile(key)
    assert second.queued_count == expected_works
    queue.shutdown()


def test_rebuild_replays_a_tile_enqueued_while_it_was_running(tmp_path):
    first = _tile(10, 20)
    second = _tile(11, 20)
    _write_tile(tmp_path, first)
    _write_tile(tmp_path, second)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    queue.enqueue_changed_tile(first)
    deferred = queue.enqueue_changed_tile(second)
    assert deferred.queued == ()

    rebuild_work = queue._pending[0]
    assert rebuild_work.kind == "area_rebuild"
    queue._run_work(rebuild_work)

    assert queue.pending_count > 0
    assert MinimapIndexStore(tmp_path, AREA).get_tile_status(second).tile_present is True
    assert MinimapIndexStore(tmp_path, AREA).get_area_index_version(AREA) == CURRENT_TILE_INDEX_VERSION
    queue.shutdown()


def test_failed_background_work_reports_error_callback(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    _mark_area_current(tmp_path)
    errors = []

    def failing_extract(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", failing_extract)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True, on_error=errors.append)

    queue.enqueue_changed_tile(key)
    assert queue.wait_until_idle(timeout=5.0)

    assert any("sift_tile" in message and "boom" in message for message in errors)
    queue.shutdown()
