# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tape Measure guides behave like the rest of the model (#627).

A guide could be clicked and selected, but Move left it where it was,
Rotate ignored it and Select All skipped it. Now:

- Move carries a selected guide (live, cancellable, one undo step with
  whatever else moves), and with nothing selected a click on a guide grabs
  it — a loose edge under the cursor still wins, the face behind does not;
- Move + Ctrl copies guides, and «3x» / «/3» lay a row of them;
- Rotate turns selected guides, and Rotate + Ctrl copies them;
- Select All and Invert Selection count the model's guides.
"""
from __future__ import annotations

import math
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.group import Group
from core.guide import Guide
from core.history import History, MoveGuidesCommand, RotateGuidesCommand
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.move import MoveTool
from tools.rotate import RotateTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _near(a, b) -> bool:
    return (a - b).length() < 1e-6


def _viewport(scene, history, guide=None, edge=None, face=None):
    """A stub viewport; ``guide`` / ``edge`` / ``face`` are what lies under
    the cursor."""
    return SimpleNamespace(
        scene=scene, history=history,
        pick_group=lambda x, y: None, pick_edge=lambda x, y: edge,
        pick_face=lambda x, y: face, pick_guide=lambda x, y: guide,
        pick_text_label=lambda x, y, rect_only=False: None,
        flash_status=lambda *a, **k: None,
        update=lambda: None)


def _ctx(viewport, world):
    screen = SimpleNamespace(x=lambda: 0, y=lambda: 0)
    return SimpleNamespace(viewport=viewport, screen=screen, world=world,
                           modifiers=0)


def _square(mesh, x0=0.0):
    return mesh.add_face([V(x0, 0), V(x0 + 1, 0), V(x0 + 1, 1), V(x0, 1)])


# ---- the commands ---------------------------------------------------------------

def test_move_command_slides_a_guide_line_and_undoes():
    scene = Scene()
    history = History(scene)
    line = Guide(V(0, 1), V(1, 0))
    scene.guides.append(line)

    history.execute(MoveGuidesCommand([line], V(0, 2, 3)))
    assert _near(line.point, V(0, 3, 3))
    assert _near(line.direction, V(1, 0))          # parallel to itself
    history.undo()
    assert _near(line.point, V(0, 1))
    history.redo()
    assert _near(line.point, V(0, 3, 3))


def test_move_command_carries_a_guide_points_origin():
    """A guide point measured from a vertex draws a dashed segment from
    ``origin``: both ends travel, so the segment keeps its shape."""
    scene = Scene()
    history = History(scene)
    pt = Guide(V(1.5, 0), origin=V(0, 0))
    scene.guides.append(pt)

    history.execute(MoveGuidesCommand([pt], V(1, 1)))
    assert _near(pt.point, V(2.5, 1))
    assert _near(pt.origin, V(1, 1))
    history.undo()
    assert _near(pt.point, V(1.5, 0))
    assert _near(pt.origin, V(0, 0))


def test_rotate_command_turns_point_direction_and_origin():
    scene = Scene()
    history = History(scene)
    line = Guide(V(2, 0), V(1, 0))
    pt = Guide(V(3, 0), origin=V(1, 0))
    scene.guides.extend([line, pt])

    history.execute(RotateGuidesCommand([line, pt], V(0, 0), V(0, 0, 1), 90))
    assert _near(line.point, V(0, 2))
    assert _near(line.direction, V(0, 1))
    assert _near(pt.point, V(0, 3))
    assert _near(pt.origin, V(0, 1))
    history.undo()                                   # exact, no drift
    assert line.point == V(2, 0) and line.direction == V(1, 0)
    assert pt.point == V(3, 0) and pt.origin == V(1, 0)


# ---- Move: a selected guide -------------------------------------------------------

def test_move_tool_drags_a_selected_guide():
    scene = Scene()
    history = History(scene)
    line = Guide(V(0, 1), V(1, 0))
    scene.guides.append(line)
    scene.select([line])
    vp = _viewport(scene, history)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0, 1)))
    assert tool.start_point is not None, "Move refused a selected guide"
    tool.on_hover(_ctx(vp, V(0, 2)))
    assert _near(line.point, V(0, 2))                # follows live
    tool.on_click(_ctx(vp, V(0, 4)))
    assert _near(line.point, V(0, 4))

    history.undo()                                   # one undo step
    assert _near(line.point, V(0, 1))


def test_esc_puts_the_guide_back():
    scene = Scene()
    history = History(scene)
    line = Guide(V(0, 1), V(1, 0))
    scene.guides.append(line)
    scene.select([line])
    vp = _viewport(scene, history)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0, 1)))
    tool.on_hover(_ctx(vp, V(0, 3)))
    tool.on_cancel(vp)
    assert _near(line.point, V(0, 1))
    assert not history.undo_stack


def test_guide_and_geometry_move_in_one_undo_step():
    scene = Scene()
    history = History(scene)
    face = _square(scene.mesh)
    line = Guide(V(0, 2), V(1, 0))
    scene.guides.append(line)
    scene.select([face, line])
    vp = _viewport(scene, history)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0, 0)))
    tool.on_click(_ctx(vp, V(5, 0)))
    assert _near(line.point, V(5, 2))
    assert any(_near(p, V(5, 0)) for p in scene.faces[0].vertices)
    assert len(history.undo_stack) == 1

    history.undo()
    assert _near(line.point, V(0, 2))
    assert any(_near(p, V(0, 0)) for p in scene.faces[0].vertices)


# ---- Move: the guide under the cursor ---------------------------------------------

def test_click_on_a_guide_grabs_it_not_the_face_behind():
    scene = Scene()
    history = History(scene)
    face = _square(scene.mesh)
    line = Guide(V(0, 0.5), V(1, 0))                # crosses the face
    scene.guides.append(line)
    vp = _viewport(scene, history, guide=line, face=face)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0.5, 0.5)))
    assert tool._moved_guides == [line]
    assert not tool._positions and not tool._groups
    tool.on_click(_ctx(vp, V(0.5, 2.5)))
    assert _near(line.point, V(0, 2.5))
    assert any(_near(p, V(0, 0)) for p in scene.faces[0].vertices)  # face stays


def test_a_loose_edge_under_the_cursor_wins_over_the_guide():
    scene = Scene()
    history = History(scene)
    face = _square(scene.mesh)
    edge = scene.edges[0]
    line = Guide(V(0, 0), V(1, 0))
    scene.guides.append(line)
    vp = _viewport(scene, history, guide=line, edge=edge, face=face)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0.5, 0)))
    assert tool._moved_guides == []
    assert tool._positions                           # the edge is grabbed
    tool.on_cancel(vp)


def test_a_selection_keeps_the_guide_as_a_snap_target():
    """With something selected, a click on a guide starts moving the
    selection from there — the guide is not taken along."""
    scene = Scene()
    history = History(scene)
    face = _square(scene.mesh)
    line = Guide(V(0, 3), V(1, 0))
    scene.guides.append(line)
    scene.select([face])
    vp = _viewport(scene, history, guide=line)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0, 3)))
    assert tool._moved_guides == []
    tool.on_click(_ctx(vp, V(0, 5)))
    assert _near(line.point, V(0, 3))


# ---- Move + Ctrl: copies and rows -----------------------------------------------------

def test_ctrl_copies_a_guide_and_3x_makes_a_row():
    scene = Scene()
    history = History(scene)
    line = Guide(V(0, 0), V(1, 0))
    scene.guides.append(line)
    vp = _viewport(scene, history, guide=line)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0, 0)))                 # grabs the hovered guide
    tool._toggle_copy(vp, say=False)
    tool.on_hover(_ctx(vp, V(0, 1)))
    assert _near(line.point, V(0, 0))                # the original stays
    assert tool._base_segments                       # the ghost is drawn
    tool.on_click(_ctx(vp, V(0, 1)))
    assert len(scene.guides) == 2
    assert _near(scene.guides[1].point, V(0, 1))
    assert _near(scene.guides[1].direction, V(1, 0))

    assert tool.on_array_value(vp, 3, "x")          # «3x»
    ys = sorted(round(g.point.y(), 6) for g in scene.guides)
    assert ys == [0.0, 1.0, 2.0, 3.0]
    history.undo()                                   # the row is one step
    assert scene.guides == [line]


def test_copy_of_a_hovered_guide_does_not_copy_the_face_behind():
    scene = Scene()
    history = History(scene)
    face = _square(scene.mesh)
    line = Guide(V(0, 0.5), V(1, 0))
    scene.guides.append(line)
    vp = _viewport(scene, history, guide=line, face=face)
    tool = MoveTool()

    tool.on_click(_ctx(vp, V(0.5, 0.5)))
    tool._toggle_copy(vp, say=False)
    tool.on_click(_ctx(vp, V(0.5, 3.5)))
    assert len(scene.faces) == 1
    assert len(scene.guides) == 2


# ---- the snap leaves the dragged guide out ----------------------------------------------

def test_dragged_guide_stays_out_of_the_snap():
    scene = Scene()
    history = History(scene)
    moving = Guide(V(0, 1), V(1, 0))
    scene.guides.append(moving)
    scene.select([moving])
    vp = _viewport(scene, history)
    tool = MoveTool()

    assert tool.moving_guide_ids() == set()
    tool.on_click(_ctx(vp, V(0, 1)))
    assert tool.moving_guide_ids() == {id(moving)}
    tool.on_click(_ctx(vp, V(0, 2)))
    assert tool.moving_guide_ids() == set()


def test_viewport_snap_scene_skips_the_dragged_guide():
    from views.viewport import Viewport
    scene = Scene()
    moving = Guide(V(0, 1), V(1, 0))
    still = Guide(V(3, 3))                          # a guide point
    scene.guides.extend([moving, still])
    tool = SimpleNamespace(moving_guide_ids=lambda: {id(moving)})
    vp = SimpleNamespace(
        scene=scene, active_tool=tool,
        _guide_snap_segment=lambda g: g.segment(),
        _clip_segment_front=lambda a, b: (a, b),
        _selection_box_points=lambda skip=None: [])
    snap = Viewport._snap_scene(vp)
    ends = [(e.a, e.b) for e in snap.edges]
    assert any(_near(a, V(3, 3)) and _near(b, V(3, 3)) for a, b in ends)
    assert not any(_near(a, moving.a) for a, _ in ends)


# ---- Rotate -----------------------------------------------------------------------------

def _rctx(vp, x, y):
    return ToolContext(viewport=vp, world=V(x, y), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _turn(vp, tool, deg, copy=False):
    """Centre at the origin, reference on +X, then drop at ``deg``."""
    tool.on_click(_rctx(vp, 0, 0))
    tool.on_click(_rctx(vp, 2, 0))
    if copy:
        tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    a = math.radians(deg)
    tool.on_hover(_rctx(vp, 2 * math.cos(a), 2 * math.sin(a)))
    tool.on_click(_rctx(vp, 2 * math.cos(a), 2 * math.sin(a)))


def test_rotate_turns_a_selected_guide():
    scene = Scene()
    history = History(scene)
    line = Guide(V(2, 0), V(1, 0))
    scene.guides.append(line)
    scene.select([line])
    vp = _viewport(scene, history)
    _turn(vp, RotateTool(), 90.0)

    assert _near(line.point, V(0, 2))
    assert _near(line.direction, V(0, 1))
    history.undo()
    assert _near(line.point, V(2, 0))
    assert _near(line.direction, V(1, 0))


def test_rotate_with_ctrl_copies_the_guide():
    scene = Scene()
    history = History(scene)
    line = Guide(V(2, 0), V(1, 0))
    scene.guides.append(line)
    scene.select([line])
    vp = _viewport(scene, history)
    _turn(vp, RotateTool(), 90.0, copy=True)

    assert _near(line.point, V(2, 0))                # the original stays
    assert len(scene.guides) == 2
    assert _near(scene.guides[1].point, V(0, 2))
    assert _near(scene.guides[1].direction, V(0, 1))


# ---- Select All / Invert Selection --------------------------------------------------------

def test_invert_selection_counts_the_models_guides():
    scene = Scene()
    face = _square(scene.mesh)
    line = Guide(V(0, 2), V(1, 0))
    scene.guides.append(line)
    scene.select([face])

    scene.invert_selection()
    assert line in scene.selection
    assert face not in scene.selection


def test_invert_selection_inside_a_group_leaves_guides_out():
    scene = Scene()
    outer = Group(Mesh(), name="caja")
    _square(outer.mesh)
    scene.groups.append(outer)
    line = Guide(V(0, 2), V(1, 0))
    scene.guides.append(line)

    scene.begin_group_edit(outer)
    scene.invert_selection()
    assert line not in scene.selection
    scene.end_group_edit()


def test_select_all_takes_the_guides_in_the_model_only():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _square(scene.mesh)
        line = Guide(V(0, 3), V(1, 0))
        pt = Guide(V(4, 4))
        scene.guides.extend([line, pt])

        win._on_select_all()
        assert line in scene.selection and pt in scene.selection

        outer = Group(Mesh(), name="caja")
        _square(outer.mesh, 5)
        scene.groups.append(outer)
        scene.begin_group_edit(outer)
        win._on_select_all()
        assert line not in scene.selection and pt not in scene.selection
        scene.end_group_edit()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
