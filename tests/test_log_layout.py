from pathlib import Path

from src.core import crash_diagnostics
from src.core import paths
from src.core.log_manager import LogManager
from src.core.observation_evidence_log import (
    route_observation_bundle,
)


def test_log_manager_groups_files_by_date_and_session(tmp_path):
    manager = LogManager(log_dir=str(tmp_path), session_ts="20260523_154500")

    assert Path(manager.get_log_path("system")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/system.log"
    assert Path(manager.get_log_path("recognition")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/recognition.log"
    assert manager.get_log_path("ocr") == manager.get_log_path("recognition")
    assert Path(manager.get_log_path("debug")).relative_to(tmp_path).as_posix() == "2026-05-23/154500/debug.log"

    manager.stop()


def test_log_manager_indexes_recent_lines_in_sqlite(tmp_path):
    manager = LogManager(log_dir=str(tmp_path), session_ts="20260523_154500")

    for idx in range(5):
        manager.enqueue("recognition", f"[12:00:0{idx}] line-{idx}")
    manager.flush()

    rows = manager.query_recent("recognition", limit=3)

    assert [row["message"] for row in rows] == [
        "[12:00:04] line-4",
        "[12:00:03] line-3",
        "[12:00:02] line-2",
    ]
    assert all(row["session"] == "20260523_154500" for row in rows)

    manager.stop()


def test_crash_diagnostics_uses_same_session_log_layout(tmp_path):
    log_dir = crash_diagnostics.resolve_session_log_dir(str(tmp_path), "20260523_154500")

    assert Path(log_dir).relative_to(tmp_path).as_posix() == "2026-05-23/154500"


def test_crash_diagnostics_uses_runtime_log_root(monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(crash_diagnostics, "_SESSION_TS", "20260523_154500")

    log_dir = Path(crash_diagnostics._resolve_log_dir())

    assert log_dir == paths.log_dir() / "2026-05-23" / "154500"
    assert not str(log_dir).startswith(str(paths.src_root()))


def test_observation_evidence_routes_summary_to_system_and_details_to_recognition():
    bundle = {
        "ocr": {"x": 100, "y": 200, "z": 30, "source": "ocr"},
        "visual": {"x": 101, "y": 201, "z": None, "source": "visual"},
        "heading": {"angle_degrees": 90.0, "bucket": 9, "confidence": 0.8},
        "decision": {"coord": [100, 200, 30], "source": "ocr", "reason": "ocr_visual_agree"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))

    assert any(log_type == "system" and "[OBS-DECISION]" in line for log_type, line in routed)
    assert any(log_type == "recognition" and "[OBS-EVIDENCE]" in line for log_type, line in routed)
    assert not any(log_type == "debug" and "[OBS-EVIDENCE]" in line for log_type, line in routed)


def test_observation_recognition_log_includes_visual_match_evidence():
    bundle = {
        "visual_result": {
            "manifest": {"area_id": "906", "candidate_type": "layered", "layer_id": "2", "z_level": -1},
            "rough": {"location": [30, 40], "raw_score": 0.01, "normalized_confidence": 0.99},
            "exact": {"location": [300, 400], "raw_score": 0.02, "normalized_confidence": 0.98},
        },
        "previous_coordinate": [90, 190, 30],
        "visual_failure_reason": "",
        "timings_ms": {"normalize_minimap": 3.2, "heading": 4.1, "visual": 12.5, "decision": 0.2, "total": 20.0},
        "decision": {"coord": [100, 200, 30], "source": "visual", "reason": "visual_near_history"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    ocr_text = "\n".join(line for log_type, line in routed if log_type == "recognition")

    assert "visual_match: area=906 type=layered layer=2 z=-1" in ocr_text
    assert "rough: location=[30, 40] raw_score=0.01 confidence=0.99" in ocr_text
    assert "exact: location=[300, 400] raw_score=0.02 confidence=0.98" in ocr_text
    assert "previous_coordinate=[90, 190, 30]" in ocr_text
    assert "timings_ms: normalize=3.2 heading=4.1 visual=12.5 decision=0.2 total=20.0" in ocr_text


def test_observation_recognition_log_includes_visual_trace_details():
    bundle = {
        "visual_trace": {
            "manifests": [
                {
                    "area_id": "8",
                    "candidate_type": "base",
                    "layer_id": "default",
                    "z_level": None,
                    "rough_index_source": "disk",
                    "rough_hits": [
                        {
                            "rank": 1,
                            "score": 0.88,
                            "window": {"left": 256, "top": 512, "width": 512, "height": 512},
                            "tile_keys": ["standard/default/base/-3_4", "standard/default/base/-2_4"],
                            "sift_index_source": "rebuilt",
                            "feature_count": 123,
                            "raw_match_count": 50,
                            "good_match_count": 22,
                            "inlier_count": 18,
                            "accepted": True,
                        }
                    ],
                }
            ]
        },
        "decision": {"coord": [100, 200, 30], "source": "visual", "reason": "visual_near_history"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    ocr_text = "\n".join(line for log_type, line in routed if log_type == "recognition")
    debug_text = "\n".join(line for log_type, line in routed if log_type == "debug")

    assert "visual_trace:" in ocr_text
    assert "manifest area=8 type=base layer=default z=None rough_index=disk" in ocr_text
    assert "hit rank=1 score=0.88 window=(256,512,512,512)" in ocr_text
    assert "tiles=standard/default/base/-3_4,standard/default/base/-2_4" in ocr_text
    assert "sift_index=rebuilt features=123 raw=50 good=22 inliers=18 accepted=True" in ocr_text
    assert "visual_trace:" not in debug_text


def test_observation_recognition_log_includes_tile_index_trace_details():
    bundle = {
        "visual_trace": {
            "rough_index_source": "tile_index",
            "rough_candidates_available": 12,
            "rough_candidates_used": 8,
            "hsv_candidates_used": 6,
            "orb_candidates_used": 2,
            "orb_status": "ready",
            "rough_candidates_skipped_missing": 3,
            "rough_hits": [
                {
                    "rank": 1,
                    "score": 0.88,
                    "work_key": "region|8|standard|default|base",
                    "tile_keys": ["8|standard|default|base|10|20"],
                    "rectangles": [(20480, 20480, 1024, 1024)],
                    "sources": ["hsv", "orb"],
                    "source_scores": {"hsv": 0.88, "orb": 0.42},
                    "sift_index_source": "tile_index",
                    "feature_count": 123,
                    "raw_match_count": 50,
                    "good_match_count": 22,
                    "inlier_count": 18,
                    "accepted": True,
                    "skip_reason": "",
                },
                {
                    "rank": 2,
                    "score": 0.0,
                    "work_key": "region|8|standard|default|1",
                    "tile_keys": ["8|standard|default|1|10|21"],
                    "rectangles": [(20480, 21504, 400, 400)],
                    "sources": ["orb"],
                    "source_scores": {"hsv": None, "orb": 0.31},
                    "sift_index_source": "tile_index",
                    "feature_count": 2,
                    "raw_match_count": 0,
                    "good_match_count": 0,
                    "inlier_count": 0,
                    "accepted": False,
                    "skip_reason": "too_few_features",
                },
            ],
        },
        "decision": {"coord": [100, 200, 30], "source": "visual", "reason": "visual_near_history"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    recognition_text = "\n".join(line for log_type, line in routed if log_type == "recognition")

    assert "tile_index: rough_candidates_available=12 used=8 skipped_missing=3" in recognition_text
    assert "hsv_used=6 orb_used=2 orb_status=ready" in recognition_text
    assert "hit rank=1 score=0.88 work_key=region|8|standard|default|base" in recognition_text
    assert "tiles=8|standard|default|base|10|20" in recognition_text
    assert "sources=hsv,orb source_scores=hsv=0.88 orb=0.42" in recognition_text
    assert "sift_index=tile_index features=123 raw=50 good=22 inliers=18 accepted=True skip=" in recognition_text
    assert "hit rank=2 score=0.0 work_key=region|8|standard|default|1" in recognition_text
    assert "sources=orb source_scores=hsv=None orb=0.31" in recognition_text
    assert "skip=too_few_features" in recognition_text


def test_observation_recognition_log_renders_history_shortcut_path_without_rough_counters():
    bundle = {
        "visual_trace": {
            "match_path": "history_shortcut",
            "rough_index_source": "tile_index",
            "history_center_px": (20480.0, 21504.0),
            "history_radius_px": 300.0,
            "rough_hits": [],
        },
        "decision": {"coord": [100, 200, 30], "source": "visual", "reason": "visual_history_shortcut"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    recognition_text = "\n".join(line for log_type, line in routed if log_type == "recognition")
    tile_index_line = next(line for line in recognition_text.splitlines() if "tile_index:" in line)

    assert "path=history_shortcut" in tile_index_line
    assert "center=(20480.0, 21504.0)" in tile_index_line
    assert "radius=300.0" in tile_index_line
    assert "rough_candidates_available" not in tile_index_line
    assert "skipped_missing" not in tile_index_line
    assert "hsv_used" not in tile_index_line
    assert "orb_used" not in tile_index_line
    assert "orb_status" not in tile_index_line
    assert "rough_candidates_available" not in recognition_text
    assert "orb_status" not in recognition_text


def test_observation_recognition_log_includes_visual_failure_reason():
    bundle = {
        "visual_failure_reason": "no_usable_scale",
        "decision": {"coord": [100, 200, 30], "source": "ocr", "reason": "ocr_only"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    ocr_text = "\n".join(line for log_type, line in routed if log_type == "recognition")

    assert "visual_failure_reason=no_usable_scale" in ocr_text


def test_observation_recognition_log_includes_error_detail_when_present():
    bundle = {
        "visual_failure_reason": "observation_error",
        "error": "boom",
        "decision": {"coord": [100, 200, 30], "source": "ocr", "reason": "ocr_only"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    ocr_text = "\n".join(line for log_type, line in routed if log_type == "recognition")

    assert "visual_failure_reason=observation_error" in ocr_text
    assert "error=boom" in ocr_text


def test_observation_recognition_log_includes_heading_failure_reason():
    bundle = {
        "heading": None,
        "heading_failure_reason": "no_heading_match",
        "decision": {"coord": [100, 200, 30], "source": "ocr", "reason": "ocr_only"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    ocr_text = "\n".join(line for log_type, line in routed if log_type == "recognition")

    assert "heading: (none)" in ocr_text
    assert "heading_failure_reason=no_heading_match" in ocr_text


def test_observation_recognition_log_includes_frame_package_path():
    bundle = {
        "frame_package_path": "D:/tmp/package.json",
        "decision": {"coord": [100, 200, 30], "source": "ocr", "reason": "ocr_only"},
    }

    routed = list(route_observation_bundle(bundle, detailed_debug=True))
    ocr_text = "\n".join(line for log_type, line in routed if log_type == "recognition")

    assert "frame_package=D:/tmp/package.json" in ocr_text
