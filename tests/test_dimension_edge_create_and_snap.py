# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dimension from an edge in one click, and snapping to dimension lines.

The first Dimension click on an edge («on edge» snap) takes both corners of
that edge as the measured points, so the next click already places the
dimension line. A plain point click keeps the classic three clicks. And a
placed dimension's line is a snap target like any other edge — also in a
scene that holds nothing else."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace  # noqa: E402

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.dimension import Dimension  # noqa: E402
from core.history import History  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.snap import SnapResult, compute_snap  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.dimension import DimensionTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _StubVP:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass


def _ctx(vp, world, snap=None):
    return ToolContext(viewport=vp, world=world, screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=snap)


def _on_edge(point, a, b):
    return SnapResult(point, "on_edge", (0, 0, 0),
                      edge=SimpleNamespace(a=a, b=b))


# ---- Tool: one click on an edge ------------------------------------------------

def test_click_on_an_edge_takes_both_corners():
    scene = Scene()
    vp = _StubVP(scene)
    tool = DimensionTool()
    tool.on_click(_ctx(vp, V(1, 0, 0), _on_edge(V(1, 0, 0), V(0, 0, 0), V(4, 0, 0))))
    assert tool.a == V(0, 0, 0) and tool.b == V(4, 0, 0)
    assert tool.start_point == V(0, 0, 0)
    assert not scene.dimensions                     # still placing the line
    tool.on_click(_ctx(vp, V(2, 0, 3)))             # placement click
    assert len(scene.dimensions) == 1
    d = scene.dimensions[0]
    assert d.value() == 4.0
    assert d.a == V(0, 0, 0) and d.b == V(4, 0, 0)
    assert tool.a is None and tool.b is None        # reset for the next one


def test_the_edge_corners_are_copies():
    a, b = V(0, 0, 0), V(4, 0, 0)
    tool = DimensionTool()
    tool.on_click(_ctx(_StubVP(Scene()), V(1, 0, 0), _on_edge(V(1, 0, 0), a, b)))
    a.setX(9.0)                                     # the edge moves later
    assert tool.a == V(0, 0, 0)


def test_a_zero_length_edge_falls_back_to_the_point():
    tool = DimensionTool()
    p = V(2, 2, 0)
    tool.on_click(_ctx(_StubVP(Scene()), p, _on_edge(p, V(2, 2, 0), V(2, 2, 0))))
    assert tool.a == p and tool.b is None


def test_an_endpoint_snap_keeps_three_clicks():
    tool = DimensionTool()
    snap = SnapResult(V(0, 0, 0), "endpoint", (0, 0, 0),
                      edge=SimpleNamespace(a=V(0, 0, 0), b=V(4, 0, 0)))
    tool.on_click(_ctx(_StubVP(Scene()), V(0, 0, 0), snap))
    assert tool.a == V(0, 0, 0) and tool.b is None


def test_no_snap_keeps_three_clicks():
    tool = DimensionTool()
    tool.on_click(_ctx(_StubVP(Scene()), V(1, 1, 0), snap=None))
    assert tool.a == V(1, 1, 0) and tool.b is None


# ---- Snap engine: the on-edge result names its edge ----------------------------

def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)          # top view, 100 px a metre


def test_on_edge_snap_carries_the_edge():
    edge = SimpleNamespace(a=V(0, 0), b=V(10, 0), center=False)
    cand = V(3.3, 0.02)                             # far from corners and midpoint
    r = compute_snap(cand, _w2p(cand), SimpleNamespace(edges=[edge]), _w2p,
                     threshold_px=9.0, edge_threshold_px=14.0)
    assert r.kind == "on_edge"
    assert r.edge is edge


def test_dimension_line_points_properties():
    d = Dimension(V(0, 0, 0), V(4, 0, 0), V(0, 0, 2))
    assert (d.line_point_a, d.line_point_b) == d.line_points()


# ---- Viewport: dimension lines are snap targets --------------------------------

def _vp_with_dimension():
    vp = Viewport(None)
    vp.scene.dimensions.append(Dimension(V(0, 0, 0), V(10, 0, 0), V(0, 2, 0)))
    vp.scene.version += 1
    return vp


def _snap_near(vp, p):
    return compute_snap(p, _w2p(p), vp._snap_scene(), _w2p,
                        threshold_px=9.0, edge_threshold_px=14.0)


def test_a_dimension_line_is_in_the_snap_scene_on_its_own():
    # Only a dimension in the scene: the snap scene must not short-cut to
    # the bare scene (which has no edges) and lose the dimension line.
    vp = _vp_with_dimension()
    segs = [(e.a, e.b) for e in vp._snap_scene().edges]
    assert (V(0, 2, 0), V(10, 2, 0)) in segs


def test_the_cursor_snaps_onto_a_dimension_line():
    vp = _vp_with_dimension()
    r = _snap_near(vp, V(3.3, 2.03, 0))
    assert r.kind == "on_edge"
    assert abs(r.point.y() - 2.0) < 1e-6


def test_a_dimension_on_a_hidden_layer_does_not_snap():
    vp = _vp_with_dimension()
    vp.scene.entity_selectable = lambda e: False    # hidden / locked
    segs = [(e.a, e.b) for e in vp._snap_scene().edges]
    assert (V(0, 2, 0), V(10, 2, 0)) not in segs
