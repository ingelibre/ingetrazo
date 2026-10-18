"""The orbit never sticks to the mouse (Andrés Rodríguez, Windows 11,
0.5.0: «el orbital se mantiene activo aunque cambie a cualquier otra
herramienta… no se desactiva con nada»). A camera drag is remembered from
the press until its release; when that release was lost, every mouse move
orbited the view, whatever tool was picked."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _move(vp, x, y, buttons=Qt.NoButton, modifiers=Qt.NoModifier):
    ev = QMouseEvent(QMouseEvent.MouseMove, QPointF(x, y), QPointF(x, y),
                     Qt.NoButton, buttons, modifiers)
    vp.mouseMoveEvent(ev)


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.resize(800, 600)
    return win


def _pose(cam):
    return (round(cam.yaw, 9), round(cam.pitch, 9))


def test_a_lost_release_does_not_leave_the_orbit_on():
    win = _window()
    vp = win.viewport
    vp._last_pos = QPoint(100, 100)          # a wheel-drag whose release was lost
    before = _pose(vp.camera)
    _move(vp, 180, 140)                      # plain move, no button held
    assert _pose(vp.camera) == before
    assert vp._last_pos is None
    win._saved_version = vp.scene.version
    win.close()


def test_a_real_drag_still_orbits():
    win = _window()
    vp = win.viewport
    vp._last_pos = QPoint(100, 100)
    before = _pose(vp.camera)
    _move(vp, 180, 140, Qt.MiddleButton)     # the wheel is held
    assert _pose(vp.camera) != before
    win._saved_version = vp.scene.version
    win.close()


def test_shift_switches_an_active_middle_drag_between_orbit_and_pan(monkeypatch):
    win = _window()
    vp = win.viewport
    modes = []
    monkeypatch.setattr(vp.camera, "orbit_about",
                        lambda *args: modes.append("orbit"))
    monkeypatch.setattr(vp.camera, "pan", lambda *args, **kwargs: modes.append("pan"))

    press = QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(100, 100),
                        QPointF(100, 100), Qt.MiddleButton, Qt.MiddleButton,
                        Qt.NoModifier)
    vp.mousePressEvent(press)
    _move(vp, 110, 110, Qt.MiddleButton)
    assert modes == ["orbit"]

    shift_press = QKeyEvent(QEvent.KeyPress, Qt.Key_Shift, Qt.ShiftModifier)
    vp.keyPressEvent(shift_press)
    assert vp._pan_mode
    _move(vp, 120, 120, Qt.MiddleButton, Qt.ShiftModifier)
    assert modes == ["orbit", "pan"]

    shift_release = QKeyEvent(QEvent.KeyRelease, Qt.Key_Shift, Qt.NoModifier)
    vp.keyReleaseEvent(shift_release)
    assert not vp._pan_mode
    _move(vp, 130, 130, Qt.MiddleButton)
    assert modes == ["orbit", "pan", "orbit"]

    win._saved_version = vp.scene.version
    win.close()


def test_picking_a_tool_ends_a_camera_drag():
    win = _window()
    vp = win.viewport
    vp.set_nav_mode("orbit")
    vp._last_pos = QPoint(100, 100)
    win._activate_tool("paint")
    assert vp.nav_mode is None and vp._last_pos is None
    # Leave no closed window holding Paint: until it is collected it sits
    # in the Alt-tap watcher and can take a later test's tap.
    win._activate_tool("select")
    win._saved_version = vp.scene.version
    win.close()
