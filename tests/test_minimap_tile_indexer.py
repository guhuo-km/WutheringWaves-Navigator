import cv2
import numpy as np

from core.map_context import TileKey
from minimap_index_store import MinimapIndexStore, MinimapIndexTileStatus
from minimap_tile_cache import MinimapTileCache
from minimap_tile_index_state import TileIndexStateStore, TileIndexStatus, canonical_tile_key
from minimap_tile_indexer import TileIndexQueue


def _tile(x: int, y: int, *, kind: str = "standard", layer_id: str = "default", z_level=None) -> TileKey:
    return TileKey(area_id="8", layer_id=layer_id, z_level=z_level, kind=kind, x=x, y=y)


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


def test_enqueue_changed_tile_adds_own_rough_and_sift_work(tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_changed_tile(key)

    assert result.queued_count == 2
    assert any(work.kind == "rough_window" and work.window_type == "tile" for work in result.queued)
    assert any(work.kind == "sift_tile" and work.tile_keys == (key,) for work in result.queued)
    status = TileIndexStateStore(tmp_path, "8").get_tile_status(key)
    assert status.tile_present is True
    assert status.file_size > 0


def test_enqueue_changed_tile_records_tile_in_sqlite(tmp_path):
    key = _tile(16, -13)
    _write_tile(tmp_path, key)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    queue.enqueue_changed_tile(key)

    status = MinimapIndexStore(tmp_path, "8").get_tile_status(key)
    assert status.tile_present is True
    assert status.png_size > 0


def test_process_work_marks_rough_and_sift_ready_in_sqlite(monkeypatch, tmp_path):
    key = _tile(16, -13)
    _write_tile(tmp_path, key)
    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", lambda **kwargs: [])
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(key)

    for work in result.queued:
        queue.process_work(work)

    status = MinimapIndexStore(tmp_path, "8").get_tile_status(key)
    assert status.rough_ready is True
    assert status.sift_ready is True


def test_enqueue_changed_tile_dedupes_canonical_cross_tile_work(tmp_path):
    a = _tile(10, 20)
    b = _tile(11, 20)
    _write_tile(tmp_path, a)
    _write_tile(tmp_path, b)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    first = queue.enqueue_changed_tile(a)
    second = queue.enqueue_changed_tile(b)

    first_keys = {work.work_key for work in first.queued}
    second_keys = {work.work_key for work in second.queued}
    cross = [key for key in first_keys | second_keys if "edge_h" in key]
    assert len(cross) == 1


def test_enqueue_changed_tile_marks_existing_adjacent_sift_stale(tmp_path):
    center = _tile(10, 20)
    right = _tile(11, 20)
    _write_tile(tmp_path, center)
    _write_tile(tmp_path, right)
    store = TileIndexStateStore(tmp_path, "8")
    store.set_tile_status(
        right,
        TileIndexStatus(tile_present=True, rough_indexed=True, sift_indexed=True, file_mtime_ns=1, file_size=2),
    )
    store.save()
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_changed_tile(center)

    assert canonical_tile_key(right) in result.stale_tile_keys
    reloaded = TileIndexStateStore(tmp_path, "8")
    assert reloaded.get_tile_status(right).sift_indexed is False
    assert reloaded.get_tile_status(right).sift_stale_reason == "neighbor_added"


def test_enqueue_changed_tile_requeues_stale_adjacent_sift(tmp_path):
    center = _tile(10, 20)
    right = _tile(11, 20)
    _write_tile(tmp_path, center)
    _write_tile(tmp_path, right)
    store = TileIndexStateStore(tmp_path, "8")
    store.set_tile_status(
        right,
        TileIndexStatus(tile_present=True, rough_indexed=True, sift_indexed=True, file_mtime_ns=1, file_size=2),
    )
    store.save()
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_changed_tile(center)

    stale_sift = [
        work for work in result.queued
        if work.kind == "sift_tile" and work.tile_keys == (right,)
    ]
    assert stale_sift


def test_enqueue_stale_sift_tiles_requeues_existing_stale_entries(tmp_path):
    key = _tile(8, -6)
    _write_tile(tmp_path, key)
    store = TileIndexStateStore(tmp_path, "8")
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

    result = queue.enqueue_stale_sift_tiles("8")

    assert result.queued_count == 1
    assert result.queued[0].kind == "sift_tile"
    assert result.queued[0].tile_keys == (key,)


def test_enqueue_missing_indexes_from_existing_pngs(tmp_path):
    key = _tile(16, -13)
    _write_tile(tmp_path, key)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_missing_indexes_for_area("8")

    assert result.queued_count >= 2
    assert any(work.kind == "rough_window" for work in result.queued)
    assert any(work.kind == "sift_tile" for work in result.queued)
    assert MinimapIndexStore(tmp_path, "8").get_tile_status(key).tile_present is True


def test_enqueue_missing_indexes_for_tiles_only_checks_given_keys(tmp_path):
    current = _tile(16, -13)
    historical = _tile(99, 99)
    _write_tile(tmp_path, current)
    _write_tile(tmp_path, historical)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)

    result = queue.enqueue_missing_indexes_for_tiles([current])

    assert result.queued_count >= 2
    assert result.incomplete_tiles == (current,)
    queued_tile_keys = {work.tile_keys[0] for work in result.queued if work.tile_keys}
    assert current in queued_tile_keys
    assert historical not in queued_tile_keys
    assert MinimapIndexStore(tmp_path, "8").get_tile_status(current).tile_present is True
    assert MinimapIndexStore(tmp_path, "8").get_tile_status(historical).exists is False


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
    assert created == ["8", "906"]
    assert len(queried) == 2


def test_process_one_work_passes_color_image_to_sift(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
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
    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", lambda **kwargs: [])
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(key)
    sift_work = next(work for work in result.queued if work.kind == "sift_tile")
    store = TileIndexStateStore(tmp_path, "8")
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

    status = TileIndexStateStore(tmp_path, "8").get_tile_status(key)
    assert status.sift_indexed is True
    assert status.file_mtime_ns > 0
    assert status.file_size > 0


def test_layered_rough_index_uses_matching_base_tile_under_alpha(monkeypatch, tmp_path):
    base = _tile(10, 20)
    layer = _tile(10, 20, kind="layered", layer_id="2", z_level=-1)
    _write_tile(tmp_path, base, color=(10, 20, 30))
    _write_layer_tile(tmp_path, layer, bgr=(110, 120, 130), alpha=128)
    seen = {}

    def fake_descriptor(image):
        seen["pixel"] = tuple(int(value) for value in image[0, 0])
        return np.ones(4, dtype=np.float32)

    monkeypatch.setattr("minimap_tile_indexer.compute_hsv_texture_descriptor", fake_descriptor)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=False)
    result = queue.enqueue_changed_tile(layer)
    rough_work = next(work for work in result.queued if work.kind == "rough_window" and work.window_type == "tile")

    queue.process_work(rough_work)

    assert seen["pixel"] == (60, 70, 80)


def test_auto_started_work_is_removed_from_pending_and_can_be_requeued(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", lambda **kwargs: [])
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True)

    first = queue.enqueue_changed_tile(key)
    assert first.queued_count == 2
    assert queue.wait_until_idle(timeout=2.0)
    assert queue.pending_count == 0

    second = queue.enqueue_changed_tile(key)
    assert second.queued_count == 2
    assert queue.wait_until_idle(timeout=2.0)
    assert queue.pending_count == 0
    queue.shutdown()


def test_failed_work_is_removed_from_pending_and_can_be_requeued(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)

    def failing_extract(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", failing_extract)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True)

    first = queue.enqueue_changed_tile(key)
    assert first.queued_count == 2
    assert queue.wait_until_idle(timeout=2.0)
    assert queue.pending_count == 0

    second = queue.enqueue_changed_tile(key)
    assert second.queued_count == 2
    queue.shutdown()


def test_failed_background_work_reports_error_callback(monkeypatch, tmp_path):
    key = _tile(10, 20)
    _write_tile(tmp_path, key)
    errors = []

    def failing_extract(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("minimap_tile_indexer.extract_owned_sift_features_from_expanded_tile", failing_extract)
    queue = TileIndexQueue(tmp_path, tile_size=32, max_workers=1, auto_start=True, on_error=errors.append)

    queue.enqueue_changed_tile(key)
    assert queue.wait_until_idle(timeout=2.0)

    assert any("sift_tile" in message and "boom" in message for message in errors)
    queue.shutdown()
