from pathlib import Path
import threading

from core.map_context import CoordinateCandidate, MapContext
from core import paths
from ocr_engine import OCRWorker
from ocr_manager import (
    BUILTIN_OCR_MODEL_PATH,
    OCRManager,
    resolve_ocr_model_path,
)
from minimap_roi import MinimapRoi
from minimap_observation_worker import MinimapObservationWorker
from screen_capture import RecognitionCapture

import numpy as np


def _recognition_capture(
    frame: np.ndarray,
    *,
    ocr_crop: np.ndarray | None = None,
    search_rect: tuple[int, int, int, int] | None = None,
) -> RecognitionCapture:
    height, width = frame.shape[:2]
    return RecognitionCapture(
        ocr_crop=frame if ocr_crop is None else ocr_crop,
        minimap_frame=frame,
        minimap_search_rect=(
            search_rect
            if search_rect is not None
            else (0, 0, max(1, width // 8), max(1, height // 4))
        ),
        source="window_full",
    )


def test_debug_recognition_cli_flag_enables_developer_diagnostics(monkeypatch):
    import main_app

    writes = []

    class FakeSettings:
        def set(self, key, value, save=True):
            writes.append((key, value, save))
            return True

        def save(self):
            writes.append(("save", True, True))
            return True

    monkeypatch.setattr("main_app.SettingsManager", FakeSettings, raising=False)

    remaining = main_app.configure_debug_recognition_from_argv(
        ["main_app.py", "--debug-recognition", "--other"]
    )

    assert remaining == ["main_app.py", "--other"]
    assert ("logging.detailed_ocr_enabled", True, False) in writes
    assert ("logging.save_minimap_frame_packages", True, False) in writes
    assert ("diagnostics.resource_probe_enabled", True, False) in writes
    assert ("save", True, True) in writes


class FakeObservationWorker:
    def __init__(self):
        self.submitted = []
        self.shutdown_called = False

    def submit(self, ocr_candidate):
        self.submitted.append(ocr_candidate)

    def shutdown(self, timeout=1.0):
        self.shutdown_called = True
        return True


def _complete_frame_sync(manager: OCRManager, candidate: CoordinateCandidate | None):
    manager._handle_recognition_frame(candidate, manager._collect_minimap_observation(candidate))


def test_minimap_observation_worker_coalesces_pending_frames():
    release_first = threading.Event()
    first_started = threading.Event()
    processed = []

    def collect(ocr_candidate):
        processed.append(ocr_candidate)
        if len(processed) == 1:
            first_started.set()
            assert release_first.wait(timeout=2.0)
        return {"seen": ocr_candidate}

    results = []
    worker = MinimapObservationWorker(collect, result_callback=results.append)

    worker.submit("first")
    assert first_started.wait(timeout=2.0)
    worker.submit("second")
    worker.submit("third")
    release_first.set()

    assert worker.wait_until_idle(timeout=2.0)
    worker.shutdown()

    assert processed == ["first", "third"]
    assert [item["ocr_candidate"] for item in results] == ["first", "third"]


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


def test_ocr_manager_submits_ocr_only_coordinate_to_observation_worker():
    manager = OCRManager()
    manager.auto_jump_enabled = False
    fake_worker = FakeObservationWorker()
    manager._observation_worker = fake_worker

    manager.on_coordinates_detected(100, 200, 30)

    assert len(fake_worker.submitted) == 1
    assert fake_worker.submitted[0].as_tuple() == (100, 200, 30)
    assert manager._coordinate_continuity.previous_coordinate is None


def test_ocr_manager_does_not_collect_minimap_observation_synchronously(monkeypatch):
    captured = []

    def fake_collect(ocr_candidate):
        captured.append(ocr_candidate)
        raise AssertionError("observation must not run in the UI slot")

    manager = OCRManager()
    manager.auto_jump_enabled = False
    fake_worker = FakeObservationWorker()
    manager._observation_worker = fake_worker
    monkeypatch.setattr(manager, "_collect_minimap_observation", fake_collect)

    manager.on_recognition_frame_completed({"ocr_coord": None})

    assert captured == []
    assert fake_worker.submitted == [None]


def test_ocr_manager_applies_completed_minimap_observation():
    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._coordinate_continuity.accept((11800, 11240, 289))
    emitted = []
    manager.coordinates_detected.connect(lambda x, y, z: emitted.append((x, y, z)))

    manager._handle_observation_completed(
        {
            "ocr_candidate": None,
            "observation": {
                "visual_candidate": {
                    "x": 11820,
                    "y": 11252,
                    "z": None,
                    "source": "visual",
                    "confidence": 0.9,
                },
                "visual_result": None,
                "heading_candidate": None,
            },
        }
    )

    assert emitted == [(11820, 11252, 289)]
    assert manager._coordinate_continuity.previous_coordinate == (11820, 11252, 289)


def test_ocr_manager_routes_observation_evidence_to_existing_logs():
    class FakeLogManager:
        def __init__(self):
            self.records = []

        def enqueue(self, log_type, line):
            self.records.append((log_type, line))

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager.set_detailed_ocr_logging(True)
    fake_logs = FakeLogManager()
    manager.set_log_manager(fake_logs)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert any(log_type == "system" and "[OBS-DECISION]" in line for log_type, line in fake_logs.records)
    assert any(log_type == "recognition" and "[OBS-EVIDENCE]" in line for log_type, line in fake_logs.records)
    assert not any(log_type == "debug" and "[OBS-EVIDENCE]" in line for log_type, line in fake_logs.records)


def test_ocr_worker_detailed_log_includes_raw_character_boxes():
    worker = OCRWorker(config_dict={"detailed_ocr_logging": True})
    emitted = []
    worker.ocr_output_updated.connect(emitted.append)
    worker._last_inference_debug = {
        "roi": {"x": 10, "y": 20, "width": 300, "height": 80},
        "total_boxes": 2,
        "kept_boxes": 1,
        "filtered_boxes": 1,
        "entries": [
            {
                "char": "-",
                "confidence": 0.93,
                "threshold": 0.45,
                "x1": 1.0,
                "y1": 2.0,
                "x2": 11.0,
                "y2": 22.0,
                "kept": True,
            },
            {
                "char": "8",
                "confidence": 0.20,
                "threshold": 0.45,
                "x1": 12.0,
                "y1": 2.0,
                "x2": 22.0,
                "y2": 22.0,
                "kept": False,
            },
        ],
    }

    worker._emit_detailed_pipeline_log(
        "SUCCESS",
        raw_detections=[],
        best_cluster=None,
        path_b_result=(True, (1, 2, 3), {"method": "punctuation", "avg_confidence": 0.9}),
        final_success=True,
        final_coords=(1, 2, 3),
        note="unit",
    )

    text = "\n".join(emitted)
    assert "[OCR-RAW] state=SUCCESS roi=(10,20,300,80) model_total=2 kept=1 filtered=1" in text
    assert "[OCR-RAW-DET] #1 char='-' bbox=(1.0,2.0,11.0,22.0) conf=0.93 th=0.45 keep=Y" in text
    assert "[OCR-RAW-DET] #2 char='8' bbox=(12.0,2.0,22.0,22.0) conf=0.20 th=0.45 keep=N" in text


def test_ocr_worker_routes_detailed_log_to_sink_without_ui_signal():
    worker = OCRWorker(config_dict={"detailed_ocr_logging": True})
    emitted = []
    sunk = []
    worker.ocr_output_updated.connect(emitted.append)
    worker.set_detailed_log_sink(sunk.append)
    worker._last_inference_debug = {
        "roi": {"x": 10, "y": 20, "width": 300, "height": 80},
        "total_boxes": 1,
        "kept_boxes": 1,
        "filtered_boxes": 0,
        "entries": [
            {
                "char": "-",
                "confidence": 0.93,
                "threshold": 0.45,
                "x1": 1.0,
                "y1": 2.0,
                "x2": 11.0,
                "y2": 22.0,
                "kept": True,
            },
        ],
    }

    worker._emit_detailed_pipeline_log(
        "SUCCESS",
        raw_detections=[],
        best_cluster=None,
        path_b_result=(True, (1, 2, 3), {"method": "punctuation", "avg_confidence": 0.9}),
        final_success=True,
        final_coords=(1, 2, 3),
        note="unit",
    )

    assert not emitted
    assert any("[OCR-RAW-DET]" in line for line in sunk)
    assert any("[OCR-FINAL]" in line for line in sunk)


def test_ocr_manager_can_reset_coordinate_continuity_on_segment_break():
    manager = OCRManager()
    manager.auto_jump_enabled = False
    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    manager.reset_coordinate_continuity("area_changed")

    assert manager._coordinate_continuity.previous_coordinate is None
    assert manager._coordinate_continuity.last_reset_reason == "area_changed"


def test_ocr_manager_resets_coordinate_continuity_when_area_changes(tmp_path):
    manager = OCRManager()
    manager.auto_jump_enabled = False
    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    first = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0})
    second = MapContext("903", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0})
    manager.update_vision_context({"map_context": first, "tile_root": tmp_path / "tiles"})
    manager.update_vision_context({"map_context": second, "tile_root": tmp_path / "tiles"})

    assert manager._coordinate_continuity.previous_coordinate is None
    assert manager._coordinate_continuity.last_reset_reason == "area_changed"


def test_ocr_manager_resets_coordinate_continuity_when_vision_context_becomes_unavailable(tmp_path):
    manager = OCRManager()
    manager.auto_jump_enabled = False
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0})
    manager.update_vision_context({"map_context": context, "tile_root": tmp_path / "tiles"})
    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    manager.update_vision_context({"map_context": None, "tile_root": None})

    assert manager._vision_map_context is None
    assert manager._vision_tile_root is None
    assert manager._coordinate_continuity.previous_coordinate is None
    assert manager._coordinate_continuity.last_reset_reason == "map_context_unavailable"


def test_ocr_manager_clears_visual_context_when_snapshot_is_none(tmp_path):
    manager = OCRManager()
    manager.auto_jump_enabled = False
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0})
    manager.update_vision_context({"map_context": context, "tile_root": tmp_path / "tiles"})

    assert manager._vision_map_context is not None
    assert manager._vision_tile_root is not None

    manager.update_vision_context(None)

    assert manager._vision_map_context is None
    assert manager._vision_tile_root is None


def test_ocr_worker_uses_recognition_capture_callback():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    crop = np.full((20, 30, 3), 155, dtype=np.uint8)
    calls = []

    def fake_capture(
        x,
        y,
        width,
        height,
        mode,
        target_window_name,
        minimap_search_region,
    ):
        calls.append(
            (
                x,
                y,
                width,
                height,
                mode,
                target_window_name,
                minimap_search_region,
            )
        )
        return _recognition_capture(frame, ocr_crop=crop, search_rect=(0, 0, 15, 25))

    worker = OCRWorker()
    worker.capture_area = {"x": 40, "y": 50, "width": 30, "height": 20}
    worker.target_window_name = "game"
    worker.minimap_search_region = {"x": 10, "y": 20, "width": 15, "height": 25}
    worker.set_recognition_capture_callback(fake_capture)

    image = worker._capture_ocr_region()

    assert calls == [
        (
            40,
            50,
            30,
            20,
            "BitBlt",
            "game",
            {"x": 10, "y": 20, "width": 15, "height": 25},
        )
    ]
    assert image.shape == (20, 30, 3)
    assert image.mean() == 155
    assert worker._last_recognition_capture.minimap_frame is frame


def test_ocr_manager_wires_recognition_capture_to_worker():
    text = Path("src/ocr_manager.py").read_text(encoding="utf-8")

    assert "capture_recognition_inputs_callback" in text
    assert "set_recognition_capture_callback" in text
    assert "captured_frame_ready.connect(self.on_observation_frame_captured)" in text
    assert "def on_observation_frame_captured(self, frame_result):" in text


def test_active_minimap_auto_search_uses_each_captured_frame_before_ocr_completion(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            return default

    manager = OCRManager()
    manager._settings = FakeSettings()
    manager._observation_worker = FakeObservationWorker()
    manager._minimap_auto_search_active = True
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    frame_result = _recognition_capture(frame)
    detected_frames = []
    monkeypatch.setattr(
        "ocr_manager.detect_minimap_circle_roi",
        lambda image, *args, **kwargs: detected_frames.append(image) or None,
    )

    manager.on_observation_frame_captured(frame_result)
    manager._collect_minimap_observation(None)
    manager._collect_minimap_observation(None)

    assert manager._observation_worker.submitted == [None]
    assert detected_frames == [frame]


def test_ocr_manager_runs_minimap_observation_when_roi_and_frame_available(monkeypatch):
    class FakeSettings:
        def __init__(self):
            self.values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
            }

        def get(self, key, default=None):
            return self.values.get(key, default)

    calls = []

    def fake_run_observation_paths(frame, **kwargs):
        calls.append((frame, kwargs))
        return {
            "visual_candidate": None,
            "visual_result": None,
            "heading_candidate": {"angle_degrees": 90.0, "bucket": 9, "confidence": 0.8},
        }

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert len(calls) == 1
    used_frame, kwargs = calls[0]
    assert used_frame is frame
    assert kwargs["roi"].x == 10
    assert kwargs["roi"].y == 20
    assert kwargs["roi"].width == 40
    assert kwargs["roi"].height == 50
    assert kwargs["ocr_candidate"].as_tuple() == (100, 200, 30)


def test_ocr_manager_keeps_latest_heading_candidate_for_map_jump(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 40,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
            }
            return values.get(key, default)

    def fake_run_observation_paths(frame, **kwargs):
        return {
            "visual_candidate": None,
            "visual_result": None,
            "heading_candidate": {"angle_degrees": 90.0, "bucket": 9, "confidence": 0.8},
        }

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert manager.latest_heading_candidate == {"angle_degrees": 90.0, "bucket": 9, "confidence": 0.8}


def test_ocr_manager_detects_heading_on_every_recognition_tick(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 40,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
                "minimap_stability.heading_recognition_enabled": True,
            }
            return values.get(key, default)

    calls = []

    def fake_run_observation_paths(frame, **kwargs):
        calls.append(kwargs)
        return {
            "visual_candidate": None,
            "visual_result": None,
            "heading_candidate": {"angle_degrees": 90.0, "bucket": 18, "confidence": 0.8}
            if kwargs["detect_heading_enabled"]
            else None,
        }

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))
    observation = manager._collect_minimap_observation(CoordinateCandidate(101, 201, 30, source="ocr"))

    assert calls[0]["detect_heading_enabled"] is True
    assert calls[1]["detect_heading_enabled"] is True
    assert observation["heading_candidate"] == {"angle_degrees": 90.0, "bucket": 18, "confidence": 0.8}
    assert "heading_failure_reason" not in observation


def test_ocr_manager_disables_heading_recognition_from_settings(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 40,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
                "minimap_stability.heading_recognition_enabled": False,
            }
            return values.get(key, default)

    calls = []

    def fake_run_observation_paths(frame, **kwargs):
        calls.append(kwargs)
        return {"visual_candidate": None, "visual_result": None, "heading_candidate": None}

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert calls[0]["detect_heading_enabled"] is False
    assert observation["heading_candidate"] is None
    assert observation["heading_failure_reason"] == "heading_disabled"


def test_ocr_manager_uses_settings_thresholds_for_coordinate_decision(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
                "minimap_stability.coordinate_agreement_x_threshold": 100,
                "minimap_stability.coordinate_agreement_y_threshold": 50,
                "minimap_stability.history_x_threshold": 150,
                "minimap_stability.history_y_threshold": 150,
            }
            return values.get(key, default)

    def fake_run_observation_paths(frame, **kwargs):
        return {
            "visual_candidate": {
                "x": 180,
                "y": 200,
                "z": None,
                "source": "visual",
                "confidence": 0.99,
            },
            "visual_result": None,
            "heading_candidate": None,
        }

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    emitted = []
    manager.coordinates_detected.connect(lambda x, y, z: emitted.append((x, y, z)))
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert emitted == [(100, 200, 30)]


def test_ocr_manager_skips_minimap_observation_without_roi(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.width": 0,
                "minimap_roi.height": 0,
            }
            return values.get(key, default)

    calls = []

    def fake_run_observation_paths(frame, **kwargs):
        calls.append((frame, kwargs))
        return {}

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert calls == []


def test_ocr_manager_passes_vision_context_to_observation(monkeypatch, tmp_path):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
            }
            return values.get(key, default)

    calls = []

    def fake_run_observation_paths(frame, **kwargs):
        calls.append(kwargs)
        return {"visual_candidate": None, "visual_result": None, "heading_candidate": None}

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    manager.update_vision_context({"map_context": context, "tile_root": tmp_path / "tiles"})
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert len(calls) == 1
    assert calls[0]["map_context"] is context
    assert calls[0]["tile_root"] == tmp_path / "tiles"


def test_ocr_manager_exports_frame_package_only_when_package_export_enabled(monkeypatch, tmp_path):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
                "logging.save_minimap_frame_packages": True,
            }
            return values.get(key, default)

    calls = []

    def fake_write_minimap_frame_package(frame, **kwargs):
        calls.append((frame, kwargs))
        return tmp_path / "pkg" / "package.json"

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager.set_detailed_ocr_logging(True)
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.write_minimap_frame_package", fake_write_minimap_frame_package)
    monkeypatch.setattr(
        "ocr_manager.run_observation_paths",
        lambda frame, **kwargs: {"visual_candidate": None, "visual_result": None, "heading_candidate": None},
    )

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert len(calls) == 1
    assert calls[0][0] is frame
    assert calls[0][1]["roi"].x == 10
    assert calls[0][1]["include_debug_artifacts"] is True
    assert calls[0][1]["ocr_candidate"].as_tuple() == (100, 200, 30)
    assert observation["frame_package_path"] == str(tmp_path / "pkg" / "package.json")


def test_ocr_manager_does_not_export_frame_package_when_package_export_disabled(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
            }
            return values.get(key, default)

    calls = []

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager.set_detailed_ocr_logging(True)
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.write_minimap_frame_package", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(
        "ocr_manager.run_observation_paths",
        lambda frame, **kwargs: {"visual_candidate": None, "visual_result": None, "heading_candidate": None},
    )

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert calls == []
    assert observation["frame_package_path"] is None


def test_ocr_manager_routes_frame_package_export_failure_to_ocr_log(monkeypatch):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
                "logging.save_minimap_frame_packages": True,
            }
            return values.get(key, default)

    class FakeLogManager:
        def __init__(self):
            self.records = []

        def enqueue(self, log_type, line):
            self.records.append((log_type, line))

    def fake_write_minimap_frame_package(frame, **kwargs):
        raise RuntimeError("package failed")

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager.set_detailed_ocr_logging(True)
    manager._settings = FakeSettings()
    fake_logs = FakeLogManager()
    manager.set_log_manager(fake_logs)
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.write_minimap_frame_package", fake_write_minimap_frame_package)
    monkeypatch.setattr(
        "ocr_manager.run_observation_paths",
        lambda frame, **kwargs: {"visual_candidate": None, "visual_result": None, "heading_candidate": None},
    )

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert observation["frame_package_path"] is None
    assert any(log_type == "recognition" and "[MINIMAP-FRAME-PACKAGE] export_failed" in line for log_type, line in fake_logs.records)
    assert not any(log_type == "debug" and "[MINIMAP-FRAME-PACKAGE] export_failed" in line for log_type, line in fake_logs.records)


def test_ocr_manager_reports_minimap_observation_exception_as_failure_reason(monkeypatch, tmp_path):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
            }
            return values.get(key, default)

    def fake_run_observation_paths(frame, **kwargs):
        raise RuntimeError("visual exploded")

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    context = MapContext(
        area_id="906",
        layer_id="default",
        tile_size=1024,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
    )
    manager.update_vision_context({"map_context": context, "tile_root": tmp_path / "tiles"})
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert observation["visual_candidate"] is None
    assert observation["visual_failure_reason"] == "observation_error"
    assert observation["error"] == "visual exploded"


def test_ocr_manager_reports_heading_failure_when_no_observation_frame():
    manager = OCRManager()
    manager.latest_observation_frame = None

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert observation["visual_failure_reason"] == "no_observation_frame"
    assert observation["heading_failure_reason"] == "no_observation_frame"


def test_ocr_manager_reports_heading_failure_when_no_minimap_roi():
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.width": 0,
                "minimap_roi.height": 0,
            }
            return values.get(key, default)

    manager = OCRManager()
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert observation["visual_failure_reason"] == "no_minimap_roi"
    assert observation["heading_failure_reason"] == "no_minimap_roi"


def test_ocr_manager_passes_current_stability_config_to_observation_paths(monkeypatch, tmp_path):
    class FakeSettings:
        def get(self, key, default=None):
            values = {
                "minimap_roi.x": 10,
                "minimap_roi.y": 20,
                "minimap_roi.width": 40,
                "minimap_roi.height": 50,
                "minimap_roi.shape": "circle",
                "minimap_roi.source": "manual",
                "minimap_stability.coordinate_agreement_x_threshold": 12,
                "minimap_stability.coordinate_agreement_y_threshold": 34,
            }
            return values.get(key, default)

    captured = []

    def fake_run_observation_paths(frame, **kwargs):
        captured.append(kwargs["stability_config"])
        return {"visual_candidate": None, "visual_result": None, "heading_candidate": None}

    manager = OCRManager()
    manager._settings = FakeSettings()
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert captured
    assert captured[0].coordinate_agreement_x_threshold == 12
    assert captured[0].coordinate_agreement_y_threshold == 34


def test_ocr_manager_locks_minimap_roi_after_three_stable_auto_detections():
    class FakeSettings:
        def __init__(self):
            self.values = {
                "minimap_stability.auto_roi_lock_tolerance_px": 2,
            }

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value, save=True):
            self.values[key] = value
            return True

        def save(self):
            return True

    settings = FakeSettings()
    manager = OCRManager()
    manager._settings = settings
    manager.start_minimap_auto_search()
    emitted = []
    manager.minimap_roi_locked.connect(lambda payload: emitted.append(payload))

    manager._handle_minimap_auto_candidate(MinimapRoi(20, 30, 210, 210, "circle", "auto"))
    manager._handle_minimap_auto_candidate(MinimapRoi(21, 31, 211, 210, "circle", "auto"))
    locked = manager._handle_minimap_auto_candidate(MinimapRoi(20, 30, 210, 209, "circle", "auto"))

    assert locked is True
    assert manager._minimap_auto_search_active is False
    assert settings.values["minimap_roi.x"] == 20
    assert settings.values["minimap_roi.y"] == 30
    assert settings.values["minimap_roi.width"] == 210
    assert settings.values["minimap_roi.height"] == 210
    assert settings.values["minimap_roi.shape"] == "circle"
    assert settings.values["minimap_roi.source"] == "auto"
    assert settings.values["minimap_roi.status"] == "locked"
    assert emitted == [
        {
            "x": 20,
            "y": 30,
            "width": 210,
            "height": 210,
            "shape": "circle",
            "source": "auto",
            "status": "locked",
        }
    ]


def test_ocr_manager_ignores_minimap_auto_candidate_when_search_is_not_active():
    class FakeSettings:
        values = {}

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value, save=True):
            self.values[key] = value
            return True

    settings = FakeSettings()
    manager = OCRManager()
    manager._settings = settings

    locked = manager._handle_minimap_auto_candidate(MinimapRoi(20, 30, 210, 210, "circle", "auto"))

    assert locked is False
    assert "minimap_roi.x" not in settings.values


def test_ocr_manager_start_minimap_auto_search_without_clearing_locked_roi():
    class FakeSettings:
        def __init__(self):
            self.values = {
                "minimap_roi.x": 20,
                "minimap_roi.y": 30,
                "minimap_roi.width": 210,
                "minimap_roi.height": 210,
                "minimap_roi.status": "locked",
            }

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value, save=True):
            self.values[key] = value
            return True

        def save(self):
            return True

    settings = FakeSettings()
    manager = OCRManager()
    manager._settings = settings
    manager._minimap_auto_candidates = [MinimapRoi(1, 2, 3, 3, "circle", "auto")]

    manager.start_minimap_auto_search()

    assert manager._minimap_auto_candidates == []
    assert manager._minimap_auto_search_active is True
    assert settings.values["minimap_roi.status"] == "searching"
    assert settings.values["minimap_roi.x"] == 20
    assert settings.values["minimap_roi.y"] == 30
    assert settings.values["minimap_roi.width"] == 210
    assert settings.values["minimap_roi.height"] == 210


def test_ocr_manager_auto_window_detect_replaces_stale_target_and_starts_minimap_search(monkeypatch):
    class FakeSettings:
        def __init__(self):
            self.values = {
                "minimap_roi.auto_calibration_enabled": True,
                "minimap_roi.x": 20,
                "minimap_roi.y": 30,
                "minimap_roi.width": 210,
                "minimap_roi.height": 210,
                "minimap_roi.status": "locked",
            }

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value, save=True):
            self.values[key] = value
            return True

        def save(self):
            return True

    class FakeScreenCapture:
        def find_best_game_window(self):
            return {
                "rect": (619, 241, 2555, 1360),
                "title": "鸣潮",
                "mode": "windowed",
                "width": 1936,
                "height": 1119,
            }

    class FakeWorker:
        is_running = True

        def __init__(self):
            self.capture_settings = []

        def update_capture_settings(self, *args):
            self.capture_settings.append(args)

    manager = OCRManager()
    manager._settings = FakeSettings()
    manager.ocr_config["ocr_interval"] = 1000
    manager.ocr_config["target_window_name"] = "鸣潮大地图-库街区 - Google Chrome"
    manager.ocr_worker = FakeWorker()
    monkeypatch.setattr("screen_capture.get_screen_capture", lambda: FakeScreenCapture())
    monkeypatch.setattr(manager, "save_config", lambda: None)

    assert manager._poll_auto_window() is True

    assert manager._current_game_window_rect == (619, 241, 2555, 1360)
    assert manager.ocr_config["target_window_name"] == "鸣潮"
    assert manager.ocr_worker.capture_settings == [
        (
            {"x": 619, "y": 1326, "width": 484, "height": 34},
            1000,
            "鸣潮",
            {"x": 619, "y": 241, "width": 242, "height": 279},
        )
    ]
    assert manager._minimap_auto_search_active is True
    assert manager._settings.values["minimap_roi.status"] == "searching"


def test_ocr_manager_minimap_preview_uses_search_rect_while_auto_searching():
    class FakeSettings:
        values = {
            "minimap_roi.status": "searching",
            "minimap_roi.x": 20,
            "minimap_roi.y": 30,
            "minimap_roi.width": 210,
            "minimap_roi.height": 210,
        }

        def get(self, key, default=None):
            return self.values.get(key, default)

    manager = OCRManager()
    manager._settings = FakeSettings()
    manager._current_game_window_rect = (619, 241, 2555, 1360)
    manager._minimap_auto_search_active = True

    assert manager.get_minimap_preview_area() == {
        "x": 619,
        "y": 241,
        "width": 242,
        "height": 279,
    }


def test_ocr_manager_minimap_preview_uses_locked_roi_after_auto_search_locks():
    class FakeSettings:
        values = {
            "minimap_roi.status": "locked",
            "minimap_roi.x": 42,
            "minimap_roi.y": 56,
            "minimap_roi.width": 214,
            "minimap_roi.height": 214,
        }

        def get(self, key, default=None):
            return self.values.get(key, default)

    manager = OCRManager()
    manager._settings = FakeSettings()
    manager._current_game_window_rect = (619, 241, 2555, 1360)

    assert manager.get_minimap_preview_area() == {
        "x": 661,
        "y": 297,
        "width": 214,
        "height": 214,
    }


def test_ocr_manager_converts_manual_minimap_selection_to_game_window_relative_roi():
    manager = OCRManager()
    manager._current_game_window_rect = (619, 241, 2555, 1360)

    roi = manager.normalize_minimap_manual_selection(661, 297, 214, 214)

    assert roi == MinimapRoi(42, 56, 214, 214, "circle", "manual")


def test_ocr_manager_does_not_use_saved_minimap_roi_while_auto_searching(monkeypatch):
    class FakeSettings:
        values = {
            "minimap_roi.status": "searching",
            "minimap_roi.x": 10,
            "minimap_roi.y": 20,
            "minimap_roi.width": 40,
            "minimap_roi.height": 50,
            "minimap_roi.shape": "circle",
            "minimap_roi.source": "auto",
        }

        def get(self, key, default=None):
            return self.values.get(key, default)

    calls = []

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    manager._minimap_auto_search_active = True
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.detect_minimap_circle_roi", lambda *args, **kwargs: None)
    monkeypatch.setattr("ocr_manager.run_observation_paths", lambda *args, **kwargs: calls.append(kwargs))

    observation = manager._collect_minimap_observation(CoordinateCandidate(100, 200, 30, source="ocr"))

    assert calls == []
    assert observation["visual_failure_reason"] == "minimap_roi_searching"


def test_ocr_manager_detects_minimap_auto_roi_in_top_left_fraction_after_ocr(monkeypatch):
    class FakeSettings:
        values = {}

        def get(self, key, default=None):
            return self.values.get(key, default)

    calls = []
    handled = []

    def fake_detect(frame, search_rect, **kwargs):
        calls.append((frame, search_rect, kwargs))
        return MinimapRoi(12, 34, 56, 56, "circle", "auto")

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    manager._minimap_auto_search_active = True
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(frame)
    monkeypatch.setattr("ocr_manager.detect_minimap_circle_roi", fake_detect, raising=False)
    monkeypatch.setattr(
        manager,
        "_handle_minimap_auto_candidate",
        lambda roi: handled.append(roi) or False,
    )

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert calls == [(frame, (0, 0, 200, 225), {"require_arrow_anchor": True})]
    assert handled == [MinimapRoi(12, 34, 56, 56, "circle", "auto")]


def test_ocr_manager_detects_minimap_auto_roi_in_provided_minimap_frame(monkeypatch):
    class FakeSettings:
        values = {}

        def get(self, key, default=None):
            return self.values.get(key, default)

    calls = []
    handled = []

    def fake_detect(frame, search_rect, **kwargs):
        calls.append((frame, search_rect, kwargs))
        return MinimapRoi(12, 34, 56, 56, "circle", "auto")

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    manager._minimap_auto_search_active = True
    game_frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(game_frame)
    monkeypatch.setattr("ocr_manager.detect_minimap_circle_roi", fake_detect, raising=False)
    monkeypatch.setattr(
        manager,
        "_handle_minimap_auto_candidate",
        lambda roi: handled.append(roi) or False,
    )

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert len(calls) == 1
    used_frame, search_rect, kwargs = calls[0]
    assert used_frame is game_frame
    assert used_frame.shape == (900, 1600, 3)
    assert search_rect == (0, 0, 200, 225)
    assert kwargs == {"require_arrow_anchor": True}
    assert handled == [MinimapRoi(12, 34, 56, 56, "circle", "auto")]


def test_ocr_manager_runs_locked_minimap_observation_on_provided_minimap_frame(monkeypatch):
    class FakeSettings:
        values = {
            "minimap_roi.x": 10,
            "minimap_roi.y": 20,
            "minimap_roi.width": 40,
            "minimap_roi.height": 50,
            "minimap_roi.shape": "circle",
            "minimap_roi.source": "manual",
        }

        def get(self, key, default=None):
            return self.values.get(key, default)

    calls = []

    def fake_run_observation_paths(frame, **kwargs):
        calls.append((frame, kwargs))
        return {"visual_candidate": None, "visual_result": None, "heading_candidate": None}

    manager = OCRManager()
    manager.auto_jump_enabled = False
    manager._settings = FakeSettings()
    game_frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    manager.latest_observation_frame = _recognition_capture(game_frame)
    monkeypatch.setattr("ocr_manager.run_observation_paths", fake_run_observation_paths)

    _complete_frame_sync(manager, CoordinateCandidate(100, 200, 30, source="ocr"))

    assert len(calls) == 1
    used_frame, kwargs = calls[0]
    assert used_frame is game_frame
    assert used_frame.shape == (900, 1600, 3)
    assert kwargs["roi"] == MinimapRoi(10, 20, 40, 50, "circle", "manual")
