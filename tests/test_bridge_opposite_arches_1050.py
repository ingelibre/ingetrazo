# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bridge (issue #1050): a side drawn with many short segments does not pull
the middle of its profile, so two arches rounded at opposite ends join upright
instead of crossing through each other like an hourglass."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.bridge import Profile, _centre, _pairs, bridge, strips
from core.mesh import Mesh

_GAP = 3.0


def _arch(x, up, n=8):
    """A doorway in a wall across X: a square with a half circle on its top
    (``up``) or under its bottom, the curve in ``n`` short segments."""
    pts = [QVector3D(x, 1, 0), QVector3D(x, 1, 2), QVector3D(x, -1, 2),
           QVector3D(x, -1, 0)]
    pts += [QVector3D(x, math.cos(math.pi * i / n), -math.sin(math.pi * i / n))
            for i in range(n - 1, 0, -1)]
    if up:
        pts = [QVector3D(p.x(), p.y(), 2 - p.z()) for p in pts]
    return pts


def _sides(a, b):
    p, q = Profile([a], True), Profile([b], True)
    return [poly for ra, rb, closed in _pairs(p, q)
            for poly in strips(ra, rb, closed)]


def _joins(polys):
    """The edges running from one wall to the other, each once."""
    out = {}
    for poly in polys:
        for i, p in enumerate(poly):
            q = poly[(i + 1) % len(poly)]
            if abs(p.x() - q.x()) > 1e-6:
                key = frozenset(((p.y(), p.z()), (q.y(), q.z())))
                out[key] = (p, q)
    return list(out.values())


def _goes_through(p, q, tri) -> bool:
    """The segment p-q passes through the triangle, touching none of its
    corners."""
    a, b, c = tri
    if any((s - t).length() < 1e-6 for s in (p, q) for t in tri):
        return False
    n = QVector3D.crossProduct(b - a, c - a)
    along = QVector3D.dotProduct(n, q - p)
    if n.length() < 1e-9 or abs(along) < 1e-9:
        return False
    t = QVector3D.dotProduct(n, a - p) / along
    if not 1e-6 < t < 1 - 1e-6:
        return False
    x = p + (q - p) * t
    sides = [QVector3D.dotProduct(QVector3D.crossProduct(v - u, x - u), n)
             for u, v in ((a, b), (b, c), (c, a))]
    return all(s > 1e-9 for s in sides) or all(s < -1e-9 for s in sides)


@pytest.mark.parametrize("n", [16, 32, 64])
@pytest.mark.parametrize("more", [3, -3])
def test_opposite_arches_do_not_go_through_themselves(n, more):
    polys = _sides(_arch(0, up=False, n=n), _arch(_GAP, up=True, n=n + more))
    tris = [(poly[0], poly[i], poly[i + 1]) for poly in polys
            for i in range(1, len(poly) - 1)]
    assert not any(_goes_through(p, q, t)
                   for p, q in _joins(polys) for t in tris)


@pytest.mark.parametrize("first_up", [False, True])
def test_opposite_arches_join_by_the_shortest_way(first_up):
    a, b = _arch(0, first_up, n=32), _arch(_GAP, not first_up, n=24)
    joins = _joins(_sides(a, b))
    mean = sum((p - q).length() for p, q in joins) / len(joins)
    assert mean < 1.15 * _GAP


def test_the_middle_of_a_profile_does_not_follow_its_points():
    # The same outline, its curve in 4 or in 64 segments.
    coarse, fine = _centre(_arch(0, True, 4)), _centre(_arch(0, True, 64))
    assert abs(coarse.z() - fine.z()) < 0.05


def test_a_profile_with_no_length_still_has_a_middle():
    p = QVector3D(1, 2, 3)
    assert (_centre([p, QVector3D(p), QVector3D(p)]) - p).length() < 1e-6


def test_opposite_arches_make_a_closed_solid():
    m = Mesh()
    a, b = _arch(0, False), _arch(_GAP, True, n=12)
    fa, fb = m.add_face(a), m.add_face(b)
    new = bridge(m, [Profile([a], True, fa), Profile([b], True, fb)])
    assert new
    assert all(len(e.faces) == 2 for e in m.edges)
