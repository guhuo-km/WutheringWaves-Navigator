from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from minimap_orb_index import OrbInvertedIndex

ORB_AREA_INDEX_NAME = "orb_index.npz"
DOCUMENT_KEYS_FIELD = "document_keys"
VOCABULARY_FIELD = "vocabulary"
WORD_OFFSETS_FIELD = "word_offsets"
DOCUMENT_IDS_FIELD = "document_ids"
WEIGHTS_FIELD = "weights"
IDF_FIELD = "idf"
DOCUMENT_COUNT_FIELD = "document_count"


@dataclass(frozen=True)
class OrbAreaIndex:
    """Persisted per-area ORB product: document keys, vocabulary, inverted index."""

    document_keys: tuple[str, ...]
    vocabulary: np.ndarray
    inverted_index: OrbInvertedIndex


def save_orb_area_index(path: Path, index: OrbAreaIndex) -> None:
    """Write the area product atomically so a reader never sees a half file."""
    path = Path(path)
    inverted = index.inverted_index
    arrays = {
        DOCUMENT_KEYS_FIELD: np.asarray(index.document_keys, dtype=np.str_),
        VOCABULARY_FIELD: np.ascontiguousarray(index.vocabulary, dtype=np.uint8),
        WORD_OFFSETS_FIELD: np.ascontiguousarray(inverted.word_offsets, dtype=np.int64),
        DOCUMENT_IDS_FIELD: np.ascontiguousarray(inverted.document_ids, dtype=np.int32),
        WEIGHTS_FIELD: np.ascontiguousarray(inverted.weights, dtype=np.float32),
        IDF_FIELD: np.ascontiguousarray(inverted.idf, dtype=np.float32),
        DOCUMENT_COUNT_FIELD: np.asarray(int(inverted.document_count), dtype=np.int64),
    }

    tmp = path.with_suffix(path.suffix + ".tmp.npz")
    with open(tmp, "wb") as handle:
        np.savez_compressed(handle, **arrays)
    tmp.replace(path)


def load_orb_area_index(path: Path) -> OrbAreaIndex:
    """Read the area product; a missing or damaged file raises to the caller."""
    with np.load(Path(path), allow_pickle=False) as data:
        document_keys = tuple(str(key) for key in data[DOCUMENT_KEYS_FIELD].tolist())
        vocabulary = np.array(data[VOCABULARY_FIELD], dtype=np.uint8, copy=True)
        inverted = OrbInvertedIndex(
            word_offsets=np.array(data[WORD_OFFSETS_FIELD], dtype=np.int64, copy=True),
            document_ids=np.array(data[DOCUMENT_IDS_FIELD], dtype=np.int32, copy=True),
            weights=np.array(data[WEIGHTS_FIELD], dtype=np.float32, copy=True),
            idf=np.array(data[IDF_FIELD], dtype=np.float32, copy=True),
            document_count=int(data[DOCUMENT_COUNT_FIELD]),
        )
    return OrbAreaIndex(document_keys=document_keys, vocabulary=vocabulary, inverted_index=inverted)
