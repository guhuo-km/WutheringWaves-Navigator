from core.map_context import TileKey
from minimap_index_store import (
    CURRENT_TILE_INDEX_VERSION,
    UNAVAILABLE_TILE_INDEX_VERSION,
    MinimapIndexStore,
)
from minimap_tile_index_state import canonical_tile_key


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


def test_index_store_reads_multiple_tile_statuses_in_one_batch(tmp_path):
    ready = _tile(1, 1)
    missing = _tile(2, 1)
    store = MinimapIndexStore(tmp_path, "8")
    store.record_tile_available(ready, png_path="ready.png", mtime_ns=1, size=2)

    statuses = store.get_tile_statuses([ready, missing])

    assert set(statuses) == {canonical_tile_key(ready), canonical_tile_key(missing)}
    assert statuses[canonical_tile_key(ready)].tile_present is True
    assert statuses[canonical_tile_key(missing)].tile_present is False


def test_current_tile_index_version_contract_matches_the_query_side_agreement():
    assert CURRENT_TILE_INDEX_VERSION == 3
    assert UNAVAILABLE_TILE_INDEX_VERSION == 0


def test_area_index_version_is_unavailable_before_any_rebuild(tmp_path):
    assert MinimapIndexStore(tmp_path, "8").get_area_index_version("8") == UNAVAILABLE_TILE_INDEX_VERSION


def test_area_index_version_roundtrips_and_is_overwritten(tmp_path):
    store = MinimapIndexStore(tmp_path, "8")

    store.set_area_index_version("8", CURRENT_TILE_INDEX_VERSION)
    assert MinimapIndexStore(tmp_path, "8").get_area_index_version("8") == CURRENT_TILE_INDEX_VERSION

    store.set_area_index_version("8", UNAVAILABLE_TILE_INDEX_VERSION)
    assert MinimapIndexStore(tmp_path, "8").get_area_index_version("8") == UNAVAILABLE_TILE_INDEX_VERSION


def test_area_index_version_is_stored_per_area(tmp_path):
    MinimapIndexStore(tmp_path, "8").set_area_index_version("8", CURRENT_TILE_INDEX_VERSION)

    assert MinimapIndexStore(tmp_path, "8").get_area_index_version("8") == CURRENT_TILE_INDEX_VERSION
    assert MinimapIndexStore(tmp_path, "906").get_area_index_version("906") == UNAVAILABLE_TILE_INDEX_VERSION


def test_area_orb_ready_is_false_without_a_row_and_roundtrips(tmp_path):
    store = MinimapIndexStore(tmp_path, "8")
    assert store.is_area_orb_ready("8") is False

    store.set_area_orb_ready("8", True)
    assert MinimapIndexStore(tmp_path, "8").is_area_orb_ready("8") is True

    store.set_area_orb_ready("8", False)
    assert MinimapIndexStore(tmp_path, "8").is_area_orb_ready("8") is False


def test_clear_tile_index_status_drops_tile_rows_but_keeps_area_version(tmp_path):
    key = _tile(16, -13)
    store = MinimapIndexStore(tmp_path, "8")
    store.record_tile_available(key, png_path="tile.png", mtime_ns=11, size=22)
    store.mark_rough_ready(key, rough_count=1)
    store.set_area_index_version("8", CURRENT_TILE_INDEX_VERSION)

    removed = store.clear_tile_index_status()

    assert removed == 1
    assert store.tile_status_items() == []
    assert store.get_tile_status(key).tile_present is False
    assert store.health_summary() == {
        "tiles": 0,
        "rough_ready": 0,
        "sift_ready": 0,
        "rough_missing": 0,
        "sift_missing": 0,
        "failed": 0,
    }
    assert store.get_area_index_version("8") == CURRENT_TILE_INDEX_VERSION
