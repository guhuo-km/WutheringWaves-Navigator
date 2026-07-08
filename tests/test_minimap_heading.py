import numpy as np
import cv2
import shutil

from core import paths
from minimap_heading import (
    HeadingCandidate,
    DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO,
    detect_heading,
    generate_rotated_templates,
    load_heading_template,
)


def test_heading_candidate_can_represent_discrete_arrow_angle():
    heading = HeadingCandidate(angle_degrees=90.0, bucket=6, confidence=None)
    assert heading.angle_degrees == 90.0
    assert heading.bucket == 6


def test_detect_heading_returns_none_without_base_template():
    image = np.zeros((260, 260, 3), dtype=np.uint8)
    mask = np.zeros((260, 260), dtype=np.uint8)

    assert detect_heading(image, mask, template_path="missing-template.png") is None


def test_default_heading_template_asset_exists():
    assert paths.asset_file("minimap_heading", "arrow_north.png").exists()


def test_load_heading_template_reads_non_ascii_path(tmp_path):
    template_dir = tmp_path / "中文路径"
    template_dir.mkdir()
    template_path = template_dir / "箭头.png"
    shutil.copy2(paths.asset_file("minimap_heading", "arrow_north.png"), template_path)

    template = load_heading_template(template_path)

    assert template.bgr.size > 0
    assert template.mask.size > 0


def test_generate_rotated_templates_uses_base_template_as_bucket_zero():
    template = load_heading_template()
    candidates = generate_rotated_templates(template)

    assert len(candidates) == 72
    assert candidates[0].bucket == 0
    assert candidates[0].angle_degrees == 0.0
    assert candidates[1].bucket == 1
    assert candidates[1].angle_degrees == 5.0


def test_generate_rotated_templates_scales_template_width_from_minimap_diameter():
    template = load_heading_template()

    candidates = generate_rotated_templates(template, minimap_diameter_px=252)

    assert DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO == 0.18
    expected_width = round(252 * DEFAULT_HEADING_TEMPLATE_WIDTH_RATIO)
    assert abs(candidates[0].bgr.shape[1] - expected_width) <= 1


def test_detect_heading_matches_centered_default_template_as_bucket_zero():
    template = load_heading_template()
    template = generate_rotated_templates(template, minimap_diameter_px=260)[0]
    image = np.zeros((260, 260, 3), dtype=np.uint8)
    h, w = template.bgr.shape[:2]
    top = 130 - h // 2
    left = 130 - w // 2
    alpha = (template.mask.astype(np.float32) / 255.0)[:, :, None]
    image[top:top + h, left:left + w] = (
        template.bgr.astype(np.float32) * alpha
        + image[top:top + h, left:left + w].astype(np.float32) * (1.0 - alpha)
    ).astype(np.uint8)
    minimap_mask = np.full((260, 260), 255, dtype=np.uint8)

    result = detect_heading(image, minimap_mask, confidence_threshold=0.9)

    assert result is not None
    assert result.bucket == 0
    assert result.angle_degrees == 0.0


def test_detect_heading_respects_minimap_mask_center_exclusion():
    template = load_heading_template()
    template = generate_rotated_templates(template, minimap_diameter_px=260)[0]
    image = np.zeros((260, 260, 3), dtype=np.uint8)
    h, w = template.bgr.shape[:2]
    top = 130 - h // 2
    left = 130 - w // 2
    alpha = (template.mask.astype(np.float32) / 255.0)[:, :, None]
    image[top:top + h, left:left + w] = (
        template.bgr.astype(np.float32) * alpha
        + image[top:top + h, left:left + w].astype(np.float32) * (1.0 - alpha)
    ).astype(np.uint8)
    minimap_mask = np.full((260, 260), 255, dtype=np.uint8)
    minimap_mask[top:top + h, left:left + w] = 0

    result = detect_heading(image, minimap_mask, confidence_threshold=0.9)

    assert result is None


def test_heading_module_does_not_emit_coordinates():
    import pathlib

    text = pathlib.Path("src/minimap_heading.py").read_text(encoding="utf-8")
    assert "coordinates_detected" not in text
    assert "update_ocr_coordinates" not in text
    assert "CoordinateCandidate" not in text
