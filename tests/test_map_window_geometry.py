from pathlib import Path

import test_bootstrap  # noqa: F401


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEPARATED_MAP_WINDOW = PROJECT_ROOT / "src" / "separated_map_window.py"
SETTINGS_INTERFACE = PROJECT_ROOT / "src" / "ui" / "interfaces" / "settings_interface.py"
MAIN_WINDOW = PROJECT_ROOT / "src" / "ui" / "main_window.py"


def test_separated_map_window_defines_default_geometry_constant():
    text = SEPARATED_MAP_WINDOW.read_text(encoding="utf-8")

    assert "DEFAULT_MAP_WINDOW_WIDTH = 630" in text
    assert "DEFAULT_MAP_WINDOW_HEIGHT = 580" in text


def test_separated_map_window_exposes_saved_geometry_api():
    text = SEPARATED_MAP_WINDOW.read_text(encoding="utf-8")

    assert "def default_geometry_from_main_window" in text
    assert "def show_with_geometry_memory" in text
    assert "def _is_geometry_visible_on_screen" in text


def test_settings_interface_exposes_map_window_geometry_checkbox():
    text = SETTINGS_INTERFACE.read_text(encoding="utf-8")

    assert "window_settings_changed = Signal(bool)" in text
    assert "def _init_window_card" in text
    assert "remember_map_window_geometry_check" in text
    assert "记住地图窗口位置和大小" in text
    assert 'settings.get("window.remember_map_window_geometry", True)' in text
    assert 'settings.set("window.remember_map_window_geometry", enabled, save=True)' in text


def test_settings_interface_persists_checkbox_state_changes():
    text = SETTINGS_INTERFACE.read_text(encoding="utf-8")

    assert "remember_map_window_geometry_check.stateChanged.connect" in text
    assert "state == Qt.CheckState.Checked.value" in text


def test_settings_interface_checkbox_keeps_transparent_background():
    text = SETTINGS_INTERFACE.read_text(encoding="utf-8")

    assert "ThemeManager.get_check_box_style()" in text
    assert "remember_map_window_geometry_check.setStyleSheet(checkbox_style)" in text


def test_settings_interface_checkbox_writes_true_and_false(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    import core.settings_manager as settings_manager_module
    from core.settings_manager import SettingsManager
    import ui.interfaces.settings_interface as settings_module

    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        '{"window": {"remember_map_window_geometry": false}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        settings_manager_module,
        "SettingsManager",
        lambda: SettingsManager(str(settings_file)),
    )

    app = QApplication.instance() or QApplication([])
    interface = settings_module.SettingsInterface(None)

    assert interface.remember_map_window_geometry_check.isChecked() is False

    interface.remember_map_window_geometry_check.setChecked(True)
    settings = SettingsManager(str(settings_file))
    assert settings.get("window.remember_map_window_geometry") is True

    interface.remember_map_window_geometry_check.setChecked(False)
    settings = SettingsManager(str(settings_file))
    assert settings.get("window.remember_map_window_geometry") is False


def test_main_window_saves_and_restores_map_window_geometry_setting():
    text = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "def _remember_map_window_geometry_enabled" in text
    assert "def _load_map_window_geometry" in text
    assert "def _save_map_window_geometry" in text
    assert 'self._settings.get("window.remember_map_window_geometry", True)' in text
    assert 'self._settings.get("window.map_window_geometry", None)' in text
    assert 'self._settings.set("window.map_window_geometry"' in text
    assert "show_with_geometry_memory(self.geometry(), self._load_map_window_geometry())" in text
    assert "self._save_map_window_geometry()" in text
