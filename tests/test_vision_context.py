import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.vision_context import (
    build_vision_snapshot,
    map_context_from_js,
    parse_get_map_context_result,
)


def test_map_context_from_js_valid():
    data = {
        "areaId": "906",
        "tileSize": 1024,
        "tileProjection": {
            "mapUnitsPerTileX": 849.92,
            "mapUnitsPerTileY": 849.92,
        },
        "coordTransform": {
            "scaleX": 0.01204705882352941,
            "scaleY": 0.01204705882352941,
            "offsetX": 1024,
            "offsetY": 0,
        },
    }
    mc = map_context_from_js(data)
    assert mc is not None
    assert mc.area_id == "906"
    assert mc.layer_id == "default"
    assert mc.tile_size == 1024
    assert mc.coord_transform["offsetX"] == 1024
    assert mc.map_units_per_tile_x == 849.92
    assert mc.map_units_per_tile_y == 849.92


def test_map_context_from_js_rejects_empty_area():
    assert map_context_from_js({"areaId": "", "coordTransform": {}}) is None


def test_parse_get_map_context_result_ok():
    raw = json.dumps({
        "ok": True,
        "data": {
            "areaId": "8",
            "tileSize": 1024,
            "coordTransform": {
                "scaleX": 1.0,
                "scaleY": 1.0,
                "offsetX": 0,
                "offsetY": 0,
            },
        },
    })
    mc = parse_get_map_context_result(raw)
    assert mc is not None
    assert mc.area_id == "8"


def test_parse_get_map_context_result_error():
    assert parse_get_map_context_result(json.dumps({"ok": False})) is None
    assert parse_get_map_context_result("not-json") is None


def test_build_vision_snapshot_shape(tmp_path):
    from core.map_context import MapContext

    mc = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0, "offsetY": 0})
    snap = build_vision_snapshot(mc, tmp_path)
    assert snap["tile_root"] == str(tmp_path)
    assert snap["map_context"] is mc
