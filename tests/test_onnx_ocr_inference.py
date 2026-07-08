import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ocr_engine import OCRWorker


def test_parse_onnx_output_keeps_existing_detection_shape():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.45})
    output = np.array(
        [
            [
                [15.0, 26.0, 25.0, 34.0, 0.90, 1.0],
                [100.0, 50.0, 120.0, 60.0, 0.10, 2.0],
            ]
        ],
        dtype=np.float32,
    )

    detections, debug = worker._parse_onnx_output(output)

    assert len(detections) == 1
    assert detections[0]["class"] == 1
    assert detections[0]["bbox"] == pytest.approx([15.0, 26.0, 25.0, 34.0])
    assert detections[0]["confidence"] == pytest.approx(0.9)
    assert debug["total_boxes"] == 2
    assert debug["kept_boxes"] == 1
    assert debug["filtered_boxes"] == 1


def test_prepare_onnx_input_letterboxes_rectangular_ocr_models_to_model_shape():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.45})
    worker.model_input_shape = (64, 640)
    image = np.zeros((39, 640, 3), dtype=np.uint8)

    tensor = worker._prepare_onnx_input(image)
    detections, _ = worker._parse_onnx_output(
        np.array([[[150.0, 20.0, 165.0, 35.0, 0.9, 3.0]]], dtype=np.float32)
    )

    assert tensor.shape == (1, 3, 64, 640)
    assert detections[0]["bbox"] == pytest.approx([150.0, 7.5, 165.0, 22.5])


def test_parse_onnx_output_supports_ultralytics_raw_detection_tensor():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.45})
    worker._last_onnx_source_shape = (64, 640)
    # Ultralytics ONNX export without NMS commonly returns [batch, 4+classes, anchors].
    output = np.zeros((1, 18, 2), dtype=np.float32)
    output[0, 0:4, 0] = [20.0, 30.0, 10.0, 8.0]  # cx, cy, w, h
    output[0, 4 + 3, 0] = 0.91
    output[0, 0:4, 1] = [100.0, 50.0, 20.0, 10.0]
    output[0, 4 + 4, 1] = 0.10

    detections, debug = worker._parse_onnx_output(output)

    assert len(detections) == 1
    assert detections[0]["class"] == 3
    assert detections[0]["bbox"] == pytest.approx([15.0, 26.0, 25.0, 34.0])
    assert detections[0]["confidence"] == pytest.approx(0.91)
    assert debug["total_boxes"] == 2
    assert debug["kept_boxes"] == 1


def test_parse_onnx_output_applies_nms_to_raw_anchor_duplicates():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.45})
    worker._last_onnx_source_shape = (64, 640)
    output = np.zeros((1, 17, 3), dtype=np.float32)
    output[0, 0:4, 0] = [20.0, 30.0, 10.0, 8.0]
    output[0, 4 + 1, 0] = 0.94
    output[0, 0:4, 1] = [20.2, 30.1, 10.1, 8.1]
    output[0, 4 + 1, 1] = 0.91
    output[0, 0:4, 2] = [80.0, 30.0, 10.0, 8.0]
    output[0, 4 + 2, 2] = 0.92

    detections, debug = worker._parse_onnx_output(output)

    assert len(detections) == 2
    assert [d["class"] for d in sorted(detections, key=lambda d: d["bbox"][0])] == [1, 2]
    assert debug["total_boxes"] == 3
    assert debug["kept_boxes"] == 2
    assert debug["filtered_boxes"] == 1


def test_detailed_pipeline_log_emits_per_character_bboxes():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.25, "detailed_ocr_logging": True})
    worker._last_inference_debug = {
        "roi": {"x": 10, "y": 20, "width": 300, "height": 40},
        "total_boxes": 2,
        "kept_boxes": 2,
        "filtered_boxes": 0,
        "entries": [
            {"char": "1", "confidence": 0.91, "threshold": 0.25, "x1": 11.0, "y1": 21.0, "x2": 19.0, "y2": 37.0, "kept": True},
            {"char": "2", "confidence": 0.88, "threshold": 0.25, "x1": 20.0, "y1": 21.0, "x2": 29.0, "y2": 37.0, "kept": True},
        ],
    }
    worker._last_candidate_clusters = []
    worker._last_selection_details = []
    messages = []
    worker.ocr_output_updated = type("SignalStub", (), {"emit": messages.append})()

    worker._emit_detailed_pipeline_log(
        "FAILED",
        [{"class": 1, "bbox": np.array([11.0, 21.0, 19.0, 37.0]), "confidence": 0.91}],
        None,
        (True, (1, 2, 3), {"method": "test", "avg_confidence": 0.9, "raw_text": "", "fallback_text": ""}),
        True,
        (1, 2, 3),
    )

    assert any("[OCR-RAW-DET] #1 char='1' bbox=(11.0,21.0,19.0,37.0)" in msg for msg in messages)
    assert any("[OCR-RAW-DET] #2 char='2' bbox=(20.0,21.0,29.0,37.0)" in msg for msg in messages)
