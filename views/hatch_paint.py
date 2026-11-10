# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ink a hatch pattern (core.hatches) inside a path, in paper millimetres —
the section cut on a sheet — and draw its swatch for the pickers."""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF)

from core.hatches import hatch_marks


def paint_hatch(painter: QPainter, path: QPainterPath, key: str,
                ink: QColor, width_mm: float, scale: float = 1.0,
                ground: QColor | None = None, angle: float = 0.0,
                families=None, offset=None) -> None:
    """Pattern ``key`` inside ``path`` (clipped to it), ``scale`` times its
    size and turned ``angle`` degrees, its marks ``width_mm`` thick in
    ``ink`` — over ``ground`` first, when given. ``families``: an imported
    pattern's; ``offset``: the pattern moved, paper mm. ``solid`` fills the
    path with ``ink``."""
    if path.isEmpty():
        return
    painter.save()
    if key == "solid":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ink))
        painter.drawPath(path)
        painter.restore()
        return
    if ground is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ground))
        painter.drawPath(path)
    painter.setClipPath(path, Qt.IntersectClip)
    br = path.boundingRect()
    marks = hatch_marks(key, (br.left(), br.top(), br.right(), br.bottom()),
                        scale, angle, families, offset)
    w = max(0.03, float(width_mm))
    pen = QPen(ink)
    pen.setWidthF(w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if marks["lines"]:
        painter.drawLines([QLineF(*seg) for seg in marks["lines"]])
    for pts in marks["polys"]:
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
    for pts in marks["closed"]:
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    for x, y, r in marks["circles"]:
        painter.drawEllipse(QPointF(x, y), r, r)
    if marks["dots"]:
        dot = QPen(ink)
        dot.setWidthF(w * 1.8)
        dot.setCapStyle(Qt.RoundCap)
        painter.setPen(dot)
        painter.drawPoints([QPointF(x, y) for x, y in marks["dots"]])
    painter.restore()


def paint_fitted(painter: QPainter, path: QPainterPath, rings, key: str,
                 ink: QColor, width_mm: float, density: float = 1.0,
                 ground: QColor | None = None) -> None:
    """A pattern fitted to each cut piece (core.hatches.FITTED): the soft
    insulation symbol spanning every ring's thickness along the way it runs,
    clipped to ``path`` (all the rings, even-odd)."""
    from core.hatches import fit_band, fitted_marks
    if path.isEmpty():
        return
    painter.save()
    if ground is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ground))
        painter.drawPath(path)
    painter.setClipPath(path, Qt.IntersectClip)
    pen = QPen(ink)
    pen.setWidthF(max(0.03, float(width_mm)))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    for ring in rings:
        band = fit_band(ring)
        if band is None:
            continue
        # In a thin piece the line thins too, or the balloons run together
        # into a dark zigzag: at most a twentieth of the thickness.
        pen.setWidthF(max(0.03, min(float(width_mm), band[4] / 20.0)))
        painter.setPen(pen)
        for pts in fitted_marks(key, *band, density=density):
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
    painter.restore()


#: The colour of each piece in its drawing: fired clay, concrete.
_PIECE_COLOURS = {"brick": QColor(214, 132, 98), "hollow": QColor(222, 150, 112),
                  "perforated": QColor(205, 124, 92),
                  "cored": QColor(170, 172, 176),
                  "block": QColor(184, 186, 190),
                  "aac": QColor(232, 232, 226)}


def piece_axo(kind: str, dims, w: int, h: int, ink: QColor | None = None,
              dpr: float = 1.0) -> QPixmap:
    """A ``w`` × ``h`` px drawing of one masonry piece in isometric — a
    brick, a ticholo with the holes that run along it on its end, a block
    with its two cores on top — its length, width and height written along
    its edges in mm: the size the fields beside it set, seen at a glance.
    ``dims``: core.hatches.brick_dims."""
    import math
    from PySide6.QtGui import QFont
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    if not kind or dims is None:
        return pm
    length, width, height = float(dims[0]), float(dims[1]), float(dims[2])
    c, sn = math.cos(math.radians(30)), math.sin(math.radians(30))

    def iso(x, y, z):
        return ((x - y) * c, (x + y) * sn - z)
    corners = [iso(x, y, z) for x in (0, length) for y in (0, width)
               for z in (0, height)]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    margin = 18.0                       # room for the measures
    k = min((w - 2 * margin) / (max(xs) - min(xs)),
            (h - 2 * margin) / (max(ys) - min(ys)))
    ox = (w - (max(xs) - min(xs)) * k) / 2.0 - min(xs) * k
    oy = (h - (max(ys) - min(ys)) * k) / 2.0 - min(ys) * k

    def at(x, y, z):
        u, v = iso(x, y, z)
        return QPointF(ox + u * k, oy + v * k)

    def quad(*pts):
        return QPolygonF([at(*q) for q in pts])
    base = _PIECE_COLOURS.get(kind, _PIECE_COLOURS["brick"])
    ink = ink or QColor(40, 44, 52)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    edge = QPen(ink, 1.0)
    edge.setJoinStyle(Qt.RoundJoin)
    p.setPen(edge)
    # Three faces in three tones: top light, the long face, the end darker.
    top = quad((0, 0, height), (length, 0, height), (length, width, height),
               (0, width, height))
    # Seen from the corner (length, width): its long face is the one at
    # y = width, its end the one at x = length.
    front = quad((0, width, 0), (length, width, 0), (length, width, height),
                 (0, width, height))
    end = quad((length, 0, 0), (length, width, 0), (length, width, height),
               (length, 0, height))
    p.setBrush(base.lighter(125))
    p.drawPolygon(top)
    p.setBrush(base)
    p.drawPolygon(front)
    p.setBrush(base.darker(118))
    p.drawPolygon(end)
    thin = QPen(ink, 0.8)
    p.setPen(thin)
    p.setBrush(QBrush(base.darker(160)))
    if kind == "hollow":
        # The holes run along it: a grid of them on its end.
        rows, cols = 2, max(2, round(width / 40.0))
        cw, ch = width / cols, height / rows
        for r in range(rows):
            for col in range(cols):
                y0, y1 = col * cw + 0.18 * cw, (col + 1) * cw - 0.18 * cw
                z0, z1 = r * ch + 0.18 * ch, (r + 1) * ch - 0.18 * ch
                p.drawPolygon(quad((length, y0, z0), (length, y1, z0),
                                   (length, y1, z1), (length, y0, z1)))
    elif kind == "perforated":
        # Its holes run upright: a grid of them on top.
        cols = max(3, round(length / 45.0))
        rows = max(2, round(width / 45.0))
        cw, ch = length / cols, width / rows
        for i in range(cols):
            for j in range(rows):
                x0, x1 = i * cw + 0.22 * cw, (i + 1) * cw - 0.22 * cw
                y0, y1 = j * ch + 0.22 * ch, (j + 1) * ch - 0.22 * ch
                p.drawPolygon(quad((x0, y0, height), (x1, y0, height),
                                   (x1, y1, height), (x0, y1, height)))
    elif kind == "cored":
        # A few large holes in a row on top.
        n = max(2, min(4, round(length / 80.0)))
        cell = length / n
        for i in range(n):
            x0, x1 = i * cell + 0.2 * cell, (i + 1) * cell - 0.2 * cell
            y0, y1 = 0.25 * width, 0.75 * width
            p.drawPolygon(quad((x0, y0, height), (x1, y0, height),
                               (x1, y1, height), (x0, y1, height)))
    elif kind == "aac":
        # Solid, light, its pores showing on every face.
        p.setBrush(QBrush(base.darker(150)))
        p.setPen(Qt.NoPen)
        import random
        rnd = random.Random(7)
        for _ in range(26):
            face = rnd.random()
            a, b = rnd.random(), rnd.random()
            if face < 0.45:
                pt = at(a * length, width, b * height)
            elif face < 0.75:
                pt = at(a * length, b * width, height)
            else:
                pt = at(length, a * width, b * height)
            p.drawEllipse(pt, 1.1, 1.1)
        p.setPen(thin)
    elif kind == "block":
        # Two cores, open on top.
        shell = min(32.0, 0.25 * width)
        mid = length / 2.0
        for x0, x1 in ((shell, mid - shell / 2.0),
                       (mid + shell / 2.0, length - shell)):
            p.drawPolygon(quad((x0, shell, height), (x1, shell, height),
                               (x1, width - shell, height),
                               (x0, width - shell, height)))
    # The measures, along the edges they measure.
    font = QFont(p.font())
    font.setPointSizeF(7.5)
    p.setFont(font)
    p.setPen(ink)

    def label(a, b, text, dx, dy):
        mid = QPointF((a.x() + b.x()) / 2.0 + dx, (a.y() + b.y()) / 2.0 + dy)
        p.drawText(QRectF(mid.x() - 30, mid.y() - 7, 60, 14),
                   Qt.AlignCenter, text)
    label(at(0, width, 0), at(length, width, 0), f"{length:g}", -8, 9)
    label(at(length, width, 0), at(length, 0, 0), f"{width:g}", 10, 8)
    label(at(0, width, 0), at(0, width, height), f"{height:g}", -18, 0)
    p.end()
    return pm


_TEXT_PATHS: dict = {}


def _text_path(text):
    """The words of a line type as a path, and its capital height — the
    same letters the sheets draw."""
    from PySide6.QtGui import QFont, QFontMetricsF
    path = _TEXT_PATHS.get(text)
    if path is None:
        font = QFont("Segoe UI")
        font.setPixelSize(100)
        font.setBold(True)
        path = QPainterPath()
        path.addText(0.0, 0.0, font, text)
        cap = QFontMetricsF(font).capHeight() or 70.0
        _TEXT_PATHS[text] = path = (path, cap)
    return path


def line_text_strokes(text: str, size: float) -> list:
    """The outlines of ``text`` as polylines in paper mm — its capitals
    ``size`` high, centred on the origin, y up — for drawing a line type's
    words with lines (the model's edges)."""
    path, cap = _text_path(text)
    box = path.boundingRect()
    k = float(size) / cap
    out = []
    for poly in path.toSubpathPolygons():
        pts = [((q.x() - box.center().x()) * k, -(q.y() + cap / 2.0) * k)
               for q in poly]
        if len(pts) > 1:
            out.append(pts)
    return out


def paint_line_text(painter: QPainter, lines, spec, colour: QColor,
                    scale: float = 1.0) -> None:
    """The words of a line type (core.layers.linetype_text ``spec``) along
    each of ``lines`` — ``(x0, y0, x1, y1)`` in the painter's units,
    ``scale`` of them to a paper mm (1 on a sheet; px per mm in a list) —
    in the gaps the pattern leaves for them, turned along each line and
    reading upright, filled in ``colour``: vector text, so a PDF keeps it
    sharp."""
    from core.layers import text_marks
    if spec is None:
        return
    text, size = spec[0], spec[1]
    path, cap = _text_path(text)
    box = path.boundingRect()
    k = float(size) / cap                  # capitals ``size`` mm high
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(colour))
    for x0, y0, x1, y1 in lines:
        for x, y, angle in text_marks((x0 / scale, y0 / scale),
                                      (x1 / scale, y1 / scale), spec):
            painter.save()
            painter.translate(x * scale, y * scale)
            painter.rotate(angle)
            painter.scale(k * scale, k * scale)
            painter.translate(-box.center().x(), cap / 2.0)
            painter.drawPath(path)
            painter.restore()
    painter.restore()


#: The mortar of the double joints, when the layer fills them.
MORTAR = QColor(205, 205, 205)


def paint_bond(painter: QPainter, path: QPainterPath, rings, key: str,
               ink: QColor, width_mm: float, ground: QColor | None,
               form: dict) -> list:
    """Masonry as it is built (core.hatches.bond_marks) in each ring of a
    plan or a vertical section — ``form["cut"]`` — over ``ground``,
    clipped to ``path`` (all the rings, even-odd) and each to its own ring.
    ``form["joints"]`` — single or double joints; with ``form["mortar"]``
    the double joints in light grey, the bricks on the ground. Returns the
    rings it could not draw that way, for the caller to lay the pattern as
    usual."""
    from core.hatches import bond_marks, fit_band, vertical_band
    cut = form.get("cut")
    joints = form.get("joints") or "single"
    mortar = bool(form.get("mortar")) and joints == "double"
    rest = []
    painter.save()
    under = MORTAR if mortar else ground
    if under is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(under))
        painter.drawPath(path)
    painter.setClipPath(path, Qt.IntersectClip)
    pen = QPen(ink)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.MiterJoin)
    painter.setBrush(Qt.NoBrush)
    for ring in rings:
        if len(ring) < 3:
            continue
        band = fit_band(ring) if cut == "plan" else vertical_band(ring)
        marks = bond_marks(key, band, cut, float(form.get("scale", 1.0)
                                                 or 1.0),
                           float(form.get("scale_n", 100.0) or 100.0),
                           form.get("brick"), joints, form.get("offset"))
        if marks is None:
            rest.append(ring)
            continue
        piece = QPainterPath()
        piece.moveTo(QPointF(float(ring[0][0]), float(ring[0][1])))
        for q in ring[1:]:
            piece.lineTo(QPointF(float(q[0]), float(q[1])))
        piece.closeSubpath()
        painter.save()
        painter.setClipPath(piece, Qt.IntersectClip)
        # A thin wall thins its joints, or they run together.
        pen.setWidthF(max(0.03, min(float(width_mm), band[4] / 16.0)))
        painter.setPen(pen)
        painter.drawLines([QLineF(x0, y0, x1, y1)
                           for x0, y0, x1, y1 in marks["lines"]])
        if marks["bricks"]:
            # Each brick its own outline: on the mortar, filled with the
            # ground (white without one) so the joint shows between.
            if mortar:
                painter.setBrush(QBrush(ground if ground is not None
                                        else QColor(255, 255, 255)))
            for pts in marks["bricks"]:
                painter.drawPolygon(QPolygonF([QPointF(x, y)
                                               for x, y in pts]))
            painter.setBrush(Qt.NoBrush)
        for pts in marks["polys"]:
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
        painter.restore()
    painter.restore()
    return rest


#: The wall a cut preview shows, by pattern: how many of the brick's
#: measures thick — what the bond is usually laid in (one brick, unless it
#: says otherwise) — or its thickness in mm.
_PREVIEW_WALL = {"brick": "width", "hollow_brick": "width",
                 "brick_honeycomb": "width", "brick_on_edge": "height",
                 "brick_one_half": "one_half", "block": "width",
                 "aac_block": "width", "perforated_block": "width",
                 "concrete_brick": "width",
                 "ashlar": 400.0, "insulation": 80.0,
                 "insulation_zigzag": 50.0, "wood_cross": 50.0}


def _preview_thick(key, brick) -> float:
    from core.hatches import brick_dims, piece_kind
    length, width, height, _bed, head = brick_dims(brick, piece_kind(key))
    wall = _PREVIEW_WALL.get(key, "length")
    return {"length": length, "width": width, "height": height,
            "one_half": length + width + head}.get(wall, wall)


def has_cut_preview(key, cross: bool = False) -> bool:
    """Whether pattern ``key`` looks otherwise in a plan and in a section
    than on its face: masonry as it is built, a pattern fitted to the
    piece, a wood one with a cross where it is cut across (``cross``)."""
    from core.hatches import COURSED, FITTED, WOOD
    return key in COURSED or key in FITTED or (cross and key in WOOD)


#: The paper around the wall in a cut tile: a shade off white, so a wall on
#: a white ground still reads.
_TILE_PAPER = QColor(238, 240, 243)
#: The swatches' border, shared by the face and the cut tiles.
_TILE_BORDER = QColor(120, 128, 138)


def cut_tile(key, cut: str, w: int, h: int, ink: QColor | None = None,
             dpr: float = 1.0, ground: QColor | None = None, brick=None,
             cross: bool = False, joints=None, mortar: bool = False,
             thick_px: float = 18.0) -> QPixmap:
    """A ``w`` × ``h`` px tile of how pattern ``key`` looks cut: a wall
    ``thick_px`` thick running through it — across, seen from above in a
    ``"plan"``; upright, in a ``"vertical"`` section — its faces inked, on
    a shade of paper, framed like the swatches. The same wall at the same
    scale in both, so they read as one. Masonry with ``brick``
    (``Layer.brick``) and its ``joints`` (double only when the layer says
    so; single otherwise: at a tile's size double ones blur) and
    ``mortar``; a wood pattern with ``cross``: in the section, a piece cut
    across, crossed; in the plan, a board along its grain."""
    from core.hatches import COURSED, WOOD, real_scale
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(_TILE_PAPER)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if has_cut_preview(key, cross):
        wood = cross and key in WOOD
        ink = ink or QColor(30, 36, 44)
        ground = ground or QColor(255, 255, 255)
        scale_n = 10.0
        real = 50.0 if wood else float(_preview_thick(key, brick))
        px = thick_px / (real / scale_n)       # px per paper mm
        tw, th, tp = w / px, h / px, real / scale_n
        if cut == "plan":
            y0 = (th - tp) / 2.0
            ring = [(-1.0, y0), (tw + 1.0, y0), (tw + 1.0, y0 + tp),
                    (-1.0, y0 + tp)]
            faces = ((-1.0, y0, tw + 1.0, y0),
                     (-1.0, y0 + tp, tw + 1.0, y0 + tp))
        else:
            x0 = (tw - tp) / 2.0
            ring = [(x0, -1.0), (x0 + tp, -1.0), (x0 + tp, th + 1.0),
                    (x0, th + 1.0)]
            faces = ((x0, -1.0, x0, th + 1.0),
                     (x0 + tp, -1.0, x0 + tp, th + 1.0))
        p.save()
        p.scale(px, px)
        path = QPainterPath()
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring]))
        path.closeSubpath()
        width = 0.8 / px                       # under a pixel: the joints
        if wood:
            if cut == "plan":
                paint_hatch(p, path, key, ink, width, 1.0, ground)
            else:
                paint_fitted(p, path, [ring], "wood_cross", ink, width, 1.0,
                             ground)
        elif key in COURSED:
            scale = real_scale(key, scale_n, brick) or 1.0
            paint_bond(p, path, [ring], key, ink, width, ground,
                       {"cut": cut, "scale": scale, "scale_n": scale_n,
                        "brick": brick,
                        "joints": joints if joints == "double" else "single",
                        "mortar": mortar})
        else:
            paint_fitted(p, path, [ring], key, ink, width, 1.0, ground)
        pen = QPen(ink)
        pen.setWidthF(1.3 / px)                # the faces: the cut line
        p.setPen(pen)
        p.drawLines([QLineF(*f) for f in faces])
        p.restore()
    p.setPen(QPen(_TILE_BORDER, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0))
    p.end()
    return QPixmap.fromImage(img)


def hatch_swatch(key, w: int, h: int, ink: QColor | None = None,
                 dpr: float = 1.0, ground: QColor | None = None,
                 angle: float = 0.0, scale: float = 1.0,
                 families=None) -> QPixmap:
    """A ``w`` × ``h`` px swatch of pattern ``key`` on white (or on
    ``ground``) with a thin border, the pattern shown at 3 px per mm — what
    the pickers show. ``None`` (the frame's fill): an empty swatch with a
    diagonal slash."""
    ink = ink or QColor(30, 36, 44)
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(ground if ground is not None else QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
    if key is None:
        p.setPen(QPen(QColor(200, 60, 50), 1.2))
        p.drawLine(rect.topLeft(), rect.bottomRight())
    else:
        k = 3.0                                    # px per paper mm
        p.save()
        p.scale(k, k)
        path = QPainterPath()
        path.addRect(QRectF(0, 0, w / k, h / k))
        paint_hatch(p, path, key, ink, 0.6 / k * 1.5, scale, None, angle,
                    families)
        p.restore()
    p.setPen(QPen(_TILE_BORDER, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRect(rect)
    p.end()
    return QPixmap.fromImage(img)


def any_colour_chip(w: int, h: int, colour: QColor | None = None,
                    dpr: float = 1.0, strokes: bool = False) -> QPixmap:
    """The «Other colour…» chip, the size and frame of :func:`colour_chip`:
    every hue across it, lighter at the top — or, once a colour is picked,
    that colour (as strokes for an ink) with a corner of hues left to say
    it can be changed."""
    from PySide6.QtGui import QLinearGradient, QPolygonF
    base = colour_chip(w, h, colour, dpr, strokes=strokes) \
        if colour is not None else None
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    hues = QLinearGradient(0, 0, w, 0)
    for i in range(7):
        hues.setColorAt(i / 6.0, QColor.fromHsvF((i % 6) / 6.0, 0.8, 0.95))
    if base is not None:
        p.drawPixmap(0, 0, base)
        corner = QPolygonF([QPointF(w * 0.55, h), QPointF(w, h),
                            QPointF(w, h * 0.35)])
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(hues))
        p.drawPolygon(corner)
    else:
        p.fillRect(QRectF(0, 0, w, h), QBrush(hues))
        fade = QLinearGradient(0, 0, 0, h)
        fade.setColorAt(0.0, QColor(255, 255, 255, 170))
        fade.setColorAt(0.6, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, h), QBrush(fade))
    p.setPen(QPen(QColor(70, 76, 86), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0))
    p.end()
    return QPixmap.fromImage(img)


def colour_chip(w: int, h: int, colour: QColor | None, dpr: float = 1.0,
                strokes: bool = False, paper: bool = False,
                badge: str | None = None) -> QPixmap:
    """A ``w`` × ``h`` px chip of ``colour`` with a dark border, for the
    ground and ink pickers. ``strokes``: three thick diagonal strokes of it
    on white (an ink; a light one on grey, or it would not show);
    ``paper``: the checkerboard of «nothing under it»; ``colour`` ``None``
    (as the frame says): the frame's own grey. ``badge``: a letter in the
    corner — «A» for automatic."""
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if paper:
        cell = 5
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if (x // cell + y // cell) % 2:
                    p.fillRect(x, y, cell, cell, QColor(214, 218, 224))
    elif strokes:
        # A piece of hatch in the ink: fine lines at 45°, evenly spaced,
        # running out at the frame — what the colour is used for.
        if colour is not None and colour.lightnessF() > 0.8:
            p.fillRect(0, 0, w, h, QColor(118, 122, 130))
        pen = QPen(colour if colour is not None else QColor(89, 94, 105), 1.4)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setClipRect(QRectF(1.0, 1.0, w - 2.0, h - 2.0))
        gap = 4.5
        x = -float(h)
        while x < w:
            p.drawLine(QPointF(x, h), QPointF(x + h, 0.0))
            x += gap
        p.setClipping(False)
    else:
        p.fillRect(0, 0, w, h, colour if colour is not None
                   else QColor(255, 255, 255))
    if badge:
        from PySide6.QtGui import QFont
        font = QFont()
        font.setPixelSize(max(7, int(h * 0.5)))
        font.setBold(True)
        p.setFont(font)
        box = QRectF(w - h * 0.62, h * 0.38, h * 0.62 - 1.0, h * 0.62 - 1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(box)
        p.setPen(QColor(40, 44, 52))
        p.drawText(box, Qt.AlignCenter, badge)
    p.setPen(QPen(QColor(70, 76, 86), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0))
    p.end()
    return QPixmap.fromImage(img)
