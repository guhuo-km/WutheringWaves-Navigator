# -*- coding: utf-8 -*-
from typing import Optional
from datetime import datetime

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget

from qfluentwidgets import CardWidget, TextEdit, PushButton, FluentIcon as FIF


class LogWidget(CardWidget):
    
    MAX_LOG_LINES = 500
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._log_count = 0
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        
        self._clear_btn = PushButton(FIF.DELETE, "")
        self._clear_btn.setFixedSize(32, 32)
        self._clear_btn.setToolTip("Clear log")
        self._clear_btn.clicked.connect(self.clear_log)
        toolbar.addWidget(self._clear_btn)
        
        layout.addLayout(toolbar)
        
        self._log_area = TextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMinimumHeight(150)
        layout.addWidget(self._log_area)
    
    @Slot(str)
    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        self._log_area.append(formatted)
        self._log_count += 1
        
        if self._log_count > self.MAX_LOG_LINES:
            self._trim_log()
        
        scrollbar = self._log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _trim_log(self):
        text = self._log_area.toPlainText()
        lines = text.split('\n')
        if len(lines) > self.MAX_LOG_LINES:
            trimmed = '\n'.join(lines[-self.MAX_LOG_LINES:])
            self._log_area.setPlainText(trimmed)
            self._log_count = self.MAX_LOG_LINES
    
    def clear_log(self):
        self._log_area.clear()
        self._log_count = 0
    
    def get_log_text(self) -> str:
        return self._log_area.toPlainText()
