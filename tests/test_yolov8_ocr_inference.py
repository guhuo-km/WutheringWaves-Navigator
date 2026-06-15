import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ocr_engine import OCRWorker


class _Scalar:
    def __init__(self, value):
        self._value = value

    def item(self):
        return self._value

    def __float__(self):
        return float(self._value)

    def __int__(self):
        return int(self._value)


class _BoxArray:
    def __init__(self, values):
        self._values = np.array(values, dtype=np.float32)

    def __getitem__(self, index):
        return _Scalar(float(self._values[index]))

    def cpu(self):
        return self

    def numpy(self):
        return self._values.copy()


class _FakeBoxes:
    def __init__(self, rows):
        self.xyxy = [_BoxArray(row[:4]) for row in rows]
        self.conf = [_Scalar(row[4]) for row in rows]
        self.cls = [_Scalar(row[5]) for row in rows]

    def __len__(self):
        return len(self.xyxy)


class _FakeResult:
    def __init__(self, rows):
        self.boxes = _FakeBoxes(rows)


class _FakeModel:
    def __init__(self, rows):
        self.rows = rows

    def __call__(self, image, verbose=False):
        return [_FakeResult(self.rows)]


def test_yolov8_inference_keeps_detection_shape_and_filters_by_threshold():
    worker = OCRWorker(config_dict={"confidence_threshold": 0.45})
    worker.model = _FakeModel(
        [
            [15.0, 26.0, 25.0, 34.0, 0.90, 1.0],
            [100.0, 50.0, 120.0, 60.0, 0.10, 2.0],
        ]
    )

    detections = worker._run_yolo_inference(np.zeros((64, 512, 3), dtype=np.uint8))

    assert len(detections) == 1
    assert detections[0]["class"] == 1
    assert detections[0]["bbox"] == pytest.approx([15.0, 26.0, 25.0, 34.0])
    assert detections[0]["confidence"] == pytest.approx(0.9)
    assert worker._last_inference_debug["total_boxes"] == 2
    assert worker._last_inference_debug["kept_boxes"] == 1
    assert worker._last_inference_debug["filtered_boxes"] == 1


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
