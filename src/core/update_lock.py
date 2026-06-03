# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


def update_lock_path(app_root: str | Path) -> Path:
    return Path(app_root) / ".update" / "apply.lock"


def is_update_in_progress(app_root: str | Path) -> bool:
    return update_lock_path(app_root).exists()


def update_in_progress_message() -> str:
    return "正在应用更新，请稍候。更新完成后再启动软件。"


@contextmanager
def update_lock(app_root: str | Path):
    path = update_lock_path(app_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(handle, str(os.getpid()).encode("ascii", errors="ignore"))
    except FileExistsError as exc:
        raise RuntimeError(f"another updater is already running: {path}") from exc
    try:
        yield
    finally:
        if handle is not None:
            os.close(handle)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
