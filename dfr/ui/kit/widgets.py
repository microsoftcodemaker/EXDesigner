"""Small reusable widgets. Colors come from tokens only."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QWidget

from dfr.ui.tokens import SOURCE_LABELS, STATUS_LABELS, TIER_LABELS, Palette, status_color


def heading(text: str, role: str = "heading") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    return label


class _Chip(QLabel):
    def __init__(self, text: str, fg: str, bg: str, tooltip: str = "") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background: {bg}; border: 1px solid {fg}; border-radius: 3px;"
            " padding: 0px 5px; font-weight: 600; }}"
        )
        if tooltip:
            self.setToolTip(tooltip)


class TierBadge(_Chip):
    """T1 / T2 fidelity badge (PRD 9.3). Plain text so it survives monochrome printing."""

    def __init__(self, tier: int, palette: Palette) -> None:
        color = palette.tier.tier1 if tier == 1 else palette.tier.tier2
        tip = "Tier 1: closed-form equation" if tier == 1 else "Tier 2: measured or simulated value"
        super().__init__(TIER_LABELS.get(tier, f"T{tier}"), color, palette.canvas, tip)


class StatusChip(_Chip):
    def __init__(self, status: str, palette: Palette) -> None:
        super().__init__(
            STATUS_LABELS.get(status, status.upper()), status_color(palette, status), palette.canvas
        )


class SourceTag(_Chip):
    def __init__(self, source: str, palette: Palette) -> None:
        tips = {
            "equation": "Tier 1 closed-form equation",
            "manual": "typed by the user",
            "measured": "bench measurement",
            "simulated": "taken from an external simulator",
        }
        super().__init__(
            SOURCE_LABELS.get(source, source),
            palette.text_muted,
            palette.canvas,
            tips.get(source, ""),
        )


class MarginBar(QWidget):
    """Horizontal stress/limit bar with pass/warn/fail bands; hollow T1 and solid T2 markers
    side by side (PRD 4.3 margin chart, in miniature)."""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_ = palette
        self.ratio_t1: float | None = None
        self.ratio_t2: float | None = None
        self.rating_ratio: float = 1.0  # rating / limit, marks the WARN->FAIL boundary
        self.setMinimumHeight(14)
        self.setMinimumWidth(80)

    def set_values(
        self, ratio_t1: float | None, ratio_t2: float | None = None, rating_ratio: float = 1.0
    ) -> None:
        self.ratio_t1, self.ratio_t2, self.rating_ratio = ratio_t1, ratio_t2, max(rating_ratio, 1.0)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # Qt override
        p = self.palette_
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        scale = w / (self.rating_ratio * 1.25)  # px per unit ratio; leaves room past FAIL
        painter.fillRect(0, 0, int(scale * 1.0), h, QColor(p.status.pass_))
        painter.fillRect(
            int(scale * 1.0), 0, int(scale * (self.rating_ratio - 1.0)), h, QColor(p.status.warn)
        )
        painter.fillRect(int(scale * self.rating_ratio), 0, w, h, QColor(p.status.fail))
        painter.setPen(QPen(QColor(p.border), 1))
        painter.drawRect(0, 0, w - 1, h - 1)
        for ratio, filled, color in (
            (self.ratio_t1, False, p.tier.tier1),
            (self.ratio_t2, True, p.tier.tier2),
        ):
            if ratio is None:
                continue
            x = min(max(ratio * scale, 3.0), w - 3.0)
            r = QRectF(x - 4, h / 2 - 4, 8, 8)
            painter.setPen(QPen(QColor(color), 2))
            painter.setBrush(QColor(color) if filled else QColor(p.canvas))
            painter.drawEllipse(r)
        painter.end()


class KeyValueGrid(QFrame):
    """Two-column label grid for the Properties panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(4)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for i, (k, v) in enumerate(rows):
            key = QLabel(k)
            key.setProperty("role", "muted")
            val = QLabel(v)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            self._grid.addWidget(key, i, 0, Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(val, i, 1)
        self._grid.setRowStretch(len(rows), 1)
