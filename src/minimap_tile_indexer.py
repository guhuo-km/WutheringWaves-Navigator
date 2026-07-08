from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
import time
from typing import Callable

import cv2
import numpy as np

from core.map_context import TileKey
from minimap_index_store import MinimapIndexStore
from minimap_retrieval_index import compute_hsv_texture_descriptor
from minimap_sift_index import (
    extract_owned_sift_features_from_expanded_tile,
    resolve_tile_image_path,
)
from minimap_tile_cache import MinimapTileCache
from minimap_tile_index_state import (
    TileIndexStateStore,
    TileIndexStatus,
    canonical_tile_key,
    canonical_window_key,
    parse_canonical_tile_key,
)


@dataclass(frozen=True)
class TileIndexWork:
    kind: str
    work_key: str
    tile_keys: tuple[TileKey, ...]
    window_type: str = ""


@dataclass(frozen=True)
class TileIndexEnqueueResult:
    queued: tuple[TileIndexWork, ...]
    stale_tile_keys: tuple[str, ...]
    pending_count: int

    @property
    def queued_count(self) -> int:
        return len(self.queued)


class TileIndexQueue:
    def __init__(
        self,
        tile_root: Path,
        *,
        tile_size: int = 1024,
        max_workers: int = 1,
        auto_start: bool = True,
        on_error: Callable[[str], None] | None = None,
    ):
        self.tile_root = Path(tile_root)
        self.tile_size = int(tile_size)
        self.auto_start = bool(auto_start)
        self.on_error = on_error
        self._lock = Lock()
        self._queued_keys: set[str] = set()
        self._pending: list[TileIndexWork] = []
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._futures: list[Future] = []

    def enqueue_changed_tile(self, key: TileKey) -> TileIndexEnqueueResult:
        store = TileIndexStateStore(self.tile_root, key.area_id)
        index_store = MinimapIndexStore(self.tile_root, key.area_id)
        path = resolve_tile_image_path(self.tile_root, key)
        stamp = _file_stamp(path)
        index_store.record_tile_available(
            key,
            png_path=str(path),
            mtime_ns=stamp[0],
            size=stamp[1],
        )
        previous = store.get_tile_status(key)
        store.set_tile_status(
            key,
            TileIndexStatus(
                tile_present=True,
                rough_indexed=previous.rough_indexed,
                sift_indexed=previous.sift_indexed,
                sift_stale_reason=previous.sift_stale_reason,
                file_mtime_ns=stamp[0],
                file_size=stamp[1],
            ),
        )
        stale = tuple(store.mark_adjacent_sift_stale(key, reason="neighbor_added"))
        sqlite_stale = tuple(index_store.mark_adjacent_sift_stale(key, reason="neighbor_added"))
        store.save()
        stale = tuple(sorted(set(stale) | set(sqlite_stale)))

        works = [
            TileIndexWork(
                kind="rough_window",
                work_key=f"rough|{canonical_window_key('tile', [key])}",
                tile_keys=(key,),
                window_type="tile",
            ),
            TileIndexWork(
                kind="sift_tile",
                work_key=f"sift|{canonical_tile_key(key)}",
                tile_keys=(key,),
                window_type="tile",
            ),
        ]
        for raw_key in stale:
            stale_key = parse_canonical_tile_key(raw_key)
            if stale_key is None:
                continue
            works.append(
                TileIndexWork(
                    kind="sift_tile",
                    work_key=f"sift|{canonical_tile_key(stale_key)}",
                    tile_keys=(stale_key,),
                    window_type="tile",
                )
            )
        works.extend(self._cross_tile_rough_work(key))
        queued = self._enqueue_many(works)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=stale,
            pending_count=self.pending_count,
        )

    def enqueue_stale_sift_tiles(self, area_id: str) -> TileIndexEnqueueResult:
        store = TileIndexStateStore(self.tile_root, str(area_id))
        works: list[TileIndexWork] = []
        stale_keys: list[str] = []
        for raw_key, status in store.tile_status_items():
            if not status.tile_present or status.sift_indexed or not status.sift_stale_reason:
                continue
            key = parse_canonical_tile_key(raw_key)
            if key is None:
                continue
            stale_keys.append(raw_key)
            works.append(
                TileIndexWork(
                    kind="sift_tile",
                    work_key=f"sift|{canonical_tile_key(key)}",
                    tile_keys=(key,),
                    window_type="tile",
                )
            )
        queued = self._enqueue_many(works)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=tuple(stale_keys),
            pending_count=self.pending_count,
        )

    def enqueue_missing_indexes_for_area(self, area_id: str) -> TileIndexEnqueueResult:
        area_id = str(area_id)
        root = self.tile_root / area_id / "standard" / "default" / "base"
        queued: list[TileIndexWork] = []
        if not root.exists():
            return TileIndexEnqueueResult(queued=(), stale_tile_keys=(), pending_count=self.pending_count)
        index_store = MinimapIndexStore(self.tile_root, area_id)
        for path in sorted(root.glob("*.png")):
            key = _tile_key_from_standard_png(area_id, path)
            if key is None:
                continue
            status = index_store.get_tile_status(key)
            if status.tile_present and status.rough_ready and status.sift_ready and not status.stale_reason:
                continue
            result = self.enqueue_changed_tile(key)
            queued.extend(result.queued)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=(),
            pending_count=self.pending_count,
        )

    def enqueue_missing_indexes_for_tiles(self, keys) -> TileIndexEnqueueResult:
        queued: list[TileIndexWork] = []
        for key in keys:
            if not isinstance(key, TileKey):
                continue
            path = resolve_tile_image_path(self.tile_root, key)
            if not path.exists():
                continue
            status = MinimapIndexStore(self.tile_root, key.area_id).get_tile_status(key)
            if status.tile_present and status.rough_ready and status.sift_ready and not status.stale_reason:
                continue
            result = self.enqueue_changed_tile(key)
            queued.extend(result.queued)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=(),
            pending_count=self.pending_count,
        )

    def health_summary(self, area_id: str) -> dict[str, int]:
        return MinimapIndexStore(self.tile_root, str(area_id)).health_summary()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            if self.pending_count == 0:
                return True
            time.sleep(0.01)
        return self.pending_count == 0

    def process_work(self, work: TileIndexWork) -> None:
        if work.kind == "rough_window":
            self._process_rough_window(work)
            return
        if work.kind == "sift_tile":
            self._process_sift_tile(work)
            return
        raise ValueError(f"unknown_tile_index_work:{work.kind}")

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _enqueue_many(self, works: list[TileIndexWork]) -> list[TileIndexWork]:
        queued: list[TileIndexWork] = []
        with self._lock:
            for work in works:
                if work.work_key in self._queued_keys:
                    continue
                self._queued_keys.add(work.work_key)
                self._pending.append(work)
                queued.append(work)
                if self.auto_start:
                    self._futures.append(self._executor.submit(self._run_work, work))
        return queued

    def _run_work(self, work: TileIndexWork) -> None:
        try:
            self.process_work(work)
        except Exception as exc:
            for key in work.tile_keys:
                try:
                    MinimapIndexStore(self.tile_root, key.area_id).mark_failed(key, error=f"{work.kind}:{exc}")
                except Exception:
                    pass
            if self.on_error is not None:
                try:
                    self.on_error(f"{work.kind}:{work.work_key}: {exc}")
                except Exception:
                    pass
        finally:
            with self._lock:
                self._queued_keys.discard(work.work_key)
                self._pending = [item for item in self._pending if item.work_key != work.work_key]

    def _cross_tile_rough_work(self, key: TileKey) -> list[TileIndexWork]:
        works: list[TileIndexWork] = []
        for dx, dy, window_type in (
            (1, 0, "edge_h"),
            (-1, 0, "edge_h"),
            (0, 1, "edge_v"),
            (0, -1, "edge_v"),
            (1, 1, "corner"),
            (1, -1, "corner"),
            (-1, 1, "corner"),
            (-1, -1, "corner"),
        ):
            neighbor = TileKey(
                area_id=key.area_id,
                layer_id=key.layer_id,
                z_level=key.z_level,
                kind=key.kind,
                x=key.x + dx,
                y=key.y + dy,
            )
            if not resolve_tile_image_path(self.tile_root, neighbor).exists():
                continue
            window_key = canonical_window_key(window_type, [key, neighbor])
            works.append(
                TileIndexWork(
                    kind="rough_window",
                    work_key=f"rough|{window_key}",
                    tile_keys=tuple(sorted((key, neighbor), key=lambda item: (item.x, item.y))),
                    window_type=window_type,
                )
            )
        return works

    def _process_rough_window(self, work: TileIndexWork) -> None:
        image = self._compose_rough_window_image(work)
        vector = compute_hsv_texture_descriptor(image)
        area_id = work.tile_keys[0].area_id
        root = self.tile_root / area_id / "indexes" / "rough_windows"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{_safe_name(work.work_key)}.json"
        payload = {
            "version": 1,
            "work_key": work.work_key,
            "kind": work.kind,
            "window_type": work.window_type,
            "tile_keys": [canonical_tile_key(key) for key in work.tile_keys],
            "vector": vector.astype(float).tolist(),
        }
        _write_json_atomic(path, payload)
        store = TileIndexStateStore(self.tile_root, area_id)
        index_store = MinimapIndexStore(self.tile_root, area_id)
        for key in work.tile_keys:
            current = store.get_tile_status(key)
            store.set_tile_status(
                key,
                TileIndexStatus(
                    tile_present=True,
                    rough_indexed=True,
                    sift_indexed=current.sift_indexed,
                    sift_stale_reason=current.sift_stale_reason,
                    file_mtime_ns=current.file_mtime_ns,
                    file_size=current.file_size,
                ),
            )
            index_store.mark_rough_ready(key, rough_count=1)
        store.save()

    def _process_sift_tile(self, work: TileIndexWork) -> None:
        key = work.tile_keys[0]
        overlap = min(64, max(0, self.tile_size // 16))
        expanded = _compose_expanded_index_tile(
            self.tile_root,
            key,
            tile_size=self.tile_size,
            overlap=overlap,
        )
        records = extract_owned_sift_features_from_expanded_tile(
            region_id=key.area_id,
            tile_x=key.x,
            tile_y=key.y,
            expanded_bgr=expanded,
            tile_size=self.tile_size,
            overlap=overlap,
        )
        descriptors = (
            np.vstack([record.descriptor for record in records]).astype(np.float32)
            if records
            else np.empty((0, 128), dtype=np.float32)
        )
        global_xy = (
            np.array([(record.global_x, record.global_y) for record in records], dtype=np.float32)
            if records
            else np.empty((0, 2), dtype=np.float32)
        )
        root = self.tile_root / key.area_id / "indexes" / "sift_tiles"
        root.mkdir(parents=True, exist_ok=True)
        sift_path = root / f"{_safe_name(work.work_key)}.npz"
        np.savez_compressed(sift_path, descriptors=descriptors, global_xy=global_xy)
        store = TileIndexStateStore(self.tile_root, key.area_id)
        current = store.get_tile_status(key)
        stamp = _file_stamp(resolve_tile_image_path(self.tile_root, key))
        store.set_tile_status(
            key,
            TileIndexStatus(
                tile_present=True,
                rough_indexed=current.rough_indexed,
                sift_indexed=True,
                sift_stale_reason="",
                file_mtime_ns=stamp[0] or current.file_mtime_ns,
                file_size=stamp[1] or current.file_size,
            ),
        )
        store.save()
        MinimapIndexStore(self.tile_root, key.area_id).mark_sift_ready(
            key,
            sift_path=str(sift_path),
            feature_count=int(len(descriptors)),
        )

    def _compose_rough_window_image(self, work: TileIndexWork) -> np.ndarray:
        tiles = []
        for key in work.tile_keys:
            image = _read_index_tile(self.tile_root, key, self.tile_size)
            tiles.append((key, image))
        if len(tiles) == 1:
            return tiles[0][1]
        if work.window_type == "edge_h":
            tiles.sort(key=lambda item: item[0].x)
            left = tiles[0][1][:, self.tile_size // 2 :]
            right = tiles[1][1][:, : self.tile_size // 2]
            return np.concatenate([left, right], axis=1)
        if work.window_type == "edge_v":
            tiles.sort(key=lambda item: item[0].y, reverse=True)
            top = tiles[0][1][self.tile_size // 2 :, :]
            bottom = tiles[1][1][: self.tile_size // 2, :]
            return np.concatenate([top, bottom], axis=0)
        return np.concatenate([item[1] for item in tiles], axis=1)


def _file_stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _tile_key_from_standard_png(area_id: str, path: Path) -> TileKey | None:
    stem = path.stem
    if "_" not in stem:
        return None
    x_part, y_part = stem.rsplit("_", 1)
    try:
        x = int(x_part)
        y = int(y_part)
    except ValueError:
        return None
    return TileKey(area_id=str(area_id), layer_id="default", z_level=None, kind="standard", x=x, y=y)


def _read_tile(path: Path, tile_size: int) -> np.ndarray:
    image = None
    if path.exists():
        data = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        return np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
    if image.shape[:2] != (tile_size, tile_size):
        image = cv2.resize(image, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
    return image[:, :, :3]


def _read_index_tile(tile_root: Path, key: TileKey, tile_size: int) -> np.ndarray:
    if key.kind == "standard":
        return _read_tile(resolve_tile_image_path(tile_root, key), tile_size)

    base_key = TileKey(
        area_id=key.area_id,
        layer_id="default",
        z_level=None,
        kind="standard",
        x=key.x,
        y=key.y,
    )
    base = _read_tile(resolve_tile_image_path(tile_root, base_key), tile_size)
    layer_path = resolve_tile_image_path(tile_root, key)
    layer = None
    if layer_path.exists():
        data = np.fromfile(str(layer_path), dtype=np.uint8)
        layer = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if layer is None:
        return np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
    if layer.shape[:2] != (tile_size, tile_size):
        layer = cv2.resize(layer, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
    if layer.ndim == 2:
        return cv2.cvtColor(layer, cv2.COLOR_GRAY2BGR)
    if layer.shape[2] == 4:
        layer_bgr = layer[:, :, :3].astype(np.float32)
        alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
        return np.clip(layer_bgr * alpha + base.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)
    return layer[:, :, :3]


def _compose_expanded_index_tile(tile_root: Path, key: TileKey, *, tile_size: int, overlap: int) -> np.ndarray:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap > tile_size:
        raise ValueError("overlap must not exceed tile_size")

    canvas = np.zeros((tile_size * 3, tile_size * 3, 3), dtype=np.uint8)
    origin_y = key.y + 1
    for nx in range(key.x - 1, key.x + 2):
        for ny in range(key.y - 1, key.y + 2):
            neighbor = TileKey(
                area_id=key.area_id,
                layer_id=key.layer_id,
                z_level=key.z_level,
                kind=key.kind,
                x=nx,
                y=ny,
            )
            tile = _read_index_tile(tile_root, neighbor, tile_size)
            left = (nx - (key.x - 1)) * tile_size
            top = (origin_y - ny) * tile_size
            canvas[top:top + tile_size, left:left + tile_size] = tile

    crop_left = tile_size - overlap
    crop_top = tile_size - overlap
    crop_right = tile_size * 2 + overlap
    crop_bottom = tile_size * 2 + overlap
    return canvas[crop_top:crop_bottom, crop_left:crop_right].copy()


def _safe_name(value: str) -> str:
    return value.replace("|", "__").replace("/", "_").replace(":", "_")


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
