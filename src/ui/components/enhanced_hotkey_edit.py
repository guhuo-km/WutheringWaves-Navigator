# -*- coding: utf-8 -*-
"""
增强的快捷键输入框 - 支持键盘和鼠标按键
"""

import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QIcon, QAction
from qfluentwidgets import LineEdit


class EnhancedHotkeyEdit(LineEdit):
    """
    增强的快捷键录制输入框
    支持键盘按键和鼠标按键（侧键、中键等）
    """

    hotkey_changed = Signal(str)  # 快捷键改变信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按下快捷键...")
        self.recording = False
        self.pressed_keys = set()
        self.current_modifiers = Qt.NoModifier

        # 鼠标按键图标映射
        self.mouse_icons = {
            "Middle": "mouse_middle.svg",
            "X1": "mouse_x1.svg",
            "X2": "mouse_x2.svg",
        }

        # 创建图标动作（初始隐藏）
        self.icon_action = QAction(self)
        self.addAction(self.icon_action, LineEdit.ActionPosition.LeadingPosition)
        self.icon_action.setVisible(False)

    def focusInEvent(self, event):
        """获得焦点时开始录制"""
        super().focusInEvent(event)
        self.recording = True
        self.pressed_keys.clear()
        self.current_modifiers = Qt.NoModifier
        self.setPlaceholderText("按下快捷键或鼠标按键...")
        self.setStyleSheet("EnhancedHotkeyEdit { border: 2px solid #0078D7; }")

    def focusOutEvent(self, event):
        """失去焦点时停止录制"""
        super().focusOutEvent(event)
        self.recording = False
        self.setPlaceholderText("点击后按下快捷键...")
        self.setStyleSheet("")

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
            self._update_icon("")
            return

        # 忽略单独的修饰键
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            self.current_modifiers = modifiers
            return

        # 构建快捷键字符串
        hotkey_str = self._build_hotkey_string(modifiers, key_name=self._get_key_name(key, event.text()))
        if hotkey_str:
            self.setText(hotkey_str)
            self.hotkey_changed.emit(hotkey_str)
            self._update_icon(hotkey_str)

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
            self._update_icon(hotkey_str)

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

    def _get_key_name(self, key, text=""):
        """获取键盘按键名称"""
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
            Qt.BackButton: "Back",           # 后退键
            Qt.ForwardButton: "Forward",     # 前进键
        }
        return mouse_map.get(button, "")

    def _update_icon(self, hotkey_str: str):
        """根据快捷键字符串更新图标显示"""
        # 检测是否包含鼠标按键
        icon_file = None
        for mouse_name, icon_filename in self.mouse_icons.items():
            if mouse_name in hotkey_str:
                icon_file = icon_filename
                break

        if icon_file:
            # 获取图标路径（根据主题优先加载 _light 版本）
            icon_path = self._resolve_mouse_icon_path(icon_file)

            if os.path.exists(icon_path):
                self.icon_action.setIcon(QIcon(icon_path))
                self.icon_action.setVisible(True)
            else:
                print(f"图标文件不存在: {icon_path}")
                self.icon_action.setVisible(False)
        else:
            # 没有鼠标按键，隐藏图标
            self.icon_action.setVisible(False)

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
