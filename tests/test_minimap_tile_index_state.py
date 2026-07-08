from pathlib import Path

from core.map_context import TileKey
from minimap_tile_index_state import (
    TileIndexStateStore,
    TileIndexStatus,
    canonical_tile_key,
    canonical_window_key,
)


def _tile(x: int, y: int, *, kind: str = "standard", layer_id: str = "default", z_level=None) -> TileKey:
    return TileKey(area_id="8", layer_id=layer_id, z_level=z_level, kind=kind, x=x, y=y)


def test_canonical_horizontal_window_key_deduplicates_tile_order():
    a = _tile(10, 20)
    b = _tile(11, 20)

    assert canonical_window_key("edge_h", [a, b]) == canonical_window_key("edge_h", [b, a])


def test_canonical_window_key_keeps_layer_and_kind_separate():
    base = canonical_window_key("tile", [_tile(10, 20)])
    layered = canonical_window_key("tile", [_tile(10, 20, kind="layered", layer_id="2", z_level=-1)])

    assert base != layered
    assert "standard" in base
    assert "layered" in layered


def test_tile_index_state_persists_status_under_area_indexes(tmp_path):
    store = TileIndexStateStore(tmp_path, area_id="8")
    key = _tile(10, 20)
    status = TileIndexStatus(
        tile_present=True,
        rough_indexed=True,
        sift_indexed=False,
        sift_stale_reason="neighbor_added",
        file_mtime_ns=123,
        file_size=456,
    )

    store.set_tile_status(key, status)
    store.save()

    expected_path = tmp_path / "8" / "indexes" / "tile_index_state.json"
    assert expected_path.exists()

    reloaded = TileIndexStateStore(tmp_path, area_id="8")
    assert reloaded.get_tile_status(key) == status


def test_tile_index_state_save_retries_transient_replace_failure(monkeypatch, tmp_path):
    original_replace = Path.replace
    calls = {"count": 0}

    def flaky_replace(self, target):
        if str(self).endswith("tile_index_state.json.tmp") and calls["count"] == 0:
            calls["count"] += 1
            raise PermissionError("temporary lock")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    store = TileIndexStateStore(tmp_path, area_id="8")
    key = _tile(10, 20)
    status = TileIndexStatus(tile_present=True, rough_indexed=True, sift_indexed=True, file_mtime_ns=1, file_size=2)

    store.set_tile_status(key, status)
    store.save()

    assert calls["count"] == 1
    assert TileIndexStateStore(tmp_path, area_id="8").get_tile_status(key) == status


def test_tile_index_state_marks_adjacent_existing_tiles_stale(tmp_path):
    store = TileIndexStateStore(tmp_path, area_id="8")
    center = _tile(10, 20)
    right = _tile(11, 20)
    far = _tile(12, 20)
    present = TileIndexStatus(tile_present=True, rough_indexed=True, sift_indexed=True, file_mtime_ns=1, file_size=2)
    for key in (center, right, far):
        store.set_tile_status(key, present)

    stale = store.mark_adjacent_sift_stale(center, reason="neighbor_added")

    assert canonical_tile_key(right) in stale
    assert canonical_tile_key(far) not in stale
    assert store.get_tile_status(right).sift_indexed is False
    assert store.get_tile_status(right).sift_stale_reason == "neighbor_added"
