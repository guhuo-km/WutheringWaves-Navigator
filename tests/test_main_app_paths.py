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
