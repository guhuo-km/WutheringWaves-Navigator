from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import numpy.typing as npt


DEFAULT_HEADING_SEARCH_RADIUS_RATIO = 0.45
DEFAULT_HEADING_H_MIN = 12
DEFAULT_HEADING_H_MAX = 48
DEFAULT_HEADING_S_MIN = 90
DEFAULT_HEADING_V_MIN = 145
DEFAULT_HEADING_MIN_AREA = 35
DEFAULT_HEADING_BUCKET_COUNT = 72
DEFAULT_HEADING_STEP_DEGREES = 5.0


@dataclass(frozen=True)
class HeadingCandidate:
    angle_degrees: float
    bucket: int
    confidence: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class HeadingGeometry:
    angle_degrees: float
    centroid_x: float
    centroid_y: float
    tip_x: float
    tip_y: float
    area: int
    elongation: float
    tip_tail_width_ratio: float
    confidence: float


def _as_bgr(image: npt.ArrayLike) -> npt.NDArray[np.uint8] | None:
    array = np.asarray(image)
    if array.size == 0:
        return None
    if array.ndim == 2:
        return cv2.cvtColor(array.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if array.ndim != 3 or array.shape[2] < 3:
        return None
    if array.shape[2] == 4:
        return cv2.cvtColor(array.astype(np.uint8), cv2.COLOR_BGRA2BGR)
    return array[:, :, :3].astype(np.uint8, copy=False)


def build_heading_color_mask(
    image: npt.ArrayLike,
    valid_mask: npt.ArrayLike | None = None,
    *,
    search_radius_ratio: float = DEFAULT_HEADING_SEARCH_RADIUS_RATIO,
    h_min: int = DEFAULT_HEADING_H_MIN,
    h_max: int = DEFAULT_HEADING_H_MAX,
    s_min: int = DEFAULT_HEADING_S_MIN,
    v_min: int = DEFAULT_HEADING_V_MIN,
) -> npt.NDArray[np.uint8]:
    bgr = _as_bgr(image)
    if bgr is None:
        return np.zeros((0, 0), dtype=np.uint8)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    color_mask = cv2.inRange(
        hsv,
        np.array((int(h_min), int(s_min), int(v_min)), dtype=np.uint8),
        np.array((int(h_max), 255, 255), dtype=np.uint8),
    )
    height, width = color_mask.shape
    center_mask = np.zeros_like(color_mask)
    radius = max(1, int(round(min(width, height) * float(search_radius_ratio))))
    cv2.circle(center_mask, (width // 2, height // 2), radius, 255, -1)
    color_mask = cv2.bitwise_and(color_mask, center_mask)

    if valid_mask is not None:
        raw_mask = np.asarray(valid_mask)
        if raw_mask.ndim == 3:
            raw_mask = cv2.cvtColor(raw_mask.astype(np.uint8), cv2.COLOR_BGR2GRAY)
        if raw_mask.shape == color_mask.shape:
            color_mask = cv2.bitwise_and(color_mask, raw_mask.astype(np.uint8))
    return color_mask


def _component_geometry(
    component_mask: npt.NDArray[np.uint8],
    area: int,
) -> tuple[HeadingGeometry | None, str]:
    points_yx = np.column_stack(np.nonzero(component_mask))
    if len(points_yx) < 4:
        return None, "component_too_small"
    points = points_yx[:, ::-1].astype(np.float64)
    centroid = points.mean(axis=0)
    centered = points - centroid
    covariance = centered.T @ centered / float(len(points))
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major_index = int(np.argmax(eigenvalues))
    major_value = float(eigenvalues[major_index])
    minor_value = float(eigenvalues[1 - major_index])
    axis = eigenvectors[:, major_index]
    perpendicular = np.array((-axis[1], axis[0]), dtype=np.float64)
    along = centered @ axis
    across = centered @ perpendicular
    end_count = max(4, int(round(len(points) * 0.20)))
    order = np.argsort(along)
    negative_indices = order[:end_count]
    positive_indices = order[-end_count:]

    def end_width(indices: npt.NDArray[np.int64]) -> float:
        values = across[indices]
        return float(values.max() - values.min())

    negative_width = end_width(negative_indices)
    positive_width = end_width(positive_indices)
    narrower_positive = positive_width < negative_width
    tip_indices = positive_indices if narrower_positive else negative_indices
    tip_index = tip_indices[int(np.argmax(along[tip_indices]))] if narrower_positive else tip_indices[int(np.argmin(along[tip_indices]))]
    tip = points[tip_index]
    direction = tip - centroid
    angle = (np.degrees(np.arctan2(direction[0], -direction[1])) + 360.0) % 360.0
    elongation = major_value / max(minor_value, 1e-6)
    width_ratio = max(negative_width, positive_width) / max(min(negative_width, positive_width), 1.0)

    if elongation < 1.18:
        return None, "weak_principal_axis"
    if width_ratio < 1.06:
        return None, "ambiguous_tip_tail"

    axis_strength = min(1.0, max(0.0, (elongation - 1.0) / 1.5))
    tip_strength = min(1.0, max(0.0, (width_ratio - 1.0) / 1.5))
    confidence = 0.5 * axis_strength + 0.5 * tip_strength
    return HeadingGeometry(
        angle_degrees=float(angle),
        centroid_x=float(centroid[0]),
        centroid_y=float(centroid[1]),
        tip_x=float(tip[0]),
        tip_y=float(tip[1]),
        area=int(area),
        elongation=float(elongation),
        tip_tail_width_ratio=float(width_ratio),
        confidence=float(confidence),
    ), ""


def detect_heading_geometry(
    image: npt.ArrayLike,
    valid_mask: npt.ArrayLike | None = None,
    *,
    search_radius_ratio: float = DEFAULT_HEADING_SEARCH_RADIUS_RATIO,
    min_area: int = DEFAULT_HEADING_MIN_AREA,
) -> tuple[HeadingGeometry | None, npt.NDArray[np.uint8], str]:
    bgr = _as_bgr(image)
    if bgr is None:
        return None, np.zeros((0, 0), dtype=np.uint8), "empty_image"
    color_mask = build_heading_color_mask(
        bgr,
        valid_mask,
        search_radius_ratio=search_radius_ratio,
    )
    component_count, labels, stats, centroids = cv2.connectedComponentsWithStats(color_mask, connectivity=8)
    image_center = np.array((bgr.shape[1] / 2.0, bgr.shape[0] / 2.0), dtype=np.float64)
    candidates: list[tuple[float, HeadingGeometry]] = []
    rejection_reason = "no_color_component"

    for label in range(1, component_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < int(min_area):
            continue
        component_mask = np.where(labels == label, 255, 0).astype(np.uint8)
        geometry, reason = _component_geometry(component_mask, area)
        if geometry is None:
            rejection_reason = reason
            continue
        distance = float(np.linalg.norm(centroids[label] - image_center))
        score = float(area) / (1.0 + distance * 0.08)
        candidates.append((score, geometry))

    if not candidates:
        return None, color_mask, rejection_reason
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1], color_mask, ""


def detect_heading(
    normalized_minimap_image: npt.ArrayLike,
    minimap_mask: npt.ArrayLike,
) -> HeadingCandidate | None:
    geometry, _, _ = detect_heading_geometry(normalized_minimap_image, minimap_mask)
    if geometry is None:
        return None
    bucket = int(round(geometry.angle_degrees / DEFAULT_HEADING_STEP_DEGREES)) % DEFAULT_HEADING_BUCKET_COUNT
    return HeadingCandidate(
        angle_degrees=geometry.angle_degrees,
        bucket=bucket,
        confidence=geometry.confidence,
        reason=(
            f"area={geometry.area};elongation={geometry.elongation:.3f};"
            f"tip_tail_width_ratio={geometry.tip_tail_width_ratio:.3f}"
        ),
    )


def collect_heading_geometry_debug(
    normalized_minimap_image: npt.ArrayLike,
    minimap_mask: npt.ArrayLike,
) -> dict[str, object]:
    bgr = _as_bgr(normalized_minimap_image)
    geometry, color_mask, reason = detect_heading_geometry(bgr, minimap_mask)
    overlay = None
    if bgr is not None:
        overlay = bgr.copy()
        if geometry is not None:
            centroid = (int(round(geometry.centroid_x)), int(round(geometry.centroid_y)))
            tip = (int(round(geometry.tip_x)), int(round(geometry.tip_y)))
            cv2.circle(overlay, centroid, 3, (255, 255, 0), -1)
            cv2.circle(overlay, tip, 4, (0, 255, 255), -1)
            cv2.line(overlay, centroid, tip, (0, 255, 255), 2)
    candidate = detect_heading(normalized_minimap_image, minimap_mask) if geometry is not None else None
    return {
        "candidate": candidate,
        "color_mask": color_mask,
        "overlay": overlay,
        "geometry": geometry,
        "reason": reason,
    }
