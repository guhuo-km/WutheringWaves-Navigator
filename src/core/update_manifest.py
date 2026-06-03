# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def resolve_manifest_path(app_root: str | Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("manifest path is empty")
    if "\x00" in relative_path:
        raise ValueError("manifest path contains null byte")
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
