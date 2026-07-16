# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from .update_manifest import (
    LEGACY_USER_CONFIG_NAMES,
    LEGACY_USER_DATA_DIRECTORIES,
    LEGACY_USER_LOG_NAMES,
    ReleaseManifest,
    is_preserved_update_path,
    normalize_update_path,
    resolve_manifest_path,
    validate_release_manifest,
)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _unique_migration_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}.{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _same_file(first: Path, second: Path) -> bool:
    return first.stat().st_size == second.stat().st_size and sha256_file(first) == sha256_file(second)


def _migrate_file(source: Path, destination: Path, source_label: str) -> None:
    if not source.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_file() and _same_file(source, destination):
            source.unlink()
            return
        conflict = _unique_migration_path(
            destination.parent / "legacy" / source_label / destination.name
        )
        conflict.parent.mkdir(parents=True, exist_ok=True)
        source.replace(conflict)
        return
    source.replace(destination)


def _migrate_directory(source: Path, destination: Path, source_label: str) -> None:
    if not source.exists() or not source.is_dir():
        return
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        relative_path = source_file.relative_to(source)
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_file() and _same_file(source_file, target):
                source_file.unlink()
                continue
            conflict = _unique_migration_path(
                destination / f"legacy-{source_label}" / relative_path
            )
            conflict.parent.mkdir(parents=True, exist_ok=True)
            source_file.replace(conflict)
        else:
            source_file.replace(target)
    shutil.rmtree(source)


def migrate_legacy_user_data(app_root: str | Path) -> None:
    root = Path(app_root)
    config_root = root / "config"
    legacy_roots = (
        (root, "root"),
        (root / "src", "src"),
        (root / "_internal", "internal"),
    )
    for legacy_root, source_label in legacy_roots:
        for name in LEGACY_USER_CONFIG_NAMES:
            _migrate_file(legacy_root / name, config_root / name, source_label)

    log_root = root / "logs"
    for legacy_root, source_label in legacy_roots:
        for name in LEGACY_USER_LOG_NAMES:
            _migrate_file(legacy_root / name, log_root / name, source_label)

    for legacy_root, source_label in legacy_roots[1:]:
        for name in LEGACY_USER_DATA_DIRECTORIES:
            _migrate_directory(legacy_root / name, root / name, source_label)


def _validate_staged_files(root: Path, staging: Path, manifest: ReleaseManifest) -> None:
    for entry in manifest.files:
        if entry.protected or not entry.managed:
            continue
        expected_hash = entry.sha256.lower()
        target = resolve_manifest_path(root, entry.path)
        if target.exists() and target.is_file() and sha256_file(target) == expected_hash:
            continue
        staged = resolve_manifest_path(staging, entry.path)
        if not staged.exists() or not staged.is_file():
            raise FileNotFoundError(f"staged file missing: {entry.path}")
        if sha256_file(staged) != expected_hash:
            raise ValueError(f"staged file hash mismatch: {entry.path}")


def _find_stale_managed_files(root: Path, manifest: ReleaseManifest) -> list[Path]:
    manifest_paths = {
        normalize_update_path(entry.path)
        for entry in manifest.files
    }
    stale: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        if normalize_update_path(relative_path) in manifest_paths:
            continue
        if is_preserved_update_path(relative_path):
            continue
        stale.append(path)
    return stale


def _write_rollback_journal(
    rollback_root: Path,
    created: list[str],
    replaced: list[str],
    stale: list[str],
) -> None:
    rollback_root.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema": 1,
        "state": "applying",
        "created": created,
        "replaced": replaced,
        "stale": stale,
    }
    try:
        _store_rollback_journal(rollback_root, payload)
    except Exception as journal_error:
        try:
            _cleanup_rollback_root(rollback_root)
        except Exception as cleanup_error:
            raise RuntimeError(
                "rollback journal creation failed and cleanup was incomplete at "
                f"{rollback_root}: {cleanup_error}"
            ) from journal_error
        raise


def _store_rollback_journal(rollback_root: Path, payload: dict[str, object]) -> None:
    journal_path = rollback_root / "journal.json"
    temporary_path = rollback_root / "journal.json.tmp"
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary_path.replace(journal_path)


def _load_rollback_journal(rollback_root: Path) -> dict[str, object]:
    journal_path = rollback_root / "journal.json"
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid rollback journal: {journal_path}") from exc
    if payload.get("schema") != 1:
        raise RuntimeError(f"unsupported rollback journal: {journal_path}")
    state = payload.get("state")
    if state not in {"applying", "committed"}:
        raise RuntimeError(f"invalid rollback journal state: {journal_path}")

    journal: dict[str, object] = {"state": state}
    for category in ("created", "replaced", "stale"):
        paths = payload.get(category)
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise RuntimeError(f"invalid rollback journal category: {category}")
        for relative_path in paths:
            resolve_manifest_path(rollback_root, relative_path)
        journal[category] = paths
    return journal


def _mark_rollback_committed(rollback_root: Path) -> None:
    journal = _load_rollback_journal(rollback_root)
    journal["schema"] = 1
    journal["state"] = "committed"
    _store_rollback_journal(rollback_root, journal)


def _remove_update_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _cleanup_rollback_root(rollback_root: Path) -> None:
    if not rollback_root.exists():
        return

    journal_path = rollback_root / "journal.json"
    temporary_path = rollback_root / "journal.json.tmp"
    for path in sorted(rollback_root.iterdir(), key=lambda candidate: candidate.name):
        if path in {journal_path, temporary_path}:
            continue
        _remove_update_path(path)
    _remove_update_path(temporary_path)
    _remove_update_path(journal_path)
    rollback_root.rmdir()


def _restore_rollback_path(
    root: Path,
    rollback_root: Path,
    category: str,
    relative_path: str,
) -> None:
    target = resolve_manifest_path(root, relative_path)
    backup = resolve_manifest_path(rollback_root / category, relative_path)
    if not backup.exists():
        return
    _remove_update_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup.replace(target)


def _rollback_from_journal(root: Path, rollback_root: Path) -> None:
    journal = _load_rollback_journal(rollback_root)
    if journal["state"] != "applying":
        raise RuntimeError(f"rollback journal is already committed: {rollback_root}")
    rollback_errors: list[str] = []

    for relative_path in sorted(
        list(journal["created"]),
        key=lambda path: len(Path(path).parts),
        reverse=True,
    ):
        try:
            _remove_update_path(resolve_manifest_path(root, relative_path))
        except Exception as exc:
            rollback_errors.append(f"remove {relative_path}: {exc}")

    for category in ("replaced", "stale"):
        for relative_path in reversed(list(journal[category])):
            try:
                _restore_rollback_path(root, rollback_root, category, relative_path)
            except Exception as exc:
                rollback_errors.append(f"restore {relative_path}: {exc}")

    if rollback_errors:
        details = "; ".join(rollback_errors)
        raise RuntimeError(
            f"rollback incomplete; backups preserved at {rollback_root}: {details}"
        )


def recover_interrupted_updates(app_root: str | Path) -> list[Path]:
    root = Path(app_root)
    staging_base = root / ".update" / "staging"
    if not staging_base.exists():
        return []

    recovered: list[Path] = []
    for staging_root in sorted(path for path in staging_base.iterdir() if path.is_dir()):
        rollback_root = staging_root / ".rollback"
        if not rollback_root.exists():
            continue
        journal_path = rollback_root / "journal.json"
        if not journal_path.exists():
            evidence = [
                path
                for path in rollback_root.iterdir()
                if path.name != "journal.json.tmp"
            ]
            if evidence:
                raise RuntimeError(
                    f"rollback journal is missing while evidence remains: {rollback_root}"
                )
            _cleanup_rollback_root(rollback_root)
            recovered.append(staging_root)
            continue
        journal = _load_rollback_journal(rollback_root)
        if journal["state"] == "committed":
            migrate_legacy_user_data(root)
        else:
            _rollback_from_journal(root, rollback_root)
        _cleanup_rollback_root(rollback_root)
        recovered.append(staging_root)
    return recovered


def _backup_replaced_target(target: Path, backup: Path) -> None:
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        target.replace(backup)
        return

    temporary_backup = backup.with_name(f"{backup.name}.partial")
    _remove_update_path(temporary_backup)
    shutil.copy2(target, temporary_backup)
    if sha256_file(temporary_backup) != sha256_file(target):
        raise OSError(f"rollback backup hash mismatch: {target}")
    temporary_backup.replace(backup)


def apply_staged_update(app_root: str | Path, staging_root: str | Path, manifest: ReleaseManifest) -> None:
    root = Path(app_root)
    staging = Path(staging_root)
    rollback_root = staging / ".rollback"

    validate_release_manifest(manifest)
    if rollback_root.exists():
        raise RuntimeError(f"previous rollback data exists: {rollback_root}")
    _validate_staged_files(root, staging, manifest)
    stale_files = _find_stale_managed_files(root, manifest)

    pending: list[tuple[Path, Path]] = []
    for entry in manifest.files:
        if entry.protected or not entry.managed:
            continue
        target = resolve_manifest_path(root, entry.path)
        target_current = (
            target.exists()
            and target.is_file()
            and sha256_file(target) == entry.sha256.lower()
        )
        if target_current:
            continue
        pending.append((target, resolve_manifest_path(staging, entry.path)))

    stale_relative = [target.relative_to(root).as_posix() for target in stale_files]
    replaced_relative = [
        target.relative_to(root).as_posix()
        for target, _staged in pending
        if target.exists()
    ]
    created_relative = [
        target.relative_to(root).as_posix()
        for target, _staged in pending
        if not target.exists()
    ]

    if not stale_relative and not replaced_relative and not created_relative:
        migrate_legacy_user_data(root)
        return

    _write_rollback_journal(
        rollback_root,
        created=created_relative,
        replaced=replaced_relative,
        stale=stale_relative,
    )

    try:
        for relative_path in stale_relative:
            target = resolve_manifest_path(root, relative_path)
            if target.exists():
                backup = resolve_manifest_path(rollback_root / "stale", relative_path)
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.replace(backup)

        for target, staged in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                relative_path = target.relative_to(root).as_posix()
                backup = resolve_manifest_path(rollback_root / "replaced", relative_path)
                _backup_replaced_target(target, backup)
            staged.replace(target)

        for entry in manifest.files:
            if entry.protected or not entry.managed:
                continue
            target = resolve_manifest_path(root, entry.path)
            if (
                not target.exists()
                or not target.is_file()
                or sha256_file(target) != entry.sha256.lower()
            ):
                raise RuntimeError(f"updated file verification failed: {entry.path}")
        for relative_path in stale_relative:
            if resolve_manifest_path(root, relative_path).is_file():
                raise RuntimeError(f"stale managed file remains: {relative_path}")
    except Exception as update_error:
        try:
            _rollback_from_journal(root, rollback_root)
        except Exception as rollback_error:
            raise RuntimeError(
                f"update failed and rollback incomplete; backups preserved at {rollback_root}: "
                f"{rollback_error}"
            ) from update_error
        _cleanup_rollback_root(rollback_root)
        raise

    _mark_rollback_committed(rollback_root)
    migrate_legacy_user_data(root)
    _cleanup_rollback_root(rollback_root)
