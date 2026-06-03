# -*- coding: utf-8 -*-
"""
Custom SVG icons for WutheringWaves Navigator

Defines custom FluentIcon implementations that load SVG icons from assets/icons/
"""

import os
from enum import Enum
from qfluentwidgets.common.icon import FluentIconBase
from qfluentwidgets.common import Theme
from qfluentwidgets import isDarkTheme

from core import paths


def get_icon_path(filename: str) -> str:
    """Get absolute path to icon file in assets/icons/"""
    return str(paths.asset_file("icons", filename))


class CustomFluentIcon(FluentIconBase, Enum):
    """Custom Fluent Icons using SVG files"""

    OCR_SETTINGS = "ocr_settings"
    MAP_SETTINGS = "map_settings"
    ROUTE_RECORDING = "route_recording"
    HOTKEY = "hotkey"

    def path(self, theme=Theme.AUTO) -> str:
        """Get the path of the SVG icon"""
        resolved_theme = theme
        if theme == Theme.AUTO:
            resolved_theme = Theme.DARK if isDarkTheme() else Theme.LIGHT

        if resolved_theme == Theme.DARK:
            return get_icon_path(f"{self.value}_light.svg")

        return get_icon_path(f"{self.value}.svg")
