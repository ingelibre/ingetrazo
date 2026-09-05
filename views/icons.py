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
    # A hand-drawn squiggle — SketchUp's Freehand (the Line flyout).
    path = QPainterPath()
    path.moveTo(10, 34)
    path.cubicTo(16, 18, 22, 40, 28, 24)
    path.cubicTo(32, 14, 36, 18, 38, 14)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    _dot(p, 10, 34)


def _rectangle(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(12, 14, 24, 20))


def _rotated_rect(p, ink):
    poly = QPolygonF([QPointF(12, 26), QPointF(26, 12),
                      QPointF(36, 22), QPointF(22, 36)])
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(poly)


def _circle(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(24, 24), 13, 13)


def _polygon(p, ink):
    pts = []
    for i in range(6):
        a = math.radians(60 * i - 30)
        pts.append(QPointF(24 + 13 * math.cos(a), 24 + 13 * math.sin(a)))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF(pts))


def _arc(p, ink):
    path = QPainterPath()
    path.moveTo(12, 34)
    path.quadTo(24, 6, 36, 34)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    _dot(p, 12, 34)
    _dot(p, 36, 34)


def _arc3(p, ink):
    _arc(p, ink)
    _dot(p, 24, 15)


def _pie(p, ink):
    # SketchUp's Pie: a closed wedge — arc plus its two radius edges.
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 10, 28, 28), 15 * 16, 115 * 16)
    import math as _m
    for adeg in (15, 130):
        a = _m.radians(adeg)
        p.drawLine(QPointF(24, 24),
                   QPointF(24 + 14 * _m.cos(a), 24 - 14 * _m.sin(a)))
    _dot(p, 24, 24)


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
    # Compass arc: centre dot, radius arm, swept arc.
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 10, 28, 28), 0, 105 * 16)
    p.drawLine(QPointF(24, 24), QPointF(38, 24))
    _dot(p, 24, 24)
    _dot(p, 38, 24, 2.6)
    _dot(p, 17, 12, 2.6)



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



def _section(p, ink):
    # A section plane: a foreshortened frame with corner brackets and the
    # normal arrow showing the side that gets cut away (SketchUp Sections).
    quad = [QPointF(10, 30), QPointF(26, 38), QPointF(38, 24), QPointF(22, 16)]
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF(quad))
    # Corner brackets.
    for i in range(4):
        c = quad[i]
        for j in (1, 3):
            n = quad[(i + j) % 4]
            dx, dy = n.x() - c.x(), n.y() - c.y()
            ln = math.hypot(dx, dy) or 1.0
            k = 4.5 / ln
            p.drawLine(c, QPointF(c.x() + dx * k, c.y() + dy * k))
    # The normal arrow (cut direction).
    a0, a1 = QPointF(24, 27), QPointF(29, 9)
    p.setPen(QPen(_accent(), 3.0, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(a0, a1)
    p.drawLine(a1, QPointF(24.5, 12.5))
    p.drawLine(a1, QPointF(31.5, 14.5))
    p.setPen(QPen(ink, 3.0))


def _section_planes(p, ink):
    # Display Section Planes: the bare plane frame with corner brackets.
    quad = [QPointF(10, 30), QPointF(26, 38), QPointF(38, 24), QPointF(22, 16)]
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF(quad))
    for i in range(4):
        c = quad[i]
        for j in (1, 3):
            n = quad[(i + j) % 4]
            dx, dy = n.x() - c.x(), n.y() - c.y()
            ln = math.hypot(dx, dy) or 1.0
            k = 5.5 / ln
            p.drawLine(c, QPointF(c.x() + dx * k, c.y() + dy * k))


def _section_cuts(p, ink):
    # Display Section Cuts: a solid sliced open — outline + thick cut chord.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(12, 18, 24, 18))
    p.drawLine(QPointF(12, 18), QPointF(20, 10))
    p.drawLine(QPointF(36, 18), QPointF(40, 12))
    cut = QPen(_accent(), 4.0)
    cut.setCapStyle(Qt.RoundCap)
    p.setPen(cut)
    p.drawLine(QPointF(10, 26), QPointF(38, 26))
    p.setPen(QPen(ink, 3.0))


def _section_fill(p, ink):
    # Display Section Fill: the cut face painted solid.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(12, 12, 24, 24))
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_accent()))
    p.drawRect(QRectF(13.5, 25, 21, 9.5))
    p.restore()
    p.drawLine(QPointF(12, 24), QPointF(36, 24))


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
    # A face with an up arrow (extrude).
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(12, 26, 18, 12))
    p.drawLine(QPointF(21, 26), QPointF(21, 10))
    p.drawLine(QPointF(21, 10), QPointF(16, 16))
    p.drawLine(QPointF(21, 10), QPointF(26, 16))


def _offset(p, ink):
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(10, 12, 28, 24))
    p.drawRect(QRectF(16, 18, 16, 12))


def _move(p, ink):
    p.drawLine(QPointF(24, 10), QPointF(24, 38))
    p.drawLine(QPointF(10, 24), QPointF(38, 24))
    for (x, y, dx1, dy1, dx2, dy2) in (
        (24, 10, -4, 5, 4, 5), (24, 38, -4, -5, 4, -5),
        (10, 24, 5, -4, 5, 4), (38, 24, -5, -4, -5, 4)):
        p.drawLine(QPointF(x, y), QPointF(x + dx1, y + dy1))
        p.drawLine(QPointF(x, y), QPointF(x + dx2, y + dy2))


def _eyedropper(p, ink):
    """The Paint tool while Alt is held: SketchUp swaps the bucket for an
    eyedropper, which is how you know the next click SAMPLES instead of
    paints. A slanted pipette — bulb top-right, barrel down-left, tip at the
    hotspot — with the accent showing through the glass."""
    barrel = QPen(ink, 3.4)
    barrel.setCapStyle(Qt.RoundCap)
    barrel.setJoinStyle(Qt.RoundJoin)
    # Barrel: from the tip (lower-left) up to the collar.
    tip, collar = QPointF(7.0, 41.0), QPointF(27.0, 21.0)
    p.setPen(Qt.NoPen)
    p.setBrush(_accent())
    p.drawPolygon(QPolygonF([QPointF(9.0, 39.0), QPointF(26.0, 22.0),
                             QPointF(29.0, 25.0), QPointF(12.0, 42.0)]))
    p.setPen(barrel)
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF([tip, QPointF(24.5, 18.5), QPointF(30.5, 24.5),
                             QPointF(11.0, 44.0)]))
    # Collar and bulb.
    p.setPen(QPen(ink, 3.4, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(23.0, 22.0), QPointF(30.0, 15.0))
    p.setBrush(QBrush(ink))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(35.0, 12.0), 8.5, 8.5)
    # A drop leaving the tip, so it reads as "picks up material".
    p.setBrush(_accent())
    p.drawEllipse(QPointF(5.0, 44.0), 2.6, 2.6)


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


def _dimension(p, ink):
    p.drawLine(QPointF(12, 30), QPointF(36, 30))
    p.drawLine(QPointF(12, 24), QPointF(12, 36))
    p.drawLine(QPointF(36, 24), QPointF(36, 36))


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
    # An open hand — Pan (grab-and-slide the view). Built from a rounded palm
    # plus rounded-cap finger strokes so the fingertips are soft, not blocky;
    # everything is the same ink, so the pieces merge into one clean hand.
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    p.drawRoundedRect(QRectF(15, 23, 18, 16), 5.5, 5.5)      # palm
    fingers = QPen(ink, 3.8)
    fingers.setCapStyle(Qt.RoundCap)
    p.setPen(fingers)
    # Four fingers rising from the palm (middle tallest, little shortest).
    p.drawLine(QPointF(18.2, 25), QPointF(18.2, 15.5))
    p.drawLine(QPointF(22.4, 25), QPointF(22.4, 12.5))
    p.drawLine(QPointF(26.6, 25), QPointF(26.6, 13.5))
    p.drawLine(QPointF(30.6, 25), QPointF(30.6, 16.5))
    # Thumb, angled out from the lower-left of the palm.
    thumb = QPen(ink, 4.2)
    thumb.setCapStyle(Qt.RoundCap)
    p.setPen(thumb)
    p.drawLine(QPointF(16.5, 30), QPointF(10.5, 24))


def _eraser(p, ink):
    # A tilted rubber eraser with a coloured working end — SketchUp's Eraser.
    p.save()
    p.translate(24, 22)
    p.rotate(-30)
    # Coloured (pink) working tip.
    p.setPen(Qt.NoPen)
    p.setBrush(_accent())
    p.drawRoundedRect(QRectF(-13, -6, 9.5, 12), 2.5, 2.5)
    # Body outline over it.
    p.setBrush(Qt.NoBrush)
    body_pen = QPen(ink, 3.0)
    body_pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(body_pen)
    p.drawRoundedRect(QRectF(-13, -6, 26, 12), 2.5, 2.5)
    p.drawLine(QPointF(-3.5, -6), QPointF(-3.5, 6))   # seam
    p.restore()
    # Motion lines trailing the swipe.
    trail = QPen(ink, 2.0)
    trail.setCapStyle(Qt.RoundCap)
    p.setPen(trail)
    p.drawLine(QPointF(12, 37), QPointF(18, 37))
    p.drawLine(QPointF(14, 41), QPointF(21, 41))


def _tape(p, ink):
    # A tape-measure body with the tape pulled out and a hook.
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(18, 20), 8.5, 8.5)
    p.drawEllipse(QPointF(18, 20), 2.6, 2.6)
    p.drawLine(QPointF(18, 28.5), QPointF(38, 28.5))   # the tape
    p.drawLine(QPointF(38, 25.5), QPointF(38, 31.5))   # end hook
    for x in (24, 29, 34):                              # tick marks
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
    # Corner brackets framing the extent (fit-to-view).
    for (cx, cy, sx, sy) in ((13, 13, 1, 1), (35, 13, -1, 1),
                             (35, 35, -1, -1), (13, 35, 1, -1)):
        p.drawLine(QPointF(cx, cy), QPointF(cx + 7 * sx, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + 7 * sy))


# ---- Standard-view icons: a little house drawn from each viewpoint ----------
# Like SketchUp, each orthographic view shows a recognisable house from that
# direction (front with a door, sides with a window, the roof from above, an
# isometric 3D house) — far more intuitive than an abstract highlighted cube.

def _view_front(p, ink):
    # Gable end seen head-on, with a door. (Front / South)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(14, 23, 20, 14))                     # wall
    p.drawPolygon(QPolygonF([QPointF(11, 23), QPointF(24, 11),
                             QPointF(37, 23)]))            # gable roof
    p.setBrush(QBrush(ink))
    p.drawRect(QRectF(21, 30, 6, 7))                       # door


def _view_back(p, ink):
    # Same gable end, but blank with a window instead of a door. (Back / North)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(14, 23, 20, 14))
    p.drawPolygon(QPolygonF([QPointF(11, 23), QPointF(24, 11),
                             QPointF(37, 23)]))
    p.drawRect(QRectF(20.5, 27, 7, 6))                     # window


def _house_side(mirror: bool):
    # Long wall seen side-on: a wide box, a low trapezoidal roof, a window and a
    # door toward one end. Right and Left are mirror images. (East / West)
    def draw(p, ink):
        p.save()
        if mirror:
            p.translate(48, 0)
            p.scale(-1, 1)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(11, 23, 26, 14))                 # long wall
        p.drawPolygon(QPolygonF([QPointF(9, 23), QPointF(15, 16),
                                 QPointF(33, 16), QPointF(39, 23)]))  # roof
        p.drawRect(QRectF(15, 27, 6, 6))                   # window
        p.setBrush(QBrush(ink))
        p.drawRect(QRectF(28, 30, 5, 7))                   # door (one end)
        p.restore()
    return draw


def _view_top(p, ink):
    # The roof seen from directly above: footprint + hip lines to the ridge.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(13, 14, 22, 20))
    p.drawLine(QPointF(13, 14), QPointF(20, 21))
    p.drawLine(QPointF(35, 14), QPointF(28, 21))
    p.drawLine(QPointF(13, 34), QPointF(20, 27))
    p.drawLine(QPointF(35, 34), QPointF(28, 27))
    p.drawLine(QPointF(20, 21), QPointF(20, 27))           # ridge
    p.drawLine(QPointF(28, 21), QPointF(28, 27))
    p.drawLine(QPointF(20, 24), QPointF(28, 24))


def _view_bottom(p, ink):
    # The footprint seen from below: a plain slab (no roof lines) with a small
    # tab, so it reads apart from Top's roof-from-above at a glance.
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(13, 16, 22, 20))
    p.drawRect(QRectF(20, 12, 8, 4))            # small tab on top
    p.drawLine(QPointF(13, 22), QPointF(35, 22))   # slab edge line


def _view_iso(p, ink):
    # A 3D house in isometric: two walls + a pyramid roof + a door.
    p.setBrush(Qt.NoBrush)
    wl, wf, wr = QPointF(13, 22), QPointF(24, 28), QPointF(35, 22)
    bl, bf, br = QPointF(13, 33), QPointF(24, 39), QPointF(35, 33)
    apex = QPointF(24, 13)
    p.drawPolygon(QPolygonF([wl, wf, bf, bl]))             # left wall
    p.drawPolygon(QPolygonF([wf, wr, br, bf]))             # right wall
    p.drawLine(wl, apex)                                   # roof edges
    p.drawLine(wf, apex)
    p.drawLine(wr, apex)
    p.setBrush(QBrush(ink))
    p.drawPolygon(QPolygonF([QPointF(18, 31), QPointF(21, 32.6),
                             QPointF(21, 38.6), QPointF(18, 37)]))   # door


def _text(p, ink):
    # An "A" with a leader line pointing down-left (SketchUp's Text).
    f = p.font()
    f.setPixelSize(24)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QPointF(20, 26), "A")
    p.drawLine(QPointF(10, 38), QPointF(19, 29))
    p.drawEllipse(QPointF(10, 38), 2.0, 2.0)


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


_DRAW = {
    "select": _select, "line": _line, "freehand": _freehand,
    "rectangle": _rectangle,
    "image": _image_icon,
    "comp_vista": _comp_vista, "comp_norte": _comp_norte,
    "comp_leyenda": _comp_leyenda, "comp_escala": _comp_escala,
    "comp_cajetin": _comp_cajetin, "comp_flecha": _comp_flecha,
    "comp_etiqueta": _comp_etiqueta, "comp_perfil": _comp_perfil,
    "comp_nivel": _comp_nivel,
    "rotated_rect": _rotated_rect, "circle": _circle, "polygon": _polygon,
    "arc": _arc, "arc3": _arc3, "center_arc": _center_arc, "pie": _pie,
    "rotate": _rotate, "scale": _scale, "flip": _flip, "followme": _followme, "pushpull": _pushpull, "offset": _offset,
    "move": _move, "paint": _paint, "eyedropper": _eyedropper,
    "dimension": _dimension,
    "geopath": _geopath, "orbit": _orbit, "pan": _pan,
    "text": _text, "text3d": _text3d,
    "eraser": _eraser, "tape": _tape, "protractor": _protractor,
    "section": _section,
    "styles": _styles_icon, "shadows": _shadows_icon,
    "section_planes": _section_planes, "section_cuts": _section_cuts,
    "section_fill": _section_fill,
    "zoom": _zoom, "zoom_window": _zoom_window,
    "zoom_extents": _zoom_extents, "view_iso": _view_iso,
    # Standard views — a house drawn from each viewpoint (SketchUp-style).
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


# ---- Tool cursors (SketchUp-style) ------------------------------------------
# The mouse pointer BECOMES the active tool — no crosshair. Like SketchUp,
# each cursor's hotspot is the tool's natural action point: the pencil TIP
# for the drawing tools (whose cursor is a pencil with the shape as a small
# badge), the eraser's working corner, the paint bucket's spout, the centre
# of the move cross / protractor. Haloed so it reads over any background.
# "select" keeps the standard arrow (SketchUp's Select is the plain pointer).

_CURSOR_SIZE = 32   # logical cursor canvas (48-space icons scale onto it)
_cursor_cache: dict = {}

# Drawing tools: pencil cursor + a mini badge of the shape at bottom-right
# (None = bare pencil, SketchUp's Line). Hotspot = the pencil tip.
_PENCIL_TOOLS = {
    "line": None, "freehand": "freehand",
    "rectangle": "rectangle", "rotated_rect": "rotated_rect",
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
    "dimension": (12, 30),          # left end of the dimension line
    "text": (24, 24), "text3d": (24, 24),
    "paint": (13, 35),              # the spout / falling drop
    "eyedropper": (7, 41),          # the pipette's tip
    "eraser": (13, 28),             # the rubber's working corner
    "tape": (38, 28),               # the tape's end hook
    "protractor": (24, 24),         # the protractor's vertex
    "orbit": (24, 24),              # camera navigation (wheel-drag / modes)
    "pan": (24, 24),
    "zoom": (21, 21),               # the magnifier's lens centre
    "zoom_window": (21, 22),
    "section": (24, 27),            # the plane's centre
}


def _pencil(p, ink) -> None:
    """SketchUp-style pencil pointing up-right, tip at (6, 42) in 48-space."""
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


def tool_cursor(key: str | None) -> QCursor | None:
    """A cursor that IS the tool (SketchUp-style), or ``None`` to keep the
    standard arrow (unknown keys, and Select — SketchUp's plain pointer)."""
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
    cache_key = (key, ink.rgb(), round(dpr, 2))
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
            # Mini badge of the shape at the bottom-right (SketchUp).
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
