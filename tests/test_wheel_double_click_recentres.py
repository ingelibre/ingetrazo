"""A double click of the wheel recentres the view on the model point under the
cursor (#979, #1154): no orbit starts, no zoom, the tool in use is not
disturbed, on sky it slides all the same, and a plain wheel-drag still orbits. Needs a
GL context that renders: the point comes from the depth of the frame."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


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


def _double_click(vp, x=200, y=200):
    """What Qt delivers: press, release, double click, release."""
    _press(vp, x, y)
    _release(vp, x, y)
    _double(vp, x, y)
    _release(vp, x, y)


def _wall(vp):
    """A wall 20 m wide in the plane y = 0, facing the camera."""
    vp.scene.guides.clear()
    vp.scene.mesh.add_face([V(-10, 0, -10), V(10, 0, -10),
                            V(10, 0, 10), V(-10, 0, 10)])
    vp.scene.version += 1


def _view(vp, perspective=True):
    cam = vp.camera
    cam.set_view("front")
    cam.perspective = perspective
    cam.target = V(0, 0, 0)
    cam.distance = 10.0
    vp.grabFramebuffer()


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _off_centre(vp):
    return vp.width() // 2 + 60, vp.height() // 2 - 40


def _projected(vp, point):
    q = vp.camera.projection_matrix() * vp.camera.view_matrix()
    n = q.map(point)
    return ((n.x() + 1.0) / 2.0 * vp.width(), (1.0 - n.y()) / 2.0 * vp.height())


@pytest.mark.parametrize("perspective", [True, False],
                         ids=["perspective", "parallel"])
def test_the_point_under_the_cursor_goes_to_the_centre(win, perspective):
    vp = win.viewport
    _wall(vp)
    _view(vp, perspective)
    x, y = _off_centre(vp)
    seen = vp._depth_world_at(x, y)
    if seen is None or seen[0] != "hit":
        pytest.skip("this GL context gives no trustworthy depth read-back")
    point = seen[1]
    yaw, pitch = vp.camera.yaw, vp.camera.pitch
    distance = vp.camera.distance
    _double_click(vp, x, y)
    cam = vp.camera
    assert (cam.target - point).length() < 1e-4
    px, py = _projected(vp, point)
    assert abs(px - vp.width() / 2) < 1.0 and abs(py - vp.height() / 2) < 1.0
    assert cam.yaw == yaw and cam.pitch == pitch       # a slide, no turn
    assert cam.distance == pytest.approx(distance, rel=1e-3)   # no zoom


def test_a_slanted_view_keeps_the_depth_of_the_point(win):
    """In a view that looks at the wall at an angle the point is nearer or
    farther than the old target, and the camera follows it: the distance is
    the depth the point was at."""
    vp = win.viewport
    _wall(vp)
    _view(vp)
    vp.camera.yaw += math.radians(35)
    vp.grabFramebuffer()
    x, y = _off_centre(vp)
    seen = vp._depth_world_at(x, y)
    if seen is None or seen[0] != "hit":
        pytest.skip("this GL context gives no trustworthy depth read-back")
    depth = vp._depth_of(seen[1])
    assert abs(depth - vp.camera.distance) > 0.1       # the case in question
    eye_depth_axis = vp.camera.forward()
    _double_click(vp, x, y)
    assert vp.camera.distance == pytest.approx(depth, rel=1e-3)
    assert (vp.camera.forward() - eye_depth_axis).length() < 1e-5


def test_a_parallel_view_keeps_its_zoom_whatever_the_depth(win):
    """The distance is what a parallel view's size comes from."""
    vp = win.viewport
    _wall(vp)
    _view(vp, perspective=False)
    vp.camera.yaw += math.radians(35)
    vp.grabFramebuffer()
    x, y = _off_centre(vp)
    seen = vp._depth_world_at(x, y)
    if seen is None or seen[0] != "hit":
        pytest.skip("this GL context gives no trustworthy depth read-back")
    assert abs(vp._depth_of(seen[1]) - vp.camera.distance) > 0.1
    distance = vp.camera.distance
    _double_click(vp, x, y)
    assert vp.camera.distance == distance
    assert (vp.camera.target - seen[1]).length() < 1e-4


@pytest.mark.parametrize("perspective", [True, False])
def test_on_empty_sky_it_slides_to_the_point_keeping_the_zoom(win, perspective):
    """Anywhere, not only on the model: the pixel clicked goes to the centre,
    at the depth of the view's centre."""
    vp = win.viewport
    _wall(vp)
    _view(vp, perspective)
    vp.camera.distance = 400.0                         # the wall, a small patch
    vp.grabFramebuffer()
    seen = vp._depth_world_at(30, 30)
    if seen != ("background", None):
        pytest.skip("this GL context gives no trustworthy depth read-back")
    target, distance = V(vp.camera.target), vp.camera.distance
    yaw, pitch = vp.camera.yaw, vp.camera.pitch
    _double_click(vp, 30, 30)
    assert vp.camera.target != target
    assert vp.camera.distance == distance
    assert (vp.camera.yaw, vp.camera.pitch) == (yaw, pitch)
    view = vp.camera.target - vp.camera.eye()
    assert abs(V.dotProduct(vp.camera.target - target, view.normalized())) < 1e-3
    x, y = _projected(vp, target)
    # What was at the centre has moved as far as the pixel was from it.
    assert abs((x - vp.width() / 2) - (vp.width() / 2 - 30)) < 2.0
    assert abs((y - vp.height() / 2) - (vp.height() / 2 - 30)) < 2.0


def test_it_no_longer_frames_the_model(win):
    vp = win.viewport
    _wall(vp)
    _view(vp)
    framed = []
    win._act_zoom_extents.triggered.connect(lambda *_: framed.append(1))
    _double_click(vp, *_off_centre(vp))
    assert framed == []
    assert not hasattr(vp, "zoomExtentsRequested")


def test_dragging_after_the_double_click_does_not_orbit(win):
    vp = win.viewport
    _press(vp)
    _release(vp)
    _double(vp)
    assert not vp._middle_drag_active and vp._last_pos is None
    yaw, pitch = vp.camera.yaw, vp.camera.pitch
    _move(vp, 300, 260)
    assert vp.camera.yaw == yaw and vp.camera.pitch == pitch
    _release(vp, 300, 260)


def test_a_plain_wheel_drag_still_orbits(win):
    vp = win.viewport
    _double_click(vp)
    yaw = vp.camera.yaw
    distance = vp.camera.distance
    _press(vp)
    _move(vp, 300, 200)
    _release(vp, 300, 200)
    assert vp.camera.yaw != yaw
    assert vp.camera.distance == pytest.approx(distance)
    assert not vp._middle_drag_active


def test_the_tool_in_use_does_not_hear_of_it(win, monkeypatch):
    vp = win.viewport
    _wall(vp)
    _view(vp)
    tool = vp.active_tool
    assert tool is not None
    calls = []
    monkeypatch.setattr(vp, "_dispatch_tool_click",
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(tool, "on_double_click",
                        lambda ctx: calls.append(ctx))
    _double_click(vp, *_off_centre(vp))
    assert calls == []
    assert vp.active_tool is tool


def test_a_line_half_drawn_stays_half_drawn(win):
    from tools.line import LineTool
    vp = win.viewport
    _wall(vp)
    _view(vp)
    tool = LineTool()
    vp.set_active_tool(tool)
    fresh = dict(vars(tool))
    x, y = _off_centre(vp)
    vp.mousePressEvent(_event(QEvent.MouseButtonPress, x, y,
                              Qt.LeftButton, Qt.LeftButton))
    vp.mouseReleaseEvent(_event(QEvent.MouseButtonRelease, x, y,
                                Qt.LeftButton, Qt.NoButton))
    started = dict(vars(tool))
    assert started != fresh                            # a line under way
    edges = len(vp.scene.mesh.edges)
    _double_click(vp, x + 30, y)
    assert vp.active_tool is tool
    assert dict(vars(tool)) == started
    assert len(vp.scene.mesh.edges) == edges


def test_it_works_in_a_navigation_mode_too(win):
    vp = win.viewport
    _wall(vp)
    _view(vp)
    vp.nav_mode = "orbit"
    x, y = _off_centre(vp)
    seen = vp._depth_world_at(x, y)
    if seen is None or seen[0] != "hit":
        vp.nav_mode = None
        pytest.skip("this GL context gives no trustworthy depth read-back")
    _double_click(vp, x, y)
    assert (vp.camera.target - seen[1]).length() < 1e-4
    assert vp.nav_mode == "orbit"
    vp.nav_mode = None


def test_it_works_in_a_tab_opened_later(win):
    """Each tab has its own viewport, and its wheel recentres that one."""
    first = win.viewport
    first_target = V(first.camera.target)
    win._new_document()
    vp = win.viewport
    assert vp is not first
    for _ in range(10):
        _app.processEvents()
    _wall(vp)
    _view(vp)
    target = V(vp.camera.target)
    _double_click(vp, *_off_centre(vp))
    assert vp.camera.target != target
    assert abs(vp.camera.target.y()) < 1e-3            # on the wall
    assert first.camera.target == first_target


def test_a_double_click_of_the_left_button_does_not_recentre(win):
    vp = win.viewport
    _wall(vp)
    _view(vp)
    target = V(vp.camera.target)
    x, y = _off_centre(vp)
    vp.mouseDoubleClickEvent(_event(QEvent.MouseButtonDblClick, x, y,
                                    Qt.LeftButton, Qt.LeftButton))
    vp.mouseReleaseEvent(_event(QEvent.MouseButtonRelease, x, y,
                                Qt.LeftButton, Qt.NoButton))
    assert vp.camera.target == target
