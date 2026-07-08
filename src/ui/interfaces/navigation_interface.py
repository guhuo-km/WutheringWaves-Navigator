# -*- coding: utf-8 -*-
"""
导航控制面板 - 优化布局版本
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    BodyLabel, PushButton, PrimaryPushButton,
    RadioButton, CheckBox, Slider, CardWidget, LineEdit,
    StrongBodyLabel, SingleDirectionScrollArea
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key


class NavigationInterface(SingleDirectionScrollArea):
    """导航控制面板（支持垂直滚动）"""

    # 信号定义
    ocr_start_requested = Signal()
    ocr_stop_requested = Signal()
    ocr_calibrate_requested = Signal()
    map_source_changed = Signal(str)  # 'official', 'local'
    map_calibrate_requested = Signal()
    map_recapture_requested = Signal()
    dot_size_changed = Signal(float)
    route_start_requested = Signal()
    route_stop_requested = Signal()
    window_topmost_changed = Signal(bool)
    window_passthrough_changed = Signal(bool)
    window_frameless_changed = Signal(bool)
    window_opacity_changed = Signal(int)
    main_topmost_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('navigationInterface')
        self._ocr_running = False
        self._coordinates = None
        self._ocr_region = None
        self._ocr_region_source = "none"
        self._map_status = None
        self._area_id = None
        self._calibration_text = tr("not_calibrated", "未校准")
        self._calibration_ok = False
        self._route_recording = False
        self._route_count = 0
        self.setup_ui()

    def setup_ui(self):
        """设置用户界面"""
        # 创建滚动内容容器
        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName('navigationScrollWidget')
        
        main_layout = QVBoxLayout(self.scroll_widget)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # === 窗口控制卡片 ===
        window_card = self._create_window_card()
        main_layout.addWidget(window_card)

        # === OCR 控制卡片 ===
        ocr_card = self._create_ocr_card()
        main_layout.addWidget(ocr_card)

        # === 地图控制卡片 ===
        map_card = self._create_map_card()
        main_layout.addWidget(map_card)

        # === 路线录制卡片 ===
        route_card = self._create_route_card()
        main_layout.addWidget(route_card)

        main_layout.addStretch()
        
        # 配置滚动区域
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.retranslate_ui()

    def _create_ocr_card(self):
        """创建 OCR 控制卡片"""
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        self.ocr_title_label = StrongBodyLabel()
        card_layout.addWidget(self.ocr_title_label)

        # 启动/停止 OCR 按钮（整行宽度，根据状态切换文字和颜色）
        self.ocr_toggle_btn = PrimaryPushButton()
        self.ocr_toggle_btn.clicked.connect(self._on_ocr_toggle_clicked)
        self._update_ocr_button_style()
        card_layout.addWidget(self.ocr_toggle_btn)

        # 校准 OCR 区域按钮（整行宽度，换行）
        self.ocr_calibrate_btn = PushButton()
        self.ocr_calibrate_btn.clicked.connect(self.ocr_calibrate_requested.emit)
        card_layout.addWidget(self.ocr_calibrate_btn)

        # 状态信息行
        status_layout = QHBoxLayout()
        status_layout.setSpacing(20)

        self.ocr_status_label = BodyLabel()
        status_layout.addWidget(self.ocr_status_label)

        self.coord_label = BodyLabel()
        status_layout.addWidget(self.coord_label)

        status_layout.addStretch()
        card_layout.addLayout(status_layout)

        # OCR 区域信息行（坐标 + 大小 + 来源）
        region_layout = QHBoxLayout()
        region_layout.setSpacing(20)

        self.ocr_region_label = BodyLabel()
        region_layout.addWidget(self.ocr_region_label)

        self.ocr_region_source_label = BodyLabel()
        region_layout.addWidget(self.ocr_region_source_label)

        region_layout.addStretch()
        card_layout.addLayout(region_layout)

        return card

    def _on_ocr_toggle_clicked(self):
        """处理 OCR 启动/停止按钮点击"""
        if self._ocr_running:
            # 当前运行中，点击后停止
            self.ocr_stop_requested.emit()
        else:
            # 当前未运行，点击后启动
            self.ocr_start_requested.emit()

    def _update_ocr_button_style(self):
        """更新 OCR 按钮的文字和颜色"""
        if self._ocr_running:
            # 运行中 - 红色停止按钮
            self.ocr_toggle_btn.setText(tr("nav_stop_ocr", "停止 OCR"))
            self.ocr_toggle_btn.setStyleSheet("""
                PrimaryPushButton {
                    background-color: #E74C3C;
                    border: 1px solid #C0392B;
                    color: white;
                }
                PrimaryPushButton:hover {
                    background-color: #C0392B;
                }
                PrimaryPushButton:pressed {
                    background-color: #A93226;
                }
            """)
        else:
            # 未启动 - 绿色启动按钮
            self.ocr_toggle_btn.setText(tr("nav_start_ocr", "启动 OCR"))
            self.ocr_toggle_btn.setStyleSheet("""
                PrimaryPushButton {
                    background-color: #27AE60;
                    border: 1px solid #229954;
                    color: white;
                }
                PrimaryPushButton:hover {
                    background-color: #229954;
                }
                PrimaryPushButton:pressed {
                    background-color: #1E8449;
                }
            """)

    def _create_map_card(self):
        """创建地图控制卡片"""
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        self.map_title_label = StrongBodyLabel()
        card_layout.addWidget(self.map_title_label)

        # 地图源选择标签
        self.map_source_label = BodyLabel()
        card_layout.addWidget(self.map_source_label)

        # 地图源单选按钮（垂直排列避免挤压）
        self.radio_official = RadioButton()
        self.radio_official.setChecked(True)
        self.radio_official.toggled.connect(lambda checked: checked and self.map_source_changed.emit('official'))
        card_layout.addWidget(self.radio_official)

        self.radio_local = RadioButton()
        self.radio_local.toggled.connect(lambda checked: checked and self.map_source_changed.emit('local'))
        card_layout.addWidget(self.radio_local)

        # 操作按钮行
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self.map_calibrate_btn = PrimaryPushButton()
        self.map_calibrate_btn.setFixedWidth(120)
        self.map_calibrate_btn.clicked.connect(self.map_calibrate_requested.emit)
        action_layout.addWidget(self.map_calibrate_btn)

        self.map_recapture_btn = PushButton()
        self.map_recapture_btn.setFixedWidth(120)
        self.map_recapture_btn.clicked.connect(self.map_recapture_requested.emit)
        action_layout.addWidget(self.map_recapture_btn)

        action_layout.addStretch()
        card_layout.addLayout(action_layout)

        # 状态行（保留以保持向后兼容）
        self.map_status_label = BodyLabel()
        card_layout.addWidget(self.map_status_label)

        # 区域ID行（独立显示，避免覆盖实时状态）
        self.map_area_label = BodyLabel()
        card_layout.addWidget(self.map_area_label)

        self.calibration_status_label = BodyLabel()
        card_layout.addWidget(self.calibration_status_label)

        # 圆点大小控制
        dot_layout = QHBoxLayout()
        dot_layout.setSpacing(12)

        self.dot_size_label = BodyLabel()
        dot_layout.addWidget(self.dot_size_label)

        self.dot_size_slider = Slider(Qt.Horizontal)
        # 百分比以 0.1 为步进：1.0%~200.0% => 滑块值 10~2000
        self.dot_size_slider.setRange(10, 2000)
        self.dot_size_slider.setValue(500)  # 50.0%
        self.dot_size_slider.valueChanged.connect(self._on_dot_size_slider_changed)
        dot_layout.addWidget(self.dot_size_slider, 1)

        # 右侧可直接输入百分比（支持小数，无上下箭头）
        self.dot_size_value = LineEdit()
        self.dot_size_value.setText("50.0%")
        self.dot_size_value.setPlaceholderText("1.0%-200.0%")
        self.dot_size_value.setFixedWidth(88)
        self.dot_size_value.editingFinished.connect(self._on_dot_size_value_edit_finished)
        dot_layout.addWidget(self.dot_size_value)

        card_layout.addLayout(dot_layout)

        return card

    def _on_dot_size_slider_changed(self, raw_value: int):
        """滑块变化 -> 同步输入框并发射百分比值"""
        percent = float(raw_value) / 10.0
        if hasattr(self, 'dot_size_value'):
            self.dot_size_value.blockSignals(True)
            self.dot_size_value.setText(f"{percent:.1f}%")
            self.dot_size_value.blockSignals(False)
        self.dot_size_changed.emit(percent)

    def _on_dot_size_value_edit_finished(self):
        """输入框编辑完成 -> 同步滑块并发射百分比值"""
        text = self.dot_size_value.text().strip().replace('%', '')
        try:
            percent = float(text)
        except Exception:
            # 非法输入时回显当前滑块值
            current_percent = float(self.dot_size_slider.value()) / 10.0
            self.dot_size_value.setText(f"{current_percent:.1f}%")
            return

        clamped = max(1.0, min(200.0, percent))
        raw_value = int(round(clamped * 10))
        if hasattr(self, 'dot_size_slider'):
            self.dot_size_slider.blockSignals(True)
            self.dot_size_slider.setValue(raw_value)
            self.dot_size_slider.blockSignals(False)
        self.dot_size_value.setText(f"{clamped:.1f}%")
        self.dot_size_changed.emit(clamped)

    def get_dot_size_percent(self) -> float:
        """获取当前圆点大小百分比值（1.0~200.0）"""
        if hasattr(self, 'dot_size_slider'):
            return float(self.dot_size_slider.value()) / 10.0
        return 50.0

    def _create_route_card(self):
        """创建路线录制卡片"""
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        self.route_title_label = StrongBodyLabel()
        card_layout.addWidget(self.route_title_label)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.route_start_btn = PrimaryPushButton()
        self.route_start_btn.setFixedWidth(120)
        self.route_start_btn.clicked.connect(self.route_start_requested.emit)
        btn_layout.addWidget(self.route_start_btn)

        self.route_stop_btn = PushButton()
        self.route_stop_btn.setFixedWidth(120)
        self.route_stop_btn.clicked.connect(self.route_stop_requested.emit)
        btn_layout.addWidget(self.route_stop_btn)

        btn_layout.addStretch()
        card_layout.addLayout(btn_layout)

        # 状态信息行
        status_layout = QHBoxLayout()
        status_layout.setSpacing(20)

        self.route_status_label = BodyLabel()
        status_layout.addWidget(self.route_status_label)

        self.route_count_label = BodyLabel()
        status_layout.addWidget(self.route_count_label)

        status_layout.addStretch()
        card_layout.addLayout(status_layout)

        return card

    def _create_window_card(self):
        """创建窗口控制卡片"""
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        self.window_title_label = StrongBodyLabel()
        card_layout.addWidget(self.window_title_label)

        # 地图窗口控制
        self.map_window_label = BodyLabel()
        card_layout.addWidget(self.map_window_label)

        # 使用网格布局避免挤压
        map_controls_grid = QGridLayout()
        map_controls_grid.setSpacing(12)
        map_controls_grid.setContentsMargins(0, 0, 0, 0)

        self.topmost_check = CheckBox()
        self.topmost_check.stateChanged.connect(lambda s: self.window_topmost_changed.emit(s == Qt.Checked))
        map_controls_grid.addWidget(self.topmost_check, 0, 0)

        self.passthrough_check = CheckBox()
        self.passthrough_check.stateChanged.connect(lambda s: self.window_passthrough_changed.emit(s == Qt.Checked))
        map_controls_grid.addWidget(self.passthrough_check, 0, 1)

        self.frameless_check = CheckBox()
        self.frameless_check.stateChanged.connect(lambda s: self.window_frameless_changed.emit(s == Qt.Checked))
        map_controls_grid.addWidget(self.frameless_check, 1, 0)

        # 设置列拉伸，让第三列占据剩余空间
        map_controls_grid.setColumnStretch(2, 1)

        card_layout.addLayout(map_controls_grid)

        # 透明度控制
        opacity_layout = QHBoxLayout()
        opacity_layout.setSpacing(12)

        self.opacity_label = BodyLabel()
        opacity_layout.addWidget(self.opacity_label)

        self.opacity_slider = Slider(Qt.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.window_opacity_changed.emit)
        opacity_layout.addWidget(self.opacity_slider, 1)

        self.opacity_value = BodyLabel("100%")
        self.opacity_value.setFixedWidth(50)
        self.opacity_slider.valueChanged.connect(lambda v: self.opacity_value.setText(f"{v}%"))
        opacity_layout.addWidget(self.opacity_value)

        card_layout.addLayout(opacity_layout)

        # 主窗口控制
        main_window_layout = QHBoxLayout()
        main_window_layout.setSpacing(12)

        self.main_window_label = BodyLabel()
        main_window_layout.addWidget(self.main_window_label)

        self.main_topmost_check = CheckBox()
        self.main_topmost_check.toggled.connect(self.main_topmost_changed.emit)
        main_window_layout.addWidget(self.main_topmost_check)

        main_window_layout.addStretch()
        card_layout.addLayout(main_window_layout)

        return card

    # === 外部调用的更新方法 ===
    def update_ocr_status(self, running: bool):
        """更新 OCR 状态"""
        self._ocr_running = running
        self._redraw_ocr_status()
        self._update_ocr_button_style()

    def update_coordinates(self, x: int, y: int, z: int):
        """更新坐标显示"""
        self._coordinates = (x, y, z)
        self._redraw_coordinates()

    def update_ocr_region(self, x: int, y: int, width: int, height: int):
        """更新 OCR 识别区域显示"""
        self._ocr_region = (x, y, width, height)
        self._redraw_ocr_region()

    def update_ocr_region_source(self, source: str):
        """更新 OCR 区域来源显示"""
        if source not in ("none", "auto", "manual"):
            source = "none"
        self._ocr_region_source = source
        self._redraw_ocr_region_source()

    def update_map_status(self, lat: float, lng: float, zoom: int):
        """更新地图状态"""
        self._map_status = (lat, lng, zoom)
        self._redraw_map_status()

    def update_area_id(self, area_id: str):
        """更新当前区域ID显示（独立于实时状态）"""
        self._area_id = area_id or "--"
        self._redraw_area_id()

    def update_calibration_status(self, text: str, ok: bool = False):
        """更新当前地图校准状态"""
        self._calibration_text = text
        self._calibration_ok = ok
        self._redraw_calibration_status()

    def update_route_status(self, recording: bool, count: int):
        """更新路线录制状态"""
        self._route_recording = recording
        self._route_count = count
        self._redraw_route_status()

    def _redraw_ocr_status(self):
        self.ocr_status_label.setText(
            tr("nav_status_running", "状态: 运行中")
            if self._ocr_running
            else tr("nav_status_not_started", "状态: 未启动")
        )

    def _redraw_coordinates(self):
        if self._coordinates is None:
            self.coord_label.setText(tr("nav_coordinates_empty", "坐标: X:-- Y:-- Z:--"))
            return
        x, y, z = self._coordinates
        self.coord_label.setText(
            tr("nav_coordinates_value", "坐标: X:{x} Y:{y} Z:{z}", x=x, y=y, z=z)
        )

    def _redraw_ocr_region(self):
        if self._ocr_region is None:
            self.ocr_region_label.setText(tr("nav_ocr_region_empty", "区域: (--,--,--×--)"))
            return
        x, y, width, height = self._ocr_region
        self.ocr_region_label.setText(
            tr(
                "nav_ocr_region_value",
                "区域: ({x},{y},{width}×{height})",
                x=x,
                y=y,
                width=width,
                height=height,
            )
        )

    def _redraw_ocr_region_source(self):
        self.ocr_region_source_label.setText(
            tr("nav_ocr_region_source", "来源: {source}", source=self._ocr_region_source)
        )

    def _redraw_map_status(self):
        if self._map_status is None:
            self.map_status_label.setText(tr("nav_map_waiting", "状态: 等待中..."))
            return
        lat, lng, zoom = self._map_status
        self.map_status_label.setText(
            tr(
                "nav_map_status_value",
                "状态: 经纬度 {lat:.4f}, {lng:.4f} | 缩放 {zoom}",
                lat=lat,
                lng=lng,
                zoom=zoom,
            )
        )

    def _redraw_area_id(self):
        self.map_area_label.setText(
            tr("nav_area_id", "当前区域ID: {area_id}", area_id=self._area_id or "--")
        )

    def _redraw_calibration_status(self):
        self.calibration_status_label.setText(
            tr("nav_calibration_status", "校准状态: {text}", text=self._calibration_text)
        )
        color = "#0f9d58" if self._calibration_ok else "#a66a00"
        self.calibration_status_label.setStyleSheet(f"color: {color};")

    def _redraw_route_status(self):
        self.route_status_label.setText(
            tr("nav_route_status_recording", "状态: 录制中")
            if self._route_recording
            else tr("nav_route_status_not_recording", "状态: 未录制")
        )
        self.route_count_label.setText(
            tr("nav_route_count", "已录制点数: {count}", count=self._route_count)
        )

    def retranslate_ui(self):
        self.window_title_label.setText(tr("nav_window_control_title", "窗口控制"))
        self.map_window_label.setText(tr("nav_map_window", "地图窗口:"))
        self.topmost_check.setText(tr("nav_window_topmost", "窗口顶置"))
        self.passthrough_check.setText(tr("nav_window_passthrough", "鼠标穿透"))
        self.frameless_check.setText(tr("nav_window_frameless", "无边框模式"))
        self.opacity_label.setText(tr("nav_window_opacity", "窗口透明度:"))
        self.main_window_label.setText(tr("nav_main_window", "主窗口:"))
        self.main_topmost_check.setText(tr("nav_main_window_topmost", "主窗口顶置"))

        self.ocr_title_label.setText(tr("nav_ocr_card_title", "OCR 识别"))
        self.ocr_calibrate_btn.setText(tr("nav_calibrate_ocr_region", "校准 OCR 区域"))
        self._update_ocr_button_style()
        self._redraw_ocr_status()
        self._redraw_coordinates()
        self._redraw_ocr_region()
        self._redraw_ocr_region_source()

        self.map_title_label.setText(tr("nav_map_control_title", "地图控制"))
        self.map_source_label.setText(tr("nav_map_source", "地图源:"))
        self.radio_official.setText(tr("nav_map_source_official", "库街区"))
        self.radio_local.setText(tr("nav_map_source_local", "本地"))
        self.map_calibrate_btn.setText(tr("nav_map_calibration", "地图校准"))
        self.map_recapture_btn.setText(tr("nav_map_recapture", "重新捕获"))
        self.dot_size_label.setText(tr("nav_dot_size", "圆点大小:"))
        self._redraw_map_status()
        self._redraw_area_id()
        self._redraw_calibration_status()

        self.route_title_label.setText(tr("nav_route_recording_title", "路线录制"))
        self.route_start_btn.setText(tr("nav_start_recording", "开始录制"))
        self.route_stop_btn.setText(tr("nav_stop_recording", "停止录制"))
        self._redraw_route_status()
