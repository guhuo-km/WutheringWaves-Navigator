import json

from core.settings_manager import SettingsManager


def test_settings_managers_for_same_file_share_updates(tmp_path):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "window": {
                    "map_window_geometry": {
                        "x": 238,
                        "y": 36,
                        "width": 630,
                        "height": 580,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    main_window_settings = SettingsManager(str(settings_file))
    settings_page_settings = SettingsManager(str(settings_file))

    settings_page_settings.set("window.remember_map_window_geometry", False, save=True)
    main_window_settings.set(
        "window.map_window_geometry",
        {"x": 680, "y": 595, "width": 630, "height": 580},
        save=True,
    )

    reloaded = SettingsManager(str(settings_file))
    assert reloaded.get("window.remember_map_window_geometry") is False
    assert reloaded.get("window.map_window_geometry.x") == 680
