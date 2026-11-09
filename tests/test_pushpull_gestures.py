# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull as a press-drag-release stroke, through the viewport's own
mouse dispatch: a real QMouseEvent press starts the drag, real move frames
build the extrusion, and the RELEASE commits it (Fix 1's wiring test — the
tool-level behaviour lives in test_pushpull_ux.py).

Headless: offscreen MainWindow, the scene/camera of
test_pushpull_click_on_the_cap.py (a ground-level camera over a ground
rectangle, where climbing the screen pulls the face up by metres), and the
QMouseEvent synthesis of test_orbit_pivot.py.
"""
from __future__ import annotations

import math
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

# The viewport coalesces hovers (a move is processed at most once per
# min(60 ms, 1.5x the last hover's cost)); sleeping past that gate makes
# each mouseMoveEvent deliver its hover synchronously, as a real hand's
# spaced-out moves arrive.
_HOVER_GATE_S = 0.08


def _ev(kind, x, y, button, buttons):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons,
                       Qt.NoModifier)


def _press(x, y):
    return _ev(QMouseEvent.MouseButtonPress, x, y, Qt.LeftButton,
               Qt.LeftButton)


def _move(x, y):
    return _ev(QMouseEvent.MouseMove, x, y, Qt.NoButton, Qt.LeftButton)


def _release(x, y):
    return _ev(QMouseEvent.MouseButtonRelease, x, y, Qt.LeftButton,
               Qt.NoButton)


def _ground_level_scene():
    """Rafael's setup (test_pushpull_click_on_the_cap): camera 6 deg above
    the ground looking along the model, an 8 x 5 rectangle on it, Push/Pull
    engaged — a face whose normal faces the camera, so vertical screen
    motion builds extrusion."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1600, 900)
    _app.processEvents()
    vp = win.viewport
    cam = vp.camera
    cam.target = QVector3D(4, 2.5, 0)
    cam.distance = 18.0
    cam.pitch = math.radians(6.0)
    cam.yaw = math.radians(-60.0)
    face = vp.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(8, 0, 0),
                                   QVector3D(8, 5, 0), QVector3D(0, 5, 0)])
    vp.scene.version += 1
    vp.update()
    _app.processEvents()
    win._activate_tool("pushpull")
    return win, vp, face


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _engage(vp, face):
    """Hover the rectangle, then a real left press starts the drag."""
    tool = vp.active_tool
    cx, cy = vp._world_to_pixel(QVector3D(4, 2.5, 0))
    vp._last_mouse_pos = QPointF(cx, cy)
    vp._process_hover(QPointF(cx, cy), Qt.NoModifier)
    assert tool.hovered_face is face
    vp.mousePressEvent(_press(cx, cy))
    assert tool.dragging is True
    return tool, cx, cy


def test_press_drag_release_through_the_viewport_commits():
    win, vp, face = _ground_level_scene()
    try:
        tool, cx, cy = _engage(vp, face)
        depth = len(vp.history.undo_stack)

        # Climb the screen in real move frames: 400 px of motion — metres
        # of extrusion (the same geometry the cap test pulls past the
        # horizon).
        for dy in (60, 160, 280, 400):
            time.sleep(_HOVER_GATE_S)
            vp.mouseMoveEvent(_move(cx, cy - dy))
        assert tool.extrusion > 3.0, tool.extrusion

        vp.mouseReleaseEvent(_release(cx, cy - 400))

        assert not tool.dragging                    # the stroke committed
        assert len(vp.history.undo_stack) == depth + 1
        assert len(vp.scene.mesh.faces) == 6        # a box, not a sheet
        top = max(v.position.z() for v in vp.scene.mesh.vertices)
        assert top > 3.0, top
    finally:
        _close(win)


def test_stationary_press_release_does_not_commit():
    win, vp, face = _ground_level_scene()
    try:
        tool, cx, cy = _engage(vp, face)
        depth = len(vp.history.undo_stack)
        faces = len(vp.scene.mesh.faces)

        vp.mouseReleaseEvent(_release(cx, cy))      # released where pressed

        assert tool.dragging is True                # a click, not a stroke
        assert len(vp.history.undo_stack) == depth
        assert len(vp.scene.mesh.faces) == faces    # the drag is still open
    finally:
        _close(win)
