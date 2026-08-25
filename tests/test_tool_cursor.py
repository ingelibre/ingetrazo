# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SketchUp-style tool cursors: activating a tool turns the mouse pointer
into the tool's icon (aim cross at the hotspot); Select keeps the arrow."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def test_tool_cursor_builds_bitmap_with_hotspot():
    from views.icons import tool_cursor
    cur = tool_cursor("line")                  # pencil, hotspot at the TIP
    assert cur is not None
    assert not cur.pixmap().isNull()
    hs = cur.hotSpot()
    assert (hs.x(), hs.y()) == (4, 28)         # (6,42) in 48-space → ×32/48
    ers = tool_cursor("eraser").hotSpot()
    assert (ers.x(), ers.y()) == (9, 19)       # the rubber's working corner
    mv = tool_cursor("move").hotSpot()
    assert (mv.x(), mv.y()) == (16, 16)        # centre of the cross
    assert tool_cursor("select") is None       # Select keeps the arrow
    assert tool_cursor("no_such_tool") is None
    assert tool_cursor(None) is None
    assert tool_cursor("line") is cur          # cached
    orb = tool_cursor("orbit")                 # wheel-drag shows it (SketchUp)
    assert orb is not None and (orb.hotSpot().x(), orb.hotSpot().y()) == (16, 16)
    assert tool_cursor("pan") is not None


def test_activating_tools_swaps_the_viewport_cursor():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        assert vp.cursor().shape() != Qt.BitmapCursor   # select at startup
        win._activate_tool("line")
        assert vp.cursor().shape() == Qt.BitmapCursor
        win._activate_tool("pushpull")
        assert vp.cursor().shape() == Qt.BitmapCursor
        win._activate_tool("select")
        assert vp.cursor().shape() != Qt.BitmapCursor   # back to the arrow
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
