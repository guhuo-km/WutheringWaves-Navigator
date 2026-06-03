import pytest

from src.core.update_manifest import ManifestFileEntry, ReleaseManifest, resolve_manifest_path


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
        "",
    ],
)
def test_resolve_manifest_path_rejects_unsafe_paths(tmp_path, unsafe_path):
    with pytest.raises(ValueError):
        resolve_manifest_path(tmp_path, unsafe_path)


def test_resolve_manifest_path_accepts_relative_path(tmp_path):
    result = resolve_manifest_path(tmp_path, "_internal/js/a.js")

    assert result == tmp_path / "_internal" / "js" / "a.js"
