import importlib
import json
import sys


def test_language_manager_defaults_to_chinese_when_user_config_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("_PYI_APPLICATION_HOME_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    import src.language_manager as language_manager

    importlib.reload(language_manager)
    monkeypatch.setattr(
        language_manager.LanguageManager,
        "_resolve_app_root",
        lambda self: str(tmp_path),
    )
    manager = language_manager.LanguageManager()

    assert manager.get_current_language() == "zh_CN"
    assert manager.config_file == str(tmp_path / "language_config.json")


def test_language_manager_uses_app_root_config_when_frozen(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    internal_root = app_root / "_internal"
    app_root.mkdir()
    internal_root.mkdir()
    (app_root / "language_config.json").write_text(
        json.dumps({"current_language": "en_US"}),
        encoding="utf-8",
    )
    (internal_root / "language_config.json").write_text(
        json.dumps({"current_language": "zh_CN"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_root / "WutheringWaves-Navigator-Smart.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal_root), raising=False)

    import src.language_manager as language_manager

    importlib.reload(language_manager)
    manager = language_manager.LanguageManager()

    assert manager.config_file == str(app_root / "language_config.json")
    assert manager.get_current_language() == "en_US"


def test_language_manager_loads_frozen_internal_language_files(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    internal_lang = app_root / "_internal" / "languages"
    internal_lang.mkdir(parents=True)
    (internal_lang / "zh_CN.json").write_text(
        json.dumps({"settings_language": "语言设置"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (internal_lang / "en_US.json").write_text(
        json.dumps({"settings_language": "Language Settings"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_root / "WutheringWaves-Navigator-Smart.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(app_root / "_internal"), raising=False)

    import src.language_manager as language_manager

    importlib.reload(language_manager)
    manager = language_manager.LanguageManager()
    manager.set_language("en_US")

    assert manager.lang_dir == str(internal_lang)
    assert manager.tr("settings_language") == "Language Settings"
