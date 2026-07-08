import logging

import numpy as np

from screen_capture import ScreenCapture


class FakeScreenCapture(ScreenCapture):
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.calls = []
        self.screen_size = (320, 240)
        self.window_rect = (100, 200, 300, 400)
        self.screen_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        self.window_frame = np.zeros((200, 200, 3), dtype=np.uint8)

    def get_screen_size(self):
        return self.screen_size

    def _find_window_rect_by_name(self, window_name):
        return self.window_rect if window_name == "game" else None

    def _capture_screen_region(self, x, y, width, height):
        self.calls.append(("screen", x, y, width, height))
        if (x, y, width, height) == (100, 200, 200, 200):
            return self.window_frame.copy()
        if (x, y, width, height) == (0, 0, 320, 240):
            return self.screen_frame.copy()
        return np.zeros((height, width, 3), dtype=np.uint8)

    def _capture_window_region(self, x, y, width, height, window_name):
        self.calls.append(("printwindow_region", x, y, width, height, window_name))
        return np.full((height, width, 3), 55, dtype=np.uint8)

    def _capture_window_frame(self, window_name):
        self.calls.append(("printwindow_frame", window_name))
        return self.window_frame.copy(), self.window_rect


def test_capture_region_with_target_window_captures_whole_window_then_crops():
    capture = FakeScreenCapture()
    capture.window_frame[30:80, 20:60] = 123

    image = capture.capture_region(120, 230, 40, 50, mode="BitBlt", target_window_name="game")

    assert capture.calls == [("screen", 100, 200, 200, 200)]
    assert image.shape == (50, 40, 3)
    assert image.mean() == 123


def test_capture_region_without_target_window_captures_whole_screen_then_crops():
    capture = FakeScreenCapture()
    capture.screen_frame[30:80, 20:60] = 222

    image = capture.capture_region(20, 30, 40, 50, mode="BitBlt", target_window_name="")

    assert capture.calls == [("screen", 0, 0, 320, 240)]
    assert image.shape == (50, 40, 3)
    assert image.mean() == 222


def test_capture_frame_and_region_returns_shared_frame_and_crop():
    capture = FakeScreenCapture()
    capture.window_frame[30:80, 20:60] = 77

    result = capture.capture_frame_and_region(120, 230, 40, 50, mode="BitBlt", target_window_name="game")

    assert capture.calls == [("screen", 100, 200, 200, 200)]
    assert result.origin == (100, 200)
    assert result.source == "window"
    assert result.target_window_name == "game"
    assert result.frame.shape == (200, 200, 3)
    assert result.crop.shape == (50, 40, 3)
    assert result.crop.mean() == 77


def test_capture_frame_and_region_printwindow_returns_whole_window_frame():
    capture = FakeScreenCapture()
    capture.window_frame[30:80, 20:60] = 88

    result = capture.capture_frame_and_region(120, 230, 40, 50, mode="PrintWindow", target_window_name="game")

    assert capture.calls == [("printwindow_frame", "game")]
    assert result.origin == (100, 200)
    assert result.source == "window"
    assert result.target_window_name == "game"
    assert result.frame.shape == (200, 200, 3)
    assert result.crop.shape == (50, 40, 3)
    assert result.crop.mean() == 88


def test_capture_frame_and_region_without_target_marks_fullscreen_source():
    capture = FakeScreenCapture()

    result = capture.capture_frame_and_region(20, 30, 40, 50, mode="BitBlt", target_window_name="")

    assert capture.calls == [("screen", 0, 0, 320, 240)]
    assert result.origin == (0, 0)
    assert result.source == "fullscreen"
    assert result.target_window_name == ""


def test_capture_frame_and_region_missing_target_marks_fallback_region_source():
    capture = FakeScreenCapture()

    result = capture.capture_frame_and_region(20, 30, 40, 50, mode="BitBlt", target_window_name="missing-game")

    assert capture.calls == [("screen", 20, 30, 40, 50)]
    assert result.origin == (20, 30)
    assert result.source == "fallback_region"
    assert result.target_window_name == "missing-game"
