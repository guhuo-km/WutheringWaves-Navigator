# -*- coding: utf-8 -*-
from typing import Any, Dict, Optional, List
from PySide6.QtCore import Qt, Signal, QThread, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    ScrollArea, CardWidget, PushButton,
    BodyLabel, StrongBodyLabel, ComboBox, CheckBox, Slider, SpinBox,
    RadioButton, SwitchButton, FluentIcon as FIF, Theme, setTheme, isDarkTheme
)

from core.gpu_adapters import (
    GpuAdapter,
    adapter_to_selection,
    enumerate_gpu_adapters,
    resolve_saved_adapter,
)

try:
    from language_manager import tr, get_language_manager, get_supported_languages
    LANGUAGE_AVAILABLE = True
except ImportError:
    LANGUAGE_AVAILABLE = False
    def tr(key, default=None, **kwargs):
        return default if default is not None else key
    def get_language_manager():
        return None
    def get_supported_languages():
        return {"zh_CN": "简体中文", "en_US": "English"}


class GpuAdapterDiscoveryWorker(QThread):
    """Enumerates display adapters away from the Qt UI thread."""

    adapters_discovered = Signal(list)
    discovery_failed = Signal()

    def run(self):
        try:
            self.adapters_discovered.emit(enumerate_gpu_adapters())
        except Exception:
            self.discovery_failed.emit()


class SettingsInterface(ScrollArea):

    language_changed = Signal(str)
    theme_changed = Signal(str)  # 新增主题变化信号
    log_settings_changed = Signal(int, int)
    window_settings_changed = Signal(bool)
    gpu_acceleration_changed = Signal(bool)
    gpu_adapter_changed = Signal(dict)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._gpu_config: Dict[str, Any] = {}
        self._gpu_adapters: List[GpuAdapter] = []
        self._gpu_discovery_worker: Optional[GpuAdapterDiscoveryWorker] = None
        self._gpu_status = "disabled"
        self._ocr_running = False
        self._pending_default_gpu_selection: Optional[Dict[str, object]] = None
        self._default_selection_persisting = False
        self.setObjectName("settingsInterface")

        # Set transparent background for consistent appearance
        self.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._scroll_widget = QWidget()
        self._layout = QVBoxLayout(self._scroll_widget)
        self._layout.setContentsMargins(36, 24, 36, 24)
        self._layout.setSpacing(20)

        self.setWidget(self._scroll_widget)
        self.setWidgetResizable(True)

        self._init_theme_card()  # 新增主题设置卡片
        self._init_language_card()
        self._init_gpu_acceleration_card()
        self._init_window_card()
        self._init_log_card()
        self.retranslate_ui()

        self._layout.addStretch(1)

    def _init_theme_card(self):
        """初始化主题设置卡片"""
        self.theme_card = CardWidget(self)
        card_layout = QVBoxLayout(self.theme_card)

        self.theme_title_label = StrongBodyLabel()
        card_layout.addWidget(self.theme_title_label)

        row = QHBoxLayout()
        self.theme_mode_label = BodyLabel()
        row.addWidget(self.theme_mode_label)

        # 主题选项
        self.theme_light_radio = RadioButton()
        self.theme_dark_radio = RadioButton()
        self.theme_auto_radio = RadioButton()

        row.addWidget(self.theme_light_radio)
        row.addWidget(self.theme_dark_radio)
        row.addWidget(self.theme_auto_radio)
        row.addStretch()

        card_layout.addLayout(row)

        # 连接信号
        self.theme_light_radio.clicked.connect(lambda: self._on_theme_changed("light"))
        self.theme_dark_radio.clicked.connect(lambda: self._on_theme_changed("dark"))
        self.theme_auto_radio.clicked.connect(lambda: self._on_theme_changed("auto"))

        # 加载当前主题设置
        self._load_theme_setting()

        self._layout.addWidget(self.theme_card)

    def _load_theme_setting(self):
        """加载主题设置"""
        from core.settings_manager import SettingsManager
        settings = SettingsManager()
        theme_mode = settings.get("appearance.theme", "auto")

        if theme_mode == "light":
            self.theme_light_radio.setChecked(True)
        elif theme_mode == "dark":
            self.theme_dark_radio.setChecked(True)
        else:
            self.theme_auto_radio.setChecked(True)

    def _on_theme_changed(self, mode: str):
        """主题改变时的处理"""
        from core.settings_manager import SettingsManager
        settings = SettingsManager()
        settings.set("appearance.theme", mode, save=True)

        # 应用主题
        if mode == "light":
            setTheme(Theme.LIGHT)
        elif mode == "dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)

        # 发射信号通知主窗口更新自定义样式
        self.theme_changed.emit(mode)

    def _init_language_card(self):
        self.language_card = CardWidget(self)
        card_layout = QVBoxLayout(self.language_card)

        self.language_title_label = StrongBodyLabel()
        card_layout.addWidget(self.language_title_label)

        row = QHBoxLayout()
        self.interface_language_label = BodyLabel()
        row.addWidget(self.interface_language_label)

        self._language_combo = ComboBox()
        self._language_combo.setMinimumWidth(150)

        for code, name in get_supported_languages().items():
            self._language_combo.addItem(name, userData=code)

        if LANGUAGE_AVAILABLE:
            lm = get_language_manager()
            if lm:
                current_lang = lm.get_current_language()
                index = self._language_combo.findData(current_lang)
                if index >= 0:
                    self._language_combo.setCurrentIndex(index)

        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        row.addWidget(self._language_combo)

        row.addStretch()
        card_layout.addLayout(row)

        self._layout.addWidget(self.language_card)

    def _init_log_card(self):
        from core.settings_manager import SettingsManager
        settings = SettingsManager()

        self.log_card = CardWidget(self)
        card_layout = QVBoxLayout(self.log_card)

        self.log_title_label = StrongBodyLabel()
        card_layout.addWidget(self.log_title_label)

        count_row = QHBoxLayout()
        self.log_count_label = BodyLabel()
        count_row.addWidget(self.log_count_label)
        self.log_count_spin = SpinBox()
        self.log_count_spin.setRange(1, 200)
        self.log_count_spin.setValue(int(settings.get("logging.max_files", 20)))
        self.log_count_spin.valueChanged.connect(self._on_log_settings_changed)
        count_row.addWidget(self.log_count_spin)
        count_row.addStretch()
        card_layout.addLayout(count_row)

        size_row = QHBoxLayout()
        self.log_size_label = BodyLabel()
        size_row.addWidget(self.log_size_label)
        self.log_size_spin = SpinBox()
        self.log_size_spin.setRange(1, 2048)
        self.log_size_spin.setValue(int(settings.get("logging.max_file_size_mb", 500)))
        self.log_size_spin.valueChanged.connect(self._on_log_settings_changed)
        size_row.addWidget(self.log_size_spin)
        size_row.addStretch()
        card_layout.addLayout(size_row)

        self._layout.addWidget(self.log_card)

    def _init_gpu_acceleration_card(self):
        self.gpu_acceleration_card = CardWidget(self)
        card_layout = QVBoxLayout(self.gpu_acceleration_card)

        self.gpu_acceleration_title_label = StrongBodyLabel()
        card_layout.addWidget(self.gpu_acceleration_title_label)

        enabled_row = QHBoxLayout()
        self.gpu_acceleration_enabled_label = BodyLabel()
        enabled_row.addWidget(self.gpu_acceleration_enabled_label)
        self.gpu_acceleration_switch = SwitchButton()
        self.gpu_acceleration_switch.checkedChanged.connect(
            self._on_gpu_acceleration_toggled
        )
        enabled_row.addWidget(self.gpu_acceleration_switch)
        enabled_row.addStretch()
        card_layout.addLayout(enabled_row)

        adapter_row = QHBoxLayout()
        self.gpu_adapter_label = BodyLabel()
        adapter_row.addWidget(self.gpu_adapter_label)
        self.gpu_adapter_combo = ComboBox()
        self.gpu_adapter_combo.setMinimumWidth(240)
        self.gpu_adapter_combo.currentIndexChanged.connect(
            self._on_gpu_adapter_changed
        )
        adapter_row.addWidget(self.gpu_adapter_combo)
        adapter_row.addStretch()
        card_layout.addLayout(adapter_row)

        self.gpu_status_label = BodyLabel()
        card_layout.addWidget(self.gpu_status_label)
        self._layout.addWidget(self.gpu_acceleration_card)
        self._refresh_gpu_presentation()

    def set_gpu_configuration(self, config):
        """Show the OCR manager's authoritative persisted GPU configuration."""
        self._gpu_config = dict(config or {})
        enabled = bool(self._gpu_config.get("gpu_acceleration_enabled", False))
        blocker = QSignalBlocker(self.gpu_acceleration_switch)
        self.gpu_acceleration_switch.setChecked(enabled)
        del blocker

        if not enabled:
            self._pending_default_gpu_selection = None
            self._gpu_status = "disabled"
            self._clear_gpu_adapters()
        elif self._gpu_adapters:
            self._apply_discovered_gpu_adapters(self._gpu_adapters)
        else:
            self._start_gpu_discovery()
        self._refresh_gpu_presentation()

    def set_ocr_running(self, running: bool):
        was_running = self._ocr_running
        self._ocr_running = bool(running)
        self._refresh_gpu_presentation()
        if was_running and not self._ocr_running:
            self._persist_deferred_default_gpu_selection()

    def mark_gpu_unavailable(self):
        self._gpu_status = "unavailable"
        self._refresh_gpu_presentation()

    def _on_gpu_acceleration_toggled(self, enabled: bool):
        if self._ocr_running:
            self.set_gpu_configuration(self._gpu_config)
            return
        self.gpu_acceleration_changed.emit(bool(enabled))

    def _on_gpu_adapter_changed(self, index: int):
        if self._ocr_running or index < 0:
            return
        adapter = self.gpu_adapter_combo.itemData(index)
        if isinstance(adapter, GpuAdapter):
            self.gpu_adapter_changed.emit(adapter_to_selection(adapter))

    def _start_gpu_discovery(self):
        if self._ocr_running or self._gpu_discovery_worker is not None:
            return
        self._gpu_status = "detecting"
        self._refresh_gpu_presentation()
        self._gpu_discovery_worker = GpuAdapterDiscoveryWorker(self)
        self._gpu_discovery_worker.adapters_discovered.connect(
            self._on_gpu_adapters_discovered
        )
        self._gpu_discovery_worker.discovery_failed.connect(
            self._on_gpu_discovery_failed
        )
        self._gpu_discovery_worker.finished.connect(self._on_gpu_discovery_finished)
        self._gpu_discovery_worker.start()

    def _on_gpu_discovery_finished(self):
        worker = self._gpu_discovery_worker
        self._gpu_discovery_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_gpu_discovery_failed(self):
        if not self._gpu_config.get("gpu_acceleration_enabled", False):
            self._gpu_status = "disabled"
            self._clear_gpu_adapters()
            self._refresh_gpu_presentation()
            return
        self.mark_gpu_unavailable()

    def shutdown_gpu_discovery(self, timeout_ms: int = 1000) -> bool:
        """Wait for discovery to end before the owning UI can be destroyed."""
        worker = self._gpu_discovery_worker
        if worker is None:
            return True
        if worker.isRunning() and not worker.wait(max(0, int(timeout_ms))):
            if worker.isRunning():
                return False
        if worker.isRunning():
            return False
        if self._gpu_discovery_worker is worker:
            self._gpu_discovery_worker = None
            worker.deleteLater()
        return True

    def _on_gpu_adapters_discovered(self, adapters):
        if not self._gpu_config.get("gpu_acceleration_enabled", False):
            self._gpu_adapters = []
            self._gpu_status = "disabled"
            self._refresh_gpu_presentation()
            return
        self._gpu_adapters = list(adapters or [])
        if not self._gpu_adapters:
            self.mark_gpu_unavailable()
            return
        self._apply_discovered_gpu_adapters(self._gpu_adapters)

    def _apply_discovered_gpu_adapters(self, adapters: List[GpuAdapter]):
        saved_selection = self._gpu_config.get("gpu_adapter")
        selected_adapter = None
        blocker = QSignalBlocker(self.gpu_adapter_combo)
        self.gpu_adapter_combo.clear()
        for adapter in adapters:
            self.gpu_adapter_combo.addItem(adapter.name, userData=adapter)
        del blocker
        if saved_selection:
            try:
                selected_adapter = resolve_saved_adapter(saved_selection, adapters)
            except ValueError:
                blocker = QSignalBlocker(self.gpu_adapter_combo)
                self.gpu_adapter_combo.setCurrentIndex(-1)
                del blocker
                self.mark_gpu_unavailable()
                return
        else:
            selected_adapter = adapters[0]

        blocker = QSignalBlocker(self.gpu_adapter_combo)
        self.gpu_adapter_combo.setCurrentIndex(adapters.index(selected_adapter))
        del blocker

        self._gpu_status = "ready"
        self._refresh_gpu_presentation()
        if not saved_selection:
            selection = adapter_to_selection(selected_adapter)
            if self._ocr_running:
                self._pending_default_gpu_selection = selection
            elif not self._default_selection_persisting:
                self.gpu_adapter_changed.emit(selection)

    def _persist_deferred_default_gpu_selection(self):
        selection = self._pending_default_gpu_selection
        self._pending_default_gpu_selection = None
        if (
            selection is None
            or not self._gpu_config.get("gpu_acceleration_enabled", False)
            or self._gpu_config.get("gpu_adapter")
        ):
            return
        self._default_selection_persisting = True
        try:
            self.gpu_adapter_changed.emit(selection)
        finally:
            self._default_selection_persisting = False

    def _clear_gpu_adapters(self):
        self._gpu_adapters = []
        blocker = QSignalBlocker(self.gpu_adapter_combo)
        self.gpu_adapter_combo.clear()
        del blocker

    def _refresh_gpu_presentation(self):
        enabled = bool(self._gpu_config.get("gpu_acceleration_enabled", False))
        self.gpu_acceleration_switch.setEnabled(not self._ocr_running)
        self.gpu_adapter_combo.setEnabled(
            not self._ocr_running
            and enabled
            and self._gpu_status in ("ready", "unavailable")
            and bool(self._gpu_adapters)
        )
        status_keys = {
            "disabled": "settings_gpu_status_disabled",
            "detecting": "settings_gpu_status_detecting",
            "ready": "settings_gpu_status_ready",
            "unavailable": "settings_gpu_status_unavailable",
        }
        self.gpu_status_label.setText(tr(status_keys[self._gpu_status]))

    def _init_window_card(self):
        from core.settings_manager import SettingsManager
        settings = SettingsManager()

        self.window_card = CardWidget(self)
        card_layout = QVBoxLayout(self.window_card)

        self.window_title_label = StrongBodyLabel()
        card_layout.addWidget(self.window_title_label)

        self.remember_map_window_geometry_check = CheckBox()
        self.remember_map_window_geometry_check.setChecked(
            bool(settings.get("window.remember_map_window_geometry", True))
        )
        self.remember_map_window_geometry_check.stateChanged.connect(
            lambda state: self._on_window_settings_changed(
                state == Qt.CheckState.Checked.value
            )
        )
        card_layout.addWidget(self.remember_map_window_geometry_check)

        self._layout.addWidget(self.window_card)

    def _on_language_changed(self, index: int):
        lang_code = self._language_combo.itemData(index)
        if lang_code:
            self.language_changed.emit(lang_code)

    def retranslate_ui(self):
        self.theme_title_label.setText(tr("settings_appearance", "外观设置"))
        self.theme_mode_label.setText(tr("settings_theme_mode", "主题模式:"))
        self.theme_light_radio.setText(tr("settings_theme_light", "浅色"))
        self.theme_dark_radio.setText(tr("settings_theme_dark", "深色"))
        self.theme_auto_radio.setText(tr("settings_theme_auto", "跟随系统"))

        self.language_title_label.setText(tr("settings_language", "语言设置"))
        self.interface_language_label.setText(
            tr("settings_interface_language", "界面语言:")
        )

        self.gpu_acceleration_title_label.setText(
            tr("settings_gpu_acceleration")
        )
        self.gpu_acceleration_enabled_label.setText(
            tr("settings_gpu_acceleration_enabled")
        )
        self.gpu_adapter_label.setText(tr("settings_gpu_adapter"))
        self._refresh_gpu_presentation()

        self.window_title_label.setText(tr("settings_window", "窗口设置"))
        self.remember_map_window_geometry_check.setText(
            tr("settings_remember_map_window_geometry", "记住地图窗口位置和大小")
        )

        self.log_title_label.setText(tr("settings_logs", "日志设置"))
        self.log_count_label.setText(
            tr("settings_log_retention_count", "保留日志数量:")
        )
        self.log_size_label.setText(
            tr("settings_log_max_file_size_mb", "单个日志大小上限(MB):")
        )

    def get_current_language(self) -> str:
        return self._language_combo.currentData() or "zh_CN"

    def update_theme(self):
        """更新主题样式"""
        from core.theme_manager import ThemeManager
        card_style = ThemeManager.get_card_widget_style()
        self._scroll_widget.setStyleSheet(ThemeManager.get_page_background_style())
        checkbox_style = ThemeManager.get_check_box_style()
        self.theme_card.setStyleSheet(card_style)
        self.language_card.setStyleSheet(card_style)
        self.gpu_acceleration_card.setStyleSheet(card_style)
        self.window_card.setStyleSheet(card_style)
        self.log_card.setStyleSheet(card_style)
        self.remember_map_window_geometry_check.setStyleSheet(checkbox_style)

    def _on_log_settings_changed(self):
        from core.settings_manager import SettingsManager
        settings = SettingsManager()
        max_files = int(self.log_count_spin.value())
        max_size_mb = int(self.log_size_spin.value())
        settings.set("logging.max_files", max_files, save=True)
        settings.set("logging.max_file_size_mb", max_size_mb, save=True)
        self.log_settings_changed.emit(max_files, max_size_mb)

    def _on_window_settings_changed(self, enabled: bool):
        from core.settings_manager import SettingsManager
        settings = SettingsManager()
        settings.set("window.remember_map_window_geometry", enabled, save=True)
        self.window_settings_changed.emit(enabled)
