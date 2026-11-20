# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The axis the magnet engaged wins over the foot of some edge's midpoint
(0.6.3 modelling test, 20-11).

Rule 9a (#1418) lets the engaged axis line up with a corner or the origin:
their foot on the axis line is offered as 'from point'. It also took every
edge's MIDPOINT, and that foot came back as kind ``midpoint`` — a line drawn
along green from the ground read «Midpoint» 13 cm off the cursor, lined up
with the middle of an edge 5.5 m away, where 0.6.2.1 showed the green axis.
The foot is no midpoint. The axis wins; the midpoint itself, under the
cursor, is still a point snap; a corner still lines up (#1418's own tests).
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


def _edge(a, b):
    return SimpleNamespace(a=a, b=b, center=False)


START = V(0.0, 0.0)
#: Far to the side of the green line; its corners line up 50 px away from
#: the cursor, its midpoint (5, 2) right beside it.
FAR_EDGE = _edge(V(5.0, 1.5), V(5.0, 2.5))


def _snap(cand, edges, start=START):
    def project(s, d):
        dd = QVector3D.dotProduct(d, d)
        return s + d * (QVector3D.dotProduct(cand - s, d) / dd)
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=list(edges)), world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=start,
        project_onto_line=project, magnetic_axis_deg=3.0)


@pytest.mark.parametrize("y", [1.96, 2.0, 2.04])
def test_the_green_axis_is_not_taken_by_a_midpoints_foot(y):
    r = _snap(V(0.02, y), [FAR_EDGE])
    assert r.kind == "axis" and r.axis == "y", (r.kind, r.point)
    assert r.point.x() == pytest.approx(0.0, abs=1e-6)
    assert r.point.y() == pytest.approx(y, abs=1e-6)     # at the cursor


def test_the_midpoint_under_the_cursor_is_still_a_midpoint():
    r = _snap(V(5.02, 2.01), [FAR_EDGE])
    assert r.kind == "midpoint", r.kind
    assert r.point == V(5.0, 2.0)


def test_a_corner_still_lines_up_with_the_engaged_axis():
    r = _snap(V(0.02, 2.47), [FAR_EDGE])
    assert r.kind == "from_point", (r.kind, r.point)
    assert r.point.x() == pytest.approx(0.0, abs=1e-6)
    assert r.point.y() == pytest.approx(2.5, abs=1e-6)
