# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Thumbnails for the tray's «In model» list: a small picture of each
component definition, drawn by hand.

Not a render — the GL renderer is never touched, which is what keeps the
tray cheap. The faces are projected from one fixed corner (front-right,
from above), painted back to front with a plain light on their own colour,
and fitted to the icon. Enough to tell a chair from a table at a glance.
A definition is drawn once and kept; a change to its geometry, its paint
or its subgroups draws it again.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF

#: Icon side, in pixels.
SIZE = 40
#: Faces drawn at most: a big definition is thinned evenly, which still
#: reads at this size and keeps a refresh well under a frame.
MAX_FACES = 3000
#: Vertices read for the change check, at most.
_PROBE = 2000

#: Where the picture is seen from (towards the viewer), and the light.
_EYE = (0.62, -0.74, 0.55)
_LIGHT = (0.35, -0.55, 0.85)
#: The default material's front, as the viewport shows it.
_DEFAULT = (0.96, 0.95, 0.925)

_cache: dict = {}


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


_E = _unit(_EYE)
_R = _unit((-_E[1], _E[0], 0.0))
_U = _unit((_E[1] * _R[2] - _E[2] * _R[1],
            _E[2] * _R[0] - _E[0] * _R[2],
            _E[0] * _R[1] - _E[1] * _R[0]))
_L = _unit(_LIGHT)


def _placements(definition, m=None, depth=0):
    """``(mesh, matrix_or_None, paint)`` for the definition's own mesh and
    every subgroup below it, in the definition's coordinates — its own
    placement in the model is left out, so every copy draws the same."""
    paint = getattr(definition, "material", None)
    yield definition.mesh, m, paint
    if depth > 16:
        return
    for child in getattr(definition, "children", None) or ():
        xf = getattr(child, "xform", None)
        cm = xf if m is None else (m if xf is None else m * xf)
        yield from _placements(child, cm, depth + 1)


def _signature(definition) -> tuple:
    """What the picture depends on: counts, a sampled coordinate sum and
    the paint of each piece. Cheap, and it changes when the geometry does."""
    sig = []
    for mesh, m, paint in _placements(definition):
        verts = mesh.vertices
        step = max(1, len(verts) // _PROBE)
        s = 0.0
        for v in verts[::step]:
            p = v.position
            s += p.x() + p.y() * 1.000003 + p.z() * 1.000007
        faces = mesh.faces
        fstep = max(1, len(faces) // _PROBE)
        colors = tuple(_paint_key(f.attrs) for f in faces[::fstep])
        sig.append((id(mesh), len(verts), len(faces), round(s, 6),
                    hash(colors), _paint_key(paint),
                    tuple(m.data()) if m is not None else None))
    return tuple(sig)


def _paint_key(attrs):
    if not attrs:
        return None
    c = attrs.get("color")
    t = attrs.get("texture")
    return (tuple(round(float(x), 3) for x in c) if c else None,
            t.get("path") if isinstance(t, dict) else None)


def _rgb(attrs, inherited):
    """The colour a face shows: its own paint, else the definition's, else
    the default material. A texture without a colour reads as a mid tone."""
    for paint in (attrs, inherited):
        if not paint:
            continue
        c = paint.get("color")
        if c:
            return tuple(float(x) for x in c[:3])
        if paint.get("texture"):
            return (0.72, 0.66, 0.58)
    return _DEFAULT


def thumbnail(definition, size: int = SIZE) -> QPixmap:
    """The icon for ``definition`` (a component instance or a kept
    template), from the cache when nothing it shows has changed."""
    sig = _signature(definition)
    key = (sig[0][0], size)
    hit = _cache.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    pm = _draw(definition, size)
    # Past this, definitions long gone. (256 was below the 1 815 of a big
    # plant, and scrolling its list drew every picture again, #158.)
    if len(_cache) > 4096:
        _cache.clear()
    _cache[key] = (sig, pm)
    return pm


def _draw(definition, size: int) -> QPixmap:
    total = sum(len(mesh.faces) for mesh, _m, _p in _placements(definition))
    stride = max(1, math.ceil(total / MAX_FACES))
    polys = []                              # (depth, points2d, rgb, shade)
    k = 0
    for mesh, m, paint in _placements(definition):
        for f in mesh.faces:
            k += 1
            if k % stride:
                continue
            pts = [v.position for v in f.loop]
            if len(pts) < 3:
                continue
            if m is not None:
                pts = [m.map(p) for p in pts]
            n = _normal(pts)
            if n is None:
                continue
            lam = abs(n[0] * _L[0] + n[1] * _L[1] + n[2] * _L[2])
            xy = [(p.x() * _R[0] + p.y() * _R[1] + p.z() * _R[2],
                   -(p.x() * _U[0] + p.y() * _U[1] + p.z() * _U[2]))
                  for p in pts]
            depth = sum(p.x() * _E[0] + p.y() * _E[1] + p.z() * _E[2]
                        for p in pts) / len(pts)
            polys.append((depth, xy, _rgb(f.attrs, paint), lam))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if not polys:
        return pm
    xs = [x for _d, xy, _c, _s in polys for x, _y in xy]
    ys = [y for _d, xy, _c, _s in polys for _x, y in xy]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    margin = 2.0
    scale = (size - 2 * margin) / span
    ox = margin + (size - 2 * margin - (max(xs) - min(xs)) * scale) / 2
    oy = margin + (size - 2 * margin - (max(ys) - min(ys)) * scale) / 2
    x0, y0 = min(xs), min(ys)
    polys.sort(key=lambda r: r[0])          # far first: nearer ones cover
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    for _d, xy, rgb, lam in polys:
        k = 0.5 + 0.5 * lam
        col = QColor.fromRgbF(*(min(1.0, c * k) for c in rgb))
        p.setBrush(col)
        p.setPen(QPen(col.darker(150), 0.6))
        p.drawPolygon(QPolygonF([QPointF(ox + (x - x0) * scale,
                                         oy + (y - y0) * scale)
                                 for x, y in xy]))
    p.end()
    return pm


def _normal(pts):
    """Newell's normal of a polygon, ``None`` when it has no area."""
    nx = ny = nz = 0.0
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        nx += (a.y() - b.y()) * (a.z() + b.z())
        ny += (a.z() - b.z()) * (a.x() + b.x())
        nz += (a.x() - b.x()) * (a.y() + b.y())
    n = math.sqrt(nx * nx + ny * ny + nz * nz)
    if n < 1e-12:
        return None
    return (nx / n, ny / n, nz / n)
