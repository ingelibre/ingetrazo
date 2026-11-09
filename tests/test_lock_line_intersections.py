# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«Constrained on line / plane»: a direction lock meets the hovered edge/face.

With a lock holding (arrow, Shift lock, reference lock), the edge under the
cursor offers the point where the lock line meets that edge's INFINITE line
(``intersection_edge``), and the face under it the point where the lock line
pierces its PLANE (``intersection_face``) - automatically, wherever the
cursor is on the edge / face. An edge wins over a face; points the lock
already finds (vertices, crossings, 'from point') come first.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D

from core.snap import compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


START = V(0, 0, 0)
PLANE = (V(6, 0, 0), V(1, 0, 0), V(6, 2, 0))        # the plane x = 6
EDGE = SimpleNamespace(a=V(6, 1), b=V(6, 3), center=False)   # on x = 6


def _snap(cand, scene_edges=(), **kw):
    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)
    kw.setdefault("axis_lock", "x")
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=list(scene_edges)), world_to_pixel=_w2p,
        threshold_px=9.0, start_point=START, project_onto_line=project, **kw)


def test_the_cursor_on_an_edge_offers_the_meeting_with_its_line():
    r = _snap(V(6.0, 2.0), hover_lock_edge=EDGE)      # far from the meeting
    assert r.kind == "intersection_edge"
    assert r.point.x() == pytest.approx(6.0, abs=1e-6)
    assert r.point.y() == pytest.approx(0.0, abs=1e-6)
    a, b = r.guide                      # the dotted extension, from the edge
    assert (a - V(6, 1)).length() < 1e-6 and (b - r.point).length() < 1e-6


def test_the_cursor_on_a_face_offers_the_meeting_with_its_plane():
    r = _snap(V(6.0, 2.0), hover_lock_plane=PLANE)
    assert r.kind == "intersection_face"
    assert r.point.x() == pytest.approx(6.0, abs=1e-6)
    assert r.point.y() == pytest.approx(0.0, abs=1e-6)
    assert (r.guide[0] - V(6, 2, 0)).length() < 1e-6


def test_the_edge_body_does_not_beat_the_meeting_with_its_line():
    """Cursor over the middle of an edge, lock holding: the arbitrary
    'from point' on the edge body must yield to the edge intersection."""
    edge = SimpleNamespace(a=V(6, 1), b=V(6, 5), center=False)
    r = _snap(V(6.0, 2.0), hover_lock_edge=edge,
              scene_edges=[edge])
    assert r.kind == "intersection_edge"
    assert r.point.y() == pytest.approx(0.0, abs=1e-6)


def test_an_edge_wins_over_a_face():
    r = _snap(V(6.0, 2.0), hover_lock_edge=EDGE, hover_lock_plane=PLANE)
    assert r.kind == "intersection_edge"


def test_without_a_hover_it_is_a_plain_lock():
    assert _snap(V(6.0, 2.0)).kind == "axis"


def test_a_plane_parallel_to_the_lock_is_never_met():
    plane = (V(0, 2, 0), V(0, 1, 0), V(0, 2, 0))        # y = 2, lock along x
    assert _snap(V(3.0, 2.0), hover_lock_plane=plane).kind == "axis"


def test_a_skew_edge_is_not_met():
    edge = SimpleNamespace(a=V(6, 1, 5), b=V(6, 3, 5), center=False)
    assert _snap(V(6.0, 2.0), hover_lock_edge=edge).kind == "axis"


def test_the_meeting_behind_the_start_counts_too():
    plane = (V(-4, 0, 0), V(1, 0, 0), V(-4, 2, 0))
    r = _snap(V(6.0, 2.0), hover_lock_plane=plane)
    assert r.kind == "intersection_face"
    assert r.point.x() == pytest.approx(-4.0, abs=1e-6)


def test_the_shift_lock_gets_it_too():
    cand = V(6.0, 2.0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)
    r = compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=[]), world_to_pixel=_w2p,
        threshold_px=9.0, start_point=START, project_onto_line=project,
        shift_lock_dir=V(1, 0, 0), hover_lock_plane=PLANE)
    assert r.kind == "intersection_face"


def test_a_vertex_on_the_lock_line_still_wins():
    corner = SimpleNamespace(a=V(4, 0), b=V(4, 2), center=False)
    cand = V(4.0, 0.0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)
    r = compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=[corner]), world_to_pixel=_w2p,
        threshold_px=9.0, start_point=START, project_onto_line=project,
        axis_lock="x", hover_lock_plane=PLANE)
    assert r.kind == "endpoint"
