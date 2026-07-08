from core.map_context import TileKey
from minimap_tile_downloader import (
    convert_tile_snapshot_to_download_inputs,
    download_missing_tiles,
    generate_standard_tile_inputs_for_game_xy,
    plan_missing_tiles,
    plan_missing_tiles_with_sizes,
    TileDownloadInput,
)
from minimap_tile_cache import MinimapTileCache


def test_plan_missing_tiles_skips_existing_files(tmp_path):
    existing = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    missing = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=3, y=4)
    existing_path = tmp_path / "906" / "standard" / "default" / "base" / "1_2.png"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(b"png")

    planned = plan_missing_tiles([existing, missing], tmp_path)
    assert planned == [missing]


def test_plan_missing_tiles_with_sizes_requires_recorded_size_match(tmp_path):
    same = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    changed = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=3, y=4)
    unknown_size = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=5, y=6)

    same_path = tmp_path / "906" / "standard" / "default" / "base" / "1_2.png"
    same_path.parent.mkdir(parents=True)
    same_path.write_bytes(b"png")
    changed_path = tmp_path / "906" / "standard" / "default" / "base" / "3_4.png"
    changed_path.write_bytes(b"png")
    unknown_path = tmp_path / "906" / "standard" / "default" / "base" / "5_6.png"
    unknown_path.write_bytes(b"png")

    planned = plan_missing_tiles_with_sizes(
        {
            same: 3,
            changed: 4,
            unknown_size: None,
        },
        tmp_path,
    )
    assert planned == [changed, unknown_size]


def test_plan_missing_tiles_with_sizes_uses_recorded_size_when_snapshot_size_is_unknown(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    cache = MinimapTileCache(tmp_path)
    path = cache.tile_path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    cache.record_tile_size(key, 3)

    assert plan_missing_tiles_with_sizes({key: None}, tmp_path) == []


def test_convert_tile_snapshot_to_download_inputs_handles_all_tile_kinds():
    snapshot = {
        "standardTiles": [
            {
                "regionId": "8",
                "x": -1,
                "y": 1,
                "leafletTileX": -2,
                "leafletTileY": -1,
                "leafletTileZ": 0,
                "url": "https://example.test/8/8_-1_1.png",
                "size": 123,
            }
        ],
        "layeredTiles": [
            {
                "regionId": "903",
                "layerId": "2",
                "zLevel": -1,
                "x": 0,
                "y": 1,
                "url": "https://example.test/903/2/-1_0_1.png",
            }
        ],
        "gravityTiles": [
            {
                "regionId": "903",
                "layerId": "2",
                "x": 0,
                "y": -1,
                "url": "https://example.test/903/2/0_-1.png",
            }
        ],
    }

    inputs = convert_tile_snapshot_to_download_inputs(snapshot)

    assert [item.key for item in inputs] == [
        TileKey(
            area_id="8",
            layer_id="default",
            z_level=None,
            kind="standard",
            x=-1,
            y=1,
            leaflet_x=-2,
            leaflet_y=-1,
            leaflet_z=0,
        ),
        TileKey(area_id="903", layer_id="2", z_level=-1, kind="layered", x=0, y=1),
        TileKey(area_id="903", layer_id="2", z_level=0, kind="gravity", x=0, y=-1),
    ]
    assert inputs[0].url == "https://example.test/8/8_-1_1.png"
    assert inputs[0].expected_size == 123


def test_generate_standard_tile_inputs_for_game_xy_uses_current_tile_url_pattern():
    inputs = generate_standard_tile_inputs_for_game_xy(
        area_id="8",
        game_xy=(-1318, 433),
        coord_transform={
            "scaleX": 0.01204705882352941,
            "scaleY": 0.01204705882352941,
            "offsetX": 1024,
            "offsetY": 0,
        },
        tile_size=1024,
        tile_base_url="https://web-static.kurobbs.com/mcmap/tiles/current",
        oss_params="x-oss-process=image/format,webp/resize,w_1024,h_1024",
        radius=1,
    )

    assert inputs[4].key == TileKey(area_id="8", layer_id="default", z_level=None, kind="standard", x=-1, y=0)
    assert inputs[4].url == (
        "https://web-static.kurobbs.com/mcmap/tiles/current/"
        "8/8_-1_0.png?x-oss-process=image/format,webp/resize,w_1024,h_1024"
    )
    assert len(inputs) == 9


def test_download_missing_tiles_writes_temp_then_records_size(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"tile-bytes"

    result = download_missing_tiles(
        [TileDownloadInput(key=key, url="https://example.test/906/906_1_2.png")],
        tmp_path,
        fetch_bytes=fake_fetch,
    )

    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "1_2.png"
    assert tile_path.read_bytes() == b"tile-bytes"
    assert calls == ["https://example.test/906/906_1_2.png"]
    assert result.changed_area_ids == {"906"}
    assert result.downloaded_sizes == {key: len(b"tile-bytes")}
    assert MinimapTileCache(tmp_path).get_recorded_tile_size(key) == len(b"tile-bytes")
    assert list(tile_path.parent.glob("*.tmp")) == []


def test_download_missing_tiles_skips_matching_recorded_size(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    tile_path = tmp_path / "906" / "standard" / "default" / "base" / "1_2.png"
    tile_path.parent.mkdir(parents=True)
    tile_path.write_bytes(b"abc")

    result = download_missing_tiles(
        [TileDownloadInput(key=key, url="https://example.test/906/906_1_2.png", expected_size=3)],
        tmp_path,
        fetch_bytes=lambda url: b"should-not-fetch",
    )

    assert tile_path.read_bytes() == b"abc"
    assert result.changed_area_ids == set()
    assert result.downloaded_sizes == {}
    assert result.input_count == 1
    assert result.skipped_count == 1


def test_download_missing_tiles_reports_input_download_skip_and_failure_counts(tmp_path):
    downloaded = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    skipped = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=3, y=4)
    failed = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=5, y=6)
    skipped_path = tmp_path / "906" / "standard" / "default" / "base" / "3_4.png"
    skipped_path.parent.mkdir(parents=True)
    skipped_path.write_bytes(b"old")

    def fake_fetch(url):
        if "fail" in url:
            raise RuntimeError("network failed")
        return b"new"

    result = download_missing_tiles(
        [
            TileDownloadInput(key=downloaded, url="https://example.test/906/906_1_2.png"),
            TileDownloadInput(key=skipped, url="https://example.test/906/906_3_4.png", expected_size=3),
            TileDownloadInput(key=failed, url="https://example.test/fail/906_5_6.png"),
        ],
        tmp_path,
        fetch_bytes=fake_fetch,
    )

    assert result.input_count == 3
    assert result.skipped_count == 1
    assert result.downloaded_sizes == {downloaded: 3}
    assert set(result.failures) == {failed}


def test_download_missing_tiles_skips_unknown_snapshot_size_when_recorded_size_matches(tmp_path):
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    cache = MinimapTileCache(tmp_path)
    tile_path = cache.tile_path(key)
    tile_path.parent.mkdir(parents=True)
    tile_path.write_bytes(b"abc")
    cache.record_tile_size(key, 3)

    result = download_missing_tiles(
        [TileDownloadInput(key=key, url="https://example.test/906/906_1_2.png", expected_size=None)],
        tmp_path,
        fetch_bytes=lambda url: b"should-not-fetch",
    )

    assert tile_path.read_bytes() == b"abc"
    assert result.changed_area_ids == set()
    assert result.downloaded_sizes == {}


def test_download_missing_tiles_triggers_refresh_only_for_changed_areas(tmp_path):
    changed = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=1, y=2)
    skipped = TileKey(area_id="903", layer_id="default", z_level=None, kind="standard", x=3, y=4)
    skipped_path = tmp_path / "903" / "standard" / "default" / "base" / "3_4.png"
    skipped_path.parent.mkdir(parents=True)
    skipped_path.write_bytes(b"old")
    refreshed = []

    download_missing_tiles(
        [
            TileDownloadInput(key=changed, url="https://example.test/906/906_1_2.png"),
            TileDownloadInput(key=skipped, url="https://example.test/903/903_3_4.png", expected_size=3),
        ],
        tmp_path,
        fetch_bytes=lambda url: b"new",
        refresh_changed_regions=lambda area_ids: refreshed.extend(sorted(area_ids)),
    )

    assert refreshed == ["906"]
