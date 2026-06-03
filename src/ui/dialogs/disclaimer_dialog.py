# -*- coding: utf-8 -*-
"""
免责声明对话框
从 main_app_legacy.py 提取
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser
from PySide6.QtCore import Qt
from qfluentwidgets import BodyLabel, PushButton, PrimaryPushButton, isDarkTheme


class DisclaimerDialog(QDialog):
    """首次使用免责声明对话框"""

    @staticmethod
    def _theme_colors():
        if isDarkTheme():
            return {
                "title": "#F2F3F5",
                "text": "#E6E8EC",
                "muted": "#A8AFBA",
                "window": "#111827",
                "panel": "#20242B",
                "border": "#3A404A",
                "button_bg": "#2B313A",
                "button_bg_hover": "#343B46",
                "button_text": "#F2F3F5",
            }
        return {
            "title": "#1F2937",
            "text": "#243244",
            "muted": "#64748B",
            "window": "#F6F7F9",
            "panel": "#FFFFFF",
            "border": "#E5E7EB",
            "button_bg": "#FFFFFF",
            "button_bg_hover": "#F2F4F7",
            "button_text": "#1F2937",
        }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("呜呜大地图 - 使用条款")
        self.setFixedSize(600, 500)
        self.setModal(True)
        
        # 设置窗口图标和样式
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        colors = self._theme_colors()
        self.setStyleSheet("""
            QDialog {
                background-color: %s;
            }
        """ % colors["window"])
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = BodyLabel("欢迎使用《呜呜大地图》！")
        title_label.setStyleSheet("""
            BodyLabel {
                font-size: 18px;
                font-weight: bold;
                color: %s;
                margin-bottom: 10px;
            }
        """ % colors["title"])
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 免责声明内容
        content_text = """本软件由B站UP主 古霍（UID: 1876277780）免费开发并发布。如果您是付费购买的，请立即退款并举报商家。

<b>重要风险提示：</b>

本软件通过"屏幕截图"来获取游戏坐标和提供便利操作。尽管这些技术本身不涉及修改游戏文件或内存，属于辅助工具范畴，但我们无法100%保证其行为完全兼容《鸣潮》未来所有版本更新或其反作弊系统的检测逻辑。

因使用本软件而可能导致的任何游戏账号异常（如警告、暂时限制等）的极低概率风险，需由您本人了解并承担。

点击"确定"即表示您已阅读、理解并同意以上条款。"""
        
        content_label = QTextBrowser()
        content_label.setHtml(content_text.replace("\n", "<br>"))
        content_label.setOpenExternalLinks(False)
        content_label.setFrameShape(QTextBrowser.NoFrame)
        content_label.setStyleSheet("""
            QTextBrowser {
                font-size: 12px;
                line-height: 1.6;
                color: %s;
                background-color: %s;
                border: 1px solid %s;
                border-radius: 8px;
                padding: 15px;
            }
        """ % (colors["text"], colors["panel"], colors["border"]))
        layout.addWidget(content_label)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # 取消按钮
        cancel_btn = PushButton("取消")
        cancel_btn.setFixedSize(80, 35)
        cancel_btn.setStyleSheet("""
            PushButton {
                color: %s;
                background-color: %s;
                border: 1px solid %s;
                border-radius: 6px;
            }
            PushButton:hover {
                background-color: %s;
            }
        """ % (colors["button_text"], colors["button_bg"], colors["border"], colors["button_bg_hover"]))
        cancel_btn.clicked.connect(self.reject)

        # 确定按钮 - 使用 PrimaryPushButton 突出主要操作
        accept_btn = PrimaryPushButton("确定")
        accept_btn.setFixedSize(80, 35)
        accept_btn.clicked.connect(self.accept)

        button_layout.addWidget(cancel_btn)
        button_layout.addSpacing(10)
        button_layout.addWidget(accept_btn)
        button_layout.addStretch()

        layout.addLayout(button_layout)
