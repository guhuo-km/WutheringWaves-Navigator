from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minimap_orb_index import build_inverted_index, score_words  # noqa: E402
from minimap_orb_store import OrbAreaIndex, load_orb_area_index, save_orb_area_index  # noqa: E402

VOCABULARY = np.arange(4 * 32, dtype=np.uint8).reshape(4, 32)
DOCUMENT_KEYS = ("area|layer|0|0", "区域|层|1|0", "area|layer|2|1")
WORD_LISTS = [
    np.array([0, 1, 1, 3], dtype=np.int64),
    np.array([], dtype=np.int64),
    np.array([2, 2, 2], dtype=np.int64),
]
QUERY_WORDS = np.array([1, 1, 2], dtype=np.int64)


def test_orb_area_index_roundtrip(tmp_path: Path) -> None:
    index = OrbAreaIndex(
        document_keys=DOCUMENT_KEYS,
        vocabulary=VOCABULARY,
        inverted_index=build_inverted_index(WORD_LISTS, VOCABULARY.shape[0]),
    )
    path = tmp_path / "orb_area.npz"

    save_orb_area_index(path, index)
    loaded = load_orb_area_index(path)

    assert loaded.document_keys == DOCUMENT_KEYS
    assert np.array_equal(loaded.vocabulary, VOCABULARY)
    assert loaded.vocabulary.dtype == np.uint8
    assert loaded.inverted_index.document_count == index.inverted_index.document_count
    assert np.array_equal(
        loaded.inverted_index.word_offsets,
        index.inverted_index.word_offsets,
    )
    assert np.array_equal(
        loaded.inverted_index.document_ids,
        index.inverted_index.document_ids,
    )
    np.testing.assert_allclose(loaded.inverted_index.weights, index.inverted_index.weights)
    np.testing.assert_allclose(loaded.inverted_index.idf, index.inverted_index.idf)
    np.testing.assert_allclose(
        score_words(loaded.inverted_index, QUERY_WORDS),
        score_words(index.inverted_index, QUERY_WORDS),
    )

    with np.load(path, allow_pickle=False) as data:
        for name in data.files:
            assert data[name].dtype != np.dtype(object), name
        assert data["document_keys"].dtype.kind == "U"

    assert not list(tmp_path.glob("*.tmp.npz"))
