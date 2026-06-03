# -*- coding: utf-8 -*-
"""
主题管理器 - 管理应用的浅色/深色主题
"""

from qfluentwidgets import isDarkTheme


class ThemeManager:
    """主题管理器 - 提供主题相关的颜色和样式"""

    @staticmethod
    def is_dark_theme() -> bool:
        """判断当前是否为深色主题"""
        return isDarkTheme()

    @staticmethod
    def get_color(light_color: str, dark_color: str) -> str:
        """根据当前主题返回对应颜色"""
        return dark_color if ThemeManager.is_dark_theme() else light_color

    @staticmethod
    def get_hotkey_input_style() -> str:
        """获取快捷键输入框样式"""
        if ThemeManager.is_dark_theme():
            return """
                HotkeyDisplayWidget {
                    background-color: #2D2D2D;
                    border: 2px solid #3F3F3F;
                    border-radius: 6px;
                    min-height: 36px;
                }
                HotkeyDisplayWidget:hover {
                    border: 2px solid #5A5A5A;
                    background-color: #333333;
                }
            """
        else:
            return """
                HotkeyDisplayWidget {
                    background-color: #FFFFFF;
                    border: 2px solid #D0D0D0;
                    border-radius: 6px;
                    min-height: 36px;
                }
                HotkeyDisplayWidget:hover {
                    border: 2px solid #A0A0A0;
                    background-color: #FAFAFA;
                }
            """

    @staticmethod
    def get_hotkey_input_focus_style() -> str:
        """获取快捷键输入框聚焦样式"""
        if ThemeManager.is_dark_theme():
            return """
                HotkeyDisplayWidget {
                    background-color: #1A2332;
                    border: 2px solid #0078D7;
                    border-radius: 6px;
                    min-height: 36px;
                }
            """
        else:
            return """
                HotkeyDisplayWidget {
                    background-color: #F0F8FF;
                    border: 2px solid #0078D7;
                    border-radius: 6px;
                    min-height: 36px;
                }
            """

    @staticmethod
    def get_hotkey_input_colors() -> dict:
        """获取快捷键输入框的颜色配置"""
        if ThemeManager.is_dark_theme():
            return {
                "border_normal": "#3F3F3F",
                "border_hover": "#5A5A5A",
                "border_focus": "#0078D7",
                "bg_normal": "#2D2D2D",
                "bg_hover": "#333333",
                "bg_focus": "#1A2332",
                "text_normal": "#FFFFFF",
                "text_focus": "#4FC3F7",
                "placeholder": "#888888"
            }
        else:
            return {
                "border_normal": "#D0D0D0",
                "border_hover": "#A0A0A0",
                "border_focus": "#0078D7",
                "bg_normal": "#FFFFFF",
                "bg_hover": "#FAFAFA",
                "bg_focus": "#F0F8FF",
                "text_normal": "#000000",
                "text_focus": "#0078D7",
                "placeholder": "#999999"
            }

    @staticmethod
    def get_route_table_style() -> str:
        """获取路线列表表格样式"""
        if ThemeManager.is_dark_theme():
            return """
                QTableWidget {
                    background-color: #2D2D2D;
                    border: 1px solid #3F3F3F;
                    border-radius: 8px;
                    gridline-color: #3F3F3F;
                    color: #FFFFFF;
                }
                QTableWidget::viewport {
                    background-color: #2D2D2D;
                }
                QHeaderView {
                    background-color: #252525;
                }
                QTableWidget::item {
                    padding: 8px;
                    border: none;
                    color: #FFFFFF;
                }
                QTableWidget::item:selected {
                    background-color: #1A237E;
                    color: #4FC3F7;
                }
                QHeaderView::section {
                    background-color: #252525;
                    padding: 8px;
                    border: none;
                    border-bottom: 1px solid #3F3F3F;
                    font-weight: bold;
                    color: #AAAAAA;
                }
                QTableWidget::item:alternate {
                    background-color: #2A2A2A;
                }
                QTableWidget QTableCornerButton::section {
                    background-color: #252525;
                    border: none;
                }
                QTableWidget QHeaderView::section:vertical {
                    background-color: #252525;
                    border: none;
                    border-right: 1px solid #3F3F3F;
                    color: #AAAAAA;
                }
            """
        else:
            return """
                QTableWidget {
                    background-color: white;
                    border: 1px solid #E5E5E5;
                    border-radius: 8px;
                    gridline-color: #F0F0F0;
                }
                QTableWidget::viewport {
                    background-color: white;
                }
                QHeaderView {
                    background-color: #F8F9FA;
                }
                QTableWidget::item {
                    padding: 8px;
                    border: none;
                }
                QTableWidget::item:selected {
                    background-color: #E3F2FD;
                    color: #1976D2;
                }
                QHeaderView::section {
                    background-color: #F8F9FA;
                    padding: 8px;
                    border: none;
                    border-bottom: 1px solid #E5E5E5;
                    font-weight: bold;
                    color: #666;
                }
                QTableWidget::item:alternate {
                    background-color: #FAFAFA;
                }
                QTableWidget QTableCornerButton::section {
                    background-color: #F8F9FA;
                    border: none;
                }
                QTableWidget QHeaderView::section:vertical {
                    background-color: #F8F9FA;
                    border: none;
                    border-right: 1px solid #E5E5E5;
                    color: #666;
                }
            """

    @staticmethod
    def get_list_widget_style() -> str:
        """获取列表控件样式"""
        if ThemeManager.is_dark_theme():
            return """
                QListWidget {
                    background-color: #2D2D2D;
                    border: 1px solid #3F3F3F;
                    border-radius: 4px;
                    color: #FFFFFF;
                }
                QListWidget::item {
                    padding: 5px;
                    color: #FFFFFF;
                }
                QListWidget::item:selected {
                    background-color: #1A237E;
                    color: #4FC3F7;
                }
                QListWidget::item:hover {
                    background-color: #3A3A3A;
                }
            """
        else:
            return """
                QListWidget {
                    background-color: white;
                    border: 1px solid #E5E5E5;
                    border-radius: 4px;
                    color: #000000;
                }
                QListWidget::item {
                    padding: 5px;
                }
                QListWidget::item:selected {
                    background-color: #E3F2FD;
                    color: #1976D2;
                }
                QListWidget::item:hover {
                    background-color: #F5F5F5;
                }
            """

    @staticmethod
    def get_text_edit_style() -> str:
        """获取文本编辑框样式（用于日志）"""
        if ThemeManager.is_dark_theme():
            return """
                QTextEdit {
                    background-color: #1E1E1E;
                    border: 1px solid #3F3F3F;
                    border-radius: 4px;
                    color: #FFFFFF;
                }
            """
        else:
            return """
                QTextEdit {
                    background-color: #FFFFFF;
                    border: 1px solid #E5E5E5;
                    border-radius: 4px;
                    color: #000000;
                }
            """

    @staticmethod
    def get_svg_icon_style() -> str:
        """获取 SVG 图标样式（深色模式下反转颜色）"""
        if ThemeManager.is_dark_theme():
            return "filter: invert(1);"
        else:
            return ""

    @staticmethod
    def get_card_widget_style() -> str:
        """获取 CardWidget 样式（适配深色主题）"""
        if ThemeManager.is_dark_theme():
            return """
                CardWidget {
                    background-color: #2D2D2D;
                    border: 1px solid #3F3F3F;
                    border-radius: 8px;
                }
                CardWidget QLabel {
                    background-color: transparent;
                }
            """
        else:
            return """
                CardWidget {
                    background-color: #FFFFFF;
                    border: 1px solid #E5E5E5;
                    border-radius: 8px;
                }
                CardWidget QLabel {
                    background-color: transparent;
                }
            """

    @staticmethod
    def get_check_box_style() -> str:
        """获取 CheckBox 样式，避免局部样式覆盖 Fluent 主题文字色。"""
        if ThemeManager.is_dark_theme():
            return """
                CheckBox {
                    background-color: transparent;
                    color: #EDEDED;
                    spacing: 8px;
                    min-width: 28px;
                    min-height: 22px;
                    outline: none;
                    margin-left: 1px;
                }
                CheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border-radius: 5px;
                    border: 1px solid transparent;
                    background-color: transparent;
                }
                CheckBox:disabled {
                    color: rgba(255, 255, 255, 0.36);
                }
            """
        return """
            CheckBox {
                background-color: transparent;
                color: #1F1F1F;
                spacing: 8px;
                min-width: 28px;
                min-height: 22px;
                outline: none;
                margin-left: 1px;
            }
            CheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid transparent;
                background-color: transparent;
            }
            CheckBox:disabled {
                color: rgba(0, 0, 0, 0.36);
            }
        """

    @staticmethod
    def get_page_background_style() -> str:
        """获取页面背景样式（用于 ScrollArea 内容区域）"""
        if ThemeManager.is_dark_theme():
            return (
                "background-color: #1E1E1E;"
                "QLabel { background-color: transparent; color: #EDEDED; }"
            )
        return "background-color: transparent; QLabel { background-color: transparent; }"

    @staticmethod
    def get_separator_color() -> str:
        """获取分隔线颜色"""
        return "#3F3F3F" if ThemeManager.is_dark_theme() else "#E0E0E0"

