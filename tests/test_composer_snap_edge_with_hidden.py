# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet snapping, where a point along an edge (#1219) meets the hidden
vertices of a see-through frame: one order for both — a drawn point, then a
hidden one, then a point along a DRAWN edge."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from tests.test_composer_snap_hidden_and_lines import _box_composer


def _wireframe():
    composer, frame = _box_composer()
    frame.style = "style:Wireframe"
    composer.edge_snap_cache.clear()
    return composer, frame


def test_a_point_along_an_edge_keeps_to_the_drawn_edges():
    composer, frame = _wireframe()
    pts, world = composer.frame_snap_points(frame)
    assert 3.0 in {round(float(w[1]), 6) for w in world}   # hidden POINTS
    _page, edge_world, _depth = composer.frame_snap_edges(frame)
    assert len(edge_world)
    assert not np.isclose(edge_world[:, :, 1], 3.0).any()  # no hidden EDGE
    # the edges the points pass leaves and the ones built on demand agree
    seeded = composer.edge_snap_cache[id(frame)][1][0]
    composer.edge_snap_cache.clear()
    built = composer.frame_snap_edges(frame)[0]
    assert sorted(map(tuple, np.round(seeded, 6))) == sorted(
        map(tuple, np.round(built, 6)))


def test_an_edge_still_catches_in_a_see_through_frame():
    composer, frame = _wireframe()
    (x0, y0), (x1, y1) = (composer._frame_world_to_page(
        frame, [(0.0, 0.0, 0.0), (6.0, 0.0, 0.0)]))
    # a quarter along the big box's bottom edge: no point within 1 mm
    x, y = x0 + 0.25 * (x1 - x0), y0 + 0.25 * (y1 - y0)
    hit = composer.nearest_snap_point(x, y + 0.4, 1.0)
    assert hit is not None and hit.on_edge
    assert abs(hit[2][0] - 1.5) < 1e-6 and hit[2][1] == 0.0
    assert composer.nearest_snap_point(x, y + 0.4, 1.0, edges=False) is None


def test_a_hidden_point_beats_a_point_along_an_edge():
    composer, frame = _wireframe()
    pts, _world = composer.frame_snap_points(frame)
    nv = composer.frame_snap_visible(frame)
    hx, hy = pts[nv]
    hit = composer.nearest_snap_point(float(hx), float(hy), 0.5)
    assert hit[2][1] == 3.0 and not getattr(hit, "on_edge", False)
