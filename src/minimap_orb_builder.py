from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from minimap_orb_index import (
    ORB_DESCRIPTOR_BYTES,
    OrbInvertedIndex,
    build_inverted_index,
    quantize_descriptors,
    train_binary_vocabulary,
)
from minimap_orb_store import OrbAreaIndex

ROUGH_FOLDER = "rough_windows"
DESCRIPTOR_FOLDER = "orb_descriptors"

DEFAULT_VOCABULARY_SIZE = 20000
DEFAULT_SAMPLE_LIMIT = 200000
DEFAULT_ITERATIONS = 12
DEFAULT_SEED = 20260813


def build_area_orb_index(
    index_root: Path,
    *,
    vocabulary: np.ndarray | None = None,
    vocabulary_size: int = DEFAULT_VOCABULARY_SIZE,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> OrbAreaIndex:
    """Assemble one area's ORB product from the indexer's rough window artifacts.

    Documents are the ``rough_windows/*.json`` files in file-name order, keyed by
    their ``work_key``; each window's descriptors come from the identically named
    ``orb_descriptors/<stem>.npy`` the indexer writes. A missing file raises.
    ``vocabulary`` skips training and quantizes every window with the given centers.
    """
    index_root = Path(index_root)

    document_keys: list[str] = []
    window_descriptors: list[np.ndarray] = []
    for json_path in sorted((index_root / ROUGH_FOLDER).glob("*.json"), key=lambda item: item.name):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        document_keys.append(str(payload["work_key"]))
        npy_path = index_root / DESCRIPTOR_FOLDER / f"{json_path.stem}.npy"
        window_descriptors.append(_read_descriptors(npy_path))

    if vocabulary is None:
        if window_descriptors:
            corpus = np.concatenate(window_descriptors, axis=0)
        else:
            corpus = np.zeros((0, ORB_DESCRIPTOR_BYTES), dtype=np.uint8)
        vocabulary = train_binary_vocabulary(
            corpus,
            vocabulary_size=int(vocabulary_size),
            sample_limit=int(sample_limit),
            iterations=int(iterations),
            seed=int(seed),
        )
    if vocabulary.shape[0] == 0:
        return OrbAreaIndex(
            document_keys=tuple(document_keys),
            vocabulary=vocabulary,
            inverted_index=_empty_inverted_index(len(document_keys)),
        )

    word_lists = [quantize_descriptors(descriptors, vocabulary) for descriptors in window_descriptors]
    return OrbAreaIndex(
        document_keys=tuple(document_keys),
        vocabulary=vocabulary,
        inverted_index=build_inverted_index(word_lists, int(vocabulary.shape[0])),
    )


def _read_descriptors(path: Path) -> np.ndarray:
    with open(path, "rb") as handle:
        descriptors = np.load(handle, allow_pickle=False)
    return np.ascontiguousarray(np.asarray(descriptors, dtype=np.uint8).reshape(-1, ORB_DESCRIPTOR_BYTES))


def _empty_inverted_index(document_count: int) -> OrbInvertedIndex:
    return OrbInvertedIndex(
        word_offsets=np.zeros(1, dtype=np.int64),
        document_ids=np.zeros(0, dtype=np.int32),
        weights=np.zeros(0, dtype=np.float32),
        idf=np.zeros(0, dtype=np.float32),
        document_count=int(document_count),
    )
