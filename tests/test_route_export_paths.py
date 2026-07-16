from pathlib import Path

from core.route_export_paths import (
    ROUTE_EXPORT_DIRECTORY_KEY,
    is_route_export_download,
    resolve_route_export_directory,
)


class FakeSettings:
    def __init__(self, value=""):
        self.value = value

    def get(self, key, default=None):
        assert key == ROUTE_EXPORT_DIRECTORY_KEY
        return self.value or default


def test_route_export_directory_uses_configured_path(tmp_path):
    target = tmp_path / "custom-routes"

    resolved = resolve_route_export_directory(FakeSettings(str(target)))

    assert resolved == target
    assert target.is_dir()


def test_route_export_directory_uses_system_downloads_without_override(monkeypatch, tmp_path):
    downloads = tmp_path / "Downloads"
    monkeypatch.setattr(
        "core.route_export_paths.QStandardPaths.writableLocation",
        lambda _location: str(downloads),
    )

    resolved = resolve_route_export_directory(FakeSettings())

    assert resolved == downloads
    assert downloads.is_dir()


def test_only_generated_route_files_use_route_export_directory():
    assert is_route_export_download("blob:https://map.example/id", "route.json")
    assert is_route_export_download("data:text/json;charset=utf-8,%7B%7D", "route.json")
    assert is_route_export_download("blob:https://map.example/id", "route.svg")
    assert is_route_export_download("blob:https://map.example/id", "routes_20260714.zip")

    assert not is_route_export_download("https://example.com/file.json", "file.json")
    assert not is_route_export_download("blob:https://map.example/id", "screenshot.png")


def test_main_window_routes_generated_exports_without_affecting_http_downloads(tmp_path):
    from ui.main_window import MainWindow

    normal_downloads = tmp_path / "normal"
    route_downloads = tmp_path / "routes"

    class Harness:
        _settings = FakeSettings(str(route_downloads))
        _sanitize_filename = MainWindow._sanitize_filename
        _ensure_unique_path = MainWindow._ensure_unique_path

        def _get_download_dir(self):
            normal_downloads.mkdir(parents=True, exist_ok=True)
            return str(normal_downloads)

    class DownloadItem:
        def __init__(self, filename):
            self.filename = filename

        def downloadFileName(self):
            return self.filename

    harness = Harness()

    route_target = MainWindow._build_download_target_path(
        harness,
        "blob:https://map.example/id",
        DownloadItem("route.json"),
    )
    normal_target = MainWindow._build_download_target_path(
        harness,
        "https://example.com/file.json",
        DownloadItem("file.json"),
    )

    assert Path(route_target).parent == route_downloads
    assert Path(normal_target).parent == normal_downloads


def test_route_export_ui_and_python_dialogs_use_shared_directory_setting():
    project_root = Path(__file__).resolve().parents[1]
    ui_text = (project_root / "src" / "ui" / "interfaces" / "route_settings_interface.py").read_text(
        encoding="utf-8"
    )
    main_window_text = (project_root / "src" / "ui" / "main_window.py").read_text(encoding="utf-8")
    recorder_text = (project_root / "src" / "route_recorder.py").read_text(encoding="utf-8")

    assert 'self._settings.set(ROUTE_EXPORT_DIRECTORY_KEY, folder)' in ui_text
    assert 'self._settings.delete(ROUTE_EXPORT_DIRECTORY_KEY)' in ui_text
    assert "resolve_route_export_directory(self._settings)" in main_window_text
    assert "resolve_route_export_directory()" in recorder_text
