import numpy as np

from core.map_context import TileKey
from minimap_candidate_regions import (
    CandidateRegionGroup,
    build_candidate_regions,
    build_radius_regions,
    select_radius_feature_indices,
    select_region_feature_indices,
)


# Rectangles: A=(0,0,10,10) and B=(5,5,10,10) overlap, C=(100,100,10,10) is
# separated from them by a gap.
_RECTANGLES = [
    (0, 0, 10, 10),
    (5, 5, 10, 10),
    (100, 100, 10, 10),
]

_POINTS = np.array(
    [
        (0.0, 0.0),      # 0: A left/top edges are inclusive
        (9.9, 9.9),      # 1: covered by both A and B
        (10.0, 10.0),    # 2: outside A on both axes, inside B
        (10.0, 0.0),     # 3: A right edge is exclusive, outside B
        (0.0, 10.0),     # 4: A bottom edge is exclusive, outside B
        (14.0, 14.0),    # 5: inside B
        (15.0, 14.0),    # 6: B right edge is exclusive
        (14.0, 15.0),    # 7: B bottom edge is exclusive
        (50.0, 50.0),    # 8: gap between the two regions
        (100.0, 100.0),  # 9: C left/top edges are inclusive
        (109.0, 109.0),  # 10: inside C
        (110.0, 110.0),  # 11: C right and bottom edges are exclusive
        (-1.0, 5.0),     # 12: left of every region
    ],
    dtype=np.float64,
)


def test_union_selects_each_row_once_in_ascending_order() -> None:
    indices = select_region_feature_indices(_POINTS, _RECTANGLES)

    assert indices.tolist() == [0, 1, 2, 5, 9, 10]
    assert indices.dtype == np.int64
    assert len(set(indices.tolist())) == len(indices.tolist())


def test_integer_feature_coordinates_use_the_same_bounds() -> None:
    integer_points = np.array(
        [
            (9, 9),
            (10, 10),
            (15, 14),
        ],
        dtype=np.int32,
    )

    indices = select_region_feature_indices(integer_points, _RECTANGLES)

    assert indices.tolist() == [0, 1]


def test_empty_rectangles_return_empty_index_array() -> None:
    for rectangles in ([], ()):
        indices = select_region_feature_indices(_POINTS, rectangles)

        assert indices.size == 0
        assert indices.dtype == np.int64


def test_empty_points_return_empty_index_array() -> None:
    for points in (np.empty((0, 2)), np.empty((0, 2), dtype=np.int32)):
        indices = select_region_feature_indices(points, _RECTANGLES)

        assert indices.size == 0
        assert indices.dtype == np.int64


def test_build_candidate_regions_merges_planes_and_isolates_layers() -> None:
    ground_tile_left = TileKey(
        area_id="area1",
        layer_id="ground",
        z_level=None,
        kind="surface",
        x=10,
        y=-3,
    )
    ground_tile_right = TileKey(
        area_id="area1",
        layer_id="ground",
        z_level=None,
        kind="surface",
        x=11,
        y=-3,
    )
    cave_tile = TileKey(
        area_id="area1",
        layer_id="cave",
        z_level=1,
        kind="surface",
        x=10,
        y=-3,
    )
    hsv_entries = [
        {
            "version": 2,
            "kind": "hsv",
            "left": 9300,
            "top": 3150,
            "width": 400,
            "height": 400,
            "tile_keys": [
                "area1|surface|ground|base|10|-3",
                "area1|surface|ground|base|11|-3",
            ],
        },
        {
            "version": 2,
            "kind": "hsv",
            "left": 9400,
            "top": 3150,
            "width": 400,
            "height": 400,
            "tile_keys": ["area1|surface|ground|base|10|-3"],
        },
        {
            "version": 2,
            "kind": "hsv",
            "left": 9300,
            "top": 3150,
            "width": 400,
            "height": 400,
            "tile_keys": ["area1|surface|cave|1|10|-3"],
        },
    ]
    orb_entries = [
        {
            "version": 2,
            "kind": "orb",
            "left": 10100,
            "top": 3500,
            "width": 400,
            "height": 400,
            "tile_keys": [
                "area1|surface|ground|base|10|-3",
                "area1|surface|ground|base|11|-3",
            ],
        },
        {
            "version": 2,
            "kind": "orb",
            "left": 10100,
            "top": 3500,
            "width": 400,
            "height": 400,
            "tile_keys": ["area1|surface|ground|base|11|-3"],
        },
    ]

    groups = build_candidate_regions(hsv_entries, orb_entries, tile_size=1024)

    assert sorted(groups) == [
        ("area1", "surface", "cave", 1),
        ("area1", "surface", "ground", None),
    ]
    assert groups[("area1", "surface", "ground", None)] == CandidateRegionGroup(
        tile_keys=[ground_tile_left, ground_tile_right],
        rectangles=[
            (9216, 3072, 1024, 1024),
            (10240, 3072, 1024, 1024),
            (10100, 3500, 400, 400),
        ],
    )
    assert groups[("area1", "surface", "cave", 1)] == CandidateRegionGroup(
        tile_keys=[cave_tile],
        rectangles=[(9216, 3072, 1024, 1024)],
    )


def _window_entry(
    scheme: str,
    left: int,
    top: int,
    tile_key: str,
    size: int = 400,
) -> dict[str, object]:
    return {
        "version": 2,
        "work_key": f"{tile_key}|{left}_{top}",
        "kind": scheme,
        "left": left,
        "top": top,
        "width": size,
        "height": size,
        "tile_keys": [tile_key],
    }


_STANDARD_KEY = "8|standard|default|base|2|0"
_LAYERED_KEY = "8|layered|2|1|2|0"
_GRAVITY_KEY = "8|gravity|default|0|2|0"


def test_radius_regions_single_plane_returns_one_group() -> None:
    entries = [
        _window_entry("hsv", 900, 900, _STANDARD_KEY),
        _window_entry("orb", 3000, 3000, _STANDARD_KEY),
    ]

    groups = build_radius_regions(entries, center_px=(1000, 1000), radius_px=50)

    assert list(groups) == [("8", "standard", "default", None)]
    assert groups[("8", "standard", "default", None)] == CandidateRegionGroup(
        tile_keys=[
            TileKey(area_id="8", kind="standard", layer_id="default", z_level=None, x=2, y=0)
        ],
        rectangles=[(900, 900, 400, 400)],
    )


def test_radius_regions_group_count_matches_planes_inside_the_circle() -> None:
    # Three distinct planes overlap the circle and a fourth plane stays outside it.
    entries = [
        _window_entry("hsv", 450, 450, _STANDARD_KEY),
        _window_entry("hsv", 500, 490, _LAYERED_KEY),
        _window_entry("orb", 490, 500, _GRAVITY_KEY),
        _window_entry("orb", 5000, 5000, "8|layered|3|2|2|0", size=10),
    ]

    groups = build_radius_regions(entries, center_px=(500, 500), radius_px=100)

    assert sorted(groups) == [
        ("8", "gravity", "default", 0),
        ("8", "layered", "2", 1),
        ("8", "standard", "default", None),
    ]
    assert groups[("8", "layered", "2", 1)].rectangles == [(500, 490, 400, 400)]
    assert groups[("8", "gravity", "default", 0)].rectangles == [(490, 500, 400, 400)]


def test_radius_regions_without_any_overlapping_entry_is_empty() -> None:
    entries = [
        _window_entry("hsv", 3000, 3000, _STANDARD_KEY),
        _window_entry("orb", -3000, -3000, _LAYERED_KEY),
    ]

    assert build_radius_regions(entries, center_px=(0, 0), radius_px=100) == {}


def test_radius_regions_boundary_and_distance_rules() -> None:
    entries = [
        # Centred on the circle centre.
        _window_entry("hsv", -1, -1, _STANDARD_KEY, size=2),
        # Left edge sits exactly on the circle bounding box right edge.
        _window_entry("hsv", 10, -2, _STANDARD_KEY, size=4),
        # One pixel further right, so entirely outside the bounding box.
        _window_entry("orb", 11, -2, _STANDARD_KEY, size=4),
        # Right edge sits exactly on the bounding box left edge.
        _window_entry("orb", -14, -2, _STANDARD_KEY, size=4),
        # One pixel further left, so entirely outside the bounding box.
        _window_entry("orb", -15, -2, _STANDARD_KEY, size=4),
    ]

    groups = build_radius_regions(entries, center_px=(0, 0), radius_px=10)

    assert groups[("8", "standard", "default", None)].rectangles == [
        (-1, -1, 2, 2),
        (10, -2, 4, 4),
        (-14, -2, 4, 4),
    ]


def test_radius_feature_indices_selects_inside_and_on_circle() -> None:
    points = np.array(
        [
            (0.0, 0.0),      # 0: circle centre
            (3.0, 4.0),      # 1: squared distance equals the radius squared
            (3.0, 5.0),      # 2: just outside
            (100.0, -100.0),  # 3: far outside
        ],
        dtype=np.float64,
    )

    indices = select_radius_feature_indices(points, center_px=(0.0, 0.0), radius_px=5.0)

    assert indices.tolist() == [0, 1]
    assert indices.dtype == np.int64


def test_radius_feature_indices_accepts_integer_points_and_empty_input() -> None:
    integer_points = np.array([(3, 4), (4, 4)], dtype=np.int32)
    assert select_radius_feature_indices(
        integer_points, center_px=(0, 0), radius_px=5
    ).tolist() == [0]

    for points in (np.empty((0, 2)), np.empty((0, 2), dtype=np.int32)):
        indices = select_radius_feature_indices(points, center_px=(0, 0), radius_px=5.0)

        assert indices.size == 0
        assert indices.dtype == np.int64
