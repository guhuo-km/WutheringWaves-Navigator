import pytest
import subprocess
import sys
from pathlib import Path

from src.updater_app import (
    UPDATER_UI_BACKEND,
    parse_update_args,
    run_update_flow,
    updater_stage_label,
)
from src.core.update_lock import (
    update_in_progress_message,
    is_update_in_progress,
    update_lock,
    update_lock_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_updater_uses_tkinter_ui_backend():
    assert UPDATER_UI_BACKEND == "tkinter"


def test_updater_import_does_not_require_pyside6():
    script = r"""
import builtins
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

real_import = builtins.__import__

def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "PySide6" or name.startswith("PySide6."):
        raise ModuleNotFoundError("No module named 'PySide6'")
    return real_import(name, globals, locals, fromlist, level)

module = None
builtins.__import__ = blocked_import
module = importlib.import_module("updater_app")
assert module.UPDATER_UI_BACKEND == "tkinter"
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_update_lock_path_lives_under_app_update_dir(tmp_path):
    assert update_lock_path(tmp_path) == tmp_path / ".update" / "apply.lock"


def test_update_lock_rejects_concurrent_updater(tmp_path):
    with update_lock(tmp_path):
        with pytest.raises(RuntimeError, match="another updater"):
            with update_lock(tmp_path):
                pass


def test_parse_update_args_accepts_download_metadata(tmp_path):
    args = parse_update_args(
        [
            "--app-root",
            str(tmp_path),
            "--main-exe",
            "WutheringWaves-Navigator-Smart.exe",
            "--version",
            "0.1.5",
            "--manifest-url",
            "https://updates.example.com/manifest.json",
            "--full-zip-url",
            "https://updates.example.com/update.zip",
            "--full-zip-sha256",
            "a" * 64,
        ]
    )

    assert args.version == "0.1.5"
    assert args.manifest_url.endswith("manifest.json")
    assert args.full_zip_sha256 == "a" * 64


def test_updater_stage_labels_do_not_expose_file_names():
    assert updater_stage_label("download") == "正在下载更新文件..."
    assert updater_stage_label("verify") == "正在校验更新文件..."
    assert updater_stage_label("apply") == "正在应用更新..."
    assert "base_library.zip" not in updater_stage_label("download")


def test_run_update_flow_reports_coarse_stages(tmp_path):
    manifest_path = tmp_path / "staging" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        '{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.1.5","channel":"stable","files":[],"delete":[]}',
        encoding="utf-8",
    )

    class Staged:
        pass

    staged_update = Staged()
    staged_update.staging_root = manifest_path.parent
    staged_update.manifest_path = manifest_path

    events = []

    def fake_stage(**kwargs):
        kwargs["progress_callback"](20, 100)
        return staged_update

    def fake_apply(app_root, staging_root, manifest):
        events.append(("fake_apply", 0))

    args = parse_update_args(
        [
            "--app-root",
            str(tmp_path),
            "--main-exe",
            "app.exe",
            "--version",
            "0.1.5",
            "--manifest-url",
            "https://updates.example.com/manifest.json",
            "--full-zip-url",
            "https://updates.example.com/update.zip",
        ]
    )

    run_update_flow(
        args,
        progress_callback=lambda stage, percent: events.append((stage, percent)),
        stage_update=fake_stage,
        apply_update=fake_apply,
        wait_for_exit=lambda pid, timeout: True,
    )

    assert ("download", 0) in events
    assert ("download", 14) in events
    assert ("verify", 70) in events
    assert ("apply", 75) in events
    assert ("complete", 100) in events


def test_is_update_in_progress_reads_apply_lock(tmp_path):
    assert is_update_in_progress(tmp_path) is False
    update_lock_path(tmp_path).parent.mkdir(parents=True)
    update_lock_path(tmp_path).write_text("123", encoding="ascii")

    assert is_update_in_progress(tmp_path) is True


def test_update_in_progress_message_is_user_facing():
    message = update_in_progress_message()

    assert "正在应用更新" in message
    assert "apply.lock" not in message
