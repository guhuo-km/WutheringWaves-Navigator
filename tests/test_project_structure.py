from pathlib import Path

from core import paths


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def test_src_tree_does_not_contain_runtime_outputs_or_static_model_copies():
    forbidden_paths = [
        SRC_ROOT / "app_settings.json",
        SRC_ROOT / "calibration_data.json",
        SRC_ROOT / "language_config.json",
        SRC_ROOT / "login_history.json",
        SRC_ROOT / "maps.json",
        SRC_ROOT / "ocr_config.json",
        SRC_ROOT / "ocr_logs.json",
        SRC_ROOT / "recorded_routes",
        SRC_ROOT / "web_profile",
        SRC_ROOT / "images",
        SRC_ROOT / "tiles",
        SRC_ROOT / "models",
    ]

    existing = [path.relative_to(PROJECT_ROOT).as_posix() for path in forbidden_paths if path.exists()]

    assert existing == []


def test_canonical_static_resources_exist_once():
    canonical_resources = [
        PROJECT_ROOT / "assets" / "ico.ico",
        PROJECT_ROOT / "assets" / "ico.png",
        PROJECT_ROOT / "models" / "class_names.txt",
        PROJECT_ROOT / "models" / "coord_ocr.pt",
        PROJECT_ROOT / "languages" / "zh_CN.json",
        PROJECT_ROOT / "languages" / "en_US.json",
    ]

    missing = [path.relative_to(PROJECT_ROOT).as_posix() for path in canonical_resources if not path.exists()]

    assert missing == []


def test_legacy_ocr_model_files_are_not_tracked_static_resources():
    legacy_model_files = [
        PROJECT_ROOT / "models" / "coord_ocr.onnx",
        PROJECT_ROOT / "src" / "models" / "coord_ocr.pt",
        PROJECT_ROOT / "src" / "models" / "coord_ocr.onnx",
    ]

    existing = [path.relative_to(PROJECT_ROOT).as_posix() for path in legacy_model_files if path.exists()]

    assert existing == []


def test_pyinstaller_spec_files_are_generated_artifacts():
    spec_files = [
        PROJECT_ROOT / "WutheringWaves-Navigator-Smart.spec",
        PROJECT_ROOT / "WutheringWaves-Updater.spec",
    ]

    existing = [path.relative_to(PROJECT_ROOT).as_posix() for path in spec_files if path.exists()]

    assert existing == []


def test_runtime_resource_helpers_are_used_for_ui_assets_and_scripts():
    files = [
        SRC_ROOT / "greasemonkey_manager.py",
        SRC_ROOT / "ui" / "custom_icons.py",
        SRC_ROOT / "ui" / "interfaces" / "about_interface.py",
        SRC_ROOT / "ui" / "interfaces" / "home_interface.py",
        SRC_ROOT / "ui" / "main_window.py",
    ]

    offenders = []
    for file_path in files:
        source = file_path.read_text(encoding="utf-8")
        if 'getattr(sys, "_MEIPASS"' in source or "os.path.dirname(os.path.abspath(__file__))" in source:
            offenders.append(file_path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_main_window_download_fallback_uses_runtime_downloads(monkeypatch):
    from ui.main_window import MainWindow

    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr("ui.main_window.QStandardPaths.writableLocation", lambda _location: "")

    assert Path(MainWindow._get_download_dir(None)) == paths.runtime_dir("downloads")


def test_main_window_update_paths_use_path_authority(monkeypatch):
    from ui.main_window import MainWindow

    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    assert MainWindow._app_root_for_update(None) == paths.app_root()
