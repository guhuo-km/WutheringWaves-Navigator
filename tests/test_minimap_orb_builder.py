from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minimap_orb_builder import build_area_orb_index  # noqa: E402
from minimap_orb_index import score_words  # noqa: E402
import minimap_orb_builder  # noqa: E402

BLANK = np.zeros(32, dtype=np.uint8)
ONES = np.full(32, 0xFF, dtype=np.uint8)
HIGH_HALF = np.concatenate([np.full(16, 0xFF, dtype=np.uint8), np.zeros(16, dtype=np.uint8)])
LOW_HALF = np.concatenate([np.zeros(16, dtype=np.uint8), np.full(16, 0xFF, dtype=np.uint8)])

FIRST_WINDOW = ("base|17/3:2", np.array([BLANK, HIGH_HALF, BLANK], dtype=np.uint8))
SECOND_WINDOW = ("base|18/3:2", np.array([LOW_HALF, ONES], dtype=np.uint8))
EMPTY_WINDOW = ("base|19/3:2", np.zeros((0, 32), dtype=np.uint8))
WINDOWS = {
    "base__17_3_2": FIRST_WINDOW,
    "base__18_3_2": SECOND_WINDOW,
    "base__19_3_2": EMPTY_WINDOW,
}
# vocabulary_size above the corpus row count keeps K-Majority deterministic: every row
# seeds a centroid, so each descriptor keeps the word of its own pattern.
TRAIN = {"vocabulary_size": 10, "sample_limit": 100, "iterations": 2, "seed": 20260813}


def _write_fixture(index_root: Path, windows: dict[str, tuple[str, np.ndarray]]) -> None:
    rough = index_root / "rough_windows"
    descriptors = index_root / "orb_descriptors"
    rough.mkdir(parents=True)
    descriptors.mkdir(parents=True)
    for stem, (work_key, rows) in windows.items():
        (rough / f"{stem}.json").write_text(json.dumps({"work_key": work_key}), encoding="utf-8")
        np.save(descriptors / f"{stem}.npy", rows)


def _reference_words(rows: np.ndarray, vocabulary: np.ndarray) -> np.ndarray:
    """Brute-force Hamming nearest centroid, independent of the production quantizer."""
    query_bits = np.unpackbits(rows, axis=1).astype(np.int64)
    vocab_bits = np.unpackbits(vocabulary, axis=1).astype(np.int64)
    distances = np.bitwise_xor(query_bits[:, None, :], vocab_bits[None, :, :]).sum(axis=2)
    return distances.argmin(axis=1).astype(np.int32)


def _listing(index_root: Path) -> list[str]:
    return sorted(path.relative_to(index_root).as_posix() for path in index_root.rglob("*") if path.is_file())


def test_build_area_orb_index_keys_and_self_query(tmp_path: Path) -> None:
    index_root = tmp_path / "indexes"
    _write_fixture(index_root, WINDOWS)
    listing_before = _listing(index_root)

    index = build_area_orb_index(index_root, **TRAIN)

    assert index.document_keys == (FIRST_WINDOW[0], SECOND_WINDOW[0], EMPTY_WINDOW[0])
    assert index.vocabulary.dtype == np.uint8
    assert index.vocabulary.shape == (5, 32)
    assert sorted({bytes(row) for row in index.vocabulary}) == sorted(
        bytes(row) for row in (BLANK, HIGH_HALF, LOW_HALF, ONES)
    )
    assert index.inverted_index.document_count == 3
    assert index.inverted_index.word_offsets.shape == (6,)
    assert 2 not in set(index.inverted_index.document_ids.tolist())

    offsets = index.inverted_index.word_offsets
    posted_documents = index.inverted_index.document_ids
    posted_weights = index.inverted_index.weights
    for document_id, window in enumerate((FIRST_WINDOW, SECOND_WINDOW)):
        words = _reference_words(window[1], index.vocabulary)
        unique_words = sorted({int(word) for word in words.tolist()})
        assert len(unique_words) == 2
        assert len(window[1]) >= len(unique_words)

        for word in unique_words:
            start, end = int(offsets[word]), int(offsets[word + 1])
            assert posted_documents[start:end].tolist().count(document_id) == 1
            assert np.all(posted_weights[start:end] > 0.0)
        assert int(np.count_nonzero(posted_documents == document_id)) == len(unique_words)

        scores = score_words(index.inverted_index, words)
        expected = np.zeros(3, dtype=np.float32)
        expected[document_id] = 1.0
        np.testing.assert_allclose(scores, expected, atol=1e-6)
        assert int(np.argmax(scores)) == document_id

    assert posted_documents.size == 4
    assert _listing(index_root) == listing_before
    assert not (index_root / "orb_index.npz").exists()


def test_build_area_orb_index_empty_corpus(tmp_path: Path) -> None:
    index = build_area_orb_index(tmp_path / "missing_root", **TRAIN)

    assert index.document_keys == ()
    assert index.vocabulary.shape == (0, 32)
    assert index.inverted_index.document_count == 0
    assert index.inverted_index.word_offsets.tolist() == [0]
    assert index.inverted_index.document_ids.size == 0
    assert index.inverted_index.weights.size == 0
    assert index.inverted_index.idf.size == 0

    descriptor_root = tmp_path / "no_rows"
    _write_fixture(
        descriptor_root,
        {
            "base__20_3_2": ("base|20/3:2", np.zeros((0, 32), dtype=np.uint8)),
            "base__21_3_2": ("base|21/3:2", np.zeros((0, 32), dtype=np.uint8)),
        },
    )
    no_rows = build_area_orb_index(descriptor_root, **TRAIN)

    assert no_rows.document_keys == ("base|20/3:2", "base|21/3:2")
    assert no_rows.vocabulary.shape == (0, 32)
    assert no_rows.inverted_index.document_count == 2
    assert no_rows.inverted_index.word_offsets.tolist() == [0]

    (descriptor_root / "orb_descriptors" / "base__21_3_2.npy").unlink()
    with pytest.raises(FileNotFoundError):
        build_area_orb_index(descriptor_root, **TRAIN)


def test_build_area_orb_index_reuses_given_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_root = tmp_path / "indexes"
    _write_fixture(index_root, WINDOWS)
    real_train = minimap_orb_builder.train_binary_vocabulary
    trained_corpus_rows: list[int] = []

    def counting_train(descriptors: np.ndarray, **kwargs: object) -> np.ndarray:
        trained_corpus_rows.append(int(np.asarray(descriptors).shape[0]))
        return real_train(descriptors, **kwargs)

    monkeypatch.setattr(minimap_orb_builder, "train_binary_vocabulary", counting_train)
    trained = build_area_orb_index(index_root, **TRAIN)
    assert trained_corpus_rows == [FIRST_WINDOW[1].shape[0] + SECOND_WINDOW[1].shape[0]]

    def forbidden_train(descriptors: np.ndarray, **kwargs: object) -> np.ndarray:
        raise AssertionError("a given vocabulary must skip training")

    monkeypatch.setattr(minimap_orb_builder, "train_binary_vocabulary", forbidden_train)
    reused = build_area_orb_index(index_root, vocabulary=trained.vocabulary)

    assert trained_corpus_rows == [FIRST_WINDOW[1].shape[0] + SECOND_WINDOW[1].shape[0]]
    assert reused.document_keys == trained.document_keys
    np.testing.assert_array_equal(reused.vocabulary, trained.vocabulary)
    assert reused.inverted_index.document_count == trained.inverted_index.document_count
    for field in ("word_offsets", "document_ids", "weights", "idf"):
        np.testing.assert_array_equal(
            getattr(reused.inverted_index, field),
            getattr(trained.inverted_index, field),
        )
