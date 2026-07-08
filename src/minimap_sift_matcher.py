from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class SiftCandidateMatch:
    candidate_id: str
    raw_match_count: int
    good_match_count: int
    inlier_count: int
    estimated_global_x: float | None
    estimated_global_y: float | None
    homography: list[list[float]] | None
    reason: str


def filter_ratio_matches(knn_matches, *, ratio: float = 0.75):
    if not 0 < ratio < 1:
        raise ValueError("ratio must be between 0 and 1")
    good = []
    for pair in knn_matches:
        if len(pair) != 2:
            continue
        first, second = pair
        if first.distance < ratio * second.distance:
            good.append(first)
    return good


def estimate_similarity_from_matches(
    query_keypoints,
    candidate_global_xy: np.ndarray,
    good_matches,
    *,
    query_width: int,
    query_height: int,
) -> dict:
    if len(good_matches) < 3:
        return {
            "estimated_global_x": None,
            "estimated_global_y": None,
            "estimated_center_x": None,
            "estimated_center_y": None,
            "query_to_map_scale_x": None,
            "query_to_map_scale_y": None,
            "query_to_map_matrix": None,
            "inlier_matches": [],
        }

    query_points = np.array(
        [query_keypoints[match.queryIdx].pt for match in good_matches],
        dtype=np.float32,
    )
    map_points = np.array(
        [candidate_global_xy[match.trainIdx] for match in good_matches],
        dtype=np.float32,
    )
    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        query_points,
        map_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=12.0,
        maxIters=2000,
        confidence=0.99,
        refineIters=10,
    )
    if matrix is None:
        return {
            "estimated_global_x": None,
            "estimated_global_y": None,
            "estimated_center_x": None,
            "estimated_center_y": None,
            "query_to_map_scale_x": None,
            "query_to_map_scale_y": None,
            "query_to_map_matrix": None,
            "inlier_matches": [],
        }

    if inlier_mask is None:
        inlier_matches = list(good_matches)
    else:
        flat_mask = inlier_mask.reshape(-1).astype(bool)
        inlier_matches = [
            match
            for match, keep in zip(good_matches, flat_mask)
            if bool(keep)
        ]

    top_left = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    center = np.array([float(query_width) / 2.0, float(query_height) / 2.0, 1.0], dtype=np.float64)
    estimated_top_left = matrix @ top_left
    estimated_center = matrix @ center
    scale_x = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    scale_y = float(np.hypot(matrix[0, 1], matrix[1, 1]))
    return {
        "estimated_global_x": float(estimated_top_left[0]),
        "estimated_global_y": float(estimated_top_left[1]),
        "estimated_center_x": float(estimated_center[0]),
        "estimated_center_y": float(estimated_center[1]),
        "query_to_map_scale_x": scale_x,
        "query_to_map_scale_y": scale_y,
        "query_to_map_matrix": matrix.astype(float).tolist(),
        "inlier_matches": inlier_matches,
    }


def select_best_sift_candidate(results: list[dict]) -> dict | None:
    if not results:
        return None
    return max(
        results,
        key=lambda item: (
            int(item.get("inlier_count") or 0),
            int(item.get("good_match_count") or 0),
            -int(item.get("rank") or 999999),
        ),
    )
