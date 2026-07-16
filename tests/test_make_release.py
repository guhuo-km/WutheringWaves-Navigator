import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.make_release import (
    build_manifest,
    copy_changed_files,
    main,
    publish_updater_artifact,
    should_protect_path,
    write_dist_version_file,
)


def test_make_release_cli_entrypoint_starts_without_import_error():
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_release.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Create WutheringWaves Navigator release artifacts" in result.stdout


def test_should_protect_user_data_paths():
    assert should_protect_path("logs/app.log") is True
    assert should_protect_path(".update/staging/file.tmp") is True
    assert should_protect_path("config/app_settings.json") is True
    assert should_protect_path("config/ocr_config.json") is True
    assert should_protect_path("config/language_config.json") is True
    assert should_protect_path("config/calibration_data.json") is True
    assert should_protect_path("config/maps.json") is True
    assert should_protect_path("recorded_routes/route.json") is True
    assert should_protect_path("tiles/a.tile") is True
    assert should_protect_path("images/map.png") is True
    assert should_protect_path("downloads/route.json") is True
    assert should_protect_path("debug/minimap/frame.png") is True
    assert should_protect_path("cache/web_profile/Cookies") is True


def test_should_classify_packaged_paths():
    assert should_protect_path("WutheringWaves-Navigator-Smart.exe") is False
    assert should_protect_path("_internal/js/wuwa_map_optimizer.js") is False
    assert should_protect_path("cache/minimap_tiles/906/tile.png") is True
    assert should_protect_path("README.txt") is False


def test_should_protect_running_updater_binary():
    assert should_protect_path("WutheringWaves-Updater.exe") is True


def test_build_manifest_hashes_files(tmp_path):
    dist_root = tmp_path / "WutheringWaves-Navigator-Smart"
    internal = dist_root / "_internal" / "js"
    internal.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
    (internal / "wuwa_map_optimizer.js").write_text("console.log('ok')", encoding="utf-8")
    (dist_root / "logs").mkdir()
    (dist_root / "logs" / "app.log").write_text("user log", encoding="utf-8")

    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="1.0.1",
        channel="stable",
        file_url_prefix="portable/files",
    )

    entries = {entry["path"]: entry for entry in manifest["files"]}
    assert entries["WutheringWaves-Navigator-Smart.exe"]["managed"] is True
    assert entries["_internal/js/wuwa_map_optimizer.js"]["managed"] is True
    assert entries["logs/app.log"]["protected"] is True
    assert entries["logs/app.log"]["url"] == ""
    assert len(entries["WutheringWaves-Navigator-Smart.exe"]["sha256"]) == 64


def test_build_manifest_uses_absolute_hash_pool_urls_for_managed_files(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "app.exe").write_bytes(b"abc")
    (dist_root / "README.txt").write_text("readme", encoding="utf-8")

    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="1.2.3",
        channel="stable",
        file_url_prefix="https://updates.example.com/wuwa-navigator/stable/files",
    )

    app_entry = next(item for item in manifest["files"] if item["path"] == "app.exe")
    readme_entry = next(item for item in manifest["files"] if item["path"] == "README.txt")
    assert app_entry["managed"] is True
    assert app_entry["url"] == (
        f"https://updates.example.com/wuwa-navigator/stable/files/{app_entry['sha256']}"
    )
    assert readme_entry["managed"] is True
    assert readme_entry["url"] == (
        f"https://updates.example.com/wuwa-navigator/stable/files/{readme_entry['sha256']}"
    )


def test_copy_changed_files_populates_hashes_without_previous_manifest(tmp_path):
    dist_root = tmp_path / "dist"
    files_root = tmp_path / "files"
    dist_root.mkdir()
    (dist_root / "same.txt").write_bytes(b"same")
    (dist_root / "changed.txt").write_bytes(b"new")

    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="0.1.6.1",
        channel="stable",
        file_url_prefix="portable/files",
    )
    same_digest = next(e["sha256"] for e in manifest["files"] if e["path"] == "same.txt")
    changed_digest = next(e["sha256"] for e in manifest["files"] if e["path"] == "changed.txt")
    copied = copy_changed_files(dist_root, files_root, manifest)

    assert copied == [changed_digest, same_digest]
    assert (files_root / same_digest).read_bytes() == b"same"
    assert (files_root / changed_digest).read_bytes() == b"new"


def test_copy_changed_files_populates_hash_pool_once(tmp_path):
    dist_root = tmp_path / "dist"
    files_root = tmp_path / "release" / "stable" / "files"
    dist_root.mkdir()
    (dist_root / "a.txt").write_text("same", encoding="utf-8")
    (dist_root / "b.txt").write_text("same", encoding="utf-8")

    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="1.2.3",
        channel="stable",
        file_url_prefix="https://updates.example.com/wuwa-navigator/stable/files",
    )

    copied = copy_changed_files(dist_root, files_root, manifest)
    digest = next(item["sha256"] for item in manifest["files"] if item["path"] == "a.txt")

    assert copied == [digest]
    assert (files_root / digest).read_text(encoding="utf-8") == "same"


def test_copy_changed_files_repairs_corrupt_existing_hash_object(tmp_path):
    dist_root = tmp_path / "dist"
    files_root = tmp_path / "files"
    dist_root.mkdir()
    (dist_root / "app.exe").write_bytes(b"correct")
    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="1.2.3",
        channel="stable",
        file_url_prefix="https://updates.example.com/files",
    )
    digest = manifest["files"][0]["sha256"]
    files_root.mkdir()
    (files_root / digest).write_bytes(b"corrupt")

    copied = copy_changed_files(dist_root, files_root, manifest)

    assert copied == [digest]
    assert (files_root / digest).read_bytes() == b"correct"


def test_publish_updater_artifact_repairs_corrupt_existing_hash_object(tmp_path):
    dist_root = tmp_path / "dist"
    files_root = tmp_path / "files"
    dist_root.mkdir()
    updater = dist_root / "WutheringWaves-Updater.exe"
    updater.write_bytes(b"correct-updater")
    digest = hashlib.sha256(b"correct-updater").hexdigest()
    files_root.mkdir()
    (files_root / digest).write_bytes(b"corrupt")

    info = publish_updater_artifact(
        dist_root,
        files_root,
        "https://updates.example.com/files",
    )

    assert info["sha256"] == digest
    assert (files_root / digest).read_bytes() == b"correct-updater"


def test_write_dist_version_file_injects_client_latest_url(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()

    version_path = write_dist_version_file(
        dist_root,
        {
            "app_id": "wutheringwaves-navigator",
            "version": "0.2.0",
            "channel": "stable",
            "update_base_url": "",
        },
        "https://updates.example.com/wuwa/stable/",
    )

    assert version_path == dist_root / "_internal" / "version.json"
    packaged = json.loads(version_path.read_text(encoding="utf-8"))
    assert packaged["update_base_url"] == "https://updates.example.com/wuwa/stable/latest.json"


def test_make_release_uses_cli_update_base_url(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    dist_root = project_root / "dist" / "WutheringWaves-Navigator-Smart"
    dist_root.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
    (dist_root / "WutheringWaves-Updater.exe").write_bytes(b"updater")
    (project_root / "version.json").write_text(
        json.dumps(
            {
                "app_id": "wutheringwaves-navigator",
                "version": "0.2.0",
                "channel": "stable",
                "update_base_url": "",
            }
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "release"
    monkeypatch.setattr(
        "sys.argv",
        [
            "make_release.py",
            "--project-root",
            str(project_root),
            "--dist-root",
            str(dist_root),
            "--output-root",
            str(output_root),
            "--update-base-url",
            "https://updates.example.com/wuwa/stable",
        ],
    )

    assert main() == 0

    latest = json.loads((output_root / "stable" / "latest.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (output_root / "stable" / "releases" / "0.2.0" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["delete"] == []
    artifact = latest["artifacts"]["windows-x64-v2"]
    assert artifact["manifest_url"] == "https://updates.example.com/wuwa/stable/releases/0.2.0/manifest.json"
    assert artifact["updater_sha256"]
    assert artifact["download_url"] == "https://www.wuwuddt.com/download"
    assert "full_zip_url" not in artifact
    assert "full_zip_sha256" not in artifact
    first_artifact_size = artifact["size"]
    assert first_artifact_size > 0
    assert (output_root / "stable" / "files" / artifact["updater_sha256"]).read_bytes() == b"updater"
    legacy_expected = {
        "version": "0.2.0",
        "update_mode": "full",
        "download_url": "https://www.wuwuddt.com/download",
        "installer_url": "https://www.wuwuddt.com/download",
    }
    for artifact_key in ("windows-x64", "windows-x64-portable", "windows-x64-installer"):
        assert latest["artifacts"][artifact_key] == legacy_expected
    assert not (output_root / "stable" / "releases" / "0.2.0" / "portable").exists()
    packaged_version = json.loads((dist_root / "_internal" / "version.json").read_text(encoding="utf-8"))
    assert packaged_version["update_base_url"] == "https://updates.example.com/wuwa/stable/latest.json"

    assert main() == 0
    repeated_latest = json.loads(
        (output_root / "stable" / "latest.json").read_text(encoding="utf-8")
    )
    assert repeated_latest["artifacts"]["windows-x64-v2"]["size"] == first_artifact_size


def test_make_release_keeps_explicit_installer_file_but_legacy_keys_still_open_download_page(
    tmp_path, monkeypatch
):
    project_root = tmp_path / "project"
    dist_root = project_root / "dist" / "WutheringWaves-Navigator-Smart"
    dist_root.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
    (dist_root / "WutheringWaves-Updater.exe").write_bytes(b"updater")
    installer_source = project_root / "setup.exe"
    installer_source.write_bytes(b"installer")
    (project_root / "version.json").write_text(
        json.dumps(
            {
                "app_id": "wutheringwaves-navigator",
                "version": "0.2.2",
                "channel": "stable",
                "update_base_url": "https://updates.example.com/wuwa/stable/latest.json",
            }
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "release"
    monkeypatch.setattr(
        "sys.argv",
        [
            "make_release.py",
            "--project-root",
            str(project_root),
            "--dist-root",
            str(dist_root),
            "--output-root",
            str(output_root),
            "--installer",
            str(installer_source),
        ],
    )

    assert main() == 0

    latest = json.loads((output_root / "stable" / "latest.json").read_text(encoding="utf-8"))
    assert latest["artifacts"]["windows-x64-installer"] == {
        "version": "0.2.2",
        "update_mode": "full",
        "download_url": "https://www.wuwuddt.com/download",
        "installer_url": "https://www.wuwuddt.com/download",
    }
    assert (
        output_root / "stable" / "releases" / "0.2.2" / "installer" / installer_source.name
    ).read_bytes() == b"installer"


def test_make_release_writes_release_notes_to_latest_and_release(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    dist_root = project_root / "dist" / "WutheringWaves-Navigator-Smart"
    dist_root.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
    (dist_root / "WutheringWaves-Updater.exe").write_bytes(b"updater")
    (project_root / "version.json").write_text(
        json.dumps(
            {
                "app_id": "wutheringwaves-navigator",
                "display_name": "呜呜大地图",
                "version": "0.2.1",
                "channel": "stable",
                "update_base_url": "https://updates.example.com/wuwa/stable/latest.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "release"
    monkeypatch.setattr(
        "sys.argv",
        [
            "make_release.py",
            "--project-root",
            str(project_root),
            "--dist-root",
            str(dist_root),
            "--output-root",
            str(output_root),
            "--release-notes",
            "修复关于页更新日志显示",
        ],
    )

    assert main() == 0

    latest = json.loads((output_root / "stable" / "latest.json").read_text(encoding="utf-8"))
    release = json.loads((output_root / "stable" / "releases" / "0.2.1" / "release.json").read_text(encoding="utf-8"))
    assert latest["release_notes"] == "修复关于页更新日志显示"
    assert release["summary"] == "修复关于页更新日志显示"
    assert release["notes"] == ["修复关于页更新日志显示"]


def test_make_release_requires_update_base_url_when_source_config_is_public_safe(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    dist_root = project_root / "dist" / "WutheringWaves-Navigator-Smart"
    dist_root.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
    (project_root / "version.json").write_text(
        json.dumps(
            {
                "app_id": "wutheringwaves-navigator",
                "version": "0.2.0",
                "channel": "stable",
                "update_base_url": "",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("WUWA_UPDATE_BASE_URL", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "make_release.py",
            "--project-root",
            str(project_root),
            "--dist-root",
            str(dist_root),
            "--output-root",
            str(tmp_path / "release"),
        ],
    )

    with pytest.raises(SystemExit, match="update base URL is required"):
        main()
