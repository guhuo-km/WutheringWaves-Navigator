# -*- coding: utf-8 -*-
"""Early crash diagnostics that do not depend on Qt UI or LogManager."""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime
from typing import Optional, TextIO


_SESSION_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
_installed = False
_crash_file: Optional[TextIO] = None
_original_sys_excepthook = None
_original_threading_excepthook = None


def resolve_session_log_dir(base_log_dir: str, session_ts: str) -> str:
    date_part, time_part = session_ts.split("_", 1)
    date_dir = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"
    return os.path.join(base_log_dir, date_dir, time_part)


def _resolve_log_dir() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        core_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(core_dir)
        base_dir = os.path.dirname(src_dir)

    log_dir = resolve_session_log_dir(os.path.join(base_dir, "logs"), _SESSION_TS)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _write_header(file_obj: TextIO) -> None:
    file_obj.write("WutheringWaves Navigator crash diagnostics\n")
    file_obj.write(f"started_at={datetime.now().isoformat(timespec='seconds')}\n")
    file_obj.write(f"python={sys.version.split()[0]}\n")
    file_obj.write(f"executable={sys.executable}\n")
    file_obj.write("=" * 72 + "\n")
    file_obj.flush()


def install_crash_diagnostics() -> Optional[str]:
    """Install early exception/faulthandler logging and return the log path."""
    global _installed, _crash_file
    global _original_sys_excepthook, _original_threading_excepthook

    if _installed:
        return getattr(_crash_file, "name", None)

    log_path = os.path.join(
        _resolve_log_dir(),
        "crash.log",
    )

    try:
        _crash_file = open(log_path, "a", encoding="utf-8", buffering=1)
        _write_header(_crash_file)
    except Exception:
        _crash_file = None
        return None

    _original_sys_excepthook = sys.excepthook
    _original_threading_excepthook = getattr(threading, "excepthook", None)

    def sys_hook(exc_type, exc_value, exc_traceback):
        try:
            _crash_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Unhandled exception\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=_crash_file)
            _crash_file.flush()
        except Exception:
            pass

        if _original_sys_excepthook:
            _original_sys_excepthook(exc_type, exc_value, exc_traceback)

    def threading_hook(args):
        try:
            _crash_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Thread exception: {args.thread.name}\n")
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=_crash_file)
            _crash_file.flush()
        except Exception:
            pass

        if _original_threading_excepthook:
            _original_threading_excepthook(args)

    sys.excepthook = sys_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = threading_hook

    try:
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        pass

    _installed = True
    return log_path
