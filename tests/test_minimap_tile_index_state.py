from pathlib import Path

from core.map_context import TileKey
from minimap_tile_geometry import url_tile_to_map_pixel
from minimap_tile_index_state import (
    COARSE_PHASES,
    COARSE_WINDOW_SIZE,
    TileIndexStateStore,
    TileIndexStatus,
    canonical_coarse_window_key,
    canonical_tile_key,
    coarse_lattice_base,
    coarse_tile_origin,
    coarse_tile_span,
    coarse_window_index_span,
    coarse_window_left_top,
    coarse_window_rects_for_tile,
)


def _tile(x: int, y: int, *, kind: str = "standard", layer_id: str = "default", z_level=None) -> TileKey:
    return TileKey(area_id="8", layer_id=layer_id, z_level=z_level, kind=kind, x=x, y=y)


def _partition(start: int, stop: int, base: int, window_size: int) -> list[int]:
    """Every window edge of one lattice that overlaps ``[start, stop)``, in order."""
    first = (start - base) // window_size - 1
    values = []
    value = base + window_size * first
    while value < stop:
        if value + window_size > start:
            values.append(value)
        value += window_size
    return values


def _phase_base_congruence(tile_size: int, phase: tuple[int, int]) -> tuple[int, int]:
    """The ``(left % W, top % W)`` pair that identifies one phase's lattice."""
    return (
        coarse_lattice_base(tile_size, COARSE_WINDOW_SIZE, phase[0]) % COARSE_WINDOW_SIZE,
        coarse_lattice_base(tile_size, COARSE_WINDOW_SIZE, phase[1]) % COARSE_WINDOW_SIZE,
    )


def _rects_of_phase(rects: list[tuple[int, int]], tile_size: int, phase: tuple[int, int]) -> list[tuple[int, int]]:
    congruence = _phase_base_congruence(tile_size, phase)
    return [(left, top) for left, top in rects if (left % COARSE_WINDOW_SIZE, top % COARSE_WINDOW_SIZE) == congruence]


def test_coarse_phases_are_four_half_window_shifts_including_the_corner_phase():
    assert set(COARSE_PHASES) == {(0, 0), (1, 0), (0, 1), (1, 1)}
    assert len({_phase_base_congruence(1024, phase) for phase in COARSE_PHASES}) == 4


def test_coarse_lattice_bases_place_each_phase_shift_half_a_window_apart():
    half = COARSE_WINDOW_SIZE // 2
    unshifted_x = coarse_lattice_base(1024, COARSE_WINDOW_SIZE, 0)
    shifted_x = coarse_lattice_base(1024, COARSE_WINDOW_SIZE, 1)
    unshifted_y = coarse_lattice_base(1024, COARSE_WINDOW_SIZE, 0)
    shifted_y = coarse_lattice_base(1024, COARSE_WINDOW_SIZE, 1)

    assert unshifted_x == 1024 // 2 - half
    assert shifted_x == unshifted_x + half
    assert shifted_y == unshifted_y + half


def test_coarse_window_left_top_equals_the_lab_anchored_crop_origin():
    tile_size = 1024
    window_size = COARSE_WINDOW_SIZE
    anchor = tile_size // 2
    half = window_size // 2

    for shift_x, shift_y in COARSE_PHASES:
        for index_x in (-3, -1, 0, 2, 7):
            for index_y in (-5, 0, 4):
                # The lab places a window centre at ``offset + size * index`` in the
                # anchored basis and cuts from ``centre - size/2 + anchor``.
                centre_x = (half if shift_x else 0) + window_size * index_x
                centre_y = (half if shift_y else 0) + window_size * index_y

                assert coarse_window_left_top(
                    tile_size,
                    window_size,
                    shift_x=shift_x,
                    shift_y=shift_y,
                    index_x=index_x,
                    index_y=index_y,
                ) == (centre_x - half + anchor, centre_y - half + anchor)


def test_coarse_window_left_top_steps_by_exactly_one_window_and_keeps_phase_congruence():
    # Lattice-edge residues measured against the lab basis: an unshifted phase edge is
    # ``0*200 - 200 + 512 = 312 (mod 400)``, a half-window-shifted edge is
    # ``200 - 200 + 512 = 512 -> 112``. A residue cannot see a whole-window translate,
    # which is why the absolute position is pinned by the lab-equivalence test instead.
    residues = {0: 312, 1: 112}
    for shift_x, shift_y in COARSE_PHASES:
        previous = None
        for index in range(-4, 5):
            left, top = coarse_window_left_top(
                1024,
                COARSE_WINDOW_SIZE,
                shift_x=shift_x,
                shift_y=shift_y,
                index_x=index,
                index_y=index,
            )
            assert left % COARSE_WINDOW_SIZE == residues[shift_x]
            assert top % COARSE_WINDOW_SIZE == residues[shift_y]
            if previous is not None:
                assert (left, top) == (previous[0] + COARSE_WINDOW_SIZE, previous[1] + COARSE_WINDOW_SIZE)
            previous = (left, top)


def test_coarse_tile_origin_matches_the_sift_map_pixel_basis():
    for x, y in ((1, 0), (3, -5), (0, 7), (-4, -4)):
        origin = coarse_tile_origin(x, y, 1024)
        map_x, map_y = url_tile_to_map_pixel(x, y, 0, 0, tile_size=1024)

        assert origin == (int(map_x), int(map_y))


def test_coarse_tile_span_covers_exactly_the_touched_tiles():
    assert list(coarse_tile_span(2048, 384, 1024)) == [2]
    assert list(coarse_tile_span(2047, 384, 1024)) == [1, 2]
    assert list(coarse_tile_span(-1024, 384, 1024)) == [-1]
    assert list(coarse_tile_span(-1, 384, 1024)) == [-1, 0]


def test_coarse_window_index_span_reaches_every_overlapping_window():
    base = coarse_lattice_base(1024, COARSE_WINDOW_SIZE, 0)
    span = coarse_window_index_span(2048, 4096, base, COARSE_WINDOW_SIZE)
    lefts = [base + COARSE_WINDOW_SIZE * index for index in span]

    assert [left for left in lefts if left < 4096 and left + COARSE_WINDOW_SIZE > 2048] == _partition(
        2048, 4096, base, COARSE_WINDOW_SIZE
    )


def test_coarse_window_rects_for_tile_partitions_the_tile_once_per_phase():
    tile_size = 1024
    rects = coarse_window_rects_for_tile(3, -5, tile_size=tile_size, window_size=COARSE_WINDOW_SIZE)
    tile_left, tile_top = coarse_tile_origin(3, -5, tile_size)
    tile_right, tile_bottom = tile_left + tile_size, tile_top + tile_size

    assert len(rects) == len(set(rects))
    for left, top in rects:
        assert left < tile_right and left + COARSE_WINDOW_SIZE > tile_left
        assert top < tile_bottom and top + COARSE_WINDOW_SIZE > tile_top

    for phase in COARSE_PHASES:
        base_x = coarse_lattice_base(tile_size, COARSE_WINDOW_SIZE, phase[0])
        base_y = coarse_lattice_base(tile_size, COARSE_WINDOW_SIZE, phase[1])
        expected_xs = _partition(tile_left, tile_right, base_x, COARSE_WINDOW_SIZE)
        expected_ys = _partition(tile_top, tile_bottom, base_y, COARSE_WINDOW_SIZE)

        assert sorted(_rects_of_phase(rects, tile_size, phase)) == sorted(
            (x, y) for x in expected_xs for y in expected_ys
        )


def test_coarse_window_rects_do_not_overlap_within_one_phase():
    rects = coarse_window_rects_for_tile(3, -5, tile_size=1024, window_size=COARSE_WINDOW_SIZE)

    for phase in COARSE_PHASES:
        covered: dict[tuple[int, int], int] = {}
        for left, top in _rects_of_phase(rects, 1024, phase):
            for x in range(left, left + COARSE_WINDOW_SIZE, 96):
                for y in range(top, top + COARSE_WINDOW_SIZE, 64):
                    covered[(x, y)] = covered.get((x, y), 0) + 1

        assert covered, phase
        assert set(covered.values()) == {1}


def test_the_four_phases_overlap_so_a_coordinate_is_sampled_four_times():
    rects = coarse_window_rects_for_tile(3, -5, tile_size=1024, window_size=COARSE_WINDOW_SIZE)
    tile_left, tile_top = coarse_tile_origin(3, -5, 1024)
    samples = [
        (x, y)
        for x in range(tile_left + 64, tile_left + 1024, 96)
        for y in range(tile_top + 64, tile_top + 1024, 64)
    ]

    coverage = {
        sample: sum(
            1
            for left, top in rects
            if left <= sample[0] < left + COARSE_WINDOW_SIZE and top <= sample[1] < top + COARSE_WINDOW_SIZE
        )
        for sample in samples
    }

    # Phases B, C and D are half-window translates of phase A, so their windows
    # overlap phase A's. Only the centres are pairwise distinct. The lab samples every
    # map coordinate exactly four times, so the count is literal, not ``len(COARSE_PHASES)``.
    assert set(coverage.values()) == {4}


def test_coarse_window_rects_are_absolute_lattice_points_not_tile_relative():
    rects = coarse_window_rects_for_tile(3, -5, tile_size=1024, window_size=COARSE_WINDOW_SIZE)

    # Every rect sits on exactly one phase lattice.
    assert {_phase_base_congruence(1024, phase) for phase in COARSE_PHASES} == {
        (left % COARSE_WINDOW_SIZE, top % COARSE_WINDOW_SIZE) for left, top in rects
    }

    # A neighbouring tile is one full 1024 map pixels away, which is not a whole number
    # of 400 windows, so its window set is the same absolute lattice re-clipped rather
    # than the previous set translated.
    neighbour = set(coarse_window_rects_for_tile(4, -5, tile_size=1024, window_size=COARSE_WINDOW_SIZE))
    translated = {(left + 1024, top) for left, top in rects}
    shared = set(rects) & neighbour

    assert neighbour != translated
    assert shared
    assert all(left < 3072 and left + COARSE_WINDOW_SIZE > 3072 for left, _top in shared)


def test_canonical_coarse_window_key_is_plane_and_absolute_rect_only():
    key = _tile(10, 20)

    assert canonical_coarse_window_key(key, 2048, -640) == "8|standard|default|base|2048_-640"
    assert canonical_coarse_window_key(key, -2048, 640) == "8|standard|default|base|-2048_640"
    assert canonical_coarse_window_key(_tile(11, 20), 2048, -640) == canonical_coarse_window_key(key, 2048, -640)
    assert canonical_coarse_window_key(key, 2048, -640) != canonical_coarse_window_key(key, 2432, -640)
    assert canonical_coarse_window_key(
        _tile(10, 20, kind="layered", layer_id="2", z_level=-1), 2048, -640
    ) != canonical_coarse_window_key(key, 2048, -640)


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


def test_tile_index_state_clear_removes_every_persisted_status(tmp_path):
    store = TileIndexStateStore(tmp_path, area_id="8")
    key = _tile(10, 20)
    store.set_tile_status(key, TileIndexStatus(tile_present=True, rough_indexed=True, sift_indexed=True, file_mtime_ns=1, file_size=2))
    store.save()

    TileIndexStateStore(tmp_path, area_id="8").clear()

    reloaded = TileIndexStateStore(tmp_path, area_id="8")
    assert reloaded.tile_status_items() == []
    assert reloaded.get_tile_status(key) == TileIndexStatus()


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
