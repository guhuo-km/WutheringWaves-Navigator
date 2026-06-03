# -*- coding: utf-8 -*-
"""
窗口选择对话框
从 ocr_manager.py 提取
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox
from PySide6.QtCore import Qt
from qfluentwidgets import BodyLabel, PushButton

# 多语言支持
try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key


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
        info_label = BodyLabel(tr('double_click_to_select', '双击选择目标窗口：'))
        info_label.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        # 窗口列表
        self.window_list = QListWidget()
        self.window_list.itemDoubleClicked.connect(self.on_window_selected)
        layout.addWidget(self.window_list)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        refresh_btn = PushButton(tr('refresh_list', '刷新列表'))
        refresh_btn.clicked.connect(self.load_windows)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        
        cancel_btn = PushButton(tr('cancel', '取消'))
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
