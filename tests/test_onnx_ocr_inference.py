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


def test_prepare_onnx_input_resizes_to_model_shape_and_scales_boxes_back():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.45})
    worker.model_input_shape = (512, 512)
    image = np.zeros((64, 512, 3), dtype=np.uint8)

    tensor = worker._prepare_onnx_input(image)
    detections, _ = worker._parse_onnx_output(
        np.array([[[180.0, 239.0, 220.0, 249.0, 0.9, 3.0]]], dtype=np.float32)
    )

    assert tensor.shape == (1, 3, 512, 512)
    assert detections[0]["bbox"] == pytest.approx([180.0, 15.0, 220.0, 25.0])


def test_parse_onnx_output_drops_invalid_zero_area_boxes():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.25})
    worker._last_onnx_source_shape = (64, 512)
    output = np.array(
        [
            [
                [434.0, 0.0, 512.0, 0.0, 0.29, 2.0],
                [-45.0, -285.0, 102.0, -134.0, 0.29, 3.0],
                [100.0, 20.0, 114.0, 38.0, 0.90, 2.0],
            ]
        ],
        dtype=np.float32,
    )

    detections, debug = worker._parse_onnx_output(output)

    assert len(detections) == 1
    assert detections[0]["bbox"] == pytest.approx([100.0, 20.0, 114.0, 38.0])
    assert debug["total_boxes"] == 3
    assert debug["kept_boxes"] == 1
    assert debug["filtered_boxes"] == 2
