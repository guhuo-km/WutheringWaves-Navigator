# -*- coding: utf-8 -*-
"""
快捷键配置界面 - 内嵌式设计，支持键盘和鼠标快捷键
"""

from typing import Optional, Dict
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout

from qfluentwidgets import (
    ScrollArea, CardWidget, PushButton, PrimaryPushButton,
    BodyLabel, StrongBodyLabel, CaptionLabel, TransparentToolButton,
    FluentIcon as FIF, InfoBar, InfoBarPosition
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

from ui.components.hotkey_display_widget import HotkeyDisplayWidget


class HotkeyInterface(ScrollArea):
    """快捷键配置界面 - 内嵌式设计"""

    hotkeys_changed = Signal(dict)  # 快捷键配置改变信号

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.setObjectName("hotkeyInterface")

        # Set transparent background for consistent appearance
        self.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._scroll_widget = QWidget()
        self._layout = QVBoxLayout(self._scroll_widget)
        self._layout.setContentsMargins(36, 24, 36, 24)
        self._layout.setSpacing(20)

        self.setWidget(self._scroll_widget)
        self.setWidgetResizable(True)

        self._hotkey_edits: Dict[str, HotkeyDisplayWidget] = {}
        self._current_hotkeys: Dict[str, str] = {}
        self._hotkey_action_labels: Dict[str, BodyLabel] = {}
        self._hotkey_clear_buttons: Dict[str, TransparentToolButton] = {}

        self._init_info_card()
        self._init_config_card()
        self._init_actions_card()

        self._layout.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_hotkey_list_height()

    def _update_hotkey_list_height(self):
        """Keep the hotkey list within the visible page and scroll internally."""
        if not hasattr(self, "_hotkey_list_scroll"):
            return

        viewport_height = self.viewport().height()
        used_height = (
            self._layout.contentsMargins().top()
            + self._layout.contentsMargins().bottom()
            + self.info_card.sizeHint().height()
            + self.actions_card.sizeHint().height()
            + self._config_title.sizeHint().height()
            + self._layout.spacing() * 3
        )
        available_height = max(180, viewport_height - used_height)
        self._hotkey_list_scroll.setMaximumHeight(available_height)

    def _init_info_card(self):
        """初始化说明卡片"""
        self.info_card = CardWidget(self)
        card_layout = QVBoxLayout(self.info_card)

        self.info_title_label = StrongBodyLabel()
        card_layout.addWidget(self.info_title_label)

        self.info_desc_label = BodyLabel()
        self.info_desc_label.setWordWrap(True)
        card_layout.addWidget(self.info_desc_label)

        self._layout.addWidget(self.info_card)

    def _init_config_card(self):
        """初始化配置卡片 - iOS 风格嵌入式分组列表"""
        self._config_title = StrongBodyLabel()
        self._layout.addWidget(self._config_title)

        # 创建一个大卡片包含所有条目
        self.main_card = CardWidget(self)
        main_card_layout = QVBoxLayout(self.main_card)
        main_card_layout.setContentsMargins(0, 0, 0, 0)
        main_card_layout.setSpacing(0)
        self._separators = []

        self._hotkey_list_scroll = ScrollArea(self.main_card)
        self._hotkey_list_scroll.setWidgetResizable(True)
        self._hotkey_list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._hotkey_list_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._hotkey_list_widget = QWidget()
        self._hotkey_list_layout = QVBoxLayout(self._hotkey_list_widget)
        self._hotkey_list_layout.setContentsMargins(0, 0, 0, 0)
        self._hotkey_list_layout.setSpacing(0)
        self._hotkey_list_scroll.setWidget(self._hotkey_list_widget)

        hotkey_actions = [
            ("toggle_ocr", "hotkey_action_toggle_ocr", "切换OCR识别"),
            ("toggle_recording", "hotkey_action_toggle_recording", "切换路线录制"),
            ("mark_next", "hotkey_action_mark_next", "标记下一点"),
            ("undo", "hotkey_action_undo", "取消最近点标记"),
            ("open_nearest", "hotkey_action_open_nearest", "打开最近未完成"),
            ("close_popup", "hotkey_action_close_popup", "关闭弹窗"),
            ("zoom_in", "hotkey_action_zoom_in", "地图放大一级"),
            ("zoom_out", "hotkey_action_zoom_out", "地图缩小一级"),
            ("prev_route", "hotkey_action_prev_route", "上一条路线"),
            ("next_route", "hotkey_action_next_route", "下一条路线"),
        ]

        self._hotkey_actions = hotkey_actions
        for idx, (action_id, action_key, action_default) in enumerate(hotkey_actions):
            # 创建每一行的容器
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(20, 12, 20, 12)
            row_layout.setSpacing(12)

            # 标签（固定宽度）
            name_label = BodyLabel()
            name_label.setFixedWidth(120)
            self._hotkey_action_labels[action_id] = name_label
            row_layout.addWidget(name_label)

            # 快捷键输入框（拉伸）
            hotkey_edit = HotkeyDisplayWidget()
            hotkey_edit.hotkey_changed.connect(lambda _, aid=action_id: self._on_hotkey_changed(aid))
            self._hotkey_edits[action_id] = hotkey_edit
            row_layout.addWidget(hotkey_edit, 1)

            # 删除按钮
            clear_btn = TransparentToolButton(FIF.DELETE, self)
            clear_btn.setFixedSize(34, 34)
            clear_btn.clicked.connect(lambda _, edit=hotkey_edit: self._clear_hotkey(edit))
            self._hotkey_clear_buttons[action_id] = clear_btn
            row_layout.addWidget(clear_btn)

            self._hotkey_list_layout.addWidget(row_widget)

            # 添加分隔线（最后一项不加）
            if idx < len(hotkey_actions) - 1:
                separator = QWidget()
                separator.setFixedHeight(1)
                separator.setStyleSheet("background-color: #E0E0E0;")
                self._hotkey_list_layout.addWidget(separator)
                self._separators.append(separator)

        main_card_layout.addWidget(self._hotkey_list_scroll)
        self._layout.addWidget(self.main_card)

    def _init_actions_card(self):
        """初始化操作按钮卡片"""
        self.actions_card = CardWidget(self)
        card_layout = QVBoxLayout(self.actions_card)

        btn_row = QHBoxLayout()

        # 恢复默认按钮
        self.reset_btn = PushButton(FIF.SYNC, "")
        self.reset_btn.clicked.connect(self._reset_to_default)
        btn_row.addWidget(self.reset_btn)

        btn_row.addStretch()

        # 应用按钮
        self.apply_btn = PrimaryPushButton(FIF.ACCEPT, "")
        self.apply_btn.clicked.connect(self._apply_settings)
        btn_row.addWidget(self.apply_btn)

        card_layout.addLayout(btn_row)
        self._layout.addWidget(self.actions_card)
        self.retranslate_ui()

    def _on_hotkey_changed(self, action_id: str):
        """快捷键改变时的处理"""
        # 不做任何处理，等待用户点击"应用设置"
        pass

    def _clear_hotkey(self, edit: HotkeyDisplayWidget):
        """清空快捷键"""
        edit.setText("")
        edit.hotkey_changed.emit("")

    def _reset_to_default(self):
        """恢复默认（清空所有快捷键）"""
        for edit in self._hotkey_edits.values():
            edit.setText("")
            edit.hotkey_changed.emit("")

        InfoBar.success(
            tr("hotkey_reset_success_title", "恢复默认"),
            tr("hotkey_reset_success_message", "已清空所有快捷键设置"),
            parent=self,
            position=InfoBarPosition.TOP
        )

    def _apply_settings(self):
        """应用设置"""
        new_hotkeys = {}

        # 收集所有快捷键
        for action_id, edit in self._hotkey_edits.items():
            hotkey_str = edit.text().strip()
            new_hotkeys[action_id] = hotkey_str

        # 检查冲突（忽略空值）
        non_empty_values = [v for v in new_hotkeys.values() if v]
        if len(non_empty_values) != len(set(non_empty_values)):
            InfoBar.error(
                tr("hotkey_apply_error_title", "设置失败"),
                tr("hotkey_duplicate_error_message", "存在重复的快捷键，请修改后重试"),
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 保存并发射信号
        self._current_hotkeys = new_hotkeys.copy()
        self.hotkeys_changed.emit(new_hotkeys)

        InfoBar.success(
            tr("hotkey_apply_success_title", "设置成功"),
            tr("hotkey_apply_success_message", "快捷键配置已保存并应用"),
            parent=self,
            position=InfoBarPosition.TOP
        )

    def load_hotkeys(self, hotkeys: Dict[str, str]):
        """加载快捷键配置"""
        self._current_hotkeys = hotkeys.copy()

        for action_id, hotkey_str in hotkeys.items():
            if action_id in self._hotkey_edits:
                edit = self._hotkey_edits[action_id]
                # 转换为显示格式（首字母大写）
                if hotkey_str:
                    display_str = self._to_display_format(hotkey_str)
                    edit.setText(display_str)
                else:
                    edit.setText("")

    def get_current_hotkeys(self) -> Dict[str, str]:
        """获取当前快捷键配置（适用于 keyboard 库的格式）"""
        hotkeys = {}
        for action_id, edit in self._hotkey_edits.items():
            hotkey_str = edit.text().strip()
            if hotkey_str:
                # 转换为 keyboard 库格式（小写）
                keyboard_format = self._to_keyboard_format(hotkey_str)
                hotkeys[action_id] = keyboard_format
            else:
                hotkeys[action_id] = ""
        return hotkeys

    def _to_display_format(self, hotkey_str: str) -> str:
        """
        转换为显示格式
        keyboard 库格式: ctrl+f1 -> 显示格式: Ctrl+F1
        """
        parts = hotkey_str.split("+")
        display_parts = []

        for part in parts:
            part_lower = part.lower()
            if part_lower == "ctrl":
                display_parts.append("Ctrl")
            elif part_lower == "alt":
                display_parts.append("Alt")
            elif part_lower == "shift":
                display_parts.append("Shift")
            elif part_lower == "middle":
                display_parts.append("Middle")
            elif part_lower in ("x1", "back"):
                # 兼容旧配置 back -> X1（显示层图标会按资源语义对调）
                display_parts.append("X1")
            elif part_lower in ("x2", "forward"):
                # 兼容旧配置 forward -> X2（显示层图标会按资源语义对调）
                display_parts.append("X2")
            else:
                display_parts.append(part.upper())

        return "+".join(display_parts)

    def _to_keyboard_format(self, hotkey_str: str) -> str:
        """
        转换为 keyboard 库格式
        显示格式: Ctrl+F1 -> keyboard 库格式: ctrl+f1
        """
        # 简单转换为小写
        return hotkey_str.lower()

    # 保持向后兼容的方法
    def update_hotkey_display(self, hotkeys: Dict[str, str]):
        """更新快捷键显示（向后兼容）"""
        self.load_hotkeys(hotkeys)

    def get_hotkey_display(self, action_id: str) -> Optional[str]:
        """获取快捷键显示文本（向后兼容）"""
        if action_id in self._hotkey_edits:
            return self._hotkey_edits[action_id].text()
        return None

    def update_theme(self):
        """更新主题样式"""
        from core.theme_manager import ThemeManager

        # 更新所有 CardWidget 的样式
        card_style = ThemeManager.get_card_widget_style()
        self._scroll_widget.setStyleSheet(ThemeManager.get_page_background_style())
        self.info_card.setStyleSheet(card_style)
        self.main_card.setStyleSheet(card_style)
        self.actions_card.setStyleSheet(card_style)

        # 更新所有快捷键输入框的主题
        for edit in self._hotkey_edits.values():
            edit.update_theme()

        # 更新分隔线颜色
        separator_color = ThemeManager.get_separator_color()
        for separator in self._separators:
            separator.setStyleSheet(f"background-color: {separator_color};")

    def retranslate_ui(self):
        self.info_title_label.setText(tr("hotkey_config_title", "全局快捷键配置"))
        self.info_desc_label.setText(
            tr(
                "hotkey_config_desc",
                "支持键盘按键（F1-F12、字母、数字等）和鼠标按键（中键、侧键等）\n"
                "点击输入框后按下快捷键，可组合 Ctrl/Alt/Shift 修饰键\n"
                "按 ESC 清空快捷键",
            )
        )
        self._config_title.setText(tr("hotkey_settings_title", "快捷键设置"))

        for action_id, action_key, action_default in self._hotkey_actions:
            text = tr(action_key, action_default)
            self._hotkey_action_labels[action_id].setText(text)
            self._hotkey_action_labels[action_id].setToolTip(text)
            self._hotkey_edits[action_id].setToolTip(text)
            self._hotkey_clear_buttons[action_id].setToolTip(
                tr("hotkey_clear", "清空")
            )

        self.reset_btn.setText(tr("hotkey_reset_default", "恢复默认"))
        self.reset_btn.setToolTip(tr("hotkey_reset_default_tooltip", "清空所有快捷键设置"))
        self.apply_btn.setText(tr("hotkey_apply_settings", "应用设置"))
