from core.map_context import MapContext, TileKey
from minimap_tile_cache import MinimapTileCache


def test_tile_cache_path_is_area_kind_layer_z_scoped(tmp_path):
    cache = MinimapTileCache(tmp_path)
    path = cache.tile_path(
        TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=10, y=20)
    )
    assert path == tmp_path / "906" / "standard" / "default" / "base" / "10_20.png"


def test_tile_cache_writes_metadata(tmp_path):
    cache = MinimapTileCache(tmp_path)
    ctx = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1, "scaleY": 1, "offsetX": 0, "offsetY": 0},
    )
    cache.write_context(ctx)
    assert (tmp_path / "906" / "context.json").exists()


def test_tile_cache_checks_recorded_file_size(tmp_path):
    cache = MinimapTileCache(tmp_path)
    path = tmp_path / "tile.png"
    path.write_bytes(b"1234")

    assert cache.is_same_cached_file(path, 4) is True
    assert cache.is_same_cached_file(path, 5) is False
    assert cache.is_same_cached_file(path, None) is True


def test_tile_cache_records_downloaded_tile_size_by_key(tmp_path):
    cache = MinimapTileCache(tmp_path)
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    path = cache.tile_path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"abcd")

    assert cache.is_same_cached_tile(key, None) is False

    cache.record_tile_size(key, 4)

    assert cache.get_recorded_tile_size(key) == 4
    assert cache.is_same_cached_tile(key, None) is True
    assert cache.is_same_cached_tile(key, 4) is True
    path.write_bytes(b"abcde")
    assert cache.is_same_cached_tile(key, None) is False


def test_tile_cache_reads_size_records_once_per_instance(monkeypatch, tmp_path):
    cache = MinimapTileCache(tmp_path)
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    path = cache.tile_path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"abcd")
    cache.size_record_path().write_text(
        '{"906/standard/default/base/1_2.png": 4}',
        encoding="utf-8",
    )
    original = cache._read_size_records
    calls = 0

    def counted_read():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(cache, "_read_size_records", counted_read)

    assert cache.is_same_cached_tile(key, None) is True
    assert cache.is_same_cached_tile(key, None) is True
    assert calls == 1
