from types import SimpleNamespace

import ocr_manager
from core.gpu_adapters import GpuAdapter, adapter_to_selection
from ocr_manager import OCRManager


def _manager(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr_manager.paths, "config_file", lambda _name: tmp_path / "ocr_config.json")
    manager = OCRManager()
    manager.ocr_config = {
        "gpu_acceleration_enabled": False,
        "gpu_adapter": None,
    }
    return manager


def test_gpu_settings_default_to_enabled_and_no_adapter(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ocr_manager.paths, "config_file", lambda _name: tmp_path / "missing.json")

    manager = OCRManager()

    assert manager.ocr_config["gpu_acceleration_enabled"] is True
    assert manager.ocr_config["gpu_adapter"] is None


def test_gpu_settings_persist_when_ocr_is_stopped(monkeypatch, tmp_path) -> None:
    manager = _manager(monkeypatch, tmp_path)
    selection = adapter_to_selection(GpuAdapter(
        name="GPU",
        dml_device_id=1,
        vendor_id=11,
        device_id=12,
        subsys_id=13,
        revision=14,
        is_software=False,
    ))

    assert manager.set_gpu_adapter(selection) is True
    assert manager.set_gpu_acceleration_enabled(True) is True

    loaded = manager.load_config()
    assert loaded["gpu_adapter"] == selection
    assert loaded["gpu_acceleration_enabled"] is True


def test_gpu_adapter_rejects_incomplete_selection_without_persisting(
    monkeypatch, tmp_path
) -> None:
    manager = _manager(monkeypatch, tmp_path)

    assert manager.set_gpu_adapter({"name": "GPU", "dml_device_id": 1}) is False
    assert manager.ocr_config["gpu_adapter"] is None
    assert not manager.config_file.exists()


def test_gpu_adapter_can_be_cleared_and_persisted(monkeypatch, tmp_path) -> None:
    manager = _manager(monkeypatch, tmp_path)
    manager.ocr_config["gpu_adapter"] = {"legacy": "selection"}

    assert manager.set_gpu_adapter(None) is True
    assert manager.ocr_config["gpu_adapter"] is None
    assert manager.load_config()["gpu_adapter"] is None


def test_gpu_enabled_update_rolls_back_when_config_write_fails(
    monkeypatch, tmp_path
) -> None:
    manager = _manager(monkeypatch, tmp_path)
    manager.config_file = tmp_path

    assert manager.set_gpu_acceleration_enabled(True) is False
    assert manager.ocr_config["gpu_acceleration_enabled"] is False


def test_gpu_adapter_update_rolls_back_when_config_write_fails(
    monkeypatch, tmp_path
) -> None:
    manager = _manager(monkeypatch, tmp_path)
    previous = adapter_to_selection(GpuAdapter(
        name="Previous GPU",
        dml_device_id=0,
        vendor_id=2,
        device_id=3,
        subsys_id=4,
        revision=5,
        is_software=False,
    ))
    replacement = dict(previous, name="Replacement GPU", dml_device_id=1)
    manager.ocr_config["gpu_adapter"] = previous
    manager.config_file = tmp_path

    assert manager.set_gpu_adapter(replacement) is False
    assert manager.ocr_config["gpu_adapter"] == previous


def test_gpu_settings_are_rejected_while_worker_is_starting_or_running(monkeypatch, tmp_path) -> None:
    manager = _manager(monkeypatch, tmp_path)
    manager.ocr_worker = SimpleNamespace(is_running=False, isRunning=lambda: False)

    assert manager.set_gpu_adapter({"dml_device_id": 2}) is False
    assert manager.set_gpu_acceleration_enabled(True) is False
    assert manager.ocr_config == {
        "gpu_acceleration_enabled": False,
        "gpu_adapter": None,
    }


def test_manager_propagates_fatal_gpu_failure_and_stopped_state(monkeypatch, tmp_path) -> None:
    manager = _manager(monkeypatch, tmp_path)
    worker = SimpleNamespace(should_stop=False)
    manager.ocr_worker = worker
    failures = []
    states = []
    manager.gpu_acceleration_failed.connect(failures.append)
    manager.state_changed.connect(states.append)
    payload = {"stage": "inference", "exception_message": "device lost"}

    manager.on_fatal_gpu_error(payload)

    assert worker.should_stop is True
    assert failures == [payload]
    assert states[-1] == "STOPPED"


def test_logging_failure_cannot_block_fatal_gpu_stop_and_signals(
    monkeypatch, tmp_path, caplog
) -> None:
    manager = _manager(monkeypatch, tmp_path)
    worker = SimpleNamespace(should_stop=False)
    manager.ocr_worker = worker
    manager._log_manager = SimpleNamespace(
        enqueue=lambda *_args: (_ for _ in ()).throw(RuntimeError("log backend failed"))
    )
    failures = []
    states = []
    manager.gpu_acceleration_failed.connect(failures.append)
    manager.state_changed.connect(states.append)
    payload = {"stage": "inference", "exception_message": "device lost"}

    manager.on_fatal_gpu_error(payload)

    assert worker.should_stop is True
    assert states[-1] == "STOPPED"
    assert failures == [payload]
    assert "Failed to persist DirectML OCR fatal error" in caplog.text


def test_finished_worker_cleanup_uses_sender_and_does_not_touch_replacement(monkeypatch, tmp_path) -> None:
    manager = _manager(monkeypatch, tmp_path)
    deleted = []
    finished = SimpleNamespace(deleteLater=lambda: deleted.append(True))
    replacement = SimpleNamespace()
    manager.ocr_worker = replacement
    monkeypatch.setattr(manager, "sender", lambda: finished)

    manager._on_ocr_worker_finished()

    assert deleted == []
    assert manager.ocr_worker is replacement


def test_finished_worker_cleanup_clears_its_current_worker(monkeypatch, tmp_path) -> None:
    manager = _manager(monkeypatch, tmp_path)
    deleted = []
    finished = SimpleNamespace(deleteLater=lambda: deleted.append(True))
    manager.ocr_worker = finished
    monkeypatch.setattr(manager, "sender", lambda: finished)

    manager._on_ocr_worker_finished()

    assert deleted == [True]
    assert manager.ocr_worker is None
