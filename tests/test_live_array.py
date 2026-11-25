# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Live arrays (core/array.py): «3x» / «/3» after copying groups or
components leaves ONE container that remembers the count, the step and
the mode, so the copies can be laid out again later — in one undo step,
after saving and reopening, after the array was moved or opened.

Synthetic models only: a pillar (a 0.3 m box as a classic group or a
component instance) copied 3 m along Y, or turned about the Z axis."""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, copy_group, iter_placements
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.move import MoveTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashed = []

    def update(self):
        pass

    def flash_status(self, msg, *a, **k):
        self.flashed.append(msg)

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None

    def pick_group(self, x, y):
        return None


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=V(x, y, z), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _pillar_mesh(x0=0.0, y0=0.0, size=0.3):
    m = Mesh()
    m.add_face([V(x0, y0), V(x0 + size, y0), V(x0 + size, y0 + size),
                V(x0, y0 + size)])
    return m


def _pillar(scene, component=False, x0=0.0):
    g = Group(_pillar_mesh(x0), name="Pilar")
    if component:
        g.xform = QMatrix4x4()
        g.component = True
    scene.groups.append(g)
    scene.selection.clear()
    scene.selection.add(g)
    return g


def _corner(group):
    """The world position of the pillar's first corner."""
    for g, m in iter_placements(group):
        p = g.mesh.faces[0].vertices[0]
        return m.map(p) if m is not None else QVector3D(p)
    raise AssertionError("no placement")


def _child_corners(container):
    out = []
    for c in container.children:
        p = _corner(c)
        if container.xform is not None:
            p = container.xform.map(p)
        out.append((round(p.x(), 6), round(p.y(), 6), round(p.z(), 6)))
    return out


def _move_array(vp, count, mode, dy=3.0):
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 0, dy))
    assert tool.on_array_value(vp, count, mode)
    return tool


# ---- Move -------------------------------------------------------------------

def test_3x_on_a_group_leaves_one_live_array():
    scene = Scene()
    g = _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 4, "x")
    assert len(scene.groups) == 1
    arr = scene.groups[0]
    assert arr.array["count"] == 4 and arr.array["mode"] == "x"
    assert arr.children[0] is g                      # the original is inside
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 3, 6, 9, 12]
    assert scene.selection == {arr}
    vp.history.undo()
    assert scene.groups == [g] and g.xform is None   # as it was before
    vp.history.redo()
    assert scene.groups == [arr]
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 3, 6, 9, 12]


def test_divide_spreads_the_copies_over_the_distance():
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 4, "/", dy=12.0)
    arr = scene.groups[0]
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 3, 6, 9, 12]


def test_retyping_re_lays_the_live_array():
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    tool = _move_array(vp, 4, "x")
    assert tool.on_array_value(vp, 2, "x")
    assert len(scene.groups) == 1
    assert len(scene.groups[0].children) == 3
    vp.history.undo()
    assert len(scene.groups) == 1 and scene.groups[0].array is None


def test_loose_geometry_still_makes_plain_copies():
    scene = Scene()
    face = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    scene.selection = [face]
    vp = _Vp(scene)
    _move_array(vp, 3, "x")
    assert scene.groups == []
    assert len(scene.mesh.faces) == 4


def test_one_copy_is_not_an_array():
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 1, "x")
    assert len(scene.groups) == 2
    assert all(getattr(g, "array", None) is None for g in scene.groups)


# ---- Editing it later ---------------------------------------------------------

def test_more_copies_later_in_one_undo_step():
    from core.array import EditArrayCommand
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 4, "x")
    arr = scene.groups[0]
    before = list(arr.children)
    vp.history.execute(EditArrayCommand(arr, {"count": 6}))
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 3, 6, 9, 12, 15, 18]
    assert arr.children[0] is before[0]
    vp.history.undo()
    assert arr.children == before and arr.array["count"] == 4
    vp.history.redo()
    assert len(arr.children) == 7


def test_new_spacing_and_mode_later():
    from core.array import EditArrayCommand
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 4, "x")
    arr = scene.groups[0]
    vp.history.execute(EditArrayCommand(arr, {"step": [0.0, 1.5, 0.0]}))
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 1.5, 3, 4.5, 6]
    vp.history.execute(EditArrayCommand(arr, {"mode": "/"}))
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 0.375, 0.75,
                                                        1.125, 1.5]


def test_a_component_array_shares_the_definition():
    from core.array import EditArrayCommand
    scene = Scene()
    g = _pillar(scene, component=True)
    vp = _Vp(scene)
    _move_array(vp, 3, "x")
    arr = scene.groups[0]
    assert all(c.mesh is g.mesh for c in arr.children)
    vp.history.execute(EditArrayCommand(arr, {"count": 5}))
    assert all(c.mesh is g.mesh and c.is_component() for c in arr.children)


def test_what_else_was_put_inside_stays():
    from core.array import EditArrayCommand
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 2, "x")
    arr = scene.groups[0]
    extra = Group(_pillar_mesh(5.0), name="Viga")
    arr.children.append(extra)
    vp.history.execute(EditArrayCommand(arr, {"count": 3}))
    assert extra in arr.children
    assert len(arr.children) == 1 + 1 + 3           # original, extra, copies


# ---- Rotate -------------------------------------------------------------------

def test_a_polar_array_is_live_too():
    from core.array import EditArrayCommand
    from tools.rotate import RotateTool
    scene = Scene()
    g = _pillar(scene, x0=2.0)
    vp = _Vp(scene)
    tool = RotateTool()
    # Fake the rotate-copy that was just made: 90° about Z at the origin.
    from core.history import CompoundCommand
    from core.array import placed_copy
    from core.history import rotation_matrix, InsertGroupCommand
    m = rotation_matrix(V(0, 0), V(0, 0, 1), 90.0)
    first = InsertGroupCommand(placed_copy(g, m))
    vp.history.execute(first)
    tool._last = {"cmd": first, "build": lambda degs: None, "deg": 90.0,
                  "copy": True, "sign": 1.0, "live": [g],
                  "center": V(0, 0), "axis": V(0, 0, 1)}
    assert tool.on_array_value(vp, 3, "x")
    arr = scene.groups[0]
    assert len(scene.groups) == 1 and arr.array["kind"] == "rotate"
    got = [(round(x, 6) + 0.0, round(y, 6) + 0.0)
           for x, y, _z in _child_corners(arr)]
    assert got == [(2, 0), (0, 2), (-2, 0), (0, -2)]
    vp.history.execute(EditArrayCommand(arr, {"count": 7, "angle": 45.0}))
    angles = sorted(round(math.degrees(math.atan2(y, x))) % 360
                    for x, y, _z in _child_corners(arr))
    assert angles == [0, 45, 90, 135, 180, 225, 270, 315]


# ---- It stays true ------------------------------------------------------------

def test_saved_and_reopened_it_is_still_live(tmp_path):
    from core.array import EditArrayCommand, can_edit
    from formats import igz
    scene = Scene()
    _pillar(scene, component=True)
    vp = _Vp(scene)
    _move_array(vp, 3, "x")
    path = tmp_path / "matriz.igz"
    igz.save_scene(scene, path)
    scene2 = Scene()
    igz.load_into(scene2, path)
    arr = scene2.groups[0]
    assert can_edit(arr) and arr.array["count"] == 3
    History(scene2).execute(EditArrayCommand(arr, {"count": 5}))
    assert [y for _x, y, _z in _child_corners(arr)] == [0, 3, 6, 9, 12, 15]


def test_a_turned_array_opened_still_steps_its_own_way():
    """Turn the array 90° (its matrix), open it (the matrix goes down into
    the children), then add a copy: it lands next in line, not along the
    world's Y."""
    from core.array import EditArrayCommand
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 2, "x")
    arr = scene.groups[0]
    turn = QMatrix4x4()
    turn.rotate(90.0, V(0, 0, 1))
    arr.xform = turn * arr.xform
    Scene._bake_container_xform(arr)
    vp.history.execute(EditArrayCommand(arr, {"count": 3}))
    xs = [x for x, _y, _z in _child_corners(arr)]
    assert xs == pytest.approx([0, -3, -6, -9], abs=1e-6)


def test_a_copied_array_names_its_own_children():
    from core.array import EditArrayCommand, can_edit, sources_of
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 2, "x")
    arr = scene.groups[0]
    twin = copy_group(arr, V(10, 0))
    assert can_edit(twin)
    assert sources_of(twin)[0] is twin.children[0]
    scene.groups.append(twin)
    vp.history.execute(EditArrayCommand(twin, {"count": 4}))
    assert len(twin.children) == 5 and len(arr.children) == 3


def test_explode_gives_back_the_plain_copies():
    from core.history import ExplodeGroupCommand
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 3, "x")
    arr = scene.groups[0]
    vp.history.execute(ExplodeGroupCommand(arr))
    assert len(scene.groups) == 4
    assert all(getattr(g, "array", None) is None for g in scene.groups)


# ---- Full turn and the hint after a copy (2026-11-25) --------------------------

def test_a_full_turn_spreads_them_round_without_landing_on_the_original():
    """«8 posts around»: 7 copies sharing 360°, every 45° — the last one
    does not land back on the original."""
    from core.array import MakeArrayCommand, rotate_recipe
    scene = Scene()
    g = _pillar(scene, x0=2.0)
    vp = _Vp(scene)
    vp.history.execute(MakeArrayCommand(
        [g], rotate_recipe(V(0, 0), V(0, 0, 1), 360.0, 7, "/")))
    arr = scene.groups[0]
    angles = sorted(round(math.degrees(math.atan2(y, x))) % 360
                    for x, y, _z in _child_corners(arr))
    assert angles == [0, 45, 90, 135, 180, 225, 270, 315]


def _hint(key, tool):
    from core.i18n import set_language
    from views.status_hints import hint_for
    out = {}
    for lang in ("en", "es"):
        set_language(lang)
        out[lang] = hint_for(key, tool, None, "parallel_perp")
    set_language("en")
    return out


def test_after_a_move_copy_the_status_bar_says_to_type_3x():
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 0, 3))
    hints = _hint("move", tool)
    assert "3x" in hints["en"] and "/3" in hints["en"]
    assert "Intro" in hints["es"]
    assert all(len(h) <= 112 for h in hints.values())     # fits the bar


def test_after_a_rotate_copy_the_status_bar_says_to_type_3x():
    from tests.test_rotate_array import _Vp as _RVp, _rotate_copy
    from tools.rotate import RotateTool
    scene = Scene()
    _pillar(scene, x0=2.0)
    vp = _RVp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, 45.0)
    hints = _hint("rotate", tool)
    assert "3x" in hints["en"] and "angle" in hints["en"]
    assert "ángulo" in hints["es"]
    assert all(len(h) <= 112 for h in hints.values())


def test_a_plain_rotation_says_nothing_about_arrays():
    from tests.test_rotate_array import _Vp as _RVp
    from tools.rotate import RotateTool
    scene = Scene()
    _pillar(scene, x0=2.0)
    vp = _RVp(scene)
    tool = RotateTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 2, 0))
    tool.on_click(_ctx(vp, 0, 2))                     # no Ctrl: a rotation
    assert "3x" not in _hint("rotate", tool)["en"]


# ---- Copies deleted by hand inside the array (2026-11-25) ----------------------

def _delete_inside(vp, arr, which):
    """Open the array, delete ``which`` of its children the way the Delete
    key does, and leave it."""
    from core.history import DeleteGroupCommand
    scene = vp.scene
    scene.begin_group_edit(arr)
    for c in which:
        vp.history.execute(DeleteGroupCommand(c))
    scene.end_group_edit()


def test_with_every_copy_deleted_there_is_no_array():
    """«Si no hay ninguna copia no hay matriz»: the original alone in the
    container is a group, not an array — and undo brings the array back."""
    from core.array import can_edit, copies_of
    scene = Scene()
    g = _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 3, "x")
    arr = scene.groups[0]
    _delete_inside(vp, arr, copies_of(arr))
    assert arr.children == [g]
    assert not can_edit(arr)
    vp.history.undo()
    assert can_edit(arr)


def test_some_copies_deleted_are_counted_out_and_come_back_on_a_relayout():
    from core.array import EditArrayCommand, can_edit, copies_of, removed_copies
    scene = Scene()
    _pillar(scene)
    vp = _Vp(scene)
    _move_array(vp, 4, "x")
    arr = scene.groups[0]
    _delete_inside(vp, arr, copies_of(arr)[1:3])
    assert can_edit(arr)
    assert len(copies_of(arr)) == 2 and removed_copies(arr) == 2
    vp.history.execute(EditArrayCommand(arr, {"count": 4}))
    assert removed_copies(arr) == 0 and len(arr.children) == 5
