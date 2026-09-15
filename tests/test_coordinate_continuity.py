from coordinate_continuity import ContinuityState, xy_within_previous


def test_continuity_state_does_not_return_previous_coordinate_by_itself():
    state = ContinuityState()
    state.accept((2784, 3490, 124))
    assert state.previous_coordinate == (2784, 3490, 124)


def test_continuity_reset_clears_previous_coordinate():
    state = ContinuityState()
    state.accept((2784, 3490, 124))
    state.reset(reason="teleport_or_scene_change")
    assert state.previous_coordinate is None


def test_xy_within_previous_uses_xy_only():
    state = ContinuityState()
    state.accept((100, 200, 30))

    assert xy_within_previous(state, (120, 220, 999), threshold=50) is True
    assert xy_within_previous(state, (160, 220, 30), threshold=50) is False


def test_xy_within_previous_accepts_separate_axis_thresholds():
    state = ContinuityState()
    state.accept((100, 200, 30))

    assert xy_within_previous(state, (103, 220, 999), threshold=(3, 20)) is True
    assert xy_within_previous(state, (104, 220, 999), threshold=(3, 20)) is False


def test_xy_within_previous_returns_none_without_history():
    assert xy_within_previous(ContinuityState(), (120, 220, 30), threshold=50) is None


def test_single_source_streak_accumulates_for_stable_same_source():
    state = ContinuityState()
    state.accept((100, 200, 30))

    state.note_single_source_frame((1000, 2000), None, tolerance=50)
    state.note_single_source_frame((1010, 2005), None, tolerance=50)
    state.note_single_source_frame((1005, 1995), None, tolerance=50)

    assert state.single_source == "ocr"
    assert state.single_source_count == 3
    assert state.single_source_xy == (1000, 2000)


def test_single_source_streak_restarts_on_drift_and_source_switch():
    state = ContinuityState()
    state.accept((100, 200, 30))

    state.note_single_source_frame((1000, 2000), None, tolerance=50)
    state.note_single_source_frame((1400, 2000), None, tolerance=50)
    assert state.single_source_count == 1
    assert state.single_source_xy == (1400, 2000)

    state.note_single_source_frame(None, (1405, 2005), tolerance=50)
    assert state.single_source == "visual"
    assert state.single_source_count == 1


def test_single_source_streak_clears_when_both_or_neither_source_present():
    state = ContinuityState()
    state.accept((100, 200, 30))
    state.note_single_source_frame((1000, 2000), None, tolerance=50)

    state.note_single_source_frame((1000, 2000), (5000, 6000), tolerance=50)
    assert state.single_source_count == 0

    state.note_single_source_frame((1000, 2000), None, tolerance=50)
    state.note_single_source_frame(None, None, tolerance=50)
    assert state.single_source_count == 0


def test_single_source_streak_clears_without_history():
    state = ContinuityState()
    state.note_single_source_frame((1000, 2000), None, tolerance=50)
    assert state.single_source_count == 0


def test_accept_and_reset_clear_single_source_streak():
    state = ContinuityState()
    state.accept((100, 200, 30))
    state.note_single_source_frame((1000, 2000), None, tolerance=50)
    assert state.single_source_count == 1

    state.accept((1000, 2000, 30))
    assert state.single_source_count == 0

    state.note_single_source_frame((3000, 4000), None, tolerance=50)
    state.reset(reason="area_changed")
    assert state.single_source_count == 0
    assert state.single_source is None
