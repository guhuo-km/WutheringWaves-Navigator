# -*- coding: utf-8 -*-
"""
Constants and configuration values
"""

from typing import Dict

# Default global hotkey configuration
DEFAULT_HOTKEYS: Dict[str, str] = {
    "toggle_ocr": "",        # Toggle OCR recognition (default unset)
    "toggle_recording": "",  # Toggle route recording (default unset)
    "mark_next": "",         # Mark next point (default unset)
    "undo": "",              # Undo (default unset)
    "open_nearest": "",      # Open nearest unfinished point popup (default unset)
    "close_popup": "",       # Close current map popup (default unset)
    "zoom_in": "",           # Zoom map in by one level (default unset)
    "zoom_out": "",          # Zoom map out by one level (default unset)
    "prev_route": "",        # Show previous imported route (default unset)
    "next_route": ""         # Show next imported route (default unset)
}

# Button to URL key mapping
BUTTON_TO_URL_KEY: Dict[str, str] = {
    "radio_online_official": "official_map",
}


def get_map_urls(current_language: str = "zh_CN") -> Dict[str, str]:
    """
    Get map URL mapping based on current language
    
    Args:
        current_language: Current language code (e.g., 'zh_CN', 'en_US')
    
    Returns:
        Dict mapping provider keys to URLs
    """
    return {
        "official_map": "https://www.kurobbs.com/mc/map",
    }
