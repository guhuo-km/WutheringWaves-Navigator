import importlib.util
import sys
from pathlib import Path


def test_main_app_import_does_not_change_current_working_directory(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    main_app = project_root / "src" / "main_app.py"
    monkeypatch.chdir(tmp_path)

    spec = importlib.util.spec_from_file_location("main_app_import_path_test", main_app)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert Path.cwd() == tmp_path
    assert sys.dont_write_bytecode is True


def test_main_app_uses_path_authority_after_bootstrap():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "src" / "main_app.py").read_text(encoding="utf-8")

    assert "from core import paths" in source
    assert "os.path.dirname(os.path.abspath(__file__))" not in source
    assert "else repo_root" not in source


def test_main_app_recovers_interrupted_updates_before_startup_maintenance():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "src" / "main_app.py").read_text(encoding="utf-8")

    assert "recover_interrupted_updates(app_root)" in source
    assert source.index("recover_interrupted_updates(app_root)") < source.index(
        "run_startup_maintenance(app_root)"
    )


def test_update_handoff_starts_updater_after_event_loop_returns():
    """Known issue: the updater currently starts while the main program is alive."""
    project_root = Path(__file__).resolve().parents[1]
    main_source = (project_root / "src" / "main_app.py").read_text(encoding="utf-8")
    window_source = (project_root / "src" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    launch_start = window_source.index("    def _launch_file_updater")
    launch_end = window_source.index("    def _setup_overlay_manager", launch_start)
    launch_body = window_source[launch_start:launch_end]

    assert "self._pending_update_command = args" in launch_body
    assert "self.close()" in launch_body
    assert "subprocess.Popen" not in launch_body
    assert main_source.index("exit_code = app.exec()") < main_source.index("subprocess.Popen(")
