# -*- coding: utf-8 -*-
"""
UI Dialogs Package
对话框组件包
"""

from .disclaimer_dialog import DisclaimerDialog
from .calibration_window import CalibrationWindow
from .window_selection_dialog import WindowSelectionDialog

try:
    from core import window_ignores
except Exception:
    window_ignores = None

if window_ignores is not None:
    window_ignores.install_patches()

__all__ = [
    'DisclaimerDialog',
    'CalibrationWindow',
    'WindowSelectionDialog',
]
