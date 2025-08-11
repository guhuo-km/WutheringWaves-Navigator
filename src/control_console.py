#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制台主窗口
包含所有控制功能：地图控制、OCR、路线录制、校准等
"""

import sys
import os
import json
import threading
from datetime import datetime
from PySide6.QtCore import QUrl, Slot, QTimer, Qt, QObject, Signal
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLabel, QRadioButton, QButtonGroup, 
                               QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
                               QGroupBox, QGridLayout, QCheckBox, QSlider, QTabWidget,
                               QMessageBox, QFileDialog, QProgressDialog, QSplitter,
                               QScrollArea, QFrame)

# 导入各种管理器和组件
try:
    from ocr_manager import OCRManager
    OCR_AVAILABLE = True
except ImportError as e:
    print(f"OCR模块导入失败: {e}")
    OCR_AVAILABLE = False

try:
    from route_recorder import RouteRecorder
    from route_list_dialog import RouteListDialog
    ROUTE_RECORDER_AVAILABLE = True
except ImportError as e:
    print(f"路线录制模块导入失败: {e}")
    ROUTE_RECORDER_AVAILABLE = False

# 导入校准系统相关类（从main_app.py）
try:
    import numpy as np
    from main_app import CalibrationSystem, CalibrationDataManager, TransformMatrix, CalibrationPoint, LocalServerManager
    CALIBRATION_AVAILABLE = True
except ImportError as e:
    print(f"校准系统导入失败: {e}")
    CALIBRATION_AVAILABLE = False


class ControlConsoleWindow(QMainWindow):
    """控制台主窗口"""
    
    # 信号定义
    map_mode_changed = Signal(str, str)  # mode, provider_or_map
    coordinates_jump_requested = Signal(float, float, int)  # lat, lng, zoom
    overlay_settings_changed = Signal(dict)  # overlay settings
    
    def __init__(self):
        super().__init__()
        
        # 窗口属性
        self.setWindowTitle("鸣潮地图导航系统 - 控制台")
        self.setGeometry(50, 50, 600, 900)
        
        # 核心管理器
        self.server_manager = None
        self.calibration_data_manager = None
        self.ocr_manager = None
        self.route_recorder = None
        
        # 校准相关
        self.current_transform_matrix = None
        self.calibration_points = []
        
        # 当前状态
        self.current_map_mode = "online"
        self.current_map_provider = "官方地图"
        self.current_local_map = None
        
        # 初始化各种管理器
        self.init_managers()
        
        # 设置UI
        self.setup_ui()
        
        # 连接信号
        self.connect_signals()
        
        print("控制台窗口初始化完成")
    
    def init_managers(self):
        """初始化各种管理器"""
        try:
            # 本地服务器管理器
            if CALIBRATION_AVAILABLE:
                self.server_manager = LocalServerManager()
                self.calibration_data_manager = CalibrationDataManager()
            
            # OCR管理器
            if OCR_AVAILABLE:
                self.ocr_manager = OCRManager(self)
                
            # 路线录制器
            if ROUTE_RECORDER_AVAILABLE:
                self.route_recorder = RouteRecorder(self)
                
            print("管理器初始化完成")
            
        except Exception as e:
            print(f"管理器初始化失败: {e}")
    
    def setup_ui(self):
        """设置用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 顶部标题
        title_label = QLabel("🎮 鸣潮地图导航系统控制台")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #0078d7;
                padding: 10px;
                background-color: #f8f9fa;
                border: 2px solid #0078d7;
                border-radius: 8px;
                margin-bottom: 10px;
            }
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 设置各个选项卡
        self.setup_map_control_tab()
        self.setup_coordinate_tab()
        self.setup_ocr_tab()
        self.setup_route_recording_tab()
        self.setup_overlay_tab()
        self.setup_settings_tab()
        
        # 底部状态区域
        self.setup_status_area(main_layout)
    
    def setup_map_control_tab(self):
        """设置地图控制选项卡"""
        tab = QWidget()
        self.tab_widget.addTab(tab, "🗺️ 地图控制")
        
        layout = QVBoxLayout(tab)
        
        # 地图模式选择组
        mode_group = QGroupBox("地图模式选择")
        mode_layout = QVBoxLayout(mode_group)
        
        # 在线地图选项
        self.online_radio = QRadioButton("在线地图")
        self.online_radio.setChecked(True)
        mode_layout.addWidget(self.online_radio)
        
        # 在线地图提供商选择
        online_provider_layout = QHBoxLayout()
        online_provider_layout.addWidget(QLabel("  提供商:"))
        self.online_provider_combo = QComboBox()
        self.online_provider_combo.addItems(["官方地图", "光环助手"])
        online_provider_layout.addWidget(self.online_provider_combo)
        online_provider_layout.addStretch()
        mode_layout.addLayout(online_provider_layout)
        
        # 本地地图选项
        self.local_radio = QRadioButton("本地地图")
        mode_layout.addWidget(self.local_radio)
        
        # 本地地图选择
        local_map_layout = QHBoxLayout()
        local_map_layout.addWidget(QLabel("  地图:"))
        self.local_map_combo = QComboBox()
        self.refresh_local_maps()
        local_map_layout.addWidget(self.local_map_combo)
        
        self.refresh_maps_btn = QPushButton("刷新")
        self.refresh_maps_btn.clicked.connect(self.refresh_local_maps)
        local_map_layout.addWidget(self.refresh_maps_btn)
        mode_layout.addLayout(local_map_layout)
        
        # 应用地图按钮
        self.apply_map_btn = QPushButton("应用地图设置")
        self.apply_map_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.apply_map_btn.clicked.connect(self.apply_map_settings)
        mode_layout.addWidget(self.apply_map_btn)
        
        layout.addWidget(mode_group)
        
        # 地图操作组
        operation_group = QGroupBox("地图操作")
        operation_layout = QGridLayout(operation_group)
        
        # 平移控制
        operation_layout.addWidget(QLabel("平移控制:"), 0, 0)
        
        pan_layout = QGridLayout()
        
        self.pan_up_btn = QPushButton("↑")
        self.pan_up_btn.clicked.connect(lambda: self.pan_map(0, -50))
        pan_layout.addWidget(self.pan_up_btn, 0, 1)
        
        self.pan_left_btn = QPushButton("←")
        self.pan_left_btn.clicked.connect(lambda: self.pan_map(-50, 0))
        pan_layout.addWidget(self.pan_left_btn, 1, 0)
        
        self.pan_right_btn = QPushButton("→")
        self.pan_right_btn.clicked.connect(lambda: self.pan_map(50, 0))
        pan_layout.addWidget(self.pan_right_btn, 1, 2)
        
        self.pan_down_btn = QPushButton("↓")
        self.pan_down_btn.clicked.connect(lambda: self.pan_map(0, 50))
        pan_layout.addWidget(self.pan_down_btn, 2, 1)
        
        operation_layout.addLayout(pan_layout, 0, 1)
        
        # 缩放控制
        zoom_layout = QHBoxLayout()
        self.zoom_in_btn = QPushButton("🔍+ 放大")
        self.zoom_in_btn.clicked.connect(self.zoom_in_map)
        zoom_layout.addWidget(self.zoom_in_btn)
        
        self.zoom_out_btn = QPushButton("🔍- 缩小")
        self.zoom_out_btn.clicked.connect(self.zoom_out_map)
        zoom_layout.addWidget(self.zoom_out_btn)
        
        operation_layout.addWidget(QLabel("缩放控制:"), 1, 0)
        operation_layout.addLayout(zoom_layout, 1, 1)
        
        layout.addWidget(operation_group)
        
        # 服务器控制组
        server_group = QGroupBox("本地服务器")
        server_layout = QVBoxLayout(server_group)
        
        server_control_layout = QHBoxLayout()
        self.start_server_btn = QPushButton("启动服务器")
        self.start_server_btn.clicked.connect(self.start_local_server)
        server_control_layout.addWidget(self.start_server_btn)
        
        self.stop_server_btn = QPushButton("停止服务器")
        self.stop_server_btn.clicked.connect(self.stop_local_server)
        self.stop_server_btn.setEnabled(False)
        server_control_layout.addWidget(self.stop_server_btn)
        
        server_layout.addLayout(server_control_layout)
        
        self.server_status_label = QLabel("服务器状态: 未启动")
        server_layout.addWidget(self.server_status_label)
        
        layout.addWidget(server_group)
        
        layout.addStretch()
    
    def setup_coordinate_tab(self):
        """设置坐标操作选项卡"""
        tab = QWidget()
        self.tab_widget.addTab(tab, "📍 坐标操作")
        
        layout = QVBoxLayout(tab)
        
        # 坐标跳转组
        jump_group = QGroupBox("坐标跳转")
        jump_layout = QGridLayout(jump_group)
        
        jump_layout.addWidget(QLabel("经度 (Lat):"), 0, 0)
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setRange(-90, 90)
        self.lat_input.setDecimals(6)
        self.lat_input.setValue(31.123456)
        jump_layout.addWidget(self.lat_input, 0, 1)
        
        jump_layout.addWidget(QLabel("纬度 (Lng):"), 1, 0)
        self.lng_input = QDoubleSpinBox()
        self.lng_input.setRange(-180, 180)
        self.lng_input.setDecimals(6)
        self.lng_input.setValue(121.654321)
        jump_layout.addWidget(self.lng_input, 1, 1)
        
        jump_layout.addWidget(QLabel("缩放级别:"), 2, 0)
        self.zoom_input = QSpinBox()
        self.zoom_input.setRange(0, 20)
        self.zoom_input.setValue(2)
        jump_layout.addWidget(self.zoom_input, 2, 1)
        
        self.jump_btn = QPushButton("跳转到坐标")
        self.jump_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.jump_btn.clicked.connect(self.jump_to_coordinates)
        jump_layout.addWidget(self.jump_btn, 3, 0, 1, 2)
        
        layout.addWidget(jump_group)
        
        # 游戏坐标转换组
        if CALIBRATION_AVAILABLE:
            convert_group = QGroupBox("游戏坐标转换")
            convert_layout = QGridLayout(convert_group)
            
            convert_layout.addWidget(QLabel("游戏X:"), 0, 0)
            self.game_x_input = QSpinBox()
            self.game_x_input.setRange(-50000, 50000)
            convert_layout.addWidget(self.game_x_input, 0, 1)
            
            convert_layout.addWidget(QLabel("游戏Y:"), 1, 0)
            self.game_y_input = QSpinBox()
            self.game_y_input.setRange(-50000, 50000)
            convert_layout.addWidget(self.game_y_input, 1, 1)
            
            self.convert_btn = QPushButton("转换并跳转")
            self.convert_btn.clicked.connect(self.convert_and_jump)
            convert_layout.addWidget(self.convert_btn, 2, 0, 1, 2)
            
            layout.addWidget(convert_group)
        
        # 校准状态组
        if CALIBRATION_AVAILABLE:
            calibration_status_group = QGroupBox("校准状态")
            calibration_status_layout = QVBoxLayout(calibration_status_group)
            
            self.calibration_status_label = QLabel("当前未校准")
            calibration_status_layout.addWidget(self.calibration_status_label)
            
            calibration_btn_layout = QHBoxLayout()
            self.start_calibration_btn = QPushButton("开始校准")
            self.start_calibration_btn.clicked.connect(self.start_calibration)
            calibration_btn_layout.addWidget(self.start_calibration_btn)
            
            self.load_calibration_btn = QPushButton("加载校准")
            self.load_calibration_btn.clicked.connect(self.load_calibration)
            calibration_btn_layout.addWidget(self.load_calibration_btn)
            
            calibration_status_layout.addLayout(calibration_btn_layout)
            
            layout.addWidget(calibration_status_group)
        
        layout.addStretch()
    
    def setup_ocr_tab(self):
        """设置OCR选项卡"""
        tab = QWidget()
        self.tab_widget.addTab(tab, "👁️ OCR识别")
        
        layout = QVBoxLayout(tab)
        
        if OCR_AVAILABLE and self.ocr_manager:
            # OCR快速控制
            quick_control_group = QGroupBox("OCR快速控制")
            quick_control_layout = QHBoxLayout(quick_control_group)
            
            self.show_ocr_panel_btn = QPushButton("显示OCR控制面板")
            self.show_ocr_panel_btn.clicked.connect(self.show_ocr_control_panel)
            quick_control_layout.addWidget(self.show_ocr_panel_btn)
            
            self.setup_ocr_region_btn = QPushButton("设置OCR区域")
            self.setup_ocr_region_btn.clicked.connect(self.setup_ocr_region)
            quick_control_layout.addWidget(self.setup_ocr_region_btn)
            
            layout.addWidget(quick_control_group)
            
            # OCR状态显示
            ocr_status_group = QGroupBox("OCR状态")
            ocr_status_layout = QVBoxLayout(ocr_status_group)
            
            self.ocr_status_label = QLabel("OCR状态: 未启动")
            ocr_status_layout.addWidget(self.ocr_status_label)
            
            self.ocr_coordinates_label = QLabel("最新坐标: 无")
            ocr_status_layout.addWidget(self.ocr_coordinates_label)
            
            # OCR自动跳转设置
            auto_jump_layout = QHBoxLayout()
            self.auto_jump_checkbox = QCheckBox("启用坐标自动跳转")
            self.auto_jump_checkbox.setChecked(True)
            self.auto_jump_checkbox.stateChanged.connect(self.on_auto_jump_changed)
            auto_jump_layout.addWidget(self.auto_jump_checkbox)
            
            ocr_status_layout.addLayout(auto_jump_layout)
            
            layout.addWidget(ocr_status_group)
            
        else:
            # OCR不可用时的提示
            unavailable_label = QLabel("OCR功能不可用\n请检查相关模块是否正确安装")
            unavailable_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unavailable_label.setStyleSheet("color: #f44336; font-size: 14px;")
            layout.addWidget(unavailable_label)
        
        layout.addStretch()
    
    def setup_route_recording_tab(self):
        """设置路线录制选项卡"""
        tab = QWidget()
        self.tab_widget.addTab(tab, "🛤️ 路线录制")
        
        layout = QVBoxLayout(tab)
        
        if ROUTE_RECORDER_AVAILABLE and self.route_recorder:
            # 录制控制组
            recording_group = QGroupBox("录制控制")
            recording_layout = QVBoxLayout(recording_group)
            
            # 路线名称输入
            name_layout = QHBoxLayout()
            name_layout.addWidget(QLabel("路线名称:"))
            self.route_name_input = QLineEdit()
            self.route_name_input.setPlaceholderText("留空自动生成")
            name_layout.addWidget(self.route_name_input)
            recording_layout.addLayout(name_layout)
            
            # 录制按钮
            record_btn_layout = QHBoxLayout()
            self.start_recording_btn = QPushButton("🔴 开始录制")
            self.start_recording_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    font-weight: bold;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
            """)
            self.start_recording_btn.clicked.connect(self.start_route_recording)
            record_btn_layout.addWidget(self.start_recording_btn)
            
            self.stop_recording_btn = QPushButton("⏹️ 停止录制")
            self.stop_recording_btn.setStyleSheet("""
                QPushButton {
                    background-color: #9e9e9e;
                    color: white;
                    font-weight: bold;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #757575;
                }
            """)
            self.stop_recording_btn.clicked.connect(self.stop_route_recording)
            self.stop_recording_btn.setEnabled(False)
            record_btn_layout.addWidget(self.stop_recording_btn)
            
            recording_layout.addLayout(record_btn_layout)
            
            layout.addWidget(recording_group)
            
            # 录制状态组
            status_group = QGroupBox("录制状态")
            status_layout = QVBoxLayout(status_group)
            
            self.recording_status_label = QLabel("状态: 未录制")
            status_layout.addWidget(self.recording_status_label)
            
            self.recording_points_label = QLabel("已录制点数: 0")
            status_layout.addWidget(self.recording_points_label)
            
            layout.addWidget(status_group)
            
            # 路线管理组
            management_group = QGroupBox("路线管理")
            management_layout = QHBoxLayout(management_group)
            
            self.view_routes_btn = QPushButton("查看已录制路线")
            self.view_routes_btn.clicked.connect(self.show_route_list)
            management_layout.addWidget(self.view_routes_btn)
            
            layout.addWidget(management_group)
            
        else:
            # 路线录制不可用时的提示
            unavailable_label = QLabel("路线录制功能不可用\n请检查相关模块是否正确安装")
            unavailable_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unavailable_label.setStyleSheet("color: #f44336; font-size: 14px;")
            layout.addWidget(unavailable_label)
        
        layout.addStretch()
    
    def setup_overlay_tab(self):
        """设置覆盖层选项卡"""
        tab = QWidget()
        self.tab_widget.addTab(tab, "⭕ 覆盖层")
        
        layout = QVBoxLayout(tab)
        
        # 覆盖层控制组
        overlay_group = QGroupBox("覆盖层设置")
        overlay_layout = QGridLayout(overlay_group)
        
        # 显示控制
        overlay_layout.addWidget(QLabel("显示覆盖层:"), 0, 0)
        self.overlay_visible_checkbox = QCheckBox()
        self.overlay_visible_checkbox.setChecked(True)
        self.overlay_visible_checkbox.stateChanged.connect(self.update_overlay_settings)
        overlay_layout.addWidget(self.overlay_visible_checkbox, 0, 1)
        
        # 半径控制
        overlay_layout.addWidget(QLabel("圆点半径:"), 1, 0)
        self.overlay_radius_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_radius_slider.setRange(1, 50)
        self.overlay_radius_slider.setValue(10)
        self.overlay_radius_slider.valueChanged.connect(self.update_overlay_settings)
        overlay_layout.addWidget(self.overlay_radius_slider, 1, 1)
        
        self.overlay_radius_label = QLabel("10")
        overlay_layout.addWidget(self.overlay_radius_label, 1, 2)
        
        # Z轴颜色映射
        overlay_layout.addWidget(QLabel("Z轴颜色映射:"), 2, 0)
        self.z_color_mapping_checkbox = QCheckBox()
        self.z_color_mapping_checkbox.setChecked(False)
        self.z_color_mapping_checkbox.stateChanged.connect(self.update_overlay_settings)
        overlay_layout.addWidget(self.z_color_mapping_checkbox, 2, 1)
        
        layout.addWidget(overlay_group)
        
        # 覆盖层预览
        preview_group = QGroupBox("预览信息")
        preview_layout = QVBoxLayout(preview_group)
        
        self.overlay_preview_label = QLabel("当前Z值: 0\n颜色: 红色")
        preview_layout.addWidget(self.overlay_preview_label)
        
        layout.addWidget(preview_group)
        
        layout.addStretch()
    
    def setup_settings_tab(self):
        """设置选项卡"""
        tab = QWidget()
        self.tab_widget.addTab(tab, "⚙️ 设置")
        
        layout = QVBoxLayout(tab)
        
        # 系统设置组
        system_group = QGroupBox("系统设置")
        system_layout = QVBoxLayout(system_group)
        
        # 开机自启动服务器
        auto_start_layout = QHBoxLayout()
        self.auto_start_server_checkbox = QCheckBox("启动时自动开启本地服务器")
        self.auto_start_server_checkbox.setChecked(True)
        auto_start_layout.addWidget(self.auto_start_server_checkbox)
        system_layout.addLayout(auto_start_layout)
        
        layout.addWidget(system_group)
        
        # 界面设置组
        ui_group = QGroupBox("界面设置")
        ui_layout = QVBoxLayout(ui_group)
        
        # 双窗口独立显示
        dual_window_layout = QHBoxLayout()
        self.dual_window_checkbox = QCheckBox("启用双窗口模式（重启生效）")
        self.dual_window_checkbox.setChecked(True)
        self.dual_window_checkbox.setEnabled(False)  # 当前已经是双窗口模式
        dual_window_layout.addWidget(self.dual_window_checkbox)
        ui_layout.addLayout(dual_window_layout)
        
        layout.addWidget(ui_group)
        
        # 数据管理组
        data_group = QGroupBox("数据管理")
        data_layout = QVBoxLayout(data_group)
        
        data_btn_layout = QHBoxLayout()
        
        self.export_settings_btn = QPushButton("导出设置")
        self.export_settings_btn.clicked.connect(self.export_settings)
        data_btn_layout.addWidget(self.export_settings_btn)
        
        self.import_settings_btn = QPushButton("导入设置")
        self.import_settings_btn.clicked.connect(self.import_settings)
        data_btn_layout.addWidget(self.import_settings_btn)
        
        self.reset_settings_btn = QPushButton("重置设置")
        self.reset_settings_btn.clicked.connect(self.reset_settings)
        data_btn_layout.addWidget(self.reset_settings_btn)
        
        data_layout.addLayout(data_btn_layout)
        
        layout.addWidget(data_group)
        
        layout.addStretch()
    
    def setup_status_area(self, main_layout):
        """设置底部状态区域"""
        # 状态和日志区域
        status_group = QGroupBox("状态与日志")
        status_layout = QVBoxLayout(status_group)
        
        # 状态标签
        self.main_status_label = QLabel("系统状态: 就绪")
        self.main_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        status_layout.addWidget(self.main_status_label)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }
        """)
        status_layout.addWidget(self.log_text)
        
        # 日志控制按钮
        log_btn_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_btn_layout.addWidget(self.clear_log_btn)
        
        self.save_log_btn = QPushButton("保存日志")
        self.save_log_btn.clicked.connect(self.save_log)
        log_btn_layout.addWidget(self.save_log_btn)
        
        log_btn_layout.addStretch()
        status_layout.addLayout(log_btn_layout)
        
        main_layout.addWidget(status_group)
    
    def connect_signals(self):
        """连接信号"""
        try:
            # OCR信号连接
            if self.ocr_manager:
                self.ocr_manager.coordinates_detected.connect(self.on_ocr_coordinates_detected)
                self.ocr_manager.state_changed.connect(self.on_ocr_state_changed)
                self.ocr_manager.error_occurred.connect(self.on_ocr_error)
                
                # 设置OCR跳转回调
                self.ocr_manager.set_jump_callback(self.ocr_coordinate_jump_callback)
            
            # 路线录制信号连接
            if self.route_recorder:
                self.route_recorder.recording_started.connect(self.on_recording_started)
                self.route_recorder.recording_stopped.connect(self.on_recording_stopped)
                self.route_recorder.point_recorded.connect(self.on_point_recorded)
                self.route_recorder.error_occurred.connect(self.on_route_error)
            
            # 覆盖层设置信号连接
            self.overlay_radius_slider.valueChanged.connect(
                lambda v: self.overlay_radius_label.setText(str(v))
            )
            
        except Exception as e:
            self.log(f"信号连接失败: {e}")
    
    def log(self, message):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.log_text.append(log_message)
        
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        print(log_message)  # 同时输出到控制台
    
    # ========== 地图控制相关方法 ==========
    
    def refresh_local_maps(self):
        """刷新本地地图列表"""
        try:
            if self.server_manager:
                maps = self.server_manager.get_local_maps()
                self.local_map_combo.clear()
                if maps:
                    self.local_map_combo.addItems(maps)
                    self.log(f"发现 {len(maps)} 个本地地图")
                else:
                    self.local_map_combo.addItem("无可用地图")
                    self.log("未发现本地地图")
            else:
                self.local_map_combo.clear()
                self.local_map_combo.addItem("服务器管理器不可用")
                
        except Exception as e:
            self.log(f"刷新本地地图失败: {e}")
    
    def apply_map_settings(self):
        """应用地图设置"""
        try:
            if self.online_radio.isChecked():
                # 在线地图模式
                provider = self.online_provider_combo.currentText()
                self.current_map_mode = "online"
                self.current_map_provider = provider
                self.map_mode_changed.emit("online", provider)
                self.log(f"切换到在线地图: {provider}")
                
            elif self.local_radio.isChecked():
                # 本地地图模式
                map_name = self.local_map_combo.currentText()
                if map_name and map_name != "无可用地图" and map_name != "服务器管理器不可用":
                    self.current_map_mode = "local"
                    self.current_local_map = map_name
                    self.map_mode_changed.emit("local", map_name)
                    self.log(f"切换到本地地图: {map_name}")
                else:
                    QMessageBox.warning(self, "警告", "请选择有效的本地地图")
                    
        except Exception as e:
            error_msg = f"应用地图设置失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def pan_map(self, x, y):
        """平移地图"""
        # 这个信号会被地图窗口接收
        if hasattr(self, 'map_window') and self.map_window:
            self.map_window.pan_by(x, y)
            self.log(f"地图平移: ({x}, {y})")
    
    def zoom_in_map(self):
        """放大地图"""
        if hasattr(self, 'map_window') and self.map_window:
            self.map_window.zoom_in()
            self.log("地图放大")
    
    def zoom_out_map(self):
        """缩小地图"""
        if hasattr(self, 'map_window') and self.map_window:
            self.map_window.zoom_out()
            self.log("地图缩小")
    
    def start_local_server(self):
        """启动本地服务器"""
        try:
            if self.server_manager:
                if self.server_manager.start_servers():
                    self.start_server_btn.setEnabled(False)
                    self.stop_server_btn.setEnabled(True)
                    self.server_status_label.setText("服务器状态: 运行中")
                    self.server_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    self.log("本地服务器启动成功")
                    
                    # 刷新本地地图列表
                    self.refresh_local_maps()
                else:
                    self.log("本地服务器启动失败")
            else:
                self.log("服务器管理器不可用")
                
        except Exception as e:
            error_msg = f"启动本地服务器失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def stop_local_server(self):
        """停止本地服务器"""
        try:
            if self.server_manager:
                self.server_manager.stop_servers()
                self.start_server_btn.setEnabled(True)
                self.stop_server_btn.setEnabled(False)
                self.server_status_label.setText("服务器状态: 未启动")
                self.server_status_label.setStyleSheet("color: #f44336;")
                self.log("本地服务器已停止")
            else:
                self.log("服务器管理器不可用")
                
        except Exception as e:
            error_msg = f"停止本地服务器失败: {e}"
            self.log(error_msg)
    
    # ========== 坐标操作相关方法 ==========
    
    def jump_to_coordinates(self):
        """跳转到指定坐标"""
        try:
            lat = self.lat_input.value()
            lng = self.lng_input.value()
            zoom = self.zoom_input.value()
            
            self.coordinates_jump_requested.emit(lat, lng, zoom)
            self.log(f"请求跳转到坐标: ({lat:.6f}, {lng:.6f}), 缩放: {zoom}")
            
        except Exception as e:
            error_msg = f"坐标跳转失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def convert_and_jump(self):
        """转换游戏坐标并跳转"""
        if not CALIBRATION_AVAILABLE or not self.current_transform_matrix:
            QMessageBox.warning(self, "警告", "当前未校准，无法转换坐标")
            return
        
        try:
            game_x = self.game_x_input.value()
            game_y = self.game_y_input.value()
            
            # 使用校准系统转换坐标
            lat, lng = CalibrationSystem.transform(game_x, game_y, self.current_transform_matrix)
            
            # 更新坐标输入框
            self.lat_input.setValue(lat)
            self.lng_input.setValue(lng)
            
            # 执行跳转
            zoom = self.zoom_input.value()
            self.coordinates_jump_requested.emit(lat, lng, zoom)
            
            self.log(f"游戏坐标转换: ({game_x}, {game_y}) -> ({lat:.6f}, {lng:.6f})")
            
        except Exception as e:
            error_msg = f"坐标转换失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def start_calibration(self):
        """开始校准"""
        QMessageBox.information(self, "提示", "校准功能需要在地图窗口中进行操作\n请先确保地图已加载完成")
        # TODO: 实现校准窗口
    
    def load_calibration(self):
        """加载校准数据"""
        if not CALIBRATION_AVAILABLE:
            return
        
        try:
            # 尝试加载当前地图模式的校准数据
            if self.current_map_mode == "online":
                matrix = self.calibration_data_manager.load_calibration(
                    "online", self.current_map_provider
                )
            else:
                matrix = self.calibration_data_manager.load_calibration(
                    "local", self.current_local_map
                )
            
            if matrix:
                self.current_transform_matrix = matrix
                self.calibration_status_label.setText("校准状态: 已校准 ✓")
                self.calibration_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.log("校准数据加载成功")
            else:
                self.calibration_status_label.setText("校准状态: 未找到校准数据")
                self.calibration_status_label.setStyleSheet("color: #f44336;")
                self.log("未找到校准数据")
                
        except Exception as e:
            error_msg = f"加载校准数据失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    # ========== OCR相关方法 ==========
    
    def show_ocr_control_panel(self):
        """显示OCR控制面板"""
        if self.ocr_manager:
            self.ocr_manager.show_control_panel()
            self.log("OCR控制面板已打开")
        else:
            QMessageBox.warning(self, "警告", "OCR管理器不可用")
    
    def setup_ocr_region(self):
        """设置OCR区域"""
        if self.ocr_manager:
            self.ocr_manager.setup_ocr_region()
            self.log("OCR区域校准工具已启动")
        else:
            QMessageBox.warning(self, "警告", "OCR管理器不可用")
    
    def on_auto_jump_changed(self, state):
        """自动跳转设置改变"""
        if self.ocr_manager:
            enabled = state == Qt.CheckState.Checked.value
            self.ocr_manager.set_auto_jump(enabled)
            self.log(f"OCR自动跳转: {'启用' if enabled else '禁用'}")
    
    def ocr_coordinate_jump_callback(self, x, y, z):
        """OCR坐标跳转回调"""
        if not CALIBRATION_AVAILABLE or not self.current_transform_matrix:
            self.log("OCR检测到坐标但未校准，无法自动跳转")
            return
        
        try:
            # 转换游戏坐标到地理坐标
            lat, lng = CalibrationSystem.transform(x, y, self.current_transform_matrix)
            
            # 执行跳转
            self.coordinates_jump_requested.emit(lat, lng, self.zoom_input.value())
            
            self.log(f"OCR自动跳转: 游戏坐标({x}, {y}, {z}) -> 地理坐标({lat:.6f}, {lng:.6f})")
            
        except Exception as e:
            self.log(f"OCR自动跳转失败: {e}")
    
    @Slot(int, int, int)
    def on_ocr_coordinates_detected(self, x, y, z):
        """OCR坐标检测到"""
        self.ocr_coordinates_label.setText(f"最新坐标: ({x}, {y}, {z})")
        
        # 更新覆盖层Z值
        if hasattr(self, 'map_window') and self.map_window:
            self.map_window.update_overlay_z_value(z)
    
    @Slot(str)
    def on_ocr_state_changed(self, state):
        """OCR状态改变"""
        color_map = {
            'LOCKED': '#4CAF50',
            'LOST': '#f44336',
            'SEARCHING': '#FF9800'
        }
        color = color_map.get(state, '#666')
        
        self.ocr_status_label.setText(f"OCR状态: {state}")
        self.ocr_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
    
    @Slot(str)
    def on_ocr_error(self, error_msg):
        """OCR错误"""
        self.log(f"OCR错误: {error_msg}")
    
    # ========== 路线录制相关方法 ==========
    
    def start_route_recording(self):
        """开始路线录制"""
        if not self.route_recorder:
            QMessageBox.warning(self, "警告", "路线录制器不可用")
            return
        
        route_name = self.route_name_input.text().strip()
        if not route_name:
            route_name = None  # 使用自动生成的名称
        
        if self.route_recorder.start_recording(route_name):
            self.start_recording_btn.setEnabled(False)
            self.stop_recording_btn.setEnabled(True)
            self.log(f"开始录制路线: {route_name or '自动生成'}")
        else:
            QMessageBox.critical(self, "错误", "启动路线录制失败")
    
    def stop_route_recording(self):
        """停止路线录制"""
        if not self.route_recorder:
            return
        
        filepath = self.route_recorder.stop_recording()
        if filepath:
            self.start_recording_btn.setEnabled(True)
            self.stop_recording_btn.setEnabled(False)
            self.log(f"路线录制完成，保存到: {filepath}")
            QMessageBox.information(self, "录制完成", f"路线已保存到:\n{filepath}")
        else:
            QMessageBox.critical(self, "错误", "停止路线录制失败")
    
    def show_route_list(self):
        """显示路线列表"""
        if not self.route_recorder:
            QMessageBox.warning(self, "警告", "路线录制器不可用")
            return
        
        try:
            dialog = RouteListDialog(self.route_recorder, self)
            dialog.exec()
        except Exception as e:
            error_msg = f"显示路线列表失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    @Slot(str)
    def on_recording_started(self, route_name):
        """录制开始"""
        self.recording_status_label.setText(f"状态: 正在录制 - {route_name}")
        self.recording_status_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    @Slot(str, int)
    def on_recording_stopped(self, route_name, point_count):
        """录制停止"""
        self.recording_status_label.setText("状态: 未录制")
        self.recording_status_label.setStyleSheet("color: #666;")
        self.recording_points_label.setText("已录制点数: 0")
    
    @Slot(int, int, int, int)
    def on_point_recorded(self, x, y, z, total_count):
        """记录点"""
        self.recording_points_label.setText(f"已录制点数: {total_count}")
        
        # 连接OCR和路线录制
        if self.route_recorder and self.route_recorder.is_recording:
            self.route_recorder.record_point(x, y, z)
    
    @Slot(str)
    def on_route_error(self, error_msg):
        """路线录制错误"""
        self.log(f"路线录制错误: {error_msg}")
    
    # ========== 覆盖层相关方法 ==========
    
    def update_overlay_settings(self):
        """更新覆盖层设置"""
        settings = {
            'visible': self.overlay_visible_checkbox.isChecked(),
            'radius': self.overlay_radius_slider.value(),
            'z_color_mapping': self.z_color_mapping_checkbox.isChecked()
        }
        
        self.overlay_settings_changed.emit(settings)
        self.log(f"覆盖层设置已更新")
    
    # ========== 设置相关方法 ==========
    
    def export_settings(self):
        """导出设置"""
        # TODO: 实现设置导出
        QMessageBox.information(self, "提示", "设置导出功能待实现")
    
    def import_settings(self):
        """导入设置"""
        # TODO: 实现设置导入
        QMessageBox.information(self, "提示", "设置导入功能待实现")
    
    def reset_settings(self):
        """重置设置"""
        reply = QMessageBox.question(
            self, "确认重置", "确定要重置所有设置吗？\n此操作无法撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # TODO: 实现设置重置
            QMessageBox.information(self, "提示", "设置重置功能待实现")
    
    # ========== 日志相关方法 ==========
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log("日志已清空")
    
    def save_log(self):
        """保存日志"""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "保存日志", 
                f"控制台日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)"
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                
                QMessageBox.information(self, "保存成功", f"日志已保存到:\n{filename}")
                self.log(f"日志已保存到: {filename}")
                
        except Exception as e:
            error_msg = f"保存日志失败: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 清理资源
            if self.server_manager:
                self.server_manager.stop_servers()
            
            if self.ocr_manager:
                self.ocr_manager.cleanup()
            
            if self.route_recorder:
                self.route_recorder.cleanup()
            
            self.log("控制台窗口正在关闭")
            event.accept()
            
        except Exception as e:
            print(f"关闭控制台窗口时出错: {e}")
            event.accept()