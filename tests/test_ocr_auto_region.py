import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ocr_manager import OCRManager


def test_auto_window_default_region_uses_one_thirty_second_height():
    manager = OCRManager()

    region = manager._calculate_default_region((100, 200, 1700, 1100))

    assert region == {
        "x": 100,
        "y": 1072,
        "width": 400,
        "height": 28,
    }
