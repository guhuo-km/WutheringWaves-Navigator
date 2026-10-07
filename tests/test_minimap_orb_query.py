from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import minimap_orb_query  # noqa: E402
from minimap_orb_builder import build_area_orb_index  # noqa: E402
from minimap_orb_index import build_inverted_index, score_words  # noqa: E402
from minimap_orb_query import OrbQueryIndex  # noqa: E402
from minimap_orb_store import OrbAreaIndex, load_orb_area_index, save_orb_area_index  # noqa: E402

VOCABULARY = np.array(
    [np.full(32, value, dtype=np.uint8) for value in (0x00, 0xFF, 0x0F, 0xF0)],
    dtype=np.uint8,
)
IMAGE = np.zeros((8, 8), dtype=np.uint8)

AREA_KEYS = ("area|layer|0|0", "area|layer|0|1", "区域|层|1|0")
AREA_WORD_LISTS = [
    np.array([0, 0], dtype=np.int64),
    np.array([1, 1, 1], dtype=np.int64),
    np.array([3], dtype=np.int64),
]
OTHER_KEYS = ("area|layer|0|0", "area|layer|0|1", "area|layer|1|0", "area|layer|1|1")
OTHER_WORD_LISTS = [
    np.array([0], dtype=np.int64),
    np.array([3, 3], dtype=np.int64),
    np.array([1, 1, 3], dtype=np.int64),
    np.array([2], dtype=np.int64),
]


def write_product(path: Path, keys: tuple[str, ...], word_lists: list[np.ndarray]) -> None:
    save_orb_area_index(
        path,
        OrbAreaIndex(
            document_keys=keys,
            vocabulary=VOCABULARY,
            inverted_index=build_inverted_index(word_lists, VOCABULARY.shape[0]),
        ),
    )


def write_empty_vocabulary_product(path: Path, index_root: Path, keys: tuple[str, ...]) -> None:
    """Produce the real empty-corpus product through the builder, then persist it."""
    rough = index_root / "rough_windows"
    descriptors = index_root / "orb_descriptors"
    rough.mkdir(parents=True)
    descriptors.mkdir(parents=True)
    for position, work_key in enumerate(keys):
        stem = f"base__{position}_0_0"
        (rough / f"{stem}.json").write_text(json.dumps({"work_key": work_key}), encoding="utf-8")
        np.save(descriptors / f"{stem}.npy", np.zeros((0, 32), dtype=np.uint8))
    save_orb_area_index(path, build_area_orb_index(index_root))


def patch_extract(monkeypatch: pytest.MonkeyPatch, rows: np.ndarray) -> None:
    monkeypatch.setattr(
        minimap_orb_query,
        "extract_orb_descriptors",
        lambda image, nfeatures=0: rows,
    )


def count_loads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    loads: list[str] = []
    real_load = minimap_orb_query.load_orb_area_index

    def counting_load(path: Path) -> OrbAreaIndex:
        loads.append(str(Path(path)))
        return real_load(path)

    monkeypatch.setattr(minimap_orb_query, "load_orb_area_index", counting_load)
    return loads


QUERY_ROWS = np.array([VOCABULARY[1], VOCABULARY[1]], dtype=np.uint8)


def test_cache_reuses_until_product_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "area_orb.npz"
    write_product(path, AREA_KEYS, AREA_WORD_LISTS)
    loads = count_loads(monkeypatch)
    patch_extract(monkeypatch, QUERY_ROWS)
    engine = OrbQueryIndex()

    keys, scores = engine.score(path, IMAGE)
    assert keys == AREA_KEYS
    assert scores.dtype == np.float32
    assert scores.shape == (len(AREA_KEYS),)
    np.testing.assert_allclose(scores, score_words(load_orb_area_index(path).inverted_index, np.array([1, 1])))
    assert int(np.argmax(scores)) == 1

    engine.score(path, IMAGE)
    assert loads == [str(path)]

    write_product(path, OTHER_KEYS, OTHER_WORD_LISTS)
    keys, scores = engine.score(path, IMAGE)
    assert loads == [str(path), str(path)]
    assert keys == OTHER_KEYS
    assert scores.shape == (len(OTHER_KEYS),)
    np.testing.assert_allclose(scores, score_words(load_orb_area_index(path).inverted_index, np.array([1, 1])))
    assert keys[int(np.argmax(scores))] == OTHER_KEYS[2]


def test_empty_words_or_empty_vocabulary_gives_zero_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "area_orb.npz"
    write_product(path, AREA_KEYS, AREA_WORD_LISTS)
    patch_extract(monkeypatch, np.zeros((0, 32), dtype=np.uint8))

    keys, scores = OrbQueryIndex().score(path, IMAGE)

    assert keys == AREA_KEYS
    assert scores.dtype == np.float32
    np.testing.assert_array_equal(scores, np.zeros(len(AREA_KEYS), dtype=np.float32))

    # An empty vocabulary must never reach quantization, even with descriptors to assign.
    empty_path = tmp_path / "empty_area_orb.npz"
    write_empty_vocabulary_product(empty_path, tmp_path / "indexes", AREA_KEYS)
    patch_extract(monkeypatch, np.array([VOCABULARY[1]], dtype=np.uint8))

    keys, scores = OrbQueryIndex().score(empty_path, IMAGE)

    assert keys == AREA_KEYS
    assert scores.dtype == np.float32
    np.testing.assert_array_equal(scores, np.zeros(len(AREA_KEYS), dtype=np.float32))
