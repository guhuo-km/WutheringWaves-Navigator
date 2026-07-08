from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np
import numpy.typing as npt

from minimap_heading import generate_rotated_templates, load_heading_template


@dataclass(frozen=True)
class MinimapRoi:
    x: int
    y: int
    width: int
    height: int
    shape: str  # circle | ellipse
    source: str  # manual | auto


@dataclass(frozen=True)
class MinimapArrowAnchor:
    x: int
    y: int
    score: float
    angle_degrees: float
    scale: float


@dataclass(frozen=True)
class NormalizedMinimap:
    exact_image: npt.NDArray[np.uint8]
    mask: npt.NDArray[np.uint8]
    rough_color_image: npt.NDArray[np.uint8]


def should_lock_auto_roi(
    frames: Sequence[MinimapRoi],
    required_frames: int = 3,
    tolerance_px: int = 2,
) -> bool:
    if required_frames <= 0 or len(frames) < required_frames:
        return False

    recent = list(frames[-required_frames:])
    first = recent[0]
    fields = ("x", "y", "width", "height")
    for frame in recent[1:]:
        if frame.shape != first.shape:
            return False
        for field in fields:
            if abs(getattr(frame, field) - getattr(first, field)) > tolerance_px:
                return False
    return True


def crop_minimap_from_frame(
    frame: npt.NDArray[np.uint8],
    roi: MinimapRoi,
) -> npt.NDArray[np.uint8]:
    from screen_capture import crop_image_region

    return crop_image_region(frame, roi.x, roi.y, roi.width, roi.height)


def _resize_template(
    image: npt.NDArray[np.uint8],
    scale: float,
    interpolation: int,
) -> npt.NDArray[np.uint8]:
    if scale == 1.0:
        return image
    height, width = image.shape[:2]
    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (scaled_width, scaled_height), interpolation=interpolation)


def detect_minimap_arrow_anchor(
    frame: npt.NDArray[np.uint8],
    search_rect: tuple[int, int, int, int],
    *,
    confidence_threshold: float = 0.72,
    scale_candidates: Sequence[float] = (0.75, 0.875, 1.0, 1.125, 1.25),
) -> MinimapArrowAnchor | None:
    """Locate the fixed player arrow inside the minimap search rectangle."""
    if frame is None or frame.size == 0:
        return None
    x, y, width, height = [int(value) for value in search_rect]
    if width <= 0 or height <= 0:
        return None

    image_h, image_w = frame.shape[:2]
    left = max(0, x)
    top = max(0, y)
    right = min(image_w, left + width)
    bottom = min(image_h, top + height)
    if right <= left or bottom <= top:
        return None

    search = frame[top:bottom, left:right]
    if search.ndim == 2:
        search_bgr = cv2.cvtColor(search, cv2.COLOR_GRAY2BGR)
    elif search.shape[2] == 4:
        search_bgr = cv2.cvtColor(search, cv2.COLOR_BGRA2BGR)
    else:
        search_bgr = search[:, :, :3]

    try:
        template = load_heading_template()
    except (FileNotFoundError, ValueError):
        return None

    best: MinimapArrowAnchor | None = None
    for rotated in generate_rotated_templates(template, bucket_count=36, step_degrees=10.0):
        for scale in scale_candidates:
            scaled_bgr = _resize_template(rotated.bgr, float(scale), cv2.INTER_LINEAR)
            scaled_mask = _resize_template(rotated.mask, float(scale), cv2.INTER_NEAREST)
            th, tw = scaled_bgr.shape[:2]
            if th <= 0 or tw <= 0 or th > search_bgr.shape[0] or tw > search_bgr.shape[1]:
                continue
            if cv2.countNonZero(scaled_mask.astype(np.uint8)) == 0:
                continue
            result = cv2.matchTemplate(
                search_bgr,
                scaled_bgr,
                cv2.TM_CCORR_NORMED,
                mask=scaled_mask.astype(np.uint8),
            )
            result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
            _, score, _, max_loc = cv2.minMaxLoc(result)
            if best is None or float(score) > best.score:
                best = MinimapArrowAnchor(
                    x=int(round(left + max_loc[0] + tw / 2.0)),
                    y=int(round(top + max_loc[1] + th / 2.0)),
                    score=float(score),
                    angle_degrees=rotated.angle_degrees,
                    scale=float(scale),
                )

    if best is None or best.score < float(confidence_threshold):
        return None
    return best


def detect_minimap_circle_roi(
    frame: npt.NDArray[np.uint8],
    search_rect: tuple[int, int, int, int],
    *,
    require_arrow_anchor: bool = False,
    arrow_confidence_threshold: float = 0.72,
) -> MinimapRoi | None:
    """Detect a circular minimap ROI inside an explicitly supplied search rectangle."""
    if frame is None or frame.size == 0:
        return None
    x, y, width, height = [int(value) for value in search_rect]
    if width <= 0 or height <= 0:
        return None

    image_h, image_w = frame.shape[:2]
    left = max(0, x)
    top = max(0, y)
    right = min(image_w, left + width)
    bottom = min(image_h, top + height)
    if right <= left or bottom <= top:
        return None

    arrow_anchor = None
    if require_arrow_anchor:
        arrow_anchor = detect_minimap_arrow_anchor(
            frame,
            (left, top, right - left, bottom - top),
            confidence_threshold=arrow_confidence_threshold,
        )
        if arrow_anchor is None:
            return None

    search = frame[top:bottom, left:right]
    gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY) if search.ndim == 3 else search
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    min_dim = min(search.shape[:2])
    min_radius = max(12, int(min_dim * 0.15))
    max_radius = max(min_radius + 1, int(min_dim * 0.48))
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(20, min_radius),
        param1=80,
        param2=18,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return None

    candidates = []
    for cx, cy, radius in np.round(circles[0]).astype(int):
        if radius <= 0:
            continue
        roi_left = left + int(cx - radius)
        roi_top = top + int(cy - radius)
        diameter = int(radius * 2)
        if diameter <= 0:
            continue
        candidates.append(
            MinimapRoi(
                x=roi_left,
                y=roi_top,
                width=diameter,
                height=diameter,
                shape="circle",
                source="auto",
            )
        )
    if not candidates:
        return None

    if arrow_anchor is not None:
        nearby_candidates = []
        for roi in candidates:
            roi_center_x = roi.x + roi.width / 2.0
            roi_center_y = roi.y + roi.height / 2.0
            center_distance = abs(roi_center_x - arrow_anchor.x) + abs(roi_center_y - arrow_anchor.y)
            max_distance = max(16.0, max(roi.width, roi.height) * 0.35)
            if center_distance <= max_distance:
                nearby_candidates.append(roi)
        if not nearby_candidates:
            return None
        return min(
            nearby_candidates,
            key=lambda roi: (
                abs((roi.x + roi.width / 2.0) - arrow_anchor.x)
                + abs((roi.y + roi.height / 2.0) - arrow_anchor.y),
                -roi.width,
            ),
        )

    search_center_x = left + (right - left) / 2.0
    search_center_y = top + (bottom - top) / 2.0
    return min(
        candidates,
        key=lambda roi: (
            abs((roi.x + roi.width / 2.0) - search_center_x)
            + abs((roi.y + roi.height / 2.0) - search_center_y),
            -roi.width,
        ),
    )


def _build_mask(width: int, height: int, shape: str) -> npt.NDArray[np.uint8]:
    mask = np.zeros((height, width), dtype=np.uint8)
    if shape == "ellipse":
        center = (width // 2, height // 2)
        axes = (max(1, width // 2), max(1, height // 2))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
    else:
        cv2.circle((mask), (width // 2, height // 2), max(1, min(width, height) // 2), 255, -1)
    return mask


def build_minimap_texture_match_mask(
    base_mask: npt.NDArray[np.uint8],
    center_exclusion_ratio: float = 0.18,
) -> npt.NDArray[np.uint8]:
    """Return a map-texture mask that ignores the fixed player arrow at center."""
    mask = np.asarray(base_mask, dtype=np.uint8).copy()
    if mask.ndim != 2 or mask.size == 0:
        return mask
    height, width = mask.shape[:2]
    radius = max(1, int(round(min(width, height) * float(center_exclusion_ratio))))
    center = (width // 2, height // 2)
    cv2.circle(mask, center, radius, 0, -1)
    return mask


def normalize_minimap_crop(
    crop: npt.NDArray[np.uint8],
    shape: str,
    rough_size: int = 52,
) -> NormalizedMinimap:
    exact = crop.copy()
    rough = cv2.resize(crop, (rough_size, rough_size), interpolation=cv2.INTER_AREA)
    height, width = exact.shape[:2]
    return NormalizedMinimap(
        exact_image=exact,
        mask=_build_mask(width, height, shape),
        rough_color_image=rough,
    )
