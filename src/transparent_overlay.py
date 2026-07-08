#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
透明覆盖层控件
用于在Web界面上显示中心圆点，支持鼠标穿透和Z轴颜色映射
"""

import math
from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QObject, QRectF
from PySide6.QtGui import QPainter, QColor


SVG_CIRCLE_CX = 50.0
SVG_CIRCLE_CY = 64.0
SVG_CIRCLE_R = 16.0
SVG_VIEWBOX_SIZE = 128.0
PLAYER_MARKER_ARROW_PATH = '<path d="M 63.44,50.56 A 19,19 0 0,1 63.44,77.44 L 83,64 Z" fill="{fill}">\n</path>'
PLAYER_MARKER_SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="100" height="100">
                <!-- Solid Circle (Player Center) -->
                <circle cx="50" cy="64" r="16" fill="{fill}">
</circle>
                <!-- Directional Arrow, path is dynamically injected by Python -->
                {arrow_path}
            </svg>"""


class TransparentOverlay(QWidget):
    """透明覆盖层控件"""
    
    def __init__(self, parent=None, resource_probe=None):
        super().__init__(parent)
        self._resource_probe = resource_probe
        
        # 设置窗口属性：透明背景、鼠标穿透
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 移除WindowStaysOnTopHint，改为只相对于父控件显示在上方
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # 圆点属性
        self.circle_radius = 5.0  # 圆点半径（默认 5px，对应 50.0%）
        self.circle_color = QColor(255, 0, 0)  # 默认红色
        self.z_color_mapping = False  # Z轴颜色映射开关
        self.current_z_value = 0  # 当前Z值
        self.heading_degrees = None
        
        # 当前覆盖层没有连续动画；半径/Z值变化时由对应 setter 主动 update。
        self.animation_timer = None
        
    def set_circle_radius(self, radius):
        """设置圆点半径"""
        self.circle_radius = max(0.1, min(50.0, float(radius)))
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

    def set_heading_degrees(self, heading_degrees):
        """设置人物朝向角度：北=0，顺时针增加。"""
        try:
            angle = float(heading_degrees)
        except (TypeError, ValueError):
            self.clear_heading()
            return
        if not math.isfinite(angle):
            self.clear_heading()
            return
        self.heading_degrees = angle % 360.0
        self.update()

    def clear_heading(self):
        """清除人物朝向指示。"""
        self.heading_degrees = None
        self.update()
    
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
        if self._resource_probe:
            self._resource_probe.count("overlay.paint")
        painter = QPainter(self)
        # 不使用抗锯齿，确保边缘硬度100%
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        
        # 获取窗口中心
        center_x = self.width() // 2
        center_y = self.height() // 2

        if self.circle_radius > 0:
            self._draw_player_marker(painter, float(center_x), float(center_y))

    def _draw_player_marker(self, painter: QPainter, center_x: float, center_y: float):
        """Draw the unified SVG marker, scaled by the original dot radius."""
        radius = float(self.circle_radius)
        scale = radius / SVG_CIRCLE_R
        svg_size = SVG_VIEWBOX_SIZE * scale
        east_reference_degrees = 90.0
        rotation_degrees = 0.0
        if self.heading_degrees is not None:
            rotation_degrees = float(self.heading_degrees) - east_reference_degrees
        fill = QColor(self.circle_color).name()
        arrow_path = PLAYER_MARKER_ARROW_PATH if self.heading_degrees is not None else ""
        svg_text = PLAYER_MARKER_SVG_TEMPLATE.replace("{arrow_path}", arrow_path).replace("{fill}", fill)
        renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        if not renderer.isValid():
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(rotation_degrees)
        target = QRectF(-SVG_CIRCLE_CX * scale, -SVG_CIRCLE_CY * scale, svg_size, svg_size)
        renderer.render(painter, target)
        painter.restore()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    
    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        self.update()


class OverlayManager(QObject):
    """覆盖层管理器"""
    
    def __init__(self, web_view, resource_probe=None):
        super().__init__()
        self.web_view = web_view
        self._resource_probe = resource_probe
        self.overlay = None
        self.setup_overlay()
    
    def setup_overlay(self):
        """设置覆盖层"""
        # 创建透明覆盖层，设置web_view为父控件
        self.overlay = TransparentOverlay(self.web_view, self._resource_probe)
        
        # 初始化覆盖层大小和位置
        self.update_overlay_geometry()
        
        # 监听web_view的大小变化
        if self.web_view:
            self.web_view.installEventFilter(self)
            
    def update_overlay_geometry(self):
        """更新覆盖层的几何位置"""
        if self._resource_probe:
            self._resource_probe.count("overlay.geometry")
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

    def set_heading_degrees(self, heading_degrees):
        """设置人物朝向角度。"""
        if self.overlay:
            self.overlay.set_heading_degrees(heading_degrees)

    def clear_heading(self):
        """清除人物朝向指示。"""
        if self.overlay:
            self.overlay.clear_heading()
    
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
        if self.overlay and self.overlay.animation_timer:
            self.overlay.animation_timer.stop()
            self.overlay.animation_timer = None

        # 清理覆盖层
        if self.overlay:
            self.overlay.close()
            self.overlay = None
