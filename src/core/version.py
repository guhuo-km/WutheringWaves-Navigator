# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppVersionInfo:
    app_id: str
    name: str
    display_name: str
    version: str
    channel: str
    update_base_url: str


DEFAULT_VERSION_INFO = AppVersionInfo(
    app_id="wutheringwaves-navigator",
    name="WutheringWaves-Navigator",
    display_name="呜呜大地图",
    version="0.0.0",
    channel="stable",
    update_base_url="",
)


def _project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _candidate_version_files(project_root: str | Path | None = None) -> list[Path]:
    if project_root is not None:
        root = Path(project_root)
        return [root / "version.json", root / "_internal" / "version.json"]

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "version.json")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass).resolve() / "version.json")

    candidates.append(_project_root_from_here() / "version.json")
    candidates.append(Path.cwd() / "version.json")
    return candidates


def find_version_file(project_root: str | Path | None = None) -> Path | None:
    return next((path for path in _candidate_version_files(project_root) if path.exists()), None)


def load_version_info(project_root: str | Path | None = None) -> AppVersionInfo:
    version_file = find_version_file(project_root)
    if version_file is None:
        return DEFAULT_VERSION_INFO

    try:
        data = json.loads(version_file.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_VERSION_INFO

    return AppVersionInfo(
        app_id=str(data.get("app_id") or DEFAULT_VERSION_INFO.app_id),
        name=str(data.get("name") or DEFAULT_VERSION_INFO.name),
        display_name=str(data.get("display_name") or DEFAULT_VERSION_INFO.display_name),
        version=str(data.get("version") or DEFAULT_VERSION_INFO.version),
        channel=str(data.get("channel") or DEFAULT_VERSION_INFO.channel),
        update_base_url=str(data.get("update_base_url") or DEFAULT_VERSION_INFO.update_base_url),
    )
