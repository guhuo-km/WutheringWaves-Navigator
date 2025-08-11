#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分离出来的地图窗口
将原有的WebView地图界面完整移动到独立窗口中，保持所有原有逻辑
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtWebEngineWidgets import QWebEngineView


class SeparatedMapWindow(QWidget):
    """分离出来的地图窗口 - 使用原有的WebView"""
    
    # 信号定义（与主窗口通信）
    window_closed = Signal()
    
    def __init__(self, web_view, main_window, parent=None):
        """
        初始化分离的地图窗口
        
        Args:
            web_view: 主窗口的WebView对象
            main_window: 主窗口引用，用于保持原有逻辑
            parent: 父窗口
        """
        super().__init__(parent)
        
        # 保存引用
        self.web_view = web_view
        self.main_window = main_window
        self._is_closing = False  # 关闭标志
        
        # 设置窗口属性
        self.setWindowTitle("鸣潮地图导航 - 地图窗口")
        self.setGeometry(100, 100, 630, 580)
        
        # 设置UI
        self.setup_ui()
        
        print("分离地图窗口初始化完成")
    
    def setup_ui(self):
        """设置用户界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 将WebView添加到此窗口
        if self.web_view:
            # 如果WebView有父窗口，先从父窗口中移除
            if self.web_view.parent():
                self.web_view.setParent(None)
            
            # 将WebView添加到此窗口
            layout.addWidget(self.web_view)
            
            print("WebView已移动到独立窗口")
        else:
            error_label = QLabel("错误：未提供WebView对象")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("color: red; font-size: 16px;")
            layout.addWidget(error_label)
    
    def show_at_position(self, main_window_geometry):
        """在主窗口右侧显示"""
        try:
            # 计算位置（在主窗口右侧）
            map_x = main_window_geometry.x() + main_window_geometry.width() + 20
            map_y = main_window_geometry.y()
            map_width = 630
            map_height = 580
            
            self.setGeometry(map_x, map_y, map_width, map_height)
            self.show()
            self.raise_()
            
            print(f"地图窗口显示在位置: ({map_x}, {map_y}, {map_width}, {map_height})")
            
        except Exception as e:
            print(f"显示地图窗口失败: {e}")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            if self._is_closing:
                print("地图窗口正在被主窗口关闭...")
                event.accept()
                return
            
            print("地图窗口关闭，退出整个程序...")
            self._is_closing = True
            
            # 将WebView返还给主窗口（如果需要的话）
            if self.web_view and self.main_window:
                # 不要返还，让主窗口知道地图窗口已关闭即可
                pass
            
            # 发射关闭信号
            self.window_closed.emit()
            
            # 关闭主窗口，退出整个程序
            if self.main_window and hasattr(self.main_window, '_is_closing') and not self.main_window._is_closing:
                self.main_window.close()
            
            print("地图窗口已关闭，程序退出")
            event.accept()
            
        except Exception as e:
            print(f"关闭地图窗口时出错: {e}")
            event.accept()