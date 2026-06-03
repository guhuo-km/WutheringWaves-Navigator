import pytest
import numpy as np
from conftest import build_ocr_string_detections, build_yolo_detection

def build_coordinate_cluster(x, y, z, missing_chars=None, class_map=None):
    """
    Builds a cluster of detections representing coordinates (x, y, z).
    
    Args:
        x, y, z (int/str): Coordinates
        missing_chars (list): List of indices or characters to omit
        class_map (dict): Character mapping
        
    Returns:
        list[dict]: List of detections
    """
    text = f"{x},{y},{z}"
    if missing_chars:
        # If missing_chars contains actual characters to drop (like ',' or '-')
        for char in missing_chars:
            if isinstance(char, str):
                text = text.replace(char, "", 1)
    
    return build_ocr_string_detections(text, class_map=class_map)

def build_trajectory_sequence(coords_list, jump_at=None, jump_offset=2000):
    """
    Builds a sequence of coordinate clusters.
    
    Args:
        coords_list (list[tuple]): List of (x, y, z)
        jump_at (int): Index where a sudden jump occurs
        jump_offset (int): Amount to jump by
        
    Returns:
        list[list[dict]]: List of detection clusters
    """
    sequence = []
    for i, (x, y, z) in enumerate(coords_list):
        if jump_at is not None and i == jump_at:
            x += jump_offset
        sequence.append(build_coordinate_cluster(x, y, z))
    return sequence

def build_timestamp_contaminated(x, y, z):
    """
    Builds coordinates with a leading timestamp-like string "202x-".
    """
    text = f"2024-{x},{y},{z}"
    return build_ocr_string_detections(text)

def test_yolo_detection_format():
    """Verify build_yolo_detection returns correct structure"""
    det = build_yolo_detection(1, [10, 20, 30, 40], 0.8)
    assert det['class'] == 1
    assert isinstance(det['bbox'], np.ndarray)
    assert det['bbox'].shape == (4,)
    assert det['confidence'] == 0.8

def test_missing_comma_fixture():
    """Verify fixture for missing comma: '-500 100 50'"""
    # Simulate missing commas but with spaces or nothing
    text = "-500 100 50"
    detections = build_ocr_string_detections(text)
    
    # Check that we have digits and minus, but no commas
    chars = [d['class'] for d in detections]
    assert 10 not in chars # 10 is comma class
    assert 12 in chars     # 12 is minus class
    # -500 100 50 -> '-', '5', '0', '0', ' ', '1', '0', '0', ' ', '5', '0'
    # Spaces are skipped in build_ocr_string_detections
    # Chars: '-', '5', '0', '0', '1', '0', '0', '5', '0' -> total 9
    assert len(detections) == 9 

def test_missing_minus_fixture():
    """Verify fixture for missing minus: '500,100,50' when it should be '-500...'"""
    # In this case the builder just produces what we tell it
    detections = build_coordinate_cluster(500, 100, 50)
    chars = [d['class'] for d in detections]
    assert 12 not in chars # No minus

def test_timestamp_contamination_fixture():
    """Verify fixture with timestamp prefix: '2024--500,100,50'"""
    detections = build_timestamp_contaminated(-500, 100, 50)
    # 2024- (5 chars) + -500,100,50 (11 chars) = 16 chars
    assert len(detections) == 16
    
    # Check for the double minus or timestamp pattern
    chars = [d['class'] for d in detections]
    # First 4 are 2, 0, 2, 4 (classes 2, 0, 2, 4)
    assert chars[0:4] == [2, 0, 2, 4]
    # 5th is minus (class 12)
    assert chars[4] == 12

def test_trajectory_jump_fixture():
    """Verify sequence with a jump"""
    coords = [(100, 100, 10), (105, 102, 10), (110, 104, 10)]
    sequence = build_trajectory_sequence(coords, jump_at=2, jump_offset=2000)
    
    assert len(sequence) == 3
    # Check that third element has a large X
    # Note: We'd need a parser to verify the value, but we can check detection count
    assert len(sequence[2]) > 0
