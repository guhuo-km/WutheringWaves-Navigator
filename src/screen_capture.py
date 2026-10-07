#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Screen Capture Module for WutheringWaves Navigator
屏幕截图模块
"""

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import win32gui
import win32ui
import win32con
import win32api
import win32process
import cv2

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key


CAPTURE_MODE_AUTO = "auto"
CAPTURE_MODE_WGC = "wgc"
CAPTURE_MODE_PRINT_WINDOW = "printwindow"
CAPTURE_MODE_WINDOW_BITBLT = "window_bitblt"

CAPTURE_MODE_ORDER: Tuple[str, ...] = (
    CAPTURE_MODE_WGC,
    CAPTURE_MODE_PRINT_WINDOW,
    CAPTURE_MODE_WINDOW_BITBLT,
)

WGC_MIN_WINDOWS_BUILD = 20348
PROBE_TIMEOUT_SECONDS = 1.5
PROBE_RETRY_INTERVAL_SECONDS = 2.0
PROBE_ATTEMPT_INTERVAL_SECONDS = 0.05
PROBE_UPDATE_INTERVAL_SECONDS = 0.5
BACKEND_FAILURE_REPROBE_COUNT = 3
SOLID_FRAME_STD_THRESHOLD = 1.0
SOLID_FRAME_SAMPLE_STEP = 8

AUTO_OCR_REGION_WIDTH_DIVISOR = 4
AUTO_OCR_REGION_HEIGHT_DIVISOR = 32
AUTO_MINIMAP_SEARCH_WIDTH_DIVISOR = 8
AUTO_MINIMAP_SEARCH_HEIGHT_DIVISOR = 4

_DWMWA_EXTENDED_FRAME_BOUNDS = 9

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_dwmapi = ctypes.windll.dwmapi
_print_window_func = _user32.PrintWindow
_print_window_func.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_print_window_func.restype = wintypes.BOOL
_dwm_get_window_attribute = _dwmapi.DwmGetWindowAttribute
_dwm_get_window_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
_dwm_get_window_attribute.restype = ctypes.c_long
_user32.GetWindowDC.argtypes = [wintypes.HWND]
_user32.GetWindowDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.DeleteDC.restype = wintypes.BOOL
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = ctypes.c_int
_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP

PW_RENDERFULLCONTENT = 2
DIB_RGB_COLORS = 0
DIB_BYTES_PER_PIXEL = 4

ClientRect = Tuple[int, int, int, int]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


@dataclass(frozen=True)
class FramePatch:
    """One captured rectangle of a frame, addressable in whole-frame client coordinates."""

    image: np.ndarray
    origin_x: int
    origin_y: int
    frame_width: int
    frame_height: int

    @classmethod
    def whole(cls, frame: np.ndarray) -> "FramePatch":
        """Wrap a complete frame so whole-frame cropping is the only coordinate path."""
        return cls(
            image=frame,
            origin_x=0,
            origin_y=0,
            frame_width=int(frame.shape[1]),
            frame_height=int(frame.shape[0]),
        )

    def _clipped(self, x: int, y: int, width: int, height: int) -> ClientRect:
        left = max(int(x), self.origin_x)
        top = max(int(y), self.origin_y)
        right = max(left, min(int(x) + int(width), self.origin_x + self.image.shape[1]))
        bottom = max(top, min(int(y) + int(height), self.origin_y + self.image.shape[0]))
        return (left, top, right - left, bottom - top)

    def sub_rect(self, x: int, y: int, width: int, height: int) -> "FramePatch":
        """Return the patch of a whole-frame rectangle, still addressed in whole-frame coordinates."""
        left, top, clipped_width, clipped_height = self._clipped(x, y, width, height)
        return FramePatch(
            image=self.image[
                top - self.origin_y:top - self.origin_y + clipped_height,
                left - self.origin_x:left - self.origin_x + clipped_width,
            ],
            origin_x=left,
            origin_y=top,
            frame_width=self.frame_width,
            frame_height=self.frame_height,
        )

    def crop(self, x: int, y: int, width: int, height: int) -> np.ndarray:
        """Return a copy of the whole-frame rectangle, clipped to this patch."""
        left, top, clipped_width, clipped_height = self._clipped(x, y, width, height)
        return self.image[
            top - self.origin_y:top - self.origin_y + clipped_height,
            left - self.origin_x:left - self.origin_x + clipped_width,
        ].copy()


@dataclass(frozen=True)
class RecognitionCapture:
    ocr_crop: Optional[np.ndarray]
    minimap_patch: Optional[FramePatch]
    source: str
    target_window_name: str = ""
    backend: str = ""
    full_frame: Optional[np.ndarray] = None


def normalize_capture_mode(value: object) -> str:
    """Map configured capture mode strings to the current internal mode names."""
    name = str(value or "").strip().lower()
    if name in (
        CAPTURE_MODE_AUTO,
        CAPTURE_MODE_WGC,
        CAPTURE_MODE_PRINT_WINDOW,
        CAPTURE_MODE_WINDOW_BITBLT,
    ):
        return name
    return CAPTURE_MODE_AUTO


def auto_ocr_region_size(width: int, height: int) -> Tuple[int, int]:
    """Bottom-left OCR band size for a frame of the given size."""
    return (
        max(1, int(width) // AUTO_OCR_REGION_WIDTH_DIVISOR),
        max(1, int(height) // AUTO_OCR_REGION_HEIGHT_DIVISOR),
    )


def auto_minimap_search_size(width: int, height: int) -> Tuple[int, int]:
    """Top-left minimap search size for a frame of the given size."""
    return (
        max(1, int(width) // AUTO_MINIMAP_SEARCH_WIDTH_DIVISOR),
        max(1, int(height) // AUTO_MINIMAP_SEARCH_HEIGHT_DIVISOR),
    )


def auto_ocr_region_from_frame_size(width: int, height: int) -> ClientRect:
    """Frame-relative (x, y, width, height) of the auto OCR region."""
    region_width, region_height = auto_ocr_region_size(width, height)
    return (0, max(0, int(height) - region_height), region_width, region_height)


def auto_minimap_search_rect(width: int, height: int) -> ClientRect:
    """Frame-relative (x, y, width, height) of the auto minimap search region."""
    search_width, search_height = auto_minimap_search_size(width, height)
    return (0, 0, search_width, search_height)


def _shift_rect(rect: Sequence[int], offset_x: int, offset_y: int) -> ClientRect:
    return (
        int(rect[0]) - int(offset_x),
        int(rect[1]) - int(offset_y),
        int(rect[2]),
        int(rect[3]),
    )


def _region_to_rect(region: Optional[Dict[str, int]]) -> Optional[ClientRect]:
    if region is None:
        return None
    return (
        int(region.get("x", 0) or 0),
        int(region.get("y", 0) or 0),
        int(region.get("width", 0) or 0),
        int(region.get("height", 0) or 0),
    )


def _union_rect(rects: Sequence[ClientRect]) -> Optional[ClientRect]:
    left = min(int(rect[0]) for rect in rects)
    top = min(int(rect[1]) for rect in rects)
    right = max(int(rect[0]) + int(rect[2]) for rect in rects)
    bottom = max(int(rect[1]) + int(rect[3]) for rect in rects)
    if right <= left or bottom <= top:
        return None
    return (left, top, right - left, bottom - top)


def _crop_bgra_to_bgr(surface: np.ndarray, rect: ClientRect) -> np.ndarray:
    """Clip the rectangle to the surface and convert it into an independent BGR copy."""
    x, y, width, height = rect
    left = max(0, min(int(x), surface.shape[1]))
    top = max(0, min(int(y), surface.shape[0]))
    right = max(left, min(int(x) + int(width), surface.shape[1]))
    bottom = max(top, min(int(y) + int(height), surface.shape[0]))
    if right <= left or bottom <= top:
        # A pushed rectangle can sit outside the client area when the window moved.
        return np.zeros((0, 0, 3), dtype=np.uint8)
    return cv2.cvtColor(surface[top:bottom, left:right], cv2.COLOR_BGRA2BGR)


def _regions_are_identical(first: Sequence[np.ndarray], second: Sequence[np.ndarray]) -> bool:
    if len(first) != len(second):
        return False
    return all(bool(np.array_equal(one, two)) for one, two in zip(first, second))


def _all_regions_solid(regions: Sequence[np.ndarray]) -> bool:
    """The capture is unusable when every requested region is a near-constant colour."""
    return all(_is_solid_frame(region) for region in regions)


def _windows_build_number() -> int:
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def _import_windows_capture():
    import windows_capture

    return windows_capture


def _is_solid_frame(frame: Optional[np.ndarray]) -> bool:
    """Sample the frame and treat near-constant pixels as an unusable capture."""
    if frame is None or frame.size == 0:
        return True
    step = max(1, int(SOLID_FRAME_SAMPLE_STEP))
    sample = frame[::step, ::step]
    if sample.size == 0:
        return True
    return float(np.std(sample.astype(np.float32))) < SOLID_FRAME_STD_THRESHOLD


def _get_extended_frame_bounds(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    rect = wintypes.RECT()
    try:
        result = _dwm_get_window_attribute(
            wintypes.HWND(int(hwnd)),
            wintypes.DWORD(_DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            wintypes.DWORD(ctypes.sizeof(rect)),
        )
    except Exception:
        return None
    if int(result) != 0:
        return None
    left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    if right - left <= 0 or bottom - top <= 0:
        return None
    return (left, top, right - left, bottom - top)


def _bitmap_to_bgra(bitmap) -> np.ndarray:
    bmp_info = bitmap.GetInfo()
    bmp_str = bitmap.GetBitmapBits(True)
    image = np.frombuffer(bmp_str, dtype=np.uint8)
    return image.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))


class _DibSurface:
    """Window-sized 32-bit top-down DIB selected into a memory DC."""

    def __init__(self, hwnd: int, width: int, height: int):
        self._hwnd = int(hwnd)
        self._window_dc: Optional[int] = None
        self.hdc: Optional[int] = None
        self._bitmap: Optional[int] = None
        self._old_bitmap: Optional[int] = None
        self._buffer = None
        self.view: Optional[np.ndarray] = None
        try:
            self._window_dc = _user32.GetWindowDC(self._hwnd)
            if not self._window_dc:
                raise OSError("GetWindowDC failed")
            self.hdc = _gdi32.CreateCompatibleDC(self._window_dc)
            if not self.hdc:
                raise OSError("CreateCompatibleDC failed")
            info = _BitmapInfo()
            info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
            # A negative height asks for top-down rows, which matches numpy slicing.
            info.bmiHeader.biHeight = -int(height)
            info.bmiHeader.biWidth = int(width)
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            bits = ctypes.c_void_p()
            self._bitmap = _gdi32.CreateDIBSection(
                self.hdc,
                ctypes.byref(info),
                DIB_RGB_COLORS,
                ctypes.byref(bits),
                None,
                0,
            )
            if not self._bitmap or bits.value is None:
                raise OSError("CreateDIBSection failed")
            self._old_bitmap = _gdi32.SelectObject(self.hdc, self._bitmap)
            self._buffer = (ctypes.c_ubyte * (int(width) * int(height) * DIB_BYTES_PER_PIXEL)).from_address(
                int(bits.value)
            )
            self.view = np.frombuffer(self._buffer, dtype=np.uint8).reshape(int(height), int(width), 4)
        except Exception:
            self.release()
            raise

    def release(self) -> None:
        if self._old_bitmap and self.hdc:
            _gdi32.SelectObject(self.hdc, self._old_bitmap)
        if self._bitmap:
            _gdi32.DeleteObject(self._bitmap)
        if self.hdc:
            _gdi32.DeleteDC(self.hdc)
        if self._window_dc:
            _user32.ReleaseDC(self._hwnd, self._window_dc)
        self._bitmap = None
        self._old_bitmap = None
        self.hdc = None
        self._window_dc = None
        self._buffer = None
        self.view = None


class _WindowFrameBackend:
    """Base class for a backend that copies client-area rectangles out of one window."""

    name = ""

    def __init__(self, owner: "ScreenCapture"):
        self._owner = owner

    def available(self) -> bool:
        return True

    def capture_regions(self, hwnd: int, rects: Sequence[ClientRect]) -> Optional[List[np.ndarray]]:
        """Return one BGR copy per requested client-area rectangle, or None when the window is unavailable."""
        raise NotImplementedError

    def close(self) -> None:
        return None


class _WgcBackend(_WindowFrameBackend):
    """Windows Graphics Capture via the windows-capture package."""

    name = CAPTURE_MODE_WGC

    def __init__(self, owner: "ScreenCapture"):
        super().__init__(owner)
        self._lock = threading.Lock()
        self._hwnd: Optional[int] = None
        self._control = None
        self._latest: Optional[np.ndarray] = None
        self._stopped = False

    def available(self) -> bool:
        if _windows_build_number() < WGC_MIN_WINDOWS_BUILD:
            return False
        try:
            _import_windows_capture()
        except Exception as e:
            self._owner.logger.info(f"WGC 不可用: {e}")
            return False
        return True

    def capture_regions(self, hwnd: int, rects: Sequence[ClientRect]) -> Optional[List[np.ndarray]]:
        if not self.available():
            return None
        try:
            self._ensure_session(hwnd)
        except Exception as e:
            self._owner.logger.error(f"WGC 会话启动失败: {e}")
            self._stop_session()
            return None
        with self._lock:
            frame = self._latest
        if frame is None:
            return None
        return self._crop_client_regions(frame, hwnd, rects)

    def close(self) -> None:
        self._stop_session()

    def _ensure_session(self, hwnd: int) -> None:
        with self._lock:
            same_window = self._hwnd == int(hwnd) and self._control is not None and not self._stopped
        if same_window:
            return
        self._stop_session()
        windows_capture = _import_windows_capture()
        capture = windows_capture.WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_hwnd=int(hwnd),
        )

        def on_frame_arrived(frame, capture_control, holder=self):
            holder._store_frame(frame)

        def on_closed(holder=self):
            holder._mark_closed()

        capture.event(on_frame_arrived)
        capture.event(on_closed)
        control = capture.start_free_threaded()
        with self._lock:
            self._hwnd = int(hwnd)
            self._control = control
            self._stopped = False
            self._latest = None
        self._owner.logger.info(f"WGC 会话已启动: hwnd={hwnd}")

    def _stop_session(self) -> None:
        with self._lock:
            control = self._control
            self._control = None
            self._hwnd = None
            self._latest = None
            self._stopped = True
        if control is None:
            return
        try:
            control.stop()
        except Exception as e:
            self._owner.logger.debug(f"WGC 会话停止失败: {e}")

    def _store_frame(self, frame) -> None:
        try:
            buffer = np.array(frame.frame_buffer, dtype=np.uint8, copy=True)
        except Exception as e:
            self._owner.logger.debug(f"WGC 帧读取失败: {e}")
            return
        with self._lock:
            self._latest = buffer

    def _mark_closed(self) -> None:
        with self._lock:
            self._stopped = True

    def _crop_client_regions(
        self,
        frame: np.ndarray,
        hwnd: int,
        rects: Sequence[ClientRect],
    ) -> Optional[List[np.ndarray]]:
        client = self._owner.get_client_rect(hwnd)
        if client is None:
            return None
        client_x, client_y, client_width, client_height = client
        frame_height, frame_width = frame.shape[:2]
        bounds = _get_extended_frame_bounds(hwnd)
        if bounds is None:
            if frame_width != client_width or frame_height != client_height:
                return None
            offset_x = offset_y = 0
        else:
            offset_x = client_x - bounds[0]
            offset_y = client_y - bounds[1]
            if (
                offset_x < 0
                or offset_y < 0
                or offset_x + client_width > frame_width
                or offset_y + client_height > frame_height
            ):
                return None
        client_surface = frame[
            offset_y:offset_y + client_height,
            offset_x:offset_x + client_width,
        ]
        return [_crop_bgra_to_bgr(client_surface, rect) for rect in rects]


class _PrintWindowBackend(_WindowFrameBackend):
    """PrintWindow renders the window into a cached DIB; only the requested rectangles are converted."""

    name = CAPTURE_MODE_PRINT_WINDOW

    def __init__(self, owner: "ScreenCapture"):
        super().__init__(owner)
        self._key: Optional[Tuple[int, int, int]] = None
        self._surface: Optional[_DibSurface] = None

    def capture_regions(self, hwnd: int, rects: Sequence[ClientRect]) -> Optional[List[np.ndarray]]:
        client = self._owner.get_client_rect(hwnd)
        if client is None:
            return None
        _, _, client_width, client_height = client
        try:
            window_left, window_top, window_right, window_bottom = win32gui.GetWindowRect(hwnd)
        except Exception as e:
            self._owner.logger.error(f"获取窗口矩形失败: {e}")
            return None
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        if window_width <= 0 or window_height <= 0:
            return None
        offset = self._owner.get_client_offset_in_window(hwnd)
        if offset is None:
            return None
        offset_x, offset_y = offset
        if (
            offset_x < 0
            or offset_y < 0
            or offset_x + client_width > window_width
            or offset_y + client_height > window_height
        ):
            return None
        try:
            surface = self._ensure_surface(int(hwnd), window_width, window_height)
            if surface is None or surface.view is None:
                return None
            result = _print_window_func(
                wintypes.HWND(int(hwnd)),
                wintypes.HDC(surface.hdc),
                wintypes.UINT(PW_RENDERFULLCONTENT),
            )
            if not int(result):
                return None
            client_surface = surface.view[offset_y:offset_y + client_height, offset_x:offset_x + client_width]
            return [_crop_bgra_to_bgr(client_surface, rect) for rect in rects]
        except Exception as e:
            self._owner.logger.error(f"{self.name} 客户区截图失败: {e}")
            self.close()
            return None

    def close(self) -> None:
        self._key = None
        surface = self._surface
        self._surface = None
        if surface is None:
            return
        try:
            surface.release()
        except Exception as e:
            self._owner.logger.debug(f"释放 DIB 位图失败: {e}")

    def _ensure_surface(self, hwnd: int, width: int, height: int) -> Optional[_DibSurface]:
        key = (hwnd, width, height)
        if self._key == key and self._surface is not None:
            return self._surface
        self.close()
        surface = _DibSurface(hwnd, width, height)
        self._surface = surface
        self._key = key
        return surface


class _WindowBitBltBackend(_WindowFrameBackend):
    """Client-area pixels copied from the screen DC in one union rectangle."""

    name = CAPTURE_MODE_WINDOW_BITBLT

    def __init__(self, owner: "ScreenCapture"):
        super().__init__(owner)
        self._size: Optional[Tuple[int, int]] = None
        self._screen_dc = None
        self._mem_dc = None
        self._save_dc = None
        self._bitmap = None

    def capture_regions(self, hwnd: int, rects: Sequence[ClientRect]) -> Optional[List[np.ndarray]]:
        client = self._owner.get_client_rect(hwnd)
        if client is None:
            return None
        union = _union_rect(rects)
        if union is None:
            return None
        union_x, union_y, union_width, union_height = union
        try:
            save_dc = self._ensure_dc(union_width, union_height)
            save_dc.BitBlt(
                (0, 0),
                (union_width, union_height),
                self._mem_dc,
                (client[0] + union_x, client[1] + union_y),
                win32con.SRCCOPY,
            )
            surface = _bitmap_to_bgra(self._bitmap)
            return [
                _crop_bgra_to_bgr(surface, _shift_rect(rect, union_x, union_y))
                for rect in rects
            ]
        except Exception as e:
            self._owner.logger.error(f"{self.name} 屏幕截图失败: {e}")
            self.close()
            return None

    def close(self) -> None:
        self._release_dc()

    def _ensure_dc(self, width: int, height: int):
        size = (width, height)
        if self._size == size and self._save_dc is not None:
            return self._save_dc
        self._release_dc()
        screen_dc = win32gui.GetDC(0)
        try:
            mem_dc = win32ui.CreateDCFromHandle(screen_dc)
            save_dc = mem_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mem_dc, width, height)
            save_dc.SelectObject(bitmap)
        except Exception:
            win32gui.ReleaseDC(0, screen_dc)
            raise
        self._screen_dc = screen_dc
        self._mem_dc = mem_dc
        self._save_dc = save_dc
        self._bitmap = bitmap
        self._size = size
        return save_dc

    def _release_dc(self) -> None:
        self._size = None
        if self._save_dc is not None:
            try:
                self._save_dc.DeleteDC()
            except Exception as e:
                self._owner.logger.debug(f"释放内存DC失败: {e}")
            self._save_dc = None
        if self._bitmap is not None:
            try:
                win32gui.DeleteObject(self._bitmap.GetHandle())
            except Exception as e:
                self._owner.logger.debug(f"释放位图失败: {e}")
            self._bitmap = None
        if self._mem_dc is not None:
            try:
                self._mem_dc.DeleteDC()
            except Exception as e:
                self._owner.logger.debug(f"释放兼容DC失败: {e}")
            self._mem_dc = None
        if self._screen_dc is not None:
            try:
                win32gui.ReleaseDC(0, self._screen_dc)
            except Exception as e:
                self._owner.logger.debug(f"释放屏幕DC失败: {e}")
            self._screen_dc = None


_BACKEND_CLASSES: Dict[str, type] = {
    CAPTURE_MODE_WGC: _WgcBackend,
    CAPTURE_MODE_PRINT_WINDOW: _PrintWindowBackend,
    CAPTURE_MODE_WINDOW_BITBLT: _WindowBitBltBackend,
}


class ScreenCapture:
    """
    屏幕截图工具类
    支持多种截图模式和窗口检测
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._backends: Dict[str, _WindowFrameBackend] = {}
        self._active_backend: Optional[str] = None
        self._backend_fail_count = 0
        self._next_probe_at = 0.0
        self._current_hwnd: Optional[int] = None
        self._event_sink: Optional[Callable[[str], None]] = None

    def set_event_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        """Install the translated-text sink for capture backend events."""
        self._event_sink = sink

    @staticmethod
    def _is_own_app_window(title: str, process_name: str) -> bool:
        """Exclude this navigator app window from game auto-detection."""
        title_norm = (title or "").lower().replace(" ", "")
        proc_norm = (process_name or "").lower().replace(" ", "")

        own_title_keywords = [
            "wutheringwaves-navigator",
            "wutheringwavesnavigator",
            "呜呜大地图",
            "navigator",
        ]
        own_process_keywords = [
            "wutheringwaves-navigator-smart.exe",
            "wutheringwaves-navigator.exe",
        ]

        if any(k in title_norm for k in own_title_keywords):
            return True
        if any(k in proc_norm for k in own_process_keywords):
            return True
        return False

    def capture_recognition_inputs(
        self,
        x: Optional[int],
        y: Optional[int],
        width: Optional[int],
        height: Optional[int],
        mode: str = CAPTURE_MODE_AUTO,
        target_window_name: str = '',
        minimap_search_region: Optional[Dict[str, int]] = None,
        target_hwnd: int = 0,
        include_full_frame: bool = False,
    ) -> Optional[RecognitionCapture]:
        """Capture the OCR band and the minimap region as patches in one coordinate system.

        When ``x``/``y``/``width``/``height`` are all present the region is manual: it is
        captured straight from the screen at those screen coordinates, matching the
        pre-refactor manual path, and the window is never consulted. When any is None the
        region is auto: only the game window client area is captured, using frame-relative
        coordinates derived from the client size (or the given ``minimap_search_region``),
        and a missing or unusable window returns None so the round is skipped.
        ``include_full_frame`` only exists for the debug frame package export.
        """
        ocr_region = None if None in (x, y, width, height) else (int(x), int(y), int(width), int(height))
        minimap_region = _region_to_rect(minimap_search_region)
        try:
            if ocr_region is None:
                return self._capture_from_window(
                    mode,
                    target_window_name,
                    target_hwnd,
                    minimap_region,
                    include_full_frame,
                )
            return self._capture_from_screen(
                ocr_region, minimap_region, include_full_frame, target_window_name
            )
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None

    def _capture_from_window(
        self,
        mode: str,
        target_window_name: str,
        target_hwnd: int,
        minimap_region: Optional[ClientRect],
        include_full_frame: bool,
    ) -> Optional[RecognitionCapture]:
        """Auto mode: crop the requested rectangles out of the game window client area.

        The rectangles are already expressed in frame (client) coordinates, so a locked
        minimap ROI is used unchanged. When no usable window is available this returns
        None and the caller skips the round; there is no fallback to the screen.
        """
        hwnd = self._resolve_target_hwnd(target_hwnd)
        if hwnd is None:
            return None
        client = self.get_client_rect(hwnd)
        if client is None:
            return None
        self._note_target_hwnd(hwnd)
        _, _, frame_width, frame_height = client
        ocr_rect = auto_ocr_region_from_frame_size(frame_width, frame_height)
        minimap_rect = (
            auto_minimap_search_rect(frame_width, frame_height)
            if minimap_region is None
            else minimap_region
        )
        rects = [ocr_rect, minimap_rect]
        if include_full_frame:
            rects.append((0, 0, frame_width, frame_height))
        regions, backend_name = self._select_and_capture(hwnd, normalize_capture_mode(mode), rects)
        if regions is None:
            return None
        return RecognitionCapture(
            ocr_crop=regions[0] if regions[0].size else None,
            minimap_patch=self._build_patch(regions[1], minimap_rect, frame_width, frame_height),
            source="window_full",
            target_window_name=target_window_name,
            backend=backend_name,
            full_frame=regions[2] if include_full_frame else None,
        )

    def _capture_from_screen(
        self,
        ocr_region: ClientRect,
        minimap_region: Optional[ClientRect],
        include_full_frame: bool,
        target_window_name: str,
    ) -> Optional[RecognitionCapture]:
        """Manual mode: BitBlt the requested regions from the screen by their screen coordinates.

        The screen coordinates become the frame (origin at their own position), matching the
        pre-refactor manual capture; the window is never consulted.
        """
        screen_width, screen_height = self.get_screen_size()
        minimap_rect = (
            auto_minimap_search_rect(screen_width, screen_height)
            if minimap_region is None
            else minimap_region
        )
        ocr_crop = self._capture_screen_region(*ocr_region)
        minimap_image = self._capture_screen_region(*minimap_rect)
        full_frame = (
            self._capture_screen_region(0, 0, screen_width, screen_height) if include_full_frame else None
        )
        if ocr_crop is None and minimap_image is None:
            return None
        return RecognitionCapture(
            ocr_crop=ocr_crop if ocr_crop is not None and ocr_crop.size else None,
            minimap_patch=(
                self._build_patch(minimap_image, minimap_rect, screen_width, screen_height)
                if minimap_image is not None and minimap_image.size
                else None
            ),
            source="fullscreen_full",
            target_window_name=target_window_name,
            full_frame=full_frame if full_frame is not None and full_frame.size else None,
        )

    @staticmethod
    def _build_patch(
        image: np.ndarray,
        rect: ClientRect,
        frame_width: int,
        frame_height: int,
    ) -> FramePatch:
        return FramePatch(
            image=image,
            origin_x=rect[0],
            origin_y=rect[1],
            frame_width=frame_width,
            frame_height=frame_height,
        )

    def _select_and_capture(
        self,
        hwnd: int,
        mode: str,
        rects: Sequence[ClientRect],
    ) -> Tuple[Optional[List[np.ndarray]], str]:
        if mode != CAPTURE_MODE_AUTO:
            backend = self._get_backend(mode)
            if backend is None or not backend.available():
                return None, mode
            return backend.capture_regions(hwnd, rects), mode

        active = self._active_backend
        if active is not None:
            backend = self._get_backend(active)
            regions = backend.capture_regions(hwnd, rects) if backend is not None else None
            if regions is not None:
                self._backend_fail_count = 0
                return regions, active
            self._backend_fail_count += 1
            if self._backend_fail_count < BACKEND_FAILURE_REPROBE_COUNT:
                return None, active
            self._log_event(
                f"capture backend {active} failed {self._backend_fail_count} times in a row, probing other backends",
                "capture_backend_reprobe",
                "截图后端 {backend} 连续 {count} 次失败，重新探测其他后端",
                backend=active,
                count=self._backend_fail_count,
            )
            self._active_backend = None

        if time.monotonic() < self._next_probe_at:
            return None, ""
        return self._probe_backends(hwnd, rects)

    def _probe_backends(
        self,
        hwnd: int,
        rects: Sequence[ClientRect],
    ) -> Tuple[Optional[List[np.ndarray]], str]:
        fallback: Optional[Tuple[str, List[np.ndarray]]] = None
        for name in CAPTURE_MODE_ORDER:
            backend = self._get_backend(name)
            if backend is None or not backend.available():
                continue
            deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
            regions = None
            while True:
                regions = backend.capture_regions(hwnd, rects)
                if regions is not None:
                    break
                if time.monotonic() >= deadline:
                    self._log_event(
                        f"capture backend {name} produced no frame within {PROBE_TIMEOUT_SECONDS}s",
                        "capture_backend_no_frame",
                        "截图后端 {backend} 在 {timeout}s 内未取到帧",
                        backend=name,
                        timeout=PROBE_TIMEOUT_SECONDS,
                    )
                    break
                time.sleep(PROBE_ATTEMPT_INTERVAL_SECONDS)
            if regions is None:
                continue
            if _all_regions_solid(regions):
                self._log_event(
                    f"capture backend {name} returned a solid frame, skipped",
                    "capture_backend_solid_frame",
                    "截图后端 {backend} 返回纯色帧，跳过",
                    backend=name,
                )
                continue
            if fallback is None:
                fallback = (name, regions)
            updated_regions = self._fetch_updated_regions(backend, hwnd, rects, regions)
            if updated_regions is not None:
                self._active_backend = name
                self._backend_fail_count = 0
                self._next_probe_at = 0.0
                self._log_event(
                    f"auto capture backend selected: {name}",
                    "capture_backend_selected",
                    "自动截图后端选定: {backend}",
                    backend=name,
                )
                return updated_regions, name
            self._log_event(
                f"capture backend {name} returned two identical frames, the image appears frozen, trying the next backend",
                "capture_backend_frozen",
                "截图后端 {backend} 连续两帧完全相同，画面疑似冻结，改用下一个后端",
                "WARNING",
                backend=name,
            )
        if fallback is not None:
            name, regions = fallback
            self._active_backend = name
            self._backend_fail_count = 0
            self._next_probe_at = 0.0
            self._log_event(
                f"auto capture backend selected: {name}, but every backend may be showing a static image (two identical frames)",
                "capture_backend_all_frames_static",
                "自动截图后端选定: {backend}，但所有后端画面可能静止（连续两帧相同）",
                "WARNING",
                backend=name,
            )
            return regions, name
        self._next_probe_at = time.monotonic() + PROBE_RETRY_INTERVAL_SECONDS
        self._log_event(
            "auto capture backend probe failed, this round skips recognition",
            "capture_backend_probe_failed",
            "自动截图后端探测失败，本轮跳过识别",
            "WARNING",
        )
        return None, ""

    def _log_event(
        self,
        log_text: str,
        key: str,
        default: str,
        level: str = "INFO",
        **params,
    ) -> None:
        """Record one backend event as ASCII file-log text and publish the translated text."""
        getattr(self.logger, level.lower(), self.logger.info)(log_text)
        sink = self._event_sink
        if sink is None:
            return
        try:
            sink(tr(key, default, **params))
        except Exception:
            self.logger.exception(f"capture event sink failed for {key}")

    def _fetch_updated_regions(
        self,
        backend: _WindowFrameBackend,
        hwnd: int,
        rects: Sequence[ClientRect],
        regions: List[np.ndarray],
    ) -> Optional[List[np.ndarray]]:
        """Return fresh regions only when at least one of them differs byte-wise from the given ones."""
        time.sleep(PROBE_UPDATE_INTERVAL_SECONDS)
        updated = backend.capture_regions(hwnd, rects)
        if updated is None:
            return None
        if _regions_are_identical(updated, regions):
            return None
        return updated

    def _get_backend(self, name: str) -> Optional[_WindowFrameBackend]:
        backend = self._backends.get(name)
        if backend is not None:
            return backend
        backend_class = _BACKEND_CLASSES.get(name)
        if backend_class is None:
            return None
        backend = backend_class(self)
        self._backends[name] = backend
        return backend

    def close(self) -> None:
        """Release all backend resources held by this instance."""
        for backend in self._backends.values():
            backend.close()
        self._active_backend = None
        self._backend_fail_count = 0
        self._next_probe_at = 0.0
        self._current_hwnd = None

    def _note_target_hwnd(self, hwnd: int) -> None:
        if self._current_hwnd == int(hwnd):
            return
        self._current_hwnd = int(hwnd)
        self._active_backend = None
        self._backend_fail_count = 0
        self._next_probe_at = 0.0

    def _resolve_target_hwnd(self, target_hwnd: int) -> Optional[int]:
        """Return the given handle when it is a live window, otherwise None.

        The capture module never searches for a window; window discovery is owned by OCRManager.
        """
        if not target_hwnd:
            return None
        try:
            hwnd = int(target_hwnd)
        except (TypeError, ValueError):
            return None
        return hwnd if win32gui.IsWindow(hwnd) else None

    def get_client_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """Return the client area as screen physical coordinates (x, y, width, height)."""
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return None
            if win32gui.IsIconic(hwnd):
                return None
            client_x, client_y = win32gui.ClientToScreen(hwnd, (0, 0))
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return None
            return (int(client_x), int(client_y), int(width), int(height))
        except Exception as e:
            self.logger.error(f"获取客户区失败: {e}")
            return None

    def get_client_offset_in_window(self, hwnd: int) -> Optional[Tuple[int, int]]:
        """Return the client area offset relative to the window rect top-left."""
        try:
            client_origin = win32gui.ClientToScreen(hwnd, (0, 0))
            window_rect = win32gui.GetWindowRect(hwnd)
            return (int(client_origin[0] - window_rect[0]), int(client_origin[1] - window_rect[1]))
        except Exception as e:
            self.logger.error(f"计算客户区偏移失败: {e}")
            return None

    def _capture_screen_region(self, x: int, y: int, width: int, height: int) -> Optional[np.ndarray]:
        """
        使用BitBlt方式捕获屏幕区域
        """
        screen_dc = None
        mem_dc = None
        save_dc = None
        save_bitmap = None
        try:
            # 获取屏幕DC
            screen_dc = win32gui.GetDC(0)

            # 创建内存DC
            mem_dc = win32ui.CreateDCFromHandle(screen_dc)
            save_dc = mem_dc.CreateCompatibleDC()

            # 创建位图
            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mem_dc, width, height)
            save_dc.SelectObject(save_bitmap)

            # 执行截图
            save_dc.BitBlt((0, 0), (width, height), mem_dc, (x, y), win32con.SRCCOPY)

            # 获取位图数据
            bmp_info = save_bitmap.GetInfo()
            bmp_str = save_bitmap.GetBitmapBits(True)

            # 转换为numpy数组
            image = np.frombuffer(bmp_str, dtype=np.uint8)
            image = image.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))

            # 转换BGRA到BGR
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            return image

        except Exception as e:
            self.logger.error(f"BitBlt截图失败: {e}")
            return None
        finally:
            if save_bitmap is not None:
                try:
                    win32gui.DeleteObject(save_bitmap.GetHandle())
                except Exception as e:
                    self.logger.debug(f"释放位图失败: {e}")
            if save_dc is not None:
                try:
                    save_dc.DeleteDC()
                except Exception as e:
                    self.logger.debug(f"释放内存DC失败: {e}")
            if mem_dc is not None:
                try:
                    mem_dc.DeleteDC()
                except Exception as e:
                    self.logger.debug(f"释放兼容DC失败: {e}")
            if screen_dc is not None:
                try:
                    win32gui.ReleaseDC(0, screen_dc)
                except Exception as e:
                    self.logger.debug(f"释放屏幕DC失败: {e}")

    def get_screen_size(self) -> Tuple[int, int]:
        """
        获取屏幕尺寸

        Returns:
            Tuple[int, int]: (width, height)
        """
        try:
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            return screen_width, screen_height
        except Exception as e:
            self.logger.error(f"获取屏幕尺寸失败: {e}")
            return 1920, 1080  # 默认值

    def find_best_game_window(self, keywords: Optional[List[str]] = None) -> Optional[Dict[str, object]]:
        """
        查找匹配度最高的游戏窗口（标题关键字优先，其次进程名，再面积）

        Returns:
            dict: {
                'title': str,
                'hwnd': int,
                'rect': (left, top, right, bottom),
                'width': int,
                'height': int,
                'area': int,
                'client_x': int,
                'client_y': int,
                'client_width': int,
                'client_height': int,
                'process_name': str,
                'mode': 'fullscreen'|'borderless'|'windowed',
                'title_hits': int,
                'process_hits': int
            }
        """
        if keywords is None:
            keywords = ['鸣潮', 'Wuthering Waves']

        normalized_keywords = [kw.lower().replace(" ", "") for kw in keywords if kw]
        candidates: List[Dict[str, object]] = []

        def enum_windows_callback(hwnd, windows):
            if not win32gui.IsWindowVisible(hwnd):
                return True

            title = win32gui.GetWindowText(hwnd)
            if not title or not title.strip():
                return True

            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 0 or height <= 0:
                return True

            title_norm = title.lower().replace(" ", "")
            title_hits = sum(1 for kw in normalized_keywords if kw in title_norm)

            process_name = self._get_process_name(hwnd)
            if self._is_own_app_window(title, process_name):
                return True
            proc_norm = process_name.lower().replace(" ", "") if process_name else ""
            process_hits = sum(1 for kw in normalized_keywords if kw in proc_norm)

            if title_hits == 0 and process_hits == 0:
                return True

            area = width * height
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            monitor_rect = self._get_monitor_rect(hwnd)
            mode = self._detect_window_mode(rect, style, monitor_rect)
            client_rect = self.get_client_rect(hwnd) or (0, 0, 0, 0)

            windows.append({
                'title': title,
                'hwnd': hwnd,
                'rect': rect,
                'width': width,
                'height': height,
                'area': area,
                'client_x': client_rect[0],
                'client_y': client_rect[1],
                'client_width': client_rect[2],
                'client_height': client_rect[3],
                'process_name': process_name,
                'mode': mode,
                'title_hits': title_hits,
                'process_hits': process_hits
            })
            return True

        win32gui.EnumWindows(enum_windows_callback, candidates)

        if not candidates:
            return None

        candidates.sort(
            key=lambda w: (w['title_hits'], w['process_hits'], w['area']),
            reverse=True
        )
        return candidates[0]

    def get_all_windows(self) -> list:
        """
        获取所有可见窗口列表

        Returns:
            list: [(窗口名称, 窗口句柄), ...] 的列表
        """
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                # 过滤掉空窗口名称和一些系统窗口
                if window_text and len(window_text.strip()) > 0:
                    # 过滤掉一些常见的系统窗口
                    system_windows = ['Program Manager', 'Desktop Window Manager', 'Windows Input Experience']
                    if not any(sys_win in window_text for sys_win in system_windows):
                        windows.append((window_text, hwnd))
            return True

        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)

        # 按窗口名称排序
        windows.sort(key=lambda x: x[0])
        return windows

    def _get_process_name(self, hwnd: int) -> str:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return ""
            try:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
                    False,
                    pid
                )
            except Exception:
                process_handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                    False,
                    pid
                )
            try:
                exe_path = win32process.GetModuleFileNameEx(process_handle, 0)
                return os.path.basename(exe_path)
            finally:
                win32api.CloseHandle(process_handle)
        except Exception:
            return ""

    def _get_monitor_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        try:
            monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            info = win32api.GetMonitorInfo(monitor)
            return info.get("Monitor", (0, 0, 0, 0))
        except Exception:
            return (0, 0, 0, 0)

    def _detect_window_mode(self, rect: Tuple[int, int, int, int], style: int,
                            monitor_rect: Tuple[int, int, int, int]) -> str:
        left, top, right, bottom = rect
        mon_left, mon_top, mon_right, mon_bottom = monitor_rect

        tolerance = 2
        if (abs(left - mon_left) <= tolerance and abs(top - mon_top) <= tolerance and
                abs(right - mon_right) <= tolerance and abs(bottom - mon_bottom) <= tolerance):
            return "fullscreen"

        has_caption = bool(style & win32con.WS_CAPTION)
        has_thick = bool(style & win32con.WS_THICKFRAME)
        if not has_caption and not has_thick:
            return "borderless"
        return "windowed"


# 全局截图实例
_screen_capture_instance = None


def get_screen_capture() -> ScreenCapture:
    """
    获取全局屏幕截图实例
    """
    global _screen_capture_instance
    if _screen_capture_instance is None:
        _screen_capture_instance = ScreenCapture()
    return _screen_capture_instance


def capture_recognition_inputs_callback(
    x: Optional[int],
    y: Optional[int],
    width: Optional[int],
    height: Optional[int],
    mode: str,
    target_window_name: str,
    minimap_search_region: Optional[Dict[str, int]],
    target_hwnd: int = 0,
    include_full_frame: bool = False,
) -> Optional[RecognitionCapture]:
    """Capture the OCR crop and the minimap patch for one recognition frame."""
    screen_capture = get_screen_capture()
    return screen_capture.capture_recognition_inputs(
        x,
        y,
        width,
        height,
        mode,
        target_window_name,
        minimap_search_region,
        target_hwnd=target_hwnd,
        include_full_frame=include_full_frame,
    )
