from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.map_context import CoordinateCandidate
from coordinate_continuity import AxisThreshold, ContinuityState, xy_within, xy_within_previous


@dataclass(frozen=True)
class CoordinateDecision:
    coord: Optional[tuple[int, int, int]]
    source: str
    reason: str


def _candidate_tuple(candidate: CoordinateCandidate, fallback_z: int | None = None) -> tuple[int, int, int]:
    z = candidate.z if candidate.z is not None else fallback_z
    if z is None:
        raise ValueError("coordinate_candidate_missing_z")
    return (candidate.x, candidate.y, z)


def _single_source_promotion_ready(
    continuity: ContinuityState,
    source: str,
    xy: tuple[int, int],
    min_frames: int,
    tolerance: AxisThreshold,
) -> bool:
    if continuity.single_source != source or continuity.single_source_xy is None:
        return False
    if continuity.single_source_count < min_frames:
        return False
    return xy_within(xy, continuity.single_source_xy, tolerance)


def choose_coordinate(
    ocr: CoordinateCandidate | None,
    visual: CoordinateCandidate | None,
    continuity: ContinuityState,
    agreement_xy_threshold: AxisThreshold = 50,
    history_xy_threshold: AxisThreshold = 150,
    promotion_frames: int = 5,
) -> CoordinateDecision:
    if ocr and visual:
        ocr_coord = _candidate_tuple(ocr)
        visual_z = ocr.z if ocr.z is not None else (
            continuity.previous_coordinate[2] if continuity.previous_coordinate is not None else None
        )
        if xy_within(ocr.as_xy_tuple(), visual.as_xy_tuple(), agreement_xy_threshold):
            return CoordinateDecision(ocr_coord, "ocr", "ocr_visual_agree")

        ocr_near = xy_within_previous(continuity, ocr_coord, history_xy_threshold)
        if visual_z is None:
            visual_near = None
        else:
            visual_near = xy_within_previous(
                continuity,
                (visual.x, visual.y, visual_z),
                history_xy_threshold,
            )

        if ocr_near is not None and visual_near is not None:
            if ocr_near and not visual_near:
                return CoordinateDecision(ocr_coord, "ocr", "ocr_near_history")
            if visual_near and not ocr_near:
                return CoordinateDecision((visual.x, visual.y, visual_z), "visual", "visual_near_history")
            if ocr_near and visual_near:
                return CoordinateDecision(ocr_coord, "ocr", "both_near_history_prefer_ocr")
            return CoordinateDecision(None, "none", "conflict_both_far_from_history")

        return CoordinateDecision(None, "none", "conflict_without_history_resolution")

    if ocr:
        ocr_coord = _candidate_tuple(ocr)
        ocr_near = xy_within_previous(continuity, ocr_coord, history_xy_threshold)
        if ocr_near is None:
            return CoordinateDecision(ocr_coord, "ocr", "ocr_only")
        if ocr_near:
            return CoordinateDecision(ocr_coord, "ocr", "ocr_only_near_history")
        if _single_source_promotion_ready(
            continuity,
            "ocr",
            ocr.as_xy_tuple(),
            promotion_frames,
            agreement_xy_threshold,
        ):
            return CoordinateDecision(ocr_coord, "ocr", "ocr_only_stable_promotion")
        return CoordinateDecision(None, "none", "ocr_only_far_from_history")

    if visual:
        if continuity.previous_coordinate is None:
            return CoordinateDecision(None, "none", "visual_xy_without_z")
        visual_coord = (visual.x, visual.y, continuity.previous_coordinate[2])
        visual_near = xy_within_previous(continuity, visual_coord, history_xy_threshold)
        if visual_near:
            return CoordinateDecision(visual_coord, "visual", "visual_only_near_history")
        if _single_source_promotion_ready(
            continuity,
            "visual",
            visual.as_xy_tuple(),
            promotion_frames,
            agreement_xy_threshold,
        ):
            return CoordinateDecision(visual_coord, "visual", "visual_only_stable_promotion")
        return CoordinateDecision(
            None,
            "none",
            "visual_only_far_from_history",
        )

    return CoordinateDecision(None, "none", "no_candidate")
