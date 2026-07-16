from src.core.startup_maintenance import (
    remove_obsolete_packaged_files,
    run_startup_maintenance,
)


def test_remove_obsolete_packaged_files_deletes_known_slimming_targets(tmp_path):
    debug_pak = tmp_path / "_internal" / "PySide6" / "resources" / "qtwebengine_devtools_resources.debug.pak"
    ffmpeg_dll = tmp_path / "_internal" / "cv2" / "opencv_videoio_ffmpeg4130_64.dll"
    kept_file = tmp_path / "_internal" / "PySide6" / "resources" / "qtwebengine_resources.pak"
    debug_pak.parent.mkdir(parents=True)
    ffmpeg_dll.parent.mkdir(parents=True)
    debug_pak.write_bytes(b"debug")
    ffmpeg_dll.write_bytes(b"ffmpeg")
    kept_file.write_bytes(b"keep")

    removed = remove_obsolete_packaged_files(tmp_path)

    assert sorted(path.name for path in removed) == [
        "opencv_videoio_ffmpeg4130_64.dll",
        "qtwebengine_devtools_resources.debug.pak",
    ]
    assert not debug_pak.exists()
    assert not ffmpeg_dll.exists()
    assert kept_file.exists()


def test_remove_obsolete_packaged_files_deletes_legacy_internal_updater(tmp_path):
    internal = tmp_path / "_internal" / "WutheringWaves-Updater.exe"
    root_updater = tmp_path / "WutheringWaves-Updater.exe"
    internal.parent.mkdir(parents=True)
    internal.write_bytes(b"new-updater")
    root_updater.write_bytes(b"old")

    removed = remove_obsolete_packaged_files(tmp_path)

    assert internal in removed
    assert not internal.exists()
    assert root_updater.read_bytes() == b"old"


def test_run_startup_maintenance_reports_actions(tmp_path):
    debug_pak = tmp_path / "_internal" / "PySide6" / "resources" / "qtwebengine_devtools_resources.debug.pak"
    debug_pak.parent.mkdir(parents=True)
    debug_pak.write_bytes(b"debug")

    result = run_startup_maintenance(tmp_path)

    assert len(result["removed"]) == 1
    assert "updater_refreshed" not in result


def test_run_startup_maintenance_migrates_legacy_user_data_for_full_package_upgrades(tmp_path):
    legacy_settings = tmp_path / "app_settings.json"
    legacy_route = tmp_path / "_internal" / "recorded_routes" / "route.json"
    legacy_log = tmp_path / "src" / "ocr_logs.json"
    legacy_settings.parent.mkdir(parents=True, exist_ok=True)
    legacy_route.parent.mkdir(parents=True, exist_ok=True)
    legacy_log.parent.mkdir(parents=True, exist_ok=True)
    legacy_settings.write_text('{"theme":"dark"}', encoding="utf-8")
    legacy_route.write_text('{"route":1}', encoding="utf-8")
    legacy_log.write_text('[]', encoding="utf-8")

    run_startup_maintenance(tmp_path)

    assert (tmp_path / "config" / "app_settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    assert (tmp_path / "recorded_routes" / "route.json").read_text(encoding="utf-8") == '{"route":1}'
    assert (tmp_path / "logs" / "ocr_logs.json").read_text(encoding="utf-8") == '[]'
