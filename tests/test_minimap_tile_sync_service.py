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
    incomplete_tiles: tuple[TileKey, ...] = ()


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


def _snapshot(area_id: str, *, x: int = 10, url: str | None = None):
    return {
        "ok": True,
        "data": {
            "standardTiles": [
                {
                    "regionId": area_id,
                    "x": x,
                    "y": 20,
                    "url": url or f"https://example.invalid/{area_id}-{x}.png",
                }
            ],
            "layeredTiles": [],
            "gravityTiles": [],
        },
    }


def _tile(area_id: str, *, x: int = 10):
    return TileKey(area_id=area_id, layer_id="default", z_level=None, kind="standard", x=x, y=20)


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
    assert index_queue.missing_tiles == []
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.downloaded_count == 1
    assert summary.failure_count == 0
    assert summary.index_queued_tiles == 1
    assert summary.stale_queued_tiles == 2
    assert summary.missing_queued_items == 0
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


def test_cumulative_snapshot_only_processes_new_or_changed_tiles(tmp_path):
    processed = []

    def download_func(raw_snapshot, tile_root):
        tiles = list(raw_snapshot["data"]["standardTiles"])
        processed.append([(tile["x"], tile["url"]) for tile in tiles])
        return FakeDownloadResult(
            changed_area_ids=set(),
            downloaded_sizes={},
            failures={},
            input_count=len(tiles),
            skipped_count=len(tiles),
        )

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=FakeIndexQueue(),
        tile_root_provider=lambda: tmp_path,
    )
    second = _snapshot("8", x=11)
    second["data"]["standardTiles"].insert(0, _snapshot("8", x=10)["data"]["standardTiles"][0])

    try:
        assert service.submit_snapshot(_snapshot("8", x=10)) is True
        assert service.wait_until_idle(timeout=2.0) is True
        assert service.submit_snapshot(second) is True
        assert service.wait_until_idle(timeout=2.0) is True
        assert service.submit_snapshot(second) is True
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert processed == [
        [(10, "https://example.invalid/8-10.png")],
        [(11, "https://example.invalid/8-11.png")],
    ]
    assert service.last_summary.input_count == 0


def test_changed_tile_url_is_processed_again(tmp_path):
    processed = []

    def download_func(raw_snapshot, tile_root):
        processed.append(raw_snapshot["data"]["standardTiles"][0]["url"])
        return FakeDownloadResult(set(), {}, {}, input_count=1, skipped_count=1)

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=FakeIndexQueue(),
        tile_root_provider=lambda: tmp_path,
    )
    try:
        service.submit_snapshot(_snapshot("8", url="https://example.invalid/old.png"))
        assert service.wait_until_idle(timeout=2.0) is True
        service.submit_snapshot(_snapshot("8", url="https://example.invalid/new.png"))
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert processed == ["https://example.invalid/old.png", "https://example.invalid/new.png"]


def test_failed_snapshot_does_not_suppress_identical_retry(tmp_path):
    calls = 0

    def download_func(raw_snapshot, tile_root):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return FakeDownloadResult(set(), {}, {}, input_count=1, skipped_count=1)

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=FakeIndexQueue(),
        tile_root_provider=lambda: tmp_path,
    )
    try:
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
        assert service.last_summary.error == "temporary failure"
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert calls == 2
    assert service.last_summary.error is None


def test_stale_reconciliation_runs_once_per_area(tmp_path):
    class ReadyIndexQueue(FakeIndexQueue):
        def enqueue_stale_sift_tiles(self, area_id: str):
            self.stale_area_ids.append(area_id)
            return FakeEnqueueResult(queued_count=0, pending_count=0)

        def enqueue_missing_indexes_for_tiles(self, keys):
            return FakeEnqueueResult(queued_count=0, pending_count=0)

    index_queue = ReadyIndexQueue()

    def download_func(raw_snapshot, tile_root):
        count = len(raw_snapshot["data"]["standardTiles"])
        return FakeDownloadResult(set(), {}, {}, input_count=count, skipped_count=count)

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=index_queue,
        tile_root_provider=lambda: tmp_path,
    )
    try:
        service.submit_snapshot(_snapshot("8", x=10))
        assert service.wait_until_idle(timeout=2.0) is True
        service.submit_snapshot(_snapshot("8", x=11))
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert index_queue.stale_area_ids == ["8"]


def test_incomplete_index_state_keeps_tile_eligible_for_retry(tmp_path):
    calls = 0

    class RetryingIndexQueue(FakeIndexQueue):
        def enqueue_missing_indexes_for_tiles(self, keys):
            keys = tuple(keys)
            if len(self.missing_tiles) == 0:
                self.missing_tiles.extend(keys)
                return FakeEnqueueResult(1, 1, incomplete_tiles=keys)
            return FakeEnqueueResult(0, 0)

    def download_func(raw_snapshot, tile_root):
        nonlocal calls
        calls += 1
        return FakeDownloadResult(set(), {}, {}, input_count=1, skipped_count=1)

    service = MinimapTileSyncService(
        download_func=download_func,
        index_queue=RetryingIndexQueue(),
        tile_root_provider=lambda: tmp_path,
    )
    try:
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert calls == 2


def test_pending_area_reconciliation_runs_again_without_tile_delta(tmp_path):
    class PendingStaleQueue(FakeIndexQueue):
        def enqueue_stale_sift_tiles(self, area_id: str):
            self.stale_area_ids.append(area_id)
            if len(self.stale_area_ids) == 1:
                self.pending_count = 1
                return FakeEnqueueResult(queued_count=1, pending_count=1)
            self.pending_count = 0
            return FakeEnqueueResult(queued_count=0, pending_count=0)

    service = MinimapTileSyncService(
        download_func=lambda raw, root: FakeDownloadResult(set(), {}, {}, input_count=1, skipped_count=1),
        index_queue=PendingStaleQueue(),
        tile_root_provider=lambda: tmp_path,
    )
    try:
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
        service.submit_snapshot(_snapshot("8"))
        assert service.wait_until_idle(timeout=2.0) is True
    finally:
        service.shutdown()

    assert service._index_queue.stale_area_ids == ["8", "8"]


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
