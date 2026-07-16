import hashlib
import shutil
from pathlib import Path

import pytest

import src.core.file_updater as file_updater_module
from src.core.file_updater import apply_staged_update, sha256_file
from src.core.update_manifest import ManifestFileEntry, ReleaseManifest


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def test_apply_staged_update_accepts_uppercase_sha256(tmp_path):
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
                sha256=digest(b"new").upper(),
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


def test_apply_staged_update_removes_unlisted_program_file_without_delete_entry(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    obsolete = app_root / "_internal" / "obsolete.dll"
    obsolete.parent.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    obsolete.write_bytes(b"obsolete")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert not obsolete.exists()


def test_apply_staged_update_handles_old_file_replaced_by_new_directory_tree(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    old_parent_file = app_root / "_internal" / "package"
    new_child = staging_root / "_internal" / "package" / "module.py"
    old_parent_file.parent.mkdir(parents=True)
    new_child.parent.mkdir(parents=True)
    old_parent_file.write_bytes(b"old-file")
    new_child.write_bytes(b"new-module")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/package/module.py",
                size=10,
                sha256=digest(b"new-module"),
                url="portable/files/module.py",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert (app_root / "_internal" / "package" / "module.py").read_bytes() == b"new-module"


def test_apply_staged_update_preserves_minimap_cache_while_cleaning_stale_program_files(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    tile = app_root / "cache" / "minimap_tiles" / "906" / "current.png"
    index = app_root / "cache" / "minimap_tiles" / "906" / "indexes" / "minimap_index.sqlite3"
    program_file = app_root / "_internal" / "app.dll"
    staged_program_file = staging_root / "_internal" / "app.dll"
    for path in (tile, index, program_file, staged_program_file):
        path.parent.mkdir(parents=True, exist_ok=True)
    tile.write_bytes(b"user-tile")
    index.write_bytes(b"user-index")
    program_file.write_bytes(b"old")
    staged_program_file.write_bytes(b"new")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert program_file.read_bytes() == b"new"
    assert tile.read_bytes() == b"user-tile"
    assert index.read_bytes() == b"user-index"


def test_apply_staged_update_does_not_replace_preserved_minimap_cache_manifest_entry(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    cache_file = app_root / "cache" / "minimap_tiles" / "906" / "current.png"
    program_file = app_root / "_internal" / "app.dll"
    staged_cache_file = staging_root / "cache" / "minimap_tiles" / "906" / "current.png"
    staged_program_file = staging_root / "_internal" / "app.dll"
    for path in (cache_file, program_file, staged_cache_file, staged_program_file):
        path.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"user-cache")
    program_file.write_bytes(b"old")
    staged_cache_file.write_bytes(b"remote-cache")
    staged_program_file.write_bytes(b"new")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            ),
            ManifestFileEntry(
                path="cache/minimap_tiles/906/current.png",
                size=12,
                sha256=digest(b"remote-cache"),
                url="portable/files/current.png",
                managed=False,
                protected=True,
            ),
        ],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert program_file.read_bytes() == b"new"
    assert cache_file.read_bytes() == b"user-cache"
    assert staged_cache_file.read_bytes() == b"remote-cache"


def test_apply_staged_update_preserves_current_user_data_paths(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    preserved = [
        app_root / "config" / "app_settings.json",
        app_root / "recorded_routes" / "route.json",
        app_root / "tiles" / "local" / "0.png",
        app_root / "images" / "local.png",
        app_root / "logs" / "runtime.log",
        app_root / "downloads" / "route.json",
        app_root / "debug" / "frame.png",
        app_root / "cache" / "web_profile" / "Cookies",
        app_root / "cache" / "general-cache.bin",
        app_root / "Uninstall.exe",
    ]
    for path in preserved:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"keep")
    staging_root.mkdir(parents=True)

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert all(path.read_bytes() == b"keep" for path in preserved)


def test_apply_staged_update_migrates_known_legacy_user_data_before_cleanup(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    legacy_settings = app_root / "app_settings.json"
    legacy_route = app_root / "_internal" / "recorded_routes" / "route.json"
    legacy_tile = app_root / "src" / "tiles" / "local" / "0.png"
    legacy_settings.parent.mkdir(parents=True)
    legacy_route.parent.mkdir(parents=True)
    legacy_tile.parent.mkdir(parents=True)
    legacy_settings.write_text('{"theme":"dark"}', encoding="utf-8")
    legacy_route.write_text('{"name":"route"}', encoding="utf-8")
    legacy_tile.write_bytes(b"tile")
    staging_root.mkdir(parents=True)

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert (app_root / "config" / "app_settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    assert (app_root / "recorded_routes" / "route.json").read_text(encoding="utf-8") == '{"name":"route"}'
    assert (app_root / "tiles" / "local" / "0.png").read_bytes() == b"tile"
    assert not legacy_settings.exists()
    assert not legacy_route.exists()
    assert not legacy_tile.exists()


def test_apply_staged_update_migrates_legacy_root_config_file(tmp_path):
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

    assert not target.exists()
    assert (app_root / "config" / "ocr_config.json").read_text(encoding="utf-8") == "{}"


def test_apply_staged_update_migrates_legacy_ocr_log(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    legacy_log = app_root / "_internal" / "ocr_logs.json"
    legacy_log.parent.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    legacy_log.write_text('[{"message":"legacy"}]', encoding="utf-8")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert not legacy_log.exists()
    assert (app_root / "logs" / "ocr_logs.json").read_text(encoding="utf-8") == '[{"message":"legacy"}]'


def test_apply_staged_update_preserves_conflicting_legacy_user_data(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    current_settings = app_root / "config" / "app_settings.json"
    legacy_settings = app_root / "app_settings.json"
    current_route = app_root / "recorded_routes" / "route.json"
    legacy_route = app_root / "_internal" / "recorded_routes" / "route.json"

    for path in (current_settings, legacy_settings, current_route, legacy_route):
        path.parent.mkdir(parents=True, exist_ok=True)
    current_settings.write_text('{"source":"current"}', encoding="utf-8")
    legacy_settings.write_text('{"source":"legacy"}', encoding="utf-8")
    current_route.write_text('{"route":"current"}', encoding="utf-8")
    legacy_route.write_text('{"route":"legacy"}', encoding="utf-8")
    staging_root.mkdir(parents=True)

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=[],
    )

    apply_staged_update(app_root, staging_root, manifest)

    assert current_settings.read_text(encoding="utf-8") == '{"source":"current"}'
    assert (app_root / "config" / "legacy" / "root" / "app_settings.json").read_text(
        encoding="utf-8"
    ) == '{"source":"legacy"}'
    assert current_route.read_text(encoding="utf-8") == '{"route":"current"}'
    assert (app_root / "recorded_routes" / "legacy-internal" / "route.json").read_text(
        encoding="utf-8"
    ) == '{"route":"legacy"}'


def test_failed_program_transaction_keeps_legacy_data_in_its_original_location(
    tmp_path,
    monkeypatch,
):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    legacy_route = app_root / "_internal" / "recorded_routes" / "route.json"
    target = app_root / "_internal" / "app.dll"
    staged = staging_root / "_internal" / "app.dll"
    legacy_route.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    legacy_route.write_text('{"route":"legacy"}', encoding="utf-8")
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )
    original_replace = Path.replace

    def fail_program_replace(path, destination):
        if path == staged and Path(destination) == target:
            raise OSError("apply failed")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_program_replace)

    with pytest.raises(OSError, match="apply failed"):
        apply_staged_update(app_root, staging_root, manifest)

    assert legacy_route.read_text(encoding="utf-8") == '{"route":"legacy"}'
    assert not (app_root / "recorded_routes" / "route.json").exists()


def test_apply_staged_update_keeps_rollback_backup_when_restore_fails(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "_internal" / "app.dll"
    staged = staging_root / "_internal" / "app.dll"
    target.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    staged.write_bytes(b"new")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    original_replace = Path.replace

    def fail_backup_restore(path, destination):
        if path == staged and Path(destination) == target:
            raise OSError("apply failed")
        if ".rollback" in path.parts and Path(destination) == target:
            raise PermissionError("target remains locked")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_backup_restore)

    with pytest.raises(RuntimeError, match="rollback incomplete"):
        apply_staged_update(app_root, staging_root, manifest)

    backup = staging_root / ".rollback" / "replaced" / "_internal" / "app.dll"
    assert backup.read_bytes() == b"old"
    assert not target.exists()


def test_recover_interrupted_update_restores_replaced_file(tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    app_root = tmp_path / "app"
    staging_root = app_root / ".update" / "staging" / "1.0.2"
    rollback_root = staging_root / ".rollback"
    target = app_root / "_internal" / "app.dll"
    staged = staging_root / "_internal" / "app.dll"
    target.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )
    original_replace = Path.replace

    def replace_then_exit(path, destination):
        result = original_replace(path, destination)
        if path == target or Path(destination) == target:
            raise SimulatedProcessExit
        return result

    monkeypatch.setattr(Path, "replace", replace_then_exit)

    with pytest.raises(SimulatedProcessExit):
        apply_staged_update(app_root, staging_root, manifest)

    monkeypatch.setattr(Path, "replace", original_replace)
    recover = getattr(file_updater_module, "recover_interrupted_updates", None)
    assert callable(recover)
    recover(app_root)

    assert target.read_bytes() == b"old"
    assert not rollback_root.exists()


def test_recover_interrupted_update_removes_new_file(tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    app_root = tmp_path / "app"
    staging_root = app_root / ".update" / "staging" / "1.0.2"
    rollback_root = staging_root / ".rollback"
    target = app_root / "_internal" / "new.dll"
    staged = staging_root / "_internal" / "new.dll"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"new")
    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/new.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/new.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )
    original_copy = shutil.copy2
    original_replace = Path.replace

    def copy_then_exit(source, destination, *args, **kwargs):
        result = original_copy(source, destination, *args, **kwargs)
        if Path(destination) == target:
            raise SimulatedProcessExit
        return result

    def replace_then_exit(path, destination):
        result = original_replace(path, destination)
        if Path(destination) == target:
            raise SimulatedProcessExit
        return result

    monkeypatch.setattr(shutil, "copy2", copy_then_exit)
    monkeypatch.setattr(Path, "replace", replace_then_exit)

    with pytest.raises(SimulatedProcessExit):
        apply_staged_update(app_root, staging_root, manifest)

    monkeypatch.setattr(Path, "replace", original_replace)
    monkeypatch.setattr(shutil, "copy2", original_copy)
    recover = getattr(file_updater_module, "recover_interrupted_updates", None)
    assert callable(recover)
    recover(app_root)

    assert not target.exists()
    assert not rollback_root.exists()


def test_recover_committed_update_keeps_new_tree_and_finishes_migration(
    tmp_path,
    monkeypatch,
):
    class SimulatedProcessExit(BaseException):
        pass

    app_root = tmp_path / "app"
    staging_root = app_root / ".update" / "staging" / "1.0.2"
    rollback_root = staging_root / ".rollback"
    legacy_settings = app_root / "app_settings.json"
    target = app_root / "_internal" / "app.dll"
    staged = staging_root / "_internal" / "app.dll"
    legacy_settings.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    legacy_settings.write_text('{"legacy":true}', encoding="utf-8")
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )
    original_migrate = file_updater_module.migrate_legacy_user_data

    def exit_before_migration(_app_root):
        raise SimulatedProcessExit

    monkeypatch.setattr(
        file_updater_module,
        "migrate_legacy_user_data",
        exit_before_migration,
    )

    with pytest.raises(SimulatedProcessExit):
        apply_staged_update(app_root, staging_root, manifest)

    assert rollback_root.exists()
    monkeypatch.setattr(
        file_updater_module,
        "migrate_legacy_user_data",
        original_migrate,
    )
    file_updater_module.recover_interrupted_updates(app_root)

    assert target.read_bytes() == b"new"
    assert not legacy_settings.exists()
    assert (app_root / "config" / "app_settings.json").read_text(
        encoding="utf-8"
    ) == '{"legacy":true}'
    assert not rollback_root.exists()


def test_recover_interrupted_update_discards_temp_only_unpublished_journal(tmp_path):
    app_root = tmp_path / "app"
    rollback_root = app_root / ".update" / "staging" / "1.0.2" / ".rollback"
    rollback_root.mkdir(parents=True)
    (rollback_root / "journal.json.tmp").write_text("partial", encoding="utf-8")

    file_updater_module.recover_interrupted_updates(app_root)

    assert not rollback_root.exists()


def test_recover_interrupted_update_preserves_evidence_without_published_journal(
    tmp_path,
):
    app_root = tmp_path / "app"
    rollback_root = app_root / ".update" / "staging" / "1.0.2" / ".rollback"
    backup = rollback_root / "replaced" / "_internal" / "app.dll"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"old")

    with pytest.raises(RuntimeError, match="rollback journal is missing"):
        file_updater_module.recover_interrupted_updates(app_root)

    assert backup.read_bytes() == b"old"


def test_committed_cleanup_keeps_journal_when_backup_cleanup_fails(
    tmp_path,
    monkeypatch,
):
    app_root = tmp_path / "app"
    staging_root = app_root / ".update" / "staging" / "1.0.2"
    rollback_root = staging_root / ".rollback"
    file_updater_module._write_rollback_journal(
        rollback_root,
        created=[],
        replaced=["_internal/app.dll"],
        stale=[],
    )
    backup = rollback_root / "replaced" / "_internal" / "app.dll"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"old")
    file_updater_module._mark_rollback_committed(rollback_root)
    original_remove = file_updater_module._remove_update_path

    def fail_backup_cleanup(path):
        if path == rollback_root / "replaced":
            raise OSError("cleanup interrupted")
        return original_remove(path)

    monkeypatch.setattr(
        file_updater_module,
        "_remove_update_path",
        fail_backup_cleanup,
    )

    with pytest.raises(OSError, match="cleanup interrupted"):
        file_updater_module.recover_interrupted_updates(app_root)

    assert (rollback_root / "journal.json").exists()
    assert backup.read_bytes() == b"old"


def test_apply_staged_update_cleans_unpublished_journal_after_write_error(
    tmp_path,
    monkeypatch,
):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    rollback_root = staging_root / ".rollback"
    target = app_root / "_internal" / "app.dll"
    staged = staging_root / "_internal" / "app.dll"
    target.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/app.dll",
                size=3,
                sha256=digest(b"new"),
                url="portable/files/app.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )
    original_replace = Path.replace

    def fail_journal_publish(path, destination):
        if (
            path == rollback_root / "journal.json.tmp"
            and Path(destination) == rollback_root / "journal.json"
        ):
            raise OSError("journal publish failed")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_journal_publish)

    with pytest.raises(OSError, match="journal publish failed"):
        apply_staged_update(app_root, staging_root, manifest)

    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"
    assert not rollback_root.exists()


def test_apply_staged_update_stops_before_migration_when_previous_rollback_exists(tmp_path):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    legacy_settings = app_root / "app_settings.json"
    rollback_marker = staging_root / ".rollback" / "replaced" / "old.dll"
    legacy_settings.parent.mkdir(parents=True)
    rollback_marker.parent.mkdir(parents=True)
    legacy_settings.write_text('{"legacy":true}', encoding="utf-8")
    rollback_marker.write_bytes(b"backup")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[],
        delete=[],
    )

    with pytest.raises(RuntimeError, match="previous rollback data exists"):
        apply_staged_update(app_root, staging_root, manifest)

    assert legacy_settings.read_text(encoding="utf-8") == '{"legacy":true}'
    assert not (app_root / "config" / "app_settings.json").exists()
    assert rollback_marker.read_bytes() == b"backup"


def test_apply_staged_update_removes_new_file_when_atomic_replace_fails(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    staging_root = tmp_path / "staging"
    target = app_root / "_internal" / "new.dll"
    staged = staging_root / "_internal" / "new.dll"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"complete")

    manifest = ReleaseManifest(
        schema=1,
        app_id="wutheringwaves-navigator",
        version="1.0.2",
        channel="stable",
        files=[
            ManifestFileEntry(
                path="_internal/new.dll",
                size=8,
                sha256=digest(b"complete"),
                url="portable/files/new.dll",
                managed=True,
                protected=False,
            )
        ],
        delete=[],
    )

    original_replace = Path.replace

    def fail_atomic_replace(path, destination):
        if path == staged and Path(destination) == target:
            raise OSError("replace interrupted")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_atomic_replace)

    with pytest.raises(OSError, match="replace interrupted"):
        apply_staged_update(app_root, staging_root, manifest)

    assert not target.exists()
