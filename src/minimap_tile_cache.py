from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.map_context import MapContext, TileKey


class MinimapTileCache:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._size_records: dict[str, int] | None = None

    def tile_path(self, key: TileKey) -> Path:
        area, kind, layer, z_part, name = key.parts()
        return self.root / area / kind / layer / z_part / name

    def context_path(self, context: MapContext) -> Path:
        return self.root / context.area_id / "context.json"

    def size_record_path(self) -> Path:
        return self.root / "tile_sizes.json"

    def write_context(self, context: MapContext) -> Path:
        path = self.context_path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(context), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def is_same_cached_file(self, path: Path, expected_size: int | None) -> bool:
        path = Path(path)
        if expected_size is None:
            return path.exists()
        return path.exists() and path.stat().st_size == expected_size

    def _tile_record_key(self, key: TileKey) -> str:
        return "/".join(key.parts())

    def _read_size_records(self) -> dict[str, int]:
        path = self.size_record_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        records: dict[str, int] = {}
        for name, size in raw.items():
            try:
                number = int(size)
            except (TypeError, ValueError):
                continue
            if number >= 0:
                records[str(name)] = number
        return records

    def get_recorded_tile_size(self, key: TileKey) -> int | None:
        return self._get_size_records().get(self._tile_record_key(key))

    def _get_size_records(self) -> dict[str, int]:
        if self._size_records is None:
            self._size_records = self._read_size_records()
        return self._size_records

    def record_tile_size(self, key: TileKey, size: int) -> None:
        records = self._get_size_records()
        records[self._tile_record_key(key)] = int(size)
        path = self.size_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def is_same_cached_tile(self, key: TileKey, expected_size: int | None) -> bool:
        path = self.tile_path(key)
        if expected_size is not None:
            return self.is_same_cached_file(path, expected_size)
        recorded_size = self.get_recorded_tile_size(key)
        if recorded_size is None:
            return False
        return self.is_same_cached_file(path, recorded_size)
