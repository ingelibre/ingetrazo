# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tool cursors: activating a tool turns the mouse pointer
into the tool's icon; Offset has an arrow with a badge, Select keeps the arrow."""
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
    assert (ers.x(), ers.y()) == (10, 21)      # middle of the rubber's accent end
    mv = tool_cursor("move").hotSpot()
    assert (mv.x(), mv.y()) == (16, 16)        # centre of the cross
    assert tool_cursor("select") is None       # Select keeps the arrow
    assert tool_cursor("no_such_tool") is None
    assert tool_cursor(None) is None
    assert tool_cursor("line") is cur          # cached
    orb = tool_cursor("orbit")                 # wheel-drag shows it
    assert orb is not None and (orb.hotSpot().x(), orb.hotSpot().y()) == (16, 16)
    assert tool_cursor("pan") is not None
    zoom = tool_cursor("zoom")                 # Z shows the magnifier, not a cross
    assert zoom is not None
    assert (zoom.hotSpot().x(), zoom.hotSpot().y()) == (14, 14)  # lens centre
    assert tool_cursor("zoom_window") is not None


def test_offset_keeps_an_arrow_tip_with_its_icon_beside_it():
    from views.icons import tool_cursor
    cur = tool_cursor("offset")
    assert cur.hotSpot().x() == cur.hotSpot().y() == 2
    pm = cur.pixmap()
    assert pm.deviceIndependentSize().width() == 32
    image, dpr = pm.toImage(), pm.devicePixelRatio()
    # The pointer occupies the upper-left; the tool badge is below-right.
    assert image.pixelColor(round(3 * dpr), round(7 * dpr)).alpha() > 0
    assert image.pixelColor(round(18 * dpr), round(18 * dpr)).alpha() > 0
    assert tool_cursor("offset") is cur


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


def test_tool_cursor_respects_cursor_style_preference():
    from core import general_settings as _gs
    from views.icons import tool_cursor

    try:
        _gs.set_value("cursor_style", "tool")
        cur_tool = tool_cursor("line")
        assert cur_tool is not None and cur_tool.shape() == Qt.BitmapCursor

        _gs.set_value("cursor_style", "crosshair")
        cur_cross = tool_cursor("line")
        assert cur_cross is not None and cur_cross.shape() == Qt.CrossCursor

        _gs.set_value("cursor_style", "arrow")
        assert tool_cursor("line") is None
    finally:
        _gs.set_value("cursor_style", "tool")
