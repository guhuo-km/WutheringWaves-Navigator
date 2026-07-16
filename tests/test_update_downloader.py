import hashlib
import inspect
from pathlib import Path

import pytest

from src.core.update_downloader import (
    UpdateDownloadError,
    prepare_updater_binary,
    stage_file_update,
)


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data
        self.headers = {"content-length": str(len(data))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield self.data

    def json(self):
        raise AssertionError("json() should not be used")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, timeout=30, stream=False):
        self.urls.append((url, timeout, stream))
        return self.responses.pop(0)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_prepare_updater_binary_skips_download_when_hash_matches(tmp_path):
    updater = tmp_path / "WutheringWaves-Updater.exe"
    updater.write_bytes(b"current")
    session = FakeSession([])

    replaced = prepare_updater_binary(
        updater_path=updater,
        updater_url="https://updates.example.com/files/updater",
        updater_sha256=sha256(b"current"),
        staging_dir=tmp_path / ".update",
        session=session,
    )

    assert replaced is False
    assert updater.read_bytes() == b"current"
    assert session.urls == []


def test_prepare_updater_binary_replaces_mismatched_updater(tmp_path):
    updater = tmp_path / "WutheringWaves-Updater.exe"
    updater.write_bytes(b"old")
    session = FakeSession([FakeResponse(b"new-updater")])

    replaced = prepare_updater_binary(
        updater_path=updater,
        updater_url="https://updates.example.com/files/updater",
        updater_sha256=sha256(b"new-updater"),
        staging_dir=tmp_path / ".update",
        session=session,
    )

    assert replaced is True
    assert updater.read_bytes() == b"new-updater"
    assert not (tmp_path / ".update" / "WutheringWaves-Updater.new.exe").exists()
    assert not (tmp_path / ".update" / "WutheringWaves-Updater.backup.exe").exists()


def test_prepare_updater_binary_keeps_root_target_across_interrupted_replace(
    tmp_path,
    monkeypatch,
):
    class SimulatedPowerLoss(BaseException):
        pass

    updater = tmp_path / "WutheringWaves-Updater.exe"
    updater.write_bytes(b"old")
    session = FakeSession([FakeResponse(b"new-updater")])
    original_replace = Path.replace

    def replace_then_interrupt(self, target):
        result = original_replace(self, target)
        raise SimulatedPowerLoss

    monkeypatch.setattr(Path, "replace", replace_then_interrupt)

    with pytest.raises(SimulatedPowerLoss):
        prepare_updater_binary(
            updater_path=updater,
            updater_url="https://updates.example.com/files/updater",
            updater_sha256=sha256(b"new-updater"),
            staging_dir=tmp_path / ".update",
            session=session,
        )

    assert updater.exists()
    assert updater.read_bytes() in {b"old", b"new-updater"}


def test_prepare_updater_binary_preserves_old_file_when_download_hash_is_wrong(tmp_path):
    updater = tmp_path / "WutheringWaves-Updater.exe"
    updater.write_bytes(b"old")
    session = FakeSession([FakeResponse(b"corrupt")])

    with pytest.raises(UpdateDownloadError, match="updater hash mismatch"):
        prepare_updater_binary(
            updater_path=updater,
            updater_url="https://updates.example.com/files/updater",
            updater_sha256=sha256(b"expected"),
            staging_dir=tmp_path / ".update",
            session=session,
        )

    assert updater.read_bytes() == b"old"


def test_prepare_updater_binary_ignores_orphaned_previous_backup(tmp_path):
    updater = tmp_path / "WutheringWaves-Updater.exe"
    staging_dir = tmp_path / ".update"
    backup = staging_dir / "WutheringWaves-Updater.backup.exe"
    updater.write_bytes(b"broken-current")
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"last-known-good")
    session = FakeSession([FakeResponse(b"expected")])

    replaced = prepare_updater_binary(
        updater_path=updater,
        updater_url="https://updates.example.com/files/updater",
        updater_sha256=sha256(b"expected"),
        staging_dir=staging_dir,
        session=session,
    )

    assert replaced is True
    assert updater.read_bytes() == b"expected"
    assert backup.read_bytes() == b"last-known-good"
    assert session.urls == [("https://updates.example.com/files/updater", 30, True)]


def test_stage_file_update_accepts_only_manifest_staging_inputs():
    parameters = inspect.signature(stage_file_update).parameters

    assert "full_zip_url" not in parameters
    assert "full_zip_sha256" not in parameters
    assert parameters["app_root"].default is inspect.Parameter.empty


def test_stage_file_update_does_not_delete_previous_rollback_data(tmp_path):
    version = "0.2.0"
    rollback_file = tmp_path / version / ".rollback" / "replaced" / "app.dll"
    rollback_file.parent.mkdir(parents=True)
    rollback_file.write_bytes(b"backup")
    session = FakeSession([])

    with pytest.raises(UpdateDownloadError, match="previous rollback data exists"):
        stage_file_update(
            version=version,
            manifest_url="https://updates.example.com/manifest.json",
            staging_base=tmp_path,
            app_root=tmp_path / "app",
            session=session,
        )

    assert rollback_file.read_bytes() == b"backup"
    assert session.urls == []


def test_stage_file_update_downloads_only_changed_manifest_files(tmp_path):
    app_root = tmp_path / "app"
    staging_base = tmp_path / "staging"
    app_root.mkdir()
    (app_root / "same.txt").write_bytes(b"same")
    (app_root / "changed.txt").write_bytes(b"old")

    manifest = (
        b'{'
        b'"schema":1,'
        b'"app_id":"wutheringwaves-navigator",'
        b'"version":"0.2.0",'
        b'"channel":"stable",'
        b'"files":['
        b'{"path":"same.txt","size":4,"sha256":"' + sha256(b"same").encode() + b'","url":"portable/files/same.txt","managed":true,"protected":false},'
        b'{"path":"changed.txt","size":3,"sha256":"' + sha256(b"new").encode() + b'","url":"portable/files/changed.txt","managed":true,"protected":false}'
        b'],'
        b'"delete":[]'
        b'}'
    )
    session = FakeSession([FakeResponse(manifest), FakeResponse(b"new")])

    staged = stage_file_update(
        version="0.2.0",
        manifest_url="https://updates.example.com/releases/0.2.0/manifest.json",
        staging_base=staging_base,
        app_root=app_root,
        session=session,
    )

    assert staged.manifest_path.read_bytes() == manifest
    assert not (staged.staging_root / "same.txt").exists()
    assert (staged.staging_root / "changed.txt").read_bytes() == b"new"
    assert session.urls == [
        ("https://updates.example.com/releases/0.2.0/manifest.json", 30, True),
        ("https://updates.example.com/releases/0.2.0/portable/files/changed.txt", 30, True),
    ]


def test_stage_file_update_rejects_invalid_manifest_before_file_download(tmp_path):
    app_root = tmp_path / "app"
    staging_base = tmp_path / "staging"
    user_config = app_root / "config" / "app_settings.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_bytes(b"user")
    digest = sha256(b"remote")
    manifest = (
        b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0",'
        b'"channel":"stable","files":['
        b'{"path":"config/app_settings.json","size":6,"sha256":"'
        + digest.encode()
        + b'","url":"https://updates.example.com/files/config","managed":true,"protected":false}'
        b'],"delete":[]}'
    )
    session = FakeSession([FakeResponse(manifest), FakeResponse(b"remote")])

    with pytest.raises(ValueError, match="path classification"):
        stage_file_update(
            version="0.2.0",
            manifest_url="https://updates.example.com/releases/0.2.0/manifest.json",
            staging_base=staging_base,
            app_root=app_root,
            session=session,
        )

    assert session.urls == [
        ("https://updates.example.com/releases/0.2.0/manifest.json", 30, True)
    ]
    assert user_config.read_bytes() == b"user"


def test_stage_file_update_downloads_hash_pool_url_entries(tmp_path):
    app_root = tmp_path / "app"
    staging_base = tmp_path / "staging"
    app_root.mkdir()
    (app_root / "changed.txt").write_bytes(b"old")
    digest = sha256(b"new")
    file_url = f"HTTPS://updates.example.com/stable/files/{digest}"

    manifest = (
        b'{'
        b'"schema":1,'
        b'"app_id":"wutheringwaves-navigator",'
        b'"version":"0.2.0",'
        b'"channel":"stable",'
        b'"files":['
        b'{"path":"changed.txt","size":3,"sha256":"' + digest.encode() + b'","url":"' + file_url.encode() + b'","managed":true,"protected":false}'
        b'],'
        b'"delete":[]'
        b'}'
    )
    session = FakeSession([FakeResponse(manifest), FakeResponse(b"new")])

    stage_file_update(
        version="0.2.0",
        manifest_url="https://updates.example.com/stable/releases/0.2.0/manifest.json",
        staging_base=staging_base,
        app_root=app_root,
        session=session,
    )

    assert (staging_base / "0.2.0" / "changed.txt").read_bytes() == b"new"
    assert session.urls == [
        ("https://updates.example.com/stable/releases/0.2.0/manifest.json", 30, True),
        (file_url, 30, True),
    ]


def test_stage_file_update_handles_old_directory_replaced_by_file(tmp_path):
    app_root = tmp_path / "app"
    staging_base = tmp_path / "staging"
    old_directory = app_root / "_internal" / "package"
    old_directory.mkdir(parents=True)
    (old_directory / "old.py").write_bytes(b"old")
    digest = sha256(b"new-file")
    manifest = (
        b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0","channel":"stable","files":['
        b'{"path":"_internal/package","size":8,"sha256":"'
        + digest.encode()
        + b'","url":"https://updates.example.com/files/'
        + digest.encode()
        + b'","managed":true,"protected":false}],"delete":[]}'
    )
    session = FakeSession([FakeResponse(manifest), FakeResponse(b"new-file")])

    staged = stage_file_update(
        version="0.2.0",
        manifest_url="https://updates.example.com/releases/0.2.0/manifest.json",
        staging_base=staging_base,
        app_root=app_root,
        session=session,
    )

    assert (staged.staging_root / "_internal" / "package").read_bytes() == b"new-file"
