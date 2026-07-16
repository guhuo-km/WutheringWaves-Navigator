# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .file_updater import migrate_legacy_user_data


REMOVED_PACKAGED_FILES = (
    "_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak",
    "_internal/cv2/opencv_videoio_ffmpeg4130_64.dll",
    "_internal/WutheringWaves-Updater.exe",
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


def run_startup_maintenance(app_root: str | Path) -> dict[str, object]:
    migrate_legacy_user_data(app_root)
    removed = remove_obsolete_packaged_files(app_root)
    return {
        "removed": [str(path) for path in removed],
    }
