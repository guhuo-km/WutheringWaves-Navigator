# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


EXPECTED_UPDATE_APP_ID = "wutheringwaves-navigator"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


LEGACY_USER_CONFIG_NAMES = (
    "app_settings.json",
    "ocr_config.json",
    "language_config.json",
    "calibration_data.json",
    "maps.json",
)

LEGACY_USER_DATA_DIRECTORIES = (
    "recorded_routes",
    "tiles",
    "images",
)

LEGACY_USER_LOG_NAMES = (
    "ocr_logs.json",
)

PRESERVED_UPDATE_FILES = frozenset(
    {
        "wutheringwaves-updater.exe",
        "uninstall.exe",
        *LEGACY_USER_CONFIG_NAMES,
        *(f"src/{name}" for name in LEGACY_USER_CONFIG_NAMES),
        *(f"_internal/{name}" for name in LEGACY_USER_CONFIG_NAMES),
        *LEGACY_USER_LOG_NAMES,
        *(f"src/{name}" for name in LEGACY_USER_LOG_NAMES),
        *(f"_internal/{name}" for name in LEGACY_USER_LOG_NAMES),
    }
)

PRESERVED_UPDATE_PREFIXES = (
    "config/",
    "logs/",
    ".update/",
    "recorded_routes/",
    "tiles/",
    "images/",
    "downloads/",
    "debug/",
    "cache/",
    *(f"src/{name}/" for name in LEGACY_USER_DATA_DIRECTORIES),
    *(f"_internal/{name}/" for name in LEGACY_USER_DATA_DIRECTORIES),
)

def normalize_update_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.casefold()


def is_preserved_update_path(path: str) -> bool:
    normalized = normalize_update_path(path)
    if normalized in PRESERVED_UPDATE_FILES:
        return True
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in PRESERVED_UPDATE_PREFIXES
    )


@dataclass(frozen=True)
class ManifestFileEntry:
    path: str
    size: int
    sha256: str
    url: str
    managed: bool
    protected: bool


@dataclass(frozen=True)
class ReleaseManifest:
    schema: int
    app_id: str
    version: str
    channel: str
    files: list[ManifestFileEntry]
    delete: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseManifest":
        files = [
            ManifestFileEntry(
                path=str(item["path"]),
                size=int(item.get("size", 0)),
                sha256=str(item.get("sha256", "")),
                url=str(item.get("url", "")),
                managed=bool(item.get("managed", False)),
                protected=bool(item.get("protected", False)),
            )
            for item in data.get("files", [])
        ]
        return cls(
            schema=int(data.get("schema", 1)),
            app_id=str(data.get("app_id", "")),
            version=str(data.get("version", "")),
            channel=str(data.get("channel", "stable")),
            files=files,
            delete=[str(path) for path in data.get("delete", [])],
        )


def validate_release_manifest(
    manifest: ReleaseManifest,
    expected_version: str | None = None,
    required_managed_paths: set[str] | frozenset[str] = frozenset(),
) -> None:
    if manifest.schema != 1:
        raise ValueError(f"unsupported manifest schema: {manifest.schema}")
    if manifest.app_id != EXPECTED_UPDATE_APP_ID:
        raise ValueError(f"unexpected manifest app_id: {manifest.app_id}")
    if not manifest.version:
        raise ValueError("manifest version is empty")
    if expected_version and manifest.version != expected_version:
        raise ValueError(
            f"manifest version mismatch: expected {expected_version}, got {manifest.version}"
        )

    seen_paths: set[str] = set()
    managed_paths: set[str] = set()
    validation_root = Path.cwd()
    for entry in manifest.files:
        resolve_manifest_path(validation_root, entry.path)
        normalized = normalize_update_path(entry.path)
        if normalized in seen_paths:
            raise ValueError(f"duplicate manifest path: {entry.path}")
        seen_paths.add(normalized)
        preserved = is_preserved_update_path(entry.path)
        if preserved:
            if entry.managed or not entry.protected:
                raise ValueError(f"invalid manifest path classification: {entry.path}")
        elif not entry.managed or entry.protected:
            raise ValueError(f"invalid manifest path classification: {entry.path}")
        if not entry.managed:
            continue
        if entry.size < 0:
            raise ValueError(f"invalid manifest file size: {entry.path}")
        if not SHA256_PATTERN.fullmatch(entry.sha256):
            raise ValueError(f"invalid manifest file hash: {entry.path}")
        try:
            parsed_url = urlsplit(entry.url)
            parsed_hostname = parsed_url.hostname
            parsed_url.port
        except ValueError as exc:
            raise ValueError(f"invalid manifest file URL: {entry.path}") from exc
        absolute_http_url = (
            parsed_url.scheme.casefold() in {"http", "https"}
            and bool(parsed_hostname)
        )
        relative_url = (
            not parsed_url.scheme
            and not parsed_url.netloc
            and bool(parsed_url.path)
        )
        if (
            not entry.url
            or any(character.isspace() for character in entry.url)
            or not (absolute_http_url or relative_url)
        ):
            raise ValueError(f"invalid manifest file URL: {entry.path}")
        managed_paths.add(normalized)

    required = {normalize_update_path(path) for path in required_managed_paths}
    missing = sorted(required - managed_paths)
    if missing:
        raise ValueError(f"manifest missing required managed files: {', '.join(missing)}")


def resolve_manifest_path(app_root: str | Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("manifest path is empty")
    if "\x00" in relative_path:
        raise ValueError("manifest path contains null byte")
    path_parts = relative_path.replace("\\", "/").split("/")
    if any(not part for part in path_parts):
        raise ValueError(f"manifest path contains repeated separators: {relative_path}")
    if any(":" in part for part in path_parts):
        raise ValueError(f"manifest path contains unsafe colon: {relative_path}")
    if any(part.endswith((" ", ".")) for part in path_parts if part):
        raise ValueError(f"manifest path contains unsafe Windows alias: {relative_path}")
    if os.path.isabs(relative_path):
        raise ValueError(f"manifest path must be relative: {relative_path}")
    if len(relative_path) >= 2 and relative_path[1] == ":":
        raise ValueError(f"manifest path must not contain drive prefix: {relative_path}")

    root = Path(app_root).resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"manifest path escapes app root: {relative_path}") from exc
    return target
