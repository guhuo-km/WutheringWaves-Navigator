from __future__ import annotations

import os
from typing import Any, Callable

_IGNORED_TITLE_KEYWORDS = (
    "wutheringwavestool",
    "wuthering waves tool",
    "鸣潮助手",
    "wutheringwavesnavigator",
    "wutheringwaves navigator",
    "wuwa-navigator",
    "wuwa navigator",
)

_IGNORED_CLASS_KEYWORDS = (
    "shell_traywnd",
    "notifyiconoverflowwindow",
    "windows.ui.core.corewindow",
    "qwindowicon",
    "qwindowtooltip",
    "notifyicon",
)

_installed = False


def _normalize(value: Any) -> str:
    return str(value or "").lower().replace("\\", "/")


def _pid() -> int:
    return os.getpid()


def should_ignore_window(hwnd: int) -> bool:
    if not hwnd:
        return True
    if hwnd == _pid():
        return True
    try:
        import win32gui
        import win32process
    except Exception:
        return False

    try:
        if not win32gui.IsWindow(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd)
        class_name = win32gui.GetClassName(hwnd)
        title_l = _normalize(title)
        class_l = _normalize(class_name)

        for keyword in _IGNORED_TITLE_KEYWORDS:
            if keyword in title_l:
                return True

        for keyword in _IGNORED_CLASS_KEYWORDS:
            if keyword in class_l:
                return True

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid and pid == _pid():
                return True
        except Exception:
            pass
    except Exception:
        return False

    return False


def install_patches() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    try:
        import win32gui
    except Exception:
        return

    original_enum_windows = getattr(win32gui, "EnumWindows", None)
    if callable(original_enum_windows):
        def filtered_enum_windows(callback: Callable[[int, int], Any], extra: int = 0):
            def filtered_callback(hwnd: int, extra_arg: int):
                if should_ignore_window(hwnd):
                    return True
                return callback(hwnd, extra_arg)
            return original_enum_windows(filtered_callback, extra)
        win32gui.EnumWindows = filtered_enum_windows

    original_find_window = getattr(win32gui, "FindWindow", None)
    if callable(original_find_window):
        def filtered_find_window(class_name: str | None, window_name: str | None) -> int:
            hwnd = original_find_window(class_name, window_name)
            if hwnd and should_ignore_window(hwnd):
                return 0
            return hwnd
        win32gui.FindWindow = filtered_find_window

    original_find_window_ex = getattr(win32gui, "FindWindowEx", None)
    if callable(original_find_window_ex):
        def filtered_find_window_ex(parent: int, class_name: str | None, window_name: str | None) -> int:
            hwnd = original_find_window_ex(parent, class_name, window_name)
            if hwnd and should_ignore_window(hwnd):
                return 0
            return hwnd
        win32gui.FindWindowEx = filtered_find_window_ex
