# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two-point placement on the composer canvas: the sheet tools accept BOTH a
drag and click-move-click (the model's dimension-tool habit), snapping every
point. A bare click with a two-point tool must NOT place a zero-size item —
that was 'the second point never snaps': the first release placed a zero
cota and silently disarmed the tool."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from views.composer import ComposerCanvasView, ComposerWindow  # noqa: E402


class _StubComposer:
    """Just enough of ComposerWindow for the canvas view: a tool mode, a
    snap oracle, and a recorder for place_tool."""
    TOOLS = ComposerWindow.TOOLS

    def __init__(self):
        self.tool_mode = "cota"
        self.placed = []
        self.snap_at = None            # (x, y) page-mm point every hit snaps to

    def nearest_snap_point(self, x, y, thr):
        return self.snap_at

    def update_cursor_label(self, x, y):
        pass

    def place_tool(self, x0, y0, x1, y1):
        self.placed.append((x0, y0, x1, y1))
        self.tool_mode = "select"


def _view():
    composer = _StubComposer()
    canvas = QGraphicsScene()
    view = ComposerCanvasView(canvas, composer)
    view._canvas_ref = canvas          # the view does not own the scene
    view.resize(400, 300)
    return view, composer


def _mouse(view, etype, px, py, button=Qt.LeftButton,
           buttons=Qt.NoButton):
    pos = QPointF(px, py)
    ev = QMouseEvent(etype, pos, pos, button, buttons, Qt.NoModifier)
    if etype == QEvent.MouseButtonPress:
        view.mousePressEvent(ev)
    elif etype == QEvent.MouseMove:
        view.mouseMoveEvent(ev)
    else:
        view.mouseReleaseEvent(ev)


def _scene_xy(view, px, py):
    p = view.mapToScene(QPoint(px, py))
    return p.x(), p.y()


class TestClickMoveClick:
    def test_two_clicks_place_one_item(self):
        view, comp = _view()
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseButtonRelease, 51, 50)      # same spot: click
        assert comp.placed == []                             # still armed
        _mouse(view, QEvent.MouseMove, 100, 80)
        _mouse(view, QEvent.MouseButtonPress, 150, 90)
        assert len(comp.placed) == 1
        x0, y0, x1, y1 = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 50, 50))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 150, 90))
        # the release of the finishing click must not start a new placement
        _mouse(view, QEvent.MouseButtonRelease, 150, 90)
        assert len(comp.placed) == 1

    def test_drag_still_places(self):
        view, comp = _view()
        _mouse(view, QEvent.MouseButtonPress, 40, 40)
        _mouse(view, QEvent.MouseMove, 120, 60, buttons=Qt.LeftButton)
        _mouse(view, QEvent.MouseButtonRelease, 120, 60)
        assert len(comp.placed) == 1
        x0, y0, x1, y1 = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 40, 40))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 120, 60))

    def test_second_click_on_the_first_point_keeps_waiting(self):
        view, comp = _view()
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseButtonRelease, 50, 50)
        _mouse(view, QEvent.MouseButtonPress, 51, 51)        # < 4 px away
        _mouse(view, QEvent.MouseButtonRelease, 51, 51)
        assert comp.placed == []                             # no zero-size item

    def test_snap_applies_to_both_points(self):
        view, comp = _view()
        comp.snap_at = (10.0, 20.0)
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseButtonRelease, 50, 50)
        comp.snap_at = (90.0, 20.0)
        _mouse(view, QEvent.MouseButtonPress, 150, 90)
        assert comp.placed == [(10.0, 20.0, 90.0, 20.0)]

    def test_escape_cancels_the_pending_placement(self):
        view, comp = _view()
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseButtonRelease, 50, 50)
        view.cancel_placement()
        _mouse(view, QEvent.MouseButtonPress, 150, 90)       # a fresh first click
        _mouse(view, QEvent.MouseButtonRelease, 150, 90)
        assert comp.placed == []                             # armed, waiting

    def test_point_tools_place_on_a_single_click(self):
        view, comp = _view()
        comp.tool_mode = "texto"
        _mouse(view, QEvent.MouseButtonPress, 70, 70)
        _mouse(view, QEvent.MouseButtonRelease, 70, 70)
        assert len(comp.placed) == 1
