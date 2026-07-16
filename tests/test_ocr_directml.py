from types import SimpleNamespace

import numpy as np

import ocr_engine
from core.gpu_adapters import GpuAdapter, adapter_to_selection
from ocr_engine import OCRWorker


def _adapter(device_id: int = 3) -> GpuAdapter:
    return GpuAdapter(
        name="NVIDIA GeForce Test",
        dml_device_id=device_id,
        vendor_id=0x10DE,
        device_id=0x2803,
        subsys_id=0x17AA3A5D,
        revision=161,
        is_software=False,
    )


class _FakeInput:
    name = "images"
    shape = [1, 3, 64, 640]


class _FakeSession:
    def __init__(self, providers):
        self.providers = providers
        self.fallback_disabled = False

    def get_inputs(self):
        return [_FakeInput()]

    def get_providers(self):
        return [item[0] if isinstance(item, tuple) else item for item in self.providers]

    def disable_fallback(self):
        self.fallback_disabled = True


def test_cpu_model_session_preserves_cpu_provider(monkeypatch, tmp_path) -> None:
    calls = []
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model")
    monkeypatch.setattr(
        ocr_engine.ort,
        "InferenceSession",
        lambda path, **kwargs: calls.append((path, kwargs)) or _FakeSession(kwargs["providers"]),
    )

    worker = OCRWorker({"gpu_acceleration_enabled": False})

    assert worker.load_model(model_path) is True
    assert calls == [(str(model_path), {"providers": ["CPUExecutionProvider"]})]


def test_directml_session_uses_saved_original_dxgi_id_and_disables_fallback(
    monkeypatch, tmp_path
) -> None:
    adapter = _adapter(3)
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model")
    calls = []

    class FakeSessionOptions:
        def __init__(self):
            self.enable_mem_pattern = True
            self.execution_mode = None
            self.entries = {}

        def add_session_config_entry(self, key, value):
            self.entries[key] = value

    def create_session(path, **kwargs):
        session = _FakeSession(kwargs["providers"])
        calls.append((path, kwargs, session))
        return session

    monkeypatch.setattr(ocr_engine, "enumerate_gpu_adapters", lambda: [adapter])
    monkeypatch.setattr(ocr_engine.ort, "get_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(ocr_engine.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(ocr_engine.ort, "ExecutionMode", SimpleNamespace(ORT_SEQUENTIAL="sequential"))
    monkeypatch.setattr(ocr_engine.ort, "InferenceSession", create_session)
    worker = OCRWorker({
        "gpu_acceleration_enabled": True,
        "gpu_adapter": adapter_to_selection(adapter),
    })

    assert worker.load_model(model_path) is True
    _, kwargs, session = calls[0]
    options = kwargs["sess_options"]
    assert kwargs["providers"] == [("DmlExecutionProvider", {"device_id": "3"})]
    assert kwargs["enable_fallback"] is False
    assert options.enable_mem_pattern is False
    assert options.execution_mode == "sequential"
    assert options.entries == {"session.disable_cpu_ep_fallback": "1"}
    assert session.fallback_disabled is True


def test_missing_directml_provider_is_fatal_and_never_creates_cpu_session(
    monkeypatch, tmp_path
) -> None:
    adapter = _adapter()
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model")
    created = []
    payloads = []
    monkeypatch.setattr(ocr_engine, "enumerate_gpu_adapters", lambda: [adapter])
    monkeypatch.setattr(ocr_engine.ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr(ocr_engine.ort, "InferenceSession", lambda *args, **kwargs: created.append(kwargs))
    worker = OCRWorker({
        "gpu_acceleration_enabled": True,
        "gpu_adapter": adapter_to_selection(adapter),
    })
    worker.fatal_gpu_error.connect(payloads.append)

    assert worker.load_model(model_path) is False
    assert created == []
    assert worker.should_stop is True
    assert payloads[0]["stage"] == "initialization"
    assert payloads[0]["saved_device_id"] == adapter.dml_device_id
    assert payloads[0]["saved_adapter"] == adapter_to_selection(adapter)
    assert payloads[0]["available_providers"] == ["CPUExecutionProvider"]


def test_session_reporting_cpu_provider_alongside_directml_still_loads_with_fallback_disabled(
    monkeypatch, tmp_path
) -> None:
    adapter = _adapter()
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"model")

    class MixedProviderSession(_FakeSession):
        def get_providers(self):
            return ["DmlExecutionProvider", "CPUExecutionProvider"]

    class FakeSessionOptions:
        def add_session_config_entry(self, _key, _value):
            return None

    monkeypatch.setattr(ocr_engine, "enumerate_gpu_adapters", lambda: [adapter])
    monkeypatch.setattr(
        ocr_engine.ort,
        "get_available_providers",
        lambda: ["DmlExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(ocr_engine.ort, "SessionOptions", FakeSessionOptions)
    monkeypatch.setattr(
        ocr_engine.ort,
        "ExecutionMode",
        SimpleNamespace(ORT_SEQUENTIAL="sequential"),
    )
    monkeypatch.setattr(
        ocr_engine.ort,
        "InferenceSession",
        lambda _path, **kwargs: MixedProviderSession(kwargs["providers"]),
    )
    worker = OCRWorker({
        "gpu_acceleration_enabled": True,
        "gpu_adapter": adapter_to_selection(adapter),
    })

    assert worker.load_model(model_path) is True
    assert worker.should_stop is False


def test_directml_inference_exception_is_fatal_and_stops_before_tracking(monkeypatch) -> None:
    adapter = _adapter()
    worker = OCRWorker({
        "gpu_acceleration_enabled": True,
        "gpu_adapter": adapter_to_selection(adapter),
    })
    worker.model_input_name = "images"
    worker.model = SimpleNamespace(run=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("device lost")))
    monkeypatch.setattr(worker, "_prepare_onnx_input", lambda image: image)
    payloads = []
    worker.fatal_gpu_error.connect(payloads.append)

    assert worker._run_onnx_inference(np.zeros((1,), dtype=np.float32)) == []
    assert worker.should_stop is True
    assert payloads[0]["stage"] == "inference"
    assert payloads[0]["exception_type"] == "RuntimeError"
    assert payloads[0]["exception_message"] == "device lost"
    assert "RuntimeError: device lost" in payloads[0]["traceback"]


def test_worker_loop_exits_before_tracking_after_fatal_gpu_inference(monkeypatch) -> None:
    adapter = _adapter()
    worker = OCRWorker({
        "gpu_acceleration_enabled": True,
        "gpu_adapter": adapter_to_selection(adapter),
    })
    monkeypatch.setattr(worker, "load_model", lambda: True)
    monkeypatch.setattr(worker, "load_settings", lambda: None)
    monkeypatch.setattr(
        worker,
        "_capture_ocr_region",
        lambda: np.zeros((8, 8, 3), dtype=np.uint8),
    )

    def fatal_inference(_image):
        worker.should_stop = True
        return []

    monkeypatch.setattr(worker, "_run_onnx_inference", fatal_inference)
    monkeypatch.setattr(
        worker,
        "_apply_tracking_algorithm",
        lambda _detections: (_ for _ in ()).throw(
            AssertionError("tracking must not run after fatal GPU inference")
        ),
    )

    worker.run()

    assert worker.is_running is False
