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
