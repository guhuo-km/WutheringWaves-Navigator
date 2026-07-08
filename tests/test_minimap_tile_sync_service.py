from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from core.map_context import TileKey
from minimap_tile_sync_service import MinimapTileSyncService


@dataclass(frozen=True)
class FakeDownloadResult:
    changed_area_ids: set[str]
    downloaded_sizes: dict[TileKey, int]
    failures: dict[TileKey, str]
    input_count: int = 0
    skipped_count: int = 0


@dataclass(frozen=True)
class FakeEnqueueResult:
    queued_count: int
    pending_count: int


class FakeIndexQueue:
    def __init__(self):
        self.changed_tiles = []
        self.stale_area_ids = []
        self.missing_area_ids = []
        self.missing_tiles = []
        self.pending_count = 0

    def enqueue_changed_tile(self, key):
        self.changed_tiles.append(key)
        self.pending_count += 1
        return FakeEnqueueResult(queued_count=1, pending_count=self.pending_count)

    def enqueue_stale_sift_tiles(self, area_id: str):
        self.stale_area_ids.append(area_id)
        self.pending_count += 2
        return FakeEnqueueResult(queued_count=2, pending_count=self.pending_count)

    def enqueue_missing_indexes_for_area(self, area_id: str):
        self.missing_area_ids.append(area_id)
        self.pending_count += 3
        return FakeEnqueueResult(queued_count=3, pending_count=self.pending_count)

    def enqueue_missing_indexes_for_tiles(self, keys):
        keys = list(keys)
        self.missing_tiles.extend(keys)
        self.pending_count += len(keys)
        return FakeEnqueueResult(queued_count=len(keys), pending_count=self.pending_count)


def _snapshot(area_id: str):
    return {
        "ok": True,
        "data": {
            "standardTiles": [
                {"regionId": area_id, "x": 10, "y": 20, "url": f"https://example.invalid/{area_id}.png"}
            ],
            "layeredTiles": [],
            "gravityTiles": [],
        },
    }


def _tile(area_id: str):
    return TileKey(area_id=area_id, layer_id="default", z_level=None, kind="standard", x=10, y=20)


def test_processes_snapshot_with_injected_download_and_index_queue(tmp_path):
    index_queue = FakeIndexQueue()
    summaries = []

    def download_func(raw_snapshot, tile_root):
        assert raw_snapshot == _snapshot("8")
        assert tile_root == tmp_path
        key = _tile("8")
        return FakeDownloadResult(
            changed_area_ids={"8"},
            downloaded_sizes={key: 123},
            failures={},
            input_count=1,
            skipped_count=0,
        )

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=index_queue,
        tile_root_provider=lambda: tmp_path,
        on_summary=summaries.append,
    )

    try:
        assert service.submit_snapshot(_snapshot("8")) is True
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert index_queue.changed_tiles == [_tile("8")]
    assert index_queue.stale_area_ids == ["8"]
    assert index_queue.missing_area_ids == []
    assert index_queue.missing_tiles == [_tile("8")]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.downloaded_count == 1
    assert summary.failure_count == 0
    assert summary.index_queued_tiles == 1
    assert summary.stale_queued_tiles == 2
    assert summary.missing_queued_items == 1
    assert summary.changed_area_ids == ("8",)


def test_snapshot_missing_index_check_only_uses_snapshot_tiles(tmp_path):
    index_queue = FakeIndexQueue()

    def download_func(raw_snapshot, tile_root):
        return FakeDownloadResult(
            changed_area_ids=set(),
            downloaded_sizes={},
            failures={},
            input_count=1,
            skipped_count=1,
        )

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=index_queue,
        tile_root_provider=lambda: tmp_path,
    )

    try:
        assert service.submit_snapshot(_snapshot("906")) is True
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert index_queue.missing_area_ids == []
    assert index_queue.missing_tiles == [_tile("906")]


def test_busy_service_keeps_only_latest_pending_snapshot(tmp_path):
    started = threading.Event()
    release = threading.Event()
    summaries = []
    processed_area_ids = []

    def download_func(raw_snapshot, tile_root):
        area_id = raw_snapshot["data"]["standardTiles"][0]["regionId"]
        processed_area_ids.append(area_id)
        if area_id == "first":
            started.set()
            assert release.wait(timeout=2.0)
        return FakeDownloadResult(
            changed_area_ids={area_id},
            downloaded_sizes={_tile(area_id): 100},
            failures={},
            input_count=1,
            skipped_count=0,
        )

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=FakeIndexQueue(),
        tile_root_provider=lambda: tmp_path,
        on_summary=summaries.append,
    )

    try:
        assert service.submit_snapshot(_snapshot("first")) is True
        assert started.wait(timeout=2.0)
        assert service.submit_snapshot(_snapshot("second")) is True
        assert service.submit_snapshot(_snapshot("third")) is True
        release.set()
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        release.set()
        service.shutdown()

    deadline = time.monotonic() + 1.0
    while len(summaries) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert processed_area_ids == ["first", "third"]
    assert [summary.changed_area_ids for summary in summaries] == [("first",), ("third",)]
