import cv2
import numpy as np

from minimap_heading import (
    DEFAULT_HEADING_SEARCH_RADIUS_RATIO,
    HeadingCandidate,
    detect_heading,
    detect_heading_geometry,
)


def _arrow_polygon(center: tuple[int, int], angle_degrees: float) -> np.ndarray:
    points = np.array(
        [
            (0.0, -28.0),
            (17.0, 17.0),
            (0.0, 10.0),
            (-17.0, 17.0),
        ],
        dtype=np.float32,
    )
    radians = np.radians(angle_degrees)
    rotation = np.array(
        [
            [np.cos(radians), -np.sin(radians)],
            [np.sin(radians), np.cos(radians)],
        ],
        dtype=np.float32,
    )
    rotated = points @ rotation.T
    rotated[:, 0] += center[0]
    rotated[:, 1] += center[1]
    return np.round(rotated).astype(np.int32)


def _paint_arrow(image: np.ndarray, center: tuple[int, int], angle_degrees: float) -> None:
    cv2.fillPoly(image, [_arrow_polygon(center, angle_degrees)], (0, 210, 255))


def test_heading_candidate_keeps_compatible_fields():
    heading = HeadingCandidate(angle_degrees=90.0, bucket=18, confidence=0.8)
    assert heading.angle_degrees == 90.0
    assert heading.bucket == 18


def test_detect_heading_returns_continuous_geometry_angle():
    image = np.zeros((260, 260, 3), dtype=np.uint8)
    _paint_arrow(image, (130, 130), 128.5)
    minimap_mask = np.full((260, 260), 255, dtype=np.uint8)

    result = detect_heading(image, minimap_mask)

    assert result is not None
    assert abs(result.angle_degrees - 128.5) <= 3.0
    assert result.angle_degrees % 5.0 != 0.0


def test_detect_heading_accepts_arrow_near_search_radius_edge():
    image = np.zeros((260, 260, 3), dtype=np.uint8)
    _paint_arrow(image, (225, 130), 258.0)

    geometry, _, reason = detect_heading_geometry(image)

    assert DEFAULT_HEADING_SEARCH_RADIUS_RATIO == 0.45
    assert reason == ""
    assert geometry is not None
    assert abs(geometry.angle_degrees - 258.0) <= 3.0
    assert abs(geometry.centroid_x - 225) <= 8


def test_detect_heading_respects_minimap_mask():
    image = np.zeros((260, 260, 3), dtype=np.uint8)
    _paint_arrow(image, (130, 130), 0.0)
    minimap_mask = np.full((260, 260), 255, dtype=np.uint8)
    cv2.circle(minimap_mask, (130, 130), 40, 0, -1)

    assert detect_heading(image, minimap_mask) is None


def test_heading_module_has_no_template_matching_chain():
    from pathlib import Path

    text = Path("src/minimap_heading.py").read_text(encoding="utf-8")
    assert "matchTemplate" not in text
    assert "arrow_north" not in text
    assert "RotatedHeadingTemplate" not in text
    assert "coordinates_detected" not in text
