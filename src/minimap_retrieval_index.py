from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class CandidateWindow:
    region_id: str
    window_id: str
    left: int
    top: int
    width: int
    height: int
    center_x: float
    center_y: float
    tile_min_x: int
    tile_max_x: int
    tile_min_y: int
    tile_max_y: int


@dataclass(frozen=True)
class RetrievalHit:
    candidate: CandidateWindow
    score: float
    rank: int


@dataclass(frozen=True)
class CandidateDescriptor:
    candidate: CandidateWindow
    vector: np.ndarray


def build_candidate_windows(
    *,
    region_id: str,
    map_left: int,
    map_top: int,
    map_width: int,
    map_height: int,
    window_size: int,
    stride: int,
    tile_size: int,
) -> list[CandidateWindow]:
    if window_size <= 0:
        raise ValueError("window_size must be positive")
    if stride <= 0:
        raise ValueError("stride must be positive")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")

    windows: list[CandidateWindow] = []
    max_left = map_left + map_width - window_size
    max_top = map_top + map_height - window_size
    if max_left < map_left or max_top < map_top:
        return windows

    row = 0
    y = map_top
    while y <= max_top:
        col = 0
        x = map_left
        while x <= max_left:
            center_x = x + window_size / 2.0
            center_y = y + window_size / 2.0
            tile_min_x = x // tile_size
            tile_max_x = (x + window_size - 1) // tile_size
            tile_min_y = y // tile_size
            tile_max_y = (y + window_size - 1) // tile_size
            windows.append(
                CandidateWindow(
                    region_id=str(region_id),
                    window_id=f"{region_id}:{row}:{col}:{x}:{y}",
                    left=int(x),
                    top=int(y),
                    width=int(window_size),
                    height=int(window_size),
                    center_x=float(center_x),
                    center_y=float(center_y),
                    tile_min_x=int(tile_min_x),
                    tile_max_x=int(tile_max_x),
                    tile_min_y=int(tile_min_y),
                    tile_max_y=int(tile_max_y),
                )
            )
            col += 1
            x += stride
        row += 1
        y += stride
    return windows


def compute_hsv_texture_descriptor(image_bgr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("image_bgr must be a BGR image")
    if mask is not None:
        if mask.ndim != 2:
            raise ValueError("mask must be a single-channel image")
        if mask.shape[:2] != image_bgr.shape[:2]:
            raise ValueError("mask shape must match image_bgr")
        descriptor_mask = mask.astype(np.uint8)
    else:
        descriptor_mask = None

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist(
        [hsv],
        [0, 1, 2],
        descriptor_mask,
        [12, 6, 4],
        [0, 180, 0, 256, 0, 256],
    ).astype(np.float32).reshape(-1)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(sobel_x, sobel_y)
    if descriptor_mask is not None and np.any(descriptor_mask):
        selected_gray = gray[descriptor_mask > 0]
        selected_magnitude = magnitude[descriptor_mask > 0]
    else:
        selected_gray = gray.reshape(-1)
        selected_magnitude = magnitude.reshape(-1)
    texture = np.array(
        [
            float(np.mean(selected_gray)) / 255.0,
            float(np.std(selected_gray)) / 255.0,
            float(np.mean(selected_magnitude)) / 255.0,
            float(np.std(selected_magnitude)) / 255.0,
        ],
        dtype=np.float32,
    )

    vector = np.concatenate([hist, texture]).astype(np.float32)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector


def retrieve_top_k(
    query_vector: np.ndarray,
    descriptors: list[CandidateDescriptor],
    *,
    top_k: int,
) -> list[RetrievalHit]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not descriptors:
        return []

    query = query_vector.astype(np.float32)
    query_norm = float(np.linalg.norm(query))
    if query_norm > 0:
        query = query / query_norm

    scored: list[tuple[float, CandidateWindow]] = []
    for item in descriptors:
        vector = item.vector.astype(np.float32)
        vector_norm = float(np.linalg.norm(vector))
        if vector_norm > 0:
            vector = vector / vector_norm
        scored.append((float(np.dot(query, vector)), item.candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        RetrievalHit(candidate=candidate, score=score, rank=index + 1)
        for index, (score, candidate) in enumerate(scored[:top_k])
    ]
