#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from src.core.update_manifest import is_preserved_update_path


DOWNLOAD_PAGE_URL = "https://www.wuwuddt.com/download"


def normalize_manifest_path(path: Path) -> str:
    return path.as_posix()


def should_protect_path(relative_path: str) -> bool:
    return is_preserved_update_path(relative_path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    dist_root: Path,
    app_id: str,
    version: str,
    channel: str,
    file_url_prefix: str,
) -> dict:
    files = []
    for file_path in sorted(path for path in dist_root.rglob("*") if path.is_file()):
        relative_path = normalize_manifest_path(file_path.relative_to(dist_root))
        protected = should_protect_path(relative_path)
        managed = not protected
        digest = sha256_file(file_path)
        url = f"{file_url_prefix.rstrip('/')}/{digest}" if managed else ""
        files.append(
            {
                "path": relative_path,
                "size": file_path.stat().st_size,
                "sha256": digest,
                "url": url,
                "managed": managed,
                "protected": protected,
            }
        )

    return {
        "schema": 1,
        "app_id": app_id,
        "version": version,
        "channel": channel,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "delete": [],
    }


def copy_changed_files(
    dist_root: Path,
    files_root: Path,
    manifest: dict,
) -> list[str]:
    copied: list[str] = []
    seen_hashes: set[str] = set()
    for entry in manifest["files"]:
        if not entry["managed"]:
            continue
        digest = entry["sha256"]
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        target = files_root / digest
        source = dist_root / entry["path"]
        if target.exists() and sha256_file(target) == digest:
            continue
        files_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(digest)
    return copied


def copy_managed_files(dist_root: Path, files_root: Path, manifest: dict) -> list[str]:
    return copy_changed_files(dist_root, files_root, manifest)


def publish_updater_artifact(dist_root: Path, files_root: Path, file_url_prefix: str) -> dict:
    updater_path = dist_root / "WutheringWaves-Updater.exe"
    if not updater_path.exists() or not updater_path.is_file():
        raise FileNotFoundError(f"updater does not exist: {updater_path}")
    digest = sha256_file(updater_path)
    target = files_root / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or sha256_file(target) != digest:
        shutil.copy2(updater_path, target)
    return {
        "url": f"{file_url_prefix.rstrip('/')}/{digest}",
        "sha256": digest,
    }


def load_version_file(project_root: Path) -> dict:
    return json.loads((project_root / "version.json").read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_dist_version_file(dist_root: Path, version_info: dict, update_base_url: str) -> Path:
    packaged_info = dict(version_info)
    packaged_info["update_base_url"] = f"{update_base_url.rstrip('/')}/latest.json"
    version_path = dist_root / "_internal" / "version.json"
    write_json(version_path, packaged_info)
    (dist_root / "version.json").unlink(missing_ok=True)
    return version_path


def build_latest_metadata(
    app_id: str,
    channel: str,
    version: str,
    update_base_url: str,
    artifact_size: int,
    updater_info: dict,
    release_notes: str = "文件级更新发布。",
) -> dict:
    update_base_url = update_base_url.rstrip("/")
    if not update_base_url:
        raise ValueError("update_base_url is required for release metadata")
    legacy_download_info = {
        "version": version,
        "update_mode": "full",
        "download_url": DOWNLOAD_PAGE_URL,
        "installer_url": DOWNLOAD_PAGE_URL,
    }
    return {
        "schema": 1,
        "app_id": app_id,
        "channel": channel,
        "latest_version": version,
        "release_url": f"{update_base_url}/releases/{version}/release.json",
        "release_notes": release_notes,
        "artifacts": {
            "windows-x64-v2": {
                "version": version,
                "update_mode": "file",
                "manifest_url": f"{update_base_url}/releases/{version}/manifest.json",
                "size": artifact_size,
                "updater_url": updater_info["url"],
                "updater_sha256": updater_info["sha256"],
                "download_url": DOWNLOAD_PAGE_URL,
            },
            "windows-x64": legacy_download_info,
            "windows-x64-portable": legacy_download_info,
            "windows-x64-installer": legacy_download_info,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create WutheringWaves Navigator release artifacts")
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist-root", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--installer", default=None)
    parser.add_argument(
        "--update-base-url",
        default=None,
        help="Public base URL for this channel, e.g. https://example.com/app/stable. "
             "Can also be set with WUWA_UPDATE_BASE_URL.",
    )
    parser.add_argument(
        "--release-notes",
        default="文件级更新发布。",
        help="Release notes shown in latest.json and release.json.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    version_info = load_version_file(project_root)
    version = version_info["version"]
    channel = version_info.get("channel", "stable")
    app_id = version_info["app_id"]
    configured_update_url = args.update_base_url or os.environ.get("WUWA_UPDATE_BASE_URL")
    if configured_update_url:
        update_base_url = configured_update_url
    else:
        update_base_url = str(version_info.get("update_base_url") or "").rsplit("/", 1)[0]
    if not update_base_url:
        raise SystemExit(
            "update base URL is required; pass --update-base-url or set WUWA_UPDATE_BASE_URL"
        )

    dist_root = Path(args.dist_root).resolve() if args.dist_root else project_root / "dist" / "WutheringWaves-Navigator-Smart"
    if not dist_root.exists() or not dist_root.is_dir():
        raise SystemExit(f"dist root does not exist: {dist_root}")
    if not any(dist_root.rglob("*")):
        raise SystemExit(f"dist root is empty: {dist_root}")

    output_root = Path(args.output_root).resolve() if args.output_root else project_root / "dist" / "release"
    release_root = output_root / channel / "releases" / version
    files_root = output_root / channel / "files"

    write_dist_version_file(dist_root, version_info, update_base_url)

    manifest = build_manifest(dist_root, app_id, version, channel, f"{update_base_url}/files")
    copy_changed_files(dist_root, files_root, manifest)
    try:
        updater_info = publish_updater_artifact(
            dist_root,
            files_root,
            f"{update_base_url}/files",
        )
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    write_json(release_root / "manifest.json", manifest)

    if args.installer:
        installer_source = Path(args.installer).resolve()
        installer_target = release_root / "installer" / installer_source.name
        installer_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(installer_source, installer_target)

    latest = build_latest_metadata(
        app_id=app_id,
        channel=channel,
        version=version,
        update_base_url=update_base_url,
        artifact_size=sum(
            {
                entry["sha256"]: int(entry["size"])
                for entry in manifest["files"]
                if entry["managed"]
            }.values()
        ),
        updater_info=updater_info,
        release_notes=args.release_notes,
    )

    release = {
        "schema": 1,
        "app_id": app_id,
        "version": version,
        "channel": channel,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "display_name": version_info.get("display_name", version_info.get("name", app_id)),
        "summary": args.release_notes,
        "notes": [line for line in args.release_notes.splitlines() if line.strip()],
        "mandatory": False,
    }

    write_json(release_root / "release.json", release)
    write_json(output_root / channel / "latest.json", latest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
