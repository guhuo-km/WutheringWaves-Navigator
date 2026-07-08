# -*- coding: utf-8 -*-
"""
OCR设置页面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame
)
from PySide6.QtCore import Signal
from qfluentwidgets import (
    BodyLabel, SubtitleLabel, PushButton, 
    ComboBox, SpinBox, DoubleSpinBox, LineEdit, CardWidget, SwitchButton,
    ScrollArea, FluentIcon as FIF
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

from core.settings_manager import SettingsManager


class OCRSettingsInterface(QWidget):
    """OCR设置页面"""
    
    window_select_requested = Signal()
    settings_changed = Signal()
    preview_hover_enter = Signal()
    preview_hover_leave = Signal()
    auto_detect_toggled = Signal(bool)
    minimap_auto_calibration_toggled = Signal(bool)
    minimap_manual_calibration_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('ocrSettingsInterface')
        self.settings = SettingsManager()
        self._loading_settings = False
        self._auto_window_status = {"state": "searching", "countdown": 5}
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._scroll_area = ScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._scroll_widget = QWidget()
        layout = QVBoxLayout(self._scroll_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        self._scroll_area.setWidget(self._scroll_widget)
        root_layout.addWidget(self._scroll_area)
        
        # === 基本设置 ===
        self.basic_card = CardWidget(self._scroll_widget)
        basic_layout = QVBoxLayout(self.basic_card)
        
        self.basic_title_label = SubtitleLabel()
        basic_layout.addWidget(self.basic_title_label)
        
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        
        # 截图方式
        self.capture_mode_label = BodyLabel()
        grid.addWidget(self.capture_mode_label, 0, 0)
        self.capture_mode = ComboBox()
        self.capture_mode.addItems(["", ""])
        self.capture_mode.currentIndexChanged.connect(self.on_settings_changed)
        grid.addWidget(self.capture_mode, 0, 1)
        
        # 目标窗口
        self.target_window_label = BodyLabel()
        grid.addWidget(self.target_window_label, 1, 0)
        window_layout = QHBoxLayout()
        self.target_window = LineEdit()
        self.target_window.textChanged.connect(self.on_settings_changed)
        window_layout.addWidget(self.target_window, 1)

        self.select_window_btn = PushButton()
        self.select_window_btn.clicked.connect(self._select_window)
        window_layout.addWidget(self.select_window_btn)
        grid.addLayout(window_layout, 1, 1)
        
        # 识别间隔
        self.interval_label = BodyLabel()
        grid.addWidget(self.interval_label, 2, 0)
        self.interval_spin = SpinBox()
        self.interval_spin.setRange(100, 2000)
        self.interval_spin.setValue(500)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.valueChanged.connect(self.on_settings_changed)
        grid.addWidget(self.interval_spin, 2, 1)

        # 数字识别置信阈值
        self.digit_confidence_label = BodyLabel()
        grid.addWidget(self.digit_confidence_label, 3, 0)
        self.digit_conf_threshold_spin = DoubleSpinBox()
        self.digit_conf_threshold_spin.setRange(0.01, 1.00)
        self.digit_conf_threshold_spin.setSingleStep(0.01)
        self.digit_conf_threshold_spin.setDecimals(2)
        self.digit_conf_threshold_spin.setValue(0.45)
        self.digit_conf_threshold_spin.valueChanged.connect(self.on_settings_changed)
        grid.addWidget(self.digit_conf_threshold_spin, 3, 1)

        # 符号识别置信阈值
        self.symbol_confidence_label = BodyLabel()
        grid.addWidget(self.symbol_confidence_label, 4, 0)
        self.symbol_conf_threshold_spin = DoubleSpinBox()
        self.symbol_conf_threshold_spin.setRange(0.01, 1.00)
        self.symbol_conf_threshold_spin.setSingleStep(0.01)
        self.symbol_conf_threshold_spin.setDecimals(2)
        self.symbol_conf_threshold_spin.setValue(0.45)
        self.symbol_conf_threshold_spin.valueChanged.connect(self.on_settings_changed)
        grid.addWidget(self.symbol_conf_threshold_spin, 4, 1)

        # OCR自动校准/自动检测窗口开关（默认开启）
        self.auto_calibration_label = BodyLabel()
        grid.addWidget(self.auto_calibration_label, 5, 0)
        auto_detect_row = QHBoxLayout()
        self._auto_detect_switch = SwitchButton()
        self._auto_detect_switch.checkedChanged.connect(self._on_auto_detect_toggled)
        auto_detect_row.addWidget(self._auto_detect_switch)
        self.auto_detect_hint = BodyLabel()
        self.auto_detect_hint.setStyleSheet("color: #888;")
        auto_detect_row.addWidget(self.auto_detect_hint)
        auto_detect_row.addStretch()
        grid.addLayout(auto_detect_row, 5, 1)

        # 小地图自动校准开关（默认开启）
        self.minimap_auto_calibration_label = BodyLabel()
        grid.addWidget(self.minimap_auto_calibration_label, 6, 0)
        minimap_auto_row = QHBoxLayout()
        self.minimap_auto_calibration_switch = SwitchButton()
        self.minimap_auto_calibration_switch.checkedChanged.connect(self._on_minimap_auto_calibration_toggled)
        minimap_auto_row.addWidget(self.minimap_auto_calibration_switch)
        self.minimap_auto_calibration_hint = BodyLabel()
        self.minimap_auto_calibration_hint.setStyleSheet("color: #888;")
        minimap_auto_row.addWidget(self.minimap_auto_calibration_hint)
        minimap_auto_row.addStretch()
        grid.addLayout(minimap_auto_row, 6, 1)

        self.heading_recognition_enabled_label = BodyLabel()
        grid.addWidget(self.heading_recognition_enabled_label, 7, 0)
        heading_enabled_row = QHBoxLayout()
        self.heading_recognition_enabled_switch = SwitchButton()
        self.heading_recognition_enabled_switch.checkedChanged.connect(self.on_settings_changed)
        heading_enabled_row.addWidget(self.heading_recognition_enabled_switch)
        heading_enabled_row.addStretch()
        grid.addLayout(heading_enabled_row, 7, 1)
        
        basic_layout.addLayout(grid)

        self.status_divider = QFrame()
        self.status_divider.setFrameShape(QFrame.Shape.HLine)
        self.status_divider.setFrameShadow(QFrame.Shadow.Sunken)
        basic_layout.addWidget(self.status_divider)

        # Option A: Header with preview button
        status_header = QHBoxLayout()
        self.status_title_label = BodyLabel()
        self.status_title_label.setStyleSheet("font-weight: bold;")
        status_header.addWidget(self.status_title_label)
        status_header.addStretch()

        # Create hover-triggered preview button
        self.preview_button = PushButton(FIF.VIEW, "")
        # Install event filter to detect hover
        self.preview_button.installEventFilter(self)
        status_header.addWidget(self.preview_button)

        basic_layout.addLayout(status_header)

        self._ocr_status_label = BodyLabel()
        self._ocr_status_label.setWordWrap(True)
        basic_layout.addWidget(self._ocr_status_label)

        self._ocr_window_label = BodyLabel()
        basic_layout.addWidget(self._ocr_window_label)

        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self._ocr_mode_label = BodyLabel()
        self._ocr_resolution_label = BodyLabel()
        self._ocr_position_label = BodyLabel()
        info_row.addWidget(self._ocr_mode_label)
        info_row.addWidget(self._ocr_resolution_label)
        info_row.addWidget(self._ocr_position_label)
        info_row.addStretch()
        basic_layout.addLayout(info_row)

        action_row = QHBoxLayout()
        self.ocr_manual_calibrate_btn = PushButton()
        self.ocr_manual_calibrate_btn.clicked.connect(self.window_select_requested.emit)
        action_row.addWidget(self.ocr_manual_calibrate_btn)
        self.minimap_manual_calibrate_btn = PushButton()
        self.minimap_manual_calibrate_btn.clicked.connect(self.minimap_manual_calibration_requested.emit)
        action_row.addWidget(self.minimap_manual_calibrate_btn)
        action_row.addStretch()
        basic_layout.addLayout(action_row)

        self.params_divider = QFrame()
        self.params_divider.setFrameShape(QFrame.Shape.HLine)
        self.params_divider.setFrameShadow(QFrame.Shadow.Sunken)
        basic_layout.addWidget(self.params_divider)

        self.recognition_params_title_label = BodyLabel()
        self.recognition_params_title_label.setStyleSheet("font-weight: bold;")
        basic_layout.addWidget(self.recognition_params_title_label)

        threshold_grid = QGridLayout()
        threshold_grid.setVerticalSpacing(10)
        self.coordinate_agreement_xy_threshold_label = BodyLabel()
        threshold_grid.addWidget(self.coordinate_agreement_xy_threshold_label, 0, 0)
        threshold_grid.addWidget(BodyLabel("X"), 0, 1)
        self.coordinate_agreement_x_threshold_spin = self._create_int_spin(
            1, 100000, "minimap_stability.coordinate_agreement_x_threshold", 50
        )
        threshold_grid.addWidget(self.coordinate_agreement_x_threshold_spin, 0, 2)
        threshold_grid.addWidget(BodyLabel("Y"), 0, 3)
        self.coordinate_agreement_y_threshold_spin = self._create_int_spin(
            1, 100000, "minimap_stability.coordinate_agreement_y_threshold", 50
        )
        threshold_grid.addWidget(self.coordinate_agreement_y_threshold_spin, 0, 4)

        self.history_xy_threshold_label = BodyLabel()
        threshold_grid.addWidget(self.history_xy_threshold_label, 1, 0)
        threshold_grid.addWidget(BodyLabel("X"), 1, 1)
        self.history_x_threshold_spin = self._create_int_spin(
            1, 100000, "minimap_stability.history_x_threshold", 150
        )
        threshold_grid.addWidget(self.history_x_threshold_spin, 1, 2)
        threshold_grid.addWidget(BodyLabel("Y"), 1, 3)
        self.history_y_threshold_spin = self._create_int_spin(
            1, 100000, "minimap_stability.history_y_threshold", 150
        )
        threshold_grid.addWidget(self.history_y_threshold_spin, 1, 4)

        self.auto_roi_lock_tolerance_label = BodyLabel()
        threshold_grid.addWidget(self.auto_roi_lock_tolerance_label, 2, 0)
        self.auto_roi_lock_tolerance_spin = self._create_int_spin(
            0, 100, "minimap_stability.auto_roi_lock_tolerance_px", 2
        )
        threshold_grid.addWidget(self.auto_roi_lock_tolerance_spin, 2, 2)

        self.rough_candidate_limit_label = BodyLabel()
        threshold_grid.addWidget(self.rough_candidate_limit_label, 3, 0)
        self.rough_candidate_limit_spin = self._create_int_spin(
            1, 100, "minimap_stability.rough_candidate_limit", 20
        )
        threshold_grid.addWidget(self.rough_candidate_limit_spin, 3, 2)
        threshold_grid.setColumnStretch(4, 1)
        basic_layout.addLayout(threshold_grid)

        layout.addWidget(self.basic_card)
        layout.addStretch()
        self.retranslate_ui()
        self.update_theme()

    def _create_int_spin(self, minimum: int, maximum: int, setting_key: str, default: int) -> SpinBox:
        spin = SpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(int(self.settings.get(setting_key, default)))
        spin.valueChanged.connect(lambda value, key=setting_key: self.settings.set(key, int(value)))
        return spin
    
    def set_target_window(self, name: str):
        self.target_window.setText(name)
        self.settings.set("ocr.target_window", name)

    def _select_window(self):
        """打开窗口选择对话框"""
        try:
            from PySide6.QtWidgets import QDialog, QMessageBox
            from ui.dialogs.window_selection_dialog import WindowSelectionDialog

            dialog = WindowSelectionDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_window = dialog.get_selected_window()
                if selected_window:
                    self.target_window.setText(selected_window)
                    self.settings.set("ocr.target_window", selected_window)
                    self.settings_changed.emit()
                    QMessageBox.information(
                        self,
                        tr("ocr_select_success_title", "选择成功"),
                        tr("ocr_select_success_message", "已选择窗口: {window}", window=selected_window),
                    )
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                tr("ocr_select_error_title", "错误"),
                tr("ocr_select_error_message", "打开窗口选择对话框失败: {error}", error=e),
            )

    def on_settings_changed(self):
        if self._loading_settings:
            return
        # Save screenshot mode as string (BitBlt or PrintWindow)
        mode = "BitBlt" if self.capture_mode.currentIndex() == 0 else "PrintWindow"
        self.settings.set("ocr.screenshot_mode", mode)
        self.settings.set("ocr.interval", self.interval_spin.value())
        self.settings.set("ocr.digit_confidence_threshold", float(self.digit_conf_threshold_spin.value()))
        self.settings.set("ocr.symbol_confidence_threshold", float(self.symbol_conf_threshold_spin.value()))
        self.settings.set("ocr.target_window", self.target_window.text())
        self.settings.set("ocr.auto_detect_region_enabled", self._auto_detect_switch.isChecked())
        self.settings.set("minimap_roi.auto_calibration_enabled", self.minimap_auto_calibration_switch.isChecked())
        self.settings.set("minimap_stability.heading_recognition_enabled", self.heading_recognition_enabled_switch.isChecked())
        self.settings_changed.emit()

    def _on_auto_detect_toggled(self, checked: bool):
        if self._loading_settings:
            return
        self.settings.set("ocr.auto_detect_region_enabled", checked)
        self.auto_detect_toggled.emit(checked)
        self.settings_changed.emit()

    def _on_minimap_auto_calibration_toggled(self, checked: bool):
        if self._loading_settings:
            return
        self.settings.set("minimap_roi.auto_calibration_enabled", checked)
        self._refresh_minimap_manual_button_state()
        self.minimap_auto_calibration_toggled.emit(checked)
        self.settings_changed.emit()

    def load_settings(self):
        self._loading_settings = True
        try:
        # Load screenshot mode and set index accordingly
            mode = self.settings.get("ocr.screenshot_mode", "BitBlt")
            self.capture_mode.setCurrentIndex(1 if mode == "PrintWindow" else 0)
            self.interval_spin.setValue(self.settings.get("ocr.interval", 500))
            self.digit_conf_threshold_spin.setValue(
                float(self.settings.get("ocr.digit_confidence_threshold", 0.45))
            )
            self.symbol_conf_threshold_spin.setValue(
                float(self.settings.get("ocr.symbol_confidence_threshold", 0.45))
            )
            window = self.settings.get("ocr.target_window", "")
            if window:
                self.target_window.setText(window)

            # 默认开启 + 持久化兜底
            auto_detect = bool(self.settings.get("ocr.auto_detect_region_enabled", True))
            self._auto_detect_switch.setChecked(auto_detect)
            self.settings.set("ocr.auto_detect_region_enabled", auto_detect)
            minimap_auto = bool(self.settings.get("minimap_roi.auto_calibration_enabled", True))
            self.minimap_auto_calibration_switch.setChecked(minimap_auto)
            self.settings.set("minimap_roi.auto_calibration_enabled", minimap_auto)
            heading_enabled = bool(self.settings.get("minimap_stability.heading_recognition_enabled", True))
            self.heading_recognition_enabled_switch.setChecked(heading_enabled)
            self.settings.set("minimap_stability.heading_recognition_enabled", heading_enabled)
            self._refresh_minimap_manual_button_state()
        finally:
            self._loading_settings = False

    def is_auto_detect_enabled(self) -> bool:
        return bool(self._auto_detect_switch.isChecked())

    def is_minimap_auto_calibration_enabled(self) -> bool:
        return bool(self.minimap_auto_calibration_switch.isChecked())

    def get_interval(self) -> int:
        return int(self.interval_spin.value())

    def get_screenshot_mode(self) -> str:
        return "BitBlt" if self.capture_mode.currentIndex() == 0 else "PrintWindow"

    def get_target_window_name(self) -> str:
        return self.target_window.text().strip()

    def get_digit_confidence_threshold(self) -> float:
        return float(self.digit_conf_threshold_spin.value())

    def get_symbol_confidence_threshold(self) -> float:
        return float(self.symbol_conf_threshold_spin.value())

    def is_heading_recognition_enabled(self) -> bool:
        return bool(self.heading_recognition_enabled_switch.isChecked())

    def update_auto_window_status(self, status: dict):
        self._auto_window_status = dict(status)
        self._redraw_auto_window_status()

    def _redraw_auto_window_status(self):
        status = self._auto_window_status
        state = status.get("state", "")
        countdown = status.get("countdown", 0)
        title = status.get("title", tr("ocr_unknown", "未识别"))
        mode = status.get("mode", "--")
        width = status.get("width")
        height = status.get("height")
        x = status.get("x")
        y = status.get("y")
        message = status.get("message", "")

        mode_map = {
            "fullscreen": tr("ocr_mode_fullscreen", "全屏"),
            "borderless": tr("ocr_mode_borderless", "无边框窗口"),
            "windowed": tr("ocr_mode_windowed", "窗口")
        }
        mode_text = mode_map.get(mode, "--")

        if state == "searching":
            self._ocr_status_label.setText(
                tr("ocr_auto_searching", "游戏窗口未找到，{countdown}秒后重试…", countdown=countdown)
            )
            self._ocr_window_label.setText(tr("ocr_window_unknown", "窗口：未识别"))
            self._ocr_mode_label.setText(tr("ocr_mode_empty", "模式：--"))
            self._ocr_resolution_label.setText(tr("ocr_resolution_empty", "分辨率：--"))
            self._ocr_position_label.setText(tr("ocr_position_empty", "位置：--"))
            return

        if state == "error":
            self._ocr_status_label.setText(
                tr("ocr_detect_failed", "窗口检测失败：{message}", message=message)
            )
            return

        if state == "manual_skip":
            self._ocr_status_label.setText(
                tr("ocr_detect_manual_skip", "识别到游戏窗口“{title}”，已存在手动OCR区域，未覆盖", title=title)
            )
        elif state == "found":
            self._ocr_status_label.setText(
                tr("ocr_detect_found", "识别到游戏窗口“{title}”", title=title)
            )
        else:
            self._ocr_status_label.setText(tr("ocr_region_status_empty", "识别区域状态：--"))

        self._ocr_window_label.setText(tr("ocr_window_value", "窗口：{title}", title=title))
        self._ocr_mode_label.setText(tr("ocr_mode_value", "模式：{mode}", mode=mode_text))
        if width is not None and height is not None:
            self._ocr_resolution_label.setText(
                tr("ocr_resolution_value", "分辨率：{width}*{height}", width=width, height=height)
            )
        else:
            self._ocr_resolution_label.setText(tr("ocr_resolution_empty", "分辨率：--"))
        if x is not None and y is not None:
            self._ocr_position_label.setText(
                tr("ocr_position_value", "位置：{x}*{y}", x=x, y=y)
            )
        else:
            self._ocr_position_label.setText(tr("ocr_position_empty", "位置：--"))

    def _refresh_minimap_manual_button_state(self):
        auto_enabled = bool(self.minimap_auto_calibration_switch.isChecked())
        self.minimap_manual_calibrate_btn.setEnabled(not auto_enabled)

    def update_theme(self):
        from core.theme_manager import ThemeManager

        self._scroll_widget.setStyleSheet(ThemeManager.get_page_background_style())
        self.basic_card.setStyleSheet(ThemeManager.get_card_widget_style())
        separator_color = ThemeManager.get_separator_color()
        for divider in (self.status_divider, self.params_divider):
            divider.setStyleSheet(f"background-color: {separator_color};")

    def retranslate_ui(self):
        self.basic_title_label.setText(tr("ocr_basic_settings", "识别设置"))
        self.capture_mode_label.setText(tr("ocr_capture_mode", "截图方式:"))
        self.capture_mode.setItemText(0, tr("ocr_capture_mode_bitblt", "BitBlt (默认)"))
        self.capture_mode.setItemText(1, tr("ocr_capture_mode_printwindow", "PrintWindow"))
        self.capture_mode.setToolTip(
            tr(
                "ocr_capture_mode_tooltip",
                "BitBlt: 快速截图，适用于大多数情况\nPrintWindow: 窗口截图，适用于某些特殊窗口",
            )
        )
        self.target_window_label.setText(tr("ocr_target_window", "目标窗口:"))
        self.target_window.setPlaceholderText(
            tr("ocr_target_window_placeholder", "留空使用全屏截图，或输入/选择窗口名称")
        )
        self.select_window_btn.setText(tr("ocr_select_window", "选择窗口"))
        self.interval_label.setText(tr("ocr_interval_ms", "截图/识别间隔 (ms):"))
        self.digit_confidence_label.setText(tr("ocr_digit_confidence", "数字识别置信阈值:"))
        self.symbol_confidence_label.setText(tr("ocr_symbol_confidence", "符号识别置信阈值:"))
        self.auto_calibration_label.setText(tr("ocr_auto_calibration", "OCR自动校准:"))
        self._auto_detect_switch.setOnText(tr("ocr_switch_on", "开"))
        self._auto_detect_switch.setOffText(tr("ocr_switch_off", "关"))
        self.auto_detect_hint.setText(tr("ocr_auto_detect_hint", "开启后自动检测游戏窗口并设置OCR区域"))
        self.minimap_auto_calibration_label.setText(tr("ocr_minimap_auto_calibration", "小地图自动校准:"))
        self.minimap_auto_calibration_switch.setOnText(tr("ocr_switch_on", "开"))
        self.minimap_auto_calibration_switch.setOffText(tr("ocr_switch_off", "关"))
        self.minimap_auto_calibration_hint.setText(tr("ocr_minimap_auto_detect_hint", "开启后自动识别小地图区域"))
        self.heading_recognition_enabled_label.setText(tr("ocr_heading_recognition_enabled", "人物朝向识别:"))
        self.heading_recognition_enabled_switch.setOnText(tr("ocr_switch_on", "开"))
        self.heading_recognition_enabled_switch.setOffText(tr("ocr_switch_off", "关"))
        self.status_title_label.setText(tr("ocr_region_status_title", "识别区域状态"))
        self.preview_button.setText(tr("ocr_preview_region", "预览区域"))
        self.preview_button.setToolTip(tr("ocr_preview_region_tooltip", "悬停鼠标查看识别区域"))
        self.ocr_manual_calibrate_btn.setText(tr("ocr_manual_calibrate_region", "校准OCR区域"))
        self.minimap_manual_calibrate_btn.setText(tr("ocr_manual_calibrate_minimap_region", "校准小地图区域"))
        self.recognition_params_title_label.setText(tr("ocr_recognition_params_title", "识别参数"))
        self.coordinate_agreement_xy_threshold_label.setText(tr("ocr_coordinate_agreement_xy_threshold", "OCR/视觉一致阈值"))
        self.history_xy_threshold_label.setText(tr("ocr_history_xy_threshold", "历史连续性阈值"))
        self.auto_roi_lock_tolerance_label.setText(tr("ocr_auto_roi_lock_tolerance", "ROI锁定误差(px)"))
        self.rough_candidate_limit_label.setText(tr("ocr_rough_candidate_limit", "粗筛候选数量"))
        self._refresh_minimap_manual_button_state()
        self._redraw_auto_window_status()
    
    def eventFilter(self, obj, event):
        """Event filter to detect hover on preview button."""
        from PySide6.QtCore import QEvent
        
        if obj == self.preview_button:
            if event.type() == QEvent.Type.Enter:
                self.preview_hover_enter.emit()
                return False
            elif event.type() == QEvent.Type.Leave:
                self.preview_hover_leave.emit()
                return False
        
        return super().eventFilter(obj, event)
