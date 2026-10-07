from __future__ import annotations

from pathlib import Path

import numpy as np

from minimap_orb_index import extract_orb_descriptors, quantize_descriptors, score_words
from minimap_orb_store import OrbAreaIndex, load_orb_area_index


class OrbQueryIndex:
    """Score one query window against a persisted per-area ORB product.

    Keeps only the most recently loaded product, reloaded when its file stamp
    changes. A product with an empty vocabulary is never quantized: every
    window scores zero. Missing or damaged products raise to the caller:
    readiness checks belong to the caller, not here.
    """

    def __init__(self) -> None:
        self._cache: tuple[tuple[str, int, int], OrbAreaIndex] | None = None

    def _index_for(self, path: Path) -> OrbAreaIndex:
        stat = path.stat()
        stamp = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
        cached = self._cache
        if cached is not None and cached[0] == stamp:
            return cached[1]
        index = load_orb_area_index(path)
        self._cache = (stamp, index)
        return index

    def score(
        self,
        path: Path,
        image: np.ndarray,
    ) -> tuple[tuple[str, ...], np.ndarray]:
        """Return (document_keys, scores) with scores aligned to the keys, float32."""
        index = self._index_for(Path(path))
        if index.vocabulary.size == 0:
            return index.document_keys, np.zeros(
                index.inverted_index.document_count, dtype=np.float32
            )
        descriptors = extract_orb_descriptors(image)
        words = quantize_descriptors(descriptors, index.vocabulary)
        scores = score_words(index.inverted_index, words)
        return index.document_keys, scores
