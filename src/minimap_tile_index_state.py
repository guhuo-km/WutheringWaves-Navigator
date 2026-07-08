from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Iterable

from core.map_context import TileKey


@dataclass(frozen=True)
class TileIndexStatus:
    tile_present: bool = False
    rough_indexed: bool = False
    sift_indexed: bool = False
    sift_stale_reason: str = ""
    file_mtime_ns: int = 0
    file_size: int = 0


def canonical_tile_key(key: TileKey) -> str:
    z_part = "base" if key.z_level is None else str(key.z_level)
    return f"{key.area_id}|{key.kind}|{key.layer_id}|{z_part}|{int(key.x)}|{int(key.y)}"


def canonical_window_key(window_type: str, tile_keys: Iterable[TileKey]) -> str:
    keys = list(tile_keys)
    if not keys:
        raise ValueError("tile_keys must not be empty")
    identities = sorted(canonical_tile_key(key) for key in keys)
    first = keys[0]
    z_part = "base" if first.z_level is None else str(first.z_level)
    prefix = f"{first.area_id}|{first.kind}|{first.layer_id}|{z_part}|{window_type}"
    return "|".join([prefix, *identities])


class TileIndexStateStore:
    def __init__(self, tile_root: Path, area_id: str):
        self.tile_root = Path(tile_root)
        self.area_id = str(area_id)
        self.path = self.tile_root / self.area_id / "indexes" / "tile_index_state.json"
        self._tile_status: dict[str, TileIndexStatus] = {}
        self._load()

    def get_tile_status(self, key: TileKey) -> TileIndexStatus:
        return self._tile_status.get(canonical_tile_key(key), TileIndexStatus())

    def tile_status_items(self) -> list[tuple[str, TileIndexStatus]]:
        return list(self._tile_status.items())

    def set_tile_status(self, key: TileKey, status: TileIndexStatus) -> None:
        self._tile_status[canonical_tile_key(key)] = status

    def mark_adjacent_sift_stale(self, changed_key: TileKey, *, reason: str) -> list[str]:
        stale: list[str] = []
        for raw_key, status in list(self._tile_status.items()):
            parsed = _parse_canonical_tile_key(raw_key)
            if parsed is None:
                continue
            if parsed.area_id != changed_key.area_id or parsed.kind != changed_key.kind:
                continue
            if parsed.layer_id != changed_key.layer_id or parsed.z_level != changed_key.z_level:
                continue
            dx = abs(int(parsed.x) - int(changed_key.x))
            dy = abs(int(parsed.y) - int(changed_key.y))
            if dx == 0 and dy == 0:
                continue
            if max(dx, dy) != 1:
                continue
            self._tile_status[raw_key] = TileIndexStatus(
                tile_present=status.tile_present,
                rough_indexed=status.rough_indexed,
                sift_indexed=False,
                sift_stale_reason=reason,
                file_mtime_ns=status.file_mtime_ns,
                file_size=status.file_size,
            )
            stale.append(raw_key)
        return stale

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "area_id": self.area_id,
            "tiles": {key: asdict(status) for key, status in sorted(self._tile_status.items())},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _replace_with_retry(tmp, self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            tiles = payload.get("tiles", {})
            if not isinstance(tiles, dict):
                return
            for key, value in tiles.items():
                if isinstance(value, dict):
                    self._tile_status[str(key)] = TileIndexStatus(
                        tile_present=bool(value.get("tile_present", False)),
                        rough_indexed=bool(value.get("rough_indexed", False)),
                        sift_indexed=bool(value.get("sift_indexed", False)),
                        sift_stale_reason=str(value.get("sift_stale_reason", "") or ""),
                        file_mtime_ns=int(value.get("file_mtime_ns", 0) or 0),
                        file_size=int(value.get("file_size", 0) or 0),
                    )
        except Exception:
            self._tile_status = {}


def _parse_canonical_tile_key(raw: str) -> TileKey | None:
    parts = raw.split("|")
    if len(parts) != 6:
        return None
    area_id, kind, layer_id, z_part, x, y = parts
    z_level = None if z_part == "base" else int(z_part)
    return TileKey(area_id=area_id, kind=kind, layer_id=layer_id, z_level=z_level, x=int(x), y=int(y))


def parse_canonical_tile_key(raw: str) -> TileKey | None:
    return _parse_canonical_tile_key(raw)


def _replace_with_retry(source: Path, target: Path, *, attempts: int = 5, delay_seconds: float = 0.05) -> None:
    last_error: OSError | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            source.replace(target)
            return
        except OSError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(float(delay_seconds))
    if last_error is not None:
        raise last_error
