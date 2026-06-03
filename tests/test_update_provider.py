from src.core.update_provider import HttpUpdateProvider, compare_versions


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.urls = []

    def get(self, url, timeout):
        self.urls.append((url, timeout))
        return FakeResponse(self.data)


def test_compare_versions_keeps_semver_behavior():
    assert compare_versions("1.0.0", "1.0.1") == -1
    assert compare_versions("1.2.0", "1.1.9") == 1
    assert compare_versions("v1.0.0", "1.0.0") == 0


def test_compare_versions_uses_fourth_version_segment():
    assert compare_versions("0.1.6.1", "0.1.6.2") == -1
    assert compare_versions("0.1.6.2", "0.1.6.1") == 1


def test_http_provider_selects_unified_file_artifact():
    session = FakeSession(
        {
            "latest_version": "0.2.0",
            "release_notes": "- ok",
            "artifacts": {
                "windows-x64": {
                    "update_mode": "file",
                    "manifest_url": "https://updates.example.com/manifest.json",
                    "size": 12,
                }
            },
        }
    )
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64",
        session=session,
    )

    result = provider.check("0.1.0")

    assert result.has_update is True
    assert result.latest_version == "0.2.0"
    assert result.release_notes == "- ok"
    assert result.update_mode == "file"
    assert result.manifest_url == "https://updates.example.com/manifest.json"
    assert result.full_zip_url == ""
    assert result.full_zip_sha256 == ""
    assert result.download_url == ""


def test_http_provider_supports_full_update_fallback():
    session = FakeSession(
        {
            "latest_version": "0.3.0",
            "release_notes": "需要全量更新",
            "artifacts": {
                "windows-x64": {
                    "update_mode": "full",
                    "download_url": "https://wuwuddt.com/download",
                    "installer_url": "https://updates.example.com/setup.exe",
                    "size": 300,
                }
            },
        }
    )
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64",
        session=session,
    )

    result = provider.check("0.1.0")

    assert result.has_update is True
    assert result.update_mode == "full"
    assert result.download_url == "https://wuwuddt.com/download"
    assert result.installer_url == "https://updates.example.com/setup.exe"
    assert result.artifact_size == 300


def test_http_provider_full_update_can_use_installer_url_as_download_target():
    session = FakeSession(
        {
            "latest_version": "0.3.0",
            "artifacts": {
                "windows-x64": {
                    "update_mode": "full",
                    "installer_url": "https://updates.example.com/setup.exe",
                    "size": 300,
                }
            },
        }
    )
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64",
        session=session,
    )

    result = provider.check("0.1.0")

    assert result.has_update is True
    assert result.update_mode == "full"
    assert result.download_url == "https://updates.example.com/setup.exe"
    assert result.installer_url == "https://updates.example.com/setup.exe"


def test_http_provider_unknown_update_mode_requires_download_target():
    session = FakeSession(
        {
            "latest_version": "0.2.0",
            "artifacts": {
                "windows-x64": {
                    "update_mode": "typo",
                }
            },
        }
    )
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64",
        session=session,
    )

    result = provider.check("0.1.0")

    assert result.has_update is False
    assert result.update_mode == "download"
    assert result.error_message == "更新产物缺少下载地址"


def test_http_provider_reports_file_update_missing_manifest_url():
    session = FakeSession(
        {
            "latest_version": "0.2.0",
            "artifacts": {
                "windows-x64": {
                    "update_mode": "file",
                    "size": 12,
                }
            },
        }
    )
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64",
        session=session,
    )

    result = provider.check("0.1.0")

    assert result.has_update is False
    assert "缺少文件更新清单地址" in result.error_message


def test_http_provider_returns_no_update_for_same_version():
    session = FakeSession({"latest_version": "1.0.1", "artifacts": {}})
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64-portable",
        session=session,
    )

    result = provider.check("1.0.1")

    assert result.has_update is False


def test_http_provider_reports_missing_artifact_for_new_version():
    session = FakeSession({"latest_version": "1.0.2", "artifacts": {}})
    provider = HttpUpdateProvider(
        latest_url="https://updates.example.com/latest.json",
        artifact_key="windows-x64-portable",
        session=session,
    )

    result = provider.check("1.0.1")

    assert result.has_update is False
    assert "未找到更新产物" in result.error_message


def test_http_provider_reports_empty_latest_url():
    provider = HttpUpdateProvider(latest_url="", artifact_key="windows-x64-portable")

    result = provider.check("1.0.1")

    assert result.has_update is False
    assert result.error_message == "更新地址未配置"
