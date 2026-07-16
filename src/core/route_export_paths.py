# -*- coding: utf-8 -*-
"""Shared route export directory resolution."""

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths

from core import paths
from core.settings_manager import SettingsManager


ROUTE_EXPORT_DIRECTORY_KEY = "route.export_directory"
ROUTE_EXPORT_EXTENSIONS = {".json", ".svg", ".zip"}


def get_system_download_directory() -> Path:
    configured = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
    if configured:
        return Path(configured)
    return paths.runtime_dir("downloads")


def resolve_route_export_directory(
    settings: Optional[SettingsManager] = None,
) -> Path:
    manager = settings or SettingsManager()
    configured = str(manager.get(ROUTE_EXPORT_DIRECTORY_KEY, "") or "").strip()
    target = _expand_directory(configured) if configured else get_system_download_directory()

    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError:
        fallback = get_system_download_directory()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def is_route_export_download(url: str, filename: str) -> bool:
    source = str(url or "").lower()
    extension = Path(str(filename or "")).suffix.lower()
    return source.startswith(("blob:", "data:")) and extension in ROUTE_EXPORT_EXTENSIONS


def _expand_directory(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    return Path(os.path.abspath(expanded))
