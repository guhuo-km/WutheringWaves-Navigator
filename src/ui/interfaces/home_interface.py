# -*- coding: utf-8 -*-
import os
import random
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, QSignalBlocker, QRect, QSize
from PySide6.QtGui import QPainter, QPixmap, QLinearGradient, QColor, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QSizePolicy
)

from qfluentwidgets import (
    ScrollArea, CardWidget, PrimaryPushButton,
    BodyLabel, TitleLabel, CaptionLabel, StrongBodyLabel,
    ComboBox
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        text = default if default is not None else key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError):
                return text
        return text

from core.settings_manager import SettingsManager
from core import paths


def _resolve_runtime_asset(*parts: str) -> str:
    """Resolve asset path in source and PyInstaller-frozen runtime."""
    return str(paths.resource_root().joinpath(*parts))


class BannerOverlay(QWidget):
    """Bottom-left gradient overlay for banner text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        gradient = QLinearGradient(rect.bottomLeft(), rect.topRight())
        gradient.setColorAt(0.0, QColor(0, 0, 0, 200))
        gradient.setColorAt(0.7, QColor(0, 0, 0, 0))
        painter.fillRect(rect, gradient)


class BannerWidget(QWidget):
    """Banner image with bottom-left gradient and white title/subtitle."""

    BANNER_ZOOM_FACTOR = 1.10

    def __init__(self, image_path: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._pixmap: Optional[QPixmap] = None
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._load_pixmap()

        self._overlay = BannerOverlay(self)
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(16, 12, 16, 12)
        overlay_layout.setSpacing(6)
        overlay_layout.setAlignment(Qt.AlignLeft | Qt.AlignBottom)

        self._title_label = TitleLabel(title)
        self._title_label.setStyleSheet("color: #FFFFFF;")
        overlay_layout.addWidget(self._title_label)

        self._subtitle_label = BodyLabel(subtitle)
        self._subtitle_label.setStyleSheet("color: #FFFFFF;")
        self._subtitle_label.setWordWrap(True)
        overlay_layout.addWidget(self._subtitle_label)

    def set_banner_text(self, title: str, subtitle: str):
        self._title_label.setText(title)
        self._subtitle_label.setText(subtitle)

    def _load_pixmap(self):
        self._pixmap = None
        if not self._image_path:
            return
        if os.path.exists(self._image_path):
            self._pixmap = QPixmap(self._image_path)
            return
        base, _ext = os.path.splitext(self._image_path)
        for ext in (".png", ".jpg", ".jpeg"):
            candidate = base + ext
            if os.path.exists(candidate):
                self._pixmap = QPixmap(candidate)
                return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap and self.width() > 0:
            ratio = self._pixmap.height() / self._pixmap.width()
            target_height = max(1, int(self.width() * ratio))
            target_height = max(220, min(320, target_height))
            if target_height != self.height():
                self.setFixedHeight(target_height)
        overlay_width = int(self.width() * 0.7)
        overlay_height = int(self.height() * 0.55)
        self._overlay.setGeometry(
            0, self.height() - overlay_height, overlay_width, overlay_height
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        radius = 8
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        if self._pixmap and not self._pixmap.isNull():
            zoomed_size = QSize(
                max(1, int(rect.width() * self.BANNER_ZOOM_FACTOR)),
                max(1, int(rect.height() * self.BANNER_ZOOM_FACTOR)),
            )
            scaled = self._pixmap.scaled(
                zoomed_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.fillRect(rect, QColor("#2B2B2B"))
            target_x = (rect.width() - scaled.width()) // 2
            target_y = (rect.height() - scaled.height()) // 2
            target_rect = QRect(target_x, target_y, scaled.width(), scaled.height())
            painter.drawPixmap(target_rect, scaled)
        else:
            painter.fillRect(rect, QColor("#2B2B2B"))


class HomeInterface(ScrollArea):

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.setObjectName("homeInterface")

        self._settings = SettingsManager()
        self._current_game_path: Optional[str] = None

        self._launch_status_key = "home_launch_status_no_path"
        self._feature_art_path = random.choice(
            [
                _resolve_runtime_asset("assets", "女漂.png"),
                _resolve_runtime_asset("assets", "男漂.png"),
            ]
        )

        # Set transparent background for consistent appearance
        self.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._scroll_widget = QWidget()
        self._layout = QVBoxLayout(self._scroll_widget)
        self._layout.setContentsMargins(36, 24, 36, 24)
        self._layout.setSpacing(16)

        self.setWidget(self._scroll_widget)
        self.setWidgetResizable(True)

        self._init_top_section()
        self._init_bottom_section()

        self.update_theme()
        self.retranslate_ui()
        self.update_status()

        self._connect_signals()

    def _connect_signals(self):
        pass

    def _init_top_section(self):
        top_container = QWidget()
        top_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        top_layout = QVBoxLayout(top_container)
        top_layout.setSpacing(12)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 随机选择女漂或男漂图片
        self._banner = BannerWidget(
            self._feature_art_path,
            "",
            "",
            self,
        )
        self._banner_card = CardWidget(self)
        banner_layout = QVBoxLayout(self._banner_card)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.addWidget(self._banner)
        top_layout.addWidget(self._banner_card)
        self._layout.addWidget(top_container, 0)

    def _init_bottom_section(self):
        bottom_container = QWidget()
        bottom_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setSpacing(12)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        bottom_layout.addWidget(self._create_launch_card())
        bottom_layout.addWidget(self._create_daily_placeholder())

        self._layout.addWidget(bottom_container, 1)

    def _create_launch_card(self) -> CardWidget:
        self._launch_card = CardWidget(self)
        card_layout = QVBoxLayout(self._launch_card)
        card_layout.setSpacing(10)

        self._launch_title_label = StrongBodyLabel()
        card_layout.addWidget(self._launch_title_label)

        row = QHBoxLayout()
        row.setSpacing(12)

        self._game_path_combo = ComboBox()
        self._game_path_combo.setMinimumWidth(360)
        self._game_path_combo.currentIndexChanged.connect(self._on_game_combo_changed)
        row.addWidget(self._game_path_combo, 1)

        self._launch_btn = PrimaryPushButton()
        self._launch_btn.clicked.connect(self._launch_game)
        row.addWidget(self._launch_btn)

        card_layout.addLayout(row)

        self._launch_status_label = CaptionLabel()
        card_layout.addWidget(self._launch_status_label)

        self._load_game_path()
        return self._launch_card

    def _create_daily_placeholder(self) -> QWidget:
        placeholder = QWidget(self)
        placeholder.setMinimumHeight(236)
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return placeholder

    def _load_game_path(self):
        path = self._settings.get("game.launcher.exe_path", "")
        if path and os.path.isfile(path):
            self._current_game_path = path
        self._refresh_game_combo()

    def _refresh_game_combo(self):
        placeholder_text = tr("home_game_path_placeholder", "请选择游戏可执行文件...")
        pick_entry_text = tr("home_pick_game_path", "选择游戏运行位置...")
        with QSignalBlocker(self._game_path_combo):
            self._game_path_combo.clear()
            self._game_path_combo.addItem(placeholder_text)

            if self._current_game_path:
                self._game_path_combo.addItem(self._current_game_path)
                self._game_path_combo.setCurrentText(self._current_game_path)
                self._set_launch_status("home_launch_status_path_selected")
            else:
                self._game_path_combo.setCurrentIndex(0)
                self._set_launch_status("home_launch_status_no_path")

            self._game_path_combo.addItem(pick_entry_text)

    def _on_game_combo_changed(self, index: int):
        text = self._game_path_combo.currentText()
        if text == tr("home_pick_game_path", "选择游戏运行位置..."):
            self._select_game_path()
            return
        if text == tr("home_game_path_placeholder", "请选择游戏可执行文件..."):
            return

        if text and os.path.isfile(text):
            self._current_game_path = text
            self._settings.set("game.launcher.exe_path", text, save=True)
            self._set_launch_status("home_launch_status_path_selected")

    def _select_game_path(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("home_pick_game_path", "选择游戏运行位置..."),
            "",
            "Executable Files (*.exe);;All Files (*.*)"
        )
        if not file_path:
            self._refresh_game_combo()
            return

        if self._current_game_path == file_path:
            self._refresh_game_combo()
            return

        self._current_game_path = file_path
        self._settings.set("game.launcher.exe_path", file_path, save=True)
        self._refresh_game_combo()

    def _launch_game(self):
        if not self._current_game_path or not os.path.isfile(self._current_game_path):
            self._set_launch_status("home_launch_status_invalid_path")
            if self.app_state:
                self.app_state.append_system_log(
                    tr("home_launch_status_invalid_path", "启动失败：未选择有效的游戏路径"),
                    "ERROR",
                )
            return

        try:
            if os.name == "nt":
                os.startfile(self._current_game_path)
            else:
                subprocess.Popen([self._current_game_path])
            self._set_launch_status("home_launch_status_launched")
            if self.app_state:
                self.app_state.append_system_log(
                    tr("home_launch_status_launched", "已尝试启动游戏"),
                    "INFO",
                )
        except Exception as e:
            self._set_launch_status("home_launch_status_failed")
            if self.app_state:
                self.app_state.append_system_log(f"启动游戏失败：{e}", "ERROR")

    def _set_launch_status(self, key: str):
        self._launch_status_key = key
        defaults = {
            "home_launch_status_no_path": "未选择游戏可执行文件",
            "home_launch_status_path_selected": "已选择游戏路径",
            "home_launch_status_invalid_path": "启动失败：未选择有效的游戏路径",
            "home_launch_status_launched": "已尝试启动游戏",
            "home_launch_status_failed": "启动失败：请检查路径或权限",
        }
        self._launch_status_label.setText(tr(key, defaults[key]))

    def retranslate_ui(self):
        self._banner.set_banner_text(
            tr("home_banner_title", "呜呜大地图"),
            tr("home_banner_subtitle", "更好的鸣潮导航工具，免费且开源"),
        )
        self._launch_title_label.setText(
            tr("home_launch_title", "启动游戏并开始识别")
        )
        self._launch_btn.setText(tr("home_launch_game", "启动游戏"))
        self._set_launch_status(self._launch_status_key)

        if hasattr(self, "_game_path_combo"):
            current_text = self._game_path_combo.currentText()
            if (
                not self._current_game_path
                or current_text in (
                    tr("home_game_path_placeholder", "请选择游戏可执行文件..."),
                    tr("home_pick_game_path", "选择游戏运行位置..."),
                )
            ):
                self._refresh_game_combo()

    def update_status(self):
        pass

    def _append_pending_log(self, message: str) -> None:
        if self.app_state:
            self.app_state.append_system_log(message, "INFO")

    def update_theme(self):
        """更新主题样式"""
        from core.theme_manager import ThemeManager
        card_style = ThemeManager.get_card_widget_style()
        self._scroll_widget.setStyleSheet(ThemeManager.get_page_background_style())
        for card in (self._banner_card, self._launch_card):
            if card:
                card.setStyleSheet(card_style)

        # 强制保持 Banner 文字为白色（不受主题影响）
        if hasattr(self, "_banner") and self._banner:
            self._banner._title_label.setStyleSheet("color: #FFFFFF;")
            self._banner._subtitle_label.setStyleSheet("color: #FFFFFF;")
