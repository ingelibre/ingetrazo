# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""core.edge_grid.EdgeGrid binned by the native engine holds NumPy's very
cells, in NumPy's order (Block 6 of 0.6.3): the same segments in the same
cells, the same long ones, the same answers near every pixel — over
segments on cell boundaries, off screen, of zero length, across the whole
view, not finite or behind the camera."""
from __future__ import annotations

import numpy as np
import pytest

import core._native as _native
from core import edge_grid
from core.edge_grid import EdgeGrid

mod = _native.native
pytestmark = pytest.mark.skipif(
    mod is None or not hasattr(mod, "edge_grid_bins"),
    reason="native module not built")

SLOTS = ("reach", "cell", "cx0", "cy0", "ncx", "ncy", "keys", "ids",
         "long_ids", "width", "height", "n")


def _segments(rng, n, w, h):
    ax = rng.uniform(-200, w + 200, n)
    ay = rng.uniform(-200, h + 200, n)
    ln = 10.0 ** rng.uniform(-1, 3.2, n)
    ang = rng.uniform(0, 2 * np.pi, n)
    bx, by = ax + ln * np.cos(ang), ay + ln * np.sin(ang)
    k = n // 10
    ax[:k] = np.round(ax[:k] / 32.0) * 32.0          # on cell boundaries
    by[k:2 * k] = ay[k:2 * k]                         # level
    bx[2 * k:3 * k] = ax[2 * k:3 * k]                 # upright
    bx[3 * k:3 * k + 20] = ax[3 * k:3 * k + 20]       # zero length
    by[3 * k:3 * k + 20] = ay[3 * k:3 * k + 20]
    sp = (np.nan, np.inf, -np.inf, 1e308, -1e308, -0.0, 0.0, 5e-324)
    for j, v in enumerate(sp):
        (ax, ay, bx, by)[j % 4][3 * k + 40 + j] = v
    ax[3 * k + 60:3 * k + 70] = -1e5                  # far off, long
    bx[3 * k + 60:3 * k + 70] = 1e5
    ok = rng.random(n) < 0.92
    return ax, ay, bx, by, ok


def _both(*args, **kw):
    got = EdgeGrid(*args, **kw)
    saved = _native.native
    _native.native = None
    try:
        with np.errstate(all="ignore"):
            want = EdgeGrid(*args, **kw)
    finally:
        _native.native = saved
    return got, want


def _same(got, want):
    for s in SLOTS:
        g, w = getattr(got, s), getattr(want, s)
        if isinstance(w, np.ndarray):
            assert g.dtype == w.dtype, s
            assert np.array_equal(g, w), s
        else:
            assert type(g) is type(w) and g == w, s


@pytest.mark.parametrize("seed", range(6))
def test_the_bins_are_numpys(seed):
    rng = np.random.default_rng(seed)
    w, h = [(900.0, 640.0), (1400.0, 900.0), (31.0, 17.0), (3000.0, 2000.0),
            (900.0, 640.0), (640.0, 900.0)][seed]
    n = [5000, 30000, 300, 60000, 0, 1][seed]
    ax, ay, bx, by, ok = _segments(rng, max(n, 100), w, h)
    ax, ay, bx, by, ok = ax[:n], ay[:n], bx[:n], by[:n], ok[:n]
    for reach, cell, maxc in ((64.0, 32.0, 16), (8.0, 32.0, 16),
                              (64.0, 7.5, 3), (0.0, 32.0, 1),
                              (64.0, 32.0, 10 ** 6)):
        got, want = _both(ax, ay, bx, by, ok, w, h, reach, cell, maxc)
        _same(got, want)
        for px, py in ((0.0, 0.0), (w, h), (w / 2, h / 3), (17.3, h - 1)):
            for r in (None, 8.0, 64.0):
                a, b = got.near(px, py, r), want.near(px, py, r)
                assert (a is None) == (b is None)
                if a is not None:
                    assert np.array_equal(a, b)


def test_the_hover_grid_answers_as_before():
    """Through Viewport's own reader, the distances near the cursor."""
    rng = np.random.default_rng(11)
    ax, ay, bx, by, ok = _segments(rng, 40000, 900.0, 640.0)
    got, want = _both(ax, ay, bx, by, ok, 900.0, 640.0, 64.0)
    for px, py in rng.uniform((0, 0), (900, 640), (50, 2)):
        a, b = got.near(px, py, 8.0), want.near(px, py, 8.0)
        da = edge_grid._numpy_distances(ax, ay, bx, by, ok, px, py, a)
        db = edge_grid._numpy_distances(ax, ay, bx, by, ok, px, py, b)
        assert np.array_equal(a, b) and np.array_equal(da, db, equal_nan=True)
