import json
import os

import pytest

from core.settings_manager import SettingsManager
from core import paths


def _restart_manager(settings_file):
    """Drop the shared in-memory cache so the next construction reloads from disk."""
    SettingsManager._shared_caches.pop(os.path.abspath(str(settings_file)), None)
    return SettingsManager(str(settings_file))


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


def test_default_settings_file_uses_runtime_config(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)
    SettingsManager._shared_caches.clear()

    manager = SettingsManager()

    assert manager.settings_file == str(paths.project_root() / ".runtime" / "config" / "app_settings.json")
    assert "src" not in manager.settings_file.replace("\\", "/").split("/")


@pytest.mark.parametrize("original", [20, 5, 100])
def test_migrate_resets_existing_candidate_limit_to_72_and_flags(tmp_path, original):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps({"minimap_stability": {"rough_candidate_limit": original}}),
        encoding="utf-8",
    )

    manager = SettingsManager(str(settings_file))
    assert manager.migrate_minimap_rough_candidate_limit() is True

    assert manager.get("minimap_stability.rough_candidate_limit") == 72
    assert manager.get("migrations.minimap_rough_candidate_limit_72") is True
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["minimap_stability"]["rough_candidate_limit"] == 72
    assert saved["migrations"]["minimap_rough_candidate_limit_72"] is True


def test_migrate_is_skipped_on_restart_and_preserves_user_value(tmp_path):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps({"minimap_stability": {"rough_candidate_limit": 20}}),
        encoding="utf-8",
    )

    manager = _restart_manager(settings_file)
    assert manager.migrate_minimap_rough_candidate_limit() is True

    # User adjusts the value after the migration has been persisted.
    manager.set("minimap_stability.rough_candidate_limit", 50, save=True)

    restarted = _restart_manager(settings_file)
    assert restarted.migrate_minimap_rough_candidate_limit() is False
    assert restarted.get("minimap_stability.rough_candidate_limit") == 50
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["minimap_stability"]["rough_candidate_limit"] == 50
    assert saved["migrations"]["minimap_rough_candidate_limit_72"] is True


def test_migrate_updates_shared_instance(tmp_path):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps({"minimap_stability": {"rough_candidate_limit": 20}}),
        encoding="utf-8",
    )

    first = SettingsManager(str(settings_file))
    second = SettingsManager(str(settings_file))

    assert first.migrate_minimap_rough_candidate_limit() is True
    assert second.get("minimap_stability.rough_candidate_limit") == 72
    assert second.get("migrations.minimap_rough_candidate_limit_72") is True
    assert second.migrate_minimap_rough_candidate_limit() is False


def test_migrate_on_new_config_sets_72(tmp_path):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(json.dumps({}), encoding="utf-8")

    manager = SettingsManager(str(settings_file))
    assert manager.migrate_minimap_rough_candidate_limit() is True
    assert manager.get("minimap_stability.rough_candidate_limit") == 72
    assert manager.get("migrations.minimap_rough_candidate_limit_72") is True


def test_migrate_is_not_applied_on_load_or_reload(tmp_path):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps({"minimap_stability": {"rough_candidate_limit": 20}}),
        encoding="utf-8",
    )

    manager = SettingsManager(str(settings_file))
    assert manager.get("minimap_stability.rough_candidate_limit") == 20
    assert manager.get("migrations.minimap_rough_candidate_limit_72") is None

    manager.reload()
    assert manager.get("minimap_stability.rough_candidate_limit") == 20
    assert manager.get("migrations.minimap_rough_candidate_limit_72") is None


def test_migrate_save_failure_rolls_back_memory_and_raises(tmp_path, monkeypatch):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps({"minimap_stability": {"rough_candidate_limit": 20}}),
        encoding="utf-8",
    )

    manager = SettingsManager(str(settings_file))
    monkeypatch.setattr(SettingsManager, "_save", lambda self: False)

    with pytest.raises(RuntimeError):
        manager.migrate_minimap_rough_candidate_limit()

    assert manager.get("minimap_stability.rough_candidate_limit") == 20
    assert manager.get("migrations.minimap_rough_candidate_limit_72") is None
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "migrations" not in saved
    assert saved["minimap_stability"]["rough_candidate_limit"] == 20
