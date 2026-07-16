import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_INTERFACE = PROJECT_ROOT / "src" / "ui" / "interfaces" / "settings_interface.py"
MAIN_WINDOW = PROJECT_ROOT / "src" / "ui" / "main_window.py"
LANGUAGES = PROJECT_ROOT / "languages"


GPU_LANGUAGE_KEYS = {
    "settings_gpu_acceleration",
    "settings_gpu_acceleration_enabled",
    "settings_gpu_adapter",
    "settings_gpu_status_disabled",
    "settings_gpu_status_detecting",
    "settings_gpu_status_ready",
    "settings_gpu_status_unavailable",
    "gpu_acceleration_unavailable_title",
    "gpu_acceleration_unavailable_message",
}


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_settings_interface_has_gpu_card_between_language_and_window_cards():
    text = SETTINGS_INTERFACE.read_text(encoding="utf-8")

    assert "self._init_gpu_acceleration_card()" in text
    assert text.index("self._init_language_card()") < text.index("self._init_gpu_acceleration_card()")
    assert text.index("self._init_gpu_acceleration_card()") < text.index("self._init_window_card()")
    assert "gpu_acceleration_changed = Signal(bool)" in text
    assert "gpu_adapter_changed = Signal(dict)" in text


def test_gpu_discovery_uses_owned_worker_and_core_adapter_enumerator():
    text = SETTINGS_INTERFACE.read_text(encoding="utf-8")

    assert "class GpuAdapterDiscoveryWorker(QThread):" in text
    assert "enumerate_gpu_adapters," in text
    assert "enumerate_gpu_adapters()" in text
    assert "self._gpu_discovery_worker.start()" in text


def test_gpu_presentation_preserves_saved_selection_and_locks_controls_while_ocr_runs():
    text = SETTINGS_INTERFACE.read_text(encoding="utf-8")

    for method in (
        "def set_gpu_configuration(self, config):",
        "def set_ocr_running(self, running: bool):",
        "def mark_gpu_unavailable(self):",
        "def _on_gpu_adapters_discovered(self, adapters):",
    ):
        assert method in text
    assert "resolve_saved_adapter" in text
    assert "adapter_to_selection" in text
    assert "if self._ocr_running:" in text


def test_main_window_wires_gpu_settings_and_native_failure_dialog():
    text = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "set_gpu_configuration(self._ocr_manager.ocr_config)" in text
    assert "gpu_acceleration_changed.connect(" in text
    assert "self._on_gpu_acceleration_changed" in text
    assert "gpu_adapter_changed.connect(" in text
    assert "self._on_gpu_adapter_changed" in text
    assert "gpu_acceleration_failed.connect(" in text
    assert "self._on_gpu_acceleration_failed" in text
    assert "ocr_state_changed.connect(self._on_ocr_running_changed)" in text
    assert "def _on_gpu_acceleration_changed(self, enabled: bool):" in text
    assert "def _on_gpu_adapter_changed(self, selection: dict):" in text
    assert "def _on_gpu_acceleration_failed(self, _details: dict):" in text
    assert "QMessageBox.StandardButton.Ok" in text
    assert 'tr("gpu_acceleration_unavailable_title"' in text
    assert '"gpu_acceleration_unavailable_message"' in text


def test_gpu_ui_language_keys_are_synchronized():
    zh = json.loads((LANGUAGES / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((LANGUAGES / "en_US.json").read_text(encoding="utf-8"))

    assert GPU_LANGUAGE_KEYS <= zh.keys()
    assert GPU_LANGUAGE_KEYS <= en.keys()


def test_gpu_user_visible_text_comes_from_translation_keys_without_python_fallbacks():
    settings_text = SETTINGS_INTERFACE.read_text(encoding="utf-8")
    main_window_text = MAIN_WINDOW.read_text(encoding="utf-8")

    for literal in (
        '"显卡加速"', '"使用显卡加速"', '"显卡"', '"状态：未启用"',
        '"状态：识别中"', '"状态：准备就绪"', '"状态：不可用"',
        '"显卡加速不可用"', '"识别已停止。请在设置中更换显卡或关闭显卡加速。"',
    ):
        assert literal not in settings_text
        assert literal not in main_window_text


def test_gpu_card_defaults_to_first_adapter_and_locks_without_persisting_during_ocr(qapp):
    from src.core.gpu_adapters import GpuAdapter
    from src.ui.interfaces.settings_interface import SettingsInterface

    interface = SettingsInterface(app_state=object())
    interface._start_gpu_discovery = lambda: None
    changes = []
    interface.gpu_adapter_changed.connect(changes.append)
    adapters = [
        GpuAdapter("NVIDIA", 0, 1, 1, 1, 1, False),
        GpuAdapter("Intel", 1, 2, 2, 2, 2, False),
    ]

    interface.set_gpu_configuration({"gpu_acceleration_enabled": True, "gpu_adapter": None})
    interface._on_gpu_adapters_discovered(adapters)

    assert interface.gpu_adapter_combo.currentText() == "NVIDIA"
    assert changes[-1]["name"] == "NVIDIA"
    assert changes[-1]["dml_device_id"] == 0

    changes.clear()
    interface.set_ocr_running(True)
    interface._gpu_config = {"gpu_acceleration_enabled": True, "gpu_adapter": None}
    interface._on_gpu_adapters_discovered(adapters)

    assert not interface.gpu_acceleration_switch.isEnabled()
    assert not interface.gpu_adapter_combo.isEnabled()
    assert changes == []

    interface.set_ocr_running(False)

    assert changes == [{
        "name": "NVIDIA", "dml_device_id": 0, "vendor_id": 1,
        "device_id": 1, "subsys_id": 1, "revision": 1,
    }]


def test_gpu_card_marks_missing_saved_adapter_unavailable_without_selecting_first(qapp):
    from src.core.gpu_adapters import GpuAdapter
    from src.ui.interfaces.settings_interface import SettingsInterface

    interface = SettingsInterface(app_state=object())
    interface._start_gpu_discovery = lambda: None
    interface.set_gpu_configuration({
        "gpu_acceleration_enabled": True,
        "gpu_adapter": {
            "name": "Missing GPU", "dml_device_id": 9, "vendor_id": 9,
            "device_id": 9, "subsys_id": 9, "revision": 9,
        },
    })

    interface._on_gpu_adapters_discovered([
        GpuAdapter("NVIDIA", 0, 1, 1, 1, 1, False),
    ])

    assert interface._gpu_status == "unavailable"
    assert interface.gpu_adapter_combo.count() == 1
    assert interface.gpu_adapter_combo.currentIndex() == -1
    assert interface.gpu_adapter_combo.isEnabled()


def test_discovery_completion_after_acceleration_is_disabled_does_not_select_an_adapter(qapp):
    from src.core.gpu_adapters import GpuAdapter
    from src.ui.interfaces.settings_interface import SettingsInterface

    interface = SettingsInterface(app_state=object())
    changes = []
    interface.gpu_adapter_changed.connect(changes.append)
    interface._gpu_config = {"gpu_acceleration_enabled": False, "gpu_adapter": None}

    interface._on_gpu_adapters_discovered([
        GpuAdapter("NVIDIA", 0, 1, 1, 1, 1, False),
    ])

    assert interface._gpu_status == "disabled"
    assert interface.gpu_adapter_combo.count() == 0
    assert changes == []


def test_disabling_gpu_acceleration_clears_cached_adapters_before_reenable(qapp):
    from src.core.gpu_adapters import GpuAdapter
    from src.ui.interfaces.settings_interface import SettingsInterface

    interface = SettingsInterface(app_state=object())
    interface._gpu_adapters = [
        GpuAdapter("NVIDIA", 0, 1, 1, 1, 1, False),
    ]
    started = []
    interface._start_gpu_discovery = lambda: started.append(True)

    interface.set_gpu_configuration({"gpu_acceleration_enabled": False, "gpu_adapter": None})

    assert interface._gpu_adapters == []

    interface.set_gpu_configuration({"gpu_acceleration_enabled": True, "gpu_adapter": None})

    assert started == [True]


def test_late_gpu_discovery_failure_after_disable_keeps_disabled_status(qapp):
    from src.ui.interfaces.settings_interface import SettingsInterface

    interface = SettingsInterface(app_state=object())
    interface.set_gpu_configuration({"gpu_acceleration_enabled": False, "gpu_adapter": None})

    interface._on_gpu_discovery_failed()

    assert interface._gpu_status == "disabled"


def test_gpu_discovery_shutdown_waits_and_never_deletes_live_thread(qapp):
    from src.ui.interfaces.settings_interface import SettingsInterface

    interface = SettingsInterface(app_state=object())
    deleted = []
    live_worker = SimpleNamespace(
        isRunning=lambda: True,
        wait=lambda _timeout: False,
        deleteLater=lambda: deleted.append(True),
    )
    interface._gpu_discovery_worker = live_worker

    assert interface.shutdown_gpu_discovery(timeout_ms=1) is False
    assert interface._gpu_discovery_worker is live_worker
    assert deleted == []

    stopped_worker = SimpleNamespace(
        isRunning=lambda: False,
        wait=lambda _timeout: True,
        deleteLater=lambda: deleted.append(True),
    )
    interface._gpu_discovery_worker = stopped_worker

    assert interface.shutdown_gpu_discovery(timeout_ms=1) is True
    assert interface._gpu_discovery_worker is None
    assert deleted == [True]


def test_main_window_close_checks_worker_shutdown_before_destroying_threads():
    text = MAIN_WINDOW.read_text(encoding="utf-8")

    close_event = text[text.index("    def closeEvent(self, event):"):]
    assert "shutdown_gpu_discovery()" in close_event
    assert "not self._ocr_manager.stop_ocr()" in close_event
    assert "event.ignore()" in close_event
    assert "self._is_closing = False" in close_event
