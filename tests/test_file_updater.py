import hashlib

import pytest

from src.core.file_updater import apply_staged_update, build_update_plan, sha256_file
from src.core.update_manifest import ManifestFileEntry, ReleaseManifest


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_build_update_plan_skips_current_and_protected_files(tmp_path):
    current = tmp_path / "_internal" / "js" / "same.js"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"same")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/js/same.js",
                size=4,
                sha256=digest(b"same"),
                url="portable/files/_internal/js/same.js",
                managed=True,
                protected=False,
            ),
            ManifestFileEntry(
                path="logs/app.log",
                size=3,
                sha256=digest(b"log"),
                url="portable/files/logs/app.log",
                managed=False,
                protected=True,
            ),
            ManifestFileEntry(
                path="_internal/js/changed.js",
                size=7,
                sha256=digest(b"changed"),
                url="portable/files/_internal/js/changed.js",
                managed=True,
                protected=False,
            ),
        ],
        delete=[],
    )

    plan = build_update_plan(tmp_path, manifest)

    assert [item.entry.path for item in plan.items] == ["_internal/js/changed.js"]


def test_sha256_file_hashes_content(tmp_path):
    target = tmp_path / "file.bin"
    target.write_bytes(b"abc")

    assert sha256_file(target) == digest(b"abc")


def test_apply_staged_update_replaces_managed_file(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "_internal" / "js" / "a.js"
    staged = staging_root / "_internal" / "js" / "a.js"
    target.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    staged.write_text("new", encoding="utf-8")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/js/a.js",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/_internal/js/a.js",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert target.read_text(encoding="utf-8") == "new"


def test_apply_staged_update_fails_when_required_staged_file_missing(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "_internal" / "js" / "a.js"
    target.parent.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/js/a.js",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/_internal/js/a.js",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    with pytest.raises(FileNotFoundError):
        apply_staged_update(app_root, staging_root, manifest)

    assert target.read_text(encoding="utf-8") == "old"


def test_apply_staged_update_does_not_replace_any_file_before_full_staging_validation(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    first = app_root / "_internal" / "base_library.zip"
    second = app_root / "_internal" / "requests.py"
    staged_first = staging_root / "_internal" / "base_library.zip"
    first.parent.mkdir(parents=True)
    staged_first.parent.mkdir(parents=True)
    first.write_bytes(b"old-base")
    second.write_bytes(b"old-requests")
    staged_first.write_bytes(b"new-base")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/base_library.zip",
                size=8,
                sha256=digest(b"new-base"),
                url="portable/files/_internal/base_library.zip",
                managed=True,
                protected=False,
            ),
            ManifestFileEntry(
                path="_internal/requests.py",
                size=12,
                sha256=digest(b"new-requests"),
                url="portable/files/_internal/requests.py",
                managed=True,
                protected=False,
            ),
        ],
        delete=[],
    )

    with pytest.raises(FileNotFoundError):
        apply_staged_update(app_root, staging_root, manifest)

    assert first.read_bytes() == b"old-base"
    assert second.read_bytes() == b"old-requests"


def test_apply_staged_update_skips_missing_staged_file_when_target_already_matches(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "_internal" / "js" / "a.js"
    target.parent.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    target.write_text("new", encoding="utf-8")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/js/a.js",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/_internal/js/a.js",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert target.read_text(encoding="utf-8") == "new"


def test_apply_staged_update_deletes_removed_managed_file(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "_internal" / "PySide6" / "resources" / "qtwebengine_devtools_resources.debug.pak"
    target.parent.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    target.write_bytes(b"debug")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=["_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak"],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert not target.exists()


def test_apply_staged_update_does_not_delete_protected_user_file(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "ocr_config.json"
    app_root.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=["ocr_config.json"],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert target.exists()
