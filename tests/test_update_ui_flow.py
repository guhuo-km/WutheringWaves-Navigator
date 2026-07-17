import json
import re
from datetime import datetime
from pathlib import Path
from types import MethodType

import src.ui.main_window as main_window_module
from src.core.update_provider import UpdateResult
from src.ui.main_window import MainWindow, build_updater_command


def test_main_window_uses_bootstrap_capable_update_artifact():
    assert MainWindow._get_update_artifact_key(None) == "windows-x64-v2"


def test_updater_bootstrap_ui_text_uses_translation_resources():
    source_path = Path(main_window_module.__file__).resolve()
    source = source_path.read_text(encoding="utf-8")
    language_root = source_path.parents[2] / "languages"
    zh = json.loads((language_root / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((language_root / "en_US.json").read_text(encoding="utf-8"))
    keys = {
        "update_auto_unavailable_title",
        "update_apply_unavailable_title",
        "update_updater_metadata_incomplete",
    "update_updater_prepare_duplicate",
    "update_updater_preparing",
    "update_updater_prepare_title",
    "update_updater_prepare_detail",
    "update_updater_prepare_failed",
        "update_updater_update_failed",
        "update_updater_updated",
    "update_updater_already_current",
    "update_updater_close_failed",
    }

    for key in keys:
        assert re.search(rf'tr\(\s*"{re.escape(key)}"', source), key
        assert key in zh
        assert key in en


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


def test_start_file_update_prepares_verified_updater_before_launch(monkeypatch, tmp_path):
    events = []

    class ImmediateExecutor:
        def submit(self, function, *args):
            function(*args)

    class AppState:
        def append_system_log(self, message, level):
            events.append(("log", level, message))

    class FinishedSignal:
        def __init__(self, owner):
            self.owner = owner

        def emit(self, result, error_message, replaced):
            self.owner._on_updater_prepare_finished(result, error_message, replaced)

    class FakeWindow:
        pass

    window = FakeWindow()
    window._updater_prepare_in_progress = False
    window._update_check_executor = ImmediateExecutor()
    window._app_state = AppState()
    window._show_updater_prepare_dialog = lambda: None
    window._close_updater_prepare_dialog = lambda: None
    window._app_root_for_update = lambda: tmp_path
    window._update_apply_lock_path = lambda: tmp_path / ".update" / "apply.lock"
    window._updater_exe_path = lambda: tmp_path / "WutheringWaves-Updater.exe"
    window._run_updater_prepare_thread = MethodType(MainWindow._run_updater_prepare_thread, window)
    window._on_updater_prepare_finished = MethodType(MainWindow._on_updater_prepare_finished, window)
    window._launch_file_updater = lambda result: events.append(("launch", result.latest_version))
    window._updater_prepare_finished = FinishedSignal(window)

    def fake_prepare(**kwargs):
        events.append(("prepare", kwargs["updater_sha256"]))
        return True

    monkeypatch.setattr(main_window_module, "prepare_updater_binary", fake_prepare)
    monkeypatch.setattr(main_window_module.sys, "frozen", True, raising=False)

    result = UpdateResult(
        has_update=True,
        current_version="0.1.4",
        latest_version="0.1.5",
        release_notes="",
        download_url="",
        checked_at=datetime(2026, 5, 23, 0, 0),
        update_mode="file",
        manifest_url="https://updates.example.com/release/manifest.json",
        updater_url="https://updates.example.com/files/updater",
        updater_sha256="a" * 64,
    )

    MainWindow._start_file_update(window, result)

    assert events.index(("prepare", "a" * 64)) < events.index(("launch", "0.1.5"))
