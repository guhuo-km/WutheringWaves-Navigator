#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
透明覆盖层控件
用于在Web界面上显示中心圆点，支持鼠标穿透和Z轴颜色映射
"""

import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QTimer, QObject
from PySide6.QtGui import QPainter, QPen, QBrush, QColor


class TransparentOverlay(QWidget):
    """透明覆盖层控件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置窗口属性：透明背景、鼠标穿透
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 移除WindowStaysOnTopHint，改为只相对于父控件显示在上方
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # 圆点属性
        self.circle_radius = 10  # 圆点半径 (1-50)
        self.circle_color = QColor(255, 0, 0)  # 默认红色
        self.z_color_mapping = False  # Z轴颜色映射开关
        self.current_z_value = 0  # 当前Z值
        
        # 动画定时器（用于颜色变化动画）
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update)
        self.animation_timer.start(50)  # 20fps更新
        
    def set_circle_radius(self, radius):
        """设置圆点半径"""
        self.circle_radius = max(1, min(50, radius))
        self.update()
    
    def set_z_color_mapping(self, enabled):
        """设置Z轴颜色映射开关"""
        self.z_color_mapping = enabled
        self.update_circle_color()
    
    def set_z_value(self, z_value):
        """设置当前Z值"""
        self.current_z_value = z_value
        if self.z_color_mapping:
            self.update_circle_color()
    
    def update_circle_color(self):
        """根据Z值更新圆点颜色"""
        if not self.z_color_mapping:
            self.circle_color = QColor(255, 0, 0)  # 默认红色
            self.update()
            return
        
        # Z值范围：-100 到 300，总跨度400
        z_range = 400
        z_min = -100
        
        # 将Z值映射到0-1范围
        normalized_z = ((self.current_z_value - z_min) % z_range) / z_range
        
        # HSL颜色映射
        hue = int(normalized_z * 360)  # 色相：0-360度
        saturation = 85  # 饱和度：85%（较高）
        lightness = 65   # 亮度：65%（中间偏高）
        
        # 创建HSL颜色
        self.circle_color = QColor()
        self.circle_color.setHsl(hue, int(saturation * 255 / 100), int(lightness * 255 / 100))
        
        self.update()
    
    def paintEvent(self, event):
        """绘制事件"""
        painter = QPainter(self)
        # 不使用抗锯齿，确保边缘硬度100%
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        
        # 获取窗口中心
        center_x = self.width() // 2
        center_y = self.height() // 2
        
        # 绘制中心圆点
        if self.circle_radius > 0:
            # 只绘制主圆点，边缘硬度100%，无阴影效果
            painter.setPen(QPen(self.circle_color, 1))
            painter.setBrush(QBrush(self.circle_color))
            painter.drawEllipse(center_x - self.circle_radius, 
                              center_y - self.circle_radius,
                              self.circle_radius * 2, 
                              self.circle_radius * 2)
    
    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        self.update()


class OverlayManager(QObject):
    """覆盖层管理器"""
    
    def __init__(self, web_view):
        super().__init__()
        self.web_view = web_view
        self.overlay = None
        self.setup_overlay()
    
    def setup_overlay(self):
        """设置覆盖层"""
        # 创建透明覆盖层，设置web_view为父控件
        self.overlay = TransparentOverlay(self.web_view)
        
        # 初始化覆盖层大小和位置
        self.update_overlay_geometry()
        
        # 监听web_view的大小变化
        if self.web_view:
            self.web_view.installEventFilter(self)
            
        # 创建定时器用于实时更新位置
        self.position_timer = QTimer()
        self.position_timer.timeout.connect(self.update_overlay_geometry)
        self.position_timer.start(50)  # 每50ms更新一次位置
    
    def update_overlay_geometry(self):
        """更新覆盖层的几何位置"""
        if not self.overlay or not self.web_view:
            return
        
        # 获取web_view的大小和位置（相对于父控件）
        size = self.web_view.size()
        pos = self.web_view.pos()
        
        # 设置覆盖层的位置和大小（相对于web_view的父控件）
        self.overlay.setGeometry(0, 0, size.width(), size.height())
        
        # 显示覆盖层并确保它在web_view上方
        if not self.overlay.isVisible():
            self.overlay.show()
        self.overlay.raise_()
    
    def eventFilter(self, obj, event):
        """事件过滤器，监听web_view的几何变化"""
        from PySide6.QtCore import QEvent
        
        if obj == self.web_view and event.type() in [
            QEvent.Type.Resize, 
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.Hide
        ]:
            # 立即更新几何位置（因为已经有定时器了，这里不需要延迟）
            self.update_overlay_geometry()
        
        return False
    
    def set_circle_radius(self, radius):
        """设置圆点半径"""
        if self.overlay:
            self.overlay.set_circle_radius(radius)
    
    def set_z_color_mapping(self, enabled):
        """设置Z轴颜色映射"""
        if self.overlay:
            self.overlay.set_z_color_mapping(enabled)
    
    def set_z_value(self, z_value):
        """设置Z值"""
        if self.overlay:
            self.overlay.set_z_value(z_value)
    
    def show_overlay(self):
        """显示覆盖层"""
        if self.overlay:
            self.update_overlay_geometry()
            self.overlay.show()
            self.overlay.raise_()
    
    def hide_overlay(self):
        """隐藏覆盖层"""
        if self.overlay:
            self.overlay.hide()
    
    def cleanup(self):
        """清理资源"""
        # 停止定时器
        if hasattr(self, 'position_timer') and self.position_timer:
            self.position_timer.stop()
            self.position_timer = None
            
        # 清理覆盖层
        if self.overlay:
            self.overlay.close()
            self.overlay = None