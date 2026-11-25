# SPDX-License-Identifier: GPL-3.0-or-later
"""A face of 1 mm can be picked and pushed (#1294).

The ray/triangle test refused |det| < 1e-6, but det is (e1 × e2)·d: it
shrinks with the triangle's area. A 1 mm square met head-on has det ≈ 6e-7,
so no tool found it under the cursor, however close the camera came. A
small det is now read against the triangle's own size — the angle between
the ray and its plane — and grazing rays are still refused."""
from __future__ import annotations

import math
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from views.viewport import (Viewport, _moller_trumbore,  # noqa: E402
                            _ray_triangle)


def _vp(side):
    vp = Viewport(None)
    vp.resize(1400, 850)
    vp.camera.set_aspect(1400, 850)
    vp.flash_status = lambda *a, **k: None
    vp.camera.target = V(side / 2, side / 2, 0)
    vp.camera.distance = 20 * side
    vp.camera.pitch = math.radians(35)
    vp.camera.yaw = math.radians(-40)
    return vp


def test_a_millimetre_square_is_picked():
    for side in (0.001, 0.0003):
        vp = _vp(side)
        f = vp.scene.mesh.add_face([V(0, 0, 0), V(side, 0, 0),
                                    V(side, side, 0), V(0, side, 0)])
        vp.scene.version += 1
        x, y = vp._world_to_pixel(V(side / 2, side / 2, 0))
        assert vp.pick_face(x, y) is f, side
        assert vp.pick_face_any(x, y) == (f, None), side


def test_a_grazing_ray_is_still_a_miss():
    o = np.array([-1.0, 0.25, 1e-9])
    d = np.array([1.0, 0.0, 0.0])                 # along the plane
    v0 = np.array([[0.0, 0.0, 0.0]])
    e1 = np.array([[1.0, 0.0, 0.0]])
    e2 = np.array([[0.0, 1.0, 0.0]])
    _t, hit = _moller_trumbore(o, d, v0, e1, e2)
    assert not hit[0]
    assert _ray_triangle(V(-1, 0.25, 1e-9), V(1, 0, 0), V(0, 0, 0),
                         V(1, 0, 0), V(0, 1, 0)) is None


def test_the_scalar_and_the_batched_test_agree_on_a_small_triangle():
    s = 0.001
    o = np.array([s / 3, s / 3, 1.0])
    d = np.array([0.1, -0.2, -1.0])
    d = d / np.linalg.norm(d)
    o = o - d * 0.0                              # head-on enough
    v0 = np.array([[0.0, 0.0, 0.0]])
    e1 = np.array([[s, 0.0, 0.0]])
    e2 = np.array([[0.0, s, 0.0]])
    # The ray from above the centroid, through the plane near it.
    o = np.array([s / 3, s / 3, 0.0]) - d * 1.0
    t, hit = _moller_trumbore(o, d, v0, e1, e2)
    assert hit[0]
    ts = _ray_triangle(V(*o), V(*d), V(0, 0, 0), V(s, 0, 0), V(0, s, 0))
    assert ts is not None and abs(ts - t[0]) < 1e-9


def test_push_pull_pulls_a_millimetre_square():
    """The reporter's gesture with the real tool and mouse events."""
    from views.main_window import MainWindow

    def ev(kind, x, y, button, buttons):
        return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button,
                           buttons, Qt.NoModifier)

    s = 0.001
    win = MainWindow()
    win.show()
    win.resize(1600, 900)
    _app.processEvents()
    try:
        vp = win.viewport
        cam = vp.camera
        cam.target = V(s / 2, s / 2, 0)
        cam.distance = 20 * s
        cam.pitch = math.radians(35)
        cam.yaw = math.radians(-40)
        face = vp.scene.mesh.add_face([V(0, 0, 0), V(s, 0, 0),
                                       V(s, s, 0), V(0, s, 0)])
        vp.scene.version += 1
        vp.update()
        _app.processEvents()
        win._activate_tool("pushpull")
        tool = vp.active_tool
        cx, cy = vp._world_to_pixel(V(s / 2, s / 2, 0))
        vp._last_mouse_pos = QPointF(cx, cy)
        vp._process_hover(QPointF(cx, cy), Qt.NoModifier)
        assert tool.hovered_face is face
        vp.mousePressEvent(ev(QMouseEvent.MouseButtonPress, cx, cy,
                              Qt.LeftButton, Qt.LeftButton))
        assert tool.dragging
        for dy in (20, 60, 120, 200):
            time.sleep(0.08)
            vp.mouseMoveEvent(ev(QMouseEvent.MouseMove, cx, cy - dy,
                                 Qt.NoButton, Qt.LeftButton))
        vp.mouseReleaseEvent(ev(QMouseEvent.MouseButtonRelease, cx, cy - 200,
                                Qt.LeftButton, Qt.NoButton))
        assert len(vp.scene.mesh.faces) == 6
        top = max(v.position.z() for v in vp.scene.mesh.vertices)
        assert top > s, top
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
