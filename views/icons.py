# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Toolbar icons, drawn programmatically with QPainter (Track: UI).

IngeTrazo has its **own** icons — the goal is not to copy any one program but to
be understood at a glance, so the learning curve is near zero. Each icon is the
plainest picture of what the tool does: the drawing tools *are* their shapes (a
line is a line, a rectangle a rectangle), Paint is a brush laying a band of
colour, Move/Pan are the familiar crossed-arrows / open-hand, Push/Pull is a
face with an extrude arrow, Orbit is a pair of curved arrows. Drawing them
ourselves keeps the set consistent, theme-aware (ink follows the palette), tiny,
and free of any third-party icon licence. No SVG files, no QtSvg, no assets.

``tool_icon(key)`` returns a :class:`QIcon` for a tool/nav key, or a null icon
for an unknown key (the action keeps its text label).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication

_PX = 48          # render size (QIcon scales down; big = crisp on HiDPI)
_M = 8.0          # margin — drawing happens in [_M, _PX-_M]


def _ink() -> QColor:
    """Icon ink colour — follows the current palette's text colour so the icons
    read on light and dark themes alike."""
    app = QApplication.instance()
    if app is not None:
        c = app.palette().windowText().color()
        # Nudge toward a medium ink so lines aren't harsh pure black.
        return QColor(c.red(), c.green(), c.blue())
    return QColor(40, 44, 52)


def _canvas():
    pm = QPixmap(_PX, _PX)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    ink = _ink()
    pen = QPen(ink, 3.0)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundStyle if hasattr(Qt, "RoundStyle") else Qt.RoundCap)
    p.setPen(pen)
    return pm, p, ink


def _accent() -> QColor:
    return QColor(243, 115, 41)   # IngeTrazo orange, for endpoint dots / handles


# ---- Per-tool drawings ---------------------------------------------------------
# Each takes (painter, ink) and draws into the _M.._PX-_M box.

def _dot(p, x, y, r=3.2, color=None):
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(color or _accent())
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _select(p, ink):
    # Arrow cursor.
    path = QPainterPath()
    path.moveTo(16, 12)
    path.lineTo(16, 36)
    path.lineTo(23, 29)
    path.lineTo(28, 39)
    path.lineTo(32, 37)
    path.lineTo(27, 27)
    path.lineTo(36, 27)
    path.closeSubpath()
    p.setBrush(QBrush(ink))
    p.drawPath(path)


def _line(p, ink):
    # A plain line with its two endpoints — the tool's own shape.
    p.drawLine(QPointF(12, 36), QPointF(36, 12))
    _dot(p, 12, 36)
    _dot(p, 36, 12)


def _freehand(p, ink):
    # Freehand: a cursive stroke with a loop in the middle, the start of the
    # stroke marked by the accent dot (where the drag began).
    path = QPainterPath()
    path.moveTo(9, 33)
    path.cubicTo(15, 33, 19, 16, 26, 17)
    path.cubicTo(33, 18, 30, 30, 24, 28)
    path.cubicTo(19, 26, 24, 14, 31, 16)
    path.cubicTo(36, 17, 37, 26, 40, 29)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    _dot(p, 9, 33)


def _guide(p, ink, a, b, dashed: bool = True) -> None:
    """A thin construction line — the diagonal, radius or chord the tool
    is built on — in the ink at 55 %, dashed."""
    pen = QPen(QColor(ink.red(), ink.green(), ink.blue(), 140), 1.8,
               Qt.DashLine if dashed else Qt.SolidLine)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(*a), QPointF(*b))
    p.restore()


# Drawing tools: the shape in ink, its DEFINING POINTS (the clicks) as accent
# dots and the construction line it is built on as a thin dashed guide
# (Marco, 2026-09-14).

def _rectangle(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(11, 14, 26, 20))
    _guide(p, ink, (11, 34), (37, 14))                 # the diagonal
    _dot(p, 11, 34, 2.9)
    _dot(p, 37, 14, 2.9)


def _rectangle_center(p, ink):
    # The same rectangle drawn the other way (issue #39): the first click
    # is the CENTRE, the second a corner — centre dot + half diagonal.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(11, 14, 26, 20))
    _guide(p, ink, (24, 24), (37, 14))
    _dot(p, 24, 24, 2.9)
    _dot(p, 37, 14, 2.9)


def _rotated_rect(p, ink):
    # Rotated rectangle: the rectangle standing at an angle, its first corner
    # (the pivot) as the accent dot, and a curved accent arrow above its far
    # corner telling that it turns.
    P = (10.0, 38.0)
    ang = math.radians(28)
    L, W = 23.0, 13.0
    B = (P[0] + L * math.cos(ang), P[1] - L * math.sin(ang))
    C = (B[0] - W * math.sin(ang), B[1] - W * math.cos(ang))
    D = (P[0] - W * math.sin(ang), P[1] - W * math.cos(ang))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF([QPointF(*P), QPointF(*B), QPointF(*C), QPointF(*D)]))
    # the turning arrow: a quarter circle round the pivot, outside the shape
    cx, cy, r = P[0], P[1], 30.0
    p.save()
    p.setPen(_rpen(_accent(), 2.8))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 12 * 16, 58 * 16)
    a = math.radians(70)
    tip = QPointF(cx + r * math.cos(a), cy - r * math.sin(a))
    p.setPen(Qt.NoPen)
    p.setBrush(_accent())
    # arrowhead pointing along the turn (counter-clockwise, towards the left)
    tx, ty = -math.sin(a), -math.cos(a)          # tangent, screen y down
    nx, ny = -ty, tx
    p.drawPolygon(QPolygonF([
        QPointF(tip.x() + tx * 6.5, tip.y() + ty * 6.5),
        QPointF(tip.x() + nx * 4.5, tip.y() + ny * 4.5),
        QPointF(tip.x() - nx * 4.5, tip.y() - ny * 4.5)]))
    p.restore()
    _dot(p, P[0], P[1], 3.3)


def _circle(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(24, 24), 13, 13)
    _guide(p, ink, (24, 24), (37, 24))                 # the radius
    _dot(p, 24, 24, 2.9)
    _dot(p, 37, 24, 2.9)


def _polygon(p, ink):
    pts = []
    for i in range(6):
        a = math.radians(60 * i - 30)
        pts.append(QPointF(24 + 13 * math.cos(a), 24 + 13 * math.sin(a)))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF(pts))
    _guide(p, ink, (24, 24), (pts[0].x(), pts[0].y()))  # the radius
    _dot(p, 24, 24, 2.9)
    _dot(p, pts[0].x(), pts[0].y(), 2.9)


def _arc(p, ink):
    # Two-point arc: the ends, the chord and the bulge.
    path = QPainterPath()
    path.moveTo(11, 34)
    path.quadTo(24, 4, 37, 34)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    _guide(p, ink, (11, 34), (37, 34))                 # the chord
    _guide(p, ink, (24, 34), (24, 19))                 # the bulge
    _dot(p, 11, 34, 2.9)
    _dot(p, 37, 34, 2.9)
    _dot(p, 24, 19, 2.4)


def _arc3(p, ink):
    # Three-point arc: the three points, nothing else to construct.
    path = QPainterPath()
    path.moveTo(11, 34)
    path.quadTo(24, 4, 37, 34)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    _dot(p, 11, 34, 2.9)
    _dot(p, 37, 34, 2.9)
    _dot(p, 24, 19, 2.9)


def _pie(p, ink):
    # Pie: a closed wedge — the arc and its two radii — with the slice
    # itself filled in the accent, so it reads as a shape and not a stroke.
    rect = QRectF(9, 11, 30, 30)
    wedge = QPainterPath()
    wedge.moveTo(24, 26)
    wedge.arcTo(rect, 20, 110)
    wedge.closeSubpath()
    acc = _accent()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 110))
    p.drawPath(wedge)
    p.restore()
    p.setBrush(Qt.NoBrush)
    p.drawPath(wedge)
    _dot(p, 24, 26, 2.9)


def _rotate(p, ink):
    # Two curved arrows chasing each other around a pivot — the universal
    # "rotate" symbol. The small centre dot is the pivot the geometry turns about.
    p.setBrush(Qt.NoBrush)
    cx, cy, r = 24, 24, 11.0
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    p.drawArc(rect, 158 * 16, -138 * 16)      # top arrow: over the top to the right
    p.drawArc(rect, 338 * 16, -138 * 16)      # bottom arrow: under to the left

    def _head(a_deg):
        a = math.radians(a_deg)
        px, py = cx + r * math.cos(a), cy - r * math.sin(a)
        # Clockwise tangent at the arc's end; barbs point back along it.
        bx, by = -math.sin(a), -math.cos(a)
        for rot in (math.radians(32), math.radians(-32)):
            dx = bx * math.cos(rot) - by * math.sin(rot)
            dy = bx * math.sin(rot) + by * math.cos(rot)
            p.drawLine(QPointF(px, py), QPointF(px + 6.5 * dx, py + 6.5 * dy))

    _head(20)      # end of the top arrow (right, pointing down)
    _head(200)     # end of the bottom arrow (left, pointing up)
    _dot(p, cx, cy, 2.4)


def _center_arc(p, ink):
    # Compass arc: centre, the two radius arms as guides, the swept arc.
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 10, 28, 28), 0, 105 * 16)
    ex = 24 + 14 * math.cos(math.radians(105))
    ey = 24 - 14 * math.sin(math.radians(105))
    _guide(p, ink, (24, 24), (38, 24))
    _guide(p, ink, (24, 24), (ex, ey))
    _dot(p, 24, 24, 2.9)
    _dot(p, 38, 24, 2.9)
    _dot(p, ex, ey, 2.9)


def _flip(p, ink):
    # Flip/mirror: two triangles reflected across a dashed axis.
    p.setBrush(Qt.NoBrush)
    dash = QPen(ink, 2.0, Qt.DashLine)
    p.save()
    p.setPen(dash)
    p.drawLine(QPointF(24, 8), QPointF(24, 40))
    p.restore()
    p.setBrush(QBrush(ink))
    p.drawPolygon(QPolygonF([QPointF(20, 14), QPointF(20, 34),
                             QPointF(10, 30)]))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF([QPointF(28, 14), QPointF(28, 34),
                             QPointF(38, 30)]))


def _scale(p, ink):
    # A small square growing to a large one along a diagonal arrow.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(11, 27, 10, 10))
    p.drawRect(QRectF(17, 11, 20, 20))
    p.drawLine(QPointF(14, 34), QPointF(33, 15))
    p.drawLine(QPointF(33, 15), QPointF(27, 15))
    p.drawLine(QPointF(33, 15), QPointF(33, 21))



def _followme(p, ink):
    # A small profile square swept along a curved path.
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(12, 36)
    path.quadTo(14, 16, 36, 14)
    p.drawPath(path)
    p.save()
    p.translate(12, 36)
    p.rotate(-75)
    p.drawRect(QRectF(-4.5, -4.5, 9, 9))
    p.restore()
    _dot(p, 36, 14)



# ---- Sections: a square, the plane as a dashed accent line, the cut edge ----
# Marco's pick (2026-09-14, the minimal family): the tool shows the plane
# through a box with the arrow of the side that goes away; "planes" is the
# bare frame with its corner brackets; "cuts" keeps the half that stays
# with the cut edge thick in the accent; "fill" paints that cut face.

def _solid_arrow(p, color, x0, y0, x1, y1, w=2.8, head=6.0):
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    bx, by = x1 - ux * head, y1 - uy * head
    pen = QPen(color, w)
    pen.setCapStyle(Qt.FlatCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(x0, y0), QPointF(bx + ux, by + uy))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    hw = head * 0.7
    p.drawPolygon(QPolygonF([QPointF(x1, y1),
                             QPointF(bx - uy * hw, by + ux * hw),
                             QPointF(bx + uy * hw, by - ux * hw)]))
    p.restore()


_SECTION_FRAME = [QPointF(9, 30), QPointF(26, 39), QPointF(39, 21), QPointF(22, 12)]


def _section(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(9, 13, 30, 22))
    pen = QPen(_accent(), 3.0, Qt.DashLine)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(24, 6), QPointF(24, 42))            # the plane
    p.restore()
    _solid_arrow(p, _accent(), 28, 9, 38, 9)                # the side cut away


def _section_planes(p, ink):
    quad = QPolygonF(_SECTION_FRAME)
    dash = QPen(QColor(ink.red(), ink.green(), ink.blue(), 110), 1.8,
                Qt.DashLine)
    p.save()
    p.setPen(dash)
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(quad)
    p.restore()
    pen = QPen(ink, 3.0)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    pts = _SECTION_FRAME
    for i, c in enumerate(pts):                            # corner brackets
        for j in (1, -1):
            n = pts[(i + j) % 4]
            dx, dy = n.x() - c.x(), n.y() - c.y()
            L = math.hypot(dx, dy) or 1.0
            p.drawLine(c, QPointF(c.x() + dx * 7.0 / L, c.y() + dy * 7.0 / L))
    p.restore()


def _section_cuts(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(24, 13), QPointF(39, 13))
    p.drawLine(QPointF(39, 13), QPointF(39, 35))
    p.drawLine(QPointF(39, 35), QPointF(24, 35))
    pen = QPen(_accent(), 4.0)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(24, 13), QPointF(24, 35))            # the cut edge
    p.restore()


def _section_fill(p, ink):
    _section_cuts(p, ink)
    acc = _accent()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 150))
    p.drawRect(QRectF(24, 13, 15, 22))                     # the cut face
    p.restore()


def _protractor(p, ink):
    # A half-circle protractor with tick marks and an angled guide arm.
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 10, 28, 28), 0, 180 * 16)
    p.drawLine(QPointF(10, 24), QPointF(38, 24))       # the base
    import math as _m
    for adeg in (30, 60, 90, 120, 150):
        a = _m.radians(adeg)
        x1, y1 = 24 + 11 * _m.cos(a), 24 - 11 * _m.sin(a)
        x2, y2 = 24 + 14 * _m.cos(a), 24 - 14 * _m.sin(a)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    pen = p.pen()
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(24, 24), QPointF(40, 11))       # the angled guide
    pen.setStyle(Qt.SolidLine)
    p.setPen(pen)
    _dot(p, 24, 24)


def _pushpull(p, ink):
    """Push/Pull in the program's line style: a flat SLAB seen from above
    — top face tinted with the accent, a 5 px edge band — and a solid
    arrow (thick shaft, filled head) rising off its centre. Marco chose it
    among cubes, ghosts and thinner slabs (2026-09-14: «me encanta la
    losa, solo la flecha no tan larga»)."""
    cx, y_top, half_w, half_h, thick = 24.0, 33.0, 15.0, 7.0, 5.0
    top = QPolygonF([QPointF(cx - half_w, y_top), QPointF(cx, y_top - half_h),
                     QPointF(cx + half_w, y_top), QPointF(cx, y_top + half_h)])
    acc = _accent()
    p.setBrush(Qt.NoBrush)
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 130))
    p.drawPolygon(top)
    p.restore()
    p.drawPolygon(top)
    for x, y in ((cx - half_w, y_top), (cx, y_top + half_h), (cx + half_w, y_top)):
        p.drawLine(QPointF(x, y), QPointF(x, y + thick))
    p.drawLine(QPointF(cx - half_w, y_top + thick), QPointF(cx, y_top + half_h + thick))
    p.drawLine(QPointF(cx, y_top + half_h + thick), QPointF(cx + half_w, y_top + thick))
    # The arrow: shorter than the first draft, its head still clear of the slab.
    shaft = QPen(ink, 5.0)
    shaft.setCapStyle(Qt.FlatCap)
    p.save()
    p.setPen(shaft)
    p.drawLine(QPointF(cx, 32.0), QPointF(cx, 21.0))
    p.restore()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    p.drawPolygon(QPolygonF([QPointF(cx, 11.0), QPointF(cx - 8.5, 22.0),
                             QPointF(cx + 8.5, 22.0)]))
    p.restore()


def _offset(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(10, 12, 28, 24))
    p.drawRect(QRectF(16, 18, 16, 12))


def _fillet(p, ink):
    """Fillet: a square corner and the rounded one that replaces it — the
    sharp corner ghosted, the arc in the accent."""
    p.setBrush(Qt.NoBrush)
    ghost = QPen(ink, 1.6, Qt.DashLine)
    p.save()
    p.setPen(ghost)
    p.drawLine(QPointF(12, 24), QPointF(12, 12))
    p.drawLine(QPointF(12, 12), QPointF(24, 12))
    p.restore()
    path = QPainterPath()
    path.moveTo(12, 38)
    path.lineTo(12, 24)
    path.quadTo(12, 12, 24, 12)
    path.lineTo(38, 12)
    p.drawPath(path)
    p.save()
    p.setPen(QPen(_accent(), 3.0))
    arc = QPainterPath()
    arc.moveTo(12, 24)
    arc.quadTo(12, 12, 24, 12)
    p.drawPath(arc)
    p.restore()


def _move(p, ink):
    p.drawLine(QPointF(24, 10), QPointF(24, 38))
    p.drawLine(QPointF(10, 24), QPointF(38, 24))
    for (x, y, dx1, dy1, dx2, dy2) in (
        (24, 10, -4, 5, 4, 5), (24, 38, -4, -5, 4, -5),
        (10, 24, 5, -4, 5, 4), (38, 24, -5, -4, -5, 4)):
        p.drawLine(QPointF(x, y), QPointF(x + dx1, y + dy1))
        p.drawLine(QPointF(x, y), QPointF(x + dx2, y + dy2))


def _eyedropper(p, ink):
    """The Paint tool while Alt is held: the bucket becomes an eyedropper,
    which is how you know the next click SAMPLES instead of paints. Drawn
    like Inkscape's dropper (Marco, 2026-09-14): a slanted
    outlined tube from the tip at the hotspot up to a collar, a solid
    rubber bulb top-right, a drop of the sampled colour at the tip."""
    pen = QPen(ink, 3.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.save()
    p.translate(24.0, 24.0)             # 85 %: it read too big beside the
    p.scale(0.85, 0.85)                 # other tools (Marco, 2026-09-14)
    p.translate(-24.0, -24.0)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # Tube: two parallel edges, converging at the tip.
    p.drawLine(QPointF(26.5, 17.0), QPointF(11.0, 32.5))
    p.drawLine(QPointF(31.0, 21.5), QPointF(15.5, 37.0))
    p.drawLine(QPointF(11.0, 32.5), QPointF(8.0, 40.0))
    p.drawLine(QPointF(15.5, 37.0), QPointF(8.0, 40.0))
    # Collar across the tube.
    p.drawLine(QPointF(23.5, 14.5), QPointF(33.5, 24.5))
    # Bulb up-right of the collar, with a glint so it reads as rubber.
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    p.drawRoundedRect(QRectF(26.5, 5.0, 16.0, 16.0), 6.5, 6.5)
    p.restore()
    p.drawLine(QPointF(29.5, 12.0), QPointF(35.5, 18.0))
    # The drop leaving the tip: what the tool picks up.
    _dot(p, 5.5, 43.5, 2.6)
    p.restore()


def _paint(p, ink):
    # IngeTrazo's Paint tool (apply a colour/material to a face), replicating
    # Inkscape's symbolic "color-fill": a tilted square bucket (a diamond) half
    # full of paint, a handle stub at the top-right, a spout at the lower-left,
    # and a fat drop falling from it. Coordinates ported from the 16 px SVG
    # (scaled ×2.5 onto the 48 px canvas).
    s, ox, oy = 2.5, 1.0, 0.0

    def P(u, v):
        return QPointF(u * s + ox, v * s + oy)

    top, right, bottom, left = P(10.29, 2.4), P(14.89, 7), P(10.29, 11.6), P(5.69, 7)
    # Paint inside the bucket (the lower half of the diamond).
    p.setPen(Qt.NoPen)
    p.setBrush(_accent())
    p.drawPolygon(QPolygonF([left, right, bottom]))
    # Diamond frame (the tilted can).
    frame = QPen(ink, 3.4)
    frame.setJoinStyle(Qt.RoundJoin)
    p.setPen(frame)
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF([top, right, bottom, left]))
    # Handle stub at the top-right.
    handle = QPen(ink, 4.0)
    handle.setCapStyle(Qt.RoundCap)
    p.setPen(handle)
    p.drawLine(P(10.9, 2.5), P(12.3, 1.3))
    # Spout at the lower-left (a small ink notch toward the drop).
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    p.drawPolygon(QPolygonF([P(5.88, 5.74), P(4.0, 7.4), P(7.0, 9.0)]))
    # Falling paint drop (accent).
    p.setBrush(_accent())
    drop = QPainterPath()
    drop.moveTo(P(3.5, 9.0))
    drop.quadTo(P(6.0, 11.6), P(6.0, 13.4))
    drop.quadTo(P(6.0, 16.0), P(3.5, 16.0))
    drop.quadTo(P(1.0, 16.0), P(1.0, 13.4))
    drop.quadTo(P(1.0, 11.6), P(3.5, 9.0))
    p.drawPath(drop)


def _dim_tick(p, ink, x: float, y: float, s: float = 3.5) -> None:
    """A dimension line's end: a solid round terminator (a dot), which
    reads at any size and needs no direction."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    p.drawEllipse(QPointF(x, y), s * 0.8, s * 0.8)
    p.restore()


def _dimension(p, ink):
    # A dimension as it is drawn: the measured edge with its two points in
    # the accent (the clicks), extension lines up to the dimension line,
    # round terminators and a plain «3» as the value («1.20» read as noise
    # at toolbar size).
    A, B = (10.0, 39.0), (38.0, 39.0)
    p.drawLine(QPointF(*A), QPointF(*B))                     # the measured edge
    _guide(p, ink, (A[0], 37.0), (A[0], 17.0))               # extension lines
    _guide(p, ink, (B[0], 37.0), (B[0], 17.0))
    p.drawLine(QPointF(A[0], 21.0), QPointF(B[0], 21.0))     # dimension line
    _dim_tick(p, ink, A[0], 21.0)
    _dim_tick(p, ink, B[0], 21.0)
    f = p.font()
    f.setPixelSize(13)
    f.setBold(True)
    p.save()
    p.setFont(f)
    p.setPen(ink)
    p.drawText(QRectF(14.0, 5.0, 20.0, 14.0), Qt.AlignCenter, "3")
    p.restore()
    _dot(p, A[0], A[1], 2.9)
    _dot(p, B[0], B[1], 2.9)


def _dimension_style(p, ink):
    # The Dimension-style panel: a dimension with a brush over it (the
    # look of the cotas), so it no longer reads as the Dimension tool
    # (Marco's pick, 2026-09-14).
    p.drawLine(QPointF(9, 36), QPointF(39, 36))
    p.drawLine(QPointF(9, 30), QPointF(9, 42))
    p.drawLine(QPointF(39, 30), QPointF(39, 42))
    p.save()
    pen = QPen(ink, 3.0)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(40, 8), QPointF(28, 20))            # handle
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_accent()))
    p.drawPolygon(QPolygonF([QPointF(29, 18), QPointF(31, 22),
                             QPointF(25, 26), QPointF(22, 23)]))   # bristles
    p.restore()


def _dimension_chain(p, ink):
    # Two dimension segments sharing one line, the total stacked above —
    # with the slash ticks and the measured points, to match Dimension.
    p.drawLine(QPointF(8, 32), QPointF(40, 32))
    for x in (8, 24, 40):
        p.drawLine(QPointF(x, 27), QPointF(x, 37))
        _dim_tick(p, ink, x, 32, 3.0)
    p.drawLine(QPointF(8, 18), QPointF(40, 18))
    p.drawLine(QPointF(8, 14), QPointF(8, 22))
    p.drawLine(QPointF(40, 14), QPointF(40, 22))
    _dim_tick(p, ink, 8, 18, 3.0)
    _dim_tick(p, ink, 40, 18, 3.0)
    for x in (8, 24, 40):
        _dot(p, x, 37, 2.6)


def _dimension_radius(p, ink):
    """Radius dimension, in IngeCAD's key for its DIM icons (Marco's pick,
    2026-09-19): the SUBJECT in the accent, heavier — the circle — and the
    DIMENSION over it in ink, a leader out of the centre with its arrow on
    the arc. No letter: at 24 px an «R» was noise."""
    import math as _m
    cx, cy, R = 21.0, 26.0, 14.0
    p.save()
    p.setPen(QPen(_accent(), 3.2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), R, R)
    p.restore()
    a = _m.radians(-40.0)
    ex, ey = cx + R * _m.cos(a), cy + R * _m.sin(a)
    _solid_arrow(p, ink, cx, cy, ex, ey, w=2.2, head=6.5)
    _dot(p, cx, cy, 2.6, ink)                       # the centre it measures from


def _dimension_diameter(p, ink):
    """Its twin: the line crosses the centre and has an arrow at each end."""
    import math as _m
    cx, cy, R = 24.0, 24.0, 14.0
    p.save()
    p.setPen(QPen(_accent(), 3.2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), R, R)
    p.restore()
    a = _m.radians(-40.0)
    dx, dy = R * _m.cos(a), R * _m.sin(a)
    _solid_arrow(p, ink, cx, cy, cx + dx, cy + dy, w=2.2, head=6.5)
    _solid_arrow(p, ink, cx, cy, cx - dx, cy - dy, w=2.2, head=6.5)


def _dimension_angular(p, ink):
    """Angular dimension, same key: the two LEGS in the accent, and the
    dimension arc between them in ink with an arrow at each end. It used
    to borrow the Protractor's icon, which is a different tool."""
    import math as _m
    vx, vy = 11.0, 35.0
    a0, a1 = _m.radians(0.0), _m.radians(-58.0)      # the two legs, page y down
    L = 28.0
    p.save()
    p.setPen(QPen(_accent(), 3.2))
    for a in (a0, a1):
        p.drawLine(QPointF(vx, vy),
                   QPointF(vx + L * _m.cos(a), vy + L * _m.sin(a)))
    p.restore()
    R = 17.0
    rect = QRectF(vx - R, vy - R, 2 * R, 2 * R)
    p.save()
    p.setPen(QPen(ink, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawArc(rect, 0, 58 * 16)                      # QPainter angles: y up
    p.restore()
    for a, side in ((a0, 1.0), (a1, -1.0)):
        ax, ay = vx + R * _m.cos(a), vy + R * _m.sin(a)
        t = a - side * _m.radians(90.0)              # along the arc
        _solid_arrow(p, ink, ax - 7.0 * _m.cos(t), ay - 7.0 * _m.sin(t),
                     ax, ay, w=1.8, head=5.5)


def _dimension_baseline(p, ink):
    """Baseline dimensions: three lines that all start at the SAME left
    edge and stack upward, each one longer than the last — AutoCAD's
    DIMBASELINE. Its twin, Chain, puts them end to end on one line."""
    x0 = 9.0
    _guide(p, ink, (x0, 40.0), (x0, 8.0))                 # the base extension
    for i, (x1, y) in enumerate(((22.0, 34.0), (31.0, 25.0), (40.0, 16.0))):
        _guide(p, ink, (x1, 40.0), (x1, y - 3.0))
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        _dim_tick(p, ink, x0, y, 3.0)
        _dim_tick(p, ink, x1, y, 3.0)
    _dot(p, x0, 40.0, 2.6)                                # the base point
    for x in (22.0, 31.0, 40.0):
        _dot(p, x, 40.0, 2.2)


def _geopath(p, ink):
    pen = p.pen()
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(11, 34), QPointF(20, 16),
                              QPointF(30, 30), QPointF(38, 14)]))
    pen.setStyle(Qt.SolidLine)
    p.setPen(pen)
    for x, y in ((11, 34), (20, 16), (30, 30), (38, 14)):
        _dot(p, x, y, 2.8)


def _undo(p, ink):
    # A bold curved arrow turning back to the left (Marco's pick, 23-09):
    # the head at the upper left, the body sweeping round and down to a
    # tapered tail. Ink outline and a soft accent fill, like the solid tools;
    # drawn at 80 % so it keeps the proportion of its neighbours.
    path = QPainterPath(QPointF(4, 17))          # the tip
    path.lineTo(QPointF(21, 4))                  # head, upper corner
    path.lineTo(QPointF(20, 11))                 # where the body leaves the head
    path.cubicTo(QPointF(37, 10), QPointF(47, 24), QPointF(33, 44))
    path.cubicTo(QPointF(32, 45.5), QPointF(29.5, 45), QPointF(30, 43))
    path.cubicTo(QPointF(36, 31), QPointF(31, 23), QPointF(19, 24))
    path.lineTo(QPointF(18, 31))                 # head, lower corner
    path.closeSubpath()
    p.save()
    p.translate(_PX / 2, _PX / 2)
    p.scale(0.8, 0.8)
    p.translate(-_PX / 2 - 1.5, -_PX / 2)
    pen = QPen(ink, 2.6 / 0.8)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    acc = _accent()
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 150))
    p.drawPath(path)
    p.restore()


def _redo(p, ink):
    # Undo seen in a mirror.
    p.save()
    p.translate(_PX, 0)
    p.scale(-1, 1)
    _undo(p, ink)
    p.restore()


def _orbit(p, ink):
    # A sphere with an arrow orbiting around it — Orbit (spin the view around
    # the model). The orbit ring passes behind the sphere at the top and in
    # front along the bottom, so it reads as a true orbit, not a flat rotation.
    cx, cy = 24.0, 25.0
    rx, ry = 15.0, 7.6
    rect = QRectF(cx - rx, cy - ry, 2 * rx, 2 * ry)
    ring = QPen(ink, 3.0)
    ring.setJoinStyle(Qt.RoundJoin)
    ring.setCapStyle(Qt.RoundCap)
    # Far side of the ring (top) — drawn first so the sphere hides its middle.
    p.setPen(ring)
    p.setBrush(Qt.NoBrush)
    p.drawArc(rect, 150 * 16, -132 * 16)
    # The sphere (accent colour, so it pops as the thing being orbited).
    p.setPen(Qt.NoPen)
    p.setBrush(_accent())
    p.drawEllipse(QPointF(cx, 19.5), 7.6, 7.6)
    # Near side of the ring (bottom, in front) with an arrowhead.
    p.setPen(ring)
    p.setBrush(Qt.NoBrush)
    start_a, end_a = 214, 338
    p.drawArc(rect, start_a * 16, (end_a - start_a) * 16)   # through the bottom
    a = math.radians(end_a)
    px, py = cx + rx * math.cos(a), cy - ry * math.sin(a)
    tx, ty = -rx * math.sin(a), -ry * math.cos(a)           # tangent (direction)
    tl = math.hypot(tx, ty)
    tx, ty = tx / tl, ty / tl
    for rot in (math.radians(38), math.radians(-38)):
        dx = -tx * math.cos(rot) + ty * math.sin(rot)
        dy = -tx * math.sin(rot) - ty * math.cos(rot)
        p.drawLine(QPointF(px, py), QPointF(px + 7.0 * dx, py + 7.0 * dy))


def _pan(p, ink):
    # Pan as a drag gesture, drawn in LINE like the reference Marco sent
    # (2026-09-14): an outlined pointing hand — index up with a rounded
    # tip, three folded fingers as bumps, the thumb tucked at the left, a
    # tapered wrist — a touch arc over the fingertip and a horizontal
    # double arrow at that level.
    from PySide6.QtGui import QPainterPath
    P = QPainterPath()
    P.moveTo(17.5, 33.0)
    P.lineTo(17.5, 14.5)                          # index, left edge
    P.cubicTo(17.5, 9.5, 24.5, 9.5, 24.5, 14.5)   # rounded tip
    P.lineTo(24.5, 26.0)
    P.cubicTo(25.0, 22.5, 30.5, 22.5, 31.0, 26.0)  # folded fingers
    P.cubicTo(31.5, 23.5, 36.5, 23.5, 37.0, 27.0)
    P.cubicTo(37.5, 25.0, 42.0, 25.5, 42.0, 29.0)
    P.lineTo(42.0, 34.0)
    P.cubicTo(42.0, 41.0, 37.0, 45.0, 31.0, 45.0)  # into the wrist
    P.lineTo(23.0, 45.0)
    P.cubicTo(17.0, 45.0, 13.0, 41.0, 12.0, 37.0)
    P.cubicTo(11.0, 34.0, 8.0, 32.5, 8.5, 29.0)    # thumb
    P.cubicTo(9.0, 26.5, 12.5, 26.0, 14.5, 28.0)
    P.cubicTo(15.5, 29.5, 16.5, 31.5, 17.5, 33.0)
    P.closeSubpath()
    pen = QPen(ink, 2.8)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.translate(24.0, 25.0)             # 88 %: a touch smaller than the
    p.scale(0.88, 0.88)                 # other tools (Marco, 2026-09-14)
    p.translate(-24.0, -25.0)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(P)
    # The gesture — touch arc and double arrow — in the accent (Marco: «la C»).
    r = 7.0
    p.setPen(QPen(_accent(), 2.4, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(QRectF(21.0 - r, 13.5 - r, 2 * r, 2 * r), 20 * 16, 140 * 16)
    pen = QPen(_accent(), 2.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    y = 13.5
    p.drawLine(QPointF(3.5, y), QPointF(11.5, y))
    p.drawLine(QPointF(3.5, y), QPointF(7.0, y - 3.5))
    p.drawLine(QPointF(3.5, y), QPointF(7.0, y + 3.5))
    p.drawLine(QPointF(30.5, y), QPointF(38.5, y))
    p.drawLine(QPointF(38.5, y), QPointF(35.0, y - 3.5))
    p.drawLine(QPointF(38.5, y), QPointF(35.0, y + 3.5))
    p.restore()


def _eraser(p, ink):
    # Eraser: a rubber block tilted as it is held, its working end in the
    # accent, and a few crumbs it has rubbed off.
    w, h, tip = 30.0, 15.0, 0.38
    p.save()
    p.translate(26, 21)
    p.rotate(-40)
    p.setPen(Qt.NoPen)
    p.setBrush(_accent())
    p.drawRoundedRect(QRectF(-w / 2, -h / 2, w * tip, h), 3, 3)
    p.drawRect(QRectF(-w / 2 + 3, -h / 2, w * tip - 3, h))
    p.setPen(_rpen(ink, 2.8))
    p.setBrush(Qt.NoBrush)
    body = QPainterPath()
    body.addRoundedRect(QRectF(-w / 2, -h / 2, w, h), 3, 3)
    p.drawPath(body)
    p.drawLine(QPointF(-w / 2 + w * tip, -h / 2),
               QPointF(-w / 2 + w * tip, h / 2))
    p.restore()
    crumbs = QColor(ink.red(), ink.green(), ink.blue(), 170)
    for x, y in ((9, 40), (15, 42), (12, 36)):
        _dot(p, x, y, 1.6, crumbs)


def _tape(p, ink):
    # A tape-measure body (right) with the tape pulled out to the left and
    # a hook — mirrored at Marco's request (2026-09-14: «el circulito al
    # lado derecho»).
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(30, 20), 8.5, 8.5)
    p.drawEllipse(QPointF(30, 20), 2.6, 2.6)
    p.drawLine(QPointF(30, 28.5), QPointF(10, 28.5))   # the tape
    p.drawLine(QPointF(10, 25.5), QPointF(10, 31.5))   # end hook
    for x in (24, 19, 14):                              # tick marks
        p.drawLine(QPointF(x, 28.5), QPointF(x, 25.8))


def _magnifier(p, ink, cx, cy, r, handle=True):
    """A magnifying glass: a lens circle centred at ``(cx, cy)`` with an
    optional handle to the lower-right. Shared by the zoom icons."""
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)
    if handle:
        d = r / math.sqrt(2)
        grip = QPen(ink, 4.0)
        grip.setCapStyle(Qt.RoundCap)
        p.save()
        p.setPen(grip)
        p.drawLine(QPointF(cx + d, cy + d), QPointF(cx + d + 8, cy + d + 8))
        p.restore()


def _zoom(p, ink):
    # A plain magnifying glass — the Zoom tool (drag up/down to zoom in/out).
    _magnifier(p, ink, 21, 21, 9)


def _zoom_window(p, ink):
    # A magnifier inside a rectangle — Zoom Window (drag a box to zoom to it).
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(9, 11, 30, 26))            # the window rectangle
    _magnifier(p, ink, 21, 22, 6.5)              # magnifier inside it


def _zoom_extents(p, ink):
    # Zoom Extents (#112): the four corners of the view as accent brackets
    # and a magnifier in the middle — everything brought inside the frame.
    p.save()
    p.setPen(_rpen(_accent(), 3.4))
    p.setBrush(Qt.NoBrush)
    a, b, arm = 7.0, 41.0, 8.0
    for x, y, dx, dy in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
    p.restore()
    _magnifier(p, ink, 22.0, 22.0, 7.5)


def _zoom_selection(p, ink):
    # Zoom Selection: Zoom Extents' four corner brackets, closing on a
    # solid square in place of the magnifier — the selection alone fills
    # the view.
    p.save()
    p.setPen(_rpen(_accent(), 3.4))
    p.setBrush(Qt.NoBrush)
    a, b, arm = 7.0, 41.0, 8.0
    for x, y, dx, dy in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
    p.setPen(_rpen(ink, 2.6))
    p.setBrush(_accent())
    p.drawRect(QRectF(17.0, 17.0, 14.0, 14.0))
    p.restore()


# ---- Standard-view icons: a little house drawn from each viewpoint ----------
# Each orthographic view shows IngeTrazo's own little house from that
# direction — ONE gable house, consistently, no windows: the door on the
# front gable, the chimney on the right slope toward the back (right of
# the apex from the front, left of it from behind, at the far end from
# each side, a square at the back-right of the roof from above). The wall
# you look at is filled with the accent, which is what tells the views
# apart at a glance (Marco, 2026-09-14, chosen among a dozen candidates).

def _accent_fill(p, poly, alpha: int = 150) -> None:
    acc = _accent()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), alpha))
    if isinstance(poly, QRectF):
        p.drawRect(poly)
    else:
        p.drawPolygon(poly)
    p.restore()


def _solid(p, ink, poly) -> None:
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    if isinstance(poly, QRectF):
        p.drawRect(poly)
    else:
        p.drawPolygon(poly)
    p.restore()


def _chimney(p, ink, x: float, roof_y: float, h: float = 6.0, w: float = 4.0):
    """A chimney stack rising ``h`` above the roof line at ``x``."""
    _solid(p, ink, QRectF(x - w / 2, roof_y - h, w, h))


_GABLE = QPolygonF([QPointF(9, 22), QPointF(23, 9), QPointF(37, 22)])
_GABLE_WALL = QRectF(12, 22, 22, 15)


def _view_front(p, ink):
    # Gable end seen head-on: the wall in accent, ONE wide door, chimney
    # RIGHT of the apex. (Front)
    _accent_fill(p, _GABLE_WALL)
    p.setBrush(Qt.NoBrush)
    p.drawRect(_GABLE_WALL)
    p.drawPolygon(_GABLE)
    _chimney(p, ink, 31.0, 15.0, h=6.5)
    _solid(p, ink, QRectF(18, 28, 10, 9))                  # wide door


def _view_back(p, ink):
    # Same gable end from behind: blank wall in accent, chimney LEFT. (Back)
    _accent_fill(p, _GABLE_WALL)
    p.setBrush(Qt.NoBrush)
    p.drawRect(_GABLE_WALL)
    p.drawPolygon(_GABLE)
    _chimney(p, ink, 15.0, 15.0, h=6.5)


def _house_side(mirror: bool):
    # Long wall seen side-on, in accent, under a low roof; the chimney at
    # the BACK end — the right end seen from the right, the left end seen
    # from the left (mirror images).
    def draw(p, ink):
        p.save()
        if mirror:
            p.translate(48, 0)
            p.scale(-1, 1)
        # A touch wider than the front — the house is square in plan, but a
        # hair of length tells the side from the gable at a glance (Marco,
        # 2026-09-14).
        wall = QRectF(11, 23, 27, 14)
        _accent_fill(p, wall)
        p.setBrush(Qt.NoBrush)
        p.drawRect(wall)
        p.drawPolygon(QPolygonF([QPointF(9, 23), QPointF(14, 15),
                                 QPointF(35, 15), QPointF(40, 23)]))  # roof
        _chimney(p, ink, 33.0, 15.0, h=6.0)
        p.restore()
    return draw


def _view_top(p, ink):
    # The gable roof from directly above: the footprint in accent, ONE
    # ridge line down the middle (two slopes, not four), the chimney as a
    # square at the back-right.
    roof = QRectF(9, 11, 24, 24)
    _accent_fill(p, roof)
    p.setBrush(Qt.NoBrush)
    p.drawRect(roof)
    p.drawLine(QPointF(21, 11), QPointF(21, 35))           # ridge
    _solid(p, ink, QRectF(25.5, 13.5, 4.5, 4.5))           # chimney
    # a hint of the front: the door's end is the bottom edge — a short
    # tick there keeps top and bottom apart from the other symbols
    p.drawLine(QPointF(17, 35), QPointF(25, 35))


def _view_bottom(p, ink):
    # The slab from below, in accent, with the walls starting off it: a
    # short diagonal stub at each corner (Marco's pick, 2026-09-14).
    slab = QRectF(9, 11, 24, 24)
    _accent_fill(p, slab)
    p.setBrush(Qt.NoBrush)
    p.drawRect(slab)
    for x in (9.0, 33.0):
        for y in (11.0, 35.0):
            p.drawLine(QPointF(x, y),
                       QPointF(x + (4.0 if x == 9.0 else -4.0),
                               y + (4.0 if y == 11.0 else -4.0)))


def _view_iso(p, ink):
    # The same house in isometric with its EAVES: gable end (door) at the
    # left, long side at the right, the roof slope overhanging both wall
    # and gable, chimney at the back of the slope.
    wl, wf, wr = QPointF(11, 23), QPointF(23, 29), QPointF(37, 22)
    bl, bf, br = QPointF(11, 35), QPointF(23, 41), QPointF(37, 34)
    apex = QPointF(17, 15.5)
    back_apex = apex + (wr - wf)
    gable = QPolygonF([bl, bf, wf, apex, wl])
    side = QPolygonF([wf, wr, br, bf])
    out = QPointF(-2.4, -1.2)          # forward, through the gable plane
    eave = QPointF(2.6, 1.6)           # outward past the side wall
    r_front_top, r_back_top = apex + out, back_apex - out * 0.4
    r_front_low = wf + out + eave + QPointF(0, -1.0)
    r_back_low = wr - out * 0.4 + eave + QPointF(0, -1.0)
    slope = QPolygonF([r_front_top, r_back_top, r_back_low, r_front_low])
    _accent_fill(p, gable, 150)
    _accent_fill(p, side, 90)
    _accent_fill(p, slope, 60)
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(gable)
    p.drawPolygon(side)
    p.drawPolygon(slope)
    p.drawLine(r_front_top, wl + out)                      # left rake edge
    cx, cy = 30.5, 13.5
    _solid(p, ink, QRectF(cx - 1.8, cy - 1, 3.6, 7))       # chimney
    _solid(p, ink, QPolygonF([QPointF(15, 30.5), QPointF(19, 32.5),
                              QPointF(19, 39.5), QPointF(15, 37.5)]))   # door


def _text(p, ink):
    # Text: a capital T inside a text frame (dashed), with the insertion
    # point as the accent dot at the frame's corner.
    faint = QColor(ink)
    faint.setAlpha(150)
    p.save()
    p.setPen(QPen(faint, 1.8, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(9, 10, 30, 28))
    p.restore()
    p.save()
    p.setPen(_rpen(ink, 3.6))
    p.drawLine(QPointF(16, 17), QPointF(32, 17))
    p.drawLine(QPointF(24, 17), QPointF(24, 32))
    p.restore()
    _dot(p, 9, 38, 3.0)


def _text3d(p, ink):
    # A solid 3D-extruded "A": an accent-coloured extrusion stacked toward the
    # upper-right, with the ink front face on top — so it reads as a block of 3D
    # text (the 3D sibling of the 2D Text "A").
    f = p.font()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    base = QPointF(12, 35)
    # Extrusion depth: many closely-spaced accent copies form a solid side.
    p.setPen(_accent())
    d = 6.0
    n = 12
    for i in range(n, 0, -1):
        off = d * i / n
        p.drawText(QPointF(base.x() + off, base.y() - off), "A")
    # Front face on top.
    p.setPen(QPen(ink))
    p.drawText(base, "A")


# ── Composer (sheet layout) icons ──────────────────────────────────────────

def _image_icon(p, ink):
    # a photo: frame, sun and mountain
    p.drawRect(8, 12, 32, 24)
    p.drawEllipse(QPointF(17, 20), 3, 3)
    p.drawPolyline(QPolygonF([QPointF(12, 32), QPointF(22, 24),
                              QPointF(28, 29), QPointF(36, 21)]))


def _comp_vista(p, ink):
    # a paper frame holding a tiny iso cube — the model-view item
    p.drawRect(8, 8, 32, 32)
    p.drawLine(QPointF(24, 16), QPointF(33, 21))
    p.drawLine(QPointF(24, 16), QPointF(15, 21))
    p.drawLine(QPointF(15, 21), QPointF(15, 30))
    p.drawLine(QPointF(33, 21), QPointF(33, 30))
    p.drawLine(QPointF(15, 30), QPointF(24, 35))
    p.drawLine(QPointF(33, 30), QPointF(24, 35))
    p.drawLine(QPointF(24, 16), QPointF(24, 26))


def _comp_norte(p, ink):
    p.drawEllipse(QPointF(24, 24), 16, 16)
    p.setBrush(ink)
    poly = QPolygonF([QPointF(24, 10), QPointF(29, 28), QPointF(24, 24),
                      QPointF(19, 28)])
    p.drawPolygon(poly)


def _comp_leyenda(p, ink):
    for i, y in enumerate((12, 24, 36)):
        p.drawRect(8, y - 3, 6, 6)
        p.drawLine(QPointF(20, y), QPointF(40, y))


def _comp_escala(p, ink):
    p.setBrush(ink)
    p.drawRect(6, 20, 9, 7)
    p.setBrush(Qt.NoBrush)
    p.drawRect(15, 20, 9, 7)
    p.setBrush(ink)
    p.drawRect(24, 20, 9, 7)
    p.setBrush(Qt.NoBrush)
    p.drawRect(33, 20, 9, 7)


def _comp_perfil(p, ink):
    # axes + a ground line: the longitudinal profile
    p.drawLine(QPointF(8, 8), QPointF(8, 38))
    p.drawLine(QPointF(8, 38), QPointF(42, 38))
    poly = QPolygonF([QPointF(10, 30), QPointF(18, 22), QPointF(24, 26),
                      QPointF(32, 14), QPointF(40, 20)])
    p.drawPolyline(poly)


def _comp_cajetin(p, ink):
    p.drawRect(6, 14, 36, 20)
    p.drawLine(QPointF(6, 24), QPointF(42, 24))
    p.drawLine(QPointF(18, 14), QPointF(18, 34))


def _comp_flecha(p, ink):
    p.drawLine(QPointF(10, 38), QPointF(38, 10))
    p.drawLine(QPointF(38, 10), QPointF(26, 13))
    p.drawLine(QPointF(38, 10), QPointF(35, 22))


def _comp_terreno(p, ink):
    # A ground line with the earth ticks hanging under it.
    p.drawLine(QPointF(6, 24), QPointF(42, 24))
    for x in (10, 17, 24, 31, 38):
        p.drawLine(QPointF(x, 24), QPointF(x - 5, 31))


def _save(p, ink):
    # The floppy that never dies: a square with a label slot and a shutter.
    p.drawRect(QRectF(9, 9, 30, 30))
    p.drawRect(QRectF(16, 9, 16, 9))              # the shutter, top
    p.drawRect(QRectF(15, 25, 18, 14))            # the label, bottom
    p.drawLine(QPointF(27, 11), QPointF(27, 16))


def _refresh(p, ink):
    # Two arrows chasing each other round a circle — update the views.
    p.setBrush(Qt.NoBrush)
    r = QRectF(11, 11, 26, 26)
    p.drawArc(r, 30 * 16, 120 * 16)
    p.drawArc(r, 210 * 16, 120 * 16)
    p.setBrush(ink)
    p.drawPolygon(QPolygonF([QPointF(36, 8), QPointF(39, 18), QPointF(29, 16)]))
    p.drawPolygon(QPolygonF([QPointF(12, 40), QPointF(9, 30), QPointF(19, 32)]))


def _export_pdf(p, ink):
    # A page with a folded corner and an arrow leaving it — export.
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(28, 8), QPointF(10, 8), QPointF(10, 40),
                              QPointF(34, 40), QPointF(34, 14), QPointF(28, 8),
                              QPointF(28, 14), QPointF(34, 14)]))
    p.drawLine(QPointF(17, 22), QPointF(27, 22))
    p.drawLine(QPointF(17, 28), QPointF(27, 28))
    p.drawLine(QPointF(30, 33), QPointF(42, 33))   # the arrow out
    p.drawLine(QPointF(38, 29), QPointF(42, 33))
    p.drawLine(QPointF(38, 37), QPointF(42, 33))


def _print_preview(p, ink):
    # A page under a magnifier — see it as it prints.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(9, 7, 22, 30))
    p.drawLine(QPointF(14, 15), QPointF(26, 15))
    p.drawLine(QPointF(14, 21), QPointF(26, 21))
    _magnifier(p, ink, 30, 30, 7)


def _comp_etiqueta(p, ink):
    # A label: two text lines in a box, with a leader arrow to a point.
    p.drawRect(QRectF(20, 8, 22, 16))
    p.drawLine(QPointF(24, 14), QPointF(38, 14))
    p.drawLine(QPointF(24, 19), QPointF(34, 19))
    p.drawLine(QPointF(20, 24), QPointF(9, 38))
    p.drawLine(QPointF(9, 38), QPointF(12, 30))
    p.drawLine(QPointF(9, 38), QPointF(17, 35))


def _comp_nivel(p, ink):
    # A level mark: open triangle on its apex, the level line, «+0.00».
    p.drawPolygon(QPolygonF([QPointF(14, 30), QPointF(8, 20), QPointF(20, 20)]))
    p.drawLine(QPointF(14, 20), QPointF(42, 20))
    p.drawLine(QPointF(24, 13), QPointF(30, 13))
    p.drawLine(QPointF(27, 10), QPointF(27, 16))
    p.drawLine(QPointF(33, 10), QPointF(40, 10))
    p.drawLine(QPointF(33, 16), QPointF(40, 16))


def _comp_llamada(p, ink):
    # A detail callout: dashed box, leader, bubble with a divider.
    pen = p.pen()
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(8, 18, 20, 16), 2, 2)
    pen.setStyle(Qt.SolidLine)
    p.setPen(pen)
    p.drawLine(QPointF(28, 20), QPointF(34, 15))
    p.drawEllipse(QRectF(33, 6, 12, 12))
    p.drawLine(QPointF(33, 12), QPointF(45, 12))


def _styles_icon(p, ink):
    # Three fanned swatch cards — the material/style deck.
    p.save()
    for i, (dx, dy, fill) in enumerate(((0, 6, None), (5, 3, None),
                                        (10, 0, _accent()))):
        r = QRectF(10 + dx, 12 + dy, 18, 24)
        p.setBrush(fill if fill is not None else Qt.NoBrush)
        p.drawRoundedRect(r, 3, 3)
    p.restore()


def _shadows_icon(p, ink):
    # A block with its cast shadow, sun rays at the corner.
    p.save()
    p.setBrush(QColor(ink.red(), ink.green(), ink.blue(), 90))
    p.setPen(Qt.NoPen)
    p.drawPolygon(QPolygonF([QPointF(16, 36), QPointF(34, 36),
                             QPointF(42, 42), QPointF(24, 42)]))
    p.restore()
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(16, 20, 16, 16))
    _dot(p, 12, 12, 4.0)
    p.save()
    pen = QPen(_accent(), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    for ang in (200, 245, 290, 335):
        a = math.radians(ang)
        p.drawLine(QPointF(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)),
                   QPointF(12 + 10.5 * math.cos(a), 12 + 10.5 * math.sin(a)))
    p.restore()


# ---- Composer: Arrange (align / distribute / group / lock) -------------------
# Two boxes and a reference line, in the same ink and accent as every other
# tool. They replaced Unicode glyphs (⇤ ⤒ ⊞ 🔒…) that drew in the text
# font, thin and off-theme (Marco, 2026-09-14).

def _arr_boxes(p, ink, a: QRectF, b: QRectF, accent_line=None) -> None:
    p.setBrush(Qt.NoBrush)
    p.drawRect(a)
    p.drawRect(b)
    if accent_line is not None:
        pen = QPen(_accent(), 3.0)
        pen.setCapStyle(Qt.RoundCap)
        p.save()
        p.setPen(pen)
        p.drawLine(*accent_line)
        p.restore()


def _arr_left(p, ink):
    _arr_boxes(p, ink, QRectF(14, 13, 20, 6), QRectF(14, 29, 12, 6),
               (QPointF(10, 8), QPointF(10, 40)))


def _arr_right(p, ink):
    _arr_boxes(p, ink, QRectF(14, 13, 20, 6), QRectF(22, 29, 12, 6),
               (QPointF(38, 8), QPointF(38, 40)))


def _arr_top(p, ink):
    _arr_boxes(p, ink, QRectF(13, 14, 6, 20), QRectF(29, 14, 6, 12),
               (QPointF(8, 10), QPointF(40, 10)))


def _arr_bottom(p, ink):
    _arr_boxes(p, ink, QRectF(13, 14, 6, 20), QRectF(29, 22, 6, 12),
               (QPointF(8, 38), QPointF(40, 38)))


def _arr_hcenter(p, ink):
    _arr_boxes(p, ink, QRectF(12, 13, 24, 6), QRectF(17, 29, 14, 6),
               (QPointF(24, 7), QPointF(24, 41)))


def _arr_vcenter(p, ink):
    _arr_boxes(p, ink, QRectF(13, 12, 6, 24), QRectF(29, 17, 6, 14),
               (QPointF(7, 24), QPointF(41, 24)))


def _arr_dist_h(p, ink):
    # three boxes, equal gaps; the accent marks the gaps
    p.setBrush(Qt.NoBrush)
    for x in (8, 20, 32):
        p.drawRect(QRectF(x, 16, 8, 16))
    pen = QPen(_accent(), 2.6)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(17, 24), QPointF(19, 24))
    p.drawLine(QPointF(29, 24), QPointF(31, 24))
    p.restore()


def _arr_dist_v(p, ink):
    p.setBrush(Qt.NoBrush)
    for y in (8, 20, 32):
        p.drawRect(QRectF(16, y, 16, 8))
    pen = QPen(_accent(), 2.6)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(24, 17), QPointF(24, 19))
    p.drawLine(QPointF(24, 29), QPointF(24, 31))
    p.restore()


def _arr_duplicate(p, ink):
    # a box and its copy, offset; the copy's corner marked with the accent
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(10, 10, 20, 20))
    p.drawRect(QRectF(18, 18, 20, 20))
    _dot(p, 38, 38, 2.8)


def _arr_group(p, ink):
    # two boxes inside a dashed frame
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(12, 15, 9, 9))
    p.drawRect(QRectF(27, 24, 9, 9))
    pen = QPen(_accent(), 2.4, Qt.DashLine)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawRect(QRectF(7, 10, 34, 28))
    p.restore()


def _arr_ungroup(p, ink):
    # the same two boxes, the frame broken open (two corner brackets)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(12, 15, 9, 9))
    p.drawRect(QRectF(27, 24, 9, 9))
    pen = QPen(_accent(), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(7, 18), QPointF(7, 10))
    p.drawLine(QPointF(7, 10), QPointF(15, 10))
    p.drawLine(QPointF(41, 30), QPointF(41, 38))
    p.drawLine(QPointF(41, 38), QPointF(33, 38))
    p.restore()


def _arr_lock(p, ink):
    # a padlock: body in ink, shackle in line
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(16, 9, 16, 16), 0, 180 * 16)
    p.drawLine(QPointF(16, 17), QPointF(16, 22))
    p.drawLine(QPointF(32, 17), QPointF(32, 22))
    _solid(p, ink, QRectF(12, 22, 24, 16))
    _dot(p, 24, 30, 2.6)


# ---- Sidebar handle (LibreOffice-style): the fold / unfold chevron ----------

def _side_collapse(p, ink):
    # A chevron pointing right: fold the sidebar away (points left to open).
    pen = QPen(ink, 3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(19, 13), QPointF(30, 24))
    p.drawLine(QPointF(30, 24), QPointF(19, 35))
    p.restore()


def _overflow_h(p, ink):
    # Double chevron «»»: the toolbar's hidden tools, on a horizontal bar.
    pen = QPen(_accent(), 3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.save()
    p.setPen(pen)
    for x in (10, 24):
        p.drawLine(QPointF(x, 14), QPointF(x + 10, 24))
        p.drawLine(QPointF(x + 10, 24), QPointF(x, 34))
    p.restore()


def _overflow_v(p, ink):
    # The same, pointing down, for a vertical bar.
    pen = QPen(_accent(), 3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.save()
    p.setPen(pen)
    for y in (10, 24):
        p.drawLine(QPointF(14, y), QPointF(24, y + 10))
        p.drawLine(QPointF(24, y + 10), QPointF(34, y))
    p.restore()


def _side_expand(p, ink):
    pen = QPen(ink, 3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(29, 13), QPointF(18, 24))
    p.drawLine(QPointF(18, 24), QPointF(29, 35))
    p.restore()


def _rpen(color, width: float) -> QPen:
    q = QPen(color, width)
    q.setCapStyle(Qt.RoundCap)
    q.setJoinStyle(Qt.RoundJoin)
    return q


def _disc(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _position_camera(p, ink):
    # Position Camera: a small camera, its lens in the accent, and under it
    # an accent marker pointing down -- the camera goes where you click.
    top = QPainterPath()
    top.moveTo(15, 12)
    top.lineTo(18, 7)
    top.lineTo(28, 7)
    top.lineTo(31, 12)
    p.setPen(_rpen(ink, 2.6))
    p.setBrush(Qt.NoBrush)
    p.drawPath(top)
    body = QPainterPath()
    body.addRoundedRect(QRectF(7, 12, 32, 21), 3.5, 3.5)
    p.setPen(_rpen(ink, 2.8))
    p.drawPath(body)
    acc = _accent()
    p.setPen(_rpen(ink, 2.6))
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 210))
    p.drawEllipse(QPointF(23, 22.5), 6.2, 6.2)
    p.setPen(Qt.NoPen)
    p.setBrush(acc)
    p.drawPolygon(QPolygonF([QPointF(18, 37), QPointF(28, 37),
                             QPointF(23, 44)]))


def _walk(p, ink):
    # Walk: two footprints stepping forward up the icon, the leading one in
    # the accent — the camera advances as you walk.
    def foot(cx, cy, angle, colour):
        p.save()
        p.translate(cx, cy)
        p.rotate(angle)
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
        p.drawEllipse(QRectF(-5.5, -10.0, 11.0, 15.0))     # sole
        p.drawEllipse(QRectF(-4.2, 7.0, 8.4, 7.0))         # heel
        p.restore()
    foot(15.5, 30.0, -14, QBrush(ink))
    foot(32.0, 17.0, -14, _accent())


def _look_around(p, ink):
    # Look Around: a head seen from above with its view cone, and a curved
    # arrow sweeping round it — the view turns, the eye stays put.
    acc = _accent()
    cx, cy = 24.0, 30.0
    cone = QPolygonF([QPointF(cx, cy), QPointF(cx - 12, 9), QPointF(cx + 12, 9)])
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 120))
    p.drawPolygon(cone)
    p.restore()
    p.setPen(_rpen(ink, 2.8))
    p.setBrush(Qt.NoBrush)
    p.drawPath(_disc(cx, cy, 6.0))                       # the head
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    p.drawPath(_disc(cx, cy - 6.5, 2.2))                 # the nose: facing up
    p.restore()
    arc = QRectF(cx - 14, cy - 14, 28, 28)
    p.save()
    p.setPen(_rpen(acc, 2.8))
    p.drawArc(arc, 200 * 16, 140 * 16)                    # the sweep below
    end = math.radians(340)
    tip = QPointF(cx + 14 * math.cos(end), cy - 14 * math.sin(end))
    p.setPen(Qt.NoPen)
    p.setBrush(acc)
    p.drawPolygon(QPolygonF([tip + QPointF(-1.5, -5.5), tip + QPointF(4.5, 1.5),
                             tip + QPointF(-4.5, 2.5)]))
    p.restore()


# ---- Solid Tools: two overlapping discs ------------------------------------
# Each boolean is the Venn picture of its result: two discs, the part the
# result KEEPS filled in the accent with an ink outline, what goes away as a
# faint dashed outline.
_DA = (18.0, 20.0, 12.5)          # first solid: centre x, y, radius
_DB = (30.0, 28.0, 12.5)          # second solid


def _solid_path(*discs):
    path = QPainterPath()
    for cx, cy, r in discs:
        path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _solid_keep(p, ink, path, alpha: int = 150):
    acc = _accent()
    p.save()
    pen = QPen(ink, 2.6)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), alpha))
    p.drawPath(path)
    p.restore()


def _dotted(ink, width: float) -> QPen:
    """A faint dashed outline: the part of a solid the result drops."""
    faint = QColor(ink)
    faint.setAlpha(140)
    pen = QPen(faint, width, Qt.DashLine)
    pen.setCapStyle(Qt.FlatCap)
    return pen


def _solid_gone(p, ink, path):
    p.save()
    p.setPen(_dotted(ink, 1.8))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.restore()


def _solid_outer_shell(p, ink):
    # Outer shell: only the outside skin survives — the union's outline,
    # drawn heavy, over a light fill.
    a, b = _solid_path(_DA), _solid_path(_DB)
    _solid_keep(p, ink, a.united(b), 70)
    p.save()
    p.setPen(QPen(ink, 3.6))
    p.setBrush(Qt.NoBrush)
    p.drawPath(a.united(b))
    p.restore()


def _solid_union(p, ink):
    # Union: one solid from both, the overlap included.
    a, b = _solid_path(_DA), _solid_path(_DB)
    _solid_keep(p, ink, a.united(b), 150)
    _solid_gone(p, ink, a.intersected(b))


def _solid_subtract(p, ink):
    # Subtract: the first solid carves itself out of the second and goes.
    a, b = _solid_path(_DA), _solid_path(_DB)
    _solid_gone(p, ink, a)
    _solid_keep(p, ink, b.subtracted(a))


def _solid_trim(p, ink):
    # Trim: like Subtract, but the first solid stays.
    a, b = _solid_path(_DA), _solid_path(_DB)
    _solid_keep(p, ink, a, 90)
    _solid_keep(p, ink, b.subtracted(a))


def _solid_intersect(p, ink):
    # Intersect: only the lens both share remains.
    a, b = _solid_path(_DA), _solid_path(_DB)
    _solid_gone(p, ink, a)
    _solid_gone(p, ink, b)
    _solid_keep(p, ink, a.intersected(b))


def _solid_split(p, ink):
    # Split: three separate solids — each side and the shared lens.
    a, b = _solid_path(_DA), _solid_path(_DB)
    _solid_keep(p, ink, a.subtracted(b), 60)
    _solid_keep(p, ink, b.subtracted(a), 60)
    _solid_keep(p, ink, a.intersected(b), 200)


_SOLID_ICONS = {
    "outer_shell": _solid_outer_shell, "solid_union": _solid_union,
    "solid_subtract": _solid_subtract, "solid_trim": _solid_trim,
    "solid_intersect": _solid_intersect, "solid_split": _solid_split,
}


def solid_cursor(state: str):
    """The Solid Tools pointer: an arrow with a grey «×» badge over anything
    that is not a solid, and a «1» or «2» on an accent disc over a solid,
    for the pick it will be."""
    from PySide6.QtGui import QCursor, QPainterPath, QPixmap
    key = ("solid", state)
    cached = _cursor_cache.get(key)
    if cached is not None:
        return cached
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    arrow = QPainterPath()
    arrow.moveTo(1, 1)
    arrow.lineTo(1, 17)
    arrow.lineTo(5, 13)
    arrow.lineTo(8, 20)
    arrow.lineTo(10.5, 19)
    arrow.lineTo(7.5, 12)
    arrow.lineTo(13, 12)
    arrow.closeSubpath()
    p.setPen(QPen(Qt.white, 1.2))
    p.setBrush(Qt.black)
    p.drawPath(arrow)
    c = QPointF(22, 22)
    if state == "no":
        p.setPen(QPen(Qt.white, 1.2))
        p.setBrush(QColor(90, 94, 102))
        p.drawRoundedRect(QRectF(15, 15, 14, 14), 3, 3)
        p.setPen(QPen(Qt.white, 2.2))
        p.drawLine(QPointF(18.5, 18.5), QPointF(25.5, 25.5))
        p.drawLine(QPointF(25.5, 18.5), QPointF(18.5, 25.5))
    else:
        p.setPen(QPen(Qt.white, 1.2))
        p.setBrush(_accent())
        p.drawEllipse(c, 7.5, 7.5)
        p.setPen(Qt.white)
        font = p.font()
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(14.5, 14.5, 15, 15), Qt.AlignCenter, state)
    p.end()
    cur = QCursor(pm, 1, 1)
    _cursor_cache[key] = cur
    return cur


def _first_person(p, ink):
    # First Person: the W/A/S/D keycaps as a game shows them, an inverted
    # T, with W — walk forward — in the accent. Big caps and no legends:
    # letters and anything smaller blur away at 24 px.
    size, gap = 13.5, 2.5
    x0 = 24.0 - size * 1.5 - gap
    top = 24.0 - size - gap / 2.0
    bottom = top + size + gap
    caps = [(x0 + size + gap, top, True),
            (x0, bottom, False), (x0 + size + gap, bottom, False),
            (x0 + 2 * (size + gap), bottom, False)]
    for x, y, lead in caps:
        cap = QPainterPath()
        cap.addRoundedRect(QRectF(x, y, size, size), 3.0, 3.0)
        p.setPen(_rpen(ink, 2.4))
        p.setBrush(_accent() if lead else Qt.NoBrush)
        p.drawPath(cap)


def _add_tag(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(24, 24), 15, 15)
    p.drawLine(16, 24, 32, 24)
    p.drawLine(24, 16, 24, 32)


def _add_tag_folder(p, ink):
    # Center the whole folder and its plus badge within the 48 px canvas.
    p.save()
    p.translate(-1.5, -3.5)
    path = QPainterPath()
    path.moveTo(7, 36)
    path.lineTo(7, 11)
    path.lineTo(19, 11)
    path.lineTo(24, 16)
    path.lineTo(39, 16)
    path.lineTo(39, 36)
    path.closeSubpath()
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setBrush(QApplication.palette().window())
    p.drawEllipse(QPointF(35, 35), 9, 9)
    p.drawLine(30, 35, 40, 35)
    p.drawLine(35, 30, 35, 40)
    p.restore()


def _tag_stack(p, ink, colored=False):
    p.setPen(_rpen(ink, 2.4))
    for offset, color in ((14, QColor(65, 146, 212)),
                          (7, QColor(245, 187, 52)),
                          (0, QColor(204, 72, 67))):
        x = offset * 0.3
        path = QPainterPath()
        path.moveTo(8 + x, 22 + offset)
        path.lineTo(24 + x, 6 + offset)
        path.lineTo(34 + x, 6 + offset)
        path.lineTo(34 + x, 16 + offset)
        path.lineTo(18 + x, 32 + offset)
        path.closeSubpath()
        p.setBrush(color if colored else QApplication.palette().window())
        p.drawPath(path)
    p.setBrush(ink)
    p.drawEllipse(QPointF(29, 11), 1.3, 1.3)


def _more_options(p, ink):
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    for y in (12, 24, 36):
        p.drawEllipse(QPointF(24, y), 3, 3)


def _assign_tag(p, ink):
    path = QPainterPath()
    path.moveTo(9, 28)
    path.lineTo(28, 9)
    path.lineTo(40, 21)
    path.lineTo(21, 40)
    path.lineTo(9, 40)
    path.closeSubpath()
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.drawEllipse(QPointF(15, 34), 2.5, 2.5)
    p.drawLine(15, 34, 5, 44)


_DRAW = {
    "add_tag": _add_tag,
    "add_tag_folder": _add_tag_folder,
    "color_by_tag": _tag_stack,
    "color_by_tag_on": lambda p, ink: _tag_stack(p, ink, colored=True),
    "assign_tag": _assign_tag,
    "more_options": _more_options,
    **_SOLID_ICONS,
    "select": _select, "line": _line, "freehand": _freehand,
    "side_collapse": _side_collapse,
    "overflow_h": _overflow_h, "overflow_v": _overflow_v,
    "side_expand": _side_expand,
    "arr_left": _arr_left, "arr_right": _arr_right, "arr_top": _arr_top,
    "arr_bottom": _arr_bottom, "arr_hcenter": _arr_hcenter,
    "arr_vcenter": _arr_vcenter, "arr_dist_h": _arr_dist_h,
    "arr_dist_v": _arr_dist_v, "arr_duplicate": _arr_duplicate,
    "arr_group": _arr_group, "arr_ungroup": _arr_ungroup, "arr_lock": _arr_lock,
    "rectangle": _rectangle, "rectangle_center": _rectangle_center,
    "image": _image_icon,
    "comp_vista": _comp_vista, "comp_norte": _comp_norte,
    "comp_leyenda": _comp_leyenda, "comp_escala": _comp_escala,
    "comp_cajetin": _comp_cajetin, "comp_flecha": _comp_flecha,
    "comp_terreno": _comp_terreno,
    "save": _save, "refresh": _refresh, "export_pdf": _export_pdf,
    "print_preview": _print_preview,
    "comp_etiqueta": _comp_etiqueta, "comp_perfil": _comp_perfil,
    "comp_nivel": _comp_nivel, "comp_llamada": _comp_llamada,
    "rotated_rect": _rotated_rect, "circle": _circle, "polygon": _polygon,
    "arc": _arc, "arc3": _arc3, "center_arc": _center_arc, "pie": _pie,
    "rotate": _rotate, "scale": _scale, "flip": _flip, "followme": _followme, "pushpull": _pushpull, "offset": _offset, "fillet": _fillet,
    "move": _move, "paint": _paint, "eyedropper": _eyedropper,
    "dimension": _dimension, "dimension_chain": _dimension_chain,
    "dimension_radius": _dimension_radius,
    "dimension_baseline": _dimension_baseline,
    "dimension_diameter": _dimension_diameter,
    "dimension_angular": _dimension_angular,
    "dimension_style": _dimension_style,
    "geopath": _geopath, "orbit": _orbit, "pan": _pan,
    "undo": _undo, "redo": _redo,
    "text": _text, "text3d": _text3d,
    "eraser": _eraser, "tape": _tape, "protractor": _protractor,
    "section": _section,
    "styles": _styles_icon, "shadows": _shadows_icon,
    "section_planes": _section_planes, "section_cuts": _section_cuts,
    "section_fill": _section_fill,
    "zoom": _zoom, "zoom_window": _zoom_window,
    "position_camera": _position_camera, "walk": _walk,
    "look_around": _look_around, "first_person": _first_person,
    "zoom_extents": _zoom_extents, "zoom_selection": _zoom_selection,
    "view_iso": _view_iso,
    # Standard views — the cube with the viewed face highlighted.
    "view_top": _view_top,
    "view_bottom": _view_bottom,
    "view_front": _view_front,
    "view_back": _view_back,
    "view_right": _house_side(mirror=False),
    "view_left": _house_side(mirror=True),
}


def tool_icon(key: str) -> QIcon:
    """Programmatic :class:`QIcon` for a tool/nav ``key`` (null if unknown)."""
    draw = _DRAW.get(key)
    if draw is None:
        return QIcon()
    pm, p, ink = _canvas()
    draw(p, ink)
    p.end()
    return QIcon(pm)


# ---- Tool cursors --------------------------------------------------------------
# The mouse pointer BECOMES the active tool — no crosshair. Each cursor's
# hotspot is the tool's natural action point: the pencil TIP
# for the drawing tools (whose cursor is a pencil with the shape as a small
# badge), the eraser's working corner, the paint bucket's spout, the centre
# of the move cross / protractor. Haloed so it reads over any background.
# "select" keeps the standard arrow.

_CURSOR_SIZE = 32   # logical cursor canvas (48-space icons scale onto it)
_cursor_cache: dict = {}

# Drawing tools: pencil cursor + a mini badge of the shape at bottom-right
# (None = bare pencil, for Line). Hotspot = the pencil tip.
_PENCIL_TOOLS = {
    "line": None, "freehand": "freehand",
    "rectangle": "rectangle", "rectangle_center": "rectangle_center",
    "rotated_rect": "rotated_rect",
    "circle": "circle", "polygon": "polygon", "arc": "arc", "arc3": "arc3",
    "center_arc": "center_arc", "pie": "pie", "geopath": "geopath",
}
_PENCIL_HOT = (6.0, 42.0)          # the tip, in 48-space

# Other tools: the icon itself is the cursor; hotspot = its action point,
# in the icon's 48-space (see each draw function's geometry).
_CURSOR_HOTSPOTS = {
    "move": (24, 24), "rotate": (24, 24), "scale": (24, 24),
    "flip": (24, 24),
    "pushpull": (24, 24), "offset": (24, 24), "followme": (24, 24),
    "fillet": (24, 24),
    "dimension": (12, 30),          # left end of the dimension line
    "text": (24, 24), "text3d": (24, 24),
    "paint": (13, 35),              # the spout / falling drop
    "eyedropper": (9.5, 38.5),      # the pipette's tip (drawn at 85 %)
    "eraser": (15, 31),             # the middle of the rubber's accent end
    "tape": (10, 28),               # the tape's end hook (now at the left)
    "protractor": (24, 24),         # the protractor's vertex
    "orbit": (24, 24),              # camera navigation (wheel-drag / modes)
    "pan": (24, 24),
    "zoom": (21, 21),               # the magnifier's lens centre
    "zoom_window": (21, 22),
    "section": (24, 27),            # the plane's centre
    "position_camera": (23, 44),    # the marker's tip: where the camera goes
    "walk": (24, 24),
    "look_around": (24, 26),        # the pupil
    "first_person": (24, 24),
}


def _pencil(p, ink) -> None:
    """A pencil pointing up-right, tip at (6, 42) in 48-space."""
    p.save()
    p.translate(6.0, 42.0)
    p.rotate(-45.0)                 # +x runs up-right along the shaft
    pen = QPen(ink, 3.0)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # Sharpened tip.
    p.drawPolygon(QPolygonF([QPointF(0.0, 0.0), QPointF(10.0, -5.5),
                             QPointF(10.0, 5.5)]))
    # Shaft with a flat butt.
    p.drawLine(QPointF(10.0, -5.5), QPointF(40.0, -5.5))
    p.drawLine(QPointF(10.0, 5.5), QPointF(40.0, 5.5))
    p.drawLine(QPointF(40.0, -5.5), QPointF(40.0, 5.5))
    # Accent lead at the very tip.
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_accent()))
    p.drawPolygon(QPolygonF([QPointF(-0.6, 0.0), QPointF(4.2, -2.4),
                             QPointF(4.2, 2.4)]))
    p.restore()


def _silhouette(src: QPixmap, color: QColor) -> QPixmap:
    """The pixmap's alpha shape filled with ``color`` (for the halo)."""
    s = QPixmap(src.size())
    s.setDevicePixelRatio(src.devicePixelRatio())
    s.fill(Qt.transparent)
    p = QPainter(s)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(s.rect(), color)
    p.end()
    return s


def tool_cursor(key: str | None, plus: bool = False) -> QCursor | None:
    """A cursor that IS the tool, or ``None`` to keep the standard arrow
    (unknown keys, and Select).

    ``plus`` adds a little ``+``: on the Tape and the Protractor it
    is the ENTIRE interface of the Ctrl toggle — a plus beside the cursor
    means this measurement will leave a guide, no plus means it only
    measures. Without it the mode is invisible and you find out after the
    click (issue #29, @pacaeiro)."""
    if not key or key == "select":
        return None
    pencil = key in _PENCIL_TOOLS
    hot48 = _PENCIL_HOT if pencil else _CURSOR_HOTSPOTS.get(key)
    draw = _DRAW.get(key)
    if hot48 is None or (draw is None and not pencil):
        return None
    ink = _ink()
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    cache_key = (key, bool(plus), ink.rgb(), round(dpr, 2))
    cached = _cursor_cache.get(cache_key)
    if cached is not None:
        return cached

    scale = _CURSOR_SIZE / float(_PX)
    art = QPixmap(int(_CURSOR_SIZE * dpr), int(_CURSOR_SIZE * dpr))
    art.setDevicePixelRatio(dpr)
    art.fill(Qt.transparent)
    p = QPainter(art)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(scale, scale)
    ipen = QPen(ink, 3.0)
    ipen.setJoinStyle(Qt.RoundJoin)
    ipen.setCapStyle(Qt.RoundCap)
    p.setPen(ipen)
    if pencil:
        _pencil(p, ink)
        badge = _DRAW.get(_PENCIL_TOOLS[key] or "")
        if badge is not None:
            # Mini badge of the shape at the bottom-right.
            p.save()
            p.translate(28.0, 28.0)
            p.scale(20.0 / _PX, 20.0 / _PX)
            bpen = QPen(ink, 4.4)     # thicker: stays readable that small
            bpen.setJoinStyle(Qt.RoundJoin)
            bpen.setCapStyle(Qt.RoundCap)
            p.setPen(bpen)
            badge(p, ink)
            p.restore()
    else:
        draw(p, ink)
    if plus:
        # The guide-mode plus, top-right so it never sits under the
        # hotspot. Drawn before the halo so it gets one too.
        ppen = QPen(ink, 4.0)
        ppen.setCapStyle(Qt.RoundCap)
        p.setPen(ppen)
        p.drawLine(34, 6, 44, 6)
        p.drawLine(39, 1, 39, 11)
    p.end()

    # Halo: a 1 px light (or dark, on dark themes) outline all around, so the
    # cursor stays legible over faces, sky and ground alike.
    halo_col = (QColor(255, 255, 255, 225) if ink.lightness() < 128
                else QColor(28, 32, 38, 225))
    halo = _silhouette(art, halo_col)
    out = QPixmap(art.size())
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                p.drawPixmap(QPointF(float(dx), float(dy)), halo)
    p.drawPixmap(QPointF(0.0, 0.0), art)
    p.end()

    hx = max(0, min(_CURSOR_SIZE - 1, round(hot48[0] * scale)))
    hy = max(0, min(_CURSOR_SIZE - 1, round(hot48[1] * scale)))
    cursor = QCursor(out, hx, hy)
    _cursor_cache[cache_key] = cursor
    return cursor


# ---- Toolbar icon size ----------------------------------------------------
#: Sizes offered in Preferences ▸ General (pixels). The first version had
#: only a «large» toggle (32) on the toolbar's right-click menu — moved
#: here so it lives with the other settings and reaches the composer's
#: toolbars too. 32 is the factory default: what Marco settled on after
#: the icon pass of 2026-09-14 («configúralo por defecto para cualquier
#: persona que instale el programa»).
TOOLBAR_ICON_SIZES = ((20, "Small"), (24, "Normal"), (32, "Large"),
                      (40, "Extra large"))
DEFAULT_TOOLBAR_ICON_PX = 24


def default_toolbar_icon_px() -> int:
    """The size a profile that never chose gets: normal (24 px). Large was
    the default for one release (Marco liked it on his 27" monitor) and
    looked clumsy on his laptop — «se ven mejor los tamaños normales»
    (2026-09-14); Preferences keeps 20/24/32/40 for whoever wants more."""
    return DEFAULT_TOOLBAR_ICON_PX


def toolbar_icon_px() -> int:
    """The toolbar icon size in pixels from the settings, migrating the
    old «large icons» toggle on first read; a profile that never chose
    gets the size that fits its screen."""
    from PySide6.QtCore import QSettings
    st = QSettings()
    raw = st.value("ui/toolbar_icon_px")
    if raw is None or str(raw) == "":
        px = (32 if str(st.value("ui/large_toolbar_icons", "0")) == "1"
              else default_toolbar_icon_px())
    else:
        try:
            px = int(raw)
        except (TypeError, ValueError):
            px = DEFAULT_TOOLBAR_ICON_PX
    return (px if px in {s for s, _ in TOOLBAR_ICON_SIZES}
            else DEFAULT_TOOLBAR_ICON_PX)


def save_toolbar_icon_px(px: int) -> None:
    from PySide6.QtCore import QSettings
    st = QSettings()
    st.setValue("ui/toolbar_icon_px", int(px))
    st.remove("ui/large_toolbar_icons")


def style_overflow_button(tb) -> None:
    """The «more tools» button a toolbar grows when its icons do not fit
    (Qt's extension button) drawn in the program's style — a double
    chevron in the accent with a tooltip — instead of the style's faint
    stub, which on a small screen read as a grey blank (Marco, 2026-09-14).
    Qt resets the button's icon on every orientation change, so it is
    reapplied then."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QToolButton
    from core.i18n import tr
    btn = tb.findChild(QToolButton, "qt_toolbar_ext_button")
    if btn is None:
        return

    def apply(*_a):
        vertical = tb.orientation() == Qt.Vertical
        btn.setIcon(tool_icon("overflow_v" if vertical else "overflow_h"))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(tr("More tools of this bar"))
        btn.setCursor(Qt.PointingHandCursor)
    apply()
    tb.orientationChanged.connect(apply)
    tb.iconSizeChanged.connect(apply)
