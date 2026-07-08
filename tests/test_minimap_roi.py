import cv2
import numpy as np

from minimap_heading import load_heading_template
from minimap_roi import (
    MinimapRoi,
    crop_minimap_from_frame,
    detect_minimap_circle_roi,
    normalize_minimap_crop,
    should_lock_auto_roi,
)
from screen_capture import crop_image_region


def _paint_heading_arrow(frame: np.ndarray, center: tuple[int, int]) -> None:
    template = load_heading_template()
    h, w = template.bgr.shape[:2]
    left = int(center[0] - w // 2)
    top = int(center[1] - h // 2)
    alpha = (template.mask.astype(np.float32) / 255.0)[:, :, None]
    frame[top:top + h, left:left + w] = (
        template.bgr.astype(np.float32) * alpha
        + frame[top:top + h, left:left + w].astype(np.float32) * (1.0 - alpha)
    ).astype(np.uint8)


def test_manual_and_auto_roi_use_same_value_shape():
    roi = MinimapRoi(x=20, y=30, width=210, height=210, shape="circle", source="manual")
    assert roi.x == 20
    assert roi.source == "manual"


def test_auto_roi_locks_after_three_stable_frames():
    frames = [
        MinimapRoi(x=20, y=30, width=210, height=210, shape="circle", source="auto"),
        MinimapRoi(x=21, y=30, width=211, height=210, shape="circle", source="auto"),
        MinimapRoi(x=20, y=31, width=210, height=209, shape="circle", source="auto"),
    ]
    assert should_lock_auto_roi(frames, required_frames=3, tolerance_px=2)


def test_auto_roi_does_not_lock_when_recent_frames_are_unstable():
    frames = [
        MinimapRoi(x=20, y=30, width=210, height=210, shape="circle", source="auto"),
        MinimapRoi(x=40, y=30, width=210, height=210, shape="circle", source="auto"),
        MinimapRoi(x=20, y=31, width=210, height=209, shape="circle", source="auto"),
    ]
    assert not should_lock_auto_roi(frames, required_frames=3, tolerance_px=2)


def test_crop_minimap_from_frame_uses_single_screenshot_frame():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    frame[30:50, 20:60] = 255
    roi = MinimapRoi(x=20, y=30, width=40, height=20, shape="ellipse", source="manual")

    crop = crop_minimap_from_frame(frame, roi)

    assert crop.shape == (20, 40, 3)
    assert crop.mean() == 255


def test_normalize_minimap_crop_outputs_exact_and_rough_images_with_mask():
    crop = np.full((100, 120, 3), 200, dtype=np.uint8)
    normalized = normalize_minimap_crop(crop, shape="circle")

    assert normalized.exact_image.shape == (100, 120, 3)
    assert normalized.mask.shape == (100, 120)
    assert normalized.rough_color_image.shape == (52, 52, 3)


def test_screen_capture_can_extract_secondary_region_from_existing_frame():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    frame[10:30, 40:70] = 100

    crop = crop_image_region(frame, 40, 10, 30, 20)

    assert crop.shape == (20, 30, 3)
    assert crop.mean() == 100


def test_detect_minimap_circle_roi_uses_explicit_search_rect():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 70), 42, (255, 255, 255), 3)
    cv2.circle(frame, (260, 170), 42, (255, 255, 255), 3)

    roi = detect_minimap_circle_roi(frame, search_rect=(0, 0, 160, 140))

    assert roi is not None
    assert roi.source == "auto"
    assert roi.shape == "circle"
    assert abs((roi.x + roi.width // 2) - 80) <= 3
    assert abs((roi.y + roi.height // 2) - 70) <= 3
    assert abs(roi.width - 84) <= 6
    assert abs(roi.height - 84) <= 6


def test_detect_minimap_circle_roi_returns_none_without_search_rect_hit():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (260, 170), 42, (255, 255, 255), 3)

    assert detect_minimap_circle_roi(frame, search_rect=(0, 0, 160, 140)) is None


def test_auto_minimap_circle_roi_requires_arrow_anchor_when_requested():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 70), 42, (255, 255, 255), 3)

    roi = detect_minimap_circle_roi(
        frame,
        search_rect=(0, 0, 160, 140),
        require_arrow_anchor=True,
        arrow_confidence_threshold=0.9,
    )

    assert roi is None


def test_auto_minimap_circle_roi_prefers_circle_near_heading_arrow():
    frame = np.zeros((260, 360, 3), dtype=np.uint8)
    cv2.circle(frame, (100, 130), 48, (255, 255, 255), 3)
    cv2.circle(frame, (240, 130), 48, (255, 255, 255), 3)
    _paint_heading_arrow(frame, (240, 130))

    roi = detect_minimap_circle_roi(
        frame,
        search_rect=(0, 0, 320, 260),
        require_arrow_anchor=True,
        arrow_confidence_threshold=0.9,
    )

    assert roi is not None
    assert abs((roi.x + roi.width // 2) - 240) <= 4
    assert abs((roi.y + roi.height // 2) - 130) <= 4
