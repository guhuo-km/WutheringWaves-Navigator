from core.map_context import CoordinateCandidate, MapContext, TileKey


def test_map_context_accepts_area_and_transform():
    ctx = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1, "scaleY": 1, "offsetX": 0, "offsetY": 0},
    )
    assert ctx.area_id == "906"
    assert ctx.tile_size == 1024


def test_ocr_coordinate_candidate_keeps_z():
    candidate = CoordinateCandidate(x=2784, y=3490, z=124, source="ocr", confidence=None)
    assert candidate.source == "ocr"
    assert candidate.as_tuple() == (2784, 3490, 124)


def test_visual_coordinate_candidate_can_be_xy_only():
    candidate = CoordinateCandidate(x=2784, y=3490, z=None, source="visual")
    assert candidate.as_xy_tuple() == (2784, 3490)
    assert candidate.z is None
    assert candidate.reason == ""


def test_tile_key_path_parts_are_stable():
    key = TileKey(area_id="906", layer_id="default", z_level=None, kind="standard", x=10, y=20)
    assert key.parts() == ("906", "standard", "default", "base", "10_20.png")
