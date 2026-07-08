from ocr_manager import normalize_builtin_ocr_model_path


def test_migrates_legacy_builtin_pt_model_path():
    config = {"model_path": "models/coord_ocr.pt", "ocr_interval": 500}

    migrated, changed = normalize_builtin_ocr_model_path(config)

    assert changed is True
    assert migrated["model_path"] == "models/coord_ocr.onnx"
    assert migrated["ocr_interval"] == 500


def test_migrates_legacy_builtin_windows_pt_model_path():
    config = {"model_path": r"models\coord_ocr.pt"}

    migrated, changed = normalize_builtin_ocr_model_path(config)

    assert changed is True
    assert migrated["model_path"] == "models/coord_ocr.onnx"


def test_keeps_builtin_onnx_model_path():
    config = {"model_path": "models/coord_ocr.onnx"}

    migrated, changed = normalize_builtin_ocr_model_path(config)

    assert changed is False
    assert migrated["model_path"] == "models/coord_ocr.onnx"


def test_keeps_custom_model_path():
    config = {"model_path": "models/custom_detector.onnx"}

    migrated, changed = normalize_builtin_ocr_model_path(config)

    assert changed is False
    assert migrated["model_path"] == "models/custom_detector.onnx"
