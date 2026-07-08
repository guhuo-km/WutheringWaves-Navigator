from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.map_context import CoordinateCandidate, MapContext, TileKey
from core.paths import minimap_tile_cache_dir
from coordinate_continuity import ContinuityState
from coordinate_decision import choose_coordinate
import minimap_observation_pipeline as pipeline
from minimap_heading import HeadingCandidate
from minimap_frame_package import read_minimap_frame_package, write_minimap_frame_package
from minimap_observation_pipeline import run_observation_paths
from minimap_roi import MinimapRoi, build_minimap_texture_match_mask
from minimap_stability_config import MinimapStabilityConfig
from minimap_stitched_resources import StitchedResourceBuilder
from minimap_tile_cache import MinimapTileCache
from minimap_tile_downloader import TileDownloadResult, convert_tile_snapshot_to_download_inputs


TILE_METADATA_SNAPSHOT_FIXTURE = {
    "mapContext": {
        "areaId": "906",
        "tileSize": 1024,
        "coordTransform": {
            "scaleX": 0.01204705882352941,
            "scaleY": 0.01204705882352941,
            "offsetX": 1024,
            "offsetY": 0,
        },
    },
    "standardTiles": [
        {
            "regionId": "906",
            "x": 1,
            "y": 2,
            "url": "https://example.com/906/906_1_2.png",
            "expectedSize": 12345,
        }
    ],
    "layeredTiles": [
        {
            "regionId": "906",
            "layerId": "2",
            "zLevel": -1,
            "x": 3,
            "y": 4,
            "url": "https://example.com/906/2/-1_3_4.png",
        }
    ],
    "gravityTiles": [
        {
            "regionId": "906",
            "layerId": "2",
            "x": 3,
            "y": 4,
            "url": "https://example.com/906/2/3_4.png",
        }
    ],
    "updatedAt": 1,
}


def test_map_context_object_loads_from_fixture():
    raw = TILE_METADATA_SNAPSHOT_FIXTURE["mapContext"]
    mc = MapContext(
        area_id=str(raw["areaId"]),
        layer_id="default",
        tile_size=int(raw["tileSize"]),
        coord_transform=dict(raw["coordTransform"]),
    )
    assert mc.area_id == "906"
    assert mc.tile_size == 1024
    assert mc.layer_id == "default"


def test_debug_script_loads_map_context_projection_fields():
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    context = dbg._load_map_context(
        {
            "areaId": "906",
            "tileSize": 1024,
            "tileProjection": {"mapUnitsPerTileX": 849.92, "mapUnitsPerTileY": 849.92},
            "coordTransform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        }
    )

    assert context is not None
    assert context.map_units_per_tile_x == 849.92
    assert context.map_units_per_tile_y == 849.92


def test_tile_cache_root_resolves():
    root = minimap_tile_cache_dir()
    assert root.name == "minimap_tiles"
    assert "runtime" in str(root).replace("\\", "/")


def test_tile_metadata_snapshot_converts_to_download_inputs():
    inputs = convert_tile_snapshot_to_download_inputs(TILE_METADATA_SNAPSHOT_FIXTURE)
    kinds = {inp.key.kind for inp in inputs}
    assert kinds == {"standard", "layered", "gravity"}
    urls = [inp.url for inp in inputs]
    assert len(urls) == len(set(urls))


def test_decision_function_handles_supplied_candidates():
    ocr = CoordinateCandidate(100, 200, 30, source="ocr")
    visual = CoordinateCandidate(101, 201, None, source="visual")
    result = choose_coordinate(ocr, visual, ContinuityState(), agreement_xy_threshold=50)
    assert result.coord == (100, 200, 30)
    assert result.reason == "ocr_visual_agree"


def test_heading_result_serializes_for_logs():
    heading = HeadingCandidate(angle_degrees=90.0, bucket=9, confidence=0.8)
    payload = asdict(heading)
    loaded = json.loads(json.dumps(payload))
    assert loaded["angle_degrees"] == 90.0
    assert loaded["bucket"] == 9


def test_debug_report_includes_visual_match_manifest_and_scores():
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    report = dbg.format_report(
        {
            "visual_candidate": {"x": 101, "y": 201, "z": None, "source": "visual"},
            "visual_result": {
                "manifest": {"area_id": "906", "candidate_type": "layered", "layer_id": "2", "z_level": -1},
                "rough": {"location": [30, 40], "normalized_confidence": 0.91},
                "exact": {"location": [300, 400], "normalized_confidence": 0.98},
            },
        }
    )

    assert "visual match: area=906 type=layered layer=2 z=-1" in report
    assert "rough: location=[30, 40] confidence=0.91" in report
    assert "exact: location=[300, 400] confidence=0.98" in report


def test_debug_report_includes_heading_failure_reason():
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    report = dbg.format_report(
        {
            "heading_candidate": None,
            "heading_failure_reason": "no_heading_match",
        }
    )

    assert "heading candidate: None" in report
    assert "heading failure reason: no_heading_match" in report


def test_debug_script_run_observation_paths_without_visual(tmp_path):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = dbg.MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")
    result = dbg.run_observation_paths(
        frame,
        roi=roi,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
    )
    assert result["ocr_candidate"]["x"] == 100
    assert result["minimap_roi"]["width"] == 100
    assert result["normalized_minimap_size"] == (100, 100, 3)
    assert result["decision"]["reason"] == "ocr_only"
    assert result["stability_config"]["history_xy_threshold"] == 150
    assert result["timings_ms"]["total"] >= 0
    assert result["timings_ms"]["normalize_minimap"] >= 0
    assert result["timings_ms"]["decision"] >= 0


def test_debug_script_auto_detects_roi_from_top_left_fraction(monkeypatch):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    calls = []

    def fake_detect(image, search_rect):
        calls.append((image, search_rect))
        return dbg.MinimapRoi(x=12, y=34, width=56, height=56, shape="circle", source="auto")

    monkeypatch.setattr(dbg, "detect_minimap_circle_roi", fake_detect)

    roi = dbg._auto_detect_roi(frame)

    assert calls == [(frame, (0, 0, 200, 225))]
    assert roi == dbg.MinimapRoi(x=12, y=34, width=56, height=56, shape="circle", source="auto")


def test_debug_script_writes_roi_debug_images(tmp_path):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[20:60, 10:50] = 180
    roi = dbg.MinimapRoi(x=10, y=20, width=40, height=40, shape="circle", source="manual")
    normalized = dbg.normalize_minimap_crop(dbg.crop_minimap_from_frame(frame, roi), roi.shape)

    written = dbg._write_roi_debug_images(frame, roi, normalized, tmp_path, "sample")

    assert [path.name for path in written] == [
        "sample_roi_overlay.png",
        "sample_roi_crop.png",
        "sample_roi_masked.png",
    ]
    assert all(path.exists() for path in written)
    masked = cv2.imread(str(written[2]), cv2.IMREAD_UNCHANGED)
    assert masked.shape[2] == 4
    assert masked[0, 0, 3] == 0
    assert masked[20, 20, 3] == 255


def test_texture_match_mask_excludes_center_arrow_area():
    mask = np.full((100, 100), 255, dtype=np.uint8)

    texture_mask = build_minimap_texture_match_mask(mask, center_exclusion_ratio=0.2)

    assert texture_mask[50, 50] == 0
    assert texture_mask[10, 50] == 255
    assert texture_mask[50, 10] == 255


def test_debug_script_parses_coordinate_filename():
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    assert dbg._parse_coordinate_filename(Path("-110,427,56.png")) == (-110, 427, 56)
    assert dbg._parse_coordinate_filename(Path("12983,11847,580.png")) == (12983, 11847, 580)
    assert dbg._parse_coordinate_filename(Path("not-a-coordinate.png")) is None


def test_debug_script_cli_can_use_coordinate_filename(tmp_path, capsys):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    img_path = tmp_path / "-110,427,56.png"
    cv2.imwrite(str(img_path), np.zeros((200, 200, 3), dtype=np.uint8))

    exit_code = dbg.main(["--image", str(img_path), "--ocr-from-filename"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OCR candidate: {'x': -110, 'y': 427, 'z': 56" in captured.out


def test_debug_script_cli_can_run_coordinate_named_sample_directory(tmp_path, capsys):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    for name in ("-110,427,56.png", "8858,5971,220.png"):
        img_path = tmp_path / name
        cv2.imwrite(str(img_path), np.zeros((200, 200, 3), dtype=np.uint8))

    exit_code = dbg.main(["--sample-dir", str(tmp_path), "--ocr-from-filename"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "sample image:" in captured.out
    assert "OCR candidate: {'x': -110, 'y': 427, 'z': 56" in captured.out
    assert "OCR candidate: {'x': 8858, 'y': 5971, 'z': 220" in captured.out


def test_debug_script_cli_can_prepare_legacy_stitched_resources(tmp_path, capsys):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    img_path = tmp_path / "-110,427,56.png"
    cv2.imwrite(str(img_path), np.zeros((200, 200, 3), dtype=np.uint8))
    roi_path = tmp_path / "roi.json"
    roi_path.write_text(
        json.dumps({"x": 10, "y": 10, "width": 100, "height": 100, "shape": "circle", "source": "manual"}),
        encoding="utf-8",
    )
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "areaId": "8",
                "tileSize": 2,
                "coordTransform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
            }
        ),
        encoding="utf-8",
    )
    legacy_root = tmp_path / "legacy"
    legacy_tile = legacy_root / "tiles" / "region_8" / "8_0_0.png"
    legacy_tile.parent.mkdir(parents=True)
    cv2.imwrite(str(legacy_tile), np.full((2, 2, 3), 100, dtype=np.uint8))

    exit_code = dbg.main(
        [
            "--sample-dir",
            str(tmp_path),
            "--ocr-from-filename",
            "--roi-json",
            str(roi_path),
            "--map-context-json",
            str(context_path),
            "--tile-root",
            str(tmp_path / "stitched"),
            "--legacy-tile-tree",
            str(legacy_root),
            "--legacy-cache-root",
            str(tmp_path / "cache"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "legacy stitched resources: imported 1 tiles, published 1 manifests" in captured.out
    assert (tmp_path / "stitched" / "8" / "base" / "manifest.json").exists()


def test_debug_script_can_prepare_current_stitched_resources_around_ocr_xy(tmp_path, monkeypatch, capsys):
    import argparse

    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    cache_root = tmp_path / "cache"
    stitched_root = tmp_path / "stitched"
    context = MapContext(
        area_id="8",
        layer_id="default",
        tile_size=2,
        coord_transform={"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        map_units_per_tile_x=2.0,
        map_units_per_tile_y=-2.0,
    )
    ocr_candidate = CoordinateCandidate(1, 1, 0, source="ocr")

    def fake_download_missing_tiles(inputs, cache_root_arg):
        cache = MinimapTileCache(cache_root_arg)
        sizes = {}
        for item in inputs:
            path = cache.tile_path(item.key)
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), np.full((2, 2, 3), 120, dtype=np.uint8))
            sizes[item.key] = path.stat().st_size
        return TileDownloadResult(
            changed_area_ids={item.key.area_id for item in inputs},
            downloaded_sizes=sizes,
            failures={},
        )

    monkeypatch.setattr(dbg, "download_missing_tiles", fake_download_missing_tiles)
    args = argparse.Namespace(
        current_tile_base_url="https://web-static.kurobbs.com/mcmap/tiles/current",
        current_oss_params="x-oss-process=image/format,webp/resize,w_1024,h_1024",
        current_cache_root=str(cache_root),
        current_tile_radius=0,
        tile_root=str(stitched_root),
    )

    exit_code = dbg._prepare_current_stitched_resources(args, context, ocr_candidate)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "current stitched resources: tiles=1 downloaded=1 manifest=8/base/manifest.json" in captured.out
    assert (stitched_root / "8" / "base" / "manifest.json").exists()


def test_debug_script_reads_image_from_unicode_path(tmp_path):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    folder = tmp_path / "新建文件夹"
    folder.mkdir()
    img_path = folder / "-110,427,56.png"
    ok, encoded = cv2.imencode(".png", np.zeros((32, 32, 3), dtype=np.uint8))
    assert ok
    img_path.write_bytes(encoded.tobytes())

    image = dbg._read_image(img_path)

    assert image is not None
    assert image.shape == (32, 32, 3)


def test_observation_pipeline_module_runs_without_visual_resources():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")

    result = run_observation_paths(
        frame,
        roi=roi,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
    )

    assert result["ocr_candidate"]["x"] == 100
    assert result["visual_candidate"] is None
    assert result["decision"]["reason"] == "ocr_only"


def test_observation_pipeline_reports_heading_failure_reason_without_roi():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    result = run_observation_paths(
        frame,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
    )

    assert result["heading_candidate"] is None
    assert result["heading_failure_reason"] == "no_minimap_roi"


def test_observation_pipeline_reports_heading_failure_reason_when_no_heading_matches():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")

    result = run_observation_paths(
        frame,
        roi=roi,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
    )

    assert result["heading_candidate"] is None
    assert result["heading_failure_reason"] == "no_heading_match"


def test_debug_script_uses_visual_result_candidate_for_decision(tmp_path, monkeypatch):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    class FakeVisualResult:
        candidate = CoordinateCandidate(101, 201, None, source="visual")

    class FakeLocator:
        def __init__(self, tile_root, config=None):
            self.tile_root = tile_root
            self.config = config

        def match(self, normalized_minimap_image, minimap_mask, map_context, active_game_xy=None):
            return FakeVisualResult()

    monkeypatch.setattr(pipeline, "MinimapVisualLocator", FakeLocator)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = dbg.MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0})

    result = dbg.run_observation_paths(
        frame,
        roi=roi,
        map_context=context,
        tile_root=tmp_path,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
    )

    assert result["visual_candidate"]["source"] == "visual"
    assert result["decision"]["reason"] == "ocr_visual_agree"


def test_observation_pipeline_excludes_center_arrow_from_visual_match_mask(tmp_path, monkeypatch):
    captured_masks = []

    class FakeVisualResult:
        candidate = CoordinateCandidate(101, 201, None, source="visual")

    class FakeLocator:
        def __init__(self, tile_root, config=None):
            self.tile_root = tile_root
            self.config = config

        def match(self, normalized_minimap_image, minimap_mask, map_context, active_game_xy=None):
            captured_masks.append(minimap_mask.copy())
            return FakeVisualResult()

    monkeypatch.setattr(pipeline, "MinimapVisualLocator", FakeLocator)
    frame = np.full((480, 640, 3), 255, dtype=np.uint8)
    roi = MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0})

    run_observation_paths(
        frame,
        roi=roi,
        map_context=context,
        tile_root=tmp_path,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
    )

    assert captured_masks
    assert captured_masks[0][50, 50] == 0
    assert captured_masks[0][50, 80] == 255


def test_observation_pipeline_uses_configured_decision_threshold(tmp_path, monkeypatch):
    class FakeVisualResult:
        candidate = CoordinateCandidate(101, 201, None, source="visual")

    class FakeLocator:
        def __init__(self, tile_root, config=None):
            self.tile_root = tile_root
            self.config = config

        def match(self, normalized_minimap_image, minimap_mask, map_context, active_game_xy=None):
            return FakeVisualResult()

    monkeypatch.setattr(pipeline, "MinimapVisualLocator", FakeLocator)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0})

    result = run_observation_paths(
        frame,
        roi=roi,
        map_context=context,
        tile_root=tmp_path,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
        stability_config=MinimapStabilityConfig(
            coordinate_agreement_x_threshold=0,
            coordinate_agreement_y_threshold=0,
        ),
    )

    assert result["decision"]["reason"] == "conflict_without_history_resolution"


def test_observation_pipeline_passes_previous_coordinate_as_visual_layer_active_xy(tmp_path, monkeypatch):
    active_values = []

    class FakeVisualResult:
        candidate = CoordinateCandidate(101, 201, None, source="visual")

    class FakeLocator:
        def __init__(self, tile_root, config=None):
            self.tile_root = tile_root
            self.config = config

        def match(self, normalized_minimap_image, minimap_mask, map_context, active_game_xy=None):
            active_values.append(active_game_xy)
            return FakeVisualResult()

    continuity = ContinuityState()
    continuity.accept((300, 400, 50))
    monkeypatch.setattr(pipeline, "MinimapVisualLocator", FakeLocator)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0})

    run_observation_paths(
        frame,
        roi=roi,
        map_context=context,
        tile_root=tmp_path,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
        continuity=continuity,
    )

    assert active_values == [(300, 400)]


def test_observation_pipeline_uses_sift_visual_path_without_saved_scale(tmp_path, monkeypatch):
    calls = []

    class FakeVisualResult:
        candidate = CoordinateCandidate(101, 201, None, source="visual")

    class FakeLocator:
        def __init__(self, tile_root, config=None):
            self.tile_root = tile_root
            self.config = config

        def match(self, normalized_minimap_image, minimap_mask, map_context, active_game_xy=None):
            calls.append(
                {
                    "limit": self.config.rough_candidate_limit,
                }
            )
            return FakeVisualResult()

    monkeypatch.setattr(pipeline, "MinimapVisualLocator", FakeLocator)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    roi = MinimapRoi(x=10, y=10, width=100, height=100, shape="circle", source="manual")
    context = MapContext("906", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0})

    result = run_observation_paths(
        frame,
        roi=roi,
        map_context=context,
        tile_root=tmp_path,
        ocr_candidate=CoordinateCandidate(100, 200, 30, source="ocr"),
        stability_config=MinimapStabilityConfig(rough_candidate_limit=12),
    )

    assert calls == [{"limit": 12}]
    assert result["visual_candidate"]["source"] == "visual"


def test_debug_script_cli_on_synthetic_image(tmp_path):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    img_path = tmp_path / "sample.png"
    cv2.imwrite(str(img_path), np.zeros((200, 200, 3), dtype=np.uint8))
    roi_path = tmp_path / "roi.json"
    roi = {"x": 5, "y": 5, "width": 80, "height": 80, "shape": "circle", "source": "manual"}
    roi_path.write_text(json.dumps(roi), encoding="utf-8")

    exit_code = dbg.main(
        [
            "--image",
            str(img_path),
            "--roi-json",
            str(roi_path),
            "--ocr-x",
            "1",
            "--ocr-y",
            "2",
            "--ocr-z",
            "3",
        ]
    )
    assert exit_code == 0


def test_frame_package_round_trips_frame_and_observation_metadata(tmp_path):
    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    roi = MinimapRoi(x=1, y=2, width=20, height=20, shape="circle", source="auto")
    context = MapContext("8", "default", 1024, {"scaleX": 0.012, "scaleY": 0.012, "offsetX": 1024, "offsetY": 0})
    ocr = CoordinateCandidate(-1318, 433, 156, source="ocr")

    package_path = write_minimap_frame_package(
        frame,
        output_root=tmp_path,
        label="sample",
        roi=roi,
        ocr_candidate=ocr,
        map_context=context,
        tile_root=tmp_path / "stitched",
        stability_config=MinimapStabilityConfig(),
    )

    package = read_minimap_frame_package(package_path)

    assert Path(package["framePath"]).exists()
    assert package["roi"]["width"] == 20
    assert package["ocrCandidate"]["x"] == -1318
    assert package["mapContext"]["area_id"] == "8"
    assert package["tileRoot"] == str(tmp_path / "stitched")
    assert package["stabilityConfig"]["history_xy_threshold"] == 150


def test_frame_package_can_export_heading_debug_artifacts(tmp_path):
    frame = np.zeros((120, 140, 3), dtype=np.uint8)
    frame[20:100, 30:110] = (30, 150, 220)
    roi = MinimapRoi(x=30, y=20, width=80, height=80, shape="circle", source="manual")

    package_path = write_minimap_frame_package(
        frame,
        output_root=tmp_path,
        label="heading_debug",
        roi=roi,
        stability_config=MinimapStabilityConfig(),
        extra={"runtime_capture_area": {"x": 2, "y": 3, "width": 20, "height": 10}},
        include_debug_artifacts=True,
    )

    package = read_minimap_frame_package(package_path)
    artifacts = package["debugArtifacts"]

    for key in [
        "ocr_crop",
        "minimap_crop",
        "normalized_minimap",
        "minimap_mask",
        "heading_center_crop",
        "heading_center_mask",
        "heading_scores",
    ]:
        assert key in artifacts
        assert (Path(package["packagePath"]).parent / artifacts[key]).exists()


def test_debug_script_cli_consumes_frame_package(tmp_path, capsys):
    script_dir = ROOT / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import debug_minimap_localization as dbg

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    package_path = write_minimap_frame_package(
        frame,
        output_root=tmp_path,
        label="debug",
        roi=MinimapRoi(x=5, y=5, width=80, height=80, shape="circle", source="manual"),
        ocr_candidate=CoordinateCandidate(1, 2, 3, source="ocr"),
        map_context=MapContext("8", "default", 1024, {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0}),
    )

    exit_code = dbg.main(["--frame-package", str(package_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "frame package:" in captured.out
    assert "OCR candidate: {'x': 1, 'y': 2, 'z': 3" in captured.out
    assert "minimap ROI: {'x': 5, 'y': 5, 'width': 80, 'height': 80" in captured.out

