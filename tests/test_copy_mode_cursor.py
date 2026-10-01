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
