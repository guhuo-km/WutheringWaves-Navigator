# -*- coding: utf-8 -*-
"""
Settings manager - wrapper for app_settings.json
"""

import os
import json
from typing import Any, Optional

from core import paths


class SettingsManager:
    """Manages application settings persistence"""

    _shared_caches: dict[str, dict] = {}
    
    def __init__(self, settings_file: Optional[str] = None):
        """
        Initialize settings manager
        
        Args:
            settings_file: Path to settings file.
                         Defaults to app_settings.json in src directory.
        """
        if settings_file is None:
            self.settings_file = str(paths.config_file("app_settings.json"))
        else:
            self.settings_file = settings_file

        self.settings_file = os.path.abspath(self.settings_file)
        if self.settings_file not in self._shared_caches:
            self._shared_caches[self.settings_file] = {}
            self._load()
        self._cache = self._shared_caches[self.settings_file]
    
    def _load(self) -> None:
        """Load settings from file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            else:
                cache = {}
        except Exception as e:
            print(f"Failed to load settings: {e}")
            cache = {}

        self._shared_caches[self.settings_file] = cache
        self._cache = cache
    
    def _save(self) -> bool:
        """Save settings to file"""
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Failed to save settings: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value
        
        Args:
            key: Setting key (supports nested keys with '.')
            default: Default value if key not found
            
        Returns:
            Setting value or default
        """
        keys = key.split('.')
        value = self._cache
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any, save: bool = True) -> bool:
        """
        Set a setting value
        
        Args:
            key: Setting key (supports nested keys with '.')
            value: Value to set
            save: Whether to immediately save to file
            
        Returns:
            True if successful
        """
        keys = key.split('.')
        target = self._cache
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        
        if save:
            return self._save()
        return True
    
    def delete(self, key: str, save: bool = True) -> bool:
        """
        Delete a setting key
        
        Args:
            key: Setting key to delete
            save: Whether to immediately save to file
            
        Returns:
            True if key was found and deleted
        """
        keys = key.split('.')
        target = self._cache
        for k in keys[:-1]:
            if isinstance(target, dict) and k in target:
                target = target[k]
            else:
                return False
        
        if keys[-1] in target:
            del target[keys[-1]]
            if save:
                return self._save()
            return True
        return False
    
    def save(self) -> bool:
        """Explicitly save all settings"""
        return self._save()
    
    def reload(self) -> None:
        """Reload settings from file"""
        self._load()
    
    def get_all(self) -> dict:
        """Get all settings as a dictionary"""
        return self._cache.copy()
