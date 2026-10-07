from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minimap_orb_index import (  # noqa: E402
    build_inverted_index,
    extract_orb_descriptors,
    quantize_descriptors,
    score_words,
    train_binary_vocabulary,
)

VOCABULARY_SIZE = 5
WORD_LISTS = [
    np.array([0, 1, 1, 3], dtype=np.uint8),
    np.array([], dtype=np.uint8),
    np.array([2, 2, 2], dtype=np.uint8),
    np.array([1, 4], dtype=np.uint8),
]


def dense_reference(word_lists, vocabulary_size, query_words):
    """Independent window-by-word dense TF-IDF, written straight from the formula."""
    window_count = len(word_lists)
    df = np.zeros(vocabulary_size, dtype=np.float64)
    for words in word_lists:
        for word in set(int(value) for value in words.tolist()):
            df[word] += 1.0
    idf = np.log((window_count + 1.0) / (df + 1.0)) + 1.0

    matrix = np.zeros((window_count, vocabulary_size), dtype=np.float64)
    for index, words in enumerate(word_lists):
        for word in (int(value) for value in words.tolist()):
            matrix[index, word] += 1.0
        total = matrix[index].sum()
        if total > 0.0:
            matrix[index] = (matrix[index] / total) * idf
            norm = np.linalg.norm(matrix[index])
            if norm > 0.0:
                matrix[index] /= norm

    query = np.zeros(vocabulary_size, dtype=np.float64)
    for word in (int(value) for value in query_words.tolist()):
        query[word] += 1.0
    total = query.sum()
    if total > 0.0:
        query = (query / total) * idf
        norm = np.linalg.norm(query)
        if norm > 0.0:
            query /= norm
        return matrix @ query, idf
    return np.zeros(window_count, dtype=np.float64), idf


def test_index_layout_and_idf():
    index = build_inverted_index(WORD_LISTS, VOCABULARY_SIZE)

    assert index.document_count == 4
    assert index.word_offsets.shape == (VOCABULARY_SIZE + 1,)
    assert index.word_offsets.dtype == np.int64
    assert index.document_ids.dtype == np.int32
    assert index.weights.dtype == np.float32
    assert index.idf.dtype == np.float32

    expected_idf = np.log((4.0 + 1.0) / (np.array([1.0, 2.0, 1.0, 1.0, 1.0]) + 1.0)) + 1.0
    np.testing.assert_allclose(index.idf, expected_idf.astype(np.float32), rtol=1e-6)

    # Postings are grouped by word, document ids ascend inside each posting, and the
    # empty window (id 1) never appears.
    assert len(index.document_ids) == int(index.word_offsets[-1])
    for word in range(VOCABULARY_SIZE):
        docs = index.document_ids[index.word_offsets[word] : index.word_offsets[word + 1]]
        assert np.all(np.diff(docs) > 0)
    assert 1 not in index.document_ids.tolist()
    assert index.document_ids.tolist().count(0) == 3  # words 0, 1, 3
    assert index.document_ids.tolist().count(2) == 1  # word 2 only
    assert index.document_ids.tolist().count(3) == 2  # words 1, 4

    # Every non-empty window row is L2-normalised.
    for document_id in (0, 2, 3):
        row = np.zeros(VOCABULARY_SIZE, dtype=np.float64)
        for word in range(VOCABULARY_SIZE):
            docs = index.document_ids[index.word_offsets[word] : index.word_offsets[word + 1]]
            weights = index.weights[index.word_offsets[word] : index.word_offsets[word + 1]]
            hit = np.flatnonzero(docs == document_id)
            if hit.size:
                row[word] = float(weights[hit[0]])
        np.testing.assert_allclose(np.linalg.norm(row), 1.0, rtol=1e-5)


def test_scores_match_dense_formula_and_ranking():
    index = build_inverted_index(WORD_LISTS, VOCABULARY_SIZE)

    for query_words in (
        np.array([1, 1, 2], dtype=np.uint8),
        np.array([0], dtype=np.uint8),
        np.array([4, 4, 1], dtype=np.uint8),
    ):
        expected, _ = dense_reference(WORD_LISTS, VOCABULARY_SIZE, query_words)
        actual = score_words(index, query_words)
        assert actual.dtype == np.float32
        np.testing.assert_allclose(actual, expected.astype(np.float32), rtol=1e-5, atol=1e-7)
        np.testing.assert_array_equal(np.argsort(-actual), np.argsort(-expected))

    # Word 2 lives only in window 2, so that window must rank first.
    assert int(np.argmax(score_words(index, np.array([2, 2], dtype=np.uint8)))) == 2


def test_empty_query_returns_zero_scores():
    index = build_inverted_index(WORD_LISTS, VOCABULARY_SIZE)
    scores = score_words(index, np.array([], dtype=np.uint8))
    assert scores.dtype == np.float32
    assert scores.shape == (4,)
    np.testing.assert_array_equal(scores, np.zeros(4, dtype=np.float32))


def test_quantize_matches_dense_hamming():
    vocabulary = np.array(
        [
            np.full(32, 0x00, dtype=np.uint8),
            np.full(32, 0xFF, dtype=np.uint8),
            np.full(32, 0x0F, dtype=np.uint8),
            np.full(32, 0xF0, dtype=np.uint8),
        ],
        dtype=np.uint8,
    )
    near_blank = np.full(32, 0x00, dtype=np.uint8)
    near_blank[-1] = 0x01
    half_ones = np.concatenate([np.full(20, 0xFF, dtype=np.uint8), np.full(12, 0x00, dtype=np.uint8)])
    descriptors = np.array(
        [
            near_blank,
            np.full(32, 0xFF, dtype=np.uint8),
            np.full(32, 0x0F, dtype=np.uint8),
            half_ones,
            np.full(32, 0x00, dtype=np.uint8),
        ],
        dtype=np.uint8,
    )

    query_bits = np.unpackbits(descriptors, axis=1).astype(np.int64)
    vocab_bits = np.unpackbits(vocabulary, axis=1).astype(np.int64)
    distances = np.bitwise_xor(query_bits[:, None, :], vocab_bits[None, :, :]).sum(axis=2)
    expected = distances.argmin(axis=1)
    ordered = np.sort(distances, axis=1)
    assert np.all(ordered[:, 0] < ordered[:, 1])  # no ties, so both paths are unambiguous

    words = quantize_descriptors(descriptors, vocabulary)
    assert words.dtype == np.int32
    assert words.shape == (5,)
    np.testing.assert_array_equal(words, expected.astype(np.int32))
    np.testing.assert_array_equal(words, np.array([0, 1, 2, 1, 0], dtype=np.int32))

    empty_words = quantize_descriptors(np.zeros((0, 32), dtype=np.uint8), vocabulary)
    assert empty_words.dtype == np.int32
    assert empty_words.shape == (0,)

    with pytest.raises(ValueError):
        quantize_descriptors(descriptors, np.zeros((0, 32), dtype=np.uint8))


def test_train_binary_vocabulary_two_cluster_majority():
    left = np.concatenate([np.full(16, 0xFF, dtype=np.uint8), np.zeros(16, dtype=np.uint8)])
    left_majority = np.concatenate([np.full(15, 0xFF, dtype=np.uint8), np.zeros(17, dtype=np.uint8)])
    right = np.concatenate([np.zeros(16, dtype=np.uint8), np.full(16, 0xFF, dtype=np.uint8)])
    right_majority = np.concatenate([np.zeros(17, dtype=np.uint8), np.full(15, 0xFF, dtype=np.uint8)])

    # 20 of the 25 members of each cluster clear the boundary byte, so the centre is
    # the majority variant, not the plain half pattern. The clusters sit 240 bits
    # apart, so assignment cannot depend on which rows the seed draws first.
    data = np.array(
        [left_majority] * 20 + [left] * 5 + [right_majority] * 20 + [right] * 5,
        dtype=np.uint8,
    )

    trained = train_binary_vocabulary(data, vocabulary_size=2, seed=20260813)
    assert trained.dtype == np.uint8
    assert trained.shape == (2, 32)
    assert trained.flags["C_CONTIGUOUS"]
    np.testing.assert_array_equal(
        trained[np.argsort(trained[:, 0])],
        np.array([right_majority, left_majority], dtype=np.uint8),
    )

    # The fixed seed is reproducible; a single centre shows the strict-majority rule:
    # an exact 50/50 split clears every bit, 51/49 keeps the majority side.
    replay = train_binary_vocabulary(data, vocabulary_size=2, seed=20260813)
    np.testing.assert_array_equal(replay, trained)

    tie = np.array([left] * 25 + [right] * 25, dtype=np.uint8)
    np.testing.assert_array_equal(
        train_binary_vocabulary(tie, vocabulary_size=1, seed=20260813),
        np.zeros((1, 32), dtype=np.uint8),
    )
    skew = np.array([left] * 26 + [right] * 24, dtype=np.uint8)
    np.testing.assert_array_equal(
        train_binary_vocabulary(skew, vocabulary_size=1, seed=20260813),
        np.array([left], dtype=np.uint8),
    )

    empty = train_binary_vocabulary(np.zeros((0, 32), dtype=np.uint8), vocabulary_size=10)
    assert empty.dtype == np.uint8
    assert empty.shape == (0, 32)


def test_extract_orb_descriptors_shapes():
    blank = extract_orb_descriptors(np.zeros((64, 64), dtype=np.uint8))
    assert blank.shape == (0, 32)
    assert blank.dtype == np.uint8

    rng = np.random.default_rng(20261005)
    texture = rng.integers(0, 256, size=(96, 96), dtype=np.uint16).astype(np.uint8)
    rows = extract_orb_descriptors(texture)
    assert rows.dtype == np.uint8
    assert rows.shape[1] == 32
    assert rows.flags["C_CONTIGUOUS"]
