# -*- coding: utf-8 -*-
"""
日志页面 - 三个标签页：系统日志、OCR日志、调试日志
日志写入改为文件异步写入，UI 按需加载当前会话日志。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, Optional, Tuple

from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit
from qfluentwidgets import (
    BodyLabel, SubtitleLabel, PushButton, CardWidget,
    SegmentedWidget, FluentIcon as FIF, CheckBox
)

try:
    from language_manager import tr
except ImportError:
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

from core.settings_manager import SettingsManager


class OutputRedirector:
    """重定向 stdout/stderr 到日志文件（保留原始终端输出）"""

    def __init__(self, log_manager, original_stream):
        self.log_manager = log_manager
        self.original_stream = original_stream

    def write(self, message):
        if self.original_stream:
            self.original_stream.write(message)
            self.original_stream.flush()

        if not self.log_manager:
            return

        if message.strip():
            timestamp = datetime.now().strftime("%H:%M:%S")
            line = f"[{timestamp}] {message.strip()}"
            self.log_manager.enqueue("debug", line)

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()


class LogInterface(QWidget):
    """日志页面 - 三个标签页"""

    detailed_ocr_logging_toggled = Signal(bool)

    def __init__(self, log_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName('logInterface')

        self._log_manager = log_manager
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

        self._log_state: Dict[str, Dict[str, object]] = {}
        self._in_append: bool = False
        self._reverse_order: bool = True
        self._page_active: bool = False
        self._settings = SettingsManager()
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(1000)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_tick)

        self.setup_ui()
        self._setup_output_redirection()
        self._init_log_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        header_layout = QHBoxLayout()
        self.title_label = SubtitleLabel()
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.segment = SegmentedWidget()
        self.segment.addItem("system", "")
        self.segment.addItem("ocr", "")
        self.segment.addItem("debug", "")
        self.segment.setCurrentItem("system")
        self.segment.currentItemChanged.connect(self.on_tab_changed)
        header_layout.addWidget(self.segment)

        layout.addLayout(header_layout)

        # 控制栏
        control_layout = QHBoxLayout()
        self.auto_refresh_label = BodyLabel()
        control_layout.addWidget(self.auto_refresh_label)

        self.auto_refresh_check = CheckBox()
        self.auto_refresh_check.setChecked(False)
        self.auto_refresh_check.stateChanged.connect(self._on_auto_refresh_toggled)
        control_layout.addWidget(self.auto_refresh_check)

        control_layout.addSpacing(10)
        self.refresh_interval_label = BodyLabel()
        control_layout.addWidget(self.refresh_interval_label)

        control_layout.addSpacing(24)
        self.detailed_ocr_label = BodyLabel()
        control_layout.addWidget(self.detailed_ocr_label)

        self.detailed_ocr_check = CheckBox()
        self.detailed_ocr_check.setChecked(
            bool(self._settings.get("logging.detailed_ocr_enabled", False))
        )
        self.detailed_ocr_check.stateChanged.connect(self._on_detailed_ocr_toggled)
        control_layout.addWidget(self.detailed_ocr_check)

        control_layout.addStretch()

        self.manual_refresh_btn = PushButton(FIF.SYNC, "")
        self.manual_refresh_btn.clicked.connect(self._manual_refresh_current)
        control_layout.addWidget(self.manual_refresh_btn)

        layout.addLayout(control_layout)

        content_card = CardWidget(self)
        content_layout = QVBoxLayout(content_card)
        content_layout.setContentsMargins(0, 0, 0, 0)

        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)

        self.system_log_edit = self._create_log_editor(font)
        self.ocr_log_edit = self._create_log_editor(font)
        self.debug_log_edit = self._create_log_editor(font)

        self.ocr_log_edit.setVisible(False)
        self.debug_log_edit.setVisible(False)

        content_layout.addWidget(self.system_log_edit)
        content_layout.addWidget(self.ocr_log_edit)
        content_layout.addWidget(self.debug_log_edit)

        layout.addWidget(content_card, 1)

        # 底部工具栏
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()

        self.clear_btn = PushButton(FIF.DELETE, "")
        self.clear_btn.clicked.connect(self.clear_current_logs)
        toolbar_layout.addWidget(self.clear_btn)

        self.save_btn = PushButton(FIF.SAVE, "")
        self.save_btn.clicked.connect(self.save_current_logs)
        toolbar_layout.addWidget(self.save_btn)

        layout.addLayout(toolbar_layout)

        self.retranslate_ui()
        self.update_theme()

    def _create_log_editor(self, font: QFont) -> QTextEdit:
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QTextEdit.NoWrap)
        editor.setFont(font)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        editor.verticalScrollBar().valueChanged.connect(
            lambda _: self._on_scroll_bottom(editor)
        )
        return editor

    def _setup_output_redirection(self):
        if not self._log_manager:
            return
        sys.stdout = OutputRedirector(self._log_manager, self._original_stdout)
        sys.stderr = OutputRedirector(self._log_manager, self._original_stderr)

    def _init_log_state(self):
        self._log_state = {
            "system": {"offset": 0, "loaded": 0, "path": self._get_log_path("system")},
            "ocr": {"offset": 0, "loaded": 0, "path": self._get_log_path("ocr")},
            "debug": {"offset": 0, "loaded": 0, "path": self._get_log_path("debug")},
        }
        self._load_initial_log("system")

    def _get_log_path(self, log_type: str) -> Optional[str]:
        if self._log_manager:
            return self._log_manager.get_log_path(log_type)
        return None

    def _current_key(self) -> str:
        # SegmentedWidget.currentItem() returns SegmentedItem widget,
        # while we need the route key string ('system'/'ocr'/'debug').
        try:
            key = self.segment.currentRouteKey()
        except Exception:
            key = "system"
        if key not in self._log_state:
            return "system"
        return key

    def _current_editor(self) -> QTextEdit:
        if self._current_key() == "ocr":
            return self.ocr_log_edit
        if self._current_key() == "debug":
            return self.debug_log_edit
        return self.system_log_edit

    def _load_initial_log(self, key: str):
        editor = self._editor_for_key(key)
        if not editor:
            return

        editor.clear()
        self._log_state[key]["offset"] = 0
        self._log_state[key]["loaded"] = 0
        self._append_log_lines(key, max_lines=200)
        editor.verticalScrollBar().setValue(0)

    def _append_log_lines(self, key: str, max_lines: Optional[int]):
        if self._in_append:
            return
        if key not in self._log_state:
            return

        path = self._log_state[key]["path"]
        editor = self._editor_for_key(key)
        if not path or not editor:
            return
        if not os.path.exists(path):
            editor.setPlainText(tr("log_missing_file", "日志文件不存在"))
            return

        self._in_append = True
        try:
            offset = int(self._log_state[key]["offset"])
            lines, new_offset = self._read_lines(path, offset, max_lines)
            if not lines:
                return

            bar = editor.verticalScrollBar()
            at_top = bar.value() == bar.minimum()
            at_bottom = bar.value() == bar.maximum()

            # File is naturally oldest -> newest. In reverse-order UI (newest first),
            # we must reverse each newly-read batch before prepending, otherwise
            # timestamps inside the batch become mixed (e.g. 10:32, 10:30, 10:31).
            text = "".join(reversed(lines)) if self._reverse_order else "".join(lines)
            if self._reverse_order:
                # Newest first in UI: prepend newly appended log lines.
                prev = editor.toPlainText()
                editor.setPlainText(text + prev)
            else:
                editor.moveCursor(QTextCursor.End)
                editor.insertPlainText(text)
            editor.horizontalScrollBar().setValue(0)

            self._log_state[key]["offset"] = new_offset
            self._log_state[key]["loaded"] = int(self._log_state[key]["loaded"]) + len(lines)

            if self._reverse_order:
                if at_top:
                    editor.verticalScrollBar().setValue(editor.verticalScrollBar().minimum())
            else:
                if at_bottom:
                    editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())
        finally:
            self._in_append = False

    def _read_lines(self, path: str, offset: int, max_lines: Optional[int]) -> Tuple[list[str], int]:
        lines = []
        new_offset = offset
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                while True:
                    if max_lines is not None and len(lines) >= max_lines:
                        break
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line)
                new_offset = f.tell()
        except Exception:
            return [], offset
        return lines, new_offset

    def _editor_for_key(self, key: str) -> Optional[QTextEdit]:
        if key == "system":
            return self.system_log_edit
        if key == "ocr":
            return self.ocr_log_edit
        if key == "debug":
            return self.debug_log_edit
        return None

    def _on_scroll_bottom(self, editor: QTextEdit):
        if self._in_append:
            return
        key = self._key_for_editor(editor)
        if not key:
            return
        bar = editor.verticalScrollBar()
        if self._reverse_order:
            if bar.value() <= bar.minimum():
                self._append_log_lines(key, max_lines=200)
        else:
            if bar.value() >= bar.maximum():
                self._append_log_lines(key, max_lines=200)

    def _key_for_editor(self, editor: QTextEdit) -> Optional[str]:
        if editor == self.system_log_edit:
            return "system"
        if editor == self.ocr_log_edit:
            return "ocr"
        if editor == self.debug_log_edit:
            return "debug"
        return None

    def _manual_refresh_current(self):
        self._append_log_lines(self._current_key(), max_lines=400)

    def _on_auto_refresh_toggled(self):
        if self.auto_refresh_check.isChecked() and self._page_active:
            # Refresh once immediately for better UX
            self._append_log_lines(self._current_key(), max_lines=200)
            self._auto_refresh_timer.start()
        else:
            self._auto_refresh_timer.stop()

    def _on_auto_refresh_tick(self):
        if not self._page_active or not self.isVisible():
            return
        self._append_log_lines(self._current_key(), max_lines=200)

    def set_page_active(self, active: bool):
        self._page_active = bool(active)
        if self.auto_refresh_check.isChecked() and self._page_active:
            self._append_log_lines(self._current_key(), max_lines=200)
            self._auto_refresh_timer.start()
        else:
            self._auto_refresh_timer.stop()

    def _on_detailed_ocr_toggled(self):
        enabled = self.detailed_ocr_check.isChecked()
        self._settings.set("logging.detailed_ocr_enabled", enabled)
        self.detailed_ocr_logging_toggled.emit(enabled)

    def is_detailed_ocr_logging_enabled(self) -> bool:
        return bool(self.detailed_ocr_check.isChecked())

    def on_tab_changed(self, key: str):
        self.system_log_edit.setVisible(key == "system")
        self.ocr_log_edit.setVisible(key == "ocr")
        self.debug_log_edit.setVisible(key == "debug")
        self._load_initial_log(key)

    def clear_current_logs(self):
        key = self._current_key()
        path = self._log_state[key]["path"]
        editor = self._current_editor()
        if path:
            try:
                with open(path, "w", encoding="utf-8"):
                    pass
            except Exception:
                pass
        editor.clear()
        self._log_state[key]["offset"] = 0
        self._log_state[key]["loaded"] = 0

    def save_current_logs(self):
        from PySide6.QtWidgets import QFileDialog

        key = self._current_key()
        editor = self._current_editor()
        content = editor.toPlainText()
        if not content:
            return

        default_name = f"{key}_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("log_save_dialog_title", "保存日志"),
            default_name,
            "Log Files (*.log);;Text Files (*.txt);;All Files (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass

    def update_theme(self):
        from core.theme_manager import ThemeManager
        style = ThemeManager.get_text_edit_style()
        self.system_log_edit.setStyleSheet(style)
        self.ocr_log_edit.setStyleSheet(style)
        self.debug_log_edit.setStyleSheet(style)

    def retranslate_ui(self):
        self.title_label.setText(tr("log_title", "运行日志"))
        self.segment.setItemText("system", tr("log_system", "系统日志"))
        self.segment.setItemText("ocr", tr("log_ocr", "OCR 日志"))
        self.segment.setItemText("debug", tr("log_debug", "调试日志"))
        self.auto_refresh_label.setText(tr("log_auto_refresh", "自动刷新:"))
        self.refresh_interval_label.setText(tr("log_refresh_interval_1s", "刷新间隔: 1s"))
        self.detailed_ocr_label.setText(tr("log_detailed_ocr", "详细OCR日志:"))
        self.manual_refresh_btn.setText(tr("log_manual_refresh", "手动刷新"))
        self.clear_btn.setText(tr("log_clear", "清空日志"))
        self.save_btn.setText(tr("log_save", "保存日志"))

    def closeEvent(self, event):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        event.accept()
