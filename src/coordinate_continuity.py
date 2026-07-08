from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


Coordinate = tuple[int, int, int]
AxisThreshold = int | tuple[int, int]


@dataclass
class ContinuityState:
    previous_coordinate: Optional[Coordinate] = None
    last_reset_reason: str = ""

    def accept(self, coord: Coordinate) -> None:
        self.previous_coordinate = coord

    def reset(self, reason: str) -> None:
        self.previous_coordinate = None
        self.last_reset_reason = reason


def xy_within_previous(
    state: ContinuityState,
    coord: Coordinate,
    threshold: AxisThreshold,
) -> bool | None:
    if state.previous_coordinate is None:
        return None
    px, py, _ = state.previous_coordinate
    x, y, _ = coord
    threshold_x, threshold_y = threshold if isinstance(threshold, tuple) else (threshold, threshold)
    return abs(x - px) <= threshold_x and abs(y - py) <= threshold_y
