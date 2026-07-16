from __future__ import annotations

import ctypes
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.core import gpu_adapters


class _FakeNativeFunction:
    def __init__(self, callback: Callable[..., int]) -> None:
        self._callback = callback

    def __call__(self, *args) -> int:
        return self._callback(*args)


def _set_void_pointer(target, value: int) -> None:
    ctypes.cast(target, ctypes.POINTER(ctypes.c_void_p)).contents.value = value


def _adapter(dml_device_id: int, *, software: bool = False) -> gpu_adapters.GpuAdapter:
    return gpu_adapters.GpuAdapter(
        name=f"Adapter {dml_device_id}",
        dml_device_id=dml_device_id,
        vendor_id=0x10DE,
        device_id=0x1234 + dml_device_id,
        subsys_id=0x5678,
        revision=1,
        is_software=software,
    )


def _raise(error: Exception) -> Callable[[], object]:
    def raiser() -> object:
        raise error

    return raiser


def test_filtering_preserves_raw_dxgi_order_and_dml_device_ids() -> None:
    adapters = [_adapter(0), _adapter(1, software=True), _adapter(2)]

    result = gpu_adapters._filter_hardware_adapters(adapters)

    assert [adapter.dml_device_id for adapter in result] == [0, 2]
    assert all(not adapter.is_software for adapter in result)


def test_dxgi_native_enumeration_decodes_desc_and_original_index(monkeypatch) -> None:
    factory_pointer = 100
    adapter_pointers = (1000, 1001)
    descriptors = {
        1000: {
            "name": "Microsoft Software Adapter",
            "vendor_id": 0x1414,
            "device_id": 0x008C,
            "subsys_id": 0,
            "revision": 0,
            "flags": gpu_adapters._DXGI_ADAPTER_FLAG_SOFTWARE,
        },
        1001: {
            "name": "NVIDIA GeForce Test",
            "vendor_id": 0x10DE,
            "device_id": 0x2803,
            "subsys_id": 0x17AA3A5D,
            "revision": 161,
            "flags": 0,
        },
    }

    def create_factory(_iid, output) -> int:
        _set_void_pointer(output, factory_pointer)
        return 0

    def enum_adapters(_factory, index, output) -> int:
        if index >= len(adapter_pointers):
            return gpu_adapters._DXGI_ERROR_NOT_FOUND
        _set_void_pointer(output, adapter_pointers[index])
        return 0

    def fake_com_method(pointer, slot, _result_type, *_arg_types):
        if pointer.value == factory_pointer and slot == 7:
            return enum_adapters
        if pointer.value in descriptors and slot == 10:
            def get_desc1(_adapter, output) -> int:
                spec = descriptors[pointer.value]
                desc = ctypes.cast(
                    output,
                    ctypes.POINTER(gpu_adapters._DXGIAdapterDesc1),
                ).contents
                desc.description = spec["name"]
                desc.vendor_id = spec["vendor_id"]
                desc.device_id = spec["device_id"]
                desc.subsys_id = spec["subsys_id"]
                desc.revision = spec["revision"]
                desc.flags = spec["flags"]
                return 0

            return get_desc1
        raise AssertionError(f"Unexpected COM call: pointer={pointer.value}, slot={slot}")

    monkeypatch.setattr(
        gpu_adapters.ctypes,
        "WinDLL",
        lambda _name: SimpleNamespace(CreateDXGIFactory1=_FakeNativeFunction(create_factory)),
    )
    monkeypatch.setattr(gpu_adapters, "_com_method", fake_com_method)
    monkeypatch.setattr(gpu_adapters, "_query_interface", lambda pointer, _iid: pointer)
    monkeypatch.setattr(gpu_adapters, "_release", lambda _pointer: None)

    raw_adapters = gpu_adapters._enumerate_dxgi_adapters()

    assert raw_adapters == [
        gpu_adapters.GpuAdapter("Microsoft Software Adapter", 0, 0x1414, 0x008C, 0, 0, True),
        gpu_adapters.GpuAdapter("NVIDIA GeForce Test", 1, 0x10DE, 0x2803, 0x17AA3A5D, 161, False),
    ]
    assert [adapter.dml_device_id for adapter in gpu_adapters._filter_hardware_adapters(raw_adapters)] == [1]


def test_non_windows_returns_empty_without_loading_native_apis(monkeypatch) -> None:
    monkeypatch.setattr(gpu_adapters, "_IS_WINDOWS", False)
    monkeypatch.setattr(gpu_adapters, "_enumerate_dxgi_adapters", _raise(AssertionError("DXGI must not load outside Windows")))

    assert gpu_adapters.enumerate_gpu_adapters() == []


def test_unavailable_dxgi_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(gpu_adapters, "_IS_WINDOWS", True)
    monkeypatch.setattr(gpu_adapters, "_enumerate_dxgi_adapters", _raise(OSError("dxgi.dll is unavailable")))

    assert gpu_adapters.enumerate_gpu_adapters() == []


def test_saved_selection_resolves_exact_original_id_and_fingerprint() -> None:
    adapter = _adapter(2)
    selection = gpu_adapters.adapter_to_selection(adapter)

    assert gpu_adapters.resolve_saved_adapter(selection, [adapter]) == adapter


def test_saved_selection_follows_unique_fingerprint_after_dxgi_reorder() -> None:
    original = _adapter(2)
    reordered = replace(original, dml_device_id=0)

    assert gpu_adapters.resolve_saved_adapter(
        gpu_adapters.adapter_to_selection(original),
        [reordered],
    ) == reordered


def test_saved_selection_rejects_ambiguous_fingerprint() -> None:
    original = _adapter(2)
    matches = [replace(original, dml_device_id=0), replace(original, dml_device_id=1)]

    with pytest.raises(gpu_adapters.GpuAdapterSelectionError, match="ambiguous"):
        gpu_adapters.resolve_saved_adapter(
            gpu_adapters.adapter_to_selection(original),
            matches,
        )


def test_selection_normalizer_keeps_only_complete_hardware_identity() -> None:
    selection = gpu_adapters.adapter_to_selection(_adapter(2))
    selection["ignored"] = "value"

    assert gpu_adapters.normalize_adapter_selection(selection) == {
        "name": "Adapter 2",
        "dml_device_id": 2,
        "vendor_id": 0x10DE,
        "device_id": 0x1236,
        "subsys_id": 0x5678,
        "revision": 1,
    }


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"name": ""},
        {"name": "GPU", "dml_device_id": True, "vendor_id": 1, "device_id": 2, "subsys_id": 3, "revision": 4},
        {"name": "GPU", "dml_device_id": 0, "vendor_id": 1, "device_id": -2, "subsys_id": 3, "revision": 4},
    ],
)
def test_selection_normalizer_rejects_incomplete_or_invalid_identity(selection) -> None:
    with pytest.raises(gpu_adapters.GpuAdapterSelectionError):
        gpu_adapters.normalize_adapter_selection(selection)
