from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Any

from minimap_tile_downloader import (
    TileDownloadResult,
    convert_tile_snapshot_to_download_inputs,
    download_missing_tiles,
)


def parse_tile_metadata_snapshot_result(raw: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        envelope = raw
    else:
        return None

    if not isinstance(envelope, dict) or not envelope.get("ok"):
        return None
    data = envelope.get("data")
    return data if isinstance(data, dict) else None


def download_tile_snapshot_result(
    raw: str | dict[str, Any] | None,
    cache_root: Path,
    *,
    fetch_bytes: Callable[[str], bytes] | None = None,
    refresh_changed_regions: Callable[[set[str]], None] | None = None,
) -> TileDownloadResult | None:
    snapshot = parse_tile_metadata_snapshot_result(raw)
    if snapshot is None:
        return None
    inputs = convert_tile_snapshot_to_download_inputs(snapshot)
    if fetch_bytes is None:
        return download_missing_tiles(
            inputs,
            Path(cache_root),
            refresh_changed_regions=refresh_changed_regions,
        )
    return download_missing_tiles(
        inputs,
        Path(cache_root),
        fetch_bytes=fetch_bytes,
        refresh_changed_regions=refresh_changed_regions,
    )
