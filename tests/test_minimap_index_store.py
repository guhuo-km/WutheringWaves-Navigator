from core.map_context import TileKey
from minimap_index_store import MinimapIndexStore


def _tile(x: int, y: int, *, area_id: str = "8", kind: str = "standard", layer_id: str = "default", z_level=None) -> TileKey:
    return TileKey(area_id=area_id, kind=kind, layer_id=layer_id, z_level=z_level, x=x, y=y)


def test_index_store_records_tile_and_index_readiness(tmp_path):
    key = _tile(16, -13)
    store = MinimapIndexStore(tmp_path, "8")

    store.record_tile_available(key, png_path="8/standard/default/base/16_-13.png", mtime_ns=11, size=22)
    store.mark_rough_ready(key, rough_count=3)
    store.mark_sift_ready(key, sift_path="8/indexes/sift_tiles/sift__8__standard__default__base__16__-13.npz", feature_count=1775)

    status = store.get_tile_status(key)
    assert status.tile_present is True
    assert status.rough_ready is True
    assert status.sift_ready is True
    assert status.png_size == 22
    assert status.feature_count == 1775


def test_index_store_health_summary_counts_missing_work(tmp_path):
    ready = _tile(1, 1)
    missing = _tile(2, 1)
    store = MinimapIndexStore(tmp_path, "8")
    store.record_tile_available(ready, png_path="ready.png", mtime_ns=1, size=2)
    store.mark_rough_ready(ready, rough_count=1)
    store.mark_sift_ready(ready, sift_path="ready.npz", feature_count=3)
    store.record_tile_available(missing, png_path="missing.png", mtime_ns=1, size=2)

    assert store.health_summary() == {
        "tiles": 2,
        "rough_ready": 1,
        "sift_ready": 1,
        "rough_missing": 1,
        "sift_missing": 1,
        "failed": 0,
    }


def test_index_store_marks_sift_stale_without_losing_tile_stamp(tmp_path):
    key = _tile(16, -13)
    store = MinimapIndexStore(tmp_path, "8")
    store.record_tile_available(key, png_path="tile.png", mtime_ns=11, size=22)
    store.mark_sift_ready(key, sift_path="tile.npz", feature_count=4)

    store.mark_sift_stale(key, reason="neighbor_added")

    status = store.get_tile_status(key)
    assert status.tile_present is True
    assert status.png_size == 22
    assert status.sift_ready is False
    assert status.stale_reason == "neighbor_added"


def test_index_store_missing_status_is_empty(tmp_path):
    key = _tile(99, -99)
    status = MinimapIndexStore(tmp_path, "8").get_tile_status(key)

    assert status.tile_present is False
    assert status.rough_ready is False
    assert status.sift_ready is False
