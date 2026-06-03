from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class RingMeterStyle:
    background_ring: QColor
    foreground_ring: QColor
    text_primary: QColor
    text_secondary: QColor


class RingMeterWidget(QWidget):
    """A compact circular meter with title + value text.

    Designed for the HomeInterface stamina card.
    """

    def __init__(
        self,
        title: str,
        current: int = 0,
        total: int = 100,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._current = int(current)
        self._total = max(0, int(total))
        self.setMinimumSize(120, 120)
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy(),
        )

    def set_title(self, title: str) -> None:
        self._title = str(title)
        self.update()

    def set_value(self, current: int, total: int) -> None:
        self._current = int(current)
        self._total = max(0, int(total))
        self.update()

    def _calc_ratio(self) -> float:
        if self._total <= 0:
            return 0.0
        return max(0.0, min(1.0, float(self._current) / float(self._total)))

    def _resolve_style(self) -> RingMeterStyle:
        # Keep this file UI-local and lightweight: avoid importing ThemeManager here.
        # qfluentwidgets uses dark theme by default detection; import lazily.
        try:
            from qfluentwidgets import isDarkTheme

            is_dark = bool(isDarkTheme())
        except Exception:
            is_dark = False

        if is_dark:
            return RingMeterStyle(
                background_ring=QColor("#3F3F3F"),
                foreground_ring=QColor("#4FC3F7"),
                text_primary=QColor("#FFFFFF"),
                text_secondary=QColor("#BBBBBB"),
            )
        return RingMeterStyle(
            background_ring=QColor("#E0E0E0"),
            foreground_ring=QColor("#0078D7"),
            text_primary=QColor("#111111"),
            text_secondary=QColor("#666666"),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        style = self._resolve_style()
        ratio = self._calc_ratio()

        # Geometry
        margin = 10
        rect = QRectF(
            margin,
            margin,
            max(1.0, float(self.width() - 2 * margin)),
            max(1.0, float(self.height() - 2 * margin)),
        )

        # Ring thickness scales with widget size, but stays reasonable
        thickness = max(8, min(14, int(min(self.width(), self.height()) * 0.09)))
        pen_bg = QPen(style.background_ring, thickness, Qt.SolidLine, Qt.RoundCap)
        pen_fg = QPen(style.foreground_ring, thickness, Qt.SolidLine, Qt.RoundCap)

        # Start at top (90 deg), draw clockwise
        start_angle = 90 * 16
        span_full = -360 * 16
        span_value = int(span_full * ratio)

        painter.setPen(pen_bg)
        painter.drawArc(rect, start_angle, span_full)

        painter.setPen(pen_fg)
        painter.drawArc(rect, start_angle, span_value)

        # Text
        painter.setPen(style.text_secondary)
        title_font = QFont(self.font())
        title_font.setPointSize(max(8, self.font().pointSize() - 1))
        painter.setFont(title_font)
        painter.drawText(self.rect().adjusted(0, 38, 0, -56), Qt.AlignHCenter, self._title)

        painter.setPen(style.text_primary)
        value_font = QFont(self.font())
        value_font.setBold(True)
        value_font.setPointSize(max(10, self.font().pointSize() + 2))
        painter.setFont(value_font)
        value_text = f"{self._current}/{self._total}" if self._total > 0 else str(self._current)
        painter.drawText(self.rect().adjusted(0, 70, 0, -24), Qt.AlignHCenter, value_text)
