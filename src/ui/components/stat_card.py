# -*- coding: utf-8 -*-
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout

from qfluentwidgets import CardWidget, BodyLabel, StrongBodyLabel, IconWidget


class StatCard(CardWidget):
    
    def __init__(self, title: str, value: str, icon=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setMinimumWidth(140)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        if icon:
            icon_widget = IconWidget(icon, self)
            icon_widget.setFixedSize(32, 32)
            layout.addWidget(icon_widget)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        self._title_label = BodyLabel(title)
        self._title_label.setObjectName("statCardTitle")
        text_layout.addWidget(self._title_label)
        
        self._value_label = StrongBodyLabel(value)
        self._value_label.setObjectName("statCardValue")
        text_layout.addWidget(self._value_label)
        
        layout.addLayout(text_layout)
        layout.addStretch()
    
    def set_value(self, value: str):
        self._value_label.setText(value)
    
    def set_title(self, title: str):
        self._title_label.setText(title)
    
    def get_value(self) -> str:
        return self._value_label.text()
    
    def get_title(self) -> str:
        return self._title_label.text()
