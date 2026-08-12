from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import time
from typing import Any

import numpy as np

from core.map_context import CoordinateCandidate, MapContext
from coordinate_continuity import ContinuityState
from coordinate_decision import choose_coordinate
from minimap_heading import detect_heading
from minimap_roi import MinimapRoi, build_minimap_texture_match_mask, crop_minimap_from_frame, normalize_minimap_crop
from minimap_stability_config import MinimapStabilityConfig, load_minimap_stability_config
from minimap_visual_locator import MinimapVisualLocator, VisualMatchConfig


def _serialize(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    return obj


def run_observation_paths(
    frame: np.ndarray,
    *,
    map_context: MapContext | None = None,
    roi: MinimapRoi | None = None,
    tile_root: Path | None = None,
    ocr_candidate: CoordinateCandidate | None = None,
    continuity: ContinuityState | None = None,
    stability_config: MinimapStabilityConfig | None = None,
    detect_heading_enabled: bool = True,
    vision_locator: MinimapVisualLocator | None = None,
) -> dict[str, Any]:
    """Run the current OCR/visual/heading decision pipeline on one provided frame."""
    total_start = time.perf_counter()
    continuity = continuity or ContinuityState()
    stability_config = stability_config or load_minimap_stability_config()
    normalized = None
    visual_candidate = None
    visual_result = None
    visual_trace = None
    heading_candidate = None
    heading_failure_reason = ""
    visual_failure_reason = ""
    timings_ms: dict[str, float] = {
        "normalize_minimap": 0.0,
        "heading": 0.0,
        "visual": 0.0,
        "decision": 0.0,
        "total": 0.0,
    }

    if roi is not None:
        minimap_crop = crop_minimap_from_frame(frame, roi)
        stage_start = time.perf_counter()
        normalized = normalize_minimap_crop(minimap_crop, roi.shape)
        timings_ms["normalize_minimap"] = (time.perf_counter() - stage_start) * 1000.0
        if detect_heading_enabled and stability_config.heading_recognition_enabled:
            stage_start = time.perf_counter()
            heading_candidate = detect_heading(
                normalized.exact_image,
                normalized.mask,
            )
            if heading_candidate is None:
                heading_failure_reason = "no_heading_match"
            timings_ms["heading"] = (time.perf_counter() - stage_start) * 1000.0
        else:
            heading_failure_reason = "heading_disabled"

        if map_context is not None and tile_root is not None:
            stage_start = time.perf_counter()
            locator = vision_locator or MinimapVisualLocator(
                tile_root,
                config=VisualMatchConfig(
                    rough_candidate_limit=stability_config.rough_candidate_limit,
                ),
            )
            visual_result = locator.match(
                normalized,
                build_minimap_texture_match_mask(normalized.mask),
                map_context,
                active_game_xy=None
                if continuity.previous_coordinate is None
                else (continuity.previous_coordinate[0], continuity.previous_coordinate[1]),
            )
            visual_trace = getattr(locator, "last_trace", None)
            visual_candidate = getattr(visual_result, "candidate", visual_result)
            if visual_candidate is None:
                visual_failure_reason = "no_visual_match"
            timings_ms["visual"] = (time.perf_counter() - stage_start) * 1000.0
        else:
            visual_failure_reason = "no_usable_scale_or_map_context"
    else:
        visual_failure_reason = "no_minimap_roi"
        heading_failure_reason = "no_minimap_roi"

    stage_start = time.perf_counter()
    decision = choose_coordinate(
        ocr_candidate,
        visual_candidate,
        continuity,
        agreement_xy_threshold=(
            stability_config.coordinate_agreement_x_threshold,
            stability_config.coordinate_agreement_y_threshold,
        ),
        history_xy_threshold=(
            stability_config.history_x_threshold,
            stability_config.history_y_threshold,
        ),
    )
    timings_ms["decision"] = (time.perf_counter() - stage_start) * 1000.0
    timings_ms["total"] = (time.perf_counter() - total_start) * 1000.0
    normalized_shape = tuple(int(x) for x in normalized.exact_image.shape) if normalized is not None else None

    return {
        "ocr_candidate": _serialize(ocr_candidate),
        "minimap_roi": _serialize(roi),
        "normalized_minimap_size": normalized_shape,
        "timings_ms": {key: round(value, 3) for key, value in timings_ms.items()},
        "stability_config": _serialize(stability_config),
        "visual_candidate": _serialize(visual_candidate),
        "visual_result": _serialize(visual_result),
        "visual_trace": _serialize(visual_trace),
        "visual_failure_reason": visual_failure_reason,
        "heading_candidate": _serialize(heading_candidate),
        "heading_failure_reason": heading_failure_reason,
        "continuity_status": {
            "previous_coordinate": continuity.previous_coordinate,
            "last_reset_reason": continuity.last_reset_reason,
        },
        "decision": {
            "coord": list(decision.coord) if decision.coord is not None else None,
            "source": decision.source,
            "reason": decision.reason,
        },
        "_decision_object": decision,
    }

