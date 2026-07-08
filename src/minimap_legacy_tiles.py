from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from core.map_context import TileKey
from minimap_tile_cache import MinimapTileCache


@dataclass(frozen=True)
class LegacyTileFile:
    key: TileKey
    path: Path


_STANDARD_RE = re.compile(r"(?P<area>-?\d+)_(?P<x>-?\d+)_(?P<y>-?\d+)\.png$")
_LAYERED_RE = re.compile(r"(?P<area>-?\d+)_(?P<layer>-?\d+)_(?P<z>-?\d+)_(?P<x>-?\d+)_(?P<y>-?\d+)\.png$")


def _parse_standard_tile(path: Path, area_id: str) -> LegacyTileFile | None:
    match = _STANDARD_RE.fullmatch(path.name)
    if not match or match.group("area") != area_id:
        return None
    return LegacyTileFile(
        key=TileKey(
            area_id=area_id,
            layer_id="default",
            z_level=None,
            kind="standard",
            x=int(match.group("x")),
            y=int(match.group("y")),
        ),
        path=path,
    )


def _parse_layered_tile(path: Path, area_id: str) -> LegacyTileFile | None:
    match = _LAYERED_RE.fullmatch(path.name)
    if not match or match.group("area") != area_id:
        return None
    return LegacyTileFile(
        key=TileKey(
            area_id=area_id,
            layer_id=match.group("layer"),
            z_level=int(match.group("z")),
            kind="layered",
            x=int(match.group("x")),
            y=int(match.group("y")),
        ),
        path=path,
    )


def iter_legacy_tile_files(
    legacy_root: Path,
    area_id: str,
    *,
    include_layered: bool = True,
) -> list[LegacyTileFile]:
    root = Path(legacy_root)
    area_id = str(area_id)
    result: list[LegacyTileFile] = []

    standard_root = root / "tiles" / f"region_{area_id}"
    if standard_root.exists():
        for path in sorted(standard_root.glob("*.png")):
            tile = _parse_standard_tile(path, area_id)
            if tile is not None:
                result.append(tile)

    if include_layered:
        layered_root = root / "layered_tiles" / f"region_{area_id}"
        if layered_root.exists():
            for path in sorted(layered_root.rglob("*.png")):
                tile = _parse_layered_tile(path, area_id)
                if tile is not None:
                    result.append(tile)

    return result


def import_legacy_tile_tree(
    legacy_root: Path,
    cache_root: Path,
    area_id: str,
    *,
    include_layered: bool = True,
) -> list[TileKey]:
    cache = MinimapTileCache(Path(cache_root))
    imported: list[TileKey] = []
    for tile in iter_legacy_tile_files(legacy_root, area_id, include_layered=include_layered):
        target = cache.tile_path(tile.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tile.path, target)
        imported.append(tile.key)
    return imported
