import importlib
import json
import sys


def test_language_manager_defaults_to_chinese_when_user_config_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("_PYI_APPLICATION_HOME_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    import src.language_manager as language_manager

    importlib.reload(language_manager)
    monkeypatch.setattr(
        language_manager.LanguageManager,
        "_resolve_runtime_root",
        lambda self: str(tmp_path),
    )
    manager = language_manager.LanguageManager()

    assert manager.get_current_language() == "zh_CN"
    assert manager.config_file == str(tmp_path / "config" / "language_config.json")


def test_language_manager_does_not_create_static_language_dir(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    static_root = tmp_path / "missing_static"
    created_dirs = []

    monkeypatch.delenv("_PYI_APPLICATION_HOME_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    import src.language_manager as language_manager

    importlib.reload(language_manager)
    monkeypatch.setattr(
        language_manager.LanguageManager,
        "_resolve_runtime_root",
        lambda self: str(runtime_root),
    )
    monkeypatch.setattr(
        language_manager.LanguageManager,
        "_resolve_resource_root",
        lambda self: str(static_root),
    )
    monkeypatch.setattr(
        language_manager.os,
        "makedirs",
        lambda path, *args, **kwargs: created_dirs.append(str(path)),
    )

    language_manager.LanguageManager()

    assert str(static_root / "languages") not in created_dirs


def test_language_manager_uses_app_root_config_when_frozen(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    internal_root = app_root / "_internal"
    app_root.mkdir()
    internal_root.mkdir()
    config_dir = app_root / "config"
    config_dir.mkdir()
    (config_dir / "language_config.json").write_text(
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

    assert manager.config_file == str(config_dir / "language_config.json")
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
