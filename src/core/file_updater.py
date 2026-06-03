# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from .update_manifest import ManifestFileEntry, ReleaseManifest, resolve_manifest_path


PROTECTED_DELETE_PATHS = {
    "app_settings.json",
    "ocr_config.json",
    "language_config.json",
    "calibration_data.json",
    "maps.json",
    "README.txt",
    "WutheringWaves-Updater.exe",
}

PROTECTED_DELETE_PREFIXES = (
    "logs/",
    ".update/",
    "recorded_routes/",
    "tiles/",
    "images/",
    "src/recorded_routes/",
    "src/tiles/",
    "src/images/",
    "_internal/recorded_routes/",
    "_internal/tiles/",
    "_internal/images/",
)


def should_skip_delete(relative_path: str) -> bool:
    path = relative_path.replace("\\", "/")
    if path in PROTECTED_DELETE_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PROTECTED_DELETE_PREFIXES)


@dataclass(frozen=True)
class UpdatePlanItem:
    entry: ManifestFileEntry
    target_path: Path


@dataclass(frozen=True)
class UpdatePlan:
    version: str
    items: list[UpdatePlanItem]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_update_plan(app_root: str | Path, manifest: ReleaseManifest) -> UpdatePlan:
    root = Path(app_root)
    items: list[UpdatePlanItem] = []
    for entry in manifest.files:
        if entry.protected or not entry.managed:
            continue
        target_path = resolve_manifest_path(root, entry.path)
        if target_path.exists() and sha256_file(target_path) == entry.sha256:
            continue
        items.append(UpdatePlanItem(entry=entry, target_path=target_path))
    return UpdatePlan(version=manifest.version, items=items)


def apply_staged_update(app_root: str | Path, staging_root: str | Path, manifest: ReleaseManifest) -> None:
    root = Path(app_root)
    staging = Path(staging_root)
    backups: list[tuple[Path, Path]] = []
    replaced: list[Path] = []

    try:
        for entry in manifest.files:
            if entry.protected or not entry.managed:
                continue
            target = resolve_manifest_path(root, entry.path)
            staged = resolve_manifest_path(staging, entry.path)
            target_current = target.exists() and sha256_file(target) == entry.sha256
            if not staged.exists():
                if target_current:
                    continue
                raise FileNotFoundError(f"staged file missing: {entry.path}")
            if sha256_file(staged) != entry.sha256:
                raise ValueError(f"staged file hash mismatch: {entry.path}")
            if target_current:
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            backup = target.with_name(target.name + ".bak")
            if target.exists():
                if backup.exists():
                    backup.unlink()
                target.replace(backup)
                backups.append((target, backup))
            shutil.copy2(staged, target)
            replaced.append(target)

        for _, backup in backups:
            if backup.exists():
                backup.unlink()

        for relative_path in manifest.delete:
            if should_skip_delete(relative_path):
                continue
            target = resolve_manifest_path(root, relative_path)
            if target.exists() and target.is_file():
                target.unlink()
    except Exception:
        for target in replaced:
            if target.exists():
                target.unlink()
        for target, backup in backups:
            if backup.exists():
                backup.replace(target)
        raise
