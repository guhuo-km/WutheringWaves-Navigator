from pathlib import Path

from src.core.crash_diagnostics import resolve_session_log_dir
from src.core.log_manager import LogManager


def test_log_manager_groups_files_by_date_and_session(tmp_path):
    manager = LogManager(log_dir=str(tmp_path), session_ts="20260523_154500")

    assert Path(manager.get_log_path("system")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/system.log"
    assert Path(manager.get_log_path("ocr")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/ocr.log"
    assert Path(manager.get_log_path("debug")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/debug.log"

    manager.stop()


def test_crash_diagnostics_uses_same_session_log_layout(tmp_path):
    log_dir = resolve_session_log_dir(str(tmp_path), "20260523_154500")

    assert Path(log_dir).relative_to(tmp_path).as_posix() == "2026-05-23/154500"
