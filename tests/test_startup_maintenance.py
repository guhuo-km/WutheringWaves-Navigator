from src.core.startup_maintenance import (
    refresh_root_updater,
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


def test_refresh_root_updater_copies_internal_updater_when_sizes_differ(tmp_path):
    internal = tmp_path / "_internal" / "WutheringWaves-Updater.exe"
    root_updater = tmp_path / "WutheringWaves-Updater.exe"
    internal.parent.mkdir(parents=True)
    internal.write_bytes(b"new-updater")
    root_updater.write_bytes(b"old")

    assert refresh_root_updater(tmp_path) is True

    assert root_updater.read_bytes() == b"new-updater"


def test_run_startup_maintenance_reports_actions(tmp_path):
    debug_pak = tmp_path / "_internal" / "PySide6" / "resources" / "qtwebengine_devtools_resources.debug.pak"
    internal = tmp_path / "_internal" / "WutheringWaves-Updater.exe"
    root_updater = tmp_path / "WutheringWaves-Updater.exe"
    debug_pak.parent.mkdir(parents=True)
    internal.parent.mkdir(parents=True, exist_ok=True)
    debug_pak.write_bytes(b"debug")
    internal.write_bytes(b"new-updater")
    root_updater.write_bytes(b"old")

    result = run_startup_maintenance(tmp_path)

    assert len(result["removed"]) == 1
    assert result["updater_refreshed"] is True
