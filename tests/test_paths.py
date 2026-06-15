from pathlib import Path

from core import paths


def test_source_mode_roots_are_stable(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    project = Path(paths.project_root())

    assert Path(paths.src_root()) == project / "src"
    assert Path(paths.resource_root()) == project
    assert Path(paths.runtime_root()) == project / ".runtime"
    assert Path(paths.config_file("app_settings.json")) == (
        project / ".runtime" / "config" / "app_settings.json"
    )
    assert Path(paths.model_file("coord_ocr.pt")) == project / "models" / "coord_ocr.pt"


def test_frozen_mode_uses_executable_parent_for_runtime(monkeypatch, tmp_path):
    exe = tmp_path / "WutheringWavesNavigator.exe"
    exe.write_text("", encoding="utf-8")
    bundle = tmp_path / "_internal"

    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(exe), raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle), raising=False)

    assert Path(paths.resource_root()) == bundle
    assert Path(paths.runtime_root()) == tmp_path
    assert Path(paths.config_file("ocr_config.json")) == tmp_path / "config" / "ocr_config.json"
