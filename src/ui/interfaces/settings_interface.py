# -*- coding: utf-8 -*-
from typing import Optional, List
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    ScrollArea, CardWidget, PushButton,
    BodyLabel, StrongBodyLabel, ComboBox, CheckBox, Slider, SpinBox,
    RadioButton, FluentIcon as FIF, Theme, setTheme, isDarkTheme
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


class SettingsInterface(ScrollArea):

    language_changed = Signal(str)
    theme_changed = Signal(str)  # 新增主题变化信号
    log_settings_changed = Signal(int, int)
    window_settings_changed = Signal(bool)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
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
