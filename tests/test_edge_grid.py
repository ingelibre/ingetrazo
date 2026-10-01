# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The screen grid finds every edge the full pass would, within reach.

``core.edge_grid.EdgeGrid`` replaces, on big models, the per-move pass over
every group hard edge (``Viewport._gedge_dist``). It may hand back MORE
candidates than are within reach — never fewer: for random segments of
every kind (short, long across the view, partly or wholly off screen,
behind the camera, degenerate) and cursors all over the view, the edges
within reach and their distances are exactly the full pass's.

Headless: NumPy only.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.edge_grid import EdgeGrid, segment_distances

W, H = 1600.0, 900.0


def _segments(rng, n):
    ax = rng.uniform(-400, W + 400, n)
    ay = rng.uniform(-400, H + 400, n)
    # Mostly short edges (a model seen whole), some long, some points.
    length = np.where(rng.random(n) < 0.9, rng.exponential(12.0, n),
                      rng.uniform(100, 2500, n))
    length[rng.random(n) < 0.02] = 0.0
    ang = rng.uniform(0, 2 * np.pi, n)
    bx = ax + length * np.cos(ang)
    by = ay + length * np.sin(ang)
    ok = rng.random(n) > 0.05                       # behind the camera
    return ax, ay, bx, by, ok


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("reach", [8.0, 48.0, 64.0])
def test_grid_misses_nothing_within_reach(seed, reach):
    rng = np.random.default_rng(seed)
    ax, ay, bx, by, ok = _segments(rng, 40000)
    grid = EdgeGrid(ax, ay, bx, by, ok, W, H, reach)
    full_cursors = np.column_stack([rng.uniform(0, W, 200),
                                    rng.uniform(0, H, 200)])
    corners = np.array([[0, 0], [W, H], [0, H], [W, 0], [W / 2, 0]])
    for px, py in np.vstack([full_cursors, corners]):
        full = segment_distances(ax, ay, bx, by, ok, px, py)
        near = grid.near(px, py)
        want = set(np.flatnonzero(full < reach).tolist())
        assert want <= set(near.tolist())
        got = segment_distances(ax, ay, bx, by, ok, px, py, near)
        np.testing.assert_array_equal(got, full[near])


def test_grid_reads_few_cells():
    # What it is for: a cursor reads the edges near it, not all of them
    # (here 10 % of the edges are long ones every query reads).
    rng = np.random.default_rng(7)
    ax, ay, bx, by, ok = _segments(rng, 200000)
    grid = EdgeGrid(ax, ay, bx, by, ok, W, H, 64.0)
    sizes = [len(grid.near(px, py)) for px, py in
             zip(rng.uniform(0, W, 50), rng.uniform(0, H, 50))]
    assert np.median(sizes) < 0.25 * len(ax)


def test_cursor_outside_the_view_falls_back():
    rng = np.random.default_rng(3)
    ax, ay, bx, by, ok = _segments(rng, 1000)
    grid = EdgeGrid(ax, ay, bx, by, ok, W, H, 48.0)
    assert grid.near(-5.0, 10.0) is None
    assert grid.near(10.0, H + 1.0) is None


def test_no_segments_on_screen():
    z = np.zeros(0)
    grid = EdgeGrid(z, z, z, z, np.zeros(0, bool), W, H, 48.0)
    assert len(grid.near(100.0, 100.0)) == 0


# ---- the viewport's contract with its two readers -------------------------

class _StubVP:
    """Just what ``Viewport._gedge_dist`` reads."""
    pick_threshold_px = 8.0

    def __init__(self, proj):
        self._proj = proj

    def _gedge_screen(self):
        return self._proj

    def width(self):
        return int(W)

    def height(self):
        return int(H)


@pytest.mark.parametrize("density", ["sparse", "dense"])
def test_viewport_readers_see_what_the_full_pass_sees(density):
    from views.viewport import Viewport
    rng = np.random.default_rng(5)
    n = 60000
    assert n >= Viewport.GEDGE_GRID_MIN
    if density == "dense":
        # The whole city in view: tiny edges packed into a patch of the
        # screen, hundreds within the near radius of any cursor in it.
        ax = rng.uniform(600, 900, n)
        ay = rng.uniform(300, 500, n)
        ang = rng.uniform(0, 2 * np.pi, n)
        ln = rng.exponential(2.0, n)
        proj = (ax, ay, ax + ln * np.cos(ang), ay + ln * np.sin(ang),
                np.ones(n, bool))
        cursors = zip(rng.uniform(600, 900, 40), rng.uniform(300, 500, 40))
    else:
        proj = _segments(rng, n)
        cursors = zip(rng.uniform(0, W, 40), rng.uniform(0, H, 40))
    vp = _StubVP(proj)
    for px, py in cursors:
        full = segment_distances(*proj, px, py)
        Viewport._gedge_dist(vp, px + 5.0, py)     # a first hover: no grid yet
        d = Viewport._gedge_dist(vp, px, py)
        assert getattr(vp, "_gedge_grid_cache", (None, None))[1] is not None
        # The hovered-edge pick: argmin under pick_threshold_px.
        i, j = int(np.argmin(d)), int(np.argmin(full))
        assert (d[i] < vp.pick_threshold_px) == (full[j] < vp.pick_threshold_px)
        if full[j] < vp.pick_threshold_px:
            assert d[i] == full[j]
        # The snap prefilter: the GEDGE_ENOUGH nearest within 48 px.
        def nearest(dist):
            c = np.flatnonzero(dist < 48.0)
            return np.sort(dist[c])[:Viewport.GEDGE_ENOUGH]
        np.testing.assert_array_equal(nearest(d), nearest(full))
