from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import cv2
import numpy as np
import numpy.typing as npt

from core.map_context import MapContext, TileKey
from minimap_tile_downloader import convert_tile_snapshot_to_download_inputs
from minimap_tile_cache import MinimapTileCache


@dataclass(frozen=True)
class StitchedManifest:
    area_id: str
    candidate_type: str
    layer_id: str
    z_level: int | None
    tile_size: int
    origin_tile_x: int
    origin_tile_y: int
    width: int
    height: int
    coord_transform: dict
    fine_gray_path: str
    rough_color_path: str
    manifest_path: str
    rough_downsample: int = 4
    origin_leaflet_tile_x: int | None = None
    origin_leaflet_tile_y: int | None = None
    map_units_per_tile_x: float | None = None
    map_units_per_tile_y: float | None = None
    active_pixel_left: int | None = None
    active_pixel_top: int | None = None
    active_pixel_right: int | None = None
    active_pixel_bottom: int | None = None


class StitchedResourceBuilder:
    def __init__(
        self,
        cache_root: Path,
        output_root: Path,
        tile_size: int = 1024,
        rough_downsample: int = 4,
    ):
        self.cache = MinimapTileCache(Path(cache_root))
        self.output_root = Path(output_root)
        self.tile_size = int(tile_size)
        self.rough_downsample = max(1, int(rough_downsample))

    def publish_base_region(
        self,
        context: MapContext,
        standard_keys: Iterable[TileKey],
    ) -> StitchedManifest:
        keys = list(standard_keys)
        image, origin_x, origin_y = self._stitch(keys)
        origin_leaflet_x, origin_leaflet_y = self._origin_leaflet_tile(keys, origin_x, origin_y)
        return self._publish(
            context=context,
            image=image,
            candidate_type="base",
            layer_id=context.layer_id,
            z_level=None,
            origin_tile_x=origin_x,
            origin_tile_y=origin_y,
            origin_leaflet_tile_x=origin_leaflet_x,
            origin_leaflet_tile_y=origin_leaflet_y,
        )

    def publish_layered_candidate(
        self,
        context: MapContext,
        standard_keys: Iterable[TileKey],
        layer_keys: Iterable[TileKey],
        candidate_type: str,
        layer_id: str,
        z_level: int,
    ) -> StitchedManifest:
        standard_keys = list(standard_keys)
        layer_keys = list(layer_keys)
        base_by_xy = {(key.x, key.y): key for key in standard_keys}
        composed_tiles: list[tuple[TileKey, npt.NDArray[np.uint8]]] = []
        for layer_key in layer_keys:
            base_key = base_by_xy.get((layer_key.x, layer_key.y))
            if base_key is None:
                continue
            composed_tiles.append((layer_key, self._compose_layer_tile(base_key, layer_key)))
        image, origin_x, origin_y = self._stitch_precomposed_tiles(composed_tiles)
        origin_base_key = base_by_xy.get((origin_x, origin_y))
        if origin_base_key is not None:
            origin_leaflet_x, origin_leaflet_y = origin_base_key.leaflet_x, origin_base_key.leaflet_y
        else:
            origin_leaflet_x, origin_leaflet_y = None, None
        active_bounds = (0, 0, int(image.shape[1]), int(image.shape[0]))
        return self._publish(
            context=context,
            image=image,
            candidate_type=candidate_type,
            layer_id=str(layer_id),
            z_level=int(z_level),
            origin_tile_x=origin_x,
            origin_tile_y=origin_y,
            origin_leaflet_tile_x=origin_leaflet_x,
            origin_leaflet_tile_y=origin_leaflet_y,
            active_pixel_bounds=active_bounds,
        )

    def _tile_path(self, key: TileKey) -> Path:
        return self.cache.tile_path(key)

    def _read_tile(self, key: TileKey) -> npt.NDArray[np.uint8]:
        path = self._tile_path(key)
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"tile_not_decodable:{path}")
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image

    def _read_tile_unchanged(self, key: TileKey) -> npt.NDArray[np.uint8]:
        path = self._tile_path(key)
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"tile_not_decodable:{path}")
        return image

    def _compose_layer_tile(self, base_key: TileKey, layer_key: TileKey) -> npt.NDArray[np.uint8]:
        base = self._read_tile(base_key)
        if base.shape[:2] != (self.tile_size, self.tile_size):
            base = cv2.resize(base, (self.tile_size, self.tile_size), interpolation=cv2.INTER_AREA)
        layer = self._read_tile_unchanged(layer_key)
        if layer.shape[:2] != (self.tile_size, self.tile_size):
            layer = cv2.resize(layer, (self.tile_size, self.tile_size), interpolation=cv2.INTER_AREA)
        if layer.ndim == 2:
            layer_bgr = cv2.cvtColor(layer, cv2.COLOR_GRAY2BGR)
            return layer_bgr
        if layer.shape[2] == 4:
            layer_bgr = layer[:, :, :3].astype(np.float32)
            alpha = (layer[:, :, 3:4].astype(np.float32) / 255.0)
            composed = layer_bgr * alpha + base.astype(np.float32) * (1.0 - alpha)
            return np.clip(composed, 0, 255).astype(np.uint8)
        return layer[:, :, :3]

    def _bounds(self, keys: list[TileKey]) -> tuple[int, int, int, int]:
        if not keys:
            raise ValueError("no_tiles_to_stitch")
        xs = [key.x for key in keys]
        ys = [key.y for key in keys]
        return min(xs), max(xs), min(ys), max(ys)

    def _stitch(self, keys: list[TileKey]) -> tuple[npt.NDArray[np.uint8], int, int]:
        min_x, max_x, min_y, max_y = self._bounds(keys)
        width = (max_x - min_x + 1) * self.tile_size
        height = (max_y - min_y + 1) * self.tile_size
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        origin_y = max_y

        for key in keys:
            tile = self._read_tile(key)
            if tile.shape[:2] != (self.tile_size, self.tile_size):
                tile = cv2.resize(tile, (self.tile_size, self.tile_size), interpolation=cv2.INTER_AREA)
            left = (key.x - min_x) * self.tile_size
            top = (origin_y - key.y) * self.tile_size
            canvas[top:top + self.tile_size, left:left + self.tile_size] = tile

        return canvas, min_x, origin_y

    def _stitch_precomposed_tiles(
        self,
        tiles: list[tuple[TileKey, npt.NDArray[np.uint8]]],
    ) -> tuple[npt.NDArray[np.uint8], int, int]:
        keys = [key for key, _ in tiles]
        min_x, max_x, min_y, max_y = self._bounds(keys)
        width = (max_x - min_x + 1) * self.tile_size
        height = (max_y - min_y + 1) * self.tile_size
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        origin_y = max_y
        for key, tile in tiles:
            if tile.shape[:2] != (self.tile_size, self.tile_size):
                tile = cv2.resize(tile, (self.tile_size, self.tile_size), interpolation=cv2.INTER_AREA)
            left = (key.x - min_x) * self.tile_size
            top = (origin_y - key.y) * self.tile_size
            canvas[top:top + self.tile_size, left:left + self.tile_size] = tile[:, :, :3]
        return canvas, min_x, origin_y

    def _origin_leaflet_tile(self, keys: list[TileKey], origin_x: int, origin_y: int) -> tuple[int | None, int | None]:
        for key in keys:
            if key.x == origin_x and key.y == origin_y:
                return key.leaflet_x, key.leaflet_y
        return None, None

    def _overlay_tiles(
        self,
        canvas: npt.NDArray[np.uint8],
        keys: list[TileKey],
        origin_x: int,
        origin_y: int,
    ) -> npt.NDArray[np.uint8]:
        for key in keys:
            tile = self._read_tile(key)
            if tile.shape[:2] != (self.tile_size, self.tile_size):
                tile = cv2.resize(tile, (self.tile_size, self.tile_size), interpolation=cv2.INTER_AREA)
            left = (key.x - origin_x) * self.tile_size
            top = (origin_y - key.y) * self.tile_size
            if top < 0 or left < 0 or top + self.tile_size > canvas.shape[0] or left + self.tile_size > canvas.shape[1]:
                continue
            canvas[top:top + self.tile_size, left:left + self.tile_size] = tile
        return canvas

    def _tile_pixel_bounds(
        self,
        keys: list[TileKey],
        origin_x: int,
        origin_y: int,
    ) -> tuple[int, int, int, int] | None:
        if not keys:
            return None
        left = min((key.x - origin_x) * self.tile_size for key in keys)
        top = min((origin_y - key.y) * self.tile_size for key in keys)
        right = max((key.x - origin_x + 1) * self.tile_size for key in keys)
        bottom = max((origin_y - key.y + 1) * self.tile_size for key in keys)
        return int(left), int(top), int(right), int(bottom)

    def _publish(
        self,
        context: MapContext,
        image: npt.NDArray[np.uint8],
        candidate_type: str,
        layer_id: str,
        z_level: int | None,
        origin_tile_x: int,
        origin_tile_y: int,
        origin_leaflet_tile_x: int | None,
        origin_leaflet_tile_y: int | None,
        active_pixel_bounds: tuple[int, int, int, int] | None = None,
    ) -> StitchedManifest:
        candidate_name = "base" if candidate_type == "base" else f"{candidate_type}_{layer_id}_z_{z_level}"
        out_dir = self.output_root / context.area_id / candidate_name
        out_dir.mkdir(parents=True, exist_ok=True)

        fine = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        rough_size = (
            max(1, image.shape[1] // self.rough_downsample),
            max(1, image.shape[0] // self.rough_downsample),
        )
        rough = cv2.resize(image, rough_size, interpolation=cv2.INTER_AREA)

        version = self._resource_version()
        fine_rel = Path(context.area_id) / candidate_name / f"fine_gray_{version}.png"
        rough_rel = Path(context.area_id) / candidate_name / f"rough_color_{version}.png"
        manifest_rel = Path(context.area_id) / candidate_name / "manifest.json"

        self._write_image_atomic(self.output_root / fine_rel, fine)
        self._write_image_atomic(self.output_root / rough_rel, rough)

        manifest = StitchedManifest(
            area_id=context.area_id,
            candidate_type=candidate_type,
            layer_id=str(layer_id),
            z_level=z_level,
            tile_size=self.tile_size,
            origin_tile_x=origin_tile_x,
            origin_tile_y=origin_tile_y,
            width=int(image.shape[1]),
            height=int(image.shape[0]),
            coord_transform=dict(context.coord_transform),
            fine_gray_path=fine_rel.as_posix(),
            rough_color_path=rough_rel.as_posix(),
            manifest_path=manifest_rel.as_posix(),
            rough_downsample=self.rough_downsample,
            origin_leaflet_tile_x=origin_leaflet_tile_x,
            origin_leaflet_tile_y=origin_leaflet_tile_y,
            map_units_per_tile_x=context.map_units_per_tile_x,
            map_units_per_tile_y=context.map_units_per_tile_y,
            active_pixel_left=None if active_pixel_bounds is None else active_pixel_bounds[0],
            active_pixel_top=None if active_pixel_bounds is None else active_pixel_bounds[1],
            active_pixel_right=None if active_pixel_bounds is None else active_pixel_bounds[2],
            active_pixel_bottom=None if active_pixel_bounds is None else active_pixel_bounds[3],
        )
        self._write_json_atomic(self.output_root / manifest_rel, asdict(manifest))
        return manifest

    def _resource_version(self) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"{stamp}_{uuid4().hex[:8]}"

    def _write_image_atomic(self, path: Path, image: npt.NDArray[np.uint8]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp.png")
        if not cv2.imwrite(str(tmp), image):
            raise ValueError(f"image_write_failed:{path}")
        tmp.replace(path)

    def _write_json_atomic(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def publish_stitched_resources_from_snapshot(
    snapshot: dict,
    *,
    context: MapContext,
    cache_root: Path,
    output_root: Path,
    changed_area_ids: set[str],
    tile_size: int | None = None,
) -> list[StitchedManifest]:
    if context.area_id not in {str(area_id) for area_id in changed_area_ids}:
        return []

    inputs = convert_tile_snapshot_to_download_inputs(snapshot)
    area_keys = [item.key for item in inputs if item.key.area_id == context.area_id]
    standard_keys = [key for key in area_keys if key.kind == "standard"]
    if not standard_keys:
        return []

    builder = StitchedResourceBuilder(
        cache_root,
        output_root,
        tile_size=tile_size if tile_size is not None else context.tile_size,
    )
    manifests = [builder.publish_base_region(context, standard_keys)]

    layer_groups: dict[tuple[str, str, int], list[TileKey]] = {}
    for key in area_keys:
        if key.kind not in {"layered", "gravity"}:
            continue
        z_level = 0 if key.z_level is None else int(key.z_level)
        layer_groups.setdefault((key.kind, key.layer_id, z_level), []).append(key)

    for (candidate_type, layer_id, z_level), layer_keys in sorted(layer_groups.items()):
        manifests.append(
            builder.publish_layered_candidate(
                context,
                standard_keys,
                layer_keys,
                candidate_type=candidate_type,
                layer_id=layer_id,
                z_level=z_level,
            )
        )
    return manifests


def missing_stitched_manifest_area_ids(
    snapshot: dict,
    *,
    context: MapContext,
    output_root: Path,
) -> set[str]:
    inputs = convert_tile_snapshot_to_download_inputs(snapshot)
    area_keys = [item.key for item in inputs if item.key.area_id == context.area_id]
    standard_keys = [key for key in area_keys if key.kind == "standard"]
    if not standard_keys:
        return set()

    root = Path(output_root) / context.area_id
    expected = [root / "base" / "manifest.json"]
    layer_names = set()
    for key in area_keys:
        if key.kind not in {"layered", "gravity"}:
            continue
        z_level = 0 if key.z_level is None else int(key.z_level)
        layer_names.add(f"{key.kind}_{key.layer_id}_z_{z_level}")
    expected.extend(root / name / "manifest.json" for name in sorted(layer_names))
    return {context.area_id} if any(not path.exists() for path in expected) else set()
