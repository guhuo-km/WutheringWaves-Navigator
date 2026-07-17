import builtins
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.updater_app import (
    UPDATER_UI_BACKEND,
    append_update_failure_log,
    parse_update_args,
    run_update_flow,
    updater_stage_label,
    wait_for_process_exit,
    UpdaterWindow,
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


def test_update_lock_recovers_dead_process_lock(tmp_path):
    path = update_lock_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("99999999", encoding="ascii")

    assert is_update_in_progress(tmp_path) is False
    assert not path.exists()

    with update_lock(tmp_path):
        assert path.exists()


def test_update_lock_recovers_reused_pid_with_different_process_start(tmp_path):
    path = update_lock_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"pid": os.getpid(), "process_create_time": 0.0}),
        encoding="ascii",
    )

    assert is_update_in_progress(tmp_path) is False
    assert not path.exists()


@pytest.mark.parametrize(
    "legacy_argument",
    [
        ["--full-zip-url", "https://updates.example.com/update.zip"],
        ["--full-zip-sha256", "a" * 64],
        ["--staging-root", "C:/staging"],
        ["--manifest", "C:/staging/manifest.json"],
        ["--no-restart"],
    ],
)
def test_parse_update_args_rejects_legacy_file_update_inputs(tmp_path, legacy_argument):
    base_arguments = [
        "--app-root",
        str(tmp_path),
        "--main-exe",
        "WutheringWaves-Navigator-Smart.exe",
        "--version",
        "0.1.5",
        "--manifest-url",
        "https://updates.example.com/manifest.json",
    ]

    with pytest.raises(SystemExit):
        parse_update_args(
            [
                *base_arguments,
                *legacy_argument,
            ]
        )


def test_updater_stage_labels_do_not_expose_file_names():
    assert updater_stage_label("download") == "正在下载更新文件..."
    assert updater_stage_label("verify") == "正在校验更新文件..."
    assert updater_stage_label("apply") == "正在应用更新..."
    assert "base_library.zip" not in updater_stage_label("download")


def test_updater_window_cannot_close_while_update_is_running():
    class FakeRoot:
        def __init__(self):
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    class FakeText:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    window = UpdaterWindow.__new__(UpdaterWindow)
    window.root = FakeRoot()
    window.detail_var = FakeText()
    window.detail_var.value = "localized status"
    window._update_running = True

    window._on_close_requested()

    assert window.root.destroyed is False
    assert window.detail_var.value == "localized status"

    window._update_running = False
    window._on_close_requested()
    assert window.root.destroyed is True


def test_updater_worker_is_not_daemonized():
    text = (PROJECT_ROOT / "src" / "updater_app.py").read_text(encoding="utf-8")

    assert "daemon=False" in text
    assert "daemon=True" not in text


def test_updater_window_returns_nonzero_result_after_failure():
    class FakeText:
        def set(self, _value):
            return None

    class FakeButton:
        def configure(self, **_kwargs):
            return None

        def state(self, _states):
            return None

    window = UpdaterWindow.__new__(UpdaterWindow)
    window.stage_var = FakeText()
    window.detail_var = FakeText()
    window.progress_var = FakeText()
    window.cancel_button = FakeButton()
    window._update_running = True
    window._result_code = 0

    window._on_finished(False, "failed")

    assert window._result_code != 0


def test_wait_for_process_exit_fails_closed_when_psutil_is_unavailable(monkeypatch):
    real_import = builtins.__import__

    def fail_psutil_import(name, *args, **kwargs):
        if name == "psutil":
            raise ModuleNotFoundError("psutil unavailable")
        return real_import(name, *args, **kwargs)

    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(builtins, "__import__", fail_psutil_import)
    monkeypatch.setattr("src.updater_app.time.time", lambda: next(times))
    monkeypatch.setattr("src.updater_app.time.sleep", lambda _seconds: None)

    assert wait_for_process_exit(1234, 1) is False


def test_run_update_flow_reports_coarse_stages(tmp_path):
    manifest_path = tmp_path / "staging" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        '{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.1.5","channel":"stable","files":['
        '{"path":"app.exe","size":3,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","url":"https://updates.example.com/files/app","managed":true,"protected":false},'
        '{"path":"_internal/version.json","size":3,"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","url":"https://updates.example.com/files/version","managed":true,"protected":false}'
        '],"delete":[]}',
        encoding="utf-8",
    )

    class Staged:
        pass

    staged_update = Staged()
    staged_update.staging_root = manifest_path.parent
    staged_update.manifest_path = manifest_path

    events = []
    staged_calls = []

    def fake_stage(**kwargs):
        staged_calls.append(kwargs)
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
        ]
    )

    run_update_flow(
        args,
        progress_callback=lambda stage, percent: events.append((stage, percent)),
        stage_update=fake_stage,
        apply_update=fake_apply,
        wait_for_exit=lambda pid, timeout: True,
        recover_updates=lambda app_root: events.append(("recover", Path(app_root))),
    )

    assert events[0] == ("recover", tmp_path)
    assert ("download", 0) in events
    assert ("download", 14) in events
    assert ("verify", 70) in events
    assert ("apply", 75) in events
    assert ("complete", 100) in events
    assert "full_zip_url" not in staged_calls[0]
    assert "full_zip_sha256" not in staged_calls[0]


def test_run_update_flow_rejects_empty_manifest_before_apply(tmp_path):
    manifest_path = tmp_path / "staging" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        '{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.1.5","channel":"stable","files":[],"delete":[]}',
        encoding="utf-8",
    )

    class Staged:
        pass

    staged = Staged()
    staged.staging_root = manifest_path.parent
    staged.manifest_path = manifest_path

    applied = []
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
        ]
    )

    with pytest.raises(ValueError, match="required managed files"):
        run_update_flow(
            args,
            progress_callback=lambda *_args: None,
            stage_update=lambda **_kwargs: staged,
            apply_update=lambda *_args: applied.append(True),
            wait_for_exit=lambda *_args: True,
        )

    assert applied == []


def test_is_update_in_progress_reads_apply_lock(tmp_path):
    assert is_update_in_progress(tmp_path) is False
    update_lock_path(tmp_path).parent.mkdir(parents=True)
    update_lock_path(tmp_path).write_text(str(os.getpid()), encoding="ascii")

    assert is_update_in_progress(tmp_path) is True


def test_update_in_progress_message_is_user_facing():
    message = update_in_progress_message()

    assert "正在应用更新" in message
    assert "apply.lock" not in message


def test_updater_failure_records_reason_and_releases_lock(tmp_path):
    """Known issue: failed updates need a durable reason and must not remain occupied."""
    args = parse_update_args(
        [
            "--app-root",
            str(tmp_path),
            "--main-exe",
            "app.exe",
            "--version",
            "0.1.6.24",
            "--manifest-url",
            "https://updates.example.com/missing-manifest.json",
        ]
    )

    with pytest.raises(RuntimeError, match="manifest unavailable"):
        run_update_flow(
            args,
            progress_callback=lambda *_args: None,
            stage_update=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("manifest unavailable")
            ),
            wait_for_exit=lambda *_args: True,
        )

    append_update_failure_log(tmp_path, "download", RuntimeError("manifest unavailable"))

    assert not update_lock_path(tmp_path).exists()
    assert "download" in (tmp_path / "logs" / "update.log").read_text(encoding="utf-8")
    assert "manifest unavailable" in (tmp_path / "logs" / "update.log").read_text(encoding="utf-8")
