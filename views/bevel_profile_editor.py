# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The bevel panel's profile editor: the outline drawn in its square, as
the usual bevel's custom-profile widget — a side view of a bevel between
two faces at a right angle, the shaded part being the solid.

* drag a point to move it (the two ends stay on their faces);
* double-click empty space to add a point there — smooth (round dot)
  or a corner (square), as the buttons under the editor say; Shift
  adds the other kind;
* double-click a point to turn it smooth or a corner;
* right-click a point to remove it.

Every change hands the outline to the tool as control points
``(x, y, smooth)`` (see :mod:`core.bevel_profiles`), and the live
preview follows.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from core import bevel_profiles
from core.i18n import tr

#: Square side and margin (px).
SIDE = 150
PAD = 10
#: How near (px) a click must land to take a point.
GRAB = 7


class ProfileEditor(QWidget):
    #: The outline changed: a list of (x, y, smooth).
    edited = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(SIDE + 2 * PAD, SIDE + 2 * PAD)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setToolTip(tr(
            "Drag a point to move it. Double-click: add a point (Shift: the "
            "other kind), or turn a point smooth/corner. Right-click a point "
            "to remove it."))
        self.points: list = bevel_profiles.controls(None, 8)
        self.segments = 8
        self._drag: int | None = None
        #: Kind of the points double-click adds: smooth, or a corner.
        self.new_smooth = True

    # ---- Data ---------------------------------------------------------------
    def set_points(self, points, segments: int) -> None:
        self.points = [tuple(p) for p in points]
        self.segments = int(segments)
        self._drag = None
        self.update()

    # ---- Geometry -----------------------------------------------------------
    def to_screen(self, x: float, y: float) -> QPointF:
        # (1, 0) bottom right, (0, 1) top left: the old edge (1, 1) is the
        # top-right corner, the solid's far corner (0, 0) bottom left.
        return QPointF(PAD + x * SIDE, PAD + (1.0 - y) * SIDE)

    def to_unit(self, p: QPointF) -> tuple[float, float]:
        x = (p.x() - PAD) / SIDE
        y = 1.0 - (p.y() - PAD) / SIDE
        return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))

    def _hit(self, p: QPointF) -> int | None:
        best, where = None, None
        for i, (x, y, _s) in enumerate(self.points):
            q = self.to_screen(x, y)
            d = (q - p).manhattanLength()
            if d <= GRAB * 1.5 and (best is None or d < best):
                best, where = d, i
        return where

    def _insert_at(self, x: float, y: float) -> int:
        """Index where a new point at (x, y) goes: in the side of the
        outline nearest to it."""
        best, where = None, 1
        for i in range(len(self.points) - 1):
            ax, ay, _s = self.points[i]
            bx, by, _t = self.points[i + 1]
            dx, dy = bx - ax, by - ay
            ln2 = dx * dx + dy * dy
            t = 0.0 if ln2 < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ln2))
            px, py = ax + dx * t, ay + dy * t
            d = (px - x) ** 2 + (py - y) ** 2
            if best is None or d < best:
                best, where = d, i + 1
        return where

    def _changed(self) -> None:
        self.update()
        self.edited.emit(list(self.points))

    # ---- Mouse --------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        i = self._hit(ev.position())
        if ev.button() == Qt.RightButton:
            if i is not None and 0 < i < len(self.points) - 1:
                del self.points[i]
                self._changed()
        elif ev.button() == Qt.LeftButton and i is not None \
                and 0 < i < len(self.points) - 1:
            self._drag = i
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is not None:
            x, y = self.to_unit(ev.position())
            smooth = self.points[self._drag][2]
            self.points[self._drag] = (x, y, smooth)
            self.update()
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag is not None:
            self._drag = None
            self._changed()
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        i = self._hit(ev.position())
        if i is not None:
            if 0 < i < len(self.points) - 1:
                x, y, smooth = self.points[i]
                self.points[i] = (x, y, not smooth)
                self._changed()
        else:
            x, y = self.to_unit(ev.position())
            smooth = self.new_smooth != bool(ev.modifiers() & Qt.ShiftModifier)
            self.points.insert(self._insert_at(x, y), (x, y, smooth))
            self._changed()
        ev.accept()

    def wheelEvent(self, ev) -> None:
        ev.accept()

    # ---- Paint --------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        box = QRectF(PAD, PAD, SIDE, SIDE)
        p.fillRect(box, pal.base())
        outline = bevel_profiles.sample(tuple(self.points), max(self.segments, 16))
        solid = QPolygonF([self.to_screen(0.0, 0.0)]
                          + [self.to_screen(x, y) for x, y in outline])
        shade = QColor(pal.text().color())
        shade.setAlpha(45)
        p.setPen(Qt.NoPen)
        p.setBrush(shade)
        p.drawPolygon(solid)
        grid = QColor(pal.text().color())
        grid.setAlpha(40)
        p.setPen(QPen(grid, 1, Qt.DotLine))
        for k in (1, 2, 3):
            v = PAD + SIDE * k / 4.0
            p.drawLine(QPointF(v, PAD), QPointF(v, PAD + SIDE))
            p.drawLine(QPointF(PAD, v), QPointF(PAD + SIDE, v))
        p.setPen(QPen(pal.mid().color(), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box)
        path = QPainterPath(self.to_screen(*outline[0]))
        for x, y in outline[1:]:
            path.lineTo(self.to_screen(x, y))
        p.setPen(QPen(pal.highlight().color(), 2))
        p.drawPath(path)
        p.setPen(QPen(pal.text().color(), 1))
        for i, (x, y, smooth) in enumerate(self.points):
            q = self.to_screen(x, y)
            p.setBrush(pal.highlight() if 0 < i < len(self.points) - 1 else pal.text())
            if smooth:
                p.drawEllipse(q, 4.0, 4.0)
            else:
                p.drawRect(QRectF(q.x() - 3.5, q.y() - 3.5, 7.0, 7.0))
        p.end()
