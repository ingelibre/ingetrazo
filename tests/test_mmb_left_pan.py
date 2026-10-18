"""Wheel held, then left pressed: the camera drag pans instead of orbiting,
an alternative to Shift+wheel-drag. Letting go of the left button while
the wheel is still held goes back to orbiting; the left button's press and
release never reach the active tool."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

MMB, LMB = Qt.MiddleButton, Qt.LeftButton
BOTH = Qt.MouseButtons(MMB | LMB)


def _ev(kind, x, y, button, buttons, mods=Qt.NoModifier):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons,
                       mods)


def _press(vp, x, y, button, buttons, mods=Qt.NoModifier):
    vp.mousePressEvent(_ev(QMouseEvent.MouseButtonPress, x, y, button,
                           buttons, mods))


def _release(vp, x, y, button, buttons):
    vp.mouseReleaseEvent(_ev(QMouseEvent.MouseButtonRelease, x, y, button,
                             buttons))


def _move(vp, x, y, buttons):
    vp.mouseMoveEvent(_ev(QMouseEvent.MouseMove, x, y, Qt.NoButton, buttons))


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.resize(800, 600)
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _angles(cam):
    return (round(cam.yaw, 9), round(cam.pitch, 9))


def _target(cam):
    t = cam.target
    return (round(t.x(), 6), round(t.y(), 6), round(t.z(), 6))


def test_wheel_then_left_pans():
    win = _window()
    vp = win.viewport
    _press(vp, 400, 300, MMB, MMB)
    _press(vp, 400, 300, LMB, BOTH)
    angles, target = _angles(vp.camera), _target(vp.camera)
    _move(vp, 460, 340, BOTH)
    assert _angles(vp.camera) == angles      # no orbit
    assert _target(vp.camera) != target      # the view slid
    _close(win)


def test_letting_go_of_left_goes_back_to_orbit():
    win = _window()
    vp = win.viewport
    _press(vp, 400, 300, MMB, MMB)
    _press(vp, 400, 300, LMB, BOTH)
    _move(vp, 430, 320, BOTH)
    _release(vp, 430, 320, LMB, MMB)
    angles = _angles(vp.camera)
    _move(vp, 490, 360, MMB)
    assert _angles(vp.camera) != angles      # orbiting again
    _release(vp, 490, 360, MMB, Qt.NoButton)
    assert vp._last_pos is None
    _close(win)


def test_a_shift_pan_stays_a_pan_after_the_left_button():
    win = _window()
    vp = win.viewport
    _press(vp, 400, 300, MMB, MMB, Qt.ShiftModifier)
    _press(vp, 400, 300, LMB, BOTH)
    _release(vp, 400, 300, LMB, MMB)
    assert vp._pan_mode
    _release(vp, 400, 300, MMB, Qt.NoButton)
    _close(win)


def test_the_tool_never_sees_the_left_button():
    win = _window()
    vp = win.viewport
    win._activate_tool("line")
    calls = []
    tool = vp.active_tool
    tool.on_click = lambda ctx: calls.append("click")
    tool.on_release = lambda view: calls.append("release")
    _press(vp, 400, 300, MMB, MMB)
    _press(vp, 400, 300, LMB, BOTH)
    _move(vp, 450, 330, BOTH)
    _release(vp, 450, 330, MMB, LMB)         # the wheel first…
    _move(vp, 470, 340, LMB)                 # …no camera drag left
    _release(vp, 470, 340, LMB, Qt.NoButton)
    assert calls == []
    assert vp._last_pos is None and vp._left_pan_restore is None
    win._activate_tool("select")
    _close(win)
