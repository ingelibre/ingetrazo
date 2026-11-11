# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust engine's ear clipping gives the Python port's triangles.

Every face of a model is triangulated for the picture, the pick index,
the hidden lines and the section fills — 90 000 of them in Python ear by
ear when the plaza opens or is drawn by layer (3.8 s of its 16 s of
lines). The engine's `earcut` is the same Mapbox port step for step, so
the triangles are the same, index for index, in the same order: a
different valid triangulation would still move the seams of a textured
face and the pixels of every picture test."""
from __future__ import annotations

import numpy as np
import pytest

from core import _native
from core import triangulate as T

native = _native.available()
pytestmark = pytest.mark.skipif(native is None or not hasattr(native, "earcut"),
                                reason="Rust engine without earcut")


def _both(points, holes=None):
    rust = native.earcut(np.asarray(points, dtype=np.float64).reshape(-1, 2),
                         list(holes or []))
    # The Python port works on Python floats (its ``_sign`` subtracts
    # booleans, which NumPy's refuse): hand it those, as every caller does.
    py = T.earcut_py([(float(x), float(y)) for x, y in points],
                     list(holes or []))
    return [tuple(t) for t in rust.tolist()], py


def _star(rng, n, r0=1.0, r1=3.0, cx=0.0, cy=0.0):
    a = np.sort(rng.uniform(0, 2 * np.pi, n))
    r = rng.uniform(r0, r1, n)
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


def test_random_polygons_with_holes_give_the_same_triangles():
    rng = np.random.default_rng(20261111)
    seen = 0
    for _ in range(300):
        outer = _star(rng, int(rng.integers(3, 40)))
        pts = [outer]
        holes = []
        for _h in range(int(rng.integers(0, 4))):
            at = len(np.concatenate(pts))
            holes.append(at)
            c = rng.uniform(-0.6, 0.6, 2)
            pts.append(_star(rng, int(rng.integers(3, 9)), 0.1, 0.4, *c)[::-1])
        points = np.concatenate(pts)
        rust, py = _both(points, holes)
        assert rust == py
        seen += len(py)
    assert seen > 5000


def test_the_degenerate_cases_recover_the_same_way():
    cases = [
        # collinear points on an edge, duplicate corners
        ([(0, 0), (1, 0), (2, 0), (2, 2), (2, 2), (0, 2), (0, 1)], []),
        # a square with a hole touching its edge, and a one-point hole
        ([(0, 0), (4, 0), (4, 4), (0, 4), (0, 2), (1, 2), (1, 3), (0, 3),
          (2, 2)], [4, 8]),
        # two holes at the same height, the bridge's tie
        ([(0, 0), (6, 0), (6, 4), (0, 4), (1, 1), (1, 3), (2, 3), (2, 1),
          (4, 1), (4, 3), (5, 3), (5, 1)], [4, 8]),
        # a self-touching outline (a figure of eight)
        ([(0, 0), (2, 0), (2, 2), (1, 1), (0, 2), (1, 1)], []),
        # a slit: an outline that folds back on itself
        ([(0, 0), (4, 0), (4, 1), (1, 1), (1, 1.0000001), (4, 1.0000001),
          (4, 2), (0, 2)], []),
        # fewer than three points, and all collinear
        ([(0, 0), (1, 0)], []),
        ([(0, 0), (1, 0), (2, 0), (3, 0)], []),
        # clockwise outer, counter-clockwise hole (both turned round)
        ([(0, 0), (0, 4), (4, 4), (4, 0), (1, 1), (3, 1), (3, 3), (1, 3)], [4]),
    ]
    for points, holes in cases:
        rust, py = _both(np.asarray(points, dtype=float), holes)
        assert rust == py, (points, holes)


def test_triangulate_goes_through_the_engine_when_it_is_on(monkeypatch):
    from PySide6.QtGui import QVector3D as V
    called = []
    real = native.earcut

    class Spy:
        def __getattr__(self, name):
            return getattr(native, name)

        def earcut(self, pts, holes):
            called.append(len(pts))
            return real(pts, holes)

    monkeypatch.setattr(_native, "native", Spy())
    outer = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)]
    hole = [V(1, 1, 0), V(1, 3, 0), V(3, 3, 0), V(3, 1, 0)]
    tris = T.triangulate(outer, [hole])
    assert called == [8] and len(tris) == 8
    # A convex face without holes fans in Python: no call.
    assert len(T.triangulate(outer)) == 2 and called == [8]
    monkeypatch.setattr(_native, "native", None)
    assert T.triangulate(outer, [hole]) == tris and called == [8]
