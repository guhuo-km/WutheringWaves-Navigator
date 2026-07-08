import numpy as np

from minimap_retrieval_index import (
    CandidateDescriptor,
    CandidateWindow,
    build_candidate_windows,
    compute_hsv_texture_descriptor,
    retrieve_top_k,
)


def test_build_candidate_windows_records_centers_and_tiles():
    windows = build_candidate_windows(
        region_id="8",
        map_left=0,
        map_top=0,
        map_width=2048,
        map_height=2048,
        window_size=512,
        stride=512,
        tile_size=1024,
    )

    assert len(windows) == 16
    first = windows[0]
    assert first.center_x == 256
    assert first.center_y == 256
    assert first.tile_min_x == 0
    assert first.tile_max_x == 0
    assert first.tile_min_y == 0
    assert first.tile_max_y == 0

    crossing = windows[5]
    assert crossing.left == 512
    assert crossing.top == 512
    assert crossing.tile_min_x == 0
    assert crossing.tile_max_x == 0
    assert crossing.tile_min_y == 0
    assert crossing.tile_max_y == 0


def test_build_candidate_windows_returns_empty_when_map_is_smaller_than_window():
    assert build_candidate_windows(
        region_id="8",
        map_left=0,
        map_top=0,
        map_width=128,
        map_height=128,
        window_size=256,
        stride=64,
        tile_size=1024,
    ) == []


def _candidate(window_id: str) -> CandidateWindow:
    return CandidateWindow(
        region_id="8",
        window_id=window_id,
        left=0,
        top=0,
        width=64,
        height=64,
        center_x=32,
        center_y=32,
        tile_min_x=0,
        tile_max_x=0,
        tile_min_y=0,
        tile_max_y=0,
    )


def test_hsv_descriptor_retrieves_more_similar_synthetic_color():
    green = np.zeros((64, 64, 3), dtype=np.uint8)
    green[:, :] = (40, 180, 40)
    blue = np.zeros((64, 64, 3), dtype=np.uint8)
    blue[:, :] = (180, 40, 40)

    query = compute_hsv_texture_descriptor(green)
    hits = retrieve_top_k(
        query,
        [
            CandidateDescriptor(_candidate("green"), compute_hsv_texture_descriptor(green)),
            CandidateDescriptor(_candidate("blue"), compute_hsv_texture_descriptor(blue)),
        ],
        top_k=2,
    )

    assert hits[0].candidate.window_id == "green"
    assert hits[0].score >= hits[1].score


def test_hsv_descriptor_uses_masked_pixels_only():
    image = np.zeros((16, 16, 3), dtype=np.uint8)
    image[:, :8] = (40, 180, 40)
    image[:, 8:] = (180, 40, 40)
    left_mask = np.zeros((16, 16), dtype=np.uint8)
    left_mask[:, :8] = 255
    right_mask = np.zeros((16, 16), dtype=np.uint8)
    right_mask[:, 8:] = 255

    left_descriptor = compute_hsv_texture_descriptor(image, mask=left_mask)
    right_descriptor = compute_hsv_texture_descriptor(image, mask=right_mask)

    assert not np.allclose(left_descriptor, right_descriptor)
