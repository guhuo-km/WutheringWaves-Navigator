import json
from pathlib import Path

from src.core.version import AppVersionInfo, find_version_file, load_version_info


def test_load_version_info_from_project_root(tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text(
        json.dumps(
            {
                "app_id": "wutheringwaves-navigator",
                "name": "WutheringWaves-Navigator",
                "display_name": "呜呜大地图",
                "version": "1.0.1",
                "channel": "stable",
                "update_base_url": "https://updates.example.com/wuwa-navigator/stable/latest.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    info = load_version_info(tmp_path)

    assert info == AppVersionInfo(
        app_id="wutheringwaves-navigator",
        name="WutheringWaves-Navigator",
        display_name="呜呜大地图",
        version="1.0.1",
        channel="stable",
        update_base_url="https://updates.example.com/wuwa-navigator/stable/latest.json",
    )


def test_load_version_info_uses_safe_defaults_when_file_missing(tmp_path):
    info = load_version_info(tmp_path)

    assert info.app_id == "wutheringwaves-navigator"
    assert info.version == "0.0.0"
    assert info.channel == "stable"


def test_load_version_info_reads_explicit_dist_root(tmp_path):
    (tmp_path / "version.json").write_text(
        json.dumps({"version": "2.3.4", "update_base_url": "https://updates.example.com/latest.json"}),
        encoding="utf-8",
    )

    info = load_version_info(tmp_path)

    assert info.version == "2.3.4"
    assert info.update_base_url == "https://updates.example.com/latest.json"


def test_load_version_info_reads_internal_version_from_explicit_app_root(tmp_path):
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "version.json").write_text(
        json.dumps({"version": "4.5.6", "update_base_url": "https://updates.example.com/latest.json"}),
        encoding="utf-8",
    )

    info = load_version_info(tmp_path)

    assert info.version == "4.5.6"
    assert info.update_base_url == "https://updates.example.com/latest.json"


def test_find_version_file_prefers_internal_version_for_packaged_app_root(tmp_path):
    (tmp_path / "version.json").write_text(
        json.dumps({"version": "3.4.5"}),
        encoding="utf-8",
    )
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "version.json").write_text(
        json.dumps({"version": "4.5.6"}),
        encoding="utf-8",
    )

    assert find_version_file(tmp_path) == internal / "version.json"


def test_repository_version_defaults_are_pre_1_0_and_do_not_embed_update_url():
    info = load_version_info(Path(__file__).resolve().parents[1])

    assert info.version == "0.1.7"
    assert info.update_base_url == ""
