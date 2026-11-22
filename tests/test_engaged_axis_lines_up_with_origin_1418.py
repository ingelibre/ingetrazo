# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The axis the Line tool's magnet engaged still lines up with the origin
and the corners (#1418, @PedroE200).

«When drawing a line parallel to the green axis, the inference engine
loses the reference to the coordinate origin, so the endpoint cannot be
placed on the red axis.» His drawing: from the origin along green, then
along red, then back along green towards the red axis. Measured with the
Line tool in a perspective view, the cursor on the red axis:

    magnet engaged (no key)    axis         y = 0.055, 0.000 2, -0.048…
    green arrow lock           from_point   y = 0 exactly

The engaged axis silenced every derived linear inference — 'from point'
with them — so that none could pull the point off the line. A foot on the
axis line pulls nothing off it; the arrow lock always offered them.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.snap import compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


def _edge(a, b):
    return SimpleNamespace(a=a, b=b, center=False)


#: Origin → along green → along red; the line now runs back along green.
W, D = 6.0, 5.0
START = V(W, D)


def _snap(cand, edges, magnetic=3.0, start=START):
    def project(s, d):
        dd = QVector3D.dotProduct(d, d)
        return s + d * (QVector3D.dotProduct(cand - s, d) / dd)
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=list(edges)), world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=start,
        project_onto_line=project, magnetic_axis_deg=magnetic)


@pytest.mark.parametrize("y", [0.05, 0.0, -0.05])
@pytest.mark.parametrize("dx", [0.0, 0.04])
def test_the_engaged_axis_lands_on_the_red_axis(y, dx):
    edges = [_edge(V(0, 0), V(0, D)), _edge(V(0, D), V(W, D))]
    r = _snap(V(W + dx, y), edges)
    assert r.kind in ("from_point", "origin"), (r.kind, r.point)
    assert r.point.x() == pytest.approx(W, abs=1e-6)
    assert r.point.y() == pytest.approx(0.0, abs=1e-6)


def test_the_origin_alone_is_enough():
    """No geometry touching the origin: it is a reference of its own."""
    r = _snap(V(W + 0.04, 0.03), [_edge(V(2, D), V(W, D))])
    assert r.kind in ("from_point", "origin"), r.kind
    assert r.point.y() == pytest.approx(0.0, abs=1e-6)


def test_away_from_any_reference_the_axis_still_holds():
    """Halfway down, nothing to line up with: the plain axis, at the
    cursor's foot on the line."""
    edges = [_edge(V(0, 0), V(0, D)), _edge(V(0, D), V(W, D))]
    r = _snap(V(W + 0.04, 2.3), edges)
    assert r.kind == "axis" and r.axis == "y"
    assert r.point.x() == pytest.approx(W, abs=1e-6)
    assert r.point.y() == pytest.approx(2.3, abs=1e-6)


def test_a_corner_still_wins_over_its_own_foot():
    """A vertex under the cursor is a point inference above the line-up."""
    edges = [_edge(V(0, 0), V(0, D)), _edge(V(0, D), V(W, D)),
             _edge(V(W, 0), V(W + 1, 0))]
    r = _snap(V(W + 0.03, 0.02), edges)
    assert r.kind == "endpoint" and r.point == V(W, 0)


# ---- the same, through the viewport and the Line tool ---------------------

@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1400, 900)
    vp.camera.set_aspect(1400, 900)
    vp.flash_status = lambda *a, **k: None
    return vp


def test_the_line_tool_reaches_the_red_axis(viewport):
    from tools.base import ToolContext
    from tools.line import LineTool
    vp = viewport
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    cam = vp.camera
    cam.target = V(3, 2, 0)
    cam.distance = 18.0
    cam.yaw = math.radians(-35.0)
    cam.pitch = math.radians(30.0)
    tool = LineTool()
    vp.set_active_tool(tool)

    def hover(w, off=(0, 0)):
        px = vp._world_to_pixel(w)
        vp._process_hover(QPointF(px[0] + off[0], px[1] + off[1]),
                          Qt.NoModifier)
        return vp.last_snap

    for p in (V(0, 0), V(0, D), V(W, D)):
        s = hover(p)
        px = vp._world_to_pixel(p)
        tool.on_click(ToolContext(viewport=vp, world=s.point,
                                  screen=QPointF(*px),
                                  modifiers=Qt.NoModifier, snap=s))
    corner = QVector3D(tool.start_point)
    assert corner.y() == pytest.approx(D, abs=0.01)
    try:
        for y, off in ((0.0, (0, 0)), (0.0, (3, 2)), (0.04, (0, 0)),
                       (-0.04, (-2, 1))):
            s = hover(V(corner.x(), y), off)
            assert s.kind in ("from_point", "origin"), (y, off, s.kind, s.point)
            assert s.point.y() == pytest.approx(0.0, abs=1e-6), (y, off)
            assert s.point.x() == pytest.approx(corner.x(), abs=1e-6)
        # Halfway down the axis still runs the line along green.
        s = hover(V(corner.x(), 2.0))
        assert s.kind == "axis" and s.axis == "y", s.kind
    finally:
        tool.on_cancel(vp)
