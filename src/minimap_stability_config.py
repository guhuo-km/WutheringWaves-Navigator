from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MinimapStabilityConfig:
    coordinate_agreement_xy_threshold: int = 50
    coordinate_agreement_x_threshold: int = 50
    coordinate_agreement_y_threshold: int = 50
    history_xy_threshold: int = 150
    history_x_threshold: int = 150
    history_y_threshold: int = 150
    auto_roi_lock_tolerance_px: int = 2
    heading_match_confidence_threshold: float = 0.65
    heading_recognition_enabled: bool = True
    rough_candidate_limit: int = 20


def _read_setting(settings, key: str, default):
    try:
        return settings.get(key, default)
    except Exception:
        return default


def load_minimap_stability_config(settings=None) -> MinimapStabilityConfig:
    if settings is None:
        from core.settings_manager import SettingsManager

        settings = SettingsManager()

    defaults = MinimapStabilityConfig()
    prefix = "minimap_stability"
    agreement_xy = int(_read_setting(settings, f"{prefix}.coordinate_agreement_xy_threshold", defaults.coordinate_agreement_xy_threshold))
    history_xy = int(_read_setting(settings, f"{prefix}.history_xy_threshold", defaults.history_xy_threshold))
    return MinimapStabilityConfig(
        coordinate_agreement_xy_threshold=agreement_xy,
        coordinate_agreement_x_threshold=int(_read_setting(settings, f"{prefix}.coordinate_agreement_x_threshold", agreement_xy)),
        coordinate_agreement_y_threshold=int(_read_setting(settings, f"{prefix}.coordinate_agreement_y_threshold", agreement_xy)),
        history_xy_threshold=history_xy,
        history_x_threshold=int(_read_setting(settings, f"{prefix}.history_x_threshold", history_xy)),
        history_y_threshold=int(_read_setting(settings, f"{prefix}.history_y_threshold", history_xy)),
        auto_roi_lock_tolerance_px=int(_read_setting(settings, f"{prefix}.auto_roi_lock_tolerance_px", defaults.auto_roi_lock_tolerance_px)),
        heading_match_confidence_threshold=float(_read_setting(settings, f"{prefix}.heading_match_confidence_threshold", defaults.heading_match_confidence_threshold)),
        heading_recognition_enabled=bool(_read_setting(settings, f"{prefix}.heading_recognition_enabled", defaults.heading_recognition_enabled)),
        rough_candidate_limit=int(_read_setting(settings, f"{prefix}.rough_candidate_limit", defaults.rough_candidate_limit)),
    )
