"""Auto capture region tracking against the game window client area.

These tests use a fake ScreenCapture so no real window or capture backend is needed.
"""

import json
import re

import pytest

from ocr_manager import OCRManager
from screen_capture import normalize_capture_mode


class FakeSettings:
    def __init__(self):
        self.values = {
            "minimap_roi.auto_calibration_enabled": False,
            "minimap_roi.status": "",
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, save=True):
        self.values[key] = value
        return True

    def save(self):
        return True


class FakeWorker:
    def __init__(self):
        self.is_running = True
        self.capture_settings = []

    def update_capture_settings(self, *args):
        self.capture_settings.append(args)

    def stop_recognition(self) -> bool:
        self.is_running = False
        return True

    def isRunning(self) -> bool:
        return False

    def deleteLater(self) -> None:
        return None


class FakeScreenCapture:
    def __init__(self):
        self.search_results = []
        self.searches = 0
        self.closed = 0
        self.sink = None
        self.sink_installs = 0

    def find_best_game_window(self, keywords=None):
        self.searches += 1
        if not self.search_results:
            return None
        return dict(self.search_results.pop(0))

    def set_event_sink(self, sink):
        self.sink = sink
        self.sink_installs += 1

    def emit_event(self, text):
        assert self.sink is not None, "OCRManager did not install a capture event sink"
        self.sink(text)

    def close(self) -> None:
        self.closed += 1


class FakeLogManager:
    def __init__(self):
        self.entries = []

    def enqueue(self, log_type, line):
        self.entries.append((log_type, line))


class FakeTimer:
    """Stand-in for QTimer so the tests can observe start/stop without an event loop."""

    def __init__(self):
        self.active = False

    def isActive(self) -> bool:
        return self.active

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


def window_result(hwnd: int, client: tuple[int, int, int, int]) -> dict:
    left, top, width, height = client
    return {
        "title": "鸣潮",
        "hwnd": hwnd,
        "mode": "windowed",
        "rect": (left - 8, top - 31, left + width + 8, top + height + 39),
        "width": width + 16,
        "height": height + 70,
        "client_x": left,
        "client_y": top,
        "client_width": width,
        "client_height": height,
    }


@pytest.fixture
def tracking(monkeypatch):
    capture = FakeScreenCapture()
    monkeypatch.setattr("screen_capture.get_screen_capture", lambda: capture)

    manager = OCRManager()
    manager._settings = FakeSettings()
    manager._auto_window_timer = FakeTimer()
    manager.ocr_config["ocr_interval"] = 1000
    worker = FakeWorker()
    manager.ocr_worker = worker

    saves: list[int] = []
    monkeypatch.setattr(manager, "save_config", lambda: saves.append(1))

    return manager, capture, worker, saves


def test_detection_stores_display_region_and_pushes_auto_regions(tracking):
    manager, capture, worker, saves = tracking
    capture.search_results.append(window_result(11, (100, 50, 800, 600)))

    assert manager._poll_auto_window() is True
    assert manager._current_game_hwnd == 11
    assert manager._current_game_window_rect == (100, 50, 900, 650)
    assert manager.ocr_config["ocr_capture_area"] == {
        "x": 100,
        "y": 632,
        "width": 200,
        "height": 18,
    }
    assert manager.ocr_config["ocr_capture_area_source"] == "auto"
    assert worker.capture_settings == [(None, 1000, "鸣潮", 11)]
    assert len(saves) == 1


def test_timer_stops_after_the_window_is_found(tracking):
    manager, capture, worker, saves = tracking
    capture.search_results.append(window_result(11, (100, 50, 800, 600)))

    manager.start_auto_window_detect()

    assert manager._current_game_hwnd == 11
    assert capture.searches == 1
    assert manager._auto_window_timer.isActive() is False


def test_timer_keeps_polling_while_no_window_is_found(tracking):
    manager, capture, worker, saves = tracking

    manager.start_auto_window_detect()

    assert capture.searches == 1
    assert manager._auto_window_remaining == 5
    assert manager._auto_window_timer.isActive() is True

    capture.search_results.append(window_result(12, (0, 0, 1024, 768)))
    for _ in range(5):
        manager._on_auto_window_tick()
    manager._on_auto_window_tick()

    assert manager._current_game_hwnd == 12
    assert manager._auto_window_timer.isActive() is False


def test_manual_region_is_pushed_as_screen_coordinates(tracking):
    manager, capture, worker, saves = tracking
    manual_region = {"x": 7, "y": 9, "width": 320, "height": 40}
    manager.ocr_config["ocr_capture_area"] = manual_region
    manager.ocr_config["manual_ocr_capture_area"] = dict(manual_region)
    manager.ocr_config["ocr_capture_area_source"] = "manual"
    worker.capture_settings.clear()

    assert manager.restore_manual_region_if_available() is True

    assert manager.ocr_config["ocr_capture_area"] == manual_region
    assert worker.capture_settings == [
        (
            manual_region,
            1000,
            manager.ocr_config.get("target_window_name", ""),
            0,
        )
    ]


@pytest.mark.parametrize(
    ("stored_mode", "expected_mode"),
    [
        ("BitBlt", "auto"),
        ("", "auto"),
        ("PrintWindow", "printwindow"),
        ("wgc", "wgc"),
        ("window_bitblt", "window_bitblt"),
    ],
)
def test_load_config_normalizes_legacy_screenshot_mode(tmp_path, monkeypatch, stored_mode, expected_mode):
    config_file = tmp_path / "ocr_config.json"
    config_file.write_text(json.dumps({"screenshot_mode": stored_mode}), encoding="utf-8")

    manager = OCRManager()
    monkeypatch.setattr(manager, "config_file", config_file)

    assert manager.load_config()["screenshot_mode"] == expected_mode


def test_default_screenshot_mode_is_auto():
    manager = OCRManager()

    assert manager.default_config["screenshot_mode"] == "auto"
    assert normalize_capture_mode("BitBlt") == "auto"


def test_unusable_client_area_is_treated_as_window_not_found(tracking):
    manager, capture, worker, saves = tracking
    region_before = dict(manager.ocr_config["ocr_capture_area"])
    source_before = manager.ocr_config["ocr_capture_area_source"]

    result = window_result(11, (100, 50, 800, 600))
    result.update({"client_x": 0, "client_y": 0, "client_width": 0, "client_height": 0})
    capture.search_results.append(result)

    assert manager._poll_auto_window() is False
    assert manager._current_game_hwnd == 0
    assert manager._current_game_window_rect is None
    assert manager.ocr_config["ocr_capture_area"] == region_before
    assert manager.ocr_config["ocr_capture_area_source"] == source_before
    assert saves == []
    assert worker.capture_settings == []


def test_stop_ocr_closes_capture_backends_once(tracking):
    manager, capture, worker, saves = tracking

    assert manager.stop_ocr() is True
    assert manager.ocr_worker is None
    assert capture.closed == 1


def test_capture_event_reaches_system_log_through_injected_sink(tracking):
    manager, capture, worker, saves = tracking
    assert capture.sink_installs == 1

    log_manager = FakeLogManager()
    manager.set_log_manager(log_manager)

    capture.emit_event("自动截图后端选定: printwindow")

    assert len(log_manager.entries) == 1
    log_type, line = log_manager.entries[0]
    assert log_type == "system"
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}\] \[INFO\] 自动截图后端选定: printwindow", line
    )
