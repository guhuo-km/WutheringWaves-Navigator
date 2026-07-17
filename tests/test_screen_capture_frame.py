import logging

import numpy as np

from screen_capture import ScreenCapture


class FakeScreenCapture(ScreenCapture):
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.calls = []
        self.window_rect = (100, 200, 300, 400)
        self.window_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        self.print_window_succeeds = True

    def _find_window_rect_by_name(self, window_name):
        return self.window_rect if window_name == "game" else None

    def _capture_screen_region(self, x, y, width, height):
        self.calls.append(("screen", x, y, width, height))
        if (x, y, width, height) == (100, 200, 200, 200):
            return self.window_frame.copy()
        if (x, y, width, height) == (20, 30, 40, 50):
            return np.full((height, width, 3), 44, dtype=np.uint8)
        if (x, y, width, height) == (100, 200, 25, 50):
            return np.full((height, width, 3), 88, dtype=np.uint8)
        return None

    def _capture_window_frame(self, window_name):
        self.calls.append(("printwindow_frame", window_name))
        if not self.print_window_succeeds:
            return None
        return self.window_frame.copy(), self.window_rect


def test_recognition_capture_uses_one_full_window_for_ocr_and_minimap():
    capture = FakeScreenCapture()
    capture.window_frame[30:80, 20:60] = 123

    result = capture.capture_recognition_inputs(
        120,
        230,
        40,
        50,
        mode="BitBlt",
        target_window_name="game",
        minimap_search_region={"x": 100, "y": 200, "width": 25, "height": 50},
    )

    assert capture.calls == [("screen", 100, 200, 200, 200)]
    assert result.source == "window_full"
    assert result.target_window_name == "game"
    assert result.ocr_crop.shape == (50, 40, 3)
    assert result.ocr_crop.mean() == 123
    assert result.minimap_frame.shape == (200, 200, 3)
    assert result.minimap_search_rect == (0, 0, 25, 50)


def test_recognition_capture_returns_independent_regions_when_full_window_fails():
    capture = FakeScreenCapture()

    result = capture.capture_recognition_inputs(
        20,
        30,
        40,
        50,
        mode="BitBlt",
        target_window_name="missing-game",
        minimap_search_region={"x": 100, "y": 200, "width": 25, "height": 50},
    )

    assert capture.calls == [
        ("screen", 20, 30, 40, 50),
        ("screen", 100, 200, 25, 50),
    ]
    assert result.source == "split_region_fallback"
    assert result.ocr_crop.mean() == 44
    assert result.minimap_frame.mean() == 88
    assert result.minimap_search_rect == (0, 0, 25, 50)


def test_printwindow_failure_retries_full_target_with_bitblt():
    capture = FakeScreenCapture()
    capture.print_window_succeeds = False

    result = capture.capture_recognition_inputs(
        120,
        230,
        40,
        50,
        mode="PrintWindow",
        target_window_name="game",
        minimap_search_region={"x": 100, "y": 200, "width": 25, "height": 50},
    )

    assert capture.calls == [
        ("printwindow_frame", "game"),
        ("screen", 100, 200, 200, 200),
    ]
    assert result.source == "window_full"
    assert result.minimap_frame.shape == (200, 200, 3)
