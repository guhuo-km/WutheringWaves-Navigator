from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np

from core import paths
from core.map_context import CoordinateCandidate, MapContext
from minimap_heading import collect_heading_match_debug
from minimap_roi import MinimapRoi
from minimap_roi import crop_minimap_from_frame, normalize_minimap_crop
from minimap_stability_config import MinimapStabilityConfig


FRAME_IMAGE_NAME = "frame.png"
PACKAGE_JSON_NAME = "package.json"


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _write_image(path: Path, frame: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("frame_package_image_encode_failed")
    path.write_bytes(encoded.tobytes())


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_serialize(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _valid_rect(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(value.get("x", 0) or 0)
        y = int(value.get("y", 0) or 0)
        width = int(value.get("width", 0) or 0)
        height = int(value.get("height", 0) or 0)
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _write_debug_artifacts(
    package_dir: Path,
    frame: np.ndarray,
    *,
    roi: MinimapRoi | None,
    stability_config: MinimapStabilityConfig | None,
    extra: dict[str, Any],
) -> dict[str, str]:
    artifacts: dict[str, str] = {}

    runtime_capture_area = _valid_rect(extra.get("runtime_capture_area"))
    if runtime_capture_area is not None:
        from screen_capture import crop_image_region

        x, y, width, height = runtime_capture_area
        ocr_crop = crop_image_region(frame, x, y, width, height)
        if getattr(ocr_crop, "size", 0):
            _write_image(package_dir / "ocr_crop.png", ocr_crop)
            artifacts["ocr_crop"] = "ocr_crop.png"

    if roi is None:
        return artifacts

    minimap_crop = crop_minimap_from_frame(frame, roi)
    if not getattr(minimap_crop, "size", 0):
        return artifacts
    _write_image(package_dir / "minimap_crop.png", minimap_crop)
    artifacts["minimap_crop"] = "minimap_crop.png"

    normalized = normalize_minimap_crop(minimap_crop, roi.shape)
    _write_image(package_dir / "normalized_minimap.png", normalized.exact_image)
    artifacts["normalized_minimap"] = "normalized_minimap.png"
    _write_image(package_dir / "minimap_mask.png", normalized.mask)
    artifacts["minimap_mask"] = "minimap_mask.png"

    config = stability_config or MinimapStabilityConfig()
    heading_debug = collect_heading_match_debug(
        normalized.exact_image,
        normalized.mask,
        confidence_threshold=float(config.heading_match_confidence_threshold),
        top_n=12,
    )
    center_image = heading_debug.get("center_image")
    center_mask = heading_debug.get("center_mask")
    if isinstance(center_image, np.ndarray) and center_image.size:
        _write_image(package_dir / "heading_center_crop.png", center_image)
        artifacts["heading_center_crop"] = "heading_center_crop.png"
    if isinstance(center_mask, np.ndarray) and center_mask.size:
        _write_image(package_dir / "heading_center_mask.png", center_mask)
        artifacts["heading_center_mask"] = "heading_center_mask.png"
    _write_json(
        package_dir / "heading_scores.json",
        {
            "candidate": heading_debug.get("candidate"),
            "scores": heading_debug.get("scores", []),
            "reason": heading_debug.get("reason", ""),
            "best_score": heading_debug.get("best_score"),
            "confidence_threshold": heading_debug.get("confidence_threshold"),
        },
    )
    artifacts["heading_scores"] = "heading_scores.json"
    return artifacts


def _package_root(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else paths.runtime_dir("debug", "minimap_frame_packages")
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_minimap_frame_package(
    frame: np.ndarray,
    *,
    output_root: Path | None = None,
    label: str | None = None,
    roi: MinimapRoi | None = None,
    ocr_candidate: CoordinateCandidate | None = None,
    map_context: MapContext | None = None,
    tile_root: Path | None = None,
    stability_config: MinimapStabilityConfig | None = None,
    extra: dict[str, Any] | None = None,
    include_debug_artifacts: bool = False,
) -> Path:
    """Export one already-captured frame and metadata for the offline debug harness."""
    if frame is None or getattr(frame, "size", 0) == 0:
        raise ValueError("frame_package_requires_non_empty_frame")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (label or "frame")).strip("_") or "frame"
    package_dir = _package_root(output_root) / f"{timestamp}_{int(time.time() * 1000) % 1000:03d}_{safe_label}"
    package_dir.mkdir(parents=True, exist_ok=False)

    image_path = package_dir / FRAME_IMAGE_NAME
    _write_image(image_path, frame)

    extra_payload = extra or {}
    debug_artifacts = (
        _write_debug_artifacts(
            package_dir,
            frame,
            roi=roi,
            stability_config=stability_config,
            extra=extra_payload,
        )
        if include_debug_artifacts
        else {}
    )

    payload = {
        "version": 1,
        "frame": FRAME_IMAGE_NAME,
        "roi": _serialize(roi),
        "ocrCandidate": _serialize(ocr_candidate),
        "mapContext": _serialize(map_context),
        "tileRoot": str(tile_root) if tile_root is not None else None,
        "stabilityConfig": _serialize(stability_config),
        "extra": _serialize(extra_payload),
        "debugArtifacts": _serialize(debug_artifacts),
    }
    (package_dir / PACKAGE_JSON_NAME).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return package_dir / PACKAGE_JSON_NAME


def read_minimap_frame_package(package_path: Path | str) -> dict[str, Any]:
    path = Path(package_path)
    if path.is_dir():
        path = path / PACKAGE_JSON_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("frame_package_json_must_be_object")
    frame_name = data.get("frame")
    if not isinstance(frame_name, str) or not frame_name:
        raise ValueError("frame_package_missing_frame")
    frame_path = (path.parent / frame_name).resolve()
    data["framePath"] = str(frame_path)
    data["packagePath"] = str(path.resolve())
    return data

