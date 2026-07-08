from pathlib import Path

from core.map_context import TileKey
from minimap_legacy_tiles import import_legacy_tile_tree, iter_legacy_tile_files


def _write(path: Path, data: bytes = b"png") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_iter_legacy_tile_files_parses_standard_and_layered_tiles(tmp_path):
    root = tmp_path / "legacy"
    _write(root / "tiles" / "region_8" / "8_-1_2.png")
    _write(root / "tiles" / "region_900" / "900_1_2.png")
    _write(root / "layered_tiles" / "region_8" / "layer_2" / "z_neg1" / "8_2_-1_4_-3.png")

    tiles = iter_legacy_tile_files(root, "8")

    assert [tile.key for tile in tiles] == [
        TileKey("8", "default", None, "standard", -1, 2),
        TileKey("8", "2", -1, "layered", 4, -3),
    ]


def test_iter_legacy_tile_files_can_skip_layered_tiles(tmp_path):
    root = tmp_path / "legacy"
    _write(root / "tiles" / "region_8" / "8_0_0.png")
    _write(root / "layered_tiles" / "region_8" / "layer_2" / "z_neg1" / "8_2_-1_4_-3.png")

    tiles = iter_legacy_tile_files(root, "8", include_layered=False)

    assert [tile.key for tile in tiles] == [
        TileKey("8", "default", None, "standard", 0, 0),
    ]


def test_import_legacy_tile_tree_copies_to_current_cache_layout(tmp_path):
    root = tmp_path / "legacy"
    cache_root = tmp_path / "cache"
    _write(root / "tiles" / "region_8" / "8_0_0.png", b"base")
    _write(root / "layered_tiles" / "region_8" / "layer_2" / "z_neg1" / "8_2_-1_4_-3.png", b"layer")

    imported = import_legacy_tile_tree(root, cache_root, "8")

    assert imported == [
        TileKey("8", "default", None, "standard", 0, 0),
        TileKey("8", "2", -1, "layered", 4, -3),
    ]
    assert (cache_root / "8" / "standard" / "default" / "base" / "0_0.png").read_bytes() == b"base"
    assert (cache_root / "8" / "layered" / "2" / "-1" / "4_-3.png").read_bytes() == b"layer"
