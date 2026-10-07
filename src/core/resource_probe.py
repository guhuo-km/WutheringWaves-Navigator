# -*- coding: utf-8 -*-
"""
Opt-in runtime counters for investigating high CPU reports.

This module is intentionally passive by default. The counter aggregator is
enabled only when settings key ``diagnostics.resource_probe_enabled`` is true.

The memory sampler is independent of that setting. It runs only when the
environment variable ``WUWA_MEMORY_PROBE`` is set, and it uses nothing but
cheap process queries: ``GetProcessMemoryInfo``, ``VirtualQueryEx``,
``QueryWorkingSetEx``, ``GetMappedFileNameW`` and ``EnumProcessModules``. It
never enables ``tracemalloc`` and never walks live Python objects, so it adds no
per allocation cost.

Two report files are written next to each other:

* ``<WUWA_MEMORY_PROBE>`` - the human readable timeline. Every sample records
  the working-set and commit totals, the committed bytes per region type, the
  largest regions by resident growth, and the content of the fastest growing
  anonymous blocks.
* ``<WUWA_MEMORY_PROBE>.regions.csv`` - the complete per-region table of every
  region holding at least ``REGION_CSV_MIN_RESIDENT`` resident bytes. Nothing is
  truncated here, so a growing region cannot be missed by the top-N list.

Concepts, because the two counters answer different questions and grow
independently:

* ``resident`` - memory currently held in physical RAM. This is the value Task
  Manager shows in its Memory column.
* ``commit`` - address space already committed. This is Task Manager's Commit
  size column. A committed block can stay non-resident for a long time and then
  become resident later without any change in the commit total.
"""

from __future__ import annotations

import bisect
import csv
import ctypes
import os
import struct
import sys
import threading
import time
from collections import Counter
from ctypes import wintypes as w
from time import monotonic
from typing import Any, Dict, List, Optional, Tuple

from . import paths
from .settings_manager import SettingsManager

MEMORY_PROBE_ENV = "WUWA_MEMORY_PROBE"
MEMORY_SAMPLE_INTERVAL_S = 5.0
TOP_REGIONS = 15
DESCRIBED_REGIONS = 3
CONTENT_PAGES = 6
REGION_CSV_MIN_RESIDENT = 1024 * 1024
PAGE_SIZE = 0x1000
MAX_MODULES = 1024
_ON_VALUES = ("1", "true", "yes", "on")
_OFF_VALUES = ("", "0", "false", "no", "off")

MEM_COMMIT = 0x1000
MEM_IMAGE = 0x1000000
MEM_MAPPED = 0x40000
MEM_PRIVATE = 0x20000
_TYPE_NAMES = {MEM_IMAGE: "image", MEM_MAPPED: "mapped", MEM_PRIVATE: "private"}

_PROTECT_FLAGS = (
    (0x01, "NOACCESS"),
    (0x02, "R"),
    (0x04, "RW"),
    (0x08, "WC"),
    (0x10, "X"),
    (0x20, "RX"),
    (0x40, "RWX"),
    (0x80, "WCX"),
)

_WS_EX_VALID_BIT = 0
_WS_EX_SHARED_BIT = 15

_MAGIC = (
    (b"\x89PNG\r\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"PK\x03\x04", "ZIP/NPZ"),
    (b"SQLite f", "sqlite"),
    (b"\x93NUMPY", "NPY"),
    (b"\x1f\x8b\x08", "gzip"),
    (b"{\"", "JSON"),
    (b"[{", "JSON"),
    (b"\x00\x00\x00\x00\x00\x00\x00\x00", "zeros"),
)


def resolve_memory_probe_path(raw: Optional[str] = None) -> str:
    """Return the report path for ``WUWA_MEMORY_PROBE``, or "" when disabled.

    Bare switch values ("1", "true", ...) select the default path next to the
    session logs; any other value is used as the report path itself.
    """
    value = (os.environ.get(MEMORY_PROBE_ENV, "") if raw is None else raw) or ""
    value = value.strip()
    lowered = value.lower()
    if lowered in _OFF_VALUES:
        return ""
    if lowered in _ON_VALUES:
        return os.path.join(str(paths.log_dir()), "memory_probe.log")
    return value


def _protect_name(protect: int) -> str:
    base = protect & 0xFF
    for flag, name in _PROTECT_FLAGS:
        if base == flag:
            return name
    return f"0x{base:02X}"


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("PageFaultCount", w.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", w.DWORD),
        ("__alignment1", w.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", w.DWORD),
        ("Protect", w.DWORD),
        ("Type", w.DWORD),
        ("__alignment2", w.DWORD),
    ]


class _WorkingSetExBlock(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_size_t)]


class _WorkingSetExInformation(ctypes.Structure):
    _fields_ = [
        ("VirtualAddress", ctypes.c_void_p),
        ("VirtualAttributes", _WorkingSetExBlock),
    ]


class _ModuleInfo(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", w.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]


class _RegionEntry:
    __slots__ = ("base", "region_type", "protect", "commit", "resident", "label", "extents")

    def __init__(
        self,
        base: int,
        region_type: int,
        protect: int,
        commit: int,
        resident: int,
        label: str,
        extents: Optional[List[Tuple[int, int]]] = None,
    ):
        self.base = base
        self.region_type = region_type
        self.protect = protect
        self.commit = commit
        self.resident = resident
        self.label = label
        # The committed sub-ranges of this allocation base. Reading anything
        # outside them is uncommitted address space.
        self.extents = extents or []


class _RegionWalk:
    def __init__(
        self,
        type_totals: Dict[int, int],
        commit_by_key: Dict[Any, int],
        resident_by_key: Dict[Any, int],
        entries: List[_RegionEntry],
        private_resident: int,
        total_resident: int,
    ) -> None:
        self.type_totals = type_totals
        self.commit_by_key = commit_by_key
        self.resident_by_key = resident_by_key
        self.entries = entries
        self.private_resident = private_resident
        self.total_resident = total_resident


class _WinApi:
    """Thin ctypes wrapper; all calls are process queries on the current process."""

    def __init__(self) -> None:
        self.available = False
        self._kernel32 = None
        self._query_memory = None
        self._query_working_set = None
        self._mapped_name = None
        self._enum_modules = None
        self._module_info = None
        self._module_name = None
        self._read_process = None
        self._handle = None
        if sys.platform != "win32":
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # The pseudo-handle is 64-bit; without an explicit restype ctypes truncates
            # it to 32 bits and every process query fails.
            kernel32.GetCurrentProcess.restype = w.HANDLE
            kernel32.GetCurrentProcess.argtypes = []
            kernel32.VirtualQueryEx.restype = ctypes.c_size_t
            kernel32.VirtualQueryEx.argtypes = [
                w.HANDLE,
                ctypes.c_void_p,
                ctypes.POINTER(_MemoryBasicInformation),
                ctypes.c_size_t,
            ]

            caller = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = None
            for name in ("kernel32", "psapi"):
                try:
                    psapi = ctypes.WinDLL(name, use_last_error=True)
                    break
                except OSError:
                    continue

            query_memory = self._bind(caller, psapi, "GetProcessMemoryInfo", "K32GetProcessMemoryInfo")
            if query_memory is None:
                return
            query_memory.restype = w.BOOL
            query_memory.argtypes = [w.HANDLE, ctypes.POINTER(_ProcessMemoryCountersEx), w.DWORD]

            query_working_set = self._bind(
                caller, psapi, "QueryWorkingSetEx", "K32QueryWorkingSetEx"
            )
            if query_working_set is not None:
                query_working_set.restype = w.BOOL
                query_working_set.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]

            mapped_name = self._bind(caller, psapi, "GetMappedFileNameW", "K32GetMappedFileNameW")
            if mapped_name is not None:
                mapped_name.restype = w.DWORD
                mapped_name.argtypes = [w.HANDLE, ctypes.c_void_p, w.LPWSTR, w.DWORD]

            enum_modules = self._bind(
                caller, psapi, "EnumProcessModules", "K32EnumProcessModules"
            )
            if enum_modules is not None:
                enum_modules.restype = w.BOOL
                enum_modules.argtypes = [
                    w.HANDLE,
                    ctypes.POINTER(w.HMODULE),
                    w.DWORD,
                    ctypes.POINTER(w.DWORD),
                ]

            module_info = self._bind(
                caller, psapi, "GetModuleInformation", "K32GetModuleInformation"
            )
            if module_info is not None:
                module_info.restype = w.BOOL
                module_info.argtypes = [
                    w.HANDLE,
                    w.HMODULE,
                    ctypes.POINTER(_ModuleInfo),
                    w.DWORD,
                ]

            module_name = self._bind(
                caller, psapi, "GetModuleFileNameExW", "K32GetModuleFileNameExW"
            )
            if module_name is not None:
                module_name.restype = w.DWORD
                module_name.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]

            # ReadProcessMemory fails cleanly on an invalid address; ctypes.string_at
            # raises an access violation and kills the process.
            read_process = getattr(kernel32, "ReadProcessMemory", None)
            if read_process is not None:
                read_process.restype = w.BOOL
                read_process.argtypes = [
                    w.HANDLE,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_size_t),
                ]

            self._kernel32 = kernel32
            self._query_memory = query_memory
            self._query_working_set = query_working_set
            self._mapped_name = mapped_name
            self._enum_modules = enum_modules
            self._module_info = module_info
            self._module_name = module_name
            self._read_process = read_process
            self._handle = kernel32.GetCurrentProcess()
            self.available = True
        except Exception:
            self.available = False

    @staticmethod
    def _bind(primary, secondary, plain: str, prefixed: str):
        for dll in (primary, secondary):
            if dll is None:
                continue
            for symbol in (prefixed, plain):
                try:
                    return getattr(dll, symbol)
                except (OSError, AttributeError):
                    continue
        return None

    def counters(self) -> Optional[_ProcessMemoryCountersEx]:
        if not self.available:
            return None
        counters = _ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        if not self._query_memory(self._handle, ctypes.byref(counters), counters.cb):
            return None
        return counters

    def modules(self) -> List[Tuple[int, int, str]]:
        """Return loaded modules as (start address, end address, file name)."""
        if not self.available or self._enum_modules is None or self._module_info is None:
            return []
        needed = w.DWORD(0)
        handle_array = (w.HMODULE * MAX_MODULES)()
        if not self._enum_modules(
            self._handle, handle_array, ctypes.sizeof(handle_array), ctypes.byref(needed)
        ):
            return []
        count = min(needed.value // ctypes.sizeof(w.HMODULE), MAX_MODULES)
        buffer = ctypes.create_unicode_buffer(1024)
        result: List[Tuple[int, int, str]] = []
        for index in range(count):
            info = _ModuleInfo()
            if not self._module_info(
                self._handle, handle_array[index], ctypes.byref(info), ctypes.sizeof(info)
            ):
                continue
            start = int(info.lpBaseOfDll or 0)
            end = start + int(info.SizeOfImage)
            name = ""
            if self._module_name is not None:
                if self._module_name(self._handle, handle_array[index], buffer, 1024):
                    name = os.path.basename(buffer.value)
            if start and end > start:
                result.append((start, end, name))
        result.sort()
        return result

    def module_owner(self, raw: bytes, modules: List[Tuple[int, int, str]]) -> str:
        """Return which module the pointers inside ``raw`` point into, with counts."""
        if not modules or len(raw) < 8:
            return ""
        starts = [item[0] for item in modules]
        counts: Counter = Counter()
        words = struct.unpack(f"<{len(raw) // 8}Q", raw[: (len(raw) // 8) * 8])
        for word in words:
            if word < 0x10000:
                continue
            position = bisect.bisect_right(starts, word) - 1
            if position < 0:
                continue
            start, end, name = modules[position]
            if start <= word < end and name:
                counts[name] += 1
        if not counts:
            return ""
        name, hits = counts.most_common(1)[0]
        return f"{name}({hits})"

    def _read(self, address: int, size: int) -> Optional[bytes]:
        """Read committed process memory; returns None instead of faulting."""
        if not self.available or self._read_process is None or address <= 0 or size <= 0:
            return None
        buffer = ctypes.create_string_buffer(size)
        transferred = ctypes.c_size_t(0)
        ok = self._read_process(
            self._handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(transferred)
        )
        if not ok or transferred.value != size:
            return None
        return buffer.raw

    def describe_region(
        self,
        extents: List[Tuple[int, int]],
        protect: int = 0,
        modules: Optional[List[Tuple[int, int, str]]] = None,
    ) -> str:
        """Sample a few committed pages of a region and describe their content."""
        if not self.available or not extents:
            return ""
        if (protect & 0xFF) == 0x01:  # PAGE_NOACCESS
            return ""
        modules = modules or []

        candidates: List[int] = []
        for address, size in extents:
            pages = max(1, size // PAGE_SIZE)
            # Spread the samples across the whole extent: the first pages are
            # often still untouched while the payload sits further in.
            step = max(1, pages // CONTENT_PAGES)
            for index in range(0, pages, step):
                candidates.append(address + index * PAGE_SIZE)
                if len(candidates) >= CONTENT_PAGES:
                    break
            if len(candidates) >= CONTENT_PAGES:
                break

        parts: List[str] = []
        for index, address in enumerate(candidates):
            raw = self._read(address, PAGE_SIZE)
            if raw is None:
                parts.append(f"p{index}=unreadable")
                continue
            printable = sum(1 for byte in raw if 32 <= byte < 127 or byte in (9, 10, 13)) / len(raw)
            zeros = raw.count(0) / len(raw)
            magic = next((value for prefix, value in _MAGIC if raw.startswith(prefix)), "")
            pieces = [
                f"p{index}",
                f"head={raw[:12].hex(' ')}",
                f"ascii={printable:.0%}",
                f"zero={zeros:.0%}",
            ]
            if magic:
                pieces.append(f"magic={magic}")
            try:
                floats = struct.unpack("<1024f", raw)
                finite = [value for value in floats if value == value and abs(value) < 1e30]
                if finite:
                    in_range = sum(1 for value in finite if 0.0 <= value <= 256.0) / len(finite)
                    pieces.append(
                        f"f32[{min(finite):.4g},{max(finite):.4g}] in0..256={in_range:.0%}"
                    )
            except Exception:
                pieces.append("f32=unreadable")
            owner = self.module_owner(raw, modules)
            if owner:
                pieces.append(f"points_into={owner}")
            parts.append(" ".join(pieces))
        return " | ".join(parts)

    def walk(self) -> _RegionWalk:
        """Enumerate committed regions and measure how much of each is resident."""
        type_totals: Dict[int, int] = {}
        commit_by_key: Dict[Any, int] = {}
        resident_by_key: Dict[Any, int] = {}
        protect_by_key: Dict[Any, int] = {}
        extents_by_key: Dict[Any, List[Tuple[int, int]]] = {}
        pages: List[Tuple[Any, int, int]] = []
        if not self.available:
            return _RegionWalk(type_totals, commit_by_key, resident_by_key, [], 0, 0)

        info = _MemoryBasicInformation()
        buffer = ctypes.create_unicode_buffer(1024)
        address = 0
        limit = 0x7FFFFFFFFFFF
        while address < limit:
            got = self._kernel32.VirtualQueryEx(
                self._handle, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)
            )
            if not got:
                break
            size = int(info.RegionSize) or PAGE_SIZE
            if info.State == MEM_COMMIT:
                region_type = info.Type
                type_totals[region_type] = type_totals.get(region_type, 0) + size
                allocation_base = int(info.AllocationBase or 0) or address
                label = ""
                if self._mapped_name is not None and (
                    region_type == MEM_IMAGE
                    or (region_type == MEM_MAPPED and size >= 8 * 1024 * 1024)
                ):
                    if self._mapped_name(self._handle, ctypes.c_void_p(address), buffer, 1024):
                        label = buffer.value
                key = (allocation_base, region_type, label)
                commit_by_key[key] = commit_by_key.get(key, 0) + size
                protect_by_key.setdefault(key, int(info.Protect))
                extents_by_key.setdefault(key, []).append((address, size))
                pages.append((key, address, (size + PAGE_SIZE - 1) // PAGE_SIZE))
            address += size

        private_resident, total_resident = self._measure_resident(pages, resident_by_key)
        entries = [
            _RegionEntry(
                key[0],
                key[1],
                protect_by_key.get(key, 0),
                commit,
                resident_by_key.get(key, 0),
                key[2],
                extents_by_key.get(key, []),
            )
            for key, commit in commit_by_key.items()
        ]
        return _RegionWalk(
            type_totals, commit_by_key, resident_by_key, entries, private_resident, total_resident
        )

    def _measure_resident(
        self, pages: List[Tuple[Any, int, int]], resident_by_key: Dict[Any, int]
    ) -> Tuple[int, int]:
        if not pages or self._query_working_set is None:
            return 0, 0
        total_pages = sum(count for _, _, count in pages)
        if total_pages <= 0:
            return 0, 0
        array = (_WorkingSetExInformation * total_pages)()
        per_key_private: Dict[Any, int] = {}
        private_pages = 0
        total_resident_pages = 0
        try:
            import numpy as np

            raw = np.frombuffer(array, dtype=np.uint64).reshape(-1, 2)
            counts = np.empty(len(pages), dtype=np.int64)
            offset = 0
            for index, (_, base, count) in enumerate(pages):
                counts[index] = count
                raw[offset : offset + count, 0] = np.arange(
                    base, base + count * PAGE_SIZE, PAGE_SIZE, dtype=np.uint64
                )
                offset += count
            if not self._query_working_set(self._handle, ctypes.byref(array), ctypes.sizeof(array)):
                return 0, 0
            flags = raw[:, 1]
            valid = (flags & 1) != 0
            private = valid & (((flags >> _WS_EX_SHARED_BIT) & 1) == 0)
            starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
            per_region_private = np.add.reduceat(private.astype(np.int64), starts)
            per_region_total = np.add.reduceat(valid.astype(np.int64), starts)
            private_pages = int(per_region_private.sum())
            total_resident_pages = int(per_region_total.sum())
            for index, (key, _, _) in enumerate(pages):
                per_key_private[key] = per_key_private.get(key, 0) + int(per_region_private[index])
        except Exception:
            index = 0
            for key, base, count in pages:
                for page in range(base, base + count * PAGE_SIZE, PAGE_SIZE):
                    array[index].VirtualAddress = page
                    index += 1
            if not self._query_working_set(self._handle, ctypes.byref(array), ctypes.sizeof(array)):
                return 0, 0
            index = 0
            for key, _, count in pages:
                for _ in range(count):
                    flag = int(array[index].VirtualAttributes.flags)
                    if flag & (1 << _WS_EX_VALID_BIT):
                        total_resident_pages += 1
                        if not (flag >> _WS_EX_SHARED_BIT) & 1:
                            private_pages += 1
                            per_key_private[key] = per_key_private.get(key, 0) + 1
                    index += 1
        for key, count in per_key_private.items():
            resident_by_key[key] = count * PAGE_SIZE
        return private_pages * PAGE_SIZE, total_resident_pages * PAGE_SIZE


class ResourceProbe:
    """Small in-process counter aggregator and opt-in memory sampler for temporary diagnostics."""

    def __init__(self, settings: Optional[SettingsManager] = None, log_manager=None):
        self._settings = settings or SettingsManager()
        self._log_manager = log_manager
        self._enabled = bool(self._settings.get("diagnostics.resource_probe_enabled", False))
        self._interval_s = max(10.0, float(self._settings.get("diagnostics.resource_probe_interval_s", 60)))
        self._counters = Counter()
        self._last_flush = monotonic()

        self._memory_path = resolve_memory_probe_path()
        self._memory_thread: Optional[threading.Thread] = None
        self._memory_stop = threading.Event()
        self._memory_samples = 0
        self._modules: List[Tuple[int, int, str]] = []
        self._csv_path = f"{self._memory_path}.regions.csv" if self._memory_path else ""
        if self._memory_path:
            self._start_memory_sampler()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def memory_probe_path(self) -> Optional[str]:
        """Report path of the memory sampler, or None when it is disabled."""
        return self._memory_path or None

    @property
    def region_csv_path(self) -> Optional[str]:
        """Complete per-region table path, or None when the sampler is disabled."""
        return self._csv_path or None

    def count(self, name: str, amount: int = 1) -> None:
        if not self._enabled:
            return
        self._counters[str(name)] += int(amount)
        self.flush_if_due()

    def flush_if_due(self) -> None:
        if not self._enabled:
            return
        now = monotonic()
        if now - self._last_flush < self._interval_s:
            return
        self.flush()

    def flush(self) -> None:
        if not self._enabled:
            return
        now = monotonic()
        elapsed = max(0.001, now - self._last_flush)
        parts = [
            f"{key}={value} ({value / elapsed:.2f}/s)"
            for key, value in sorted(self._counters.items())
        ]
        line = f"[RESOURCE_PROBE] interval={elapsed:.1f}s " + ("; ".join(parts) if parts else "no events")
        if self._log_manager:
            try:
                self._log_manager.enqueue("debug", line)
            except Exception:
                pass
        else:
            print(line)
        self._counters.clear()
        self._last_flush = now

    def stop_memory_sampler(self) -> None:
        """Ask the memory sampler thread to stop after its current sample."""
        self._memory_stop.set()

    def _start_memory_sampler(self) -> None:
        directory = os.path.dirname(self._memory_path)
        if directory:
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError:
                pass
        api = _WinApi()
        self._modules = api.modules() if api.available else []
        module_lines = [f"  module {start:#014x}-{end:#014x} {name}" for start, end, name in self._modules]
        self._append_memory_lines(
            [
                "",
                f"===== memory probe started pid={os.getpid()} at {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"interval_s={MEMORY_SAMPLE_INTERVAL_S:g} =====",
                "resident = Task Manager Memory column; commit = Task Manager Commit size column",
                f"complete per-region table: {self._csv_path}",
                f"loaded modules: {len(self._modules)}",
                *module_lines,
            ]
        )
        self._memory_thread = threading.Thread(
            target=self._memory_sampler_loop, name="ResourceProbeMemory", daemon=True
        )
        self._memory_thread.start()

    def _memory_sampler_loop(self) -> None:
        while True:
            try:
                self._write_memory_sample()
            except Exception as exc:
                self._append_memory_lines([f"[memory-probe] sample failed: {exc!r}"])
            if self._memory_stop.wait(MEMORY_SAMPLE_INTERVAL_S):
                return

    def _append_memory_lines(self, lines: List[str]) -> None:
        try:
            with open(self._memory_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass

    def _append_region_rows(self, index: int, walk: _RegionWalk, stamp: str) -> None:
        rows = [entry for entry in walk.entries if entry.resident >= REGION_CSV_MIN_RESIDENT]
        if not rows:
            return
        rows.sort(key=lambda entry: entry.resident, reverse=True)
        try:
            is_new = not os.path.exists(self._csv_path) or os.path.getsize(self._csv_path) == 0
            with open(self._csv_path, "a", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                if is_new:
                    writer.writerow(
                        ["sample", "ts", "base", "type", "protect", "commit_mb", "resident_mb", "label"]
                    )
                for entry in rows:
                    writer.writerow(
                        [
                            index,
                            stamp,
                            f"0x{entry.base:012X}",
                            _TYPE_NAMES.get(entry.region_type, entry.region_type),
                            _protect_name(entry.protect),
                            f"{entry.commit / 1048576:.2f}",
                            f"{entry.resident / 1048576:.2f}",
                            entry.label,
                        ]
                    )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass

    def _write_memory_sample(self) -> None:
        self._memory_samples += 1
        index = self._memory_samples
        stamp = time.strftime("%H:%M:%S")
        api = _WinApi()
        if not api.available:
            self._append_memory_lines(["", f"===== sample {index} at {stamp} =====", "unsupported platform"])
            return

        started = time.perf_counter()
        counters = api.counters()
        walk = api.walk()
        walk_ms = (time.perf_counter() - started) * 1000

        commit = int(counters.PrivateUsage) if counters else 0
        work_set = int(counters.WorkingSetSize) if counters else 0
        peak_commit = int(counters.PeakPagefileUsage) if counters else 0
        previous = getattr(self, "_previous_totals", (0, 0))
        commit_delta = (commit - previous[0]) / 1048576 if previous[0] else 0.0
        resident_delta = (walk.private_resident - previous[1]) / 1048576 if previous[1] else 0.0
        self._previous_totals = (commit, walk.private_resident)

        previous_commit: Dict[Any, int] = getattr(self, "_previous_commit", {})
        previous_resident: Dict[Any, int] = getattr(self, "_previous_resident", {})

        lines = [
            "",
            f"===== sample {index} at {stamp} =====",
            f"workingset_private_mb={walk.private_resident / 1048576:.1f} "
            f"workingset_total_mb={work_set / 1048576:.1f} "
            f"private_commit_mb={commit / 1048576:.1f} "
            f"peak_commit_mb={peak_commit / 1048576:.1f}",
            f"resident_delta_mb={resident_delta:+.1f}  commit_delta_mb={commit_delta:+.1f}  "
            f"walk_ms={walk_ms:.0f}  regions={len(walk.entries)}",
        ]
        type_parts = [
            f"{_TYPE_NAMES.get(code, str(code))}={walk.type_totals.get(code, 0) / 1048576:.1f}"
            for code in (MEM_IMAGE, MEM_MAPPED, MEM_PRIVATE)
        ]
        lines.append(f"committed_mb: {' '.join(type_parts)}")

        def key_of(entry: _RegionEntry):
            return (entry.base, entry.region_type, entry.label)

        ranked = sorted(
            walk.entries,
            key=lambda entry: (
                entry.resident - previous_resident.get(key_of(entry), 0),
                entry.resident,
            ),
            reverse=True,
        )[:TOP_REGIONS]

        lines.append(f"[top {TOP_REGIONS} regions by resident growth, then resident size]")
        described = 0
        for entry in ranked:
            key = key_of(entry)
            commit_diff = entry.commit - previous_commit.get(key, 0)
            resident_diff = entry.resident - previous_resident.get(key, 0)
            suffix = f"  {entry.label}" if entry.label else ""
            lines.append(
                f"  base=0x{entry.base:012X}  {_TYPE_NAMES.get(entry.region_type, entry.region_type):<8} "
                f"{_protect_name(entry.protect):<7} "
                f"resident={entry.resident / 1048576:>9,.1f} MB (delta={resident_diff / 1048576:+.1f}) "
                f"commit={entry.commit / 1048576:>9,.1f} MB (delta={commit_diff / 1048576:+.1f}){suffix}"
            )
            if (
                described < DESCRIBED_REGIONS
                and entry.region_type == MEM_PRIVATE
                and entry.resident >= 8 * 1024 * 1024
            ):
                content = api.describe_region(entry.extents, entry.protect, self._modules)
                if content:
                    lines.append(f"      content: {content}")
                    described += 1

        self._previous_commit = dict(walk.commit_by_key)
        self._previous_resident = dict(walk.resident_by_key)
        self._append_memory_lines(lines)
        self._append_region_rows(index, walk, stamp)
