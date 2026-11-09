# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Discussion #267 (tomlai-git, found by Arthur031221): «16s» sets the
sides of a circle / the segments of an arc, and the parser understood it,
but the keyboard never let the «s» into the value box."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _type(vp, text):
    for ch in text:
        key = Qt.Key_S if ch == "s" else Qt.Key(Qt.Key_0 + int(ch))
        if vp._value_buffer:   # mid-value, no window shortcut steals it
            ov = QKeyEvent(QEvent.ShortcutOverride, key, Qt.NoModifier, ch)
            vp.event(ov)
            assert ov.isAccepted(), ch
        vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, ch))
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                               Qt.NoModifier, "\r"))


@pytest.mark.parametrize("tool,attr", [("circle", "sides"),
                                       ("arc", "segments")])
def test_typing_16s_sets_the_count(win, tool, attr):
    win._activate_tool(tool)
    vp = win.viewport
    _type(vp, "16s")
    assert getattr(vp.active_tool, attr) == 16
    assert vp._value_buffer == ""


def test_a_bare_s_is_still_a_shortcut(win):
    win._activate_tool("circle")
    vp = win.viewport
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.NoModifier, "s"))
    assert vp._value_buffer == ""
