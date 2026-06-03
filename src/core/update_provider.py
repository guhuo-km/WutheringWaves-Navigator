# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


@dataclass
class UpdateResult:
    has_update: bool
    current_version: str
    latest_version: str
    release_notes: str
    download_url: str
    checked_at: datetime
    update_mode: str = "download"
    manifest_url: str = ""
    installer_url: str = ""
    full_zip_url: str = ""
    full_zip_sha256: str = ""
    artifact_size: int = 0
    error_message: str = ""


def compare_versions(v1: str, v2: str) -> int:
    """Compare semantic versions, supporting prefixes/suffixes.

    Returns:
        -1 if v1 < v2
         0 if equal/unknown
         1 if v1 > v2
    """

    def normalize(v: str):
        base = (v or "").lower().lstrip("v").split("-")[0]
        nums = []
        for part in base.split("."):
            if part.isdigit():
                nums.append(int(part))
        return nums

    try:
        p1 = normalize(v1)
        p2 = normalize(v2)
        max_len = max(len(p1), len(p2), 3)
        for i in range(max_len):
            n1 = p1[i] if i < len(p1) else 0
            n2 = p2[i] if i < len(p2) else 0
            if n1 < n2:
                return -1
            if n1 > n2:
                return 1
        return 0
    except Exception:
        return 0


class StaticUpdateProvider:
    """Static provider for frontend stage before backend is ready."""

    def __init__(self, latest_version: str, release_notes: str, download_url: str):
        self.latest_version = latest_version
        self.release_notes = release_notes
        self.download_url = download_url

    def check(self, current_version: str) -> UpdateResult:
        has_update = compare_versions(current_version, self.latest_version) < 0
        return UpdateResult(
            has_update=has_update,
            current_version=current_version,
            latest_version=self.latest_version,
            release_notes=self.release_notes,
            download_url=self.download_url,
            checked_at=datetime.now(),
        )


class HttpUpdateProvider:
    def __init__(self, latest_url: str, artifact_key: str, session: Any | None = None, timeout: int = 10):
        self.latest_url = latest_url
        self.artifact_key = artifact_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def check(self, current_version: str) -> UpdateResult:
        checked_at = datetime.now()
        if not self.latest_url:
            return UpdateResult(
                has_update=False,
                current_version=current_version,
                latest_version=current_version,
                release_notes="",
                download_url="",
                checked_at=checked_at,
                error_message="更新地址未配置",
            )

        try:
            response = self.session.get(self.latest_url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return UpdateResult(
                has_update=False,
                current_version=current_version,
                latest_version=current_version,
                release_notes="",
                download_url="",
                checked_at=checked_at,
                error_message=str(exc),
            )

        latest_version = str(data.get("latest_version") or current_version)
        has_update = compare_versions(current_version, latest_version) < 0
        artifacts = data.get("artifacts", {})
        artifact = artifacts.get(self.artifact_key)
        if has_update and not artifact:
            return UpdateResult(
                has_update=False,
                current_version=current_version,
                latest_version=latest_version,
                release_notes=str(data.get("release_notes") or ""),
                download_url="",
                checked_at=checked_at,
                error_message=f"未找到更新产物: {self.artifact_key}",
            )
        artifact = artifact or {}
        update_mode = str(artifact.get("update_mode") or "download")
        if update_mode not in {"file", "full", "download"}:
            update_mode = "download"
        installer_url = str(artifact.get("installer_url") or "")
        manifest_url = str(artifact.get("manifest_url") or "")
        full_zip_url = str(artifact.get("full_zip_url") or "")
        full_zip_sha256 = str(artifact.get("full_zip_sha256") or "")
        download_url = str(artifact.get("download_url") or "") or installer_url or full_zip_url
        artifact_size = int(artifact.get("size") or 0)
        if has_update and update_mode == "file" and not manifest_url:
            return UpdateResult(
                has_update=False,
                current_version=current_version,
                latest_version=latest_version,
                release_notes=str(data.get("release_notes") or ""),
                download_url=download_url,
                checked_at=checked_at,
                update_mode=update_mode,
                manifest_url=manifest_url,
                installer_url=installer_url,
                full_zip_url=full_zip_url,
                full_zip_sha256=full_zip_sha256,
                artifact_size=artifact_size,
                error_message="缺少文件更新清单地址",
            )
        if has_update and update_mode in {"full", "download"} and not download_url:
            return UpdateResult(
                has_update=False,
                current_version=current_version,
                latest_version=latest_version,
                release_notes=str(data.get("release_notes") or ""),
                download_url="",
                checked_at=checked_at,
                update_mode=update_mode,
                manifest_url=manifest_url,
                installer_url=installer_url,
                full_zip_url=full_zip_url,
                full_zip_sha256=full_zip_sha256,
                artifact_size=artifact_size,
                error_message="更新产物缺少下载地址",
            )

        return UpdateResult(
            has_update=has_update,
            current_version=current_version,
            latest_version=latest_version,
            release_notes=str(data.get("release_notes") or ""),
            download_url=download_url,
            checked_at=checked_at,
            update_mode=update_mode,
            manifest_url=manifest_url,
            installer_url=installer_url,
            full_zip_url=full_zip_url,
            full_zip_sha256=full_zip_sha256,
            artifact_size=artifact_size,
        )
