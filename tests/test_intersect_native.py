# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust box-pair test (Intersect Faces' broad phase) must give exactly
the pairs the NumPy code gives, in the same order: random boxes of mixed
sizes, boxes that touch within eps or miss by a hair, a huge pavement under
the rest, flat boxes, both one list against itself and two lists. Then
Intersect Faces itself, both ways, on random tilted plates. Skipped when
the module is not built."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("INGETRAZO_RUST", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import core._native as _native  # noqa: E402
from core import intersect  # noqa: E402

pytestmark = pytest.mark.skipif(_native.native is None,
                                reason="native module not built")

EPS = 1e-6


def _random_boxes(rng, n):
    lo, hi = [], []
    for _ in range(n):
        kind = rng.random()
        c = [rng.uniform(-50, 50) for _ in range(3)]
        if kind < 0.05:                       # a pavement under everything
            s = [rng.uniform(40, 120), rng.uniform(40, 120), 0.0]
        elif kind < 0.2:                      # flat (a face in a plane)
            s = [rng.uniform(0, 3), rng.uniform(0, 3), 0.0]
        else:
            s = [rng.uniform(0, 4) for _ in range(3)]
        a = [c[k] - s[k] / 2 for k in range(3)]
        b = [c[k] + s[k] / 2 for k in range(3)]
        lo.append(a)
        hi.append(b)
    lo, hi = np.array(lo), np.array(hi)
    # Neighbours that touch exactly, within eps, or miss by a hair.
    for _ in range(n):
        i, j = rng.randrange(n), rng.randrange(n)
        k = rng.randrange(3)
        gap = rng.choice([0.0, EPS * 0.5, EPS * 0.95, EPS, EPS * 1.0001,
                          EPS * 3])
        w = hi[j, k] - lo[j, k]
        lo[j, k] = hi[i, k] + gap
        hi[j, k] = lo[j, k] + w
    return lo, hi


def _pairs(monkeypatch, use_native, *args):
    monkeypatch.setattr(_native, "native",
                        _native.available() if use_native else None)
    return list(intersect._touching(*args))


@pytest.mark.parametrize("seed", range(8))
def test_same_pairs_as_numpy(monkeypatch, seed):
    rng = random.Random(seed)
    lo_a, hi_a = _random_boxes(rng, rng.randrange(1, 900))
    lo_b, hi_b = _random_boxes(rng, rng.randrange(1, 900))
    for args in ((lo_a, hi_a, lo_a, hi_a, True),
                 (lo_a, hi_a, lo_b, hi_b, False)):
        want = _pairs(monkeypatch, False, *args)
        got = _pairs(monkeypatch, True, *args)
        assert got == want
    assert want, "the scene should have touching boxes"


def test_one_box_and_empty(monkeypatch):
    lo = np.zeros((1, 3))
    hi = np.ones((1, 3))
    empty = np.zeros((0, 3))
    for args in ((lo, hi, lo, hi, True), (lo, hi, lo, hi, False),
                 (lo, hi, empty, empty, False)):
        assert _pairs(monkeypatch, True, *args) == \
            _pairs(monkeypatch, False, *args)


def _plates(rng, n):
    """Random tilted rectangles (some with a hole), as loose faces."""
    from PySide6.QtGui import QMatrix4x4, QVector3D

    from core.scene import Scene
    scene = Scene()
    for _ in range(n):
        m = QMatrix4x4()
        m.translate(*(rng.uniform(-3, 3) for _ in range(3)))
        m.rotate(rng.uniform(0, 360), rng.random(), rng.random(),
                 rng.random() + 0.1)
        w, d = rng.uniform(0.5, 3), rng.uniform(0.5, 3)
        pts = [m.map(QVector3D(x, y, 0)) for x, y in
               ((0, 0), (w, 0), (w, d), (0, d))]
        try:
            scene.mesh.add_face(pts)
        except ValueError:
            pass
    return scene


@pytest.mark.parametrize("seed", range(4))
def test_intersect_faces_same_segments(monkeypatch, seed):
    from core.intersect import WITH_SELECTION, segments_for
    scene = _plates(random.Random(100 + seed), 40)
    scene.selection.update(scene.mesh.faces)
    out = []
    for use in (False, True):
        monkeypatch.setattr(_native, "native",
                            _native.available() if use else None)
        out.append([(p.toTuple(), q.toTuple())
                    for p, q in segments_for(scene, WITH_SELECTION)])
    assert out[0] == out[1]
    assert out[0], "random plates should cross somewhere"


def test_boxes_on_cell_borders_and_a_giant(monkeypatch):
    """Unit boxes on an integer lattice that stop half an eps short of the
    next one (they touch only through eps, across a cell border of the
    grid), plus one box far bigger than the grid's cell budget."""
    lo, hi = [], []
    for x in range(30):
        for y in range(30):
            lo.append([x, y, 0.0])
            hi.append([x + 1 - EPS * 0.5, y + 1 - EPS * 0.5, 1.0])
    lattice = np.array(lo), np.array(hi)
    lo.append([-5000.0, -5000.0, 0.5])
    hi.append([5000.0, 5000.0, 0.5])
    giant = np.array(lo), np.array(hi)
    # (the lattice alone keeps a cell of 1, so its borders are integers)
    for lo, hi in (lattice, giant):
        small_lo, small_hi = lattice[0] + 0.25, lattice[1] - 0.25
        for args in ((lo, hi, lo, hi, True), (lo, hi, lo, hi, False),
                     (small_lo, small_hi, lo, hi, False)):
            want = _pairs(monkeypatch, False, *args)
            assert _pairs(monkeypatch, True, *args) == want
