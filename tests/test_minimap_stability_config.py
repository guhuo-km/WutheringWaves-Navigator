from minimap_stability_config import (
    MinimapStabilityConfig,
    load_minimap_stability_config,
)


def test_minimap_stability_config_uses_confirmed_defaults():
    config = MinimapStabilityConfig()

    assert config.coordinate_agreement_xy_threshold == 50
    assert config.coordinate_agreement_x_threshold == 50
    assert config.coordinate_agreement_y_threshold == 50
    assert config.history_xy_threshold == 150
    assert config.history_x_threshold == 150
    assert config.history_y_threshold == 150
    assert config.auto_roi_lock_tolerance_px == 2
    assert config.heading_match_confidence_threshold == 0.65
    assert config.heading_recognition_enabled is True
    assert config.rough_candidate_limit == 20


def test_minimap_stability_config_loads_existing_settings_values():
    class FakeSettings:
        values = {
            "minimap_stability.coordinate_agreement_xy_threshold": "41",
            "minimap_stability.coordinate_agreement_x_threshold": "44",
            "minimap_stability.coordinate_agreement_y_threshold": "45",
            "minimap_stability.history_xy_threshold": "120",
            "minimap_stability.history_x_threshold": "121",
            "minimap_stability.history_y_threshold": "122",
            "minimap_stability.auto_roi_lock_tolerance_px": "3",
            "minimap_stability.heading_match_confidence_threshold": "0.7",
            "minimap_stability.heading_recognition_enabled": False,
            "minimap_stability.rough_candidate_limit": "12",
        }

        def get(self, key, default=None):
            return self.values.get(key, default)

    config = load_minimap_stability_config(FakeSettings())

    assert config.coordinate_agreement_xy_threshold == 41
    assert config.coordinate_agreement_x_threshold == 44
    assert config.coordinate_agreement_y_threshold == 45
    assert config.history_xy_threshold == 120
    assert config.history_x_threshold == 121
    assert config.history_y_threshold == 122
    assert config.auto_roi_lock_tolerance_px == 3
    assert config.heading_match_confidence_threshold == 0.7
    assert config.heading_recognition_enabled is False
    assert config.rough_candidate_limit == 12
