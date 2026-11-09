# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Join Segments' preview: before anything changes, a dot on every point
the command would take away (green) and on every point of a straight line
it keeps all the same, in the colour of the reason — with a small panel
that counts them, explains the colours, and joins (Enter) or cancels
(Esc). The dots come from a dry run of the command itself
(:func:`core.edits.join_preview`), so they never promise what it will
not do.

The panel floats in the view's lower-right corner, built like the
bevel's (:mod:`views.bevel_panel`): a child of the viewport that never
covers the rest of the window and eats its own clicks, while the view
keeps the keyboard — Enter and Esc reach the panel through a filter."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QPushButton)

from core.i18n import tr

#: Gap between the panel and the view's lower-right corner (px).
MARGIN = 12

#: Each reason's colour, its short name in the legend and, on hover, what
#: it tells the user (see :data:`core.edits.JOIN_REASONS`). Green goes;
#: the rest stay.
REASON_STYLE = {
    "join": (QColor(60, 180, 90), "Taken away", "Points taken away"),
    "kink": (QColor(230, 40, 40), "Kink",
             "Kept: almost straight, but a real corner"),
    "branch": (QColor(255, 140, 0), "Another edge",
               "Kept: another edge meets the line here"),
    "flags": (QColor(150, 60, 220), "Soft, hidden or layer",
              "Kept: the pieces differ in soft, hidden or layer"),
    "curve": (QColor(30, 130, 255), "Curve", "Kept: part of a curve"),
}


def _dot(color: QColor) -> QLabel:
    """A round swatch of ``color`` for the legend."""
    lab = QLabel()
    lab.setFixedSize(12, 12)
    r, g, b = color.red(), color.green(), color.blue()
    lab.setStyleSheet(f"background: rgb({r}, {g}, {b}); border-radius: 6px;")
    return lab


class JoinPreview(QFrame):
    """The panel, and the dots it paints on ``viewport`` while it is open.

    ``verdicts`` is ``{vertex: reason}``; ``matrix`` places the vertices
    in the world (the open group's placement, ``None`` at the top level).
    ``accepted`` is the caller's cue to run the command; ``finished``
    follows either way, once the panel is gone."""

    accepted = Signal()
    rejected = Signal()
    finished = Signal(bool)

    def __init__(self, viewport, verdicts: dict, matrix=None) -> None:
        super().__init__(viewport)
        self._viewport = viewport
        self._matrix = matrix
        self._open = True
        self.setObjectName("joinPreview")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.setCursor(Qt.ArrowCursor)
        # The world positions, taken now: the panel never holds the
        # model's own objects past an edit made while it is open.
        self._dots = [(reason, self._world(v))
                      for v, reason in verdicts.items()]
        counts: dict = {}
        for reason in verdicts.values():
            counts[reason] = counts.get(reason, 0) + 1
        self.counts = counts

        form = QFormLayout(self)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        n = counts.get("join", 0)
        head = QLabel(tr("{n} points will be taken away", n=n) if n
                      else tr("No point can be taken away"))
        head.setStyleSheet("font-weight: 600;")
        form.addRow(head)
        kept_title = False
        for reason, (color, name, tip) in REASON_STYLE.items():
            if not counts.get(reason):
                continue
            if reason != "join" and not kept_title:
                form.addRow(QLabel(tr("Kept:")))
                kept_title = True
            label = QLabel(f"{counts[reason]}  {tr(name)}")
            dot = _dot(color)
            for w in (dot, label):
                w.setToolTip(tr(tip))
            form.addRow(dot, label)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton(tr("Cancel"))
        self.apply_button = QPushButton(tr("Join"))
        for b in (self.cancel_button, self.apply_button):
            b.setFocusPolicy(Qt.NoFocus)
            buttons.addWidget(b)
        self.apply_button.setEnabled(bool(n))
        self.apply_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        form.addRow(buttons)

        self._keys = _Keys(self)
        viewport.installEventFilter(self._keys)
        overlays = getattr(viewport, "_ext_overlays", None)
        if overlays is not None:
            overlays.append(self._paint)
        self.place()
        self.show()
        self.raise_()
        viewport.update()

    # ---- Showing ------------------------------------------------------------
    def place(self) -> None:
        """Lower-right corner of the view."""
        self.adjustSize()
        w, h = self._viewport.width(), self._viewport.height()
        self.move(max(MARGIN, w - self.width() - MARGIN),
                  max(MARGIN, h - self.height() - MARGIN))

    def _world(self, v):
        return self._matrix.map(v.position) if self._matrix is not None \
            else v.position

    # ---- Closing ------------------------------------------------------------
    def accept(self) -> None:
        if self.apply_button.isEnabled() and self._close():
            self.accepted.emit()
            self.finished.emit(True)

    def reject(self) -> None:
        if self._close():
            self.rejected.emit()
            self.finished.emit(False)

    def _close(self) -> bool:
        """Take the panel and its dots off the view, once."""
        if not self._open:
            return False
        self._open = False
        self._viewport.removeEventFilter(self._keys)
        overlays = getattr(self._viewport, "_ext_overlays", None)
        if overlays is not None and self._paint in overlays:
            overlays.remove(self._paint)
        self.hide()
        self.deleteLater()
        self._viewport.update()
        return True

    def _paint(self, vp, painter: QPainter) -> None:
        """The dots: the kept ones larger and drawn last, so a reason to
        look closer is never hidden under a green dot."""
        painter.setRenderHint(QPainter.Antialiasing)
        order = sorted(self._dots, key=lambda d: d[0] != "join")
        for reason, world in order:
            q = vp.world_to_pixel(world)
            if q is None:
                continue
            color = REASON_STYLE[reason][0]
            r = 4.0 if reason == "join" else 6.0
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(*q), r, r)

    # ---- Nothing gets through to the model ------------------------------------
    def mousePressEvent(self, ev) -> None:
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        ev.accept()

    def wheelEvent(self, ev) -> None:
        ev.accept()


class _Keys(QObject):
    """On the viewport while the panel is open: Enter joins, Esc
    cancels (neither reaches the active tool), and the panel stays in its
    corner when the view changes size."""

    def __init__(self, panel: JoinPreview) -> None:
        super().__init__(panel)
        self._panel = panel

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Resize:
            self._panel.place()
        elif ev.type() == QEvent.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._panel.accept()
                return True
            if ev.key() == Qt.Key_Escape:
                self._panel.reject()
                return True
        return False
