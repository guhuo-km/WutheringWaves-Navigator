from core.map_provider_capabilities import (
    MapProviderCapabilities,
    capabilities_for_current_map,
)


def test_official_map_has_full_official_capabilities():
    caps = capabilities_for_current_map("online", "official_map")

    assert caps == MapProviderCapabilities(
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


def test_local_map_has_only_local_capabilities():
    caps = capabilities_for_current_map("local", "official_map")

    assert caps.provider_key == "local"
    assert caps.mode == "local"
    assert caps.uses_full_userscript is False
    assert caps.uses_lite_userscript is True
    assert caps.supports_auto_calibration is False
    assert caps.supports_official_tile_metadata is False
    assert caps.supports_minimap_visual_location is False
    assert caps.supports_official_ui_cleanup is False
    assert caps.supports_local_affine_calibration is True


def test_aura_is_not_a_supported_provider_after_boundary_cleanup():
    caps = capabilities_for_current_map("online", "aura_helper")

    assert caps.provider_key == "unsupported"
    assert caps.mode == "online"
    assert caps.uses_full_userscript is False
    assert caps.uses_lite_userscript is False
    assert caps.supports_auto_calibration is False
    assert caps.supports_official_tile_metadata is False
    assert caps.supports_minimap_visual_location is False
