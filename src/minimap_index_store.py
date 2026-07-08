from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Iterable

from core.map_context import TileKey
from minimap_tile_index_state import canonical_tile_key, parse_canonical_tile_key


@dataclass(frozen=True)
class MinimapIndexTileStatus:
    tile_key: str
    tile_present: bool = False
    rough_ready: bool = False
    sift_ready: bool = False
    stale_reason: str = ""
    png_path: str = ""
    png_mtime_ns: int = 0
    png_size: int = 0
    rough_count: int = 0
    sift_path: str = ""
    feature_count: int = 0
    error: str = ""

    @property
    def exists(self) -> bool:
        return self.tile_present or bool(self.png_path or self.sift_path or self.error)


class MinimapIndexStore:
    def __init__(self, tile_root: Path, area_id: str):
        self.tile_root = Path(tile_root)
        self.area_id = str(area_id)
        self.path = self.tile_root / self.area_id / "indexes" / "minimap_index.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def record_tile_available(self, key: TileKey, *, png_path: str, mtime_ns: int, size: int) -> None:
        self._upsert(
            key,
            tile_present=1,
            png_path=str(png_path),
            png_mtime_ns=int(mtime_ns),
            png_size=int(size),
            error="",
        )

    def mark_rough_ready(self, key: TileKey, *, rough_count: int = 1) -> None:
        self._upsert(key, tile_present=1, rough_ready=1, rough_count=int(rough_count), error="")

    def mark_sift_ready(self, key: TileKey, *, sift_path: str, feature_count: int) -> None:
        self._upsert(
            key,
            tile_present=1,
            sift_ready=1,
            stale_reason="",
            sift_path=str(sift_path),
            feature_count=int(feature_count),
            error="",
        )

    def mark_sift_stale(self, key: TileKey, *, reason: str) -> None:
        self._upsert(key, sift_ready=0, stale_reason=str(reason))

    def mark_failed(self, key: TileKey, *, error: str) -> None:
        self._upsert(key, error=str(error))

    def get_tile_status(self, key: TileKey) -> MinimapIndexTileStatus:
        return self.get_tile_status_by_raw_key(canonical_tile_key(key))

    def get_tile_status_by_raw_key(self, raw_key: str) -> MinimapIndexTileStatus:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tile_index_status WHERE tile_key = ?",
                (str(raw_key),),
            ).fetchone()
        if row is None:
            return MinimapIndexTileStatus(tile_key=str(raw_key))
        return _status_from_row(row)

    def tile_status_items(self) -> list[tuple[str, MinimapIndexTileStatus]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tile_index_status ORDER BY tile_key").fetchall()
        return [(str(row["tile_key"]), _status_from_row(row)) for row in rows]

    def mark_adjacent_sift_stale(self, changed_key: TileKey, *, reason: str) -> list[str]:
        stale: list[str] = []
        for raw_key, status in self.tile_status_items():
            parsed = parse_canonical_tile_key(raw_key)
            if parsed is None:
                continue
            if parsed.area_id != changed_key.area_id or parsed.kind != changed_key.kind:
                continue
            if parsed.layer_id != changed_key.layer_id or parsed.z_level != changed_key.z_level:
                continue
            dx = abs(int(parsed.x) - int(changed_key.x))
            dy = abs(int(parsed.y) - int(changed_key.y))
            if max(dx, dy) != 1 or (dx == 0 and dy == 0):
                continue
            if not status.tile_present:
                continue
            self.mark_sift_stale(parsed, reason=reason)
            stale.append(raw_key)
        return stale

    def health_summary(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN rough_ready = 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN sift_ready = 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN tile_present = 1 AND rough_ready = 0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN tile_present = 1 AND sift_ready = 0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN error != '' THEN 1 ELSE 0 END)
                FROM tile_index_status
                """
            ).fetchone()
        values = [int(value or 0) for value in row]
        return {
            "tiles": values[0],
            "rough_ready": values[1],
            "sift_ready": values[2],
            "rough_missing": values[3],
            "sift_missing": values[4],
            "failed": values[5],
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tile_index_status (
                    tile_key TEXT PRIMARY KEY,
                    area_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    layer_id TEXT NOT NULL,
                    z_level TEXT NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    tile_present INTEGER NOT NULL DEFAULT 0,
                    png_path TEXT NOT NULL DEFAULT '',
                    png_mtime_ns INTEGER NOT NULL DEFAULT 0,
                    png_size INTEGER NOT NULL DEFAULT 0,
                    rough_ready INTEGER NOT NULL DEFAULT 0,
                    rough_count INTEGER NOT NULL DEFAULT 0,
                    sift_ready INTEGER NOT NULL DEFAULT 0,
                    sift_path TEXT NOT NULL DEFAULT '',
                    feature_count INTEGER NOT NULL DEFAULT 0,
                    stale_reason TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )
                """
            )

    def _upsert(self, key: TileKey, **fields) -> None:
        raw_key = canonical_tile_key(key)
        z_level = "base" if key.z_level is None else str(key.z_level)
        values = {
            "tile_key": raw_key,
            "area_id": str(key.area_id),
            "kind": str(key.kind),
            "layer_id": str(key.layer_id),
            "z_level": z_level,
            "x": int(key.x),
            "y": int(key.y),
            "updated_at": time.time(),
        }
        values.update(fields)
        columns = list(values.keys())
        assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "tile_key")
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO tile_index_status ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(tile_key) DO UPDATE SET {assignments}"
        )
        with self._connect() as conn:
            conn.execute(sql, [values[column] for column in columns])


def _status_from_row(row: sqlite3.Row) -> MinimapIndexTileStatus:
    return MinimapIndexTileStatus(
        tile_key=str(row["tile_key"]),
        tile_present=bool(row["tile_present"]),
        rough_ready=bool(row["rough_ready"]),
        sift_ready=bool(row["sift_ready"]),
        stale_reason=str(row["stale_reason"] or ""),
        png_path=str(row["png_path"] or ""),
        png_mtime_ns=int(row["png_mtime_ns"] or 0),
        png_size=int(row["png_size"] or 0),
        rough_count=int(row["rough_count"] or 0),
        sift_path=str(row["sift_path"] or ""),
        feature_count=int(row["feature_count"] or 0),
        error=str(row["error"] or ""),
    )
