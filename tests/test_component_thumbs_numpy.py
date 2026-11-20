# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «In model» pictures are worked out over every face at once, and
come out pixel for pixel as the one-face-at-a-time loop drew them.

That loop read each corner's coordinates five times and ran Newell's
normal, the depth and the projection in Python per face: ~50 ms for a
pergola of 1 700 faces on Marco's plaza, and the pictures of the rows a
selection scrolled into view landed inside the next Ctrl+Z (20-11). Now
each corner is read once and numpy does the sums — in the same order,
CPython's compensated ``sum()`` included, so the doubles are the same."""
from __future__ import annotations

import math
import random
from types import SimpleNamespace as NS

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QMatrix4x4, QPainter, QPen, QPixmap,
                           QPolygonF, QVector3D)
from PySide6.QtWidgets import QApplication

from views import component_thumbs as ct

_app = QApplication.instance() or QApplication([])


# -- the drawing as 0.6.2 did it, one face at a time ------------------------
def _normal_ref(pts):
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


def _draw_ref(definition, size):
    _E, _R, _U, _L = ct._E, ct._R, ct._U, ct._L
    total = sum(len(mesh.faces) for mesh, _m, _p in ct._placements(definition))
    stride = max(1, math.ceil(total / ct.MAX_FACES))
    polys = []
    k = 0
    for mesh, m, paint in ct._placements(definition):
        for f in mesh.faces:
            k += 1
            if k % stride:
                continue
            pts = [v.position for v in f.loop]
            if len(pts) < 3:
                continue
            if m is not None:
                pts = [m.map(p) for p in pts]
            n = _normal_ref(pts)
            if n is None:
                continue
            lam = abs(n[0] * _L[0] + n[1] * _L[1] + n[2] * _L[2])
            xy = [(p.x() * _R[0] + p.y() * _R[1] + p.z() * _R[2],
                   -(p.x() * _U[0] + p.y() * _U[1] + p.z() * _U[2]))
                  for p in pts]
            depth = sum(p.x() * _E[0] + p.y() * _E[1] + p.z() * _E[2]
                        for p in pts) / len(pts)
            polys.append((depth, xy, ct._rgb(f.attrs, paint), lam))
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
    polys.sort(key=lambda r: r[0])
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


# -- definitions of every kind of face ---------------------------------------
_PAINTS = [None, {"color": (0.8, 0.2, 0.1)}, {"color": (1.0, 1.0, 1.0)},
           {"texture": {"path": "madera.png"}}, {}]


def _face(pts, attrs=None):
    return NS(loop=[NS(position=QVector3D(*p)) for p in pts], attrs=attrs)


def _random_def(rng, nfaces, children=0, depth=0):
    faces = []
    for _ in range(nfaces):
        kind = rng.random()
        n = rng.choice([1, 2, 3, 3, 4, 4, 4, 5, 6, 8, 9, 12, 17, 33])
        if kind < 0.1:          # a sliver: no area, left out
            p = (rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5))
            pts = [p] * n
        else:
            c = [rng.uniform(-20, 20) for _ in range(3)]
            r = rng.uniform(0.01, 6)
            a0 = rng.uniform(0, 6.3)
            tilt = rng.uniform(-1, 1)
            pts = [(c[0] + r * math.cos(a0 + 6.283 * i / n),
                    c[1] + r * math.sin(a0 + 6.283 * i / n),
                    c[2] + tilt * r * math.cos(a0 + 6.283 * i / n)
                    + rng.uniform(-0.3, 0.3))
                   for i in range(n)]
            if kind < 0.15:     # signed zeros and repeated depths
                pts = [(-0.0, y, 0.0) for _x, y, _z in pts]
        faces.append(_face(pts, rng.choice(_PAINTS)))
    kids = []
    for _ in range(children):
        kid = _random_def(rng, rng.randint(0, 40), 1 if depth < 1 else 0,
                          depth + 1)
        m = QMatrix4x4()
        choice = rng.random()
        if choice < 0.3:
            m.translate(rng.uniform(-9, 9), rng.uniform(-9, 9), 1.5)
        elif choice < 0.6:
            m.rotate(rng.uniform(0, 360), 0.3, 0.2, 1.0)
            m.scale(rng.uniform(0.2, 3.0))
        elif choice < 0.8:
            m.scale(1.0, -1.0, 2.0)     # a mirror
        else:
            m = None
        kid.xform = m
        kids.append(kid)
    return NS(mesh=NS(faces=faces, vertices=[]), children=kids,
              material=rng.choice(_PAINTS), name="def")


def _pixels(pm):
    im = pm.toImage()
    return bytes(im.constBits())


def test_the_pictures_are_the_same_pixels_as_one_face_at_a_time():
    rng = random.Random(1405)
    cases = [_random_def(rng, rng.randint(0, 60), rng.randint(0, 3))
             for _ in range(60)]
    # Over MAX_FACES: thinned evenly, the same faces left out.
    cases.append(_random_def(rng, ct.MAX_FACES * 2 + 7, 2))
    cases.append(_random_def(rng, 0, 0))                     # nothing
    cases.append(NS(mesh=NS(faces=[_face([(0, 0, 0)] * 4)], vertices=[]),
                    children=[], material=None, name="sliver"))
    for i, d in enumerate(cases):
        for size in (ct.SIZE, 17):
            assert _pixels(ct._draw(d, size)) == _pixels(_draw_ref(d, size)), \
                (i, size)


class _CountedV(QVector3D):
    """A corner that counts how often its coordinates are read."""
    reads = [0]

    def x(self):
        self.reads[0] += 1
        return super().x()

    def y(self):
        self.reads[0] += 1
        return super().y()

    def z(self):
        self.reads[0] += 1
        return super().z()

    def toTuple(self):
        self.reads[0] += 3
        return super().toTuple()


def test_each_corner_is_read_once():
    rng = random.Random(7)
    faces = []
    corners = 0
    for _ in range(200):
        n = rng.choice([3, 4, 5, 8])
        c = [rng.uniform(-5, 5) for _ in range(3)]
        faces.append(NS(loop=[NS(position=_CountedV(
            c[0] + math.cos(i), c[1] + math.sin(i), c[2] + 0.1 * i))
            for i in range(n)], attrs=None))
        corners += n
    d = NS(mesh=NS(faces=faces, vertices=[]), children=[], material=None,
           name="d")
    _CountedV.reads[0] = 0
    ct._draw(d, ct.SIZE)
    # One read of x, y and z per corner (the loop read each one five
    # times over: twice in the normal, in the projection and the depth).
    assert _CountedV.reads[0] == 3 * corners, (_CountedV.reads[0], corners)
