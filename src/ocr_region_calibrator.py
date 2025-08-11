#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR Region Calibrator for WutheringWaves Navigator
OCR区域校准工具
"""

import sys
from PySide6.QtWidgets import QApplication, QWidget, QPushButton
from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QScreen, QPen, QBrush, QPainterPath, QFont, QCursor


# 定义八个控制点的位置
class HandleOptions:
    TOP_LEFT = 1
    TOP_MIDDLE = 2
    TOP_RIGHT = 3
    MIDDLE_LEFT = 4
    MIDDLE_RIGHT = 5
    BOTTOM_LEFT = 6
    BOTTOM_MIDDLE = 7
    BOTTOM_RIGHT = 8


class OCRRegionCalibrator(QWidget):
    """
    OCR 区域校准工具主窗口 (边缘预览优化版)
    用于让用户选择OCR识别的屏幕区域
    """
    
    # 信号：当用户确认选择区域时发射 (x, y, width, height)
    region_selected = Signal(int, int, int, int)
    # 信号：当用户取消选择时发射
    selection_cancelled = Signal()
    
    def __init__(self, app=None):
        super().__init__()
        if app is None:
            self.app = QApplication.instance()
            if self.app is None:
                self.app = QApplication(sys.argv)
        else:
            self.app = app
            
        self.screen = self.app.primaryScreen()
        self.desktop_pixmap = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.is_selecting = False
        self.selection_start_pos = QPoint()
        self.selection_rect = QRect()
        self.active_handle = None
        self.is_moving = False
        
        self.init_ui()

    def showEvent(self, event):
        if self.desktop_pixmap is None:
             self.desktop_pixmap = self.screen.grabWindow(0)
        super().showEvent(event)

    def init_ui(self):
        """初始化工具栏按钮"""
        self.confirm_button = QPushButton("✔", self)
        self.confirm_button.setGeometry(0, 0, 30, 30)
        self.confirm_button.setFont(QFont("Arial", 12))
        self.confirm_button.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border-radius: 15px; border: 1px solid #3e8e41; }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.confirm_button.clicked.connect(self.confirm_selection)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.hide()

        self.cancel_button = QPushButton("✘", self)
        self.cancel_button.setGeometry(0, 0, 30, 30)
        self.cancel_button.setFont(QFont("Arial", 12))
        self.cancel_button.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white; border-radius: 15px; border: 1px solid #da190b; }
            QPushButton:hover { background-color: #e53935; }
        """)
        self.cancel_button.clicked.connect(self.cancel_selection)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.hide()

    def paintEvent(self, event):
        if not self.desktop_pixmap:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        overlay_path = QPainterPath()
        overlay_path.addRect(QRectF(self.rect()))
        if not self.selection_rect.isNull():
            selection_path = QPainterPath()
            selection_path.addRect(QRectF(self.selection_rect))
            overlay_path -= selection_path
        painter.drawPixmap(self.rect(), self.desktop_pixmap)
        painter.fillPath(overlay_path, QColor(0, 0, 0, 120))
        if not self.selection_rect.isNull():
            pen = QPen(QColor("#0078D7"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.selection_rect)
            handle_rects = list(self.get_handle_rects().values())
            if handle_rects:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#0078D7")))
                painter.drawRects(handle_rects)
            self.draw_info_box(painter)
            self.draw_magnifier(painter)

    def draw_info_box(self, painter):
        info_text = f"OCR区域: {self.selection_rect.x()}, {self.selection_rect.y()} - {self.selection_rect.width()}x{self.selection_rect.height()}"
        font = QFont("Arial", 10)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(info_text)
        text_rect.adjust(-4, -2, 4, 2)
        info_box_pos = self.selection_rect.topLeft() - QPoint(0, text_rect.height() + 4)
        if info_box_pos.y() < 0:
             info_box_pos = self.selection_rect.topLeft() + QPoint(4, 4)
        info_box_rect = text_rect.translated(info_box_pos)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRect(info_box_rect)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(info_box_rect, Qt.AlignmentFlag.AlignCenter, info_text)

    def draw_magnifier(self, painter):
        """在鼠标指针附近绘制放大镜 (已优化边缘位置)"""
        cursor_pos = self.mapFromGlobal(QCursor.pos())
        screen_rect = self.rect()  # 获取全屏窗口的矩形

        # 放大镜参数
        mag_size = 120    # 放大镜的直径
        offset = 20       # 与光标的距离
        zoom_factor = 2
        source_size = int(mag_size / zoom_factor)

        # 动态计算放大镜位置
        # 默认位置在光标右下方
        mag_x = cursor_pos.x() + offset
        mag_y = cursor_pos.y() + offset

        # 如果会超出右侧边界，则翻转到左侧
        if mag_x + mag_size > screen_rect.right():
            mag_x = cursor_pos.x() - offset - mag_size

        # 如果会超出底部边界，则翻转到上方
        if mag_y + mag_size > screen_rect.bottom():
            mag_y = cursor_pos.y() - offset - mag_size
        
        magnifier_rect = QRect(mag_x, mag_y, mag_size, mag_size)

        # 计算要放大的源图像区域
        source_rect = QRect(
            cursor_pos.x() - source_size // 2,
            cursor_pos.y() - source_size // 2,
            source_size, source_size)
        
        # 绘制
        path = QPainterPath()
        path.addEllipse(magnifier_rect.toRectF())
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(magnifier_rect, self.desktop_pixmap, source_rect)
        painter.restore()
        
        painter.setPen(QPen(QColor("#0078D7"), 2))
        painter.drawEllipse(magnifier_rect)
        
        cx, cy = magnifier_rect.center().x(), magnifier_rect.center().y()
        painter.setPen(QPen(QColor("red"), 1))
        painter.drawLine(cx, cy - mag_size // 2, cx, cy + mag_size // 2)
        painter.drawLine(cx - mag_size // 2, cy, cx + mag_size // 2, cy)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.selection_rect.isNull():
                self.active_handle = self.get_handle_at(event.pos())
                if self.active_handle: return
                elif self.selection_rect.contains(event.pos()):
                    self.is_moving = True
                    self.selection_start_pos = event.pos()
                    return
                else: return
            else:
                self.is_selecting = True
                self.selection_start_pos = event.pos()
                self.selection_rect = QRect(self.selection_start_pos, QSize())
                self.confirm_button.hide()
                self.cancel_button.hide()
                self.update()

    def mouseMoveEvent(self, event):
        self.update_cursor_shape(event.pos())
        if self.is_selecting:
            self.selection_rect = QRect(self.selection_start_pos, event.pos()).normalized()
        elif self.active_handle:
            self.resize_selection(event.pos())
            self.update_toolbar_position()
        elif self.is_moving:
            delta = event.pos() - self.selection_start_pos
            self.selection_rect.translate(delta)
            self.selection_start_pos = event.pos()
            self.update_toolbar_position()
        self.update()

    def mouseReleaseEvent(self, event):
        # 释放时，如果创建的选区过小则判定为无效
        if self.is_selecting and self.selection_rect.width() < 5 and self.selection_rect.height() < 5:
            self.selection_rect = QRect()
        
        if self.is_selecting or self.active_handle or self.is_moving:
            if not self.selection_rect.isNull():
                self.update_toolbar_position()
                self.confirm_button.show()
                self.cancel_button.show()

        self.is_selecting = False
        self.active_handle = None
        self.is_moving = False
        self.update_cursor_shape(event.pos())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_selection()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self.selection_rect.isNull(): 
                self.confirm_selection()

    def confirm_selection(self):
        """确认选择区域"""
        rect = self.selection_rect
        print(f"OCR区域已选择: x={rect.x()}, y={rect.y()}, width={rect.width()}, height={rect.height()}")
        # 发射信号
        self.region_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())
        self.close()
    
    def cancel_selection(self):
        """取消选择"""
        print("OCR区域选择已取消")
        self.selection_cancelled.emit()
        self.close()
        
    def get_handle_rects(self, size=8):
        if self.selection_rect.isNull(): return {}
        offset = size // 2
        r = self.selection_rect
        return {
            HandleOptions.TOP_LEFT: QRect(r.left() - offset, r.top() - offset, size, size),
            HandleOptions.TOP_MIDDLE: QRect(r.center().x() - offset, r.top() - offset, size, size),
            HandleOptions.TOP_RIGHT: QRect(r.right() - offset, r.top() - offset, size, size),
            HandleOptions.MIDDLE_LEFT: QRect(r.left() - offset, r.center().y() - offset, size, size),
            HandleOptions.MIDDLE_RIGHT: QRect(r.right() - offset, r.center().y() - offset, size, size),
            HandleOptions.BOTTOM_LEFT: QRect(r.left() - offset, r.bottom() - offset, size, size),
            HandleOptions.BOTTOM_MIDDLE: QRect(r.center().x() - offset, r.bottom() - offset, size, size),
            HandleOptions.BOTTOM_RIGHT: QRect(r.right() - offset, r.bottom() - offset, size, size),
        }

    def get_handle_at(self, pos):
        for handle, rect in self.get_handle_rects().items():
            if rect.contains(pos): return handle
        return None

    def update_cursor_shape(self, pos):
        if self.is_selecting or self.selection_rect.isNull():
            self.setCursor(Qt.CursorShape.CrossCursor)
            return

        handle = self.get_handle_at(pos)
        
        if handle:
            if handle in (HandleOptions.TOP_LEFT, HandleOptions.BOTTOM_RIGHT): 
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif handle in (HandleOptions.TOP_RIGHT, HandleOptions.BOTTOM_LEFT): 
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif handle in (HandleOptions.TOP_MIDDLE, HandleOptions.BOTTOM_MIDDLE): 
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif handle in (HandleOptions.MIDDLE_LEFT, HandleOptions.MIDDLE_RIGHT): 
                self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self.selection_rect.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def resize_selection(self, pos):
        r = self.selection_rect
        if self.active_handle == HandleOptions.TOP_LEFT: r.setTopLeft(pos)
        elif self.active_handle == HandleOptions.TOP_MIDDLE: r.setTop(pos.y())
        elif self.active_handle == HandleOptions.TOP_RIGHT: r.setTopRight(pos)
        elif self.active_handle == HandleOptions.MIDDLE_LEFT: r.setLeft(pos.x())
        elif self.active_handle == HandleOptions.MIDDLE_RIGHT: r.setRight(pos.x())
        elif self.active_handle == HandleOptions.BOTTOM_LEFT: r.setBottomLeft(pos)
        elif self.active_handle == HandleOptions.BOTTOM_MIDDLE: r.setBottom(pos.y())
        elif self.active_handle == HandleOptions.BOTTOM_RIGHT: r.setBottomRight(pos)
        self.selection_rect = r.normalized()

    def update_toolbar_position(self):
        if self.selection_rect.isNull(): return
        toolbar_width = 70
        toolbar_x = self.selection_rect.right() - toolbar_width
        toolbar_y = self.selection_rect.bottom() + 10
        if toolbar_y + 30 > self.height():
            toolbar_y = self.selection_rect.bottom() - 40
        self.cancel_button.move(toolbar_x, toolbar_y)
        self.confirm_button.move(toolbar_x + 35, toolbar_y)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = OCRRegionCalibrator(app)
    window.show()
    sys.exit(app.exec())