# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #414: type a new measurement right after finishing a shape and it
is redrawn with it.

Push/Pull, Move, Rotate, Scale and Offset already had this «hot retype»;
the Rectangle, the Line and the Circle did not: draw a 3 x 2 rectangle,
type «4;1» + Enter and nothing happened. Now the shape just drawn is undone
and drawn again from the same start, in ONE undo step however many times
the value is retyped, until a click, Esc or another operation closes the
window."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.base import ToolContext  # noqa: E402
from tools.circle import CircleTool, PolygonTool  # noqa: E402
from tools.line import LineTool  # noqa: E402
from tools.rectangle import RectangleTool  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def viewport():
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _fresh(vp, tool):
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    vp.history.redo_stack.clear()
    tool.on_activate(vp)


def _ctx(vp, world):
    return ToolContext(viewport=vp, world=world, screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _click(vp, tool, *points):
    for p in points:
        tool.on_click(_ctx(vp, p))


def _bbox(mesh):
    xs = [v.position.x() for v in mesh.vertices]
    ys = [v.position.y() for v in mesh.vertices]
    return (round(min(xs), 6), round(min(ys), 6),
            round(max(xs), 6), round(max(ys), 6))


def _edges(mesh):
    return sorted(
        tuple(sorted((tuple(round(c, 6) for c in (p.x(), p.y(), p.z()))
                      for p in (e.v0.position, e.v1.position))))
        for e in mesh.edges)


# ---- Rectangle -------------------------------------------------------------
def test_rectangle_retyped_after_two_clicks(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(3, 2, 0))
    mesh = viewport.scene.mesh
    assert _bbox(mesh) == (0, 0, 3, 2)
    steps = len(viewport.history.undo_stack)
    assert tool.on_value(viewport, (4.0, 1.0))
    assert _bbox(mesh) == (0, 0, 4, 1)
    assert len(mesh.faces) == 1
    assert len(viewport.history.undo_stack) == steps   # replaced, not added
    assert tool.on_value(viewport, (5.0, 2.5))         # again: still one step
    assert _bbox(mesh) == (0, 0, 5, 2.5)
    assert len(viewport.history.undo_stack) == steps
    viewport.history.undo()
    assert mesh.faces == [] and mesh.edges == []


def test_rectangle_keeps_its_quadrant(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(-3, -2, 0))
    assert tool.on_value(viewport, (4.0, 1.0))
    assert _bbox(viewport.scene.mesh) == (-4, -1, 0, 0)


def test_rectangle_retyped_after_typed_dimensions(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0))
    tool.hover_point = V(1, 1, 0)
    assert tool.on_value(viewport, (3.0, 2.0))
    assert _bbox(viewport.scene.mesh) == (0, 0, 3, 2)
    steps = len(viewport.history.undo_stack)
    assert tool.on_value(viewport, (2.0, 2.0))
    assert _bbox(viewport.scene.mesh) == (0, 0, 2, 2)
    assert len(viewport.history.undo_stack) == steps


def test_rectangle_lone_number_sets_the_stretched_side(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0))
    tool._live_side = "u"                 # the cursor was stretching width
    _click(viewport, tool, V(3, 2, 0))
    assert tool.on_value(viewport, 5.0)
    assert _bbox(viewport.scene.mesh) == (0, 0, 5, 2)


def test_rectangle_from_the_centre_stays_centred(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    tool._set_from_center(viewport, True)
    _click(viewport, tool, V(0, 0, 0), V(2, 1, 0))
    assert _bbox(viewport.scene.mesh) == (-2, -1, 2, 1)
    assert tool.on_value(viewport, (6.0, 2.0))
    assert _bbox(viewport.scene.mesh) == (-3, -1, 3, 1)


def test_rectangle_window_closes_on_undo_and_on_a_click(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(3, 2, 0))
    viewport.history.undo()
    assert not tool.on_value(viewport, (4.0, 1.0))     # nothing comes back
    assert viewport.scene.mesh.faces == []
    _click(viewport, tool, V(0, 0, 0), V(3, 2, 0))
    _click(viewport, tool, V(10, 10, 0))               # a new first corner
    tool.on_cancel(viewport)
    assert not tool.on_value(viewport, (4.0, 1.0))
    assert _bbox(viewport.scene.mesh) == (0, 0, 3, 2)


def test_rectangle_refuses_zero_or_negative(viewport):
    tool = RectangleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(3, 2, 0))
    assert not tool.on_value(viewport, (0.0, 1.0))
    assert not tool.on_value(viewport, (-1.0, 1.0))
    assert _bbox(viewport.scene.mesh) == (0, 0, 3, 2)
    assert tool.on_value(viewport, (4.0, 1.0))         # window still open


# ---- Line ------------------------------------------------------------------
def test_line_segment_retyped_while_the_cursor_sits_on_its_end(viewport):
    tool = LineTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0))
    steps = len(viewport.history.undo_stack)
    assert tool.on_value(viewport, 3.0)
    assert _edges(viewport.scene.mesh) == [((0, 0, 0), (3, 0, 0))]
    assert len(viewport.history.undo_stack) == steps
    assert tool.start_point == V(3, 0, 0)         # the chain goes on from there
    assert tool.on_value(viewport, 1.5)           # and again
    assert _edges(viewport.scene.mesh) == [((0, 0, 0), (1.5, 0, 0))]
    assert len(viewport.history.undo_stack) == steps
    assert tool.on_value(viewport, -1.0)          # negative: the other way
    assert _edges(viewport.scene.mesh) == [((-1, 0, 0), (0, 0, 0))]
    assert tool.on_value(viewport, (1.0, 1.0, 0.0))   # a delta, too
    assert _edges(viewport.scene.mesh) == [((0, 0, 0), (1, 1, 0))]
    assert tool.chain_vertices == [V(0, 0, 0), V(1, 1, 0)]
    viewport.history.undo()
    assert viewport.scene.mesh.edges == []


def test_line_typed_segment_is_retyped_too(viewport):
    tool = LineTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0))
    tool.hover_point = V(1, 0, 0)
    assert tool.on_value(viewport, 2.0)
    assert tool.on_value(viewport, 4.0)
    assert _edges(viewport.scene.mesh) == [((0, 0, 0), (4, 0, 0))]


def test_line_moving_the_cursor_makes_the_number_the_next_segment(viewport):
    tool = LineTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0))
    tool.on_hover(_ctx(viewport, V(2, 1, 0)))     # the rubber band goes up
    assert tool.on_value(viewport, 1.0)
    assert _edges(viewport.scene.mesh) == [((0, 0, 0), (2, 0, 0)),
                                           ((2, 0, 0), (2, 1, 0))]


def test_line_closing_segment_is_retyped_with_the_chain_ended(viewport):
    tool = LineTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0),
           V(0, 0, 0))
    mesh = viewport.scene.mesh
    assert len(mesh.faces) == 1 and tool.start_point is None
    steps = len(viewport.history.undo_stack)
    assert tool.on_value(viewport, 3.0)          # (0,2) down past the start
    # …split at the corner it passes through, as any drawn edge is.
    assert ((0, -1, 0), (0, 0, 0)) in _edges(mesh)
    assert ((0, 0, 0), (0, 2, 0)) in _edges(mesh)
    assert tool.start_point is None              # still finished
    assert len(viewport.history.undo_stack) == steps
    assert tool.on_value(viewport, 2.0)          # back to closing it
    assert len(mesh.faces) == 1


def test_line_window_closes_after_an_undo(viewport):
    tool = LineTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0), V(2, 2, 0))
    assert tool.on_undo(viewport)                # Ctrl+Z mid-chain
    assert tool._last is None
    tool.on_cancel(viewport)
    assert not tool.on_value(viewport, 5.0)
    assert _edges(viewport.scene.mesh) == [((0, 0, 0), (2, 0, 0))]


# ---- Circle and Polygon ----------------------------------------------------
def _radii(mesh, center):
    return {round((v.position - center).length(), 6) for v in mesh.vertices}


@pytest.mark.parametrize("cls,sides", [(CircleTool, 24), (PolygonTool, 6)])
def test_circle_radius_retyped_right_after(viewport, cls, sides):
    tool = cls()
    _fresh(viewport, tool)
    _click(viewport, tool, V(1, 1, 0), V(3, 1, 0))
    mesh = viewport.scene.mesh
    assert tool.vcb_caption() == "Radius"
    assert not tool.value_is_unitless()          # a length, not a count
    steps = len(viewport.history.undo_stack)
    assert tool.on_value(viewport, 1.5)
    assert _radii(mesh, V(1, 1, 0)) == {1.5}
    assert mesh.vertex_at(V(2.5, 1, 0)) is not None     # same direction
    assert sorted(len(f.vertices) for f in mesh.faces) == [sides]
    assert len(viewport.history.undo_stack) == steps
    assert tool.sides == sides                   # not taken as a count
    viewport.history.undo()
    assert mesh.faces == []


def test_circle_sides_then_radius_both_retype(viewport):
    tool = CircleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0))
    steps = len(viewport.history.undo_stack)
    assert tool.on_segments_value(viewport, 12)        # «12s»
    assert tool.on_value(viewport, 1.0)                # then «1»
    mesh = viewport.scene.mesh
    assert sorted(len(f.vertices) for f in mesh.faces) == [12]
    assert _radii(mesh, V(0, 0, 0)) == {1.0}
    assert len(viewport.history.undo_stack) == steps


def test_circle_idle_number_is_the_side_count_outside_the_window(viewport):
    tool = CircleTool()
    _fresh(viewport, tool)
    assert tool.value_is_unitless() and tool.vcb_caption() == "Sides"
    assert tool.on_value(viewport, 8)                  # before any circle
    assert tool.sides == 8 and viewport.scene.mesh.faces == []
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0))
    viewport.history.undo()                            # the window closes
    assert tool.value_is_unitless() and tool.vcb_caption() == "Sides"
    assert tool.on_value(viewport, 12)
    assert tool.sides == 12 and viewport.scene.mesh.faces == []


def test_circle_window_closes_on_a_new_centre_and_on_esc(viewport):
    tool = CircleTool()
    _fresh(viewport, tool)
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0))
    tool.on_cancel(viewport)
    assert tool.vcb_caption() == "Sides"
    _click(viewport, tool, V(0, 0, 0), V(2, 0, 0))
    _click(viewport, tool, V(10, 0, 0))                # a new centre
    tool.on_cancel(viewport)
    assert tool.on_value(viewport, 6)                  # a count again
    assert _radii(viewport.scene.mesh, V(0, 0, 0)) == {2.0}


# ---- Through the keyboard, as the user types it ----------------------------
_KEYS = {";": Qt.Key_Semicolon, ".": Qt.Key_Period, "-": Qt.Key_Minus}


def _type(vp, text):
    for ch in text:
        key = _KEYS.get(ch) or Qt.Key(Qt.Key_0 + int(ch))
        if vp._value_buffer:
            ov = QKeyEvent(QEvent.ShortcutOverride, key, Qt.NoModifier, ch)
            vp.event(ov)
        vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, ch))
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                               Qt.NoModifier, "\r"))


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def test_typed_after_a_rectangle_through_the_value_box(win):
    win._activate_tool("rectangle")
    vp = win.viewport
    tool = vp.active_tool
    _click(vp, tool, V(0, 0, 0), V(3, 2, 0))
    steps = len(vp.history.undo_stack)
    w, h = vp._parse_value_buffer("4;1", comma_lists=True)
    _type(vp, "4;1")
    assert _bbox(vp.scene.mesh) == (0, 0, round(w, 6), round(h, 6))
    assert len(vp.history.undo_stack) == steps


def test_typed_after_a_circle_through_the_value_box(win):
    win._activate_tool("circle")
    vp = win.viewport
    tool = vp.active_tool
    _click(vp, tool, V(0, 0, 0), V(2, 0, 0))
    r = vp._parse_value_buffer("1", comma_lists=False)
    _type(vp, "1")
    assert _radii(vp.scene.mesh, V(0, 0, 0)) == {round(r, 6)}
    assert tool.sides == 24


def test_typed_after_a_line_through_the_value_box(win):
    win._activate_tool("line")
    vp = win.viewport
    tool = vp.active_tool
    _click(vp, tool, V(0, 0, 0), V(2, 0, 0))
    length = vp._parse_value_buffer("3", comma_lists=False)
    _type(vp, "3")
    assert _edges(vp.scene.mesh) == [((0, 0, 0), (round(length, 6), 0, 0))]
    assert math.isclose(tool.start_point.x(), length)
