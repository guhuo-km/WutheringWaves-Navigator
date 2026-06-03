from pathlib import Path

from core import paths
from ocr_manager import (
    BUILTIN_OCR_MODEL_PATH,
    OCRManager,
    resolve_ocr_model_path,
)


def test_ocr_manager_uses_runtime_config_and_log_paths(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    manager = OCRManager()

    assert manager.config_file == paths.config_file("ocr_config.json")
    assert manager.log_file == paths.log_file("ocr_logs.json")
    assert not str(manager.config_file).startswith(str(paths.src_root()))
    assert not str(manager.log_file).startswith(str(paths.src_root()))


def test_builtin_ocr_model_resolves_to_canonical_model_directory(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    assert BUILTIN_OCR_MODEL_PATH == "models/coord_ocr.onnx"
    assert resolve_ocr_model_path(BUILTIN_OCR_MODEL_PATH) == paths.model_file("coord_ocr.onnx")
    assert resolve_ocr_model_path(Path("models") / "coord_ocr.onnx") == paths.model_file("coord_ocr.onnx")


def test_custom_ocr_model_path_is_not_rewritten(tmp_path):
    custom = tmp_path / "custom_detector.onnx"

    assert resolve_ocr_model_path(custom) == custom
