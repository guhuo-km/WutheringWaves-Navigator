"""Shared map observation data objects.

Boundaries:
- Userscript exposes map context and incrementally discovered tile metadata only.
- Python downloads and caches tiles.
- Normal visual localization does not depend on OCR coordinates.
- History does not silently reuse old coordinates as a fallback.
- Heading recognition reuses the minimap crop but is not part of coordinate solving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class MapContext:
    area_id: str
    layer_id: str
    tile_size: int
    coord_transform: dict[str, Any]
    map_units_per_tile_x: Optional[float] = None
    map_units_per_tile_y: Optional[float] = None


@dataclass(frozen=True)
class TileKey:
    area_id: str
    layer_id: str
    z_level: Optional[int]
    kind: str
    x: int
    y: int
    leaflet_x: Optional[int] = None
    leaflet_y: Optional[int] = None
    leaflet_z: Optional[int] = None

    def parts(self) -> tuple[str, str, str, str, str]:
        z_part = "base" if self.z_level is None else str(self.z_level)
        return (self.area_id, self.kind, self.layer_id, z_part, f"{self.x}_{self.y}.png")


@dataclass(frozen=True)
class CoordinateCandidate:
    x: int
    y: int
    z: Optional[int]
    source: str
    confidence: Optional[float] = None
    reason: str = ""

    def as_xy_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)

    def as_tuple(self) -> tuple[int, int, Optional[int]]:
        return (self.x, self.y, self.z)
