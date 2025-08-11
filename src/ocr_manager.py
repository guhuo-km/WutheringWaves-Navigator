#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR Manager for WutheringWaves Navigator
OCR管理器 - 负责协调OCR引擎和UI界面
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QTimer, Slot
from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QSlider, QDoubleSpinBox, QSpinBox, QPushButton, QTextEdit, QCheckBox, QWidget, QGridLayout, QComboBox, QLineEdit, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt

# 多语言支持
try:
    from language_manager import get_language_manager, tr
    LANGUAGE_AVAILABLE = True
except ImportError:
    LANGUAGE_AVAILABLE = False
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

from ocr_engine import OCRWorker, RecognitionState
from ocr_region_calibrator import OCRRegionCalibrator
from screen_capture import capture_region_callback


class WindowSelectionDialog(QDialog):
    """
    窗口选择对话框
    显示所有活动窗口供用户选择
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_window_name = None
        self.setWindowTitle(tr('select_target_window', '选择目标窗口'))
        self.setFixedSize(500, 400)
        self.setup_ui()
        self.load_windows()
    
    def setup_ui(self):
        """设置用户界面"""
        layout = QVBoxLayout(self)
        
        # 说明标签
        info_label = QLabel(tr('double_click_to_select', '双击选择目标窗口：'))
        info_label.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        # 窗口列表
        self.window_list = QListWidget()
        self.window_list.itemDoubleClicked.connect(self.on_window_selected)
        layout.addWidget(self.window_list)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton(tr('refresh_list', '刷新列表'))
        refresh_btn.clicked.connect(self.load_windows)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        
        cancel_btn = QPushButton(tr('cancel', '取消'))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def load_windows(self):
        """加载所有活动窗口"""
        try:
            from screen_capture import get_screen_capture
            screen_capture = get_screen_capture()
            windows = screen_capture.get_all_windows()
            
            self.window_list.clear()
            
            if not windows:
                item = QListWidgetItem(tr('no_windows_found', '未找到可用窗口'))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.window_list.addItem(item)
                return
            
            # 添加窗口到列表
            for window_name, hwnd in windows:
                item = QListWidgetItem(f"{window_name} (HWND: {hwnd})")
                item.setData(Qt.ItemDataRole.UserRole, window_name)  # 存储窗口名称
                self.window_list.addItem(item)
                
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载窗口列表失败: {e}")
    
    def on_window_selected(self, item):
        """用户双击选择窗口"""
        window_name = item.data(Qt.ItemDataRole.UserRole)
        if window_name:
            self.selected_window_name = window_name
            self.accept()
    
    def get_selected_window(self):
        """获取选择的窗口名称"""
        return self.selected_window_name


class OCRAdvancedSettings(QDialog):
    """
    高级OCR设置对话框 - 按照用户截图设计
    """
    
    def __init__(self, ocr_manager, parent=None):
        super().__init__(parent)
        self.ocr_manager = ocr_manager
        self.setWindowTitle(tr('advanced_ocr_settings', '高级OCR设置'))
        self.setGeometry(200, 200, 500, 600)
        self.setModal(True)  # 模态对话框
        
        self.setup_advanced_ui()
        self.load_advanced_settings()
    
    def setup_advanced_ui(self):
        """设置简化的高级OCR设置UI"""
        layout = QVBoxLayout(self)
        
        # 顶部说明
        info_text = QLabel(
            "🔧 简化的OCR参数设置\n\n"
            "经过算法优化，现在只需要调整核心参数即可获得最佳识别效果：\n"
            "• 基础识别参数：控制字符识别的基础阈值\n"
            "• 坐标跟踪参数：控制坐标跟踪的稳定性\n"
            "• 聚类分隔参数：控制智能聚类算法\n\n"
            "✨ 新算法已自动优化聚类和分隔逻辑，减少了手动调参的需要"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet(
            "background-color: #f0f8ff; "
            "padding: 15px; "
            "border: 2px solid #4CAF50; "
            "border-radius: 8px; "
            "font-size: 12px; "
            "color: #333;"
        )
        layout.addWidget(info_text)
        
        # 快速预设选择
        preset_group = QGroupBox("快速预设")
        preset_layout = QHBoxLayout(preset_group)
        
        preset_desc = QLabel("选择适合的预设配置：")
        preset_layout.addWidget(preset_desc)
        
        # 预设按钮
        balanced_btn = QPushButton("推荐设置")
        balanced_btn.setToolTip("默认推荐设置，适合大多数场景")
        balanced_btn.clicked.connect(lambda: self.apply_preset("balanced"))
        balanced_btn.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white;")
        preset_layout.addWidget(balanced_btn)
        
        high_accuracy_btn = QPushButton("高精度模式")
        high_accuracy_btn.setToolTip("适合文字清晰、要求高准确率的场景")
        high_accuracy_btn.clicked.connect(lambda: self.apply_preset("high_accuracy"))
        preset_layout.addWidget(high_accuracy_btn)
        
        fast_btn = QPushButton("快速模式")
        fast_btn.setToolTip("适合快速识别的场景")
        fast_btn.clicked.connect(lambda: self.apply_preset("fast"))
        preset_layout.addWidget(fast_btn)
        
        preset_layout.addStretch()
        
        layout.addWidget(preset_group)
        
        # 基础识别参数组
        detection_group = QGroupBox("基础识别参数")
        detection_layout = QGridLayout(detection_group)
        
        # 置信度阈值
        detection_layout.addWidget(QLabel("置信度阈值:"), 0, 0)
        self.confidence_spinbox = QDoubleSpinBox()
        self.confidence_spinbox.setRange(0.01, 1.0)
        self.confidence_spinbox.setSingleStep(0.01)
        self.confidence_spinbox.setValue(0.45)
        detection_layout.addWidget(self.confidence_spinbox, 0, 1)
        detection_layout.addWidget(QLabel("(推荐: 0.45, 范围: 0.01-1.0)"), 0, 2)
        
        # 置信度阈值说明
        conf_desc = QLabel("控制字符识别的最低置信度。较低值识别更多字符，较高值减少误识别")
        conf_desc.setWordWrap(True)
        conf_desc.setStyleSheet("color: #666; font-size: 11px; padding: 2px;")
        detection_layout.addWidget(conf_desc, 0, 3)
        
        layout.addWidget(detection_group)
        
        # 坐标跟踪参数组
        tracking_group = QGroupBox("坐标跟踪参数")
        tracking_layout = QGridLayout(tracking_group)
        
        # 最大速度阈值
        tracking_layout.addWidget(QLabel("最大移动速度:"), 0, 0)
        self.max_speed_spinbox = QSpinBox()
        self.max_speed_spinbox.setRange(100, 5000)
        self.max_speed_spinbox.setValue(1000)
        tracking_layout.addWidget(self.max_speed_spinbox, 0, 1)
        tracking_layout.addWidget(QLabel("(推荐: 1000, 范围: 100-5000)"), 0, 2)
        
        # 最大速度阈值说明
        speed_desc = QLabel("检测传送跳跃的速度阈值。超过此值的坐标变化被视为瞬移")
        speed_desc.setWordWrap(True)
        speed_desc.setStyleSheet("color: #666; font-size: 11px; padding: 2px;")
        tracking_layout.addWidget(speed_desc, 0, 3)
        
        # 丢失阈值帧数
        tracking_layout.addWidget(QLabel("失联帧数阈值:"), 1, 0)
        self.lost_frames_spinbox = QSpinBox()
        self.lost_frames_spinbox.setRange(1, 20)
        self.lost_frames_spinbox.setValue(5)
        tracking_layout.addWidget(self.lost_frames_spinbox, 1, 1)
        tracking_layout.addWidget(QLabel("(推荐: 5, 范围: 1-20)"), 1, 2)
        
        # 丢失阈值帧数说明
        lost_desc = QLabel("连续识别失败多少帧后重新搜索坐标。值越小越敏感")
        lost_desc.setWordWrap(True)
        lost_desc.setStyleSheet("color: #666; font-size: 11px; padding: 2px;")
        tracking_layout.addWidget(lost_desc, 1, 3)
        
        # Z轴异常阈值
        tracking_layout.addWidget(QLabel("垂直移动阈值:"), 2, 0)
        self.z_threshold_spinbox = QSpinBox()
        self.z_threshold_spinbox.setRange(10, 200)
        self.z_threshold_spinbox.setValue(50)
        tracking_layout.addWidget(self.z_threshold_spinbox, 2, 1)
        tracking_layout.addWidget(QLabel("(推荐: 50, 范围: 10-200)"), 2, 2)
        
        # Z轴异常阈值说明
        z_desc = QLabel("垂直方向(Z轴)的异常移动检测。用于识别跳跃、飞行等动作")
        z_desc.setWordWrap(True)
        z_desc.setStyleSheet("color: #666; font-size: 11px; padding: 2px;")
        tracking_layout.addWidget(z_desc, 2, 3)
        
        layout.addWidget(tracking_group)
        
        # 调试日志设置组 - 恢复这个重要功能！
        debug_group = QGroupBox("调试日志设置")
        debug_layout = QGridLayout(debug_group)
        
        # 启用详细调试日志
        self.verbose_debug_checkbox = QCheckBox("启用详细调试日志")
        self.verbose_debug_checkbox.setChecked(False)
        debug_layout.addWidget(self.verbose_debug_checkbox, 0, 0)
        debug_layout.addWidget(QLabel("输出详细的OCR识别过程、聚类分析和错误诊断信息"), 0, 1, 1, 2)
        
        # 详细日志说明
        debug_desc = QLabel(
            "📝 启用后将输出：\n"
            "• 字符检测详情和置信度\n" 
            "• 聚类算法执行过程\n"
            "• 坐标选择逻辑分析\n"
            "• 时间戳过滤过程\n"
            "• 异常和错误的详细堆栈\n"
            "⚠️ 对调试问题至关重要！"
        )
        debug_desc.setWordWrap(True)
        debug_desc.setStyleSheet(
            "color: #444; font-size: 11px; padding: 8px; "
            "background-color: #fffbf0; border: 1px solid #ddd; border-radius: 4px;"
        )
        debug_layout.addWidget(debug_desc, 1, 0, 1, 3)
        
        layout.addWidget(debug_group)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("恢复推荐值")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept_settings)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("应用")
        apply_btn.clicked.connect(self.apply_settings)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
    
    def load_advanced_settings(self):
        """加载高级设置"""
        config = self.ocr_manager.ocr_config
        advanced = config.get('advanced_ocr_settings', {})
        
        # 基础识别参数
        self.confidence_spinbox.setValue(config.get('confidence_threshold', 0.45))
        
        # 坐标跟踪参数
        self.max_speed_spinbox.setValue(advanced.get('max_speed_threshold', 1000))
        self.lost_frames_spinbox.setValue(advanced.get('lost_threshold_frames', 5))
        self.z_threshold_spinbox.setValue(advanced.get('z_axis_threshold', 50))
        
        # 调试日志设置
        self.verbose_debug_checkbox.setChecked(advanced.get('verbose_debug', False))
    
    def reset_to_defaults(self):
        """重置为推荐值"""
        # 基础识别参数
        self.confidence_spinbox.setValue(0.45)
        
        # 坐标跟踪参数
        self.max_speed_spinbox.setValue(1000)
        self.lost_frames_spinbox.setValue(5)
        self.z_threshold_spinbox.setValue(50)
        
        # 调试日志设置
        self.verbose_debug_checkbox.setChecked(False)
    
    def apply_settings(self):
        """应用简化的设置"""
        # 更新OCR管理器的配置
        self.ocr_manager.ocr_config['confidence_threshold'] = self.confidence_spinbox.value()
        
        # 核心高级设置（包含调试日志）
        advanced_settings = {
            'max_speed_threshold': self.max_speed_spinbox.value(),
            'lost_threshold_frames': self.lost_frames_spinbox.value(),
            'z_axis_threshold': self.z_threshold_spinbox.value(),
            'verbose_debug': self.verbose_debug_checkbox.isChecked()
        }
        
        self.ocr_manager.ocr_config['advanced_ocr_settings'] = advanced_settings
        self.ocr_manager.save_config()
        
        # 更新运行中的OCR工作器
        if self.ocr_manager.ocr_worker:
            self.ocr_manager.ocr_worker.update_confidence_threshold(self.confidence_spinbox.value())
            self.ocr_manager.ocr_worker.update_advanced_parameters(advanced_settings)
    
    def accept_settings(self):
        """确认并关闭"""
        self.apply_settings()
        self.accept()
    
    def apply_preset(self, preset_name):
        """应用预设配置"""
        if preset_name == "high_accuracy":
            # 高精度模式：高置信度，严格阈值，启用详细日志
            self.confidence_spinbox.setValue(0.55)
            self.max_speed_spinbox.setValue(800)
            self.lost_frames_spinbox.setValue(3)
            self.z_threshold_spinbox.setValue(30)
            self.verbose_debug_checkbox.setChecked(True)  # 高精度模式启用详细日志
            
        elif preset_name == "balanced":
            # 平衡模式：默认推荐设置
            self.confidence_spinbox.setValue(0.45)
            self.max_speed_spinbox.setValue(1000)
            self.lost_frames_spinbox.setValue(5)
            self.z_threshold_spinbox.setValue(50)
            self.verbose_debug_checkbox.setChecked(False)  # 平衡模式关闭详细日志
            
        elif preset_name == "fast":
            # 快速模式：低置信度，宽松阈值，关闭详细日志提升性能
            self.confidence_spinbox.setValue(0.35)
            self.max_speed_spinbox.setValue(1500)
            self.lost_frames_spinbox.setValue(3)  
            self.z_threshold_spinbox.setValue(80)
            self.verbose_debug_checkbox.setChecked(False)  # 快速模式关闭详细日志


class OCRControlPanel(QDialog):
    """
    OCR控制面板 - 按照用户截图重新设计的简洁界面
    """
    
    def __init__(self, ocr_manager, parent=None):
        super().__init__(parent)
        self.ocr_manager = ocr_manager
        self.setWindowTitle("坐标识别 (OCR)")
        self.setGeometry(200, 200, 600, 700)  # 增大窗口尺寸以容纳更大的日志区域
        self.setModal(False)  # 非模态对话框
        
        # 设置窗口可以调整大小
        self.setMinimumSize(500, 600)
        self.setMaximumSize(800, 900)
        
        self.advanced_dialog = None
        
        self.setup_ui()
        self.connect_signals()
        self.update_ui_from_config()
    
    def setup_ui(self):
        """设置UI界面 - 按照用户截图设计"""
        layout = QVBoxLayout(self)
        
        # 顶部大按钮区域 - 开始识别/停止识别
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton(tr('start_recognition', '开始识别'))
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.start_btn.clicked.connect(self.start_ocr)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton(tr('stop_recognition', '停止识别'))
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_ocr)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        layout.addLayout(button_layout)
        
        # OCR设置组
        ocr_group = QGroupBox(tr('ocr_settings', 'OCR设置'))
        ocr_layout = QGridLayout(ocr_group)
        
        # 识别间隔
        ocr_layout.addWidget(QLabel(tr('recognition_interval', '识别间隔:')), 0, 0)
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(100, 5000)
        self.interval_spinbox.setValue(1000)
        self.interval_spinbox.setSuffix(" ms")
        self.interval_spinbox.valueChanged.connect(self.on_interval_changed)
        ocr_layout.addWidget(self.interval_spinbox, 0, 1)
        ocr_layout.addWidget(QLabel(tr('interval_note', '(ms, 最低100)')), 0, 2)
        
        # 截图模式
        ocr_layout.addWidget(QLabel(tr('capture_mode', '截图模式:')), 1, 0)
        self.capture_mode_combo = QComboBox()
        self.capture_mode_combo.addItems([tr('bitblt_default', 'BitBlt (默认)'), tr('print_window', 'PrintWindow')])
        ocr_layout.addWidget(self.capture_mode_combo, 1, 1, 1, 2)
        
        # 目标窗口名称
        ocr_layout.addWidget(QLabel(tr('target_window_name', '目标窗口名称:')), 2, 0)
        self.window_name_edit = QLineEdit()
        self.window_name_edit.setPlaceholderText(tr('fullscreen_capture_placeholder', '留空使用全屏截图'))
        ocr_layout.addWidget(self.window_name_edit, 2, 1)
        
        window_btn_layout = QHBoxLayout()
        detect_btn = QPushButton(tr('detect', '检测'))
        detect_btn.clicked.connect(self.detect_window)
        window_btn_layout.addWidget(detect_btn)
        
        clear_btn = QPushButton(tr('clear', '清空'))
        clear_btn.clicked.connect(lambda: self.window_name_edit.clear())
        window_btn_layout.addWidget(clear_btn)
        
        ocr_layout.addLayout(window_btn_layout, 2, 2)
        
        # 置信度阈值
        ocr_layout.addWidget(QLabel(tr('confidence_threshold', '置信度阈值:')), 3, 0)
        self.confidence_spinbox = QDoubleSpinBox()
        self.confidence_spinbox.setRange(0.1, 1.0)
        self.confidence_spinbox.setSingleStep(0.01)
        self.confidence_spinbox.setValue(0.45)
        self.confidence_spinbox.valueChanged.connect(self.on_confidence_changed)
        ocr_layout.addWidget(self.confidence_spinbox, 3, 1)
        ocr_layout.addWidget(QLabel(tr('confidence_note', '(0.1-1.0, 推荐0.45)')), 3, 2)
        
        # OCR区域校准
        ocr_layout.addWidget(QLabel(tr('ocr_region_calibration', 'OCR区域校准:')), 4, 0)
        self.region_btn = QPushButton(tr('calibrate_ocr_region', '校准OCR区域'))
        self.region_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.region_btn.clicked.connect(self.setup_ocr_region)
        ocr_layout.addWidget(self.region_btn, 4, 1, 1, 2)
        
        # 高级OCR设置按钮
        self.advanced_btn = QPushButton(tr('advanced_ocr_settings_btn', '高级OCR设置...'))
        self.advanced_btn.clicked.connect(self.show_advanced_settings)
        ocr_layout.addWidget(self.advanced_btn, 5, 1, 1, 2)
        
        layout.addWidget(ocr_group)
        
        # 状态显示组
        status_group = QGroupBox(tr('recognition_status', '识别状态'))
        status_layout = QVBoxLayout(status_group)
        
        self.state_label = QLabel(tr('status_not_started', '状态: 未启动'))
        self.state_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        status_layout.addWidget(self.state_label)
        
        self.coordinates_label = QLabel(tr('coordinates_not_detected', '坐标: 未检测到'))
        self.coordinates_label.setStyleSheet("font-size: 12px;")
        status_layout.addWidget(self.coordinates_label)
        
        # OCR输出显示 - 增强版
        output_header_layout = QHBoxLayout()
        self.output_label = QLabel(tr('ocr_output', 'OCR输出:'))
        output_header_layout.addWidget(self.output_label)
        
        # 添加清空日志按钮
        self.clear_log_btn = QPushButton(tr('clear_log', '清空日志'))
        self.clear_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                font-size: 10px;
                padding: 4px 8px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        self.clear_log_btn.clicked.connect(self.clear_ocr_logs)
        output_header_layout.addWidget(self.clear_log_btn)
        
        # 添加保存日志按钮
        self.save_log_btn = QPushButton(tr('save_log', '保存日志'))
        self.save_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                font-size: 10px;
                padding: 4px 8px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        self.save_log_btn.clicked.connect(self.save_ocr_logs)
        output_header_layout.addWidget(self.save_log_btn)
        
        output_header_layout.addStretch()
        status_layout.addLayout(output_header_layout)
        
        # 增大日志显示区域
        self.output_text = QTextEdit()
        self.output_text.setMinimumHeight(250)  # 从100增加到250
        self.output_text.setMaximumHeight(400)  # 设置最大高度以便调整窗口大小
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                line-height: 1.2;
            }
        """)
        
        # 设置文本换行和滚动
        self.output_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.output_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.output_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        status_layout.addWidget(self.output_text)
        
        # 初始化日志历史
        self.log_history = []
        self.max_log_entries = 1000  # 最多保存1000条日志记录
        
        layout.addWidget(status_group)
    
    def show_advanced_settings(self):
        """显示高级设置对话框"""
        if self.advanced_dialog is None:
            self.advanced_dialog = OCRAdvancedSettings(self.ocr_manager, self)
        
        self.advanced_dialog.load_advanced_settings()  # 重新加载当前设置
        self.advanced_dialog.exec()
    
    def detect_window(self):
        """打开窗口选择对话框"""
        try:
            dialog = WindowSelectionDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_window = dialog.get_selected_window()
                if selected_window:
                    self.window_name_edit.setText(selected_window)
                    QMessageBox.information(self, "选择成功", f"已选择窗口: {selected_window}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"打开窗口选择对话框失败: {e}")
    
    def connect_signals(self):
        """连接信号"""
        pass  # 信号连接在OCRManager中处理
    
    def update_ui_from_config(self):
        """从配置更新UI"""
        config = self.ocr_manager.ocr_config
        
        # 更新界面控件
        self.interval_spinbox.setValue(config.get('ocr_interval', 1000))
        self.confidence_spinbox.setValue(config.get('confidence_threshold', 0.45))
        self.window_name_edit.setText(config.get('target_window_name', ''))
        
        # 设置截图模式
        mode = config.get('screenshot_mode', 'BitBlt')
        if mode == 'PrintWindow':
            self.capture_mode_combo.setCurrentIndex(1)
        else:
            self.capture_mode_combo.setCurrentIndex(0)
    
    def setup_ocr_region(self):
        """设置OCR区域"""
        self.ocr_manager.setup_ocr_region()
    
    def start_ocr(self):
        """开始OCR识别"""
        success = self.ocr_manager.start_ocr()
        if success:
            # 注意：不要在这里重复连接信号！
            # OCRManager.start_ocr() 中已经连接了所有必要的信号
            # 这里重复连接会导致每个信号触发两次
            
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.state_label.setText(tr('status_recognizing', '状态: 识别中'))
    
    def stop_ocr(self):
        """停止OCR识别"""
        self.ocr_manager.stop_ocr()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.state_label.setText(tr('status_stopped', '状态: 已停止'))
    
    def on_interval_changed(self, value):
        """识别间隔变化"""
        self.ocr_manager.update_ocr_interval(value)
    
    def on_confidence_changed(self, value):
        """置信度变化"""
        self.ocr_manager.update_confidence_threshold(value)
    
    def update_state(self, state):
        """更新状态显示"""
        state_colors = {
            'LOCKED': '#4CAF50',    # 绿色
            'LOST': '#f44336',      # 红色
            'SEARCHING': '#FF9800'  # 橙色
        }
        color = state_colors.get(state, '#0078D7')
        self.state_label.setText(tr('status_format', '状态: {state}', state=state))
        self.state_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")
    
    def update_coordinates(self, x, y, z):
        """更新坐标显示"""
        self.coordinates_label.setText(tr('coordinates_format', '坐标: ({x}, {y}, {z})', x=x, y=y, z=z))
        self.coordinates_label.setStyleSheet("font-size: 12px; color: #4CAF50; font-weight: bold;")
    
    def update_ocr_output(self, output):
        """更新OCR输出显示 - 增强版带日志保留"""
        from datetime import datetime
        
        # 添加时间戳
        timestamp = datetime.now().strftime("%H:%M:%S")
        timestamped_output = f"[{timestamp}] {output}"
        
        # 添加到历史记录
        self.log_history.append(timestamped_output)
        
        # 限制历史记录数量
        if len(self.log_history) > self.max_log_entries:
            self.log_history.pop(0)
        
        # 更新显示 - 保留之前的内容
        self.output_text.append(timestamped_output)
        
        # 自动滚动到底部
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_region_info(self, x, y, width, height):
        """更新区域信息显示"""
        # 在状态标签中显示区域信息
        self.state_label.setText(tr('status_region_set', '状态: 区域已设置 ({x}, {y}, {width}x{height})', x=x, y=y, width=width, height=height))
    
    def clear_ocr_logs(self):
        """清空OCR日志"""
        self.output_text.clear()
        self.log_history.clear()
        
        # 添加清空日志的记录
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        clear_message = f"[{timestamp}] === 日志已清空 ==="
        self.log_history.append(clear_message)
        self.output_text.append(clear_message)
    
    def save_ocr_logs(self):
        """保存OCR日志到文件"""
        if not self.log_history:
            QMessageBox.information(self, "保存日志", "没有日志可以保存")
            return
        
        from datetime import datetime
        from PySide6.QtWidgets import QFileDialog
        import os
        
        # 默认文件名：包含当前日期时间
        default_filename = f"OCR_日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # 弹出保存对话框
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存OCR日志",
            default_filename,
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"OCR日志导出\n")
                    f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"总记录数: {len(self.log_history)}\n")
                    f.write("=" * 50 + "\n\n")
                    
                    for log_entry in self.log_history:
                        f.write(log_entry + "\n")
                
                QMessageBox.information(self, "保存成功", f"日志已保存到:\n{file_path}")
                
                # 添加保存成功的记录到日志中
                timestamp = datetime.now().strftime("%H:%M:%S")
                save_message = f"[{timestamp}] ✓ 日志已保存到: {os.path.basename(file_path)}"
                self.log_history.append(save_message)
                self.output_text.append(save_message)
                
                # 自动滚动到底部
                scrollbar = self.output_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
                
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"保存日志时出错:\n{str(e)}")
    
    def get_log_history(self):
        """获取日志历史记录"""
        return self.log_history.copy()
    
    def load_previous_logs(self, logs):
        """加载之前的日志记录"""
        if logs:
            self.log_history.extend(logs)
            
            # 限制总数量
            if len(self.log_history) > self.max_log_entries:
                self.log_history = self.log_history[-self.max_log_entries:]
            
            # 更新显示
            self.output_text.clear()
            for log_entry in self.log_history:
                self.output_text.append(log_entry)
            
            # 滚动到底部
            scrollbar = self.output_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.advanced_dialog:
            self.advanced_dialog.close()
        event.accept()


class OCRManager(QObject):
    """
    OCR管理器 - 协调OCR引擎、UI界面和主应用程序
    """
    
    # 信号定义
    coordinates_detected = Signal(int, int, int)  # 检测到坐标时发射
    state_changed = Signal(str)  # 状态变化时发射
    error_occurred = Signal(str)  # 发生错误时发射
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 配置文件路径
        self.config_file = Path("ocr_config.json")
        
        # 默认配置
        self.default_config = {
            'confidence_threshold': 0.45,
            'ocr_interval': 1000,
            'model_path': 'models/coord_ocr.pt',
            'ocr_capture_area': {
                'x': 100,
                'y': 100,
                'width': 200,
                'height': 50
            },
            'advanced_ocr_settings': {
                'max_speed_threshold': 1000,
                'lost_threshold_frames': 5,
                'z_axis_threshold': 50,
                'verbose_debug': False  # 默认关闭详细调试，需要时手动开启
            },
            'target_window_name': '',
            'screenshot_mode': 'BitBlt',
            'auto_jump_enabled': True  # 默认启用自动跳转
        }
        
        # 加载配置
        self.ocr_config = self.load_config()
        
        # OCR工作线程
        self.ocr_worker = None
        
        # 控制面板
        self.control_panel = None
        
        # 区域校准器
        self.region_calibrator = None
        
        # 自动跳转功能
        self.auto_jump_enabled = self.ocr_config.get('auto_jump_enabled', True)
        self.jump_callback = None  # 跳转回调函数
        
        # 日志持久化
        self.log_file = self.config_file.parent / "ocr_logs.json"
        self.max_stored_logs = 500  # 最多存储500条日志记录
    
    def load_config(self) -> Dict[str, Any]:
        """加载OCR配置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # 合并默认配置（确保所有必需的键都存在）
                merged_config = self.default_config.copy()
                merged_config.update(config)
                return merged_config
            else:
                return self.default_config.copy()
        except Exception as e:
            print(f"加载OCR配置失败: {e}")
            return self.default_config.copy()
    
    def save_config(self):
        """保存OCR配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.ocr_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存OCR配置失败: {e}")
    
    def load_logs(self) -> list:
        """加载之前保存的日志"""
        try:
            if self.log_file.exists():
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('logs', [])
            return []
        except Exception as e:
            print(f"加载OCR日志失败: {e}")
            return []
    
    def save_logs(self, logs: list):
        """保存日志到文件"""
        try:
            # 限制存储的日志数量
            if len(logs) > self.max_stored_logs:
                logs = logs[-self.max_stored_logs:]
            
            data = {
                'logs': logs,
                'last_saved': datetime.now().isoformat(),
                'total_count': len(logs)
            }
            
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"保存OCR日志失败: {e}")
    
    def show_control_panel(self):
        """显示控制面板"""
        if self.control_panel is None:
            self.control_panel = OCRControlPanel(self)
            
            # 加载之前的日志
            previous_logs = self.load_logs()
            if previous_logs:
                self.control_panel.load_previous_logs(previous_logs)
        
        if not self.control_panel.isVisible():
            self.control_panel.show()
        else:
            self.control_panel.raise_()
            self.control_panel.activateWindow()
    
    def setup_ocr_region(self):
        """设置OCR区域"""
        try:
            # 如果已有校准器在运行，先关闭
            if self.region_calibrator is not None:
                self.region_calibrator.close()
                self.region_calibrator = None
            
            # 创建区域校准器
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                app = QApplication([])
            
            self.region_calibrator = OCRRegionCalibrator(app)
            self.region_calibrator.region_selected.connect(self.on_region_selected)
            self.region_calibrator.selection_cancelled.connect(self.on_region_cancelled)
            
            # 显示校准器
            self.region_calibrator.show()
            self.region_calibrator.raise_()
            self.region_calibrator.activateWindow()
            
            print("OCR区域校准工具已启动")
            
        except Exception as e:
            error_msg = f"启动OCR区域校准失败: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(error_msg)
    
    @Slot(int, int, int, int)
    def on_region_selected(self, x, y, width, height):
        """OCR区域选择完成"""
        self.ocr_config['ocr_capture_area'] = {
            'x': x,
            'y': y,
            'width': width,
            'height': height
        }
        self.save_config()
        
        # 更新控制面板显示
        if self.control_panel:
            self.control_panel.update_region_info(x, y, width, height)
        
        # 清理校准器引用
        self.region_calibrator = None
        
        print(f"OCR区域已设置: ({x}, {y}, {width}, {height})")
    
    @Slot()
    def on_region_cancelled(self):
        """OCR区域选择取消"""
        # 清理校准器引用
        self.region_calibrator = None
        print("OCR区域选择已取消")
    
    def start_ocr(self):
        """启动OCR识别"""
        try:
            # 检查是否已设置OCR区域
            area = self.ocr_config.get('ocr_capture_area')
            if not area or area.get('width', 0) <= 0 or area.get('height', 0) <= 0:
                self.error_occurred.emit("请先设置OCR识别区域")
                return False
            
            # 检查模型文件是否存在
            model_path = Path(self.ocr_config.get('model_path', 'models/coord_ocr.pt'))
            if not model_path.exists():
                self.error_occurred.emit(f"OCR模型文件不存在: {model_path}")
                return False
            
            # 创建OCR工作线程
            if self.ocr_worker is not None:
                self.stop_ocr()
            
            self.ocr_worker = OCRWorker(config_dict=self.ocr_config)
            self.ocr_worker.set_capture_callback(capture_region_callback)
            
            # 连接信号
            self.ocr_worker.coordinates_detected.connect(self.on_coordinates_detected)
            self.ocr_worker.recognition_state_changed.connect(self.on_state_changed)
            self.ocr_worker.error_occurred.connect(self.on_error_occurred)
            self.ocr_worker.ocr_output_updated.connect(self.on_ocr_output_updated)
            
            # 启动OCR
            self.ocr_worker.start_recognition()
            
            print("OCR识别已启动")
            return True
            
        except Exception as e:
            error_msg = f"启动OCR识别失败: {e}"
            print(error_msg)
            self.error_occurred.emit(error_msg)
            return False
    
    def stop_ocr(self):
        """停止OCR识别"""
        try:
            if self.ocr_worker is not None:
                self.ocr_worker.stop_recognition()
                self.ocr_worker.deleteLater()
                self.ocr_worker = None
            
            print("OCR recognition stopped")
            
        except Exception as e:
            error_msg = f"停止OCR识别失败: {e}"
            print(error_msg)
            self.error_occurred.emit(error_msg)
    
    def is_running(self) -> bool:
        """检查OCR是否正在运行"""
        return self.ocr_worker is not None and self.ocr_worker.is_running
    
    def get_current_state(self) -> str:
        """获取当前OCR状态"""
        if self.ocr_worker is not None:
            return self.ocr_worker.get_current_state()
        return "STOPPED"
    
    def update_confidence_threshold(self, threshold: float):
        """更新置信度阈值"""
        self.ocr_config['confidence_threshold'] = threshold
        if self.ocr_worker is not None:
            self.ocr_worker.update_confidence_threshold(threshold)
        self.save_config()
    
    def update_ocr_interval(self, interval: int):
        """更新OCR识别间隔"""
        self.ocr_config['ocr_interval'] = interval
        if self.ocr_worker is not None:
            self.ocr_worker.update_interval(interval)
        self.save_config()
    
    def update_advanced_parameter(self, param_name: str, value):
        """更新高级参数"""
        if 'advanced_ocr_settings' not in self.ocr_config:
            self.ocr_config['advanced_ocr_settings'] = {}
        
        self.ocr_config['advanced_ocr_settings'][param_name] = value
        
        if self.ocr_worker is not None:
            self.ocr_worker.update_advanced_parameters({param_name: value})
        
        self.save_config()
    
    def set_auto_jump(self, enabled: bool):
        """设置自动跳转功能"""
        self.auto_jump_enabled = enabled
        # 保存配置
        self.ocr_config['auto_jump_enabled'] = enabled
        self.save_config()
    
    def set_jump_callback(self, callback):
        """设置坐标跳转回调函数"""
        self.jump_callback = callback
    
    @Slot(int, int, int)
    def on_coordinates_detected(self, x, y, z):
        """坐标检测到时的处理"""
        # 更新控制面板显示
        if self.control_panel:
            self.control_panel.update_coordinates(x, y, z)
        
        # 发射信号
        self.coordinates_detected.emit(x, y, z)
        
        # 自动跳转功能
        if self.auto_jump_enabled and self.jump_callback:
            try:
                self.jump_callback(x, y, z)
            except Exception as e:
                print(f"自动跳转失败: {e}")
    
    @Slot(str)
    def on_state_changed(self, state):
        """状态变化时的处理"""
        # 更新控制面板显示
        if self.control_panel:
            self.control_panel.update_state(state)
        
        # 发射信号
        self.state_changed.emit(state)
    
    @Slot(str)
    def on_error_occurred(self, error_msg):
        """错误发生时的处理"""
        print(f"OCR错误: {error_msg}")
        self.error_occurred.emit(error_msg)
    
    @Slot(str)
    def on_ocr_output_updated(self, output):
        """OCR输出更新时的处理"""
        # 更新控制面板显示
        if self.control_panel:
            self.control_panel.update_ocr_output(output)
    
    def cleanup(self):
        """清理资源"""
        # 保存日志到文件
        if self.control_panel and hasattr(self.control_panel, 'log_history'):
            try:
                self.save_logs(self.control_panel.get_log_history())
                print("OCR日志已保存到持久化存储")
            except Exception as e:
                print(f"保存OCR日志时出错: {e}")
        
        self.stop_ocr()
        if self.control_panel:
            self.control_panel.close()
            self.control_panel = None
        if self.region_calibrator:
            self.region_calibrator.close()
            self.region_calibrator = None