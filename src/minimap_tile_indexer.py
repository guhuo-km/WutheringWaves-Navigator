from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
import time
from typing import Callable, Iterable

import cv2
import numpy as np

from core.map_context import TileKey
from minimap_index_store import (
    CURRENT_TILE_INDEX_VERSION,
    UNAVAILABLE_TILE_INDEX_VERSION,
    MinimapIndexStore,
)
from minimap_orb_builder import build_area_orb_index
from minimap_orb_index import extract_orb_descriptors
from minimap_orb_store import ORB_AREA_INDEX_NAME, load_orb_area_index, save_orb_area_index
from minimap_retrieval_index import compute_hsv_texture_descriptor
from minimap_sift_index import (
    extract_owned_sift_features_from_expanded_tile,
    resolve_tile_image_path,
)
from minimap_tile_geometry import url_tile_to_map_pixel
from minimap_tile_index_state import (
    COARSE_PHASES,
    COARSE_TILE_CACHE_LIMIT,
    COARSE_WINDOW_SIZE,
    TileIndexStateStore,
    TileIndexStatus,
    canonical_coarse_window_key,
    canonical_tile_key,
    coarse_lattice_base,
    coarse_tile_origin,
    coarse_tile_span,
    coarse_window_index_span,
    coarse_window_left_top,
    coarse_window_rects_for_tile,
    parse_canonical_tile_key,
)


@dataclass(frozen=True)
class TileIndexWork:
    kind: str
    work_key: str
    tile_keys: tuple[TileKey, ...]
    rect: tuple[int, int, int, int] = ()
    area_id: str = ""


@dataclass(frozen=True)
class TileIndexEnqueueResult:
    queued: tuple[TileIndexWork, ...]
    stale_tile_keys: tuple[str, ...]
    pending_count: int
    incomplete_tiles: tuple[TileKey, ...] = ()

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
        self._rebuilding_area_ids: set[str] = set()
        self._deferred_tiles: dict[str, list[TileKey]] = {}
        self._pending_area_works: dict[str, int] = {}
        self._tile_image_cache: dict[str, np.ndarray] = {}
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._futures: list[Future] = []
        if self.auto_start:
            self._enqueue_many(
                [TileIndexWork(kind="area_reconcile", work_key="area_reconcile", tile_keys=())]
            )

    def enqueue_changed_tile(self, key: TileKey) -> TileIndexEnqueueResult:
        area_id = str(key.area_id)
        if self._defer_during_rebuild(area_id, key):
            return TileIndexEnqueueResult(
                queued=(),
                stale_tile_keys=(),
                pending_count=self.pending_count,
            )
        if MinimapIndexStore(self.tile_root, area_id).get_area_index_version(area_id) != CURRENT_TILE_INDEX_VERSION:
            self._request_area_rebuild(area_id)
            if self._defer_during_rebuild(area_id, key):
                return TileIndexEnqueueResult(
                    queued=(),
                    stale_tile_keys=(),
                    pending_count=self.pending_count,
                )
        store = TileIndexStateStore(self.tile_root, area_id)
        index_store = MinimapIndexStore(self.tile_root, area_id)
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
                kind="sift_tile",
                work_key=f"sift|{canonical_tile_key(key)}",
                tile_keys=(key,),
                area_id=area_id,
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
                    area_id=area_id,
                )
            )
        works.extend(self._coarse_works_for_tile(key))
        # A changed tile makes the published area ORB product stale; the coalesced
        # area_orb_build in _run_work re-publishes it once every window/SIFT work for
        # this area has drained.
        MinimapIndexStore(self.tile_root, area_id).set_area_orb_ready(area_id, False)
        queued = self._enqueue_many(works)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=stale,
            pending_count=self.pending_count,
        )

    def enqueue_stale_sift_tiles(self, area_id: str) -> TileIndexEnqueueResult:
        area_id = str(area_id)
        if self._is_area_rebuilding(area_id):
            return TileIndexEnqueueResult(queued=(), stale_tile_keys=(), pending_count=self.pending_count)
        store = TileIndexStateStore(self.tile_root, area_id)
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
                )
            )
        queued = self._enqueue_many(works)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=tuple(stale_keys),
            pending_count=self.pending_count,
        )

    def enqueue_missing_indexes_for_area(self, area_id: str) -> TileIndexEnqueueResult:
        """Regenerate the whole area's coarse and SIFT indexes.

        A partial per-tile patch is not enough once an area is behind the current
        coarse rule: every window of the area has to be re-cut on the new lattice, and
        the legacy per-tile readiness rows must not be trusted during the switch. The
        area version in SQLite is the single authority for that, so this entry point
        only asks for the area rebuild.
        """
        return self._request_area_rebuild(str(area_id))

    def enqueue_missing_indexes_for_tiles(self, keys) -> TileIndexEnqueueResult:
        queued: list[TileIndexWork] = []
        incomplete: list[TileKey] = []
        keys_by_area: dict[str, list[TileKey]] = {}
        for key in keys:
            if not isinstance(key, TileKey):
                continue
            path = resolve_tile_image_path(self.tile_root, key)
            if not path.exists():
                continue
            keys_by_area.setdefault(str(key.area_id), []).append(key)
        for area_id, area_keys in keys_by_area.items():
            statuses = MinimapIndexStore(self.tile_root, area_id).get_tile_statuses(area_keys)
            for key in area_keys:
                status = statuses[canonical_tile_key(key)]
                if status.tile_present and status.rough_ready and status.sift_ready and not status.stale_reason:
                    continue
                incomplete.append(key)
                result = self.enqueue_changed_tile(key)
                queued.extend(result.queued)
        return TileIndexEnqueueResult(
            queued=tuple(queued),
            stale_tile_keys=(),
            pending_count=self.pending_count,
            incomplete_tiles=tuple(incomplete),
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
        if work.kind == "area_rebuild":
            self._process_area_rebuild(work)
            return
        if work.kind == "area_reconcile":
            self._coordinate_area_rebuilds()
            return
        if work.kind == "area_orb_build":
            self._process_area_orb_build(work)
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
                if work.kind in ("rough_window", "sift_tile") and work.area_id:
                    self._pending_area_works[work.area_id] = self._pending_area_works.get(work.area_id, 0) + 1
                if self.auto_start:
                    self._futures.append(self._executor.submit(self._run_work, work))
        return queued

    def _run_work(self, work: TileIndexWork) -> None:
        error = self._execute_work(work)
        replay: list[TileKey] = []
        orb_area: str | None = None
        with self._lock:
            self._queued_keys.discard(work.work_key)
            self._pending = [item for item in self._pending if item.work_key != work.work_key]
            if work.kind == "area_rebuild":
                self._rebuilding_area_ids.discard(work.area_id)
                if error is None:
                    replay = self._deferred_tiles.pop(work.area_id, [])
            if work.kind in ("rough_window", "sift_tile") and work.area_id:
                remaining = self._pending_area_works.get(work.area_id, 0) - 1
                if remaining < 0:
                    remaining = 0
                self._pending_area_works[work.area_id] = remaining
                orb_area = work.area_id
        if orb_area is not None:
            self._maybe_publish_area_orb(orb_area)
        for key in replay:
            self.enqueue_changed_tile(key)

    def _maybe_publish_area_orb(self, area_id: str) -> None:
        """Enqueue one area ORB build once the area's window/SIFT works have drained.

        The store reads and the enqueue run outside ``self._lock`` on purpose: ``Lock``
        is not reentrant, so holding it here would deadlock against ``_enqueue_many``.
        """
        with self._lock:
            if self._pending_area_works.get(area_id, 0) != 0:
                return
        index_store = MinimapIndexStore(self.tile_root, area_id)
        if index_store.is_area_orb_ready(area_id):
            return
        if index_store.get_area_index_version(area_id) != CURRENT_TILE_INDEX_VERSION:
            return
        self._enqueue_many(
            [
                TileIndexWork(
                    kind="area_orb_build",
                    work_key=f"area_orb_build|{area_id}",
                    tile_keys=(),
                    area_id=area_id,
                )
            ]
        )

    def _execute_work(self, work: TileIndexWork) -> str | None:
        """Run one work item and report the failure reason, or ``None`` on success."""
        try:
            self.process_work(work)
        except Exception as exc:
            for key in work.tile_keys:
                try:
                    MinimapIndexStore(self.tile_root, key.area_id).mark_failed(key, error=f"{work.kind}:{exc}")
                except Exception:
                    pass
            message = f"{work.kind}:{work.work_key}: {exc}"
            self._report_error(message)
            return message
        return None

    def _coarse_works_for_tile(self, key: TileKey) -> list[TileIndexWork]:
        """Coarse windows a single changed tile can affect.

        Window identity is the plane plus the absolute rectangle, so the affected set
        is exactly the windows overlapping this tile: a window that does not overlap it
        can neither change its pixels nor its tile membership.
        """
        rects = coarse_window_rects_for_tile(
            key.x,
            key.y,
            tile_size=self.tile_size,
            window_size=COARSE_WINDOW_SIZE,
        )
        cells = self._neighbor_cells(key)
        alpha_cache: dict[str, np.ndarray | None] = {}
        return self._coarse_works(key, rects, cells, alpha_cache)

    def _coarse_works_for_plane(self, plane_keys: list[TileKey]) -> list[TileIndexWork]:
        """Every coarse window of one plane, across all three phases.

        The lattice is defined on absolute map pixels, so windows are generated over
        the plane's extent and kept only when they intersect at least one existing
        tile of that plane; a window inside the extent that hits no tile is not a
        document at all.
        """
        cells = self._plane_cells(plane_keys)
        origins = [coarse_tile_origin(key.x, key.y, self.tile_size) for key in plane_keys]
        extent_left = min(origin[0] for origin in origins)
        extent_top = min(origin[1] for origin in origins)
        extent_right = max(origin[0] for origin in origins) + self.tile_size
        extent_bottom = max(origin[1] for origin in origins) + self.tile_size
        sample = plane_keys[0]
        alpha_cache: dict[str, np.ndarray | None] = {}
        works: dict[str, TileIndexWork] = {}
        for shift_x, shift_y in COARSE_PHASES:
            base_x = coarse_lattice_base(self.tile_size, COARSE_WINDOW_SIZE, shift_x)
            base_y = coarse_lattice_base(self.tile_size, COARSE_WINDOW_SIZE, shift_y)
            for index_x in coarse_window_index_span(extent_left, extent_right, base_x, COARSE_WINDOW_SIZE):
                for index_y in coarse_window_index_span(extent_top, extent_bottom, base_y, COARSE_WINDOW_SIZE):
                    left, top = coarse_window_left_top(
                        self.tile_size,
                        COARSE_WINDOW_SIZE,
                        shift_x=shift_x,
                        shift_y=shift_y,
                        index_x=index_x,
                        index_y=index_y,
                    )
                    for work in self._coarse_works(sample, ((left, top),), cells, alpha_cache):
                        works.setdefault(work.work_key, work)
        return [works[key] for key in sorted(works)]

    def _coarse_works(
        self,
        plane: TileKey,
        rects: Iterable[tuple[int, int]],
        cells: dict[tuple[int, int], TileKey],
        alpha_cache: dict[str, np.ndarray | None],
    ) -> list[TileIndexWork]:
        works: list[TileIndexWork] = []
        for left, top in rects:
            keys = self._window_tile_keys(plane, left, top, cells)
            if not keys:
                continue
            if plane.kind != "standard" and not self._layered_window_contributes(left, top, keys, alpha_cache):
                continue
            works.append(
                TileIndexWork(
                    kind="rough_window",
                    work_key=f"rough|{canonical_coarse_window_key(plane, left, top)}",
                    tile_keys=keys,
                    rect=(left, top, COARSE_WINDOW_SIZE, COARSE_WINDOW_SIZE),
                    area_id=str(plane.area_id),
                )
            )
        return works

    @staticmethod
    def _plane_cells(keys: Iterable[TileKey]) -> dict[tuple[int, int], TileKey]:
        cells: dict[tuple[int, int], TileKey] = {}
        for key in keys:
            cells[(int(key.x) - 1, -int(key.y))] = key
        return cells

    def _neighbor_cells(self, key: TileKey) -> dict[tuple[int, int], TileKey]:
        """Existing tiles of the plane that any window of this tile can reach."""
        tile_left, tile_top = coarse_tile_origin(key.x, key.y, self.tile_size)
        reach = COARSE_WINDOW_SIZE - 1
        cells: dict[tuple[int, int], TileKey] = {}
        for bx in coarse_tile_span(tile_left - reach, 2 * reach + self.tile_size, self.tile_size):
            for by in coarse_tile_span(tile_top - reach, 2 * reach + self.tile_size, self.tile_size):
                neighbor = TileKey(
                    area_id=key.area_id,
                    layer_id=key.layer_id,
                    z_level=key.z_level,
                    kind=key.kind,
                    x=bx + 1,
                    y=-by,
                )
                if resolve_tile_image_path(self.tile_root, neighbor).exists():
                    cells[(bx, by)] = neighbor
        return cells

    def _window_tile_keys(
        self,
        plane: TileKey,
        left: int,
        top: int,
        cells: dict[tuple[int, int], TileKey],
    ) -> tuple[TileKey, ...]:
        keys = [
            cells[(bx, by)]
            for bx in coarse_tile_span(left, COARSE_WINDOW_SIZE, self.tile_size)
            for by in coarse_tile_span(top, COARSE_WINDOW_SIZE, self.tile_size)
            if (bx, by) in cells
        ]
        return tuple(sorted(keys, key=lambda item: (int(item.x), int(item.y))))

    def _layered_window_contributes(
        self,
        left: int,
        top: int,
        keys: tuple[TileKey, ...],
        alpha_cache: dict[str, np.ndarray | None],
    ) -> bool:
        """Whether a layered window's overlay changes anything inside its rectangle.

        Only the alpha channel is inspected, never the composited pixels, and a missing
        overlay means "the reader replaces the base", which is a contribution. Mirrors
        the lab's ``_crop_layered_window_contributes`` rule so both sides drop the same
        windows.
        """
        right = int(left) + COARSE_WINDOW_SIZE
        bottom = int(top) + COARSE_WINDOW_SIZE
        for key in keys:
            alpha = self._read_layer_alpha(key, alpha_cache)
            if alpha is None:
                return True
            tile_left, tile_top = coarse_tile_origin(key.x, key.y, self.tile_size)
            x0 = max(int(left), tile_left) - tile_left
            y0 = max(int(top), tile_top) - tile_top
            x1 = min(right, tile_left + self.tile_size) - tile_left
            y1 = min(bottom, tile_top + self.tile_size) - tile_top
            if x1 <= x0 or y1 <= y0:
                continue
            if alpha[y0:y1, x0:x1].any():
                return True
        return False

    def _read_layer_alpha(self, key: TileKey, cache: dict[str, np.ndarray | None]) -> np.ndarray | None:
        """Alpha plane of a layered tile, or ``None`` when it is not alpha-composited.

        ``_read_index_tile`` applies the overlay alpha only when the PNG decodes to a
        ``(tile_size, tile_size, 4)`` array under ``IMREAD_UNCHANGED``; every other
        shape replaces the base instead of blending over it.
        """
        name = canonical_tile_key(key)
        if name in cache:
            return cache[name]
        path = resolve_tile_image_path(self.tile_root, key)
        alpha: np.ndarray | None = None
        if path.exists():
            data = np.fromfile(str(path), dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
            if (
                image is not None
                and image.ndim == 3
                and image.shape[2] == 4
                and image.shape[:2] == (self.tile_size, self.tile_size)
            ):
                alpha = image[:, :, 3]
        if len(cache) >= COARSE_TILE_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        cache[name] = alpha
        return alpha

    def _read_plane_tile(self, key: TileKey) -> np.ndarray:
        name = canonical_tile_key(key)
        cache = self._tile_image_cache
        if name in cache:
            return cache[name]
        image = _read_index_tile(self.tile_root, key, self.tile_size)
        if len(cache) >= COARSE_TILE_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        cache[name] = image
        return image

    def _is_area_rebuilding(self, area_id: str) -> bool:
        with self._lock:
            return area_id in self._rebuilding_area_ids

    def _defer_during_rebuild(self, area_id: str, key: TileKey) -> bool:
        """Fold a per-tile update into the area rebuild that owns it.

        A rebuild clears the area's artifacts and readiness rows and then regenerates
        them, so an interleaved per-tile write would either be deleted on its way or
        mark a tile ready against a file the rebuild is about to remove. The update is
        replayed when the rebuild finishes without a failure.
        """
        with self._lock:
            if area_id not in self._rebuilding_area_ids:
                return False
            self._deferred_tiles.setdefault(area_id, []).append(key)
            return True

    def _request_area_rebuild(self, area_id: str) -> TileIndexEnqueueResult:
        work = TileIndexWork(
            kind="area_rebuild",
            work_key=f"area_rebuild|{area_id}",
            tile_keys=(),
            area_id=area_id,
        )
        with self._lock:
            if area_id in self._rebuilding_area_ids:
                return TileIndexEnqueueResult(
                    queued=(),
                    stale_tile_keys=(),
                    pending_count=len(self._pending),
                )
            self._rebuilding_area_ids.add(area_id)
            self._queued_keys.add(work.work_key)
            self._pending.append(work)
            if self.auto_start:
                self._futures.append(self._executor.submit(self._run_work, work))
        return TileIndexEnqueueResult(
            queued=(work,),
            stale_tile_keys=(),
            pending_count=self.pending_count,
        )

    def _coordinate_area_rebuilds(self) -> None:
        """Queue a full rebuild for every existing area that is behind the rule.

        Runs as an ordinary work item on the queue's own executor, so no UI thread and
        no timer touches the filesystem, and the queue's pending count covers it.
        """
        for area_id in self._list_area_ids():
            try:
                version = MinimapIndexStore(self.tile_root, area_id).get_area_index_version(area_id)
            except Exception as exc:
                self._report_error(f"area_reconcile:{area_id}: {exc}")
                continue
            if version == CURRENT_TILE_INDEX_VERSION:
                self._maybe_publish_area_orb(area_id)
                continue
            self._request_area_rebuild(area_id)

    def _list_area_ids(self) -> list[str]:
        if not self.tile_root.exists():
            return []
        area_ids: list[str] = []
        for entry in sorted(self.tile_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            if not any(child.is_dir() for child in entry.iterdir()):
                continue
            area_ids.append(entry.name)
        return area_ids

    def _process_area_rebuild(self, work: TileIndexWork) -> None:
        area_id = work.area_id
        index_store = MinimapIndexStore(self.tile_root, area_id)
        index_store.set_area_index_version(area_id, UNAVAILABLE_TILE_INDEX_VERSION)
        index_store.set_area_orb_ready(area_id, False)
        planes = self._scan_area_planes(area_id)
        self._clear_area_generated_indexes(area_id, index_store)

        tile_keys: list[TileKey] = []
        works: list[TileIndexWork] = []
        for plane_keys in planes.values():
            tile_keys.extend(plane_keys)
            works.extend(self._coarse_works_for_plane(plane_keys))
        for key in sorted(tile_keys, key=canonical_tile_key):
            path = resolve_tile_image_path(self.tile_root, key)
            stamp = _file_stamp(path)
            index_store.record_tile_available(
                key,
                png_path=str(path),
                mtime_ns=stamp[0],
                size=stamp[1],
            )
            works.append(
                TileIndexWork(
                    kind="sift_tile",
                    work_key=f"sift|{canonical_tile_key(key)}",
                    tile_keys=(key,),
                    area_id=area_id,
                )
            )
        failures = 0
        for item in works:
            if self._execute_work(item) is not None:
                failures += 1
        if failures:
            self._report_error(f"area_rebuild_incomplete:{area_id}:failed_works={failures}")
            return
        # Publish the area ORB product only after every window and SIFT tile succeeded.
        # A build or save failure propagates to _execute_work, keeping the area
        # unavailable and not ready.
        index_root = self.tile_root / str(area_id) / "indexes"
        orb_index = build_area_orb_index(index_root)
        save_orb_area_index(index_root / ORB_AREA_INDEX_NAME, orb_index)
        index_store.set_area_orb_ready(area_id, True)
        index_store.set_area_index_version(area_id, CURRENT_TILE_INDEX_VERSION)

    def _process_area_orb_build(self, work: TileIndexWork) -> None:
        area_id = work.area_id
        index_root = self.tile_root / str(area_id) / "indexes"
        index_store = MinimapIndexStore(self.tile_root, area_id)
        path = index_root / ORB_AREA_INDEX_NAME
        vocabulary: np.ndarray | None = None
        if path.exists():
            # Reusing the trained vocabulary only skips a retrain; it is not a fallback
            # chain. A missing or unreadable product is expected and the normal path
            # retrains, so only this read is guarded.
            try:
                vocabulary = load_orb_area_index(path).vocabulary
            except Exception:
                vocabulary = None
        orb_index = build_area_orb_index(index_root, vocabulary=vocabulary)
        save_orb_area_index(path, orb_index)
        index_store.set_area_orb_ready(area_id, True)

    def _scan_area_planes(self, area_id: str) -> dict[tuple[str, str, int | None], list[TileKey]]:
        """Tile universe of one area, grouped per map plane.

        Reads the cache layout ``<area>/<kind>/<layer>/<z_part>/<x>_<y>.png`` at a
        fixed depth, so ``indexes`` and any other generated folder is never treated as
        a plane.
        """
        area_root = self.tile_root / str(area_id)
        planes: dict[tuple[str, str, int | None], list[TileKey]] = {}
        if not area_root.exists():
            return planes
        for kind_dir in sorted(area_root.iterdir(), key=lambda item: item.name):
            if not kind_dir.is_dir() or kind_dir.name == "indexes":
                continue
            for layer_dir in sorted(kind_dir.iterdir(), key=lambda item: item.name):
                if not layer_dir.is_dir():
                    continue
                for z_dir in sorted(layer_dir.iterdir(), key=lambda item: item.name):
                    if not z_dir.is_dir():
                        continue
                    if z_dir.name == "base":
                        z_level = None
                    else:
                        z_level = _parse_z_level(z_dir.name)
                        if z_level is None:
                            continue
                    keys: list[TileKey] = []
                    for path in sorted(z_dir.glob("*.png"), key=lambda item: item.name):
                        parsed = _tile_key_from_png(area_id, kind_dir.name, layer_dir.name, z_level, path.stem)
                        if parsed is not None:
                            keys.append(parsed)
                    if keys:
                        planes[(kind_dir.name, layer_dir.name, z_level)] = keys
        return planes

    def _clear_area_generated_indexes(self, area_id: str, index_store: MinimapIndexStore) -> None:
        """Drop every generated artifact and readiness row of one area.

        Original tile PNGs are never touched, so the area can be regenerated from them.
        A file that cannot be deleted raises: leaving a stale artifact behind while the
        area is reported current is worse than an incomplete rebuild.
        """
        index_root = self.tile_root / str(area_id) / "indexes"
        for folder in ("rough_windows", "sift_tiles", "orb_descriptors"):
            root = index_root / folder
            if not root.exists():
                continue
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                if not path.is_file():
                    continue
                path.unlink()
        (index_root / ORB_AREA_INDEX_NAME).unlink(missing_ok=True)
        index_store.clear_tile_index_status()
        index_store.set_area_orb_ready(area_id, False)
        TileIndexStateStore(self.tile_root, area_id).clear()

    def _report_error(self, message: str) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(message)
        except Exception:
            pass

    def _process_rough_window(self, work: TileIndexWork) -> None:
        image = self._compose_coarse_window_image(work)
        area_id = work.tile_keys[0].area_id
        safe_name = _safe_name(work.work_key)
        json_path = self.tile_root / area_id / "indexes" / "rough_windows" / f"{safe_name}.json"
        npy_path = self.tile_root / area_id / "indexes" / "orb_descriptors" / f"{safe_name}.npy"
        # Mirror the lab's all-black rule: a fully zero composed window is the map filler
        # and never enters the HSV or ORB document set. Its artifacts are dropped, yet the
        # tiles stay rough-ready so the empty window is not re-scheduled forever.
        if not image.any():
            json_path.unlink(missing_ok=True)
            npy_path.unlink(missing_ok=True)
        else:
            vector = compute_hsv_texture_descriptor(image)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            left, top, width, height = work.rect
            payload = {
                "version": 2,
                "work_key": work.work_key,
                "kind": work.kind,
                "left": int(left),
                "top": int(top),
                "width": int(width),
                "height": int(height),
                "tile_keys": [canonical_tile_key(key) for key in work.tile_keys],
                "vector": vector.astype(float).tolist(),
            }
            _write_json_atomic(json_path, payload)
            descriptors = extract_orb_descriptors(image)
            npy_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(npy_path, descriptors)
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

    def _compose_coarse_window_image(self, work: TileIndexWork) -> np.ndarray:
        """Native-size crop of the plane at the window's absolute map rectangle.

        Missing tiles leave their part of the canvas at zero and a tile that is only
        partly inside the window contributes exactly the overlapping part, so the
        produced pixels are the same image the lab cuts for the same rectangle.
        """
        left, top, width, height = work.rect
        canvas = np.zeros((int(height), int(width), 3), dtype=np.uint8)
        for key in work.tile_keys:
            image = self._read_plane_tile(key)
            origin_x, origin_y = url_tile_to_map_pixel(key.x, key.y, 0, 0, tile_size=self.tile_size)
            tile_left, tile_top = int(origin_x), int(origin_y)
            x0 = max(int(left), tile_left)
            y0 = max(int(top), tile_top)
            x1 = min(int(left) + int(width), tile_left + self.tile_size)
            y1 = min(int(top) + int(height), tile_top + self.tile_size)
            if x1 <= x0 or y1 <= y0:
                continue
            canvas[y0 - int(top) : y1 - int(top), x0 - int(left) : x1 - int(left)] = image[
                y0 - tile_top : y1 - tile_top,
                x0 - tile_left : x1 - tile_left,
            ]
        return canvas


def _file_stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _parse_z_level(z_part: str) -> int | None:
    try:
        return int(z_part)
    except ValueError:
        return None


def _tile_key_from_png(area_id: str, kind: str, layer_id: str, z_level: int | None, stem: str) -> TileKey | None:
    if "_" not in stem:
        return None
    x_part, y_part = stem.rsplit("_", 1)
    try:
        x = int(x_part)
        y = int(y_part)
    except ValueError:
        return None
    return TileKey(area_id=str(area_id), layer_id=layer_id, z_level=z_level, kind=kind, x=x, y=y)


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
