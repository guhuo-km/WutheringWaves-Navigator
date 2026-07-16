# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


def update_lock_path(app_root: str | Path) -> Path:
    return Path(app_root) / ".update" / "apply.lock"


def _process_create_time(pid: int) -> float | None:
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def _process_exists(pid: int, expected_create_time: float | None = None) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        if not psutil.pid_exists(pid):
            return False
        if expected_create_time is None:
            return True
        try:
            actual_create_time = float(psutil.Process(pid).create_time())
        except Exception:
            return True
        return abs(actual_create_time - expected_create_time) < 0.001
    except Exception:
        if expected_create_time is not None:
            return True
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False


def _remove_stale_lock(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        raw_owner = path.read_text(encoding="ascii").strip()
        owner = json.loads(raw_owner)
        if isinstance(owner, dict):
            pid = int(owner["pid"])
            expected_create_time = float(owner["process_create_time"])
        else:
            pid = int(owner)
            expected_create_time = None
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        try:
            if time.time() - path.stat().st_mtime < 60:
                return False
        except OSError:
            return False
    else:
        if _process_exists(pid, expected_create_time):
            return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def is_update_in_progress(app_root: str | Path) -> bool:
    path = update_lock_path(app_root)
    if not path.exists():
        return False
    return not _remove_stale_lock(path)


def update_in_progress_message() -> str:
    return "正在应用更新，请稍候。更新完成后再启动软件。"


@contextmanager
def update_lock(app_root: str | Path):
    path = update_lock_path(app_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    for attempt in range(2):
        try:
            handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            pid = os.getpid()
            process_create_time = _process_create_time(pid)
            if process_create_time is None:
                owner = str(pid)
            else:
                owner = json.dumps(
                    {
                        "pid": pid,
                        "process_create_time": process_create_time,
                    },
                    separators=(",", ":"),
                )
            os.write(handle, owner.encode("ascii", errors="ignore"))
            break
        except FileExistsError as exc:
            if attempt == 0 and _remove_stale_lock(path):
                continue
            raise RuntimeError(f"another updater is already running: {path}") from exc
        except Exception:
            if handle is not None:
                os.close(handle)
                handle = None
            try:
                path.unlink()
            except OSError:
                pass
            raise
    try:
        yield
    finally:
        if handle is not None:
            os.close(handle)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
