# SPDX-License-Identifier: GPL-3.0-or-later
"""A hidden edge must not lend a lock its height (#1085).

With Z locked from a box's top corner and the cursor moving straight up,
the box's FAR vertical edge — hidden behind the box itself — projects
onto the very screen line the cursor travels. The edge-body 'from point'
took the point of that edge under the cursor (three quarters up the far
edge) and landed the locked point BELOW the start, at that height,
instead of above it where the cursor was heading.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _box(vp):
    from core.edits import build_add_edges
    sc = vp.scene
    sc.mesh.clear()
    vp.history.undo_stack.clear()
    bot = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]
    top = [V(0, 0, 2), V(2, 0, 2), V(2, 2, 2), V(0, 2, 2)]
    segs = [(sq[i], sq[(i + 1) % 4]) for sq in (bot, top) for i in range(4)]
    segs += [(bot[i], top[i]) for i in range(4)]
    vp.history.execute(build_add_edges(sc, segs))
    assert len(sc.mesh.faces) == 6
    return sc


def test_dragging_up_from_the_top_corner_goes_up(viewport):
    from tools.line import LineTool
    vp = viewport
    _box(vp)
    vp.camera.target = V(1, 1, 1)
    vp.camera.distance = 9
    vp.camera.yaw = math.radians(45)
    vp.camera.pitch = math.radians(35)
    corner = V(2, 2, 2)
    # The trap is real in this view: the far edge is hidden, and its
    # projection passes through the cursor's screen position.
    assert vp._is_occluded(V(0, 0, 1.0))
    tool = LineTool()
    vp.set_active_tool(tool)
    tool.start_point = V(corner)
    vp.axis_lock = "z"
    try:
        pa = vp._world_to_pixel(corner)
        assert pa is not None
        vp._process_hover(QPointF(pa[0], pa[1] - 120), Qt.NoModifier)
        snap = vp.last_snap
        assert snap is not None
        assert snap.kind == "axis"
        assert snap.point.z() > corner.z()
    finally:
        vp.axis_lock = None
