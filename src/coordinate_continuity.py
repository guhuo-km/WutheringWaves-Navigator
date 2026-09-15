from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


Coordinate = tuple[int, int, int]
AxisThreshold = int | tuple[int, int]


@dataclass
class ContinuityState:
    previous_coordinate: Optional[Coordinate] = None
    last_reset_reason: str = ""
    single_source: Optional[str] = None
    single_source_xy: Optional[tuple[int, int]] = None
    single_source_count: int = 0

    def accept(self, coord: Coordinate) -> None:
        self.previous_coordinate = coord
        self._clear_single_source()

    def reset(self, reason: str) -> None:
        self.previous_coordinate = None
        self.last_reset_reason = reason
        self._clear_single_source()

    def _clear_single_source(self) -> None:
        self.single_source = None
        self.single_source_xy = None
        self.single_source_count = 0

    def note_single_source_frame(
        self,
        ocr_xy: Optional[tuple[int, int]],
        visual_xy: Optional[tuple[int, int]],
        tolerance: AxisThreshold,
    ) -> None:
        """Track consecutive far frames where a single source stays stable."""
        if self.previous_coordinate is None or (ocr_xy is None) == (visual_xy is None):
            self._clear_single_source()
            return
        source = "ocr" if ocr_xy is not None else "visual"
        xy = ocr_xy if ocr_xy is not None else visual_xy
        if (
            source == self.single_source
            and self.single_source_xy is not None
            and xy_within(xy, self.single_source_xy, tolerance)
        ):
            self.single_source_count += 1
            return
        self.single_source = source
        self.single_source_xy = xy
        self.single_source_count = 1


def xy_within(
    a: tuple[int, int],
    b: tuple[int, int],
    threshold: AxisThreshold,
) -> bool:
    threshold_x, threshold_y = threshold if isinstance(threshold, tuple) else (threshold, threshold)
    return abs(a[0] - b[0]) <= threshold_x and abs(a[1] - b[1]) <= threshold_y


def xy_within_previous(
    state: ContinuityState,
    coord: Coordinate,
    threshold: AxisThreshold,
) -> bool | None:
    if state.previous_coordinate is None:
        return None
    px, py, _ = state.previous_coordinate
    x, y, _ = coord
    return xy_within((x, y), (px, py), threshold)
