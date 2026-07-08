from dataclasses import dataclass

from minimap_sift_matcher import filter_ratio_matches


@dataclass
class FakeMatch:
    distance: float


def test_filter_ratio_matches_keeps_only_clear_matches():
    kept = filter_ratio_matches(
        [
            [FakeMatch(10), FakeMatch(20)],
            [FakeMatch(18), FakeMatch(20)],
            [FakeMatch(5)],
        ],
        ratio=0.75,
    )

    assert len(kept) == 1
    assert kept[0].distance == 10
