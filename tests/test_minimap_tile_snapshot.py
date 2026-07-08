import json

from core.map_context import TileKey
from minimap_tile_snapshot import download_tile_snapshot_result, parse_tile_metadata_snapshot_result


def test_parse_tile_metadata_snapshot_result_accepts_userscript_envelope():
    raw = json.dumps(
        {
            "ok": True,
            "data": {
                "standardTiles": [
                    {
                        "regionId": "906",
                        "x": 1,
                        "y": 2,
                        "url": "https://example.test/906/906_1_2.png",
                    }
                ],
                "layeredTiles": [],
                "gravityTiles": [],
            },
        }
    )

    snapshot = parse_tile_metadata_snapshot_result(raw)

    assert snapshot is not None
    assert snapshot["standardTiles"][0]["regionId"] == "906"


def test_parse_tile_metadata_snapshot_result_rejects_error_or_invalid_payload():
    assert parse_tile_metadata_snapshot_result(json.dumps({"ok": False})) is None
    assert parse_tile_metadata_snapshot_result("not-json") is None
    assert parse_tile_metadata_snapshot_result(None) is None


def test_download_tile_snapshot_result_converts_and_downloads_changed_tiles(tmp_path):
    raw = json.dumps(
        {
            "ok": True,
            "data": {
                "standardTiles": [
                    {
                        "regionId": "906",
                        "x": 1,
                        "y": 2,
                        "url": "https://example.test/906/906_1_2.png",
                    }
                ],
                "layeredTiles": [],
                "gravityTiles": [],
            },
        }
    )
    refreshed = []

    result = download_tile_snapshot_result(
        raw,
        tmp_path,
        fetch_bytes=lambda url: b"tile",
        refresh_changed_regions=lambda area_ids: refreshed.extend(sorted(area_ids)),
    )

    key = TileKey("906", "default", None, "standard", 1, 2)
    assert result is not None
    assert result.downloaded_sizes == {key: 4}
    assert refreshed == ["906"]
