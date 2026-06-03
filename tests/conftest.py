import pytest
import numpy as np
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.modules.pop('src', None)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENDORED_FLUENT = os.path.join(PROJECT_ROOT, 'PyQt-Fluent-Widgets-PySide6')
if VENDORED_FLUENT not in sys.path:
    sys.path.insert(0, VENDORED_FLUENT)

# Add src to path to allow importing from ocr_engine
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

@pytest.fixture
def class_map():
    """Returns mapping from character to class ID based on models/class_names.txt"""
    return {
        '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
        '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
        ',': 10, ':': 11, '-': 12
    }

@pytest.fixture
def char_map(class_map):
    """Returns mapping from class ID to character"""
    return {v: k for k, v in class_map.items()}

def build_yolo_detection(class_id, bbox, confidence=0.95):
    """
    Builds a single YOLO-like detection dictionary.
    
    Args:
        class_id (int): Character class ID
        bbox (list or np.ndarray): [x1, y1, x2, y2]
        confidence (float): Detection confidence
        
    Returns:
        dict: YOLO detection format
    """
    return {
        'class': int(class_id),
        'bbox': np.array(bbox, dtype=np.float32),
        'confidence': float(confidence)
    }

def build_ocr_string_detections(text, start_x=10, start_y=10, char_width=10, char_height=20, gap=2, class_map=None):
    """
    Converts a string of characters into a list of YOLO detection dicts.
    
    Args:
        text (str): String to convert (e.g., "-500,100,50")
        start_x (int): Starting x coordinate
        start_y (int): Starting y coordinate
        char_width (int): Width of each character bbox
        char_height (int): Height of each character bbox
        gap (int): Horizontal gap between characters
        class_map (dict): Character to class ID mapping
        
    Returns:
        list[dict]: List of detection dictionaries
    """
    if class_map is None:
        class_map = {
            '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
            '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
            ',': 10, ':': 11, '-': 12
        }
        
    detections = []
    current_x = start_x
    
    for char in text:
        if char == ' ':
            current_x += char_width + gap
            continue
            
        if char not in class_map:
            continue
            
        class_id = class_map[char]
        bbox = [current_x, start_y, current_x + char_width, start_y + char_height]
        detections.append(build_yolo_detection(class_id, bbox))
        current_x += char_width + gap
        
    return detections
