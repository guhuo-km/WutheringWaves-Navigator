# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import requests

from .update_manifest import ReleaseManifest, resolve_manifest_path


class UpdateDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    staging_root: Path
    manifest_path: Path
    package_path: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_to_file(session, url: str, target: Path, timeout: int, progress_callback=None) -> None:
    response = session.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    total = int(response.headers.get("content-length") or 0)
    downloaded = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            handle.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                progress_callback(downloaded, total)


def _download_bytes(session, url: str, timeout: int) -> bytes:
    response = session.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    return b"".join(chunk for chunk in response.iter_content(chunk_size=1024 * 256) if chunk)


def _resolve_staging_root(staging_base: str | Path, version: str) -> Path:
    try:
        return resolve_manifest_path(staging_base, version)
    except ValueError as exc:
        raise UpdateDownloadError(f"unsafe version path: {version}") from exc


def _safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            try:
                target = resolve_manifest_path(destination, info.filename)
            except ValueError as exc:
                raise UpdateDownloadError(f"unsafe zip path: {info.filename}") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _absolute_entry_url(manifest_url: str, entry_url: str) -> str:
    if entry_url.startswith(("http://", "https://")):
        return entry_url
    base = manifest_url.rsplit("/", 1)[0]
    return f"{base.rstrip('/')}/{entry_url.lstrip('/')}"


def _stage_changed_manifest_files(
    app_root: str | Path,
    manifest_url: str,
    manifest: ReleaseManifest,
    staging_root: Path,
    session,
    timeout: int,
    progress_callback=None,
) -> None:
    root = Path(app_root)
    changed_entries = []
    for entry in manifest.files:
        if entry.protected or not entry.managed:
            continue
        target = resolve_manifest_path(root, entry.path)
        if target.exists() and _sha256_file(target).lower() == entry.sha256.lower():
            continue
        changed_entries.append(entry)

    total = sum(entry.size for entry in changed_entries)
    downloaded = 0
    for entry in changed_entries:
        staged_path = resolve_manifest_path(staging_root, entry.path)
        url = _absolute_entry_url(manifest_url, entry.url)
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        _download_to_file(session, url, staged_path, timeout)
        if _sha256_file(staged_path).lower() != entry.sha256.lower():
            raise UpdateDownloadError(f"file hash mismatch: {entry.path}")
        downloaded += entry.size
        if progress_callback:
            progress_callback(downloaded, total)


def stage_file_update(
    version: str,
    manifest_url: str,
    full_zip_url: str,
    staging_base: str | Path,
    full_zip_sha256: str | None = None,
    app_root: str | Path | None = None,
    session=None,
    timeout: int = 30,
    progress_callback=None,
) -> StagedUpdate:
    if not manifest_url:
        raise UpdateDownloadError("missing update URL")
    if app_root is None and not full_zip_sha256:
        raise UpdateDownloadError("missing package hash")

    session = session or requests.Session()
    base = Path(staging_base)
    staging_root = _resolve_staging_root(base, version)
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    manifest_path = staging_root / "manifest.json"
    package_path = staging_root / "update.zip"

    try:
        manifest_bytes = _download_bytes(session, manifest_url, timeout)
        manifest_path.write_bytes(manifest_bytes)
        manifest = ReleaseManifest.from_dict(json.loads(manifest_bytes.decode("utf-8")))
        if app_root is not None:
            _stage_changed_manifest_files(
                app_root=app_root,
                manifest_url=manifest_url,
                manifest=manifest,
                staging_root=staging_root,
                session=session,
                timeout=timeout,
                progress_callback=progress_callback,
            )
        else:
            if not full_zip_url:
                raise UpdateDownloadError("missing update URL")
            _download_to_file(session, full_zip_url, package_path, timeout, progress_callback)

            if _sha256_file(package_path).lower() != full_zip_sha256.lower():
                raise UpdateDownloadError("package hash mismatch")

            _safe_extract_zip(package_path, staging_root)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise

    return StagedUpdate(
        version=version,
        staging_root=staging_root,
        manifest_path=manifest_path,
        package_path=package_path,
    )
