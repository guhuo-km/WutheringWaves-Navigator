# -*- coding: utf-8 -*-
"""The opt-in memory sampler stays silent unless WUWA_MEMORY_PROBE is set."""

from __future__ import annotations

import ctypes
import csv
import struct
import time

from core.resource_probe import (
    MEMORY_PROBE_ENV,
    MEM_IMAGE,
    MEM_MAPPED,
    MEM_PRIVATE,
    ResourceProbe,
    _WinApi,
    resolve_memory_probe_path,
)


class _StubSettings:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_probe_path_resolution():
    assert resolve_memory_probe_path("") == ""
    assert resolve_memory_probe_path("0") == ""
    assert resolve_memory_probe_path("off") == ""
    assert resolve_memory_probe_path("1").endswith("memory_probe.log")
    assert resolve_memory_probe_path(r"D:\Temp\trace.log") == r"D:\Temp\trace.log"


def test_sampler_is_off_without_the_environment_variable(monkeypatch):
    monkeypatch.delenv(MEMORY_PROBE_ENV, raising=False)
    probe = ResourceProbe(_StubSettings(), None)
    assert probe.memory_probe_path is None
    assert probe.region_csv_path is None
    assert probe._memory_thread is None
    probe.count("anything")


def test_region_walk_resident_and_commit_are_consistent():
    """Guards the PSAPI_WORKING_SET_EX_BLOCK bit layout used for the Memory column."""
    api = _WinApi()
    assert api.available
    before = api.counters()
    walk = api.walk()
    after = api.counters()

    # The walk and the counter query are separate instants, so the working set
    # moves between them; compare against the larger of the two readings.
    working_set_limit = max(int(before.WorkingSetSize), int(after.WorkingSetSize))
    commit_limit = max(int(before.PrivateUsage), int(after.PrivateUsage))

    assert 0 < walk.private_resident <= walk.total_resident
    assert walk.total_resident <= working_set_limit + 8 * 1024 * 1024
    assert commit_limit > 0

    assert sum(walk.commit_by_key.values()) == sum(walk.type_totals.values())
    # PrivateUsage counts private commit only; the walk also sees DLLs and file mappings.
    private_commit = walk.type_totals.get(MEM_PRIVATE, 0)
    assert abs(private_commit - commit_limit) < 256 * 1024 * 1024
    assert sum(walk.resident_by_key.values()) == walk.private_resident

    for entry in walk.entries:
        assert entry.commit > 0
        assert 0 <= entry.resident <= entry.commit + 1024 * 1024
        assert entry.region_type in (MEM_IMAGE, MEM_MAPPED, MEM_PRIVATE)


def test_modules_and_module_owner_resolve_a_type_pointer():
    """Pointer scanning is what names the module an anonymous block belongs to."""
    api = _WinApi()
    assert api.available
    modules = api.modules()
    assert modules
    assert any(name for _, _, name in modules)

    marker = ["probe"]
    header = ctypes.string_at(id(marker), 16)
    owner = api.module_owner(header, modules)
    assert "python" in owner.lower()
    assert owner.endswith("(1)")


def test_describe_region_identifies_text_and_floats():
    import ctypes as _ctypes

    api = _WinApi()
    assert api.available
    modules = api.modules()

    text = (b'{"hello":"world"} ' * 250)[:4096]
    text_buffer = _ctypes.create_string_buffer(text, 4096)
    text_report = api.describe_region(
        [(_ctypes.addressof(text_buffer), 4096)], 0x04, modules
    )
    assert "ascii=100%" in text_report
    assert "magic=JSON" in text_report

    packed = struct.pack("<1024f", *([1.5] * 1024))
    float_buffer = _ctypes.create_string_buffer(packed, 4096)
    float_report = api.describe_region(
        [(_ctypes.addressof(float_buffer), 4096)], 0x04, modules
    )
    assert "f32[1.5,1.5]" in float_report
    assert "in0..256=100%" in float_report


def test_describe_region_never_faults_on_unreadable_addresses():
    """A bad address must be reported, not raise an access violation."""
    api = _WinApi()
    assert api.available
    report = api.describe_region([(0x1000, 4096)], 0x04, [])
    assert "unreadable" in report
    assert api.describe_region([], 0x04, []) == ""
    assert api.describe_region([(0x1000, 4096)], 0x01, []) == ""


def test_sampler_writes_timeline_and_complete_region_table(tmp_path, monkeypatch):
    report = tmp_path / "nested" / "memory_probe.log"
    monkeypatch.setenv(MEMORY_PROBE_ENV, str(report))
    # One 48 MB private allocation guarantees a region large enough to describe.
    payload = ctypes.create_string_buffer(b"\x5a" * (48 * 1024 * 1024), 48 * 1024 * 1024)
    probe = ResourceProbe(_StubSettings(), None)
    csv_path = tmp_path / "nested" / "memory_probe.log.regions.csv"
    try:
        assert payload
        assert probe.memory_probe_path == str(report)
        assert probe.region_csv_path == str(csv_path)
        assert report.exists()

        text = ""
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            text = report.read_text(encoding="utf-8")
            if "[top 15 regions by resident growth" in text:
                break
            time.sleep(0.2)

        assert "memory probe started" in text
        assert "loaded modules:" in text
        assert "module 0x" in text
        assert "workingset_private_mb=" in text
        assert "workingset_total_mb=" in text
        assert "private_commit_mb=" in text
        assert "resident_delta_mb=" in text
        assert "walk_ms=" in text
        assert "committed_mb: image=" in text
        assert "[top 15 regions by resident growth, then resident size]" in text
        assert "resident=" in text and "commit=" in text
        assert "content:" in text

        deadline = time.monotonic() + 30.0
        rows = []
        while time.monotonic() < deadline:
            if csv_path.exists():
                with csv_path.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                if rows:
                    break
            time.sleep(0.2)

        assert rows
        assert set(rows[0]) == {
            "sample",
            "ts",
            "base",
            "type",
            "protect",
            "commit_mb",
            "resident_mb",
            "label",
        }
        assert all(row["type"] in ("image", "mapped", "private") for row in rows)
    finally:
        probe.stop_memory_sampler()
