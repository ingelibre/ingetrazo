# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A guide, a line or an arc facet that pierces the face under the cursor
snaps as «Intersection» (``core.snap._edge_face_snap``). Before, only edge
with edge and face with face crossings were offered."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector3D as V

from core.snap import compute_snap

# The floor z = 0, a square of 4 with a 1x1 hole in the middle.
OUTER = [V(-2, -2, 0), V(2, -2, 0), V(2, 2, 0), V(-2, 2, 0)]
HOLE = [V(-0.5, -0.5, 0), V(0.5, -0.5, 0), V(0.5, 0.5, 0), V(-0.5, 0.5, 0)]


def _w2p(p):
    # An oblique view, so a vertical edge does not collapse to a point.
    return (p.x() * 100.0 + p.z() * 30.0, p.y() * 100.0 + p.z() * 60.0)


def _edge(a, b, guide=False):
    return SimpleNamespace(a=a, b=b, guide=guide)


def _snap(edge, cursor, holes=(), outline=True, **kw):
    scene = SimpleNamespace(edges=[edge])
    out = (lambda: (OUTER, list(holes), "group")) if outline else None
    return compute_snap(
        candidate_world=cursor, candidate_pixel=_w2p(cursor), scene=scene,
        world_to_pixel=_w2p, threshold_px=9.0, edge_threshold_px=14.0,
        face_under_cursor=True, face_outline=out, **kw)


def test_a_vertical_line_through_the_face_gives_the_intersection():
    line = _edge(V(1, 1, -1), V(1, 1, 1))
    r = _snap(line, V(1.0, 1.0, 0.0))
    assert r.kind == "intersection"
    assert (r.point - V(1, 1, 0)).length() < 1e-6
    assert r.context == "group"


def test_a_guide_line_through_the_face_gives_the_intersection():
    guide = _edge(V(1, 1, -50), V(1, 1, 50), guide=True)
    r = _snap(guide, V(1.0, 1.0, 0.0))
    assert r.kind == "intersection"
    assert (r.point - V(1, 1, 0)).length() < 1e-6


def test_an_arc_facet_through_the_face_gives_the_intersection():
    facet = _edge(V(-1, 1, -0.3), V(-1.2, 1.1, 0.4))
    hit = facet.a + (facet.b - facet.a) * (0.3 / 0.7)
    r = _snap(facet, V(hit.x(), hit.y(), 0.0))
    assert r.kind == "intersection"
    assert abs(r.point.z()) < 1e-6


def test_a_crossing_outside_the_face_or_inside_a_hole_is_ignored():
    outside = _edge(V(3, 3, -1), V(3, 3, 1))
    assert _snap(outside, V(3.0, 3.0, 0.0)).kind != "intersection"
    inside_hole = _edge(V(0, 0, -1), V(0, 0, 1))
    r = _snap(inside_hole, V(0.0, 0.0, 0.0), holes=[HOLE])
    assert r.kind != "intersection"


def test_an_edge_stopping_short_of_the_plane_is_ignored():
    short = _edge(V(1, 1, 0.5), V(1, 1, 2))
    assert _snap(short, V(1.0, 1.0, 0.0)).kind != "intersection"


def test_an_edge_lying_in_the_plane_has_no_single_crossing():
    flat = _edge(V(-1, 1, 0), V(1, 1, 0))
    assert _snap(flat, V(0.3, 1.0, 0.0)).kind != "intersection"


def test_a_crossing_far_from_the_cursor_is_ignored():
    line = _edge(V(1, 1, -1), V(1, 1, 1))
    assert _snap(line, V(1.0, 1.0, 1.0)).kind != "intersection"


def test_without_a_face_outline_nothing_changes():
    line = _edge(V(1, 1, -1), V(1, 1, 1))
    assert _snap(line, V(1.0, 1.0, 0.0), outline=False).kind != "intersection"


def test_a_hidden_crossing_is_not_offered():
    line = _edge(V(1, 1, -1), V(1, 1, 1))
    r = _snap(line, V(1.0, 1.0, 0.0), is_occluded=lambda p: True)
    assert r.kind != "intersection"
