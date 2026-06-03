# -*- coding: utf-8 -*-
"""
Interface pages for the main navigation (V2 - 9 pages)
"""

from .home_interface import HomeInterface
from .navigation_interface import NavigationInterface
from .ocr_settings_interface import OCRSettingsInterface
from .map_settings_interface import MapSettingsInterface
from .route_settings_interface import RouteSettingsInterface
from .hotkey_interface import HotkeyInterface
from .log_interface import LogInterface
from .settings_interface import SettingsInterface
from .about_interface import AboutInterface

__all__ = [
    'HomeInterface',
    'NavigationInterface',
    'OCRSettingsInterface',
    'MapSettingsInterface',
    'RouteSettingsInterface',
    'HotkeyInterface',
    'LogInterface',
    'SettingsInterface',
    'AboutInterface'
]
