import cv2
import numpy as np

from minimap_roi import (
    MinimapRoi,
    detect_minimap_circle_roi,
    normalize_minimap_crop,
    should_lock_auto_roi,
)
from screen_capture import FramePatch


def _paint_heading_arrow(frame: np.ndarray, center: tuple[int, int]) -> None:
    points = np.array([(0, -28), (17, 17), (0, 10), (-17, 17)], dtype=np.int32)
    points[:, 0] += center[0]
    points[:, 1] += center[1]
    cv2.fillPoly(frame, [points], (0, 210, 255))


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


def test_frame_patch_crop_uses_whole_frame_coordinates():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    frame[30:50, 20:60] = 255
    roi = MinimapRoi(x=20, y=30, width=40, height=20, shape="ellipse", source="manual")

    crop = FramePatch.whole(frame).crop(roi.x, roi.y, roi.width, roi.height)

    assert crop.shape == (20, 40, 3)
    assert crop.mean() == 255


def test_frame_patch_crop_clips_secondary_region_to_patch_extent():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    frame[10:30, 40:70] = 100
    patch = FramePatch.whole(frame).sub_rect(40, 10, 30, 20)

    crop = patch.crop(40, 10, 30, 20)

    assert patch.origin_x == 40
    assert patch.origin_y == 10
    assert crop.shape == (20, 30, 3)
    assert crop.mean() == 100


def test_frame_patch_crop_of_area_outside_patch_is_empty():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    patch = FramePatch.whole(frame).sub_rect(0, 0, 20, 20)

    assert patch.crop(50, 60, 10, 10).shape == (0, 0, 3)


def test_normalize_minimap_crop_outputs_exact_and_rough_images_with_mask():
    crop = np.full((100, 120, 3), 200, dtype=np.uint8)
    normalized = normalize_minimap_crop(crop, shape="circle")

    assert normalized.exact_image.shape == (100, 120, 3)
    assert normalized.mask.shape == (100, 120)
    assert normalized.rough_color_image.shape == (52, 52, 3)


def test_detect_minimap_circle_roi_uses_patch_extent_as_search_range():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 70), 42, (255, 255, 255), 3)
    cv2.circle(frame, (260, 170), 42, (255, 255, 255), 3)

    roi = detect_minimap_circle_roi(FramePatch.whole(frame).sub_rect(0, 0, 160, 140))

    assert roi is not None
    assert roi.source == "auto"
    assert roi.shape == "circle"
    assert abs((roi.x + roi.width // 2) - 80) <= 3
    assert abs((roi.y + roi.height // 2) - 70) <= 3
    assert abs(roi.width - 84) <= 6
    assert abs(roi.height - 84) <= 6


def test_detect_minimap_circle_roi_returns_none_outside_patch():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (260, 170), 42, (255, 255, 255), 3)

    assert detect_minimap_circle_roi(FramePatch.whole(frame).sub_rect(0, 0, 160, 140)) is None


def test_detect_minimap_circle_roi_reports_whole_frame_coordinates():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (180, 110), 42, (255, 255, 255), 3)

    roi = detect_minimap_circle_roi(FramePatch.whole(frame).sub_rect(100, 0, 160, 200))

    assert roi is not None
    assert abs((roi.x + roi.width // 2) - 180) <= 3
    assert abs((roi.y + roi.height // 2) - 110) <= 3


def test_auto_minimap_circle_roi_requires_arrow_anchor_when_requested():
    frame = np.zeros((220, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 70), 42, (255, 255, 255), 3)

    roi = detect_minimap_circle_roi(
        FramePatch.whole(frame).sub_rect(0, 0, 160, 140),
        require_arrow_anchor=True,
    )

    assert roi is None


def test_auto_minimap_circle_roi_prefers_circle_near_heading_arrow():
    frame = np.zeros((260, 360, 3), dtype=np.uint8)
    cv2.circle(frame, (100, 130), 48, (255, 255, 255), 3)
    cv2.circle(frame, (240, 130), 48, (255, 255, 255), 3)
    _paint_heading_arrow(frame, (240, 130))

    roi = detect_minimap_circle_roi(
        FramePatch.whole(frame).sub_rect(0, 0, 320, 260),
        require_arrow_anchor=True,
    )

    assert roi is not None
    assert abs((roi.x + roi.width // 2) - 240) <= 4
    assert abs((roi.y + roi.height // 2) - 130) <= 4
