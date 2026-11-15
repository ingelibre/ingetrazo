# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Composition guides: lines to frame a picture by, as a camera's
viewfinder shows them — the rule of thirds, the golden ratio, a grid, the
diagonals, the golden triangle, the golden spiral, the centre.

They are only drawn, never exported: over the preview of Export View
(SVG) and over the 3D view (a scene tab's right-click menu ▸ Composition
Guides), where they fall inside the camera's frame when it has one.

The golden triangle and the golden spiral are not symmetric: their TURN
flips them left↔right or top↔bottom and, the spiral, turns it 90°, so
their strong point falls where the picture wants it (:data:`TURNABLE`,
``OrbitCamera.composition_turn``).
"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform

#: Every guide, ``"none"`` first (no lines), and how a file's value is read
#: — the camera keeps the guide it shows (``OrbitCamera.composition_guide``).
from core.camera import COMPOSITION_GUIDES as GUIDES  # noqa: F401
from core.camera import COMPOSITION_TURNS as TURNS  # noqa: F401
from core.camera import FLIP_H, FLIP_V, TURN_90  # noqa: F401
from core.camera import TURNABLE_GUIDES as TURNABLE  # noqa: F401
from core.camera import read_composition_guide as read_guide  # noqa: F401
from core.camera import read_composition_turn as read_turn  # noqa: F401
from core.i18n import tr

#: The guides the SVG preview begins with, and the one the view's switch
#: turns on before any other was chosen.
DEFAULT_GUIDES = "thirds"

#: The golden section of a side: where the golden ratio's lines fall.
GOLDEN = (5.0 ** 0.5 - 1.0) / 2.0         # 0.618…
#: The golden ratio itself, the long side of a golden rectangle.
PHI = 1.0 + GOLDEN                         # 1.618…
#: How many squares the spiral is cut into before they are too small to
#: see (the tenth is under 1 % of the first).
SPIRAL_STEPS = 10


def guide_names() -> dict:
    """Each guide's name, in the interface language."""
    return {"none": tr("No guides"), "thirds": tr("Rule of thirds"),
            "golden": tr("Golden ratio"), "grid": tr("Grid"),
            "diagonals": tr("Diagonals"),
            "golden_triangle": tr("Golden triangle"),
            "spiral": tr("Golden spiral"), "centre": tr("Centre")}


def turn_names() -> dict:
    """Each part of a guide's orientation: its name and what it does, in
    the interface language."""
    return {
        FLIP_H: (tr("Flip horizontally"),
                 tr("Flip the golden triangle or spiral left to right.")),
        FLIP_V: (tr("Flip vertically"),
                 tr("Flip the golden triangle or spiral top to bottom.")),
        TURN_90: (tr("Rotate 90°"),
                  tr("Turn the golden spiral a quarter turn: it starts "
                     "from the top or the side.")),
    }


def turn_parts(key: str) -> tuple:
    """What can be changed of the guide ``key``'s orientation: both flips
    for the golden triangle (its two flips give its two ways), the flips
    and the 90° turn for the spiral, nothing for the others."""
    if key == "spiral":
        return (FLIP_H, FLIP_V, TURN_90)
    if key == "golden_triangle":
        return (FLIP_H, FLIP_V)
    return ()


def turn_transform(page: QRectF, turn: int) -> QTransform:
    """The flips of ``turn`` (:data:`FLIP_H`, :data:`FLIP_V`) about the
    middle of ``page``; the 90° turn is the spiral's own (see
    :func:`spiral_path`)."""
    sx = -1 if turn & FLIP_H else 1
    sy = -1 if turn & FLIP_V else 1
    c = page.center()
    t = QTransform()
    t.translate(c.x(), c.y())
    t.scale(sx, sy)
    t.translate(-c.x(), -c.y())
    return t


def _foot(p: QPointF, a: QPointF, b: QPointF) -> QPointF:
    """Where the line from ``p`` square to ``a``–``b`` meets it."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    k = ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / (dx * dx + dy * dy)
    return QPointF(a.x() + k * dx, a.y() + k * dy)


def golden_triangle_lines(page: QRectF) -> list:
    """The golden triangle in turn 0: the diagonal from the top left to
    the bottom right, and from each other corner the line square to it."""
    tl, br = page.topLeft(), page.bottomRight()
    tr_, bl = page.topRight(), page.bottomLeft()
    return [QLineF(tl, br), QLineF(tr_, _foot(tr_, tl, br)),
            QLineF(bl, _foot(bl, tl, br))]


def spiral_path(page: QRectF, turned: bool = False) -> QPainterPath:
    """The golden spiral, unflipped: a golden rectangle cut into squares,
    a quarter circle in each, stretched to fill ``page`` (a frame seldom
    has the golden shape). Landscape, the first square is on the left and
    the eye lands right of the centre, low; portrait — or ``turned``, the
    90° turn — the same laid over its diagonal, the first square on top.
    The squares' sides are part of the path."""
    path = QPainterPath()
    x, y, w, h = 0.0, 0.0, PHI, 1.0         # a golden rectangle, landscape
    for k in range(SPIRAL_STEPS):
        side = min(w, h)
        if k % 4 == 0:                      # the square on the left
            sq = QRectF(x, y, side, side)
            centre = sq.bottomRight()
            x, w = x + side, w - side
            cut = QLineF(sq.topRight(), sq.bottomRight())
        elif k % 4 == 1:                    # on top
            sq = QRectF(x, y, side, side)
            centre = sq.bottomLeft()
            y, h = y + side, h - side
            cut = QLineF(sq.bottomLeft(), sq.bottomRight())
        elif k % 4 == 2:                    # on the right
            sq = QRectF(x + w - side, y, side, side)
            centre = sq.topLeft()
            w -= side
            cut = QLineF(sq.topLeft(), sq.bottomLeft())
        else:                               # at the bottom
            sq = QRectF(x, y + h - side, side, side)
            centre = sq.topRight()
            h -= side
            cut = QLineF(sq.topLeft(), sq.topRight())
        circle = QRectF(centre.x() - side, centre.y() - side,
                        2 * side, 2 * side)
        start = 180.0 - 90.0 * (k % 4)
        if k == 0:
            path.arcMoveTo(circle, start)
        path.arcTo(circle, start, -90.0)
        sub = path.currentPosition()
        path.moveTo(cut.p1())
        path.lineTo(cut.p2())
        path.moveTo(sub)
    # The golden rectangle onto the page; a portrait page takes it turned
    # over its diagonal (x and y swapped), so the squares stay squares-ish.
    t = QTransform()
    if (page.width() >= page.height()) != bool(turned):
        t.translate(page.x(), page.y())
        t.scale(page.width() / PHI, page.height())
    else:
        t = QTransform(0.0, page.height() / PHI, page.width(), 0.0,
                       page.x(), page.y())
    return t.map(path)


def draw_guides(p: QPainter, page: QRectF, key: str, turn: int = 0) -> None:
    """The composition guides ``key`` over the rectangle ``page``, flipped
    by ``turn`` when they have a side (:data:`TURNABLE`): a light line
    over a dark one, so they read on paper and on a picture alike."""
    x0, y0, w, h = page.x(), page.y(), page.width(), page.height()
    lines = []
    path = None

    def across(fracs):
        for f in fracs:
            lines.append(QLineF(x0 + f * w, y0, x0 + f * w, y0 + h))
            lines.append(QLineF(x0, y0 + f * h, x0 + w, y0 + f * h))

    if key == "thirds":
        across((1.0 / 3.0, 2.0 / 3.0))
    elif key == "golden":
        across((1.0 - GOLDEN, GOLDEN))
    elif key == "grid":
        across((0.25, 0.5, 0.75))
    elif key == "diagonals":
        lines.append(QLineF(page.topLeft(), page.bottomRight()))
        lines.append(QLineF(page.bottomLeft(), page.topRight()))
    elif key == "centre":
        across((0.5,))                      # a cross from side to side
    elif key == "golden_triangle":
        lines = golden_triangle_lines(page)
    elif key == "spiral" and w > 0 and h > 0:
        path = spiral_path(page, bool(turn & TURN_90))
    if not lines and path is None:
        return
    if key in TURNABLE and turn & (FLIP_H | FLIP_V):
        t = turn_transform(page, turn)
        lines = [t.map(ln) for ln in lines]
        if path is not None:
            path = t.map(path)
    p.save()
    p.setClipRect(page)
    p.setBrush(Qt.NoBrush)
    for pen in (QPen(QColor(0, 0, 0, 90), 2.2),
                QPen(QColor(255, 255, 255, 200), 1.0)):
        p.setPen(pen)
        if lines:
            p.drawLines(lines)
        if path is not None:
            p.drawPath(path)
    p.restore()
