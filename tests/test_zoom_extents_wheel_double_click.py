"""A double click of the wheel frames the whole model (#979): no orbit starts,
the tool in use is not disturbed, and a plain wheel-drag still orbits."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication


def _event(kind, x, y, button, buttons):
    p = QPointF(x, y)
    return QMouseEvent(kind, p, p, button, buttons, Qt.NoModifier)


def _press(vp, x=200, y=200):
    vp.mousePressEvent(_event(QEvent.MouseButtonPress, x, y,
                              Qt.MiddleButton, Qt.MiddleButton))


def _release(vp, x=200, y=200):
    vp.mouseReleaseEvent(_event(QEvent.MouseButtonRelease, x, y,
                                Qt.MiddleButton, Qt.NoButton))


def _double(vp, x=200, y=200):
    vp.mouseDoubleClickEvent(_event(QEvent.MouseButtonDblClick, x, y,
                                    Qt.MiddleButton, Qt.MiddleButton))


def _move(vp, x, y):
    vp.mouseMoveEvent(_event(QEvent.MouseMove, x, y,
                             Qt.NoButton, Qt.MiddleButton))


def _double_click(vp):
    """What Qt delivers: press, release, double click, release."""
    _press(vp)
    _release(vp)
    _double(vp)


@pytest.fixture
def win():
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    window = MainWindow()
    cam = window.viewport.camera
    cam.target = V(500, 500, 0)
    cam.distance = 4000                   # far away from everything
    yield window
    window._saved_version = window.viewport.scene.version
    window.close()


def test_a_double_click_of_the_wheel_frames_the_model(win):
    vp = win.viewport
    _double_click(vp)
    _release(vp)
    assert vp.camera.distance < 20        # framed the 1.7 m figure
    assert abs(vp.camera.target.x() + 0.65) < 1.0


def test_it_frames_as_zoom_extents_does(win):
    vp = win.viewport
    _double_click(vp)
    _release(vp)
    framed = (V(vp.camera.target), vp.camera.distance)
    vp.camera.target = V(500, 500, 0)
    vp.camera.distance = 4000
    win._act_zoom_extents.trigger()
    assert vp.camera.target == framed[0]
    assert vp.camera.distance == pytest.approx(framed[1])


def test_dragging_after_the_double_click_does_not_orbit(win):
    vp = win.viewport
    _double_click(vp)
    assert not vp._middle_drag_active and vp._last_pos is None
    yaw, pitch = vp.camera.yaw, vp.camera.pitch
    _move(vp, 300, 280)
    assert (vp.camera.yaw, vp.camera.pitch) == (yaw, pitch)
    _release(vp, 300, 280)
    assert not vp._middle_drag_active and vp._last_pos is None


def test_a_wheel_drag_still_orbits_and_does_not_frame(win):
    vp = win.viewport
    yaw, distance = vp.camera.yaw, vp.camera.distance
    _press(vp)
    _move(vp, 300, 200)
    _release(vp, 300, 200)
    assert vp.camera.yaw != yaw
    assert vp.camera.distance == pytest.approx(distance)
    assert not vp._middle_drag_active


def test_a_single_click_of_the_wheel_does_not_frame(win):
    vp = win.viewport
    distance = vp.camera.distance
    _press(vp)
    _release(vp)
    assert vp.camera.distance == pytest.approx(distance)


def test_the_tool_in_use_does_not_hear_of_it(win, monkeypatch):
    vp = win.viewport
    tool = vp.active_tool
    assert tool is not None
    calls = []
    monkeypatch.setattr(vp, "_dispatch_tool_click",
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(tool, "on_double_click",
                        lambda ctx: calls.append(ctx))
    _double_click(vp)
    _release(vp)
    assert calls == []
    assert vp.active_tool is tool
    assert vp.camera.distance < 20


def test_it_works_in_a_navigation_mode_too(win):
    """With the Orbit or Pan button on, the wheel behaves the same."""
    vp = win.viewport
    vp.nav_mode = "orbit"
    _double_click(vp)
    _release(vp)
    assert vp.camera.distance < 20
    assert vp.nav_mode == "orbit"
    vp.nav_mode = None


def test_a_double_click_of_the_left_button_does_not_frame(win):
    vp = win.viewport
    distance = vp.camera.distance
    vp.mouseDoubleClickEvent(_event(QEvent.MouseButtonDblClick, 200, 200,
                                    Qt.LeftButton, Qt.LeftButton))
    vp.mouseReleaseEvent(_event(QEvent.MouseButtonRelease, 200, 200,
                                Qt.LeftButton, Qt.NoButton))
    assert vp.camera.distance == pytest.approx(distance)
