# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A section dragged by its arrow measures the model once, not per move.

Seen in a user's video (a furnished two-storey house, 0.6.1 on Windows with
the Rust engine): every drag of a section's arrow froze the window about
two seconds. Each move cut the plane against every triangle of the model
from scratch — their corners, their heights along the normal, a crossing
point for each of their three edges — though sliding a plane along its
normal changes none of that but the offset.

Compared with the plain way of cutting, to the bit; counted, not timed.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QVector3D

from core import section
from core.section import PlaneReach, cut_chords


def _cut_plain(v0, e1, e2, normal, point, visible=None, rows=False):
    """``cut_chords`` as it was: every triangle, every edge."""
    nv = np.array([normal.x(), normal.y(), normal.z()], dtype=np.float64)
    c = float(np.dot(nv, [point.x(), point.y(), point.z()]))
    p0 = np.asarray(v0, dtype=np.float64)
    p1 = p0 + e1
    p2 = p0 + e2
    d0 = p0 @ nv - c
    d1 = p1 @ nv - c
    d2 = p2 @ nv - c
    pts = []
    for (a, b, da, db) in ((p0, p1, d0, d1), (p1, p2, d1, d2),
                           (p2, p0, d2, d0)):
        cross = (da * db) < 0
        t = np.zeros(len(da))
        np.divide(da, da - db, out=t, where=cross)
        pts.append((cross, a + (b - a) * t[:, None]))
    two = (pts[0][0].astype(np.int8) + pts[1][0] + pts[2][0]) == 2
    if visible is not None:
        two &= visible
    if not two.any():
        return (None, None) if rows else None
    acc = np.zeros((int(two.sum()), 2, 3))
    slot = np.zeros(int(two.sum()), dtype=np.int64)
    for cross, p in pts:
        m = cross[two]
        where = np.where(m)[0]
        acc[where, np.minimum(slot[where], 1)] = p[two][m]
        slot[where] += 1
    if rows:
        return acc.astype(np.float32), np.nonzero(two)[0]
    return acc.astype(np.float32)


def _triangles(rng, n):
    """Random triangles, some lying on a grid so corners fall exactly on
    the plane's offsets (the cases where an edge touches without
    crossing)."""
    v0 = rng.uniform(-5, 5, size=(n, 3))
    v0[: n // 3] = np.round(v0[: n // 3])
    e1 = rng.uniform(-2, 2, size=(n, 3))
    e2 = rng.uniform(-2, 2, size=(n, 3))
    e1[: n // 4] = np.round(e1[: n // 4])
    e2[: n // 4] = np.round(e2[: n // 4])
    return v0, e1, e2


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return a.dtype == b.dtype and a.shape == b.shape and np.array_equal(a, b)


def test_the_kept_heights_cut_what_the_plain_cut_cuts():
    rng = np.random.default_rng(20261110)
    v0, e1, e2 = _triangles(rng, 4000)
    visible = rng.random(len(v0)) > 0.1
    cut = 0
    for normal in (QVector3D(0, 0, -1), QVector3D(1, 0, 0),
                   QVector3D(0.3, -0.5, 0.8).normalized()):
        reach = PlaneReach(v0, e1, e2, normal)
        for z in (-6.0, -1.0, 0.0, 0.5, 1.0, 2.25, 3.0, 7.0):
            point = QVector3D(0.1, -0.2, 0.0) + normal * z
            for vis in (None, visible):
                got = cut_chords(v0, e1, e2, normal, point, vis, rows=True,
                                 reach=reach)
                want = _cut_plain(v0, e1, e2, normal, point, vis, rows=True)
                assert _same(got[0], want[0]) and _same(got[1], want[1])
                assert _same(cut_chords(v0, e1, e2, normal, point, vis),
                             _cut_plain(v0, e1, e2, normal, point, vis))
                cut += 0 if want[0] is None else len(want[0])
    assert cut > 10000           # the comparison did see chords


def test_a_slid_plane_works_only_the_triangles_it_crosses(monkeypatch):
    rng = np.random.default_rng(7)
    v0, e1, e2 = _triangles(rng, 20000)
    # Small triangles, as a model's are next to its size.
    e1, e2 = e1 * 0.1, e2 * 0.1
    normal = QVector3D(0, 0, 1)
    reach = PlaneReach(v0, e1, e2, normal)
    worked = []
    real = np.divide

    def counted(a, b, *args, **kw):
        worked.append(len(a))
        return real(a, b, *args, **kw)

    monkeypatch.setattr(section.np if hasattr(section, "np") else np,
                        "divide", counted)
    reach.cut(QVector3D(0, 0, 4.5))
    # Only triangles reaching above and below z = 4.5 are cut, three edges
    # each: a few hundred of twenty thousand. Measuring every triangle
    # again was 3 × 20 000 per move.
    assert 0 < sum(worked) < 0.1 * 3 * len(v0)


def test_the_heights_are_kept_only_for_the_same_arrays_and_normal():
    rng = np.random.default_rng(3)
    v0, e1, e2 = _triangles(rng, 50)
    n = QVector3D(0, 0, 1)
    reach = PlaneReach(v0, e1, e2, n)
    assert reach.fits(v0, n, e1, e2)
    assert not reach.fits(v0.copy(), n, e1, e2)
    assert not reach.fits(v0, n, e1.copy(), e2)
    assert not reach.fits(v0, QVector3D(0, 1, 0), e1, e2)
    # Handed a reach that does not fit, the cut makes its own and is right.
    other = QVector3D(1, 0, 0)
    got = cut_chords(v0, e1, e2, other, QVector3D(0.5, 0, 0), rows=True,
                     reach=reach)
    want = _cut_plain(v0, e1, e2, other, QVector3D(0.5, 0, 0), rows=True)
    assert _same(got[0], want[0]) and _same(got[1], want[1])
