from pathlib import Path

from src.core import crash_diagnostics
from src.core import paths
from src.core.log_manager import LogManager


def test_log_manager_groups_files_by_date_and_session(tmp_path):
    manager = LogManager(log_dir=str(tmp_path), session_ts="20260523_154500")

    assert Path(manager.get_log_path("system")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/system.log"
    assert Path(manager.get_log_path("ocr")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/ocr.log"
    assert Path(manager.get_log_path("debug")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/debug.log"

    manager.stop()


def test_crash_diagnostics_uses_same_session_log_layout(tmp_path):
    log_dir = crash_diagnostics.resolve_session_log_dir(str(tmp_path), "20260523_154500")

    assert Path(log_dir).relative_to(tmp_path).as_posix() == "2026-05-23/154500"


def test_crash_diagnostics_uses_runtime_log_root(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(crash_diagnostics, "_SESSION_TS", "20260523_154500")

    log_dir = Path(crash_diagnostics._resolve_log_dir())

    assert log_dir == paths.log_dir() / "2026-05-23" / "154500"
    assert not str(log_dir).startswith(str(paths.src_root()))
