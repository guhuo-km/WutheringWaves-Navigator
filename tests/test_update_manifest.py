from dataclasses import replace

import pytest

from src.core.update_manifest import (
    ManifestFileEntry,
    ReleaseManifest,
    is_preserved_update_path,
    resolve_manifest_path,
    validate_release_manifest,
)


def test_manifest_entry_tracks_managed_and_protected_flags():
    entry = ManifestFileEntry(
        path="_internal/js/wuwa_map_optimizer.js",
        size=12,
        sha256="a" * 64,
        url="portable/files/_internal/js/wuwa_map_optimizer.js",
        managed=True,
        protected=False,
    )

    assert entry.path == "_internal/js/wuwa_map_optimizer.js"
    assert entry.managed is True
    assert entry.protected is False


def test_release_manifest_from_dict_keeps_files():
    manifest = ReleaseManifest.from_dict(
        {
            "schema": 1,
            "app_id": "wutheringwaves-navigator",
            "version": "1.0.1",
            "channel": "stable",
            "files": [
                {
                    "path": "WutheringWaves-Navigator-Smart.exe",
                    "size": 5,
                    "sha256": "b" * 64,
                    "url": "portable/files/WutheringWaves-Navigator-Smart.exe",
                    "managed": True,
                    "protected": False,
                }
            ],
            "delete": [],
        }
    )

    assert manifest.version == "1.0.1"
    assert manifest.files[0].path == "WutheringWaves-Navigator-Smart.exe"


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.txt",
        "/absolute/path.txt",
        "C:/Windows/system32/file.dll",
        "C:\\Windows\\system32\\file.dll",
        "safe/../../outside.txt",
        "safe//file.dll",
        "safe\\\\file.dll",
        "WutheringWaves-Updater.exe::$DATA",
        "config/app_settings.json ",
        "config/app_settings.json.",
        "",
    ],
)
def test_resolve_manifest_path_rejects_unsafe_paths(tmp_path, unsafe_path):
    with pytest.raises(ValueError):
        resolve_manifest_path(tmp_path, unsafe_path)


def test_resolve_manifest_path_accepts_relative_path(tmp_path):
    result = resolve_manifest_path(tmp_path, "_internal/js/a.js")

    assert result == tmp_path / "_internal" / "js" / "a.js"


@pytest.mark.parametrize(
    "path",
    [
        "config/app_settings.json",
        "logs/runtime.log",
        "recorded_routes/route.json",
        "tiles/local/0.png",
        "images/local.png",
        "downloads/route.json",
        "debug/minimap/frame.png",
        "cache/web_profile/Cookies",
        "cache/general-cache.bin",
        "cache/minimap_tiles/906/indexes/minimap_index.sqlite3",
        ".update/staging/0.2.0/manifest.json",
        "WutheringWaves-Updater.exe",
        "Uninstall.exe",
        "app_settings.json",
        "src/ocr_config.json",
        "_internal/calibration_data.json",
        "src/recorded_routes/route.json",
        "_internal/tiles/local/0.png",
        "_internal/images/local.png",
        "ocr_logs.json",
        "src/ocr_logs.json",
        "_internal/ocr_logs.json",
    ],
)
def test_is_preserved_update_path_keeps_real_runtime_and_installer_data(path):
    assert is_preserved_update_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "WutheringWaves-Navigator-Smart.exe",
        "_internal/python312.dll",
        "README.txt",
    ],
)
def test_is_preserved_update_path_does_not_exempt_program_content(path):
    assert is_preserved_update_path(path) is False


def valid_program_manifest() -> ReleaseManifest:
    return ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="0.2.0",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="WutheringWaves-Navigator-Smart.exe",
                size=3,
                sha256="a" * 64,
                url="https://updates.example.com/files/app",
                managed=True,
                protected=False,
            ),
            ManifestFileEntry(
                path="_internal/version.json",
                size=3,
                sha256="b" * 64,
                url="https://updates.example.com/files/version",
                managed=True,
                protected=False,
            ),
        ],
        delete=[],
    )


def test_validate_release_manifest_accepts_expected_program_snapshot():
    validate_release_manifest(
        valid_program_manifest(),
        expected_version="0.2.0",
        required_managed_paths={
            "WutheringWaves-Navigator-Smart.exe",
            "_internal/version.json",
        },
    )


@pytest.mark.parametrize(
    "entry",
    [
        ManifestFileEntry(
            path="config/app_settings.json",
            size=3,
            sha256="c" * 64,
            url="https://updates.example.com/files/config",
            managed=True,
            protected=False,
        ),
        ManifestFileEntry(
            path="_internal/python312.dll",
            size=0,
            sha256="",
            url="",
            managed=False,
            protected=True,
        ),
    ],
)
def test_validate_release_manifest_rejects_remote_path_classification(entry):
    manifest = valid_program_manifest()
    manifest.files.append(entry)

    with pytest.raises(ValueError, match="path classification"):
        validate_release_manifest(
            manifest,
            expected_version="0.2.0",
            required_managed_paths={
                "WutheringWaves-Navigator-Smart.exe",
                "_internal/version.json",
            },
        )


def test_validate_release_manifest_rejects_managed_minimap_cache_entry():
    manifest = valid_program_manifest()
    manifest.files.append(
        ManifestFileEntry(
            path="cache/minimap_tiles/906/indexes/minimap_index.sqlite3",
            size=3,
            sha256="c" * 64,
            url="https://updates.example.com/files/minimap-index",
            managed=True,
            protected=False,
        )
    )

    with pytest.raises(ValueError, match="path classification"):
        validate_release_manifest(
            manifest,
            expected_version="0.2.0",
            required_managed_paths={
                "WutheringWaves-Navigator-Smart.exe",
                "_internal/version.json",
            },
        )


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///tmp/update.bin",
        "https://",
        "https://updates.example.com:notaport/file",
        "https://updates.example.com:99999/file",
        "not a url",
    ],
)
def test_validate_release_manifest_rejects_invalid_managed_file_urls(bad_url):
    manifest = valid_program_manifest()
    manifest.files[0] = replace(manifest.files[0], url=bad_url)

    with pytest.raises(ValueError, match="URL"):
        validate_release_manifest(
            manifest,
            expected_version="0.2.0",
            required_managed_paths={
                "WutheringWaves-Navigator-Smart.exe",
                "_internal/version.json",
            },
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda manifest: object.__setattr__(manifest, "app_id", "wrong-app"), "app_id"),
        (lambda manifest: object.__setattr__(manifest, "version", "0.1.0"), "version"),
        (lambda manifest: manifest.files.clear(), "required managed files"),
        (
            lambda manifest: manifest.files.append(
                ManifestFileEntry(
                    path="_INTERNAL/VERSION.JSON",
                    size=3,
                    sha256="c" * 64,
                    url="https://updates.example.com/files/duplicate",
                    managed=True,
                    protected=False,
                )
            ),
            "duplicate manifest path",
        ),
    ],
)
def test_validate_release_manifest_rejects_unsafe_authoritative_snapshots(mutate, message):
    manifest = valid_program_manifest()
    mutate(manifest)

    with pytest.raises(ValueError, match=message):
        validate_release_manifest(
            manifest,
            expected_version="0.2.0",
            required_managed_paths={
                "WutheringWaves-Navigator-Smart.exe",
                "_internal/version.json",
            },
        )
