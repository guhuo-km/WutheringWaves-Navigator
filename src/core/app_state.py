# -*- coding: utf-8 -*-
"""
Application state management - centralized state with Qt Signals
"""

from typing import Optional, Any, List
from datetime import datetime
from PySide6.QtCore import QObject, Signal

from .calibration import TransformMatrix, CalibrationDataManager


class AppState(QObject):
    """
    Centralized application state manager
    
    All shared state flows through this class. UI components read from
    and write to AppState, which emits signals for cross-component updates.
    """
    
    # State change signals
    mode_changed = Signal(str)              # 'online' or 'local'
    map_provider_changed = Signal(str)       # Provider key
    local_map_changed = Signal(str)          # Local map name
    area_id_changed = Signal(str)            # Area ID for online maps
    calibration_updated = Signal(object)     # TransformMatrix or None
    ocr_state_changed = Signal(str)          # OCR state string
    tracking_state_changed = Signal(bool)    # Map tracking on/off
    recording_state_changed = Signal(bool)   # Route recording on/off
    coordinates_detected = Signal(int, int, int)  # x, y, z from OCR
    map_status_updated = Signal(float, float, int)  # lat, lng, zoom
    
    # UI-related signals
    log_message = Signal(str)                # Log message to display
    status_message = Signal(str)             # Status bar message
    system_log_updated = Signal(list)        # Full system log buffer (list[str])
    system_log_appended = Signal(str, str)   # message, level
    ocr_area_source_changed = Signal(str)    # 'none', 'auto', 'manual'
    ocr_region_changed = Signal(int, int, int, int)  # x, y, width, height
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        # Map state
        self._current_mode: str = "online"  # 'online' or 'local'
        self._current_map_provider: str = "official_map"
        self._current_local_map: Optional[str] = None
        self._current_area_id: Optional[str] = None
        self._current_url: Optional[str] = None
        
        # Calibration state
        self._transform_matrix: Optional[TransformMatrix] = None
        self._calibration_manager: Optional[CalibrationDataManager] = None
        self._auto_calibration_cached: bool = False
        self._auto_calibration_matrix: Optional[TransformMatrix] = None
        
        # Map status
        self._current_lat: float = 0.0
        self._current_lng: float = 0.0
        self._current_zoom: int = 1
        
        # Feature states
        self._ocr_running: bool = False
        self._tracking_active: bool = True  # Default enabled
        self._recording_active: bool = False

        # OCR area state
        self._ocr_area_source: str = "none"
        self._ocr_region = {"x": 0, "y": 0, "width": 0, "height": 0}

        # System log buffer
        self._system_log_buffer: List[str] = []
        self._system_log_max: int = 50

        # Log manager (optional)
        self._log_manager = None
        self._resource_probe = None
        
        # Initialize calibration manager
        self._calibration_manager = CalibrationDataManager()
    
    # ==================== Properties ====================
    
    @property
    def current_mode(self) -> str:
        return self._current_mode
    
    @current_mode.setter
    def current_mode(self, value: str):
        if value != self._current_mode:
            self._current_mode = value
            self.mode_changed.emit(value)
    
    @property
    def current_map_provider(self) -> str:
        return self._current_map_provider
    
    @current_map_provider.setter
    def current_map_provider(self, value: str):
        if value != self._current_map_provider:
            self._current_map_provider = value
            self.map_provider_changed.emit(value)
    
    @property
    def current_local_map(self) -> Optional[str]:
        return self._current_local_map
    
    @current_local_map.setter
    def current_local_map(self, value: Optional[str]):
        if value != self._current_local_map:
            self._current_local_map = value
            if value:
                self.local_map_changed.emit(value)
    
    @property
    def current_area_id(self) -> Optional[str]:
        return self._current_area_id
    
    @current_area_id.setter
    def current_area_id(self, value: Optional[str]):
        if value != self._current_area_id:
            self._current_area_id = value
            if value:
                self.area_id_changed.emit(value)
    
    @property
    def current_url(self) -> Optional[str]:
        return self._current_url
    
    @current_url.setter
    def current_url(self, value: Optional[str]):
        self._current_url = value
    
    @property
    def transform_matrix(self) -> Optional[TransformMatrix]:
        return self._transform_matrix
    
    @transform_matrix.setter
    def transform_matrix(self, value: Optional[TransformMatrix]):
        self._transform_matrix = value
        self.calibration_updated.emit(value)
    
    @property
    def calibration_manager(self) -> CalibrationDataManager:
        return self._calibration_manager
    
    @property
    def current_lat(self) -> float:
        return self._current_lat
    
    @property
    def current_lng(self) -> float:
        return self._current_lng
    
    @property
    def current_zoom(self) -> int:
        return self._current_zoom
    
    @property
    def ocr_running(self) -> bool:
        return self._ocr_running
    
    @ocr_running.setter
    def ocr_running(self, value: bool):
        if value != self._ocr_running:
            self._ocr_running = value
            state = "RUNNING" if value else "STOPPED"
            self.ocr_state_changed.emit(state)
    
    @property
    def tracking_active(self) -> bool:
        return self._tracking_active
    
    @tracking_active.setter
    def tracking_active(self, value: bool):
        if value != self._tracking_active:
            self._tracking_active = value
            self.tracking_state_changed.emit(value)
    
    @property
    def recording_active(self) -> bool:
        return self._recording_active
    
    @recording_active.setter
    def recording_active(self, value: bool):
        if value != self._recording_active:
            self._recording_active = value
            self.recording_state_changed.emit(value)

    @property
    def ocr_area_source(self) -> str:
        return self._ocr_area_source

    @ocr_area_source.setter
    def ocr_area_source(self, value: str):
        if value not in ("none", "auto", "manual"):
            value = "none"
        if value != self._ocr_area_source:
            self._ocr_area_source = value
            self.ocr_area_source_changed.emit(value)

    @property
    def ocr_region(self) -> dict:
        return dict(self._ocr_region)

    def set_ocr_region(self, x: int, y: int, width: int, height: int) -> None:
        """Update OCR capture region and notify listeners."""
        new_region = {"x": int(x), "y": int(y), "width": int(width), "height": int(height)}
        if new_region != self._ocr_region:
            self._ocr_region = new_region
            self.ocr_region_changed.emit(new_region["x"], new_region["y"], new_region["width"], new_region["height"])
    
    @property
    def auto_calibration_cached(self) -> bool:
        return self._auto_calibration_cached
    
    @auto_calibration_cached.setter
    def auto_calibration_cached(self, value: bool):
        self._auto_calibration_cached = value
    
    @property
    def auto_calibration_matrix(self) -> Optional[TransformMatrix]:
        return self._auto_calibration_matrix
    
    @auto_calibration_matrix.setter
    def auto_calibration_matrix(self, value: Optional[TransformMatrix]):
        self._auto_calibration_matrix = value
    
    # ==================== Methods ====================
    
    def update_map_status(self, lat: float, lng: float, zoom: int):
        """Update current map status from WebView"""
        self._current_lat = lat
        self._current_lng = lng
        self._current_zoom = zoom
        self.map_status_updated.emit(lat, lng, zoom)
    
    def update_ocr_coordinates(self, x: int, y: int, z: int):
        """Update coordinates from OCR detection"""
        self.coordinates_detected.emit(x, y, z)
    
    def log(self, message: str):
        """Emit log message signal"""
        self.append_system_log(message, "INFO")
        self.log_message.emit(message)
    
    def set_status(self, message: str):
        """Emit status message signal"""
        self.status_message.emit(message)

    def append_system_log(self, message: str, level: str = "INFO") -> None:
        """Append a message to the system log buffer and notify listeners."""
        if self._resource_probe:
            self._resource_probe.count("system_log.append")
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        self._system_log_buffer.append(line)
        if len(self._system_log_buffer) > self._system_log_max:
            self._system_log_buffer = self._system_log_buffer[-self._system_log_max:]
        self.system_log_updated.emit(self._system_log_buffer.copy())
        self.system_log_appended.emit(message, level)
        if self._log_manager:
            try:
                self._log_manager.enqueue("system", line)
            except Exception:
                pass

    def get_system_log_buffer(self) -> List[str]:
        """Return a copy of the system log buffer."""
        return self._system_log_buffer.copy()

    def set_log_manager(self, log_manager) -> None:
        """Attach a LogManager for file-based system logs."""
        self._log_manager = log_manager

    def set_resource_probe(self, resource_probe) -> None:
        """Attach optional runtime diagnostics counters."""
        self._resource_probe = resource_probe
    
    def load_calibration_for_current_map(self) -> bool:
        """
        Load calibration data for the current map configuration
        
        Returns:
            True if calibration was loaded, False otherwise
        """
        if self._current_mode == "online":
            matrix = self._calibration_manager.load_calibration(
                "online", self._current_map_provider, self._current_area_id
            )
        else:
            if self._current_local_map:
                matrix = self._calibration_manager.load_calibration(
                    "local", self._current_local_map
                )
            else:
                matrix = None
        
        if matrix:
            self.transform_matrix = matrix
            return True
        self.transform_matrix = None
        return False
    
    def save_calibration_for_current_map(self) -> bool:
        """
        Save current calibration for the current map configuration
        
        Returns:
            True if calibration was saved, False otherwise
        """
        if self._transform_matrix is None:
            return False
        
        if self._current_mode == "online":
            return self._calibration_manager.save_calibration(
                "online", self._current_map_provider,
                self._transform_matrix, self._current_area_id
            )
        else:
            if self._current_local_map:
                return self._calibration_manager.save_calibration(
                    "local", self._current_local_map, self._transform_matrix
                )
        return False
    
    def has_calibration_for_current_map(self) -> bool:
        """Check if calibration exists for current map"""
        if self._current_mode == "online":
            return self._calibration_manager.has_calibration(
                "online", self._current_map_provider, self._current_area_id
            )
        else:
            if self._current_local_map:
                return self._calibration_manager.has_calibration(
                    "local", self._current_local_map
                )
        return False
    
    def get_current_map_identifier(self) -> str:
        """Get a human-readable identifier for the current map"""
        if self._current_mode == "online":
            area_suffix = f" ({self._current_area_id})" if self._current_area_id else ""
            return f"{self._current_map_provider}{area_suffix}"
        else:
            return self._current_local_map or "Unknown"
    
    def reset_auto_calibration_cache(self):
        """Reset auto calibration cache when map changes"""
        self._auto_calibration_cached = False
        self._auto_calibration_matrix = None
