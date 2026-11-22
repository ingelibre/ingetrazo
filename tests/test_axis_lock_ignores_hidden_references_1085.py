# SPDX-License-Identifier: GPL-3.0-or-later
"""Z locked from a box's top corner: the point follows the cursor up (#1085).

Under an arrow lock, pointing AT a reference (a corner, a midpoint, a
point of an edge) takes that reference's height on the lock line. In an
Iso view the box's hidden back edge sits right above the top corner on
screen, so moving the cursor up hovered its midpoint, then its body, and
the point went DOWN to them. A reference only counts by being pointed at
when it can be seen; in X-ray, where nothing hides anything, it still
does, and a visible one keeps working."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _box(mesh, x0, y0, z0, dx, dy, dz):
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for a, b, c, d in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                       (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[a], p[b], p[c], p[d]])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _scene(win, perspective, extra_box=False):
    """The box in an Iso view framed as in the issue (the taller box
    beside it widens the frame)."""
    vp = win.viewport
    sc = vp.scene
    sc.groups.clear()
    _box(sc.mesh, 0, 0, 0, 2, 2, 2)                  # the issue's 2 m box
    if extra_box:
        _box(sc.mesh, 4, 0, 0, 1, 1, 3.5)            # a taller one beside
    sc.version += 1
    cam = vp.camera
    cam.set_aspect(vp.width(), vp.height())
    cam.set_view("iso")
    cam.perspective = perspective
    cam.fit_to(V(-1, -1, 0), V(6, 3, 4) if extra_box else V(3, 3, 4))
    QApplication.processEvents()
    return vp


def _mouse(vp, kind, px, buttons=Qt.NoButton):
    ev = QMouseEvent(kind, QPointF(*px), QPointF(*px),
                     Qt.LeftButton if buttons else Qt.NoButton, buttons,
                     Qt.NoModifier)
    {QMouseEvent.MouseMove: vp.mouseMoveEvent,
     QMouseEvent.MouseButtonPress: vp.mousePressEvent,
     QMouseEvent.MouseButtonRelease: vp.mouseReleaseEvent}[kind](ev)
    vp._run_pending_hover()


def _line_from_top_corner_with_z_locked(win, vp):
    win._activate_tool("line")
    tool = vp.active_tool
    a = vp._world_to_pixel(V(2, 0, 2))               # the top corner
    _mouse(vp, QMouseEvent.MouseMove, a)
    _mouse(vp, QMouseEvent.MouseButtonPress, a, Qt.LeftButton)
    _mouse(vp, QMouseEvent.MouseButtonRelease, a)
    assert tool.start_point == V(2, 0, 2)
    vp.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Up,
                               Qt.NoModifier))
    assert vp.axis_lock == "z"
    return tool, a


def _z_above(vp, tool, a, up_px):
    _mouse(vp, QMouseEvent.MouseMove, (a[0], a[1] - up_px))
    return tool.hover_point.z()


@pytest.mark.parametrize("perspective", [True, False])
def test_moving_the_cursor_up_takes_the_point_up(win, perspective):
    vp = _scene(win, perspective)
    tool, a = _line_from_top_corner_with_z_locked(win, vp)
    heights = [_z_above(vp, tool, a, up) for up in (40, 80, 120, 200)]
    assert all(h > 2.0 for h in heights), heights     # never below the corner
    assert heights == sorted(heights), heights        # and following the cursor


def test_a_visible_corner_still_gives_its_height(win):
    vp = _scene(win, True, extra_box=True)
    tool, _a = _line_from_top_corner_with_z_locked(win, vp)
    corner = V(4, 0, 3.5)                             # the taller box's top
    assert not vp._is_occluded(corner)
    _mouse(vp, QMouseEvent.MouseMove, vp._world_to_pixel(corner))
    assert tool.hover_point.z() == pytest.approx(3.5, abs=1e-6)


def test_in_xray_the_back_edge_still_counts(win):
    vp = _scene(win, True)
    vp.scene.display_style.face_mode = "xray"
    assert vp._effective_style().face_mode == "xray"
    tool, a = _line_from_top_corner_with_z_locked(win, vp)
    back_mid = vp._world_to_pixel(V(0, 2, 1))         # seen through in X-ray
    _mouse(vp, QMouseEvent.MouseMove, back_mid)
    assert tool.hover_point.z() == pytest.approx(1.0, abs=1e-6)
