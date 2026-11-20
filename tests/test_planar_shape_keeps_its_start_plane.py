# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A shape started on a free point keeps the plane of its first click
after the cursor merely crosses a face (0.6.3 modelling test, 20-11).

A rectangle started on the ground in front of a box, the cursor taken over
the box's corner to acquire it: the corner pixel lies on the front face,
and the viewport, rightly, laid the point on that face (#545). But the
tool's live ``hover_plane`` took the face's normal with it, and the
viewport read the free shape's plane from there: back on the ground, the
cursor's point came off a VERTICAL plane through the first corner (z =
2.275 m in the report) and the «From point» to the box's corner was lost.
The face is the shape's plane only while the cursor is on it.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _scene():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1200, 800)
    _app.processEvents()
    vp = win.viewport
    p = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0),
         V(0, 0, 2), V(2, 0, 2), V(2, 2, 2), V(0, 2, 2)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        vp.scene.mesh.add_face([p[i] for i in loop])
    vp.camera.set_view("iso")
    vp.scene.version += 1
    _app.processEvents()
    return win, vp


def _hover(vp, world):
    px, py = vp._world_to_pixel(world)
    vp._last_mouse_pos = QPointF(px, py)
    vp._refresh_snap()
    return px, py


def _press(vp, px, py):
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


@pytest.mark.parametrize("tool", ["rectangle", "circle"])
def test_crossing_a_face_leaves_the_start_plane_alone(tool):
    win, vp = _scene()
    try:
        win._activate_tool(tool)
        _app.processEvents()
        _press(vp, *_hover(vp, V(1.0, -1.5, 0.0)))   # free point, ground
        _app.processEvents()
        t = vp.active_tool
        assert t.start_point is not None and t.work_plane is None
        assert abs(t.start_point.z()) < 1e-3

        # Over the front wall (y = 0): the point is on the wall (#545).
        px, py = _hover(vp, V(1.0, 0.0, 1.0))
        face, _grp = vp.pick_face_any(px, py)
        assert face is not None, "the test is not over the wall"
        snap = vp.inference.snap(px, py, Qt.NoModifier)
        assert snap is not None and abs(snap.point.y()) < 1e-3

        # Back on the open ground: the ground again, not a vertical plane
        # through the first point with the wall's normal.
        px, py = _hover(vp, V(2.8, -1.0, 0.0))
        assert vp.pick_face_any(px, py)[0] is None
        snap = vp.inference.snap(px, py, Qt.NoModifier)
        assert snap is not None
        assert abs(snap.point.z()) < 1e-3, (
            f"the point stood up off the ground: {snap.point}")
        normal = QVector3D(t.drawing_plane()[1]).normalized()
        assert abs(normal.z()) > 0.999, f"the shape's plane is {normal}"
    finally:
        win._saved_version = vp.scene.version
        win.close()
