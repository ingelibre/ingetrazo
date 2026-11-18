# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing along an axis with the magnet, 'From point' still lines up the
end with a corner or the origin (#1418).

The open rectangle of the issue: a corner at the origin, the green side,
the top side, and the right side being drawn down along green toward the
red axis. The arrow lock offered the origin's 'From point' and the line
ended exactly on red; the axis magnet — the same line drawn without the
arrow — silenced it with every other derived inference, and the point slid
past the red axis. Its foot is on the axis line, so the magnet keeps it."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from core.edits import build_add_edges
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    vp = w.viewport
    sc = vp.scene
    sc.groups.clear()
    vp.history.execute(build_add_edges(sc, [
        (V(0, 0, 0), V(0, 6, 0)), (V(0, 6, 0), V(10, 6, 0))]))
    cam = vp.camera
    cam.set_aspect(vp.width(), vp.height())
    cam.set_view("iso")
    cam.perspective = True
    cam.fit_to(V(-2, -6, 0), V(15, 8, 1))
    QApplication.processEvents()
    yield w
    w._saved_version = sc.version
    w.close()


def _mouse(vp, kind, px, buttons=Qt.NoButton):
    ev = QMouseEvent(kind, QPointF(*px), QPointF(*px),
                     Qt.LeftButton if buttons else Qt.NoButton, buttons,
                     Qt.NoModifier)
    {QMouseEvent.MouseMove: vp.mouseMoveEvent,
     QMouseEvent.MouseButtonPress: vp.mousePressEvent,
     QMouseEvent.MouseButtonRelease: vp.mouseReleaseEvent}[kind](ev)
    vp._run_pending_hover()


def _line_from(win, start, exact=True):
    win._activate_tool("line")
    vp = win.viewport
    a = vp._world_to_pixel(start)
    _mouse(vp, QMouseEvent.MouseMove, a)
    _mouse(vp, QMouseEvent.MouseButtonPress, a, Qt.LeftButton)
    _mouse(vp, QMouseEvent.MouseButtonRelease, a)
    if exact:                                   # started on a vertex
        assert vp.active_tool.start_point == start
    return vp.active_tool


def _near(vp, world, off_px):
    p = vp._world_to_pixel(world)
    _mouse(vp, QMouseEvent.MouseMove, (p[0] + off_px * 0.7,
                                       p[1] + off_px * 0.7))
    return vp.active_tool.hover_point, vp.last_snap


@pytest.mark.parametrize("arrow", [False, True])
@pytest.mark.parametrize("off_px", [6.0, 3.0, 0.0])
def test_the_right_side_ends_exactly_on_the_red_axis(win, arrow, off_px):
    vp = win.viewport
    _line_from(win, V(10, 6, 0))
    if arrow:
        vp.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Left,
                                   Qt.NoModifier))
        assert vp.axis_lock == "y"
    point, snap = _near(vp, V(10, 0, 0), off_px)
    assert snap.kind == "from_point"
    assert point.x() == pytest.approx(10.0, abs=1e-9)
    assert point.y() == pytest.approx(0.0, abs=1e-9)        # ON the red axis
    assert snap.guide is not None
    assert snap.guide[0] == V(0, 0, 0)                      # from the origin


def test_a_corner_lines_up_too_along_red(win):
    vp = win.viewport
    tool = _line_from(win, V(14, -3, 0), exact=False)     # on bare ground
    start = tool.start_point
    point, snap = _near(vp, V(10, start.y(), 0), 3.0)       # below (10, 6)
    assert snap.kind == "from_point"
    assert point.x() == pytest.approx(10.0, abs=1e-9)       # in line with it
    assert point.y() == pytest.approx(start.y(), abs=1e-9)  # still on red


def test_away_from_every_reference_the_magnet_still_slides(win):
    vp = win.viewport
    _line_from(win, V(10, 6, 0))
    point, snap = _near(vp, V(10, 1.7, 0), 0.0)
    assert snap.kind == "axis"
    assert point.x() == pytest.approx(10.0, abs=1e-9)
    assert point.y() == pytest.approx(1.7, abs=0.15)        # where the cursor is
