# SPDX-License-Identifier: GPL-3.0-or-later
"""The perpendicular lock of rule 4b yields to an edge under the cursor (#544).

A line started on a corner is "square to the wall you started on" whenever it
runs within 8 degrees of that wall's perpendicular, which from a corner is the
adjacent edge itself. A tapered leg - the line from the top corner of a tall
rectangle to a point of its bottom edge - runs about 8 degrees off vertical:
the lock pulled the point 27 px off the bottom edge, onto the right edge, and
the trapezoid could not be drawn from that corner.
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector3D

from core.snap import compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _edge(a, b):
    return SimpleNamespace(a=a, b=b, center=False)


def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


def _project(cand):
    def project(s, d):
        dd = QVector3D.dotProduct(d, d)
        return s + d * (QVector3D.dotProduct(cand - s, d) / dd)
    return project


def _snap(cand, edges, start):
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=edges), world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=start,
        project_onto_line=_project(cand))


def _rectangle(w, h):
    a, b, c, d = V(0, 0), V(w, 0), V(w, h), V(0, h)
    return [_edge(a, b), _edge(b, c), _edge(c, d), _edge(d, a)]


def test_a_point_on_an_edge_under_the_cursor_beats_the_lock_from_a_corner():
    edges = _rectangle(4.0, 7.2)
    snap = _snap(V(3.0, 0.0), edges, start=V(4.0, 7.2))
    assert snap.kind == "on_edge"
    assert (snap.point - V(3.0, 0.0)).length() < 1e-5


def test_the_lock_still_holds_with_no_edge_under_the_cursor():
    edges = _rectangle(4.0, 7.2)
    snap = _snap(V(3.6, 3.0), edges, start=V(4.0, 7.2))
    assert snap.kind == "reference"


def test_the_edge_you_started_on_does_not_cancel_the_lock():
    edges = _rectangle(4.0, 7.2)
    snap = _snap(V(4.0 - 0.05, 3.0), edges, start=V(4.0, 7.2))
    assert snap.kind != "on_edge"
    assert abs(snap.point.x() - 4.0) < 1e-5
