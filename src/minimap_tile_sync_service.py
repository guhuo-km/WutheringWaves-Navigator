from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Thread
import time
from typing import Any, Callable

from minimap_tile_snapshot import download_tile_snapshot_result, parse_tile_metadata_snapshot_result
from minimap_tile_downloader import convert_tile_snapshot_to_download_inputs


@dataclass(frozen=True)
class MinimapTileSyncSummary:
    input_count: int = 0
    skipped_count: int = 0
    downloaded_count: int = 0
    failure_count: int = 0
    changed_area_ids: tuple[str, ...] = ()
    index_queued_tiles: int = 0
    stale_queued_tiles: int = 0
    missing_queued_items: int = 0
    index_pending_count: int = 0
    error: str | None = None


DownloadFunc = Callable[[str | dict[str, Any] | None, Path], Any]
TileRootProvider = Callable[[], Path]
SummaryCallback = Callable[[MinimapTileSyncSummary], None]


class MinimapTileSyncService:
    def __init__(
        self,
        *,
        download_func: DownloadFunc = download_tile_snapshot_result,
        index_queue: Any,
        tile_root_provider: TileRootProvider,
        on_summary: SummaryCallback | None = None,
    ):
        self._download_func = download_func
        self._index_queue = index_queue
        self._tile_root_provider = tile_root_provider
        self._on_summary = on_summary
        self._condition = Condition()
        self._busy = False
        self._pending_snapshot: str | dict[str, Any] | None = None
        self._shutdown = False
        self._worker: Thread | None = None
        self.last_summary: MinimapTileSyncSummary | None = None

    def submit_snapshot(self, snapshot_result: str | dict[str, Any] | None) -> bool:
        if not snapshot_result:
            return False
        with self._condition:
            if self._shutdown:
                return False
            if self._busy:
                self._pending_snapshot = snapshot_result
                self._condition.notify_all()
                return True
            self._busy = True
            self._worker = Thread(target=self._run_loop, args=(snapshot_result,), daemon=True)
            self._worker.start()
            return True

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + float(timeout)
        with self._condition:
            while self._busy or self._pending_snapshot is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._condition:
            self._shutdown = True
            self._pending_snapshot = None
            worker = self._worker
            self._condition.notify_all()
        if worker is not None and worker.is_alive():
            worker.join(timeout=float(timeout))

    def _run_loop(self, snapshot_result: str | dict[str, Any] | None) -> None:
        current = snapshot_result
        while current is not None:
            summary = self._process_snapshot(current)
            self._emit_summary(summary)
            with self._condition:
                current = self._pending_snapshot
                self._pending_snapshot = None
                if current is None or self._shutdown:
                    self._busy = False
                    self._condition.notify_all()
                    return

    def _process_snapshot(self, snapshot_result: str | dict[str, Any] | None) -> MinimapTileSyncSummary:
        try:
            snapshot = parse_tile_metadata_snapshot_result(snapshot_result)
            tile_root = Path(self._tile_root_provider())
            download_result = self._download_func(snapshot_result, tile_root)
            if download_result is None:
                return MinimapTileSyncSummary(error="snapshot_parse_failed")

            index_queued, pending = self._enqueue_changed_tile_indexes(download_result.downloaded_sizes.keys())
            stale_queued, pending = self._enqueue_stale_sift_indexes(snapshot, pending)
            missing_queued, pending = self._enqueue_missing_indexes(snapshot, pending)
            changed_area_ids = sorted(str(area_id) for area_id in download_result.changed_area_ids)
            return MinimapTileSyncSummary(
                input_count=int(getattr(download_result, "input_count", 0)),
                skipped_count=int(getattr(download_result, "skipped_count", 0)),
                downloaded_count=len(getattr(download_result, "downloaded_sizes", {}) or {}),
                failure_count=len(getattr(download_result, "failures", {}) or {}),
                changed_area_ids=tuple(changed_area_ids),
                index_queued_tiles=index_queued,
                stale_queued_tiles=stale_queued,
                missing_queued_items=missing_queued,
                index_pending_count=pending,
            )
        except Exception as exc:
            return MinimapTileSyncSummary(error=str(exc))

    def _emit_summary(self, summary: MinimapTileSyncSummary) -> None:
        self.last_summary = summary
        if self._on_summary is not None:
            self._on_summary(summary)

    def _enqueue_changed_tile_indexes(self, downloaded_tiles) -> tuple[int, int]:
        queued_tiles = 0
        pending = int(getattr(self._index_queue, "pending_count", 0))
        for tile_key in downloaded_tiles:
            result = self._index_queue.enqueue_changed_tile(tile_key)
            if getattr(result, "queued_count", 0):
                queued_tiles += 1
            pending = int(getattr(result, "pending_count", pending))
        return queued_tiles, pending

    def _enqueue_stale_sift_indexes(self, snapshot: dict[str, Any] | None, pending: int) -> tuple[int, int]:
        if not isinstance(snapshot, dict):
            return 0, pending
        queued_tiles = 0
        for area_id in self._tile_snapshot_area_ids(snapshot):
            result = self._index_queue.enqueue_stale_sift_tiles(area_id)
            queued_tiles += int(getattr(result, "queued_count", 0))
            pending = int(getattr(result, "pending_count", pending))
        return queued_tiles, pending

    def _enqueue_missing_indexes(self, snapshot: dict[str, Any] | None, pending: int) -> tuple[int, int]:
        if not isinstance(snapshot, dict):
            return 0, pending
        keys = [item.key for item in convert_tile_snapshot_to_download_inputs(snapshot)]
        if not keys:
            return 0, pending
        result = self._index_queue.enqueue_missing_indexes_for_tiles(keys)
        queued_items = int(getattr(result, "queued_count", 0))
        pending = int(getattr(result, "pending_count", pending))
        return queued_items, pending

    @staticmethod
    def _tile_snapshot_area_ids(snapshot: dict[str, Any]) -> list[str]:
        area_ids = set()
        for field in ("standardTiles", "layeredTiles", "gravityTiles"):
            for tile in snapshot.get(field, []) or []:
                if isinstance(tile, dict) and tile.get("regionId") is not None:
                    area_ids.add(str(tile.get("regionId")))
        return sorted(area_ids)
