# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ctrl on Move, Rotate and Flip makes a COPY — and the cursor says so.

The mode only showed as a flash in the status bar: whoever was looking at
the model, not at the bar, found out after the click whether they had moved
the original or a copy. The pointer now carries the same little + the Tape
and the Protractor show for their guide mode (#29), while copy is on.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _ctrl(vp):
    vp.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Control,
                               Qt.ControlModifier))
    vp.keyReleaseEvent(QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Control,
                                 Qt.NoModifier))


def _shows(vp, key, plus):
    from views.icons import tool_cursor
    want = tool_cursor(key, plus)
    return vp.cursor().pixmap().cacheKey() == want.pixmap().cacheKey()


@pytest.mark.parametrize("key", ["move", "rotate", "flip"])
def test_ctrl_puts_a_plus_on_the_cursor_and_takes_it_off(win, key):
    vp = win.viewport
    win._activate_tool(key)
    assert vp.active_tool.cursor_plus is False
    assert _shows(vp, key, plus=False)
    _ctrl(vp)
    assert vp.active_tool.cursor_plus is True
    assert _shows(vp, key, plus=True), "copy mode on, but no + on the cursor"
    _ctrl(vp)
    assert vp.active_tool.cursor_plus is False
    assert _shows(vp, key, plus=False)


@pytest.mark.parametrize("key", ["move", "rotate", "flip"])
def test_picking_the_tool_up_again_starts_without_the_plus(win, key):
    vp = win.viewport
    win._activate_tool(key)
    _ctrl(vp)
    win._activate_tool("line")
    win._activate_tool(key)
    assert vp.active_tool.cursor_plus is False
    assert _shows(vp, key, plus=False)


def _ctrl_shortcut(vp, key, text):
    """Ctrl held for a shortcut: the letter reaches the viewport as a
    ShortcutOverride when a menu action owns it (Ctrl+Z), never alone."""
    from PySide6.QtCore import QEvent
    vp.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Control,
                               Qt.ControlModifier))
    vp.event(QKeyEvent(QEvent.ShortcutOverride, key, Qt.ControlModifier, text))
    vp.keyReleaseEvent(QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_Control,
                                 Qt.NoModifier))


@pytest.mark.parametrize("key", ["move", "rotate", "flip"])
def test_ctrl_z_leaves_the_copy_mode_alone(win, key):
    """The Tape's #183, on the copy tools: Ctrl+Z (or Ctrl+C…) used to
    switch copy mode on the way, without a word."""
    vp = win.viewport
    win._activate_tool(key)
    _ctrl_shortcut(vp, Qt.Key_Z, "z")
    assert vp.active_tool.cursor_plus is False
    assert _shows(vp, key, plus=False)
    _ctrl(vp)                                    # a real tap still works…
    _ctrl_shortcut(vp, Qt.Key_C, "c")            # …and survives a shortcut
    assert vp.active_tool.cursor_plus is True
    assert _shows(vp, key, plus=True)


def test_the_plus_goes_when_the_one_copy_is_made(win):
    """Flip (like Rotate) arms Ctrl for ONE operation: once the copy is
    made the mode is off, and the cursor must say so too."""
    from types import SimpleNamespace
    from PySide6.QtGui import QVector3D as V
    vp = win.viewport
    scene = vp.scene
    face = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    scene.selection = [face]
    win._activate_tool("flip")
    tool = vp.active_tool
    _ctrl(vp)
    assert _shows(vp, "flip", plus=True)
    tool._lock_axis = "x"
    tool.on_click(SimpleNamespace(viewport=vp))
    assert tool.cursor_plus is False
    assert _shows(vp, "flip", plus=False)
