from datetime import datetime

from src.core.update_provider import UpdateResult
from src.ui.main_window import build_updater_command


def test_update_result_defaults_allow_failed_state_rendering():
    result = UpdateResult(
        has_update=False,
        current_version="0.1.0",
        latest_version="0.1.0",
        release_notes="",
        download_url="",
        checked_at=datetime(2026, 5, 20, 0, 0),
        error_message="更新地址未配置",
    )

    assert result.error_message == "更新地址未配置"


def test_build_updater_command_passes_download_metadata(tmp_path):
    updater = tmp_path / "WutheringWaves-Updater.exe"
    app_root = tmp_path / "app"
    result = UpdateResult(
        has_update=True,
        current_version="0.1.4",
        latest_version="0.1.5",
        release_notes="",
        download_url="",
        checked_at=datetime(2026, 5, 23, 0, 0),
        update_mode="file",
        manifest_url="https://updates.example.com/release/manifest.json",
    )

    command = build_updater_command(
        updater_path=updater,
        app_root=app_root,
        main_exe="WutheringWaves-Navigator-Smart.exe",
        result=result,
        wait_pid=1234,
    )

    assert command[0] == str(updater)
    assert "--version" in command
    assert "0.1.5" in command
    assert "--manifest-url" in command
    assert result.manifest_url in command
    assert "--full-zip-url" not in command
    assert "--full-zip-sha256" not in command
    assert "--staging-root" not in command
