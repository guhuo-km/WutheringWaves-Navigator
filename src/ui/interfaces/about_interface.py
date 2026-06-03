# -*- coding: utf-8 -*-
import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout

from qfluentwidgets import (
    ScrollArea, CardWidget, BodyLabel, TitleLabel, CaptionLabel,
    HyperlinkButton, PrimaryPushButton, DotInfoBadge, InfoBadgePosition,
    FluentIcon as FIF
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

try:
    from core.version import load_version_info
except ImportError:
    from ...core.version import load_version_info

try:
    from core import paths
except ImportError:
    from ...core import paths


class AboutInterface(ScrollArea):
    check_update_requested = Signal()
    start_update_requested = Signal()
    open_download_requested = Signal()

    GITHUB_URL = "https://github.com/guhuo-km/WutheringWaves-Navigator"
    BILIBILI_URL = "https://space.bilibili.com/1876277780"

    @staticmethod
    def _resolve_runtime_asset(*parts: str) -> str:
        return str(paths.resource_root().joinpath(*parts))
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutInterface")
        self._update_button_badge = None
        self._version_info = load_version_info()
        self._update_state = ("not_checked",)

        # Set transparent background for consistent appearance
        self.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._scroll_widget = QWidget()
        self._layout = QVBoxLayout(self._scroll_widget)
        self._layout.setContentsMargins(48, 32, 48, 32)
        self._layout.setSpacing(24)
        self._layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.setWidget(self._scroll_widget)
        self.setWidgetResizable(True)
        
        self._init_header()
        self._init_info_card()
        self._init_credits_card()
        self._init_update_card()
        self.retranslate_ui()
        
        self._layout.addStretch(1)
    
    def _init_header(self):
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setAlignment(Qt.AlignCenter)
        header_layout.setSpacing(12)
        
        logo_label = BodyLabel()
        logo_path = self._resolve_runtime_asset("assets", "ico.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(pixmap.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(logo_label)
        
        self.title_label = TitleLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.title_label)
        
        version = CaptionLabel(f"v{self._version_info.version}")
        version.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(version)
        
        self.desc_label = BodyLabel()
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.desc_label)
        
        self._layout.addWidget(header)
    
    def _init_info_card(self):
        self.info_card = CardWidget()
        card_layout = QVBoxLayout(self.info_card)
        card_layout.setSpacing(16)

        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignCenter)
        links_layout.setSpacing(24)

        self.github_btn = HyperlinkButton(
            url=self.GITHUB_URL,
            text="",
            parent=self
        )
        self.github_btn.setIcon(FIF.GITHUB)
        links_layout.addWidget(self.github_btn)

        self.bilibili_btn = HyperlinkButton(
            url=self.BILIBILI_URL,
            text="",
            parent=self
        )
        self.bilibili_btn.setIcon(FIF.LINK)
        links_layout.addWidget(self.bilibili_btn)

        card_layout.addLayout(links_layout)
        self._layout.addWidget(self.info_card)

    def _init_update_card(self):
        self.update_card = CardWidget()
        card_layout = QVBoxLayout(self.update_card)
        card_layout.setContentsMargins(20, 12, 20, 12)
        card_layout.setSpacing(6)

        self.update_title_label = BodyLabel()
        self.update_version_label = BodyLabel()
        self.update_status_label = BodyLabel()
        self.update_mode_label = CaptionLabel()
        self.update_checked_label = CaptionLabel()
        self.update_reason_label = CaptionLabel("")
        self.update_btn = PrimaryPushButton("", self)
        self.start_update_btn = PrimaryPushButton("", self)
        self.open_download_btn = PrimaryPushButton("", self)

        for label in (
            self.update_status_label,
            self.update_mode_label,
            self.update_checked_label,
            self.update_reason_label,
        ):
            if hasattr(label, "setWordWrap"):
                label.setWordWrap(True)

        self.update_title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.update_version_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.update_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.update_btn.clicked.connect(self.check_update_requested.emit)
        self.start_update_btn.clicked.connect(self.start_update_requested.emit)
        self.open_download_btn.clicked.connect(self.open_download_requested.emit)
        self.start_update_btn.hide()
        self.open_download_btn.hide()

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        header_layout.addWidget(self.update_title_label)
        header_layout.addStretch(1)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(4)
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.addWidget(self.update_version_label, 0, 0)
        info_grid.addWidget(self.update_status_label, 0, 1)
        info_grid.addWidget(self.update_checked_label, 1, 0)
        info_grid.addWidget(self.update_mode_label, 1, 1)
        info_grid.addWidget(self.update_reason_label, 2, 0, 1, 2)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 2, 0, 0)
        button_layout.addWidget(self.update_btn)
        button_layout.addWidget(self.start_update_btn)
        button_layout.addWidget(self.open_download_btn)
        button_layout.addStretch(1)

        card_layout.addLayout(header_layout)
        card_layout.addLayout(info_grid)
        card_layout.addLayout(button_layout)

        self._layout.addWidget(self.update_card)

    def set_update_checking(self):
        self._update_state = ("checking",)
        self._render_update_state()
        self.update_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.start_update_btn.hide()
        self.open_download_btn.hide()

    def set_update_no_update(self, checked_text: str):
        self._update_state = ("latest", checked_text)
        self._render_update_state()
        self.update_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.start_update_btn.hide()
        self.open_download_btn.hide()

    def set_update_available(
        self,
        latest_version: str,
        mode_text: str,
        size_text: str,
        checked_text: str,
        can_auto_update: bool,
        release_notes: str = "",
    ):
        self._update_state = (
            "available",
            latest_version,
            mode_text,
            size_text,
            checked_text,
            can_auto_update,
            release_notes,
        )
        self._render_update_state()
        self.update_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.start_update_btn.setVisible(can_auto_update)
        self.open_download_btn.show()

    def set_update_full_required(self, latest_version: str, reason: str, checked_text: str):
        self._update_state = ("full_required", latest_version, reason, checked_text)
        self._render_update_state()
        self.update_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.start_update_btn.hide()
        self.open_download_btn.show()

    def set_update_failed(self, reason: str):
        self._update_state = ("failed", reason)
        self._render_update_state()
        self.update_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.start_update_btn.hide()
        self.open_download_btn.show()
    
    def _init_credits_card(self):
        self.credits_card = CardWidget()
        card_layout = QVBoxLayout(self.credits_card)
        card_layout.setSpacing(8)
        
        self.credits_title = BodyLabel()
        title_font = self.credits_title.font()
        title_font.setBold(True)
        self.credits_title.setFont(title_font)
        card_layout.addWidget(self.credits_title)
        
        self._credit_labels = []
        for _ in range(3):
            label = CaptionLabel()
            self._credit_labels.append(label)
            card_layout.addWidget(label)

        self._layout.addWidget(self.credits_card)

    def _render_update_state(self):
        state = self._update_state[0]
        self.update_title_label.setText(tr("about_update", "更新"))
        self.update_version_label.setText(
            tr("about_version", "版本: v{version}", version=self._version_info.version)
        )
        self.update_btn.setText(tr("about_check_update", "检查更新"))
        self.start_update_btn.setText(tr("about_start_update", "立即更新"))
        self.open_download_btn.setText(tr("about_open_download", "打开下载页"))

        if state == "checking":
            self.update_status_label.setText(
                tr("about_update_status_checking", "状态: 正在检查更新")
            )
            self.update_mode_label.setText(tr("about_update_mode_empty", "更新方式: - / 大小: -"))
            self.update_checked_label.setText(tr("about_update_checked_empty", "最近检查: -"))
            self.update_reason_label.setText("")
        elif state == "latest":
            _state, checked_text = self._update_state
            self.update_status_label.setText(
                tr("about_update_status_latest", "状态: 当前已是最新版本")
            )
            self.update_mode_label.setText(tr("about_update_mode_empty", "更新方式: - / 大小: -"))
            self.update_checked_label.setText(
                tr("about_update_checked", "最近检查: {checked_text}", checked_text=checked_text)
            )
            self.update_reason_label.setText("")
        elif state == "available":
            (
                _state,
                latest_version,
                mode_text,
                size_text,
                checked_text,
                _can_auto_update,
                release_notes,
            ) = self._update_state
            self.update_status_label.setText(
                tr("about_update_status_available", "状态: 有可用更新 v{version}", version=latest_version)
            )
            self.update_mode_label.setText(
                tr("about_update_mode_size", "更新方式: {mode} / 大小: {size}", mode=mode_text, size=size_text)
            )
            self.update_checked_label.setText(
                tr("about_update_checked", "最近检查: {checked_text}", checked_text=checked_text)
            )
            self.update_reason_label.setText(
                tr("about_update_release_notes", "更新日志: {notes}", notes=release_notes.strip())
                if release_notes.strip()
                else ""
            )
        elif state == "full_required":
            _state, latest_version, reason, checked_text = self._update_state
            self.update_status_label.setText(
                tr("about_update_status_full_required", "状态: 需要下载安装新版 v{version}", version=latest_version)
            )
            self.update_mode_label.setText(
                tr("about_update_manual_mode", "更新方式: 手动下载安装 / 大小: -")
            )
            self.update_checked_label.setText(
                tr("about_update_checked", "最近检查: {checked_text}", checked_text=checked_text)
            )
            self.update_reason_label.setText(
                tr("about_update_reason", "原因: {reason}", reason=reason)
            )
        elif state == "failed":
            _state, reason = self._update_state
            self.update_status_label.setText(
                tr("about_update_status_failed", "状态: 检查失败")
            )
            self.update_mode_label.setText(tr("about_update_mode_empty", "更新方式: - / 大小: -"))
            self.update_checked_label.setText(tr("about_update_checked_empty", "最近检查: -"))
            self.update_reason_label.setText(
                tr("about_update_reason", "原因: {reason}", reason=reason)
            )
        else:
            self.update_status_label.setText(
                tr("about_update_status_not_checked", "状态: 未检查")
            )
            self.update_mode_label.setText(tr("about_update_mode_empty", "更新方式: - / 大小: -"))
            self.update_checked_label.setText(tr("about_update_checked_empty", "最近检查: -"))
            self.update_reason_label.setText("")

    def retranslate_ui(self):
        self.title_label.setText(tr("about_title", "呜呜大地图"))
        self.desc_label.setText(
            tr("about_description", "一个用于鸣潮游戏的智能地图导航工具，支持OCR坐标识别和路线录制")
        )
        self.github_btn.setText(tr("about_github_homepage", "GitHub项目主页"))
        self.bilibili_btn.setText(tr("about_bilibili_homepage", "B站主页"))
        self._render_update_state()

        self.credits_title.setText(tr("about_credits_title", "致谢"))
        credit_keys = [
            ("about_credit_fluent", "PyQt-Fluent-Widgets - 现代Fluent Design UI框架"),
            ("about_credit_ocr", "PaddleOCR / YOLO - 坐标识别引擎"),
            ("about_credit_maps", "地图数据来自官方来源"),
        ]
        for label, (key, default) in zip(self._credit_labels, credit_keys):
            label.setText(tr(key, default))

    def update_theme(self):
        """更新主题样式"""
        from core.theme_manager import ThemeManager
        card_style = ThemeManager.get_card_widget_style()
        self._scroll_widget.setStyleSheet(ThemeManager.get_page_background_style())
        self.info_card.setStyleSheet(card_style)
        self.credits_card.setStyleSheet(card_style)
        self.update_card.setStyleSheet(card_style)
        if ThemeManager.is_dark_theme():
            text_style = "background-color: transparent; color: #EDEDED;"
            for label in (
                self.update_title_label,
                self.update_version_label,
                self.update_status_label,
                self.update_mode_label,
                self.update_checked_label,
                self.update_reason_label,
            ):
                label.setStyleSheet(text_style)
            self.credits_title.setStyleSheet("font-weight: bold; " + text_style)
            for label in self._credit_labels:
                label.setStyleSheet(text_style)
        else:
            for label in (
                self.update_title_label,
                self.update_version_label,
                self.update_status_label,
                self.update_mode_label,
                self.update_checked_label,
                self.update_reason_label,
            ):
                label.setStyleSheet("")
            self.credits_title.setStyleSheet("font-weight: bold;")
            for label in self._credit_labels:
                label.setStyleSheet("")

    def set_update_badge_visible(self, visible: bool):
        if visible:
            if self._update_button_badge is None:
                self._update_button_badge = DotInfoBadge.attension(
                    parent=self,
                    target=self.update_btn,
                    position=InfoBadgePosition.TOP_RIGHT
                )
            self._update_button_badge.show()
        elif self._update_button_badge is not None:
            self._update_button_badge.hide()
