"""Helpers for building the OCRManager vision snapshot from userscript data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from core.map_context import MapContext

DEFAULT_LAYER_ID = "default"


def map_context_from_js(
    data: Dict[str, Any],
    layer_id: str = DEFAULT_LAYER_ID,
) -> Optional[MapContext]:
    """Build a ``MapContext`` from ``getMapContext()`` payload fields."""
    if not isinstance(data, dict):
        return None
    area_id = str(data.get("areaId") or "").strip()
    if not area_id:
        return None
    ct = data.get("coordTransform")
    if not isinstance(ct, dict):
        return None
    try:
        coord_transform = {
            "scaleX": float(ct["scaleX"]),
            "scaleY": float(ct["scaleY"]),
            "offsetX": float(ct["offsetX"]),
            "offsetY": float(ct["offsetY"]),
        }
        tile_size = int(data.get("tileSize") or 1024)
        tile_projection = data.get("tileProjection") if isinstance(data.get("tileProjection"), dict) else {}
        map_units_per_tile_x = tile_projection.get("mapUnitsPerTileX")
        map_units_per_tile_y = tile_projection.get("mapUnitsPerTileY")
    except (KeyError, TypeError, ValueError):
        return None
    return MapContext(
        area_id=area_id,
        layer_id=layer_id,
        tile_size=tile_size,
        coord_transform=coord_transform,
        map_units_per_tile_x=float(map_units_per_tile_x) if map_units_per_tile_x is not None else None,
        map_units_per_tile_y=float(map_units_per_tile_y) if map_units_per_tile_y is not None else None,
    )


def parse_get_map_context_result(raw: Optional[str]) -> Optional[MapContext]:
    """Parse the JSON string returned by ``build_get_map_context_command()``."""
    if not raw:
        return None
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict) or not envelope.get("ok"):
        return None
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    return map_context_from_js(data)


def build_vision_snapshot(map_context: MapContext, tile_root: Path) -> Dict[str, Any]:
    """Snapshot dict consumed by ``OCRManager.update_vision_context``."""
    return {
        "tile_root": str(tile_root),
        "map_context": map_context,
    }
