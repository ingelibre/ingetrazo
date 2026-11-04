# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An axis the Line crossed on its way does not hold the cursor afterwards.

The magnet engages inside its own 3° cone and lets go outside it. Holding it
wider takes every derived inference away inside the wider cone: heading for
an edge or a face just off the axis gave the axis, and a free line a few
degrees off could no longer be drawn once the cursor had passed over the axis.
Driven through the real hover path, because the state lives between hovers.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from tools.line import LineTool  # noqa: E402
from views.viewport import Viewport, _HoverEvent  # noqa: E402


def _vp():
    vp = Viewport(None)
    vp.resize(1400, 850)
    vp.camera.set_aspect(1400, 850)
    vp.flash_status = lambda *a, **k: None
    vp.camera.yaw = math.radians(-35.0)
    vp.camera.pitch = math.radians(35.0)
    vp.camera.target = V(2, 0, 0)
    vp.camera.distance = 16.0
    return vp


def _hover(vp, p):
    x, y = vp._world_to_pixel(p)
    vp._process_hover(QPointF(x, y), Qt.NoModifier)
    return vp.last_snap


def _line_along_x(vp):
    t = LineTool()
    vp.active_tool = t
    t.on_activate(vp)
    x, y = vp._world_to_pixel(V(0, 0, 0))
    _hover(vp, V(0, 0, 0))
    t.on_click(vp._build_ctx(_HoverEvent(QPointF(x, y), Qt.NoModifier)))
    assert _hover(vp, V(1, 0, 0)).kind == "axis"
    assert _hover(vp, V(1.4, 0, 0)).kind == "axis"


def test_an_edge_just_off_the_axis_is_still_on_edge():
    vp = _vp()
    vp.scene.mesh.add_edge(V(4, -5, 0), V(4, 5, 0))
    _line_along_x(vp)
    r = _hover(vp, V(4, 1, 0))                 # 14° off X
    assert r.kind == "on_edge"
    assert abs(r.point.y() - 1.0) < 0.02


def test_a_face_just_off_the_axis_is_still_on_face():
    vp = _vp()
    vp.scene.mesh.add_face([V(2, 0.1, 0), V(5, 0.1, 0),
                            V(5, 3, 0), V(2, 3, 0)])
    _line_along_x(vp)
    assert _hover(vp, V(4, 0.7, 0)).kind == "on_face"      # 10° off X


def test_a_free_line_ten_degrees_off_the_axis_stays_free():
    vp = _vp()
    _line_along_x(vp)
    r = _hover(vp, V(3, 3 * math.tan(math.radians(10)), 0))
    assert r.kind == "none"
    assert r.point.y() > 0.4


def test_a_move_over_a_face_lands_on_it_not_on_a_reference_in_the_air():
    """The 3D reading of a reference is for drawing (#1095). What Move carries
    goes onto the face under the cursor, also where the axis line of a corner
    passes in front of that face on screen."""
    from tools.move import MoveTool

    vp = _vp()
    vp.scene.mesh.add_face([V(-20, 5, -5), V(20, 5, -5),
                            V(20, 5, 10), V(-20, 5, 10)])
    vp.scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0.5, 0), V(0, 0.5, 0)])
    t = MoveTool()
    vp.active_tool = t
    t.on_activate(vp)
    x, y = vp._world_to_pixel(V(0.5, 0.25, 0))
    vp._process_hover(QPointF(x, y), Qt.NoModifier)
    t.on_click(vp._build_ctx(_HoverEvent(QPointF(x, y), Qt.NoModifier)))
    ref = V(-2, 0, 3)
    vp.inference._acquired_point = ref
    vp.inference._encouraged = [V(ref)]
    r = _hover(vp, ref + V(1, 0, 0))           # floats 5 m before the wall
    assert r.kind == "on_face"
    assert abs(r.point.y() - 5.0) < 1e-3
