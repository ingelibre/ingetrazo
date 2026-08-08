# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two-point placement on the composer canvas: the sheet tools accept BOTH a
drag and click-move-click (the model's dimension-tool habit), snapping every
point. The dimension tool adds a THIRD click that pulls the dimension line
away from the measured points (LayOut-style ``sep_mm``). A bare click with a
two-point tool must NOT place a zero-size item — that was 'the second point
never snaps': the first release placed a zero cota and silently disarmed the
tool."""
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

from core.composition import CotaItem                           # noqa: E402
from views.composer import ComposerCanvasView, ComposerWindow   # noqa: E402


class _StubComposer:
    """Just enough of ComposerWindow for the canvas view: a tool mode, a
    snap oracle, and a recorder for place_tool."""
    TOOLS = ComposerWindow.TOOLS

    def __init__(self, mode="linea"):
        self.tool_mode = mode
        self.placed = []
        self.snap_at = None            # (x, y) page-mm point every hit snaps to

    def nearest_snap_point(self, x, y, thr):
        return self.snap_at

    def update_cursor_label(self, x, y):
        pass

    def place_tool(self, x0, y0, x1, y1, sep_mm=0.0):
        self.placed.append((x0, y0, x1, y1, sep_mm))
        self.tool_mode = "select"


def _view(mode="linea"):
    composer = _StubComposer(mode)
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


def _click(view, px, py):
    _mouse(view, QEvent.MouseButtonPress, px, py)
    _mouse(view, QEvent.MouseButtonRelease, px, py)


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
        x0, y0, x1, y1, _sep = comp.placed[0]
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
        x0, y0, x1, y1, _sep = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 40, 40))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 120, 60))

    def test_second_click_on_the_first_point_keeps_waiting(self):
        view, comp = _view()
        _click(view, 50, 50)
        _click(view, 51, 51)                                 # < 4 px away
        assert comp.placed == []                             # no zero-size item

    def test_snap_applies_to_both_points(self):
        view, comp = _view()
        comp.snap_at = (10.0, 20.0)
        _click(view, 50, 50)
        comp.snap_at = (90.0, 20.0)
        _mouse(view, QEvent.MouseButtonPress, 150, 90)
        assert comp.placed[0][:4] == (10.0, 20.0, 90.0, 20.0)

    def test_escape_cancels_the_pending_placement(self):
        view, comp = _view()
        _click(view, 50, 50)
        view.cancel_placement()
        _click(view, 150, 90)                                # a fresh first click
        assert comp.placed == []                             # armed, waiting

    def test_point_tools_place_on_a_single_click(self):
        view, comp = _view("texto")
        _click(view, 70, 70)
        assert len(comp.placed) == 1


class TestCotaSepPhase:
    def test_third_click_sets_the_separation(self):
        view, comp = _view("cota")
        _click(view, 50, 50)                                 # first point
        _click(view, 150, 50)                                # second point
        assert comp.placed == []                             # sep phase now
        _mouse(view, QEvent.MouseMove, 100, 90)
        _mouse(view, QEvent.MouseButtonPress, 100, 80)       # third click
        assert len(comp.placed) == 1
        x0, y0, x1, y1, sep = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 50, 50))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 150, 50))
        assert sep == pytest.approx(30.0)                    # 80 - 50, along +n
        _mouse(view, QEvent.MouseButtonRelease, 100, 80)
        assert len(comp.placed) == 1

    def test_drag_then_click_also_works(self):
        view, comp = _view("cota")
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseMove, 150, 50, buttons=Qt.LeftButton)
        _mouse(view, QEvent.MouseButtonRelease, 150, 50)     # points fixed
        assert comp.placed == []
        _mouse(view, QEvent.MouseButtonPress, 100, 20)       # pull the line up
        assert len(comp.placed) == 1
        assert comp.placed[0][4] == pytest.approx(-30.0)

    def test_sep_phase_ignores_snapping(self):
        view, comp = _view("cota")
        _click(view, 50, 50)
        _click(view, 150, 50)
        comp.snap_at = (999.0, 999.0)                        # must NOT bite
        _mouse(view, QEvent.MouseButtonPress, 100, 75)
        assert comp.placed[0][4] == pytest.approx(25.0)

    def test_escape_cancels_the_sep_phase(self):
        view, comp = _view("cota")
        _click(view, 50, 50)
        _click(view, 150, 50)
        view.cancel_placement()
        _click(view, 100, 80)                                # fresh first click
        assert comp.placed == []


class TestCotaModel:
    def test_normal_is_perpendicular_and_unit(self):
        ct = CotaItem(dx_mm=30.0, dy_mm=40.0)
        nx, ny = ct.normal()
        assert nx * 30.0 + ny * 40.0 == pytest.approx(0.0)
        assert nx * nx + ny * ny == pytest.approx(1.0)

    def test_label_honours_decimals(self):
        ct = CotaItem(dx_mm=34.56, dy_mm=0.0, scale_n=100.0, decimals=1)
        assert ct.label() == "3.5 m"
        ct.decimals = 3
        assert ct.label() == "3.456 m"

    def test_old_documents_load_without_the_new_fields(self):
        ct = CotaItem(**{"x_mm": 5.0, "y_mm": 6.0, "dx_mm": 40.0,
                         "dy_mm": 0.0, "scale_n": 50.0, "offset_mm": 4.0,
                         "text": ""})
        assert ct.sep_mm == 0.0                              # line on the points
        assert ct.ends == "tick"
        assert ct.text_mm == pytest.approx(2.8)
