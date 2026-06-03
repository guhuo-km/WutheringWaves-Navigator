# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from pathlib import Path


REMOVED_PACKAGED_FILES = (
    "_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak",
    "_internal/cv2/opencv_videoio_ffmpeg4130_64.dll",
)


def remove_obsolete_packaged_files(app_root: str | Path) -> list[Path]:
    root = Path(app_root)
    removed: list[Path] = []
    for relative_path in REMOVED_PACKAGED_FILES:
        target = root / relative_path
        if target.exists() and target.is_file():
            target.unlink()
            removed.append(target)
    return removed


def refresh_root_updater(app_root: str | Path) -> bool:
    root = Path(app_root)
    source = root / "_internal" / "WutheringWaves-Updater.exe"
    target = root / "WutheringWaves-Updater.exe"
    if not source.exists() or not source.is_file():
        return False
    if target.exists() and target.stat().st_size == source.stat().st_size:
        return False
    shutil.copy2(source, target)
    return True


def run_startup_maintenance(app_root: str | Path) -> dict[str, object]:
    removed = remove_obsolete_packaged_files(app_root)
    updater_refreshed = refresh_root_updater(app_root)
    return {
        "removed": [str(path) for path in removed],
        "updater_refreshed": updater_refreshed,
    }
