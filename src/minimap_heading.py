from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import numpy.typing as npt

from core import paths


DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO = 0.18
DEFAULT_HEADING_BUCKET_COUNT = 72
DEFAULT_HEADING_STEP_DEGREES = 5.0


@dataclass(frozen=True)
class HeadingCandidate:
    angle_degrees: float
    bucket: int
    confidence: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class HeadingTemplate:
    bgr: npt.NDArray[np.uint8]
    mask: npt.NDArray[np.uint8]


@dataclass(frozen=True)
class RotatedHeadingTemplate:
    bucket: int
    angle_degrees: float
    bgr: npt.NDArray[np.uint8]
    mask: npt.NDArray[np.uint8]


def default_heading_template_path() -> Path:
    return paths.asset_file("minimap_heading", "arrow_north.png")


def load_heading_template(template_path: str | Path | None = None) -> HeadingTemplate:
    path = Path(template_path) if template_path is not None else default_heading_template_path()
    image = None
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
        if encoded.size > 0:
            image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    except OSError:
        image = None
    if image is None:
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(str(path))
    if image.ndim == 2:
        bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        mask = np.full(image.shape, 255, dtype=np.uint8)
    elif image.shape[2] == 4:
        bgr = image[:, :, :3]
        alpha = image[:, :, 3]
        mask = np.where(alpha > 8, alpha, 0).astype(np.uint8)
    else:
        bgr = image[:, :, :3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        mask = np.where(gray > 8, 255, 0).astype(np.uint8)
    return HeadingTemplate(bgr=bgr, mask=mask)


def _rotate_image_and_mask(
    bgr: npt.NDArray[np.uint8],
    mask: npt.NDArray[np.uint8],
    angle_degrees: float,
) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint8]]:
    h, w = bgr.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    matrix[0, 2] += (new_w / 2.0) - center[0]
    matrix[1, 2] += (new_h / 2.0) - center[1]
    rotated_bgr = cv2.warpAffine(
        bgr,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    rotated_mask = cv2.warpAffine(
        mask,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return rotated_bgr, rotated_mask


def _resize_template_to_width(
    template: HeadingTemplate,
    target_width_px: int | None,
) -> HeadingTemplate:
    if target_width_px is None or target_width_px <= 0:
        return template
    current_h, current_w = template.bgr.shape[:2]
    if current_w <= 0:
        return template
    target_width = max(1, int(round(target_width_px)))
    target_height = max(1, int(round(current_h * (target_width / current_w))))
    if target_width == current_w and target_height == current_h:
        return template
    return HeadingTemplate(
        bgr=cv2.resize(template.bgr, (target_width, target_height), interpolation=cv2.INTER_AREA),
        mask=cv2.resize(template.mask, (target_width, target_height), interpolation=cv2.INTER_AREA),
    )


def generate_rotated_templates(
    template: HeadingTemplate,
    bucket_count: int = DEFAULT_HEADING_BUCKET_COUNT,
    step_degrees: float = DEFAULT_HEADING_STEP_DEGREES,
    *,
    minimap_diameter_px: int | float | None = None,
    template_width_ratio: float = DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO,
) -> list[RotatedHeadingTemplate]:
    if minimap_diameter_px is not None:
        template = _resize_template_to_width(
            template,
            int(round(float(minimap_diameter_px) * float(template_width_ratio))),
        )
    candidates: list[RotatedHeadingTemplate] = []
    for bucket in range(bucket_count):
        angle = float(bucket) * float(step_degrees)
        # User/game convention is clock angle: north=0, clockwise increases.
        # OpenCV positive angles rotate counter-clockwise, so render with -angle.
        bgr, mask = _rotate_image_and_mask(template.bgr, template.mask, -angle)
        candidates.append(RotatedHeadingTemplate(bucket=bucket, angle_degrees=angle % 360.0, bgr=bgr, mask=mask))
    return candidates


def _center_crop(image: npt.NDArray[np.uint8], size: int) -> npt.NDArray[np.uint8]:
    h, w = image.shape[:2]
    side = min(size, h, w)
    top = max(0, (h - side) // 2)
    left = max(0, (w - side) // 2)
    return image[top:top + side, left:left + side]


def _match_template(
    image: npt.NDArray[np.uint8],
    image_mask: npt.NDArray[np.uint8],
    candidate: RotatedHeadingTemplate,
) -> float:
    if image.shape[0] < candidate.bgr.shape[0] or image.shape[1] < candidate.bgr.shape[1]:
        return 0.0
    if image_mask.shape[:2] != image.shape[:2]:
        return 0.0
    template_h, template_w = candidate.mask.shape[:2]
    candidate_region = _center_crop(image_mask, max(template_h, template_w))
    if candidate_region.shape[:2] != candidate.mask.shape[:2]:
        candidate_region = cv2.resize(candidate_region, (template_w, template_h), interpolation=cv2.INTER_NEAREST)
    combined_mask = cv2.bitwise_and(candidate.mask, candidate_region.astype(np.uint8))
    if cv2.countNonZero(combined_mask) == 0:
        return 0.0
    result = cv2.matchTemplate(image, candidate.bgr, cv2.TM_CCORR_NORMED, mask=combined_mask)
    result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return float(max_val)


def detect_heading(
    normalized_minimap_image,
    minimap_mask,
    *,
    template_path: str | Path | None = None,
    confidence_threshold: float = 0.65,
    template_width_ratio: float = DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO,
) -> HeadingCandidate | None:
    debug = collect_heading_match_debug(
        normalized_minimap_image,
        minimap_mask,
        template_path=template_path,
        confidence_threshold=confidence_threshold,
        template_width_ratio=template_width_ratio,
        top_n=1,
    )
    candidate = debug.get("candidate")
    return candidate if isinstance(candidate, HeadingCandidate) else None


def collect_heading_match_debug(
    normalized_minimap_image,
    minimap_mask,
    *,
    template_path: str | Path | None = None,
    confidence_threshold: float = 0.65,
    template_width_ratio: float = DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO,
    top_n: int = 8,
) -> dict[str, object]:
    """Run heading matching and return the exact center input plus top bucket scores."""
    try:
        template = load_heading_template(template_path)
    except (FileNotFoundError, ValueError):
        return {
            "candidate": None,
            "scores": [],
            "center_image": None,
            "center_mask": None,
            "reason": "template_missing",
        }

    image = np.asarray(normalized_minimap_image)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    raw_mask = np.asarray(minimap_mask)
    if raw_mask.ndim == 3:
        raw_mask = cv2.cvtColor(raw_mask, cv2.COLOR_BGR2GRAY)
    masked_image = image.copy()
    if raw_mask.shape[:2] == image.shape[:2]:
        masked_image[raw_mask == 0] = 0
    minimap_diameter = int(min(image.shape[:2]))
    center_size = max(96, int(round(minimap_diameter * 0.5)))
    center = _center_crop(masked_image, center_size)
    center_mask = _center_crop(raw_mask.astype(np.uint8), center_size)
    best_candidate: RotatedHeadingTemplate | None = None
    best_score = 0.0
    scores: list[dict[str, float | int]] = []
    for candidate in generate_rotated_templates(
        template,
        minimap_diameter_px=minimap_diameter,
        template_width_ratio=template_width_ratio,
    ):
        score = _match_template(center, center_mask, candidate)
        scores.append(
            {
                "bucket": int(candidate.bucket),
                "angle_degrees": float(candidate.angle_degrees),
                "score": float(score),
            }
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate

    scores = sorted(scores, key=lambda item: float(item["score"]), reverse=True)
    if best_candidate is None or best_score < confidence_threshold:
        return {
            "candidate": None,
            "scores": scores[: max(1, int(top_n))],
            "center_image": center,
            "center_mask": center_mask,
            "reason": "below_threshold",
            "best_score": float(best_score),
            "confidence_threshold": float(confidence_threshold),
        }
    heading = HeadingCandidate(
        angle_degrees=best_candidate.angle_degrees,
        bucket=best_candidate.bucket,
        confidence=best_score,
    )
    return {
        "candidate": heading,
        "scores": scores[: max(1, int(top_n))],
        "center_image": center,
        "center_mask": center_mask,
        "reason": "",
        "best_score": float(best_score),
        "confidence_threshold": float(confidence_threshold),
    }
