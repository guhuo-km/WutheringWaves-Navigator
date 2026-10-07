from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

ORB_NFEATURES = 800
ORB_DESCRIPTOR_BYTES = 32


@dataclass(frozen=True)
class OrbInvertedIndex:
    """Word-major TF-IDF inverted index over ORB bag-of-words windows.

    ``word_offsets`` has ``vocabulary_size + 1`` entries; the postings of word
    ``w`` occupy ``document_ids[word_offsets[w]:word_offsets[w + 1]]``.
    """

    word_offsets: np.ndarray
    document_ids: np.ndarray
    weights: np.ndarray
    idf: np.ndarray
    document_count: int


def _normalized_tfidf(words: np.ndarray, idf: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the (word id, weight) pairs of one L2-normalised TF-IDF row."""
    if words.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)
    counts = np.bincount(words, minlength=idf.shape[0]).astype(np.float64)
    tfidf = (counts / counts.sum()) * idf.astype(np.float64)
    norm = float(np.linalg.norm(tfidf))
    if norm > 0.0:
        tfidf /= norm
    present = np.flatnonzero(tfidf)
    return present, tfidf[present].astype(np.float32)


def build_inverted_index(
    word_lists: Sequence[np.ndarray],
    vocabulary_size: int,
) -> OrbInvertedIndex:
    if vocabulary_size <= 0:
        raise ValueError("vocabulary_size must be positive")

    window_count = len(word_lists)
    flattened: list[np.ndarray] = []
    df = np.zeros(vocabulary_size, dtype=np.float64)
    for words in word_lists:
        flat = np.asarray(words, dtype=np.int64).ravel()
        if flat.size and (flat.min() < 0 or flat.max() >= vocabulary_size):
            raise ValueError("word id out of vocabulary range")
        flattened.append(flat)
        if flat.size:
            df[np.unique(flat)] += 1.0

    idf = (np.log((float(window_count) + 1.0) / (df + 1.0)) + 1.0).astype(np.float32)

    posting_lengths = np.zeros(vocabulary_size, dtype=np.int64)
    entries: list[tuple[int, np.ndarray, np.ndarray]] = []
    for document_id, flat in enumerate(flattened):
        present, weights = _normalized_tfidf(flat, idf)
        if present.size == 0:
            continue
        posting_lengths[present] += 1
        entries.append((document_id, present, weights))

    word_offsets = np.zeros(vocabulary_size + 1, dtype=np.int64)
    np.cumsum(posting_lengths, out=word_offsets[1:])

    total = int(word_offsets[-1])
    document_ids = np.empty(total, dtype=np.int32)
    posting_weights = np.empty(total, dtype=np.float32)
    cursor = word_offsets[:-1].copy()
    for document_id, present, weights in entries:
        positions = cursor[present]
        document_ids[positions] = document_id
        posting_weights[positions] = weights
        cursor[present] += 1

    return OrbInvertedIndex(
        word_offsets=word_offsets,
        document_ids=document_ids,
        weights=posting_weights,
        idf=idf,
        document_count=window_count,
    )


def score_words(index: OrbInvertedIndex, query_words: np.ndarray) -> np.ndarray:
    scores = np.zeros(index.document_count, dtype=np.float32)
    flat = np.asarray(query_words, dtype=np.int64).ravel()
    if flat.size == 0:
        return scores
    if flat.min() < 0 or flat.max() >= index.idf.shape[0]:
        raise ValueError("word id out of vocabulary range")

    present, query_weights = _normalized_tfidf(flat, index.idf)
    for word, query_weight in zip(present, query_weights):
        start = int(index.word_offsets[word])
        end = int(index.word_offsets[word + 1])
        if start == end:
            continue
        np.add.at(
            scores,
            index.document_ids[start:end],
            index.weights[start:end] * query_weight,
        )
    return scores


def extract_orb_descriptors(image: np.ndarray, nfeatures: int = ORB_NFEATURES) -> np.ndarray:
    """ORB descriptors of one window as contiguous uint8 rows, ``(0, 32)`` when empty."""
    detector = cv2.ORB_create(nfeatures=int(nfeatures))
    _keypoints, descriptors = detector.detectAndCompute(image, None)
    if descriptors is None or len(descriptors) == 0:
        return np.zeros((0, ORB_DESCRIPTOR_BYTES), dtype=np.uint8)
    return np.ascontiguousarray(descriptors, dtype=np.uint8)


def quantize_descriptors(descriptors: np.ndarray, vocabulary: np.ndarray) -> np.ndarray:
    """Assign each descriptor its nearest vocabulary word id under Hamming distance."""
    centroids = np.ascontiguousarray(np.asarray(vocabulary, dtype=np.uint8).reshape(-1, ORB_DESCRIPTOR_BYTES))
    if centroids.shape[0] == 0:
        raise ValueError("vocabulary must not be empty")
    rows = np.ascontiguousarray(np.asarray(descriptors, dtype=np.uint8).reshape(-1, ORB_DESCRIPTOR_BYTES))
    if rows.shape[0] == 0:
        return np.zeros(0, dtype=np.int32)

    import faiss

    flat = faiss.IndexBinaryFlat(ORB_DESCRIPTOR_BYTES * 8)
    flat.add(centroids)
    _distances, labels = flat.search(rows, 1)
    return np.asarray(labels[:, 0], dtype=np.int32)


def _binary_kmeans(data: np.ndarray, vocabulary_size: int, iterations: int, rng) -> np.ndarray:
    """K-Majority binary k-means; faiss.IndexBinaryFlat is the Hamming assigner."""
    import faiss

    total = int(data.shape[0])
    vocabulary_size = min(int(vocabulary_size), total)
    if vocabulary_size <= 0 or total == 0:
        return np.zeros((0, ORB_DESCRIPTOR_BYTES), dtype=np.uint8)
    centroids = np.ascontiguousarray(
        data[rng.choice(total, size=vocabulary_size, replace=False)], dtype=np.uint8
    )
    bits = np.unpackbits(data, axis=1).astype(np.int64)
    for _ in range(max(1, int(iterations))):
        flat = faiss.IndexBinaryFlat(ORB_DESCRIPTOR_BYTES * 8)
        flat.add(centroids)
        _distances, labels = flat.search(data, 1)
        words = labels[:, 0]
        accumulator = np.zeros((vocabulary_size, ORB_DESCRIPTOR_BYTES * 8), dtype=np.int64)
        np.add.at(accumulator, words, bits)
        counts = np.bincount(words, minlength=vocabulary_size).astype(np.float64)
        majority = (accumulator > (counts[:, None] / 2.0)).astype(np.uint8)
        new_centroids = np.packbits(majority, axis=1)
        empty = counts == 0
        if empty.any():
            new_centroids[empty] = centroids[empty]
        new_centroids = np.ascontiguousarray(new_centroids, dtype=np.uint8)
        if np.array_equal(new_centroids, centroids):
            return new_centroids
        centroids = new_centroids
    return np.ascontiguousarray(centroids, dtype=np.uint8)


def train_binary_vocabulary(
    descriptors: np.ndarray,
    vocabulary_size: int = 20000,
    sample_limit: int = 200000,
    iterations: int = 12,
    seed: int = 20260813,
) -> np.ndarray:
    """Train binary vocabulary centers with the lab's K-Majority binary k-means."""
    data = np.ascontiguousarray(
        np.asarray(descriptors, dtype=np.uint8).reshape(-1, ORB_DESCRIPTOR_BYTES)
    )
    total = int(data.shape[0])
    rng = np.random.default_rng(int(seed))
    limit = min(int(sample_limit), total)
    if total > limit:
        pick = rng.permutation(total)[:limit]
        sample = np.ascontiguousarray(data[pick], dtype=np.uint8)
    else:
        sample = data
    return _binary_kmeans(sample, int(vocabulary_size), int(iterations), rng)
