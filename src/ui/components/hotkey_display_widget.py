# -*- coding: utf-8 -*-
"""
快捷键显示组件 - 支持文字和图标混合显示
"""

import os
from PySide6.QtCore import Qt, Signal, QSize, QRectF
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QColor
from PySide6.QtSvgWidgets import QSvgWidget


class HotkeyDisplayWidget(QWidget):
    """
    快捷键显示组件
    支持文字和图标混合显示（修饰键用文字，鼠标按键用图标）
    """

    hotkey_changed = Signal(str)  # 快捷键改变信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName("hotkeyDisplay")
        self.recording = False
        self._hovered = False
        self.pressed_keys = set()
        self.current_modifiers = Qt.NoModifier
        self.current_hotkey = ""

        self.setMinimumHeight(28)

        # 鼠标按键图标映射
        self.mouse_icons = {
            "Middle": "mouse_middle.svg",
            # 资源图中 X1/X2 的上下语义与 Qt 命名相反，这里做显示层对调
            "X1": "mouse_x2.svg",
            "X2": "mouse_x1.svg",
        }

        # 设置布局
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(6, 4, 6, 4)
        self.layout.setSpacing(4)

        # 占位符标签
        self.placeholder_label = QLabel("点击后按下快捷键...")
        self.placeholder_label.setStyleSheet("color: #999; font-size: 13px;")
        self.layout.addWidget(self.placeholder_label)
        self.layout.addStretch()

        # 初始化颜色（将在 update_theme 中更新）
        self._radius = 5
        self._border_width = 1
        self.update_theme()

    def update_theme(self):
        """更新主题颜色"""
        from core.theme_manager import ThemeManager
        colors = ThemeManager.get_hotkey_input_colors()

        self._border_normal = QColor(colors["border_normal"])
        self._border_hover = QColor(colors["border_hover"])
        self._border_focus = QColor(colors["border_focus"])
        self._bg_normal = QColor(colors["bg_normal"])
        self._bg_hover = QColor(colors["bg_hover"])
        self._bg_focus = QColor(colors["bg_focus"])
        self._text_normal = colors["text_normal"]
        self._text_focus = colors["text_focus"]
        self._placeholder_color = colors["placeholder"]

        # 重新渲染
        self._render_hotkey(self.current_hotkey)
        self.update()

    def setText(self, hotkey_str: str):
        """设置快捷键文本并渲染"""
        self.current_hotkey = hotkey_str
        self._render_hotkey(hotkey_str)

    def text(self) -> str:
        """获取当前快捷键文本"""
        return self.current_hotkey

    def _render_hotkey(self, hotkey_str: str):
        """渲染快捷键（文字+图标混合）"""
        # 清空现有内容
        while self.layout.count() > 0:
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 根据是否聚焦决定文字颜色
        text_color = self._text_focus if self.recording else self._text_normal
        placeholder_color = self._text_focus if self.recording else self._placeholder_color

        if not hotkey_str:
            # 显示占位符
            self.placeholder_label = QLabel("点击后按下快捷键..." if not self.recording else "按下快捷键或鼠标按键...")
            self.placeholder_label.setStyleSheet(f"color: {placeholder_color}; font-size: 13px;")
            self.layout.addWidget(self.placeholder_label)
            self.layout.addStretch()
            return

        # 解析快捷键字符串
        parts = hotkey_str.split("+")

        for i, part in enumerate(parts):
            # 兼容旧值 Back/Forward，统一映射为可显示 SVG 的 X1/X2
            part_lower = part.lower()
            if part_lower == "back":
                part = "X1"
            elif part_lower == "forward":
                part = "X2"

            # 检查是否是鼠标按键
            if part in self.mouse_icons:
                # 显示图标（使用 QSvgWidget 保持清晰）
                icon_widget = self._create_icon_widget(part)
                if icon_widget:
                    self.layout.addWidget(icon_widget)
            else:
                # 显示文字 - 聚焦时也要变蓝！
                text_label = QLabel(part)
                text_label.setStyleSheet(f"color: {text_color}; font-weight: bold; font-size: 14px;")
                self.layout.addWidget(text_label)

            # 添加 "+" 分隔符（除了最后一个）
            if i < len(parts) - 1:
                plus_label = QLabel("+")
                plus_label.setStyleSheet(f"color: {text_color}; font-size: 14px; padding: 0 2px;")
                self.layout.addWidget(plus_label)

        self.layout.addStretch()

    def _create_icon_widget(self, mouse_name: str) -> QSvgWidget:
        """创建 SVG 图标控件（使用 QSvgWidget 保持矢量清晰）"""
        icon_file = self.mouse_icons.get(mouse_name)
        if not icon_file:
            return None

        # 获取图标路径（根据主题优先加载 _light 版本）
        icon_path = self._resolve_mouse_icon_path(icon_file)

        if not os.path.exists(icon_path):
            print(f"图标文件不存在: {icon_path}")
            return None

        # 创建 QSvgWidget（矢量渲染，不会模糊）
        svg_widget = QSvgWidget(icon_path)
        svg_widget.setFixedSize(20, 20)  # 设置合适的大小
        svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        svg_widget.setAutoFillBackground(False)
        svg_widget.setStyleSheet("background: transparent;")

        return svg_widget

    def _resolve_mouse_icon_path(self, icon_file: str) -> str:
        """根据主题解析鼠标图标路径，深色主题优先加载 _light.svg。"""
        from core.theme_manager import ThemeManager
        from core.utils import get_assets_path

        base_name, ext = os.path.splitext(icon_file)
        if ThemeManager.is_dark_theme():
            dark_variant = get_assets_path(os.path.join("icons", f"{base_name}_light{ext}"))
            if os.path.exists(dark_variant):
                return dark_variant

        return get_assets_path(os.path.join("icons", icon_file))

    def focusInEvent(self, event):
        """获得焦点时开始录制"""
        super().focusInEvent(event)
        self.recording = True
        self.pressed_keys.clear()
        self.current_modifiers = Qt.NoModifier

        # 重新渲染以更新文字颜色（包括已有的快捷键）
        self._render_hotkey(self.current_hotkey if self.current_hotkey else "")
        self.update()

    def focusOutEvent(self, event):
        """失去焦点时停止录制"""
        super().focusOutEvent(event)
        self.recording = False

        # 恢复显示
        self._render_hotkey(self.current_hotkey)
        self.update()

    def enterEvent(self, event):
        """鼠标悬停时刷新边框颜色"""
        super().enterEvent(event)
        self._hovered = True
        if not self.recording:
            self.update()

    def leaveEvent(self, event):
        """鼠标离开时刷新边框颜色"""
        super().leaveEvent(event)
        self._hovered = False
        if not self.recording:
            self.update()

    def paintEvent(self, event):
        """自绘边框，确保视觉上可见"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self.recording:
            border_color = self._border_focus
            bg_color = self._bg_focus
        elif self._hovered:
            border_color = self._border_hover
            bg_color = self._bg_hover
        else:
            border_color = self._border_normal
            bg_color = self._bg_normal

        rect = QRectF(
            self._border_width / 2,
            self._border_width / 2,
            self.width() - self._border_width,
            self.height() - self._border_width
        )
        painter.setPen(QPen(border_color, self._border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, self._radius, self._radius)

    def keyPressEvent(self, event):
        """键盘按下事件"""
        if not self.recording:
            return

        key = event.key()
        modifiers = event.modifiers()

        # ESC 清空快捷键
        if key == Qt.Key_Escape:
            self.setText("")
            self.hotkey_changed.emit("")
            return

        # 忽略单独的修饰键
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            self.current_modifiers = modifiers
            return

        # 构建快捷键字符串
        hotkey_str = self._build_hotkey_string(
            modifiers,
            key_name=self._get_key_name(key, event.text(), modifiers),
        )
        if hotkey_str:
            self.setText(hotkey_str)
            self.hotkey_changed.emit(hotkey_str)

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件 - 捕捉鼠标按键"""
        if not self.recording:
            super().mousePressEvent(event)
            return

        button = event.button()

        # 忽略左键和右键（用于其他UI交互）
        if button in (Qt.LeftButton, Qt.RightButton):
            super().mousePressEvent(event)
            return

        # 获取鼠标按键名称
        mouse_name = self._get_mouse_button_name(button)
        if not mouse_name:
            return

        # 构建快捷键字符串（使用当前修饰键状态）
        hotkey_str = self._build_hotkey_string(self.current_modifiers, mouse_name=mouse_name)
        if hotkey_str:
            self.setText(hotkey_str)
            self.hotkey_changed.emit(hotkey_str)

        event.accept()

    def _build_hotkey_string(self, modifiers, key_name=None, mouse_name=None):
        """构建快捷键字符串"""
        parts = []

        # 添加修饰键
        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")

        # 添加主键或鼠标按键
        if key_name:
            parts.append(key_name)
        elif mouse_name:
            parts.append(mouse_name)

        if parts:
            return "+".join(parts)
        return ""

    def _get_key_name(self, key, text="", modifiers=Qt.NoModifier):
        """获取键盘按键名称"""
        if modifiers & Qt.KeypadModifier and Qt.Key_0 <= key <= Qt.Key_9:
            digit = key - Qt.Key_0
            return f"Num{digit}"

        # 功能键
        key_map = {
            Qt.Key_F1: "F1", Qt.Key_F2: "F2", Qt.Key_F3: "F3", Qt.Key_F4: "F4",
            Qt.Key_F5: "F5", Qt.Key_F6: "F6", Qt.Key_F7: "F7", Qt.Key_F8: "F8",
            Qt.Key_F9: "F9", Qt.Key_F10: "F10", Qt.Key_F11: "F11", Qt.Key_F12: "F12",
            Qt.Key_Space: "Space", Qt.Key_Return: "Enter", Qt.Key_Escape: "Esc",
            Qt.Key_Tab: "Tab", Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete",
            Qt.Key_Insert: "Insert", Qt.Key_Home: "Home", Qt.Key_End: "End",
            Qt.Key_PageUp: "PageUp", Qt.Key_PageDown: "PageDown",
            Qt.Key_Up: "Up", Qt.Key_Down: "Down", Qt.Key_Left: "Left", Qt.Key_Right: "Right"
        }

        if key in key_map:
            return key_map[key]

        # 普通字符键
        if text and text.isprintable():
            return text.upper()

        return ""

    def _get_mouse_button_name(self, button):
        """获取鼠标按键名称"""
        mouse_map = {
            Qt.MiddleButton: "Middle",       # 中键
            Qt.XButton1: "X1",               # 侧键1（后退）
            Qt.XButton2: "X2",               # 侧键2（前进）
            Qt.BackButton: "X1",             # 后退键（统一为 X1）
            Qt.ForwardButton: "X2",          # 前进键（统一为 X2）
        }
        return mouse_map.get(button, "")

    def get_hotkey_for_keyboard_library(self):
        """
        获取适用于 keyboard 库的快捷键字符串格式
        将显示格式（Ctrl+F1）转换为 keyboard 库格式（ctrl+f1）
        """
        hotkey_str = self.text().strip()
        if not hotkey_str:
            return ""

        # 转换为小写
        hotkey_str = hotkey_str.lower()

        # keyboard 库不支持鼠标按键，如果包含鼠标按键则返回空
        mouse_buttons = ["middle", "x1", "x2", "back", "forward"]
        for mouse_btn in mouse_buttons:
            if mouse_btn in hotkey_str:
                return ""  # 鼠标快捷键由其他方式处理

        return hotkey_str
