# SPDX-License-Identifier: GPL-3.0-or-later
"""A clean corner reads «Endpoint», never «Intersection» (#357, @kellytait).

Edges that share a corner «intersect» at that corner. Between the endpoint
rule's 9 px and the edge threshold's 14 px the corner came back labelled
Intersection, and so did an extension that «crossed» its neighbour at its
own end. Same point either way, but it made users hunt for tracing errors
that were not there. Two guides that really cross still read Intersection."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D

from core.scene import Scene
from core.snap import compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _w2p(p):
    return (p.x() * 100.0, p.y() * 100.0)          # 100 px a metre


def _snap(scene, cand, **kw):
    return compute_snap(cand, _w2p(cand), scene, _w2p,
                        threshold_px=9.0, edge_threshold_px=14.0, **kw)


def _corner():
    """Three lines meeting at (5, 4): the steps in the report."""
    sc = Scene()
    sc.mesh.add_edge(V(0, 4), V(5, 4))
    sc.mesh.add_edge(V(5, 0), V(5, 4))
    sc.mesh.add_edge(V(5, 4), V(5, 8))
    return sc


@pytest.mark.parametrize("dx, dy", [(0.08, 0.08), (0.1, 0.05), (-0.07, 0.09),
                                    (0.12, -0.03), (0.03, 0.12)])
def test_near_a_clean_corner_it_is_the_endpoint(dx, dy):
    # 9-14 px from the corner: where «Intersection» used to show up.
    r = _snap(_corner(), V(5 + dx, 4 + dy))
    if r.kind in ("endpoint", "intersection"):
        assert r.kind == "endpoint"
        assert (r.point - V(5, 4)).length() < 1e-4


def test_heading_along_the_wall_into_the_corner_is_the_endpoint():
    r = _snap(_corner(), V(4.95, 4.02), start_point=V(2, 4))
    assert r.kind == "endpoint"
    assert (r.point - V(5, 4)).length() < 1e-4


def test_lines_that_really_cross_still_intersect():
    sc = Scene()
    sc.mesh.add_edge(V(0, 0), V(4, 4))
    sc.mesh.add_edge(V(0, 4), V(4, 0))
    r = _snap(sc, V(2.05, 2.05))
    assert r.kind == "intersection"
    assert (r.point - V(2, 2)).length() < 1e-4
