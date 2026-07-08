from core.map_context import CoordinateCandidate
from coordinate_continuity import ContinuityState
from coordinate_decision import choose_coordinate


def test_choose_coordinate_accepts_agreement_without_history():
    ocr = CoordinateCandidate(100, 200, 30, source="ocr")
    visual = CoordinateCandidate(101, 201, None, source="visual")
    result = choose_coordinate(
        ocr,
        visual,
        ContinuityState(),
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord == (100, 200, 30)
    assert result.reason == "ocr_visual_agree"


def test_choose_coordinate_accepts_separate_xy_agreement_thresholds():
    ocr = CoordinateCandidate(100, 200, 30, source="ocr")
    visual = CoordinateCandidate(103, 220, None, source="visual")

    accepted = choose_coordinate(
        ocr,
        visual,
        ContinuityState(),
        agreement_xy_threshold=(3, 20),
        history_xy_threshold=150,
    )
    rejected = choose_coordinate(
        ocr,
        visual,
        ContinuityState(),
        agreement_xy_threshold=(2, 20),
        history_xy_threshold=150,
    )

    assert accepted.reason == "ocr_visual_agree"
    assert rejected.reason == "conflict_without_history_resolution"


def test_choose_coordinate_accepts_ocr_when_visual_is_missing():
    ocr = CoordinateCandidate(100, 200, 30, source="ocr")
    result = choose_coordinate(
        ocr,
        None,
        ContinuityState(),
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord == (100, 200, 30)
    assert result.reason == "ocr_only"


def test_choose_coordinate_accepts_ocr_only_near_history():
    state = ContinuityState()
    state.accept((100, 200, 30))
    ocr = CoordinateCandidate(120, 230, 31, source="ocr")
    result = choose_coordinate(
        ocr,
        None,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord == (120, 230, 31)
    assert result.reason == "ocr_only_near_history"


def test_choose_coordinate_rejects_ocr_only_far_from_history():
    state = ContinuityState()
    state.accept((11820, 11252, 289))
    ocr = CoordinateCandidate(11870, 1125, 289, source="ocr")
    result = choose_coordinate(
        ocr,
        None,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord is None
    assert result.reason == "ocr_only_far_from_history"


def test_choose_coordinate_accepts_visual_only_near_history_with_last_z():
    state = ContinuityState()
    state.accept((1000, 2000, 30))
    visual = CoordinateCandidate(1040, 1980, None, source="visual")
    result = choose_coordinate(
        None,
        visual,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord == (1040, 1980, 30)
    assert result.reason == "visual_only_near_history"


def test_choose_coordinate_rejects_visual_only_far_from_history():
    state = ContinuityState()
    state.accept((10935, 10795, 54))
    visual = CoordinateCandidate(9978, 8784, None, source="visual")
    result = choose_coordinate(
        None,
        visual,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord is None
    assert result.reason == "visual_only_far_from_history"


def test_choose_coordinate_uses_history_only_for_large_conflict():
    state = ContinuityState()
    state.accept((100, 200, 30))
    ocr = CoordinateCandidate(10000, 20000, 30, source="ocr")
    visual = CoordinateCandidate(102, 202, None, source="visual")
    result = choose_coordinate(
        ocr,
        visual,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord == (102, 202, 30)
    assert result.reason == "visual_near_history"


def test_choose_coordinate_rejects_when_conflict_and_both_far_from_history():
    state = ContinuityState()
    state.accept((100, 200, 30))
    ocr = CoordinateCandidate(10000, 20000, 30, source="ocr")
    visual = CoordinateCandidate(-5000, -6000, None, source="visual")
    result = choose_coordinate(
        ocr,
        visual,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord is None
    assert result.reason == "conflict_both_far_from_history"


def test_choose_coordinate_prefers_ocr_when_both_conflicting_candidates_are_near_history():
    state = ContinuityState()
    state.accept((100, 200, 30))
    ocr = CoordinateCandidate(140, 220, 31, source="ocr")
    visual = CoordinateCandidate(40, 210, None, source="visual")
    result = choose_coordinate(
        ocr,
        visual,
        state,
        agreement_xy_threshold=50,
        history_xy_threshold=150,
    )
    assert result.coord == (140, 220, 31)
    assert result.reason == "both_near_history_prefer_ocr"
