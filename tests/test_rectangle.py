# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rectangle tool — on-screen dimensions and typed exact size (VCB).

Drawing a rectangle shows a live ``width × height`` readout, and typing
``W;H`` + Enter lays the rectangle at that exact size, in the quadrant the
cursor is heading toward.

Headless: ``QVector3D`` values + a stub viewport.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.rectangle import RectangleTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _Stub:
    def __init__(self) -> None:
        self.scene = Scene()
        self.history = History(self.scene)

    def update(self) -> None:
        pass


def _corner_keys(face):
    return {(round(v.x(), 3), round(v.y(), 3), round(v.z(), 3)) for v in face.vertices}


def test_dimension_label_tracks_drag():
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)
    text, _ = t.value_label()
    assert text == "5.00 × 4.00 m"


def test_label_none_before_drag():
    t = RectangleTool()
    assert t.value_label() is None


def test_typed_dimensions_build_exact_rectangle():
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)            # heading +X, +Y
    assert t.on_value(vp, (3.0, 2.0)) is True
    assert len(vp.scene.faces) == 1
    assert _corner_keys(vp.scene.faces[0]) == {
        (0, 0, 0), (3, 0, 0), (3, 2, 0), (0, 2, 0)
    }


def test_typed_dimensions_follow_drag_quadrant():
    # Cursor heading into the -X, -Y quadrant → the exact rectangle lays there.
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(-1, -1)
    assert t.on_value(vp, (3.0, 2.0)) is True
    assert _corner_keys(vp.scene.faces[0]) == {
        (0, 0, 0), (-3, 0, 0), (-3, -2, 0), (0, -2, 0)
    }


def test_typed_dimensions_rejects_non_pair():
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)
    assert t.on_value(vp, 3.0) is False          # a bare length isn't a W×H
    assert t.on_value(vp, (1.0, 2.0, 3.0)) is False  # a 3D delta isn't either
    assert len(vp.scene.faces) == 0


def test_typed_single_dimension_builds_square_when_locked():
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)
    t._arrow_square_lock = True

    assert t.on_value(vp, 3.0) is True
    assert _corner_keys(vp.scene.faces[0]) == {
        (0, 0, 0), (3, 0, 0), (3, 3, 0), (0, 3, 0)
    }


# ---- Ctrl: from the centre (issue #39, @pacaeiro) ------------------------

def test_ctrl_toggles_centre_mode_and_the_badge():
    from PySide6.QtCore import Qt
    vp = _Stub()
    vp.flashed = []
    vp.flash_status = lambda t, *a, **k: vp.flashed.append(t)
    t = RectangleTool()
    t.icon = "rectangle"
    t.on_activate(vp)
    assert t._from_center is False and t.icon == "rectangle"
    assert t.on_key(vp, Qt.Key_Control, Qt.NoModifier) is True
    assert t._from_center is True and t.icon == "rectangle_center"
    assert t.on_key(vp, Qt.Key_Control, Qt.NoModifier) is True
    assert t._from_center is False and t.icon == "rectangle"
    assert len(vp.flashed) == 2


def test_from_the_centre_the_second_click_is_a_corner():
    from PySide6.QtCore import QPointF, Qt
    from tools.base import ToolContext
    vp = _Stub()
    t = RectangleTool()
    t.on_activate(vp)
    t.on_key(vp, Qt.Key_Control, Qt.NoModifier)

    def ctx(x, y):
        return ToolContext(viewport=vp, world=V(x, y), screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None)
    t.on_click(ctx(1, 1))                      # the centre
    t.hover_point = V(3, 2)
    text, mid = t.value_label()
    assert text == "4.00 × 2.00 m" and (mid - V(1, 1)).length() < 1e-9
    t.on_click(ctx(3, 2))                      # a corner
    assert _corner_keys(vp.scene.faces[0]) == {
        (-1, 0, 0), (3, 0, 0), (3, 2, 0), (-1, 2, 0)}


def test_typed_sizes_from_the_centre_are_the_whole_width_and_height():
    from PySide6.QtCore import Qt
    vp = _Stub()
    t = RectangleTool()
    t.on_activate(vp)
    t.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)
    assert t.on_value(vp, (4.0, 2.0)) is True
    assert _corner_keys(vp.scene.faces[0]) == {
        (-2, -1, 0), (2, -1, 0), (2, 1, 0), (-2, 1, 0)}


def test_picking_the_tool_up_again_starts_corner_wise():
    from PySide6.QtCore import Qt
    vp = _Stub()
    t = RectangleTool()
    t.on_activate(vp)
    t.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    t.on_activate(vp)
    assert t._from_center is False


def test_square_from_the_centre_is_a_true_square():
    # Regression: the square nudge used to hold the mirror fixed and move the
    # cursor, growing the WRONG side. A near-square drag from the centre came
    # out as 4.00 × 4.10 m yet was still labelled "Cuadrado".
    t = RectangleTool()
    t.on_activate(_Stub())
    t._from_center = True
    t.start_point = V(0, 0)
    t.hover_point = V(2.0, 1.95)                   # within SQUARE_TOL
    anchor, far = t._span(t.hover_point)
    du, dv = t._dimensions(anchor, far)
    assert abs(abs(du) - abs(dv)) < 1e-9           # a real square
    assert abs(abs(du) - 4.0) < 1e-9               # grown to the longer side
    assert ((anchor + far) * 0.5).length() < 1e-9  # still centred on the click
    text, mid = t.value_label()
    assert text.endswith("(Cuadrado)")
    assert mid.length() < 1e-9


def test_from_the_centre_shows_no_square_cue_when_it_is_not_square():
    t = RectangleTool()
    t.on_activate(_Stub())
    t._from_center = True
    t.start_point = V(0, 0)
    t.hover_point = V(2.0, 1.5)
    text, _ = t.value_label()
    assert text == "4.00 × 3.00 m"
    assert "Cuadrado" not in text


def test_committing_a_square_from_the_centre_builds_real_square_corners():
    t = RectangleTool()
    t.on_activate(_Stub())
    t._from_center = True
    t.start_point = V(0, 0)
    t.hover_point = V(2.0, 1.95)
    anchor, far = t._span(t.hover_point)
    corners = t._corners(anchor, far)
    sides = [(corners[(i + 1) % 4] - corners[i]).length() for i in range(4)]
    assert max(sides) - min(sides) < 1e-9
    assert all(abs(s - 4.0) < 1e-9 for s in sides)


def test_shift_locks_square_inference_while_held():
    from PySide6.QtCore import QPointF, Qt
    from tools.base import ToolContext

    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)

    def hover(x, y, modifiers):
        t.on_hover(ToolContext(viewport=vp, world=V(x, y), screen=QPointF(0, 0),
                               modifiers=modifiers, snap=None))

    hover(4.0, 3.9, Qt.ShiftModifier)
    assert t._square_locked()
    hover(6.0, 2.0, Qt.ShiftModifier)
    _, far = t._span(t.hover_point)
    assert t._dimensions(t.start_point, far) == (6.0, 6.0)

    hover(6.0, 2.0, Qt.NoModifier)
    assert not t._square_locked()
    _, far = t._span(t.hover_point)
    assert t._dimensions(t.start_point, far) == (6.0, 2.0)


def test_down_toggles_square_lock_after_square_inference():
    from PySide6.QtCore import QPointF, Qt
    from tools.base import ToolContext

    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.on_hover(ToolContext(viewport=vp, world=V(4.0, 3.9), screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None))

    assert t.on_key(vp, Qt.Key_Down, Qt.NoModifier) is True
    t.on_hover(ToolContext(viewport=vp, world=V(6.0, 2.0), screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None))
    _, far = t._span(t.hover_point)
    assert t._dimensions(t.start_point, far) == (6.0, 6.0)

    assert t.on_key(vp, Qt.Key_Down, Qt.NoModifier) is True
    t.on_hover(ToolContext(viewport=vp, world=V(6.0, 2.0), screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None))
    _, far = t._span(t.hover_point)
    assert t._dimensions(t.start_point, far) == (6.0, 2.0)
