from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapProviderCapabilities:
    provider_key: str
    mode: str
    uses_full_userscript: bool
    uses_lite_userscript: bool
    supports_auto_calibration: bool
    supports_official_tile_metadata: bool
    supports_minimap_visual_location: bool
    supports_official_ui_cleanup: bool
    supports_local_affine_calibration: bool


def capabilities_for_current_map(mode: str, provider_key: str | None) -> MapProviderCapabilities:
    mode_key = str(mode or "").strip().lower()
    provider = str(provider_key or "").strip()

    if mode_key == "local":
        return MapProviderCapabilities(
            provider_key="local",
            mode="local",
            uses_full_userscript=False,
            uses_lite_userscript=True,
            supports_auto_calibration=False,
            supports_official_tile_metadata=False,
            supports_minimap_visual_location=False,
            supports_official_ui_cleanup=False,
            supports_local_affine_calibration=True,
        )

    if mode_key == "online" and provider == "official_map":
        return MapProviderCapabilities(
            provider_key="official_map",
            mode="online",
            uses_full_userscript=True,
            uses_lite_userscript=False,
            supports_auto_calibration=True,
            supports_official_tile_metadata=True,
            supports_minimap_visual_location=True,
            supports_official_ui_cleanup=True,
            supports_local_affine_calibration=False,
        )

    return MapProviderCapabilities(
        provider_key="unsupported",
        mode=mode_key or "unknown",
        uses_full_userscript=False,
        uses_lite_userscript=False,
        supports_auto_calibration=False,
        supports_official_tile_metadata=False,
        supports_minimap_visual_location=False,
        supports_official_ui_cleanup=False,
        supports_local_affine_calibration=False,
    )
