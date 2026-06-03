import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.make_release import (
    build_latest_metadata,
    build_delete_entries,
    build_manifest,
    copy_changed_files,
    create_portable_zip,
    main,
    should_protect_path,
    write_dist_version_file,
)


def test_should_protect_user_data_paths():
    assert should_protect_path("logs/app.log") is True
    assert should_protect_path(".update/staging/file.tmp") is True
    assert should_protect_path("app_settings.json") is True
    assert should_protect_path("ocr_config.json") is True
    assert should_protect_path("language_config.json") is True
    assert should_protect_path("calibration_data.json") is True
    assert should_protect_path("maps.json") is True
    assert should_protect_path("recorded_routes/route.json") is True
    assert should_protect_path("tiles/a.tile") is True
    assert should_protect_path("images/map.png") is True
    assert should_protect_path("src/app_settings.json") is True
    assert should_protect_path("src/ocr_config.json") is True
    assert should_protect_path("src/calibration_data.json") is True
    assert should_protect_path("src/recorded_routes/route.json") is True
    assert should_protect_path("src/tiles/a.tile") is True
    assert should_protect_path("_internal/app_settings.json") is True
    assert should_protect_path("_internal/ocr_config.json") is True
    assert should_protect_path("_internal/calibration_data.json") is True
    assert should_protect_path("_internal/recorded_routes/route.json") is True
    assert should_protect_path("_internal/tiles/a.tile") is True


def test_should_manage_packaged_paths():
    assert should_protect_path("WutheringWaves-Navigator-Smart.exe") is False
    assert should_protect_path("_internal/js/wuwa_map_optimizer.js") is False


def test_should_protect_running_updater_binary():
    assert should_protect_path("WutheringWaves-Updater.exe") is True


def test_should_ignore_generated_readme():
    assert should_protect_path("README.txt") is True


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
    assert readme_entry["managed"] is False
    assert readme_entry["url"] == "https://updates.example.com/wuwa-navigator/stable/files/README.txt"


def test_build_delete_entries_lists_removed_managed_files(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    (dist_root / "current.txt").write_text("new", encoding="utf-8")
    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="0.1.0",
        channel="stable",
        file_url_prefix="portable/files",
    )
    previous_entries = {
        "current.txt": {"path": "current.txt", "managed": True, "protected": False},
        "_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak": {
            "path": "_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak",
            "managed": True,
            "protected": False,
        },
    }

    assert build_delete_entries(manifest, previous_entries) == [
        "_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak"
    ]


def test_build_delete_entries_skips_removed_protected_files(tmp_path):
    dist_root = tmp_path / "dist"
    dist_root.mkdir()
    manifest = build_manifest(
        dist_root=dist_root,
        app_id="wutheringwaves-navigator",
        version="0.1.0",
        channel="stable",
        file_url_prefix="portable/files",
    )
    previous_entries = {
        "ocr_config.json": {"path": "ocr_config.json", "managed": False, "protected": True},
        "logs/app.log": {"path": "logs/app.log", "managed": False, "protected": True},
    }

    assert build_delete_entries(manifest, previous_entries) == []


def test_copy_changed_files_populates_missing_hashes_even_when_previous_manifest_matches(tmp_path):
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
    previous_entries = {
        "same.txt": {"sha256": next(e["sha256"] for e in manifest["files"] if e["path"] == "same.txt")},
        "changed.txt": {"sha256": "0" * 64},
    }

    same_digest = next(e["sha256"] for e in manifest["files"] if e["path"] == "same.txt")
    changed_digest = next(e["sha256"] for e in manifest["files"] if e["path"] == "changed.txt")
    copied = copy_changed_files(dist_root, files_root, manifest, previous_entries)

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


def test_build_latest_metadata_uses_unified_windows_artifact():
    latest = build_latest_metadata(
        app_id="wutheringwaves-navigator",
        channel="stable",
        version="0.2.0",
        update_base_url="https://updates.example.com/wuwa/stable/",
        artifact_size=42,
        installer_info=None,
    )

    assert "windows-x64" in latest["artifacts"]
    assert "windows-x64-portable" not in latest["artifacts"]
    assert latest["release_url"] == "https://updates.example.com/wuwa/stable/releases/0.2.0/release.json"
    artifact = latest["artifacts"]["windows-x64"]
    assert artifact["update_mode"] == "file"
    assert artifact["manifest_url"] == "https://updates.example.com/wuwa/stable/releases/0.2.0/manifest.json"
    assert artifact["size"] == 42
    assert "full_zip_url" not in artifact
    assert "full_zip_sha256" not in artifact


def test_build_latest_metadata_preserves_installer_artifact():
    installer_info = {
        "version": "0.2.0",
        "update_mode": "installer",
        "installer_url": "https://updates.example.com/wuwa/stable/releases/0.2.0/installer/setup.exe",
        "installer_sha256": "c" * 64,
        "size": 123,
    }

    latest = build_latest_metadata(
        app_id="wutheringwaves-navigator",
        channel="stable",
        version="0.2.0",
        update_base_url="https://updates.example.com/wuwa/stable",
        artifact_size=42,
        installer_info=installer_info,
    )

    assert latest["artifacts"]["windows-x64-installer"] == installer_info


def test_create_portable_zip_matches_manifest_relative_paths(tmp_path):
    dist_root = tmp_path / "WutheringWaves-Navigator-Smart"
    internal = dist_root / "_internal" / "js"
    internal.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
    (internal / "wuwa_map_optimizer.js").write_text("console.log('ok')", encoding="utf-8")

    zip_path = tmp_path / "release" / "portable.zip"
    create_portable_zip(dist_root, zip_path)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "WutheringWaves-Navigator-Smart.exe" in names
    assert "_internal/js/wuwa_map_optimizer.js" in names
    assert "WutheringWaves-Navigator-Smart/WutheringWaves-Navigator-Smart.exe" not in names


def test_build_latest_metadata_requires_update_base_url():
    with pytest.raises(ValueError, match="update_base_url"):
        build_latest_metadata(
            app_id="wutheringwaves-navigator",
            channel="stable",
            version="0.2.0",
            update_base_url="",
            artifact_size=42,
            installer_info=None,
        )


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

    packaged = json.loads(version_path.read_text(encoding="utf-8"))
    assert packaged["update_base_url"] == "https://updates.example.com/wuwa/stable/latest.json"


def test_make_release_uses_cli_update_base_url(tmp_path, monkeypatch):
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
    artifact = latest["artifacts"]["windows-x64"]
    assert artifact["manifest_url"] == "https://updates.example.com/wuwa/stable/releases/0.2.0/manifest.json"
    packaged_version = json.loads((dist_root / "version.json").read_text(encoding="utf-8"))
    assert packaged_version["update_base_url"] == "https://updates.example.com/wuwa/stable/latest.json"


def test_make_release_writes_release_notes_to_latest_and_release(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    dist_root = project_root / "dist" / "WutheringWaves-Navigator-Smart"
    dist_root.mkdir(parents=True)
    (dist_root / "WutheringWaves-Navigator-Smart.exe").write_bytes(b"exe")
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
