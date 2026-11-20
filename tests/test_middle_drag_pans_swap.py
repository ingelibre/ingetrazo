"""Preferences ▸ "Middle-button drag pans" (PR #467): the bare wheel-drag pans
and Shift orbits, and it stays so while the drag moves. Shift pressed or
released during a drag switches the two live, so that switch has to read
the preference too, or the first move of a swapped drag went back to orbit."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _event(kind, x, y, button, buttons, mods=Qt.NoModifier):
    p = QPointF(x, y)
    return QMouseEvent(kind, p, p, button, buttons, mods)


def _press(vp, mods=Qt.NoModifier):
    vp.mousePressEvent(_event(QEvent.MouseButtonPress, 200, 200,
                              Qt.MiddleButton, Qt.MiddleButton, mods))


def _move(vp, x, mods=Qt.NoModifier):
    vp.mouseMoveEvent(_event(QEvent.MouseMove, x, 200,
                             Qt.NoButton, Qt.MiddleButton, mods))


def _release(vp):
    vp.mouseReleaseEvent(_event(QEvent.MouseButtonRelease, 260, 200,
                                Qt.MiddleButton, Qt.NoButton))


@pytest.fixture
def vp():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    for _ in range(10):
        _app.processEvents()
    if getattr(w.viewport, "_gl", None) is None or not w.viewport.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    yield w.viewport
    w._saved_version = w.viewport.scene.version
    w.close()


def test_by_default_the_bare_drag_orbits_and_shift_pans(vp):
    vp._middle_drag_pans = False
    _press(vp)
    assert vp._pan_mode is False
    _move(vp, 220)
    assert vp._pan_mode is False
    _move(vp, 240, Qt.ShiftModifier)
    assert vp._pan_mode is True
    _release(vp)


def test_swapped_the_bare_drag_pans_while_it_moves(vp):
    vp._middle_drag_pans = True
    _press(vp)
    assert vp._pan_mode is True
    _move(vp, 220)
    assert vp._pan_mode is True
    _move(vp, 240, Qt.ShiftModifier)
    assert vp._pan_mode is False
    _move(vp, 250)
    assert vp._pan_mode is True
    _release(vp)


def test_swapped_shift_at_the_press_orbits(vp):
    vp._middle_drag_pans = True
    _press(vp, Qt.ShiftModifier)
    assert vp._pan_mode is False
    _move(vp, 220, Qt.ShiftModifier)
    assert vp._pan_mode is False
    _release(vp)
