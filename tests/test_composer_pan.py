# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Panning the sheet: the middle button anywhere, or the Pan tool."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QGraphicsScene

from views.composer import ComposerCanvasView, ComposerWindow


class _Stub:
    TOOLS = ComposerWindow.TOOLS

    def __init__(self, mode="select"):
        self.tool_mode = mode

    def update_cursor_label(self, *_a):
        pass


def _view(mode):
    canvas = QGraphicsScene()
    canvas.setSceneRect(QRectF(0, 0, 3000, 3000))
    view = ComposerCanvasView(canvas, _Stub(mode))
    view._canvas_ref = canvas
    view.resize(400, 300)
    view.show()
    view.horizontalScrollBar().setValue(500)
    view.verticalScrollBar().setValue(500)
    return view


def _mouse(view, etype, px, py, button):
    pos = QPointF(px, py)
    ev = QMouseEvent(etype, pos, pos, button, button, Qt.NoModifier)
    {QEvent.MouseButtonPress: view.mousePressEvent,
     QEvent.MouseMove: view.mouseMoveEvent,
     QEvent.MouseButtonRelease: view.mouseReleaseEvent}[etype](ev)


def _drag(view, button, x0, y0, x1, y1):
    _mouse(view, QEvent.MouseButtonPress, x0, y0, button)
    _mouse(view, QEvent.MouseMove, x1, y1, button)
    _mouse(view, QEvent.MouseButtonRelease, x1, y1, button)


def test_middle_button_pans_in_any_tool():
    view = _view("select")
    try:
        h0, v0 = (view.horizontalScrollBar().value(),
                  view.verticalScrollBar().value())
        _drag(view, Qt.MiddleButton, 100, 100, 60, 80)   # content follows
        assert view.horizontalScrollBar().value() == h0 + 40
        assert view.verticalScrollBar().value() == v0 + 20
        assert view._pan_last is None                     # released
    finally:
        view.close()


def test_pan_tool_pans_with_the_left_button_only_in_pan_mode():
    view = _view("pan")
    try:
        h0 = view.horizontalScrollBar().value()
        _drag(view, Qt.LeftButton, 100, 100, 130, 100)
        assert view.horizontalScrollBar().value() == h0 - 30
        assert view.cursor().shape() == Qt.OpenHandCursor
        view.composer.tool_mode = "select"
        h1 = view.horizontalScrollBar().value()
        _drag(view, Qt.LeftButton, 100, 100, 130, 100)    # rubber band, no pan
        assert view.horizontalScrollBar().value() == h1
    finally:
        view.close()
