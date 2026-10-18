# SPDX-License-Identifier: GPL-3.0-or-later
"""Push/Pull measures the drag from the clicked spot, not the centroid.

The pull was read off the line through the face's centroid. On a 12 × 7.32
slab clicked near a corner, lifting the cursor 0.3 m read -3.39 m; on a ring
the centroid lies in the hole and 1 m of cursor gave 0.13 m walls (tutorial
hunt 2, A13/B5). The cursor now rides the line through the click.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _window(target, distance):
    from views.main_window import MainWindow
    win = MainWindow()
    win._confirm_discard = lambda *a, **k: True   # never a modal on close
    win.show()
    win.resize(1600, 900)
    _app.processEvents()
    cam = win.viewport.camera
    cam.target = target
    cam.distance = distance
    cam.pitch = math.radians(30.0)
    cam.yaw = math.radians(-50.0)
    return win, win.viewport


def _event(vp, px, py):
    vp._last_mouse_pos = QPointF(px, py)
    return QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(px, py),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def _pull(win, vp, at, rise):
    """Click the face at ``at``, move the cursor to ``rise`` m above it."""
    vp.scene.version += 1
    vp.update()
    _app.processEvents()
    win._activate_tool("pushpull")
    tool = vp.active_tool
    px, py = vp._world_to_pixel(at)
    vp._process_hover(QPointF(px, py), Qt.NoModifier)
    vp._dispatch_tool_click(_event(vp, px, py))
    assert tool.dragging
    qx, qy = vp._world_to_pixel(at + V(0, 0, rise))
    vp._process_hover(QPointF(qx, qy), Qt.NoModifier)
    return tool.extrusion


def test_a_pull_clicked_near_a_slab_corner_follows_the_cursor():
    win, vp = _window(V(6, 3.66, 0), 22.0)
    try:
        vp.scene.mesh.add_face([V(0, 0, 0), V(12, 0, 0), V(12, 7.32, 0),
                                V(0, 7.32, 0)])
        got = _pull(win, vp, V(0.4, 0.4, 0), 0.3)
        assert abs(got - 0.3) < 0.03, got
    finally:
        win.close()


def test_a_ring_pulled_one_metre_rises_one_metre():
    win, vp = _window(V(0, 0, 0), 14.0)
    try:
        outer = [V(-2, -2, 0), V(2, -2, 0), V(2, 2, 0), V(-2, 2, 0)]
        hole = [V(-1.8, -1.8, 0), V(-1.8, 1.8, 0), V(1.8, 1.8, 0),
                V(1.8, -1.8, 0)]
        vp.scene.mesh.add_face(outer, [hole])
        got = _pull(win, vp, V(1.9, 0, 0), 1.0)
        assert abs(got - 1.0) < 0.05, got
    finally:
        win.close()
