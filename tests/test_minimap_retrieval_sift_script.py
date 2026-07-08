from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import cv2
import pytest


def _load_experiment_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "experiment_minimap_retrieval_sift.py"
    spec = importlib.util.spec_from_file_location("experiment_minimap_retrieval_sift", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sample_images_from_args_prefers_explicit_sample_image(tmp_path):
    module = _load_experiment_module()
    sample = tmp_path / "one.png"
    sample.write_bytes(b"not-used-by-this-test")

    args = argparse.Namespace(sample_image=sample, sample_dir=None)

    assert module._sample_images_from_args(args) == [sample]


def test_sample_images_from_args_lists_supported_images_in_name_order(tmp_path):
    module = _load_experiment_module()
    (tmp_path / "b.png").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "c.txt").write_text("ignored", encoding="utf-8")

    args = argparse.Namespace(sample_image=None, sample_dir=tmp_path)

    samples = module._sample_images_from_args(args)

    assert [path.name for path in samples] == ["a.jpg", "b.png"]


def test_full_experiment_sample_dir_writes_batch_manifest_without_visual_validation(tmp_path, monkeypatch):
    module = _load_experiment_module()
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    (sample_dir / "b.png").write_bytes(b"")
    (sample_dir / "a.png").write_bytes(b"")
    output_dir = tmp_path / "out"

    def fake_run_for_sample(args, sample_image, timestamp):
        bundle_dir = Path(args.output_dir) / timestamp / sample_image.stem
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "review_manifest.json").write_text(
            json.dumps(
                {
                    "human_confirmation_required": True,
                    "script_made_success_decision": False,
                    "sample_image": str(sample_image),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return bundle_dir

    real_datetime = module.datetime

    class FakeDateTime:
        @staticmethod
        def now():
            return real_datetime(2026, 7, 7, 6, 30, 0)

    monkeypatch.setattr(module, "_run_full_experiment_for_sample", fake_run_for_sample)
    monkeypatch.setattr(module, "datetime", FakeDateTime)

    args = argparse.Namespace(
        sample_image=None,
        sample_dir=sample_dir,
        output_dir=output_dir,
    )

    module._run_full_experiment(args)

    manifest_path = output_dir / "20260707_063000" / "batch_review_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["human_confirmation_required"] is True
    assert payload["script_made_success_decision"] is False
    assert payload["sample_count"] == 2
    assert [Path(item["sample_image"]).name for item in payload["samples"]] == ["a.png", "b.png"]
    assert all(item["review_manifest"].endswith("review_manifest.json") for item in payload["samples"])


def test_parse_legacy_flat_tile_key_from_layer_directory(tmp_path):
    module = _load_experiment_module()
    root = tmp_path / "processed_layered_tiles" / "8" / "0"
    root.mkdir(parents=True)
    path = root / "8_0_-1_-2.png"
    path.write_bytes(b"")

    key = module._parse_tile_key_from_cache_path(root, path)

    assert key.area_id == "8"
    assert key.layer_id == "0"
    assert key.kind == "standard"
    assert key.z_level is None
    assert key.x == -1
    assert key.y == -2


class FakeDMatch:
    def __init__(self, query_idx: int, train_idx: int):
        self.queryIdx = query_idx
        self.trainIdx = train_idx


def test_similarity_estimate_maps_query_center_with_scale():
    module = _load_experiment_module()
    query_keypoints = [
        cv2.KeyPoint(10, 10, 3),
        cv2.KeyPoint(110, 10, 3),
        cv2.KeyPoint(10, 60, 3),
        cv2.KeyPoint(110, 60, 3),
    ]
    candidate_global_xy = module.np.array(
        [
            [120, 70],
            [320, 70],
            [120, 170],
            [320, 170],
        ],
        dtype=module.np.float32,
    )
    matches = [FakeDMatch(index, index) for index in range(4)]

    estimate = module._estimate_similarity_from_matches(
        query_keypoints,
        candidate_global_xy,
        matches,
        query_width=120,
        query_height=70,
    )

    assert estimate["estimated_global_x"] == pytest.approx(100.0, abs=0.01)
    assert estimate["estimated_global_y"] == pytest.approx(50.0, abs=0.01)
    assert estimate["estimated_center_x"] == pytest.approx(220.0, abs=0.01)
    assert estimate["estimated_center_y"] == pytest.approx(120.0, abs=0.01)
    assert estimate["query_to_map_scale_x"] == pytest.approx(2.0, abs=0.01)
    assert estimate["query_to_map_scale_y"] == pytest.approx(2.0, abs=0.01)
    assert len(estimate["inlier_matches"]) == 4


def test_select_best_sift_candidate_prefers_more_inliers_then_good_matches_then_rank():
    module = _load_experiment_module()

    best = module._select_best_sift_candidate(
        [
            {"rank": 1, "good_match_count": 30, "inlier_count": 4},
            {"rank": 2, "good_match_count": 10, "inlier_count": 5},
            {"rank": 3, "good_match_count": 11, "inlier_count": 5},
            {"rank": 4, "good_match_count": 11, "inlier_count": 5},
        ]
    )

    assert best["rank"] == 3
