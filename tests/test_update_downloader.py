import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest

from src.core.update_downloader import UpdateDownloadError, stage_file_update


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


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_stage_file_update_downloads_verifies_and_extracts(tmp_path):
    manifest = b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0","channel":"stable","files":[],"delete":[]}'
    zip_data = make_zip({"WutheringWaves-Navigator-Smart.exe": b"new"})
    session = FakeSession([FakeResponse(manifest), FakeResponse(zip_data)])

    staged = stage_file_update(
        version="0.2.0",
        manifest_url="https://updates.example.com/manifest.json",
        full_zip_url="https://updates.example.com/full.zip",
        full_zip_sha256=sha256(zip_data),
        staging_base=tmp_path,
        session=session,
    )

    assert staged.version == "0.2.0"
    assert staged.manifest_path.read_bytes() == manifest
    assert (staged.staging_root / "WutheringWaves-Navigator-Smart.exe").read_bytes() == b"new"


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
        full_zip_url="https://updates.example.com/releases/0.2.0/full.zip",
        full_zip_sha256=sha256(b"not-used"),
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


def test_stage_file_update_downloads_hash_pool_url_entries(tmp_path):
    app_root = tmp_path / "app"
    staging_base = tmp_path / "staging"
    app_root.mkdir()
    (app_root / "changed.txt").write_bytes(b"old")
    digest = sha256(b"new")
    file_url = f"https://updates.example.com/stable/files/{digest}"

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
        full_zip_url="",
        staging_base=staging_base,
        app_root=app_root,
        session=session,
    )

    assert (staging_base / "0.2.0" / "changed.txt").read_bytes() == b"new"
    assert session.urls == [
        ("https://updates.example.com/stable/releases/0.2.0/manifest.json", 30, True),
        (file_url, 30, True),
    ]


def test_stage_file_update_rejects_missing_zip_hash(tmp_path):
    manifest = b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0","channel":"stable","files":[],"delete":[]}'
    zip_data = make_zip({"a.txt": b"new"})
    session = FakeSession([FakeResponse(manifest), FakeResponse(zip_data)])

    with pytest.raises(UpdateDownloadError, match="missing package hash"):
        stage_file_update(
            version="0.2.0",
            manifest_url="https://updates.example.com/manifest.json",
            full_zip_url="https://updates.example.com/full.zip",
            staging_base=tmp_path,
            session=session,
        )

    assert session.urls == []


def test_stage_file_update_rejects_bad_zip_hash(tmp_path):
    manifest = b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0","channel":"stable","files":[],"delete":[]}'
    zip_data = make_zip({"a.txt": b"new"})
    session = FakeSession([FakeResponse(manifest), FakeResponse(zip_data)])

    with pytest.raises(UpdateDownloadError, match="hash mismatch"):
        stage_file_update(
            version="0.2.0",
            manifest_url="https://updates.example.com/manifest.json",
            full_zip_url="https://updates.example.com/full.zip",
            full_zip_sha256="0" * 64,
            staging_base=tmp_path,
            session=session,
        )


def test_stage_file_update_rejects_unsafe_version_path_without_touching_outside(tmp_path):
    staging_base = tmp_path / "staging"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    session = FakeSession([])

    with pytest.raises(UpdateDownloadError, match="unsafe version path"):
        stage_file_update(
            version="../outside",
            manifest_url="https://updates.example.com/manifest.json",
            full_zip_url="https://updates.example.com/full.zip",
            full_zip_sha256="a" * 64,
            staging_base=staging_base,
            session=session,
        )

    assert sentinel.read_text(encoding="utf-8") == "do not delete"
    assert not (outside / "manifest.json").exists()
    assert session.urls == []


def test_stage_file_update_rejects_zip_path_traversal(tmp_path):
    manifest = b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0","channel":"stable","files":[],"delete":[]}'
    zip_data = make_zip({"../escape.txt": b"bad"})
    session = FakeSession([FakeResponse(manifest), FakeResponse(zip_data)])

    with pytest.raises(UpdateDownloadError, match="unsafe zip path"):
        stage_file_update(
            version="0.2.0",
            manifest_url="https://updates.example.com/manifest.json",
            full_zip_url="https://updates.example.com/full.zip",
            full_zip_sha256=sha256(zip_data),
            staging_base=tmp_path,
            session=session,
        )


def test_stage_file_update_cleans_partial_extract_after_late_zip_path_traversal(tmp_path):
    manifest = b'{"schema":1,"app_id":"wutheringwaves-navigator","version":"0.2.0","channel":"stable","files":[],"delete":[]}'
    zip_data = make_zip({"safe.txt": b"partial", "../escape.txt": b"bad"})
    session = FakeSession([FakeResponse(manifest), FakeResponse(zip_data)])

    with pytest.raises(UpdateDownloadError, match="unsafe zip path"):
        stage_file_update(
            version="0.2.0",
            manifest_url="https://updates.example.com/manifest.json",
            full_zip_url="https://updates.example.com/full.zip",
            full_zip_sha256=sha256(zip_data),
            staging_base=tmp_path,
            session=session,
        )

    assert not (tmp_path / "0.2.0" / "safe.txt").exists()
    assert not (tmp_path / "0.2.0").exists()
