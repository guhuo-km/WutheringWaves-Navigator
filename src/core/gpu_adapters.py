from __future__ import annotations

import ctypes
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


_IS_WINDOWS = sys.platform == "win32"

_DXGI_ERROR_NOT_FOUND = ctypes.c_int32(0x887A0002).value
_DXGI_ADAPTER_FLAG_SOFTWARE = 0x2

_COM_FUNCTION = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


@dataclass(frozen=True)
class GpuAdapter:
    name: str
    dml_device_id: int
    vendor_id: int
    device_id: int
    subsys_id: int
    revision: int
    is_software: bool


class GpuAdapterSelectionError(ValueError):
    pass


_FINGERPRINT_FIELDS = (
    "name",
    "vendor_id",
    "device_id",
    "subsys_id",
    "revision",
)

_SELECTION_FIELDS = (
    "name",
    "dml_device_id",
    "vendor_id",
    "device_id",
    "subsys_id",
    "revision",
)


def normalize_adapter_selection(selection: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(selection, Mapping):
        raise GpuAdapterSelectionError("GPU adapter selection must be a mapping")

    name = selection.get("name")
    if not isinstance(name, str) or not name.strip():
        raise GpuAdapterSelectionError("GPU adapter name is missing")

    normalized: dict[str, object] = {"name": name.strip()}
    for field in _SELECTION_FIELDS[1:]:
        value = selection.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GpuAdapterSelectionError(
                f"GPU adapter {field} must be a non-negative integer"
            )
        normalized[field] = value
    return normalized


def adapter_to_selection(adapter: GpuAdapter) -> dict[str, object]:
    return {
        "name": adapter.name,
        "dml_device_id": adapter.dml_device_id,
        "vendor_id": adapter.vendor_id,
        "device_id": adapter.device_id,
        "subsys_id": adapter.subsys_id,
        "revision": adapter.revision,
    }


def resolve_saved_adapter(
    selection: Mapping[str, object] | None,
    adapters: Sequence[GpuAdapter],
) -> GpuAdapter:
    if not selection:
        raise GpuAdapterSelectionError("saved GPU adapter selection is missing")
    selection = normalize_adapter_selection(selection)

    def fingerprint_matches(adapter: GpuAdapter) -> bool:
        return all(
            selection.get(field) == getattr(adapter, field)
            for field in _FINGERPRINT_FIELDS
        )

    exact_matches = [
        adapter
        for adapter in adapters
        if selection.get("dml_device_id") == adapter.dml_device_id
        and fingerprint_matches(adapter)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]

    fingerprint_matches_list = [
        adapter for adapter in adapters if fingerprint_matches(adapter)
    ]
    if len(fingerprint_matches_list) == 1:
        return fingerprint_matches_list[0]
    if len(fingerprint_matches_list) > 1:
        raise GpuAdapterSelectionError("saved GPU adapter fingerprint is ambiguous")
    raise GpuAdapterSelectionError("saved GPU adapter is unavailable")


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> _GUID:
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _LUID(ctypes.Structure):
    _fields_ = [
        ("low_part", ctypes.c_uint32),
        ("high_part", ctypes.c_int32),
    ]


class _DXGIAdapterDesc1(ctypes.Structure):
    _fields_ = [
        ("description", ctypes.c_wchar * 128),
        ("vendor_id", ctypes.c_uint32),
        ("device_id", ctypes.c_uint32),
        ("subsys_id", ctypes.c_uint32),
        ("revision", ctypes.c_uint32),
        ("dedicated_video_memory", ctypes.c_size_t),
        ("dedicated_system_memory", ctypes.c_size_t),
        ("shared_system_memory", ctypes.c_size_t),
        ("adapter_luid", _LUID),
        ("flags", ctypes.c_uint32),
    ]


_IID_IDXGI_FACTORY1 = _GUID.from_string("770aae78-f26f-4dba-a829-253c83d1b387")
_IID_IDXGI_ADAPTER1 = _GUID.from_string("29038f61-3839-4626-91fd-086879011a05")

def enumerate_gpu_adapters() -> list[GpuAdapter]:
    if not _IS_WINDOWS:
        return []

    try:
        return _filter_hardware_adapters(_enumerate_dxgi_adapters())
    except (AttributeError, OSError):
        return []


def _filter_hardware_adapters(adapters: Sequence[GpuAdapter]) -> list[GpuAdapter]:
    return [adapter for adapter in adapters if not adapter.is_software]


def _enumerate_dxgi_adapters() -> list[GpuAdapter]:
    dxgi = ctypes.WinDLL("dxgi.dll")
    create_factory = dxgi.CreateDXGIFactory1
    create_factory.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    create_factory.restype = ctypes.c_int32

    factory = ctypes.c_void_p()
    _check_hresult(
        create_factory(ctypes.byref(_IID_IDXGI_FACTORY1), ctypes.byref(factory)),
        "CreateDXGIFactory1",
    )

    adapters: list[GpuAdapter] = []
    try:
        enum_adapters = _com_method(
            factory,
            7,
            ctypes.c_int32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        )
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            result = enum_adapters(factory, index, ctypes.byref(adapter))
            if result == _DXGI_ERROR_NOT_FOUND:
                break
            _check_hresult(result, "IDXGIFactory::EnumAdapters")

            try:
                adapter1 = _query_interface(adapter, _IID_IDXGI_ADAPTER1)
                try:
                    desc = _DXGIAdapterDesc1()
                    get_desc1 = _com_method(
                        adapter1,
                        10,
                        ctypes.c_int32,
                        ctypes.POINTER(_DXGIAdapterDesc1),
                    )
                    _check_hresult(
                        get_desc1(adapter1, ctypes.byref(desc)),
                        "IDXGIAdapter1::GetDesc1",
                    )
                    adapters.append(
                        GpuAdapter(
                            name=desc.description.rstrip("\x00").strip(),
                            dml_device_id=index,
                            vendor_id=int(desc.vendor_id),
                            device_id=int(desc.device_id),
                            subsys_id=int(desc.subsys_id),
                            revision=int(desc.revision),
                            is_software=bool(
                                desc.flags & _DXGI_ADAPTER_FLAG_SOFTWARE
                            ),
                        )
                    )
                finally:
                    _release(adapter1)
            finally:
                _release(adapter)
            index += 1
    finally:
        _release(factory)

    return adapters


def _query_interface(pointer: ctypes.c_void_p, iid: _GUID) -> ctypes.c_void_p:
    query_interface = _com_method(
        pointer,
        0,
        ctypes.c_int32,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    result = ctypes.c_void_p()
    _check_hresult(
        query_interface(pointer, ctypes.byref(iid), ctypes.byref(result)),
        "IUnknown::QueryInterface",
    )
    return result


def _release(pointer: ctypes.c_void_p) -> None:
    if not pointer or not pointer.value:
        return
    release = _com_method(pointer, 2, ctypes.c_uint32)
    release(pointer)


def _com_method(pointer: ctypes.c_void_p, index: int, result_type, *arg_types):
    if not pointer or not pointer.value:
        raise OSError("COM interface pointer is null")
    vtable = ctypes.cast(
        pointer,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    return _COM_FUNCTION(
        result_type,
        ctypes.c_void_p,
        *arg_types,
    )(vtable[index])


def _check_hresult(result: int, operation: str) -> None:
    if result < 0:
        raise OSError(f"{operation} failed with HRESULT 0x{result & 0xFFFFFFFF:08X}")


__all__ = ["GpuAdapter", "enumerate_gpu_adapters"]
