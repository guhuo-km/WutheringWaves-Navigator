import json
import logging
import string
from pathlib import Path

import numpy as np
import pytest

import screen_capture
from screen_capture import ScreenCapture, normalize_capture_mode


@pytest.fixture(autouse=True)
def no_update_wait(monkeypatch):
    monkeypatch.setattr(screen_capture, "PROBE_UPDATE_INTERVAL_SECONDS", 0.0)


RECTS = ((0, 0, 64, 64),)


class FakeBackend:
    """Stands in for a window frame backend; each entry is one whole response."""

    def __init__(self, name, frames=None, available=True):
        self.name = name
        self._frames = list(frames or [None])
        self.available_flag = available
        self.calls = []

    def available(self):
        return self.available_flag

    def capture_regions(self, hwnd, rects):
        self.calls.append(hwnd)
        if len(self._frames) > 1:
            entry = self._frames.pop(0)
        else:
            entry = self._frames[0]
        if entry is None:
            return None
        if isinstance(entry, list):
            return list(entry)
        return [entry for _ in rects]

    def close(self):
        self.calls.append("close")


class SlicingBackend:
    """Window backend that crops the requested client rectangles out of one fixed frame."""

    def __init__(self, name, frame, available=True):
        self.name = name
        self.frame = frame
        self.available_flag = available
        self.calls = []
        self.rect_calls = []

    def available(self):
        return self.available_flag

    def capture_regions(self, hwnd, rects):
        self.calls.append(hwnd)
        self.rect_calls.append([tuple(rect) for rect in rects])
        return [self._crop(rect) for rect in rects]

    def _crop(self, rect):
        x, y, width, height = rect
        return self.frame[y:y + height, x:x + width].copy()

    def close(self):
        self.calls.append("close")


class UpdatingSlicingBackend(SlicingBackend):
    """Slicing backend whose frame changes one pixel per call so the freeze check passes."""

    def __init__(self, name, frame, available=True):
        super().__init__(name, frame, available)
        self._tick = 0

    def _crop(self, rect):
        self._tick += 1
        self.frame[0, 0, 0] = self._tick % 256
        return super()._crop(rect)


def noisy_frame(seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)


def solid_frame(value=7):
    return np.full((64, 64, 3), value, dtype=np.uint8)


def make_capture_with_backends(**backends):
    capture = ScreenCapture()
    capture._backends = dict(backends)
    return capture


def updating_pair(seed=0):
    """Two frames that differ only outside the sampled solid-colour region."""
    return noisy_frame(seed), noisy_frame(seed + 100)


class FakeScreenCapture(ScreenCapture):
    """ScreenCapture whose window lookup, screen size, and frame backends are fakes."""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.calls = []
        self.client_rect = (100, 200, 200, 200)
        self.screen_size = (800, 600)
        self.window_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        self.hwnd = 4242
        self._backends = {
            screen_capture.CAPTURE_MODE_WGC: UpdatingSlicingBackend(
                screen_capture.CAPTURE_MODE_WGC, self.window_frame
            ),
            screen_capture.CAPTURE_MODE_PRINT_WINDOW: FakeBackend(
                screen_capture.CAPTURE_MODE_PRINT_WINDOW, [None]
            ),
            screen_capture.CAPTURE_MODE_WINDOW_BITBLT: FakeBackend(
                screen_capture.CAPTURE_MODE_WINDOW_BITBLT, [None]
            ),
        }

    def _resolve_target_hwnd(self, target_hwnd):
        return int(target_hwnd) if target_hwnd else None

    def get_client_rect(self, hwnd):
        return self.client_rect

    def get_screen_size(self):
        return self.screen_size

    def _capture_screen_region(self, x, y, width, height):
        self.calls.append(("screen", x, y, width, height))
        if (x, y, width, height) == (100, 200, 200, 200):
            return self.window_frame.copy()
        if (x, y, width, height) == (20, 30, 40, 50):
            return np.full((height, width, 3), 44, dtype=np.uint8)
        if (x, y, width, height) == (100, 200, 25, 50):
            return np.full((height, width, 3), 88, dtype=np.uint8)
        if (x, y, width, height) == (0, 0, self.screen_size[0], self.screen_size[1]):
            return np.full((height, width, 3), 66, dtype=np.uint8)
        return None


def _forbid_screen_capture(capture):
    def _boom(*args, **kwargs):
        raise AssertionError("auto mode must not capture the screen")

    capture._capture_from_screen = _boom


def test_auto_capture_derives_ocr_and_minimap_from_the_frame():
    capture, _ = make_window_capture_with_size(200, 200, origin=(100, 200))
    _forbid_screen_capture(capture)

    result = capture.capture_recognition_inputs(
        None,
        None,
        None,
        None,
        mode="printwindow",
        target_window_name="game",
        minimap_search_region=None,
    )

    assert result.source == "window_full"
    assert result.target_window_name == "game"
    assert result.full_frame is None
    assert capture._backends["printwindow"].rect_calls[0] == [
        screen_capture.auto_ocr_region_from_frame_size(200, 200),
        screen_capture.auto_minimap_search_rect(200, 200),
    ]


def test_auto_capture_adds_the_full_frame_only_for_debug_export():
    capture, _ = make_window_capture_with_size(200, 200, origin=(100, 200))
    _forbid_screen_capture(capture)

    result = capture.capture_recognition_inputs(
        None,
        None,
        None,
        None,
        mode="printwindow",
        target_window_name="game",
        minimap_search_region=None,
        include_full_frame=True,
    )

    assert capture._backends["printwindow"].rect_calls[0] == [
        screen_capture.auto_ocr_region_from_frame_size(200, 200),
        screen_capture.auto_minimap_search_rect(200, 200),
        (0, 0, 200, 200),
    ]
    assert result.full_frame.shape == (200, 200, 3)


def test_locked_roi_is_cropped_at_frame_coordinates_despite_client_offset():
    capture, frame = make_window_capture_with_size(800, 600, origin=(30, 40))
    _forbid_screen_capture(capture)
    roi = {"x": 100, "y": 120, "width": 60, "height": 80}
    frame[120:200, 100:160] = 123

    result = capture.capture_recognition_inputs(
        None,
        None,
        None,
        None,
        mode="printwindow",
        target_window_name="game",
        minimap_search_region=roi,
    )

    ocr_rect, minimap_rect = capture._backends["printwindow"].rect_calls[0]
    assert ocr_rect == screen_capture.auto_ocr_region_from_frame_size(800, 600)
    assert minimap_rect == (100, 120, 60, 80)
    patch = result.minimap_patch
    assert (patch.origin_x, patch.origin_y) == (100, 120)
    assert (patch.frame_width, patch.frame_height) == (800, 600)
    assert patch.image.mean() == 123


def test_auto_capture_returns_none_without_a_usable_window_and_never_screens():
    capture = FakeScreenCapture()

    result = capture.capture_recognition_inputs(
        None,
        None,
        None,
        None,
        mode="auto",
        target_window_name="game",
        minimap_search_region=None,
        target_hwnd=0,
    )

    assert result is None
    assert capture.calls == []


def test_manual_capture_blits_screen_regions_by_screen_coordinates():
    capture = FakeScreenCapture()

    result = capture.capture_recognition_inputs(
        20,
        30,
        40,
        50,
        mode="auto",
        target_window_name="game",
        minimap_search_region={"x": 100, "y": 200, "width": 25, "height": 50},
    )

    assert capture.calls == [
        ("screen", 20, 30, 40, 50),
        ("screen", 100, 200, 25, 50),
    ]
    assert result.source == "fullscreen_full"
    assert result.backend == ""
    assert result.ocr_crop.mean() == 44
    patch = result.minimap_patch
    assert patch.image.mean() == 88
    assert (patch.origin_x, patch.origin_y) == (100, 200)
    assert (patch.frame_width, patch.frame_height) == capture.screen_size
    assert np.array_equal(patch.crop(100, 200, 25, 50), patch.image)


def test_manual_capture_never_uses_a_window_backend():
    capture = FakeScreenCapture()

    result = capture.capture_recognition_inputs(
        120,
        230,
        40,
        50,
        mode="printwindow",
        target_window_name="game",
        minimap_search_region={"x": 100, "y": 200, "width": 25, "height": 50},
    )

    assert capture._backends["printwindow"].calls == []
    assert capture._backends["wgc"].calls == []
    assert capture._backends["window_bitblt"].calls == []
    assert result.source == "fullscreen_full"


def make_window_capture_with_size(width: int, height: int, origin=(30, 40)):
    """Window capture whose only available backend yields a client frame of the given size."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    band_width, band_height = screen_capture.auto_ocr_region_size(width, height)
    frame[height - band_height:height, 0:band_width] = 200

    capture = ScreenCapture()
    capture._backends = {
        name: (
            SlicingBackend(name, frame)
            if name == "printwindow"
            else FakeBackend(name, [None])
        )
        for name in screen_capture.CAPTURE_MODE_ORDER
    }
    capture.get_client_rect = lambda hwnd: (origin[0], origin[1], width, height)
    capture._resolve_target_hwnd = lambda target_hwnd=0: 7
    return capture, frame


@pytest.mark.parametrize(
    ("width", "height", "expected_size"),
    [(2560, 1600, (640, 50)), (1920, 1080, (480, 33))],
)
def test_auto_regions_are_derived_from_the_frame_size(width, height, expected_size):
    capture, frame = make_window_capture_with_size(width, height)

    result = capture.capture_recognition_inputs(
        None,
        None,
        None,
        None,
        mode="printwindow",
        target_window_name="game",
        minimap_search_region=None,
    )

    expected_width, expected_height = expected_size
    assert result.source == "window_full"
    assert result.ocr_crop.shape == (expected_height, expected_width, 3)
    assert np.array_equal(
        result.ocr_crop, frame[height - expected_height:height, 0:expected_width]
    )
    assert result.minimap_patch.image.shape == (height // 4, width // 8, 3)
    assert (result.minimap_patch.origin_x, result.minimap_patch.origin_y) == (0, 0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("auto", "auto"),
        ("AUTO", "auto"),
        (" wgc ", "wgc"),
        ("WGC", "wgc"),
        ("PrintWindow", "printwindow"),
        ("printwindow", "printwindow"),
        ("window_bitblt", "window_bitblt"),
        ("Window_BitBlt", "window_bitblt"),
        ("BitBlt", "auto"),
        ("", "auto"),
        (None, "auto"),
        ("nonsense", "auto"),
    ],
)
def test_normalize_capture_mode_mapping(value, expected):
    assert normalize_capture_mode(value) == expected


def test_auto_mode_selects_wgc_when_available():
    first, second = updating_pair(1)
    wgc = FakeBackend("wgc", [first, second])
    printwindow = FakeBackend("printwindow", [noisy_frame(2)])
    bitblt = FakeBackend("window_bitblt", [noisy_frame(3)])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "wgc"
    assert regions[0] is second
    assert capture._active_backend == "wgc"
    assert wgc.calls == [7, 7]
    assert printwindow.calls == []
    assert bitblt.calls == []


def test_backends_receive_every_requested_rectangle():
    wgc = UpdatingSlicingBackend("wgc", noisy_frame(1))
    capture = make_capture_with_backends(wgc=wgc)
    rects = [(0, 0, 64, 64), (0, 0, 32, 32)]

    regions, backend_name = capture._select_and_capture(7, "auto", rects)

    assert backend_name == "wgc"
    assert wgc.rect_calls == [rects, rects]
    assert regions[1].shape == (32, 32, 3)


def test_auto_mode_keeps_a_backend_when_one_region_carries_content():
    first, second = updating_pair(45)
    wgc = FakeBackend("wgc", [solid_frame()])
    printwindow = FakeBackend("printwindow", [[solid_frame(), first], [second, second]])
    bitblt = FakeBackend("window_bitblt", [noisy_frame(46)])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(
        7, "auto", [(0, 0, 64, 64), (0, 0, 64, 64)]
    )

    assert backend_name == "printwindow"
    assert len(regions) == 2
    assert wgc.calls == [7]


def test_auto_mode_skips_unavailable_wgc():
    first, second = updating_pair(2)
    wgc = FakeBackend("wgc", [noisy_frame(1)], available=False)
    printwindow = FakeBackend("printwindow", [first, second])
    bitblt = FakeBackend("window_bitblt", [noisy_frame(3)])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "printwindow"
    assert wgc.calls == []
    assert bitblt.calls == []


def test_auto_mode_skips_backends_returning_only_solid_regions():
    first, second = updating_pair(4)
    wgc = FakeBackend("wgc", [solid_frame()])
    printwindow = FakeBackend("printwindow", [solid_frame()])
    bitblt = FakeBackend("window_bitblt", [first, second])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "window_bitblt"
    assert wgc.calls == [7]
    assert printwindow.calls == [7]
    assert bitblt.calls == [7, 7]


def test_auto_mode_skips_backend_whose_frames_never_change():
    frozen = noisy_frame(11)
    first, second = updating_pair(12)
    wgc = FakeBackend("wgc", [frozen])
    printwindow = FakeBackend("printwindow", [first, second])
    bitblt = FakeBackend("window_bitblt", [noisy_frame(13)])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "printwindow"
    assert wgc.calls == [7, 7]
    assert bitblt.calls == []


def test_auto_mode_picks_first_candidate_when_every_frame_is_frozen(caplog):
    frozen_wgc = noisy_frame(21)
    frozen_printwindow = noisy_frame(23)
    frozen_bitblt = noisy_frame(22)
    wgc = FakeBackend("wgc", [frozen_wgc])
    printwindow = FakeBackend("printwindow", [frozen_printwindow])
    bitblt = FakeBackend("window_bitblt", [frozen_bitblt])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    with caplog.at_level(logging.WARNING):
        regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "wgc"
    assert regions[0] is frozen_wgc
    assert capture._active_backend == "wgc"
    assert any(
        "every backend may be showing a static image" in record.getMessage()
        for record in caplog.records
    )
    assert printwindow.calls == [7, 7]
    assert bitblt.calls == [7, 7]


def test_manual_mode_skips_the_frame_update_check():
    frozen = noisy_frame(31)
    backend = FakeBackend("printwindow", [frozen])
    capture = make_capture_with_backends(printwindow=backend)

    regions, backend_name = capture._select_and_capture(7, "printwindow", RECTS)

    assert backend_name == "printwindow"
    assert regions[0] is frozen
    assert backend.calls == [7]


def test_auto_mode_times_out_a_backend_without_frames(monkeypatch):
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.01)
    first, second = updating_pair(5)
    wgc = FakeBackend("wgc", [None])
    printwindow = FakeBackend("printwindow", [first, second])
    bitblt = FakeBackend("window_bitblt", [None])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "printwindow"
    assert len(wgc.calls) >= 2


def test_auto_mode_selects_window_bitblt_when_earlier_backends_produce_nothing(monkeypatch):
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.005)
    first, second = updating_pair(44)
    wgc = FakeBackend("wgc", [None])
    printwindow = FakeBackend("printwindow", [None])
    bitblt = FakeBackend("window_bitblt", [first, second])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "window_bitblt"
    assert regions[0] is second
    assert capture._active_backend == "window_bitblt"
    assert bitblt.calls == [7, 7]


def test_failed_probe_is_throttled_until_retry_interval(monkeypatch):
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.005)
    capture = make_capture_with_backends(
        **{
            name: FakeBackend(name, [None])
            for name in screen_capture.CAPTURE_MODE_ORDER
        }
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)
    assert regions is None and backend_name == ""
    attempt_count = len(capture._backends["wgc"].calls)

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)
    assert regions is None and backend_name == ""
    assert len(capture._backends["wgc"].calls) == attempt_count


def test_three_consecutive_none_frames_trigger_reprobe(monkeypatch):
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.005)
    wgc_first, wgc_second = updating_pair(6)
    printwindow_first, printwindow_second = updating_pair(7)
    wgc = FakeBackend("wgc", [wgc_first, wgc_second, None])
    printwindow = FakeBackend("printwindow", [printwindow_first, printwindow_second])
    bitblt = FakeBackend("window_bitblt", [None])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    first_regions, backend_name = capture._select_and_capture(7, "auto", RECTS)
    assert backend_name == "wgc"
    assert first_regions[0] is wgc_second
    assert wgc.calls == [7, 7]

    assert capture._select_and_capture(7, "auto", RECTS)[0] is None
    assert capture._select_and_capture(7, "auto", RECTS)[0] is None
    assert capture._active_backend == "wgc"
    assert printwindow.calls == []

    assert capture._select_and_capture(7, "auto", RECTS)[0] is not None
    assert capture._active_backend == "printwindow"


def test_wgc_availability_requires_min_build_and_import(monkeypatch):
    backend = screen_capture._WgcBackend(ScreenCapture())

    monkeypatch.setattr(screen_capture, "_windows_build_number", lambda: 19045)
    assert backend.available() is False

    monkeypatch.setattr(screen_capture, "_windows_build_number", lambda: 20348)

    def boom():
        raise ImportError("no windows_capture")

    monkeypatch.setattr(screen_capture, "_import_windows_capture", boom)
    assert backend.available() is False

    monkeypatch.setattr(screen_capture, "_import_windows_capture", lambda: object())
    assert backend.available() is True


def test_auto_mode_ignores_wgc_below_min_build(monkeypatch):
    monkeypatch.setattr(screen_capture, "_windows_build_number", lambda: 19045)
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.005)

    def fail_capture_regions(hwnd, rects):
        raise AssertionError("WGC must not be used below the minimum Windows build")

    wgc = screen_capture._WgcBackend(ScreenCapture())
    wgc.capture_regions = fail_capture_regions
    first, second = updating_pair(8)
    printwindow = FakeBackend("printwindow", [first, second])
    bitblt = FakeBackend("window_bitblt", [None])
    capture = make_capture_with_backends(
        wgc=wgc, printwindow=printwindow, window_bitblt=bitblt
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "printwindow"
    assert wgc.available() is False


LANGUAGE_ROOT = Path(__file__).resolve().parents[1] / "languages"

CAPTURE_EVENT_KEYS = (
    "capture_backend_selected",
    "capture_backend_reprobe",
    "capture_backend_no_frame",
    "capture_backend_solid_frame",
    "capture_backend_frozen",
    "capture_backend_all_frames_static",
    "capture_backend_probe_failed",
)


def load_language(name: str) -> dict:
    return json.loads((LANGUAGE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def make_event_capture(monkeypatch, **backends):
    """Capture wired to the real zh_CN translations and a text-recording sink."""
    translations = load_language("zh_CN")

    def translate(key, default=None, **kwargs):
        text = translations.get(key, default if default is not None else key)
        return text.format(**kwargs) if kwargs else text

    monkeypatch.setattr(screen_capture, "tr", translate)
    events: list[str] = []
    capture = make_capture_with_backends(**backends)
    capture.set_event_sink(events.append)
    return capture, events


def test_frozen_and_static_backend_events_publish_exact_text(monkeypatch):
    frozen = noisy_frame(41)
    capture, events = make_event_capture(
        monkeypatch,
        wgc=FakeBackend("wgc", [frozen]),
        printwindow=FakeBackend("printwindow", [frozen]),
        window_bitblt=FakeBackend("window_bitblt", [frozen]),
    )

    capture._select_and_capture(7, "auto", RECTS)

    assert events == [
        "截图后端 wgc 连续两帧完全相同，画面疑似冻结，改用下一个后端",
        "截图后端 printwindow 连续两帧完全相同，画面疑似冻结，改用下一个后端",
        "截图后端 window_bitblt 连续两帧完全相同，画面疑似冻结，改用下一个后端",
        "自动截图后端选定: wgc，但所有后端画面可能静止（连续两帧相同）",
    ]


def test_solid_and_selected_backend_events_publish_exact_text(monkeypatch):
    first, second = updating_pair(9)
    capture, events = make_event_capture(
        monkeypatch,
        wgc=FakeBackend("wgc", [solid_frame()]),
        printwindow=FakeBackend("printwindow", [first, second]),
        window_bitblt=FakeBackend("window_bitblt", [None]),
    )

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "printwindow"
    assert events == [
        "截图后端 wgc 返回纯色帧，跳过",
        "自动截图后端选定: printwindow",
    ]


def test_no_frame_and_probe_failed_events_publish_exact_text(monkeypatch):
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.005)
    capture, events = make_event_capture(
        monkeypatch,
        **{name: FakeBackend(name, [None]) for name in screen_capture.CAPTURE_MODE_ORDER},
    )

    capture._select_and_capture(7, "auto", RECTS)

    assert events == [
        "截图后端 wgc 在 0.01s 内未取到帧",
        "截图后端 printwindow 在 0.01s 内未取到帧",
        "截图后端 window_bitblt 在 0.01s 内未取到帧",
        "自动截图后端探测失败，本轮跳过识别",
    ]


def test_reprobe_event_publishes_exact_text(monkeypatch):
    capture, events = make_event_capture(monkeypatch)
    capture._active_backend = "wgc"
    capture._backend_fail_count = screen_capture.BACKEND_FAILURE_REPROBE_COUNT - 1
    capture._backends = {"wgc": FakeBackend("wgc", [None])}
    capture._next_probe_at = float("inf")

    regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert regions is None
    assert backend_name == ""
    assert events == ["截图后端 wgc 连续 3 次失败，重新探测其他后端"]


def test_capture_event_keys_and_placeholders_match_across_language_files():
    zh = load_language("zh_CN")
    en = load_language("en_US")
    formatter = string.Formatter()

    for key in CAPTURE_EVENT_KEYS:
        assert key in zh, key
        assert key in en, key
        zh_fields = {field for _, field, _, _ in formatter.parse(zh[key]) if field}
        en_fields = {field for _, field, _, _ in formatter.parse(en[key]) if field}
        assert zh_fields == en_fields, key


def test_backend_events_without_a_sink_only_write_ascii_file_log(monkeypatch, caplog):
    monkeypatch.setattr(screen_capture, "PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(screen_capture, "PROBE_ATTEMPT_INTERVAL_SECONDS", 0.005)

    def fail_tr(*args, **kwargs):
        raise AssertionError("tr must not be called without an event sink")

    monkeypatch.setattr(screen_capture, "tr", fail_tr)
    frozen = noisy_frame(43)
    capture = make_capture_with_backends(
        wgc=FakeBackend("wgc", [frozen]),
        printwindow=FakeBackend("printwindow", [None]),
        window_bitblt=FakeBackend("window_bitblt", [None]),
    )

    with caplog.at_level(logging.DEBUG, logger="screen_capture"):
        capture._select_and_capture(7, "auto", RECTS)

    messages = [record.getMessage() for record in caplog.records]
    assert "capture backend wgc returned two identical frames, the image appears frozen, trying the next backend" in messages
    assert "auto capture backend selected: wgc, but every backend may be showing a static image (two identical frames)" in messages
    assert all(record.getMessage().isascii() for record in caplog.records)


def test_failing_event_sink_is_logged_and_does_not_break_capture(monkeypatch, caplog):
    def broken_sink(text):
        raise RuntimeError("sink down")

    first, second = updating_pair(47)
    capture = make_capture_with_backends(wgc=FakeBackend("wgc", [first, second]))
    capture.set_event_sink(broken_sink)

    with caplog.at_level(logging.DEBUG, logger="screen_capture"):
        regions, backend_name = capture._select_and_capture(7, "auto", RECTS)

    assert backend_name == "wgc"
    assert regions is not None
    assert any("capture event sink failed for capture_backend_selected" in record.getMessage() for record in caplog.records)


class RecordingDC:
    def __init__(self, log):
        self._log = log

    def GetSafeHdc(self):
        return 555

    def BitBlt(self, dest, size, source_dc, source, raster):
        self._log.append(("BitBlt", dest, size, source_dc, source, raster))


class RecordingBitmap:
    def __init__(self, surface):
        self.surface = surface


class RecordingDib:
    """Stands in for the window-sized DIB so the tests never allocate GDI objects."""

    def __init__(self, surface, label, log):
        self.view = surface
        self.hdc = 555
        self.label = label
        self._log = log

    def release(self):
        self._log.append(("release", self.label))


def make_gdi_owner():
    owner = ScreenCapture()
    owner.get_client_rect = lambda hwnd: (14, 26, 40, 30)
    owner.get_client_offset_in_window = lambda hwnd: (4, 6)
    return owner


def install_dib_double(monkeypatch, log, surface, window_state):
    state = {"count": 0}

    def factory(hwnd, width, height):
        state["count"] += 1
        label = f"dib{state['count']}"
        log.append(("create_dib", int(hwnd), int(width), int(height), label))
        return RecordingDib(surface, label, log)

    monkeypatch.setattr(screen_capture, "_DibSurface", factory)
    monkeypatch.setattr(screen_capture.win32gui, "GetWindowRect", lambda hwnd: window_state[0])

    def fake_print_window(hwnd, hdc, flags):
        log.append(("PrintWindow", hwnd.value, hdc.value, flags.value))
        return window_state[1]

    monkeypatch.setattr(screen_capture, "_print_window_func", fake_print_window)


def test_printwindow_backend_crops_each_requested_rect_from_the_dib(monkeypatch):
    owner = make_gdi_owner()
    backend = screen_capture._PrintWindowBackend(owner)
    log = []
    window_surface = np.zeros((44, 64, 4), dtype=np.uint8)
    window_surface[6:36, 4:44, :3] = 200
    install_dib_double(monkeypatch, log, window_surface, [(10, 20, 74, 64), 1])

    regions = backend.capture_regions(999, [(0, 0, 40, 30), (2, 2, 6, 6)])

    assert ("create_dib", 999, 64, 44, "dib1") in log
    assert ("PrintWindow", 999, 555, screen_capture.PW_RENDERFULLCONTENT) in log
    assert [entry for entry in log if entry[0] == "BitBlt"] == []
    assert regions[0].shape == (30, 40, 3)
    assert np.all(regions[0] == 200)
    assert regions[1].shape == (6, 6, 3)
    assert np.all(regions[1] == 200)


def test_printwindow_backend_returns_none_when_printwindow_fails(monkeypatch):
    owner = make_gdi_owner()
    backend = screen_capture._PrintWindowBackend(owner)
    log = []
    window_surface = np.zeros((44, 64, 4), dtype=np.uint8)
    install_dib_double(monkeypatch, log, window_surface, [(10, 20, 74, 64), 0])

    assert backend.capture_regions(999, [(0, 0, 40, 30)]) is None
    assert [entry for entry in log if entry[0] == "BitBlt"] == []


def test_printwindow_backend_reuses_the_dib_until_the_window_resizes(monkeypatch):
    owner = make_gdi_owner()
    backend = screen_capture._PrintWindowBackend(owner)
    log = []
    window_surface = np.zeros((84, 96, 4), dtype=np.uint8)
    window_surface[6:36, 4:44, :3] = 200
    window_state = [(10, 20, 74, 64), 1]
    install_dib_double(monkeypatch, log, window_surface, window_state)

    assert backend.capture_regions(999, [(0, 0, 40, 30)])[0].mean() == 200
    backend.capture_regions(999, [(0, 0, 40, 30)])
    assert [entry for entry in log if entry[0] == "create_dib"] == [
        ("create_dib", 999, 64, 44, "dib1")
    ]

    window_state[0] = (10, 20, 106, 104)
    assert backend.capture_regions(999, [(0, 0, 40, 30)])[0].mean() == 200
    assert ("create_dib", 999, 96, 84, "dib2") in log
    assert ("release", "dib1") in log


def test_printwindow_backend_yields_empty_region_for_a_rect_outside_the_client(monkeypatch):
    owner = make_gdi_owner()
    backend = screen_capture._PrintWindowBackend(owner)
    log = []
    window_surface = np.zeros((44, 64, 4), dtype=np.uint8)
    window_surface[6:36, 4:44, :3] = 200
    install_dib_double(monkeypatch, log, window_surface, [(10, 20, 74, 64), 1])

    regions = backend.capture_regions(999, [(50, 50, 10, 10), (0, 0, 40, 30)])

    assert regions[0].shape == (0, 0, 3)
    assert regions[1].shape == (30, 40, 3)


def install_screen_bitblt(monkeypatch, backend, log, surface):
    """Fake the screen-DC BitBlt path."""
    dc = RecordingDC(log)
    bitmap = RecordingBitmap(surface)

    def fake_ensure_dc(width, height):
        log.append(("ensure_dc", width, height))
        backend._bitmap = bitmap
        backend._mem_dc = "screen-dc"
        return dc

    monkeypatch.setattr(screen_capture, "_bitmap_to_bgra", lambda bmp: bmp.surface)
    backend._ensure_dc = fake_ensure_dc
    return dc


def test_window_bitblt_backend_blits_the_union_of_the_requested_rects(monkeypatch):
    owner = make_gdi_owner()
    backend = screen_capture._WindowBitBltBackend(owner)
    log = []
    union_surface = np.full((30, 40, 4), 77, dtype=np.uint8)
    union_surface[20:30, 30:40, :3] = 111
    install_screen_bitblt(monkeypatch, backend, log, union_surface)

    regions = backend.capture_regions(999, [(0, 0, 10, 10), (30, 20, 10, 10)])

    assert regions[0].shape == (10, 10, 3)
    assert np.all(regions[0] == 77)
    assert regions[1].shape == (10, 10, 3)
    assert np.all(regions[1] == 111)
    assert ("ensure_dc", 40, 30) in log
    assert [entry for entry in log if entry[0] == "PrintWindow"] == []
    assert (
        "BitBlt",
        (0, 0),
        (40, 30),
        "screen-dc",
        (14, 26),
        screen_capture.win32con.SRCCOPY,
    ) in log
