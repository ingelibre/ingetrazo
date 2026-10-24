# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Redo puts back the SAME group a command made (issue #737).

Make Group → Explode → undo twice → redo twice: the first redo grouped the
box again, the second did nothing and was dropped from the redo stack. Make
Group built a brand-new Group on every ``do``, so on redo the group in the
scene was not the one Explode held. The same went for a container made
over groups (Make Group, Make Component) and for one made inside an open
group. Each case: do → next command → undo ×2 → redo ×2 must end where the
first pass did, with nothing left to redo."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.history import (ExplodeGroupCommand, GroupInContextCommand,
                          History, MakeComponentOfCommand, MakeGroupCommand,
                          MakeNestedGroupCommand, MoveGroupCommand,
                          ReplaceComponentCommand)
from core.mesh import Mesh
from core.scene import Scene


def _loose_box(scene, x=0.0):
    """Six faces of a 1 m box straight into the loose mesh."""
    p = [V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)]
    q = [v + V(0, 0, 1) for v in p]
    m = scene.mesh
    m.add_face(list(reversed(p)))
    m.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        m.add_face([p[i], p[j], q[j], q[i]])


def _box_group(x, name):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return Group(m, name=name)


def _state(scene):
    return (len(scene.mesh.faces), len(scene.mesh.edges),
            sorted(len(g.mesh.faces) for g in scene.groups),
            len(scene.groups))


def _replay(scene, hist, first, second):
    """``first`` then ``second(scene)``, undo both, redo both: the model
    must come back exactly as after the first pass."""
    hist.execute(first)
    hist.execute(second(scene))
    after = _state(scene)
    assert hist.undo() and hist.undo()
    assert hist.redo()
    assert hist.redo(), "the second redo was lost"
    assert _state(scene) == after
    assert not hist.redo_stack
    # And once more, the whole way back and forth.
    assert hist.undo() and hist.undo() and hist.redo() and hist.redo()
    assert _state(scene) == after


def test_make_group_then_explode_redoes_both():
    scene = Scene()
    hist = History(scene)
    _loose_box(scene)
    before = _state(scene)
    cmd = MakeGroupCommand(list(scene.mesh.faces), list(scene.mesh.edges))
    _replay(scene, hist, cmd,
            lambda s: ExplodeGroupCommand(s.groups[-1]))
    assert _state(scene) == before          # exploded: loose box again
    assert not scene.groups


def test_redo_of_make_group_brings_back_the_same_group():
    scene = Scene()
    hist = History(scene)
    _loose_box(scene)
    cmd = MakeGroupCommand(list(scene.mesh.faces), list(scene.mesh.edges))
    hist.execute(cmd)
    made = scene.groups[-1]
    hist.undo()
    hist.redo()
    assert scene.groups[-1] is made
    assert len(made.mesh.faces) == 6
    assert not scene.mesh.faces


def test_make_group_then_move_redoes_both():
    """Any command holding the new group, not only Explode."""
    scene = Scene()
    hist = History(scene)
    _loose_box(scene)
    cmd = MakeGroupCommand(list(scene.mesh.faces), list(scene.mesh.edges))
    _replay(scene, hist, cmd,
            lambda s: MoveGroupCommand(s.groups[-1], V(3, 0, 0)))
    xs = [v.position.x() for v in scene.groups[-1].mesh.vertices]
    assert min(xs) == 3.0                   # moved, once


def test_group_of_groups_then_explode_redoes_both():
    scene = Scene()
    hist = History(scene)
    scene.groups.extend([_box_group(0, "A"), _box_group(3, "B")])
    cmd = MakeNestedGroupCommand([], [], list(scene.groups), name="Fila")
    _replay(scene, hist, cmd,
            lambda s: ExplodeGroupCommand(s.groups[-1]))
    assert sorted(g.name for g in scene.groups) == ["A", "B"]


def test_group_of_loose_geometry_and_groups_then_explode_redoes_both():
    scene = Scene()
    hist = History(scene)
    _loose_box(scene, x=6.0)
    scene.groups.extend([_box_group(0, "A"), _box_group(3, "B")])
    cmd = MakeNestedGroupCommand(list(scene.mesh.faces),
                                 list(scene.mesh.edges),
                                 list(scene.groups), name="Fila")
    _replay(scene, hist, cmd,
            lambda s: ExplodeGroupCommand(s.groups[-1]))
    assert len(scene.mesh.faces) == 6
    assert sorted(g.name for g in scene.groups) == ["A", "B"]


def test_component_of_groups_then_explode_redoes_both():
    scene = Scene()
    hist = History(scene)
    scene.groups.extend([_box_group(0, "A"), _box_group(3, "B")])
    cmd = MakeComponentOfCommand([], [], list(scene.groups), name="Banca")
    _replay(scene, hist, cmd,
            lambda s: ExplodeGroupCommand(s.groups[-1]))
    assert sorted(g.name for g in scene.groups) == ["A", "B"]


def test_group_made_inside_an_open_group_then_explode_redoes_both():
    scene = Scene()
    hist = History(scene)
    outer = _box_group(10, "Casa")
    scene.groups.append(outer)
    scene.begin_group_edit(outer)
    try:
        _loose_box(scene)
        inner = MakeGroupCommand(list(scene.mesh.faces),
                                 list(scene.mesh.edges))
        ctx = scene.edit_group
        cmd = GroupInContextCommand(inner, ctx)
        hist.execute(cmd)
        made = cmd.group
        hist.execute(GroupInContextCommand(ExplodeGroupCommand(made), ctx))
        after = _state(scene)
        assert hist.undo() and hist.undo()
        assert hist.redo() and hist.redo()
        assert _state(scene) == after
        assert not hist.redo_stack
    finally:
        scene.end_group_edit()


def _snapshot(scene):
    """Where everything is: the loose mesh's vertices and each top-level
    group's name with its own vertices (rounded, order-free)."""
    def pts(mesh):
        return sorted((round(v.position.x(), 6), round(v.position.y(), 6),
                       round(v.position.z(), 6)) for v in mesh.vertices)
    return (pts(scene.mesh), len(scene.mesh.faces),
            sorted((g.name or "", tuple(pts(g.mesh)), len(g.children or ()))
                   for g in scene.groups))


def test_window_loose_geometry_and_one_group_then_explode_redoes_both():
    """The menu's way: a loose box and ONE group selected, Make Group,
    Explode, then Edit ▸ Undo twice and Edit ▸ Redo twice."""
    import sys
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene, hist = vp.scene, vp.history
        scene.groups[:] = []                       # no scale figure
        _loose_box(scene, x=6.0)
        scene.groups.append(_box_group(0, "A"))
        scene.selection.clear()
        scene.selection.update(scene.mesh.faces)
        scene.selection.update(scene.mesh.edges)
        scene.selection.add(scene.groups[0])
        start = _snapshot(scene)

        win._on_make_group()
        grouped = _snapshot(scene)
        assert len(scene.groups) == 1 and not scene.mesh.faces
        container = scene.groups[0]
        scene.selection.clear()
        scene.selection.add(container)
        win._on_explode_group()
        exploded = _snapshot(scene)
        assert exploded == start                   # loose box and A again

        win._on_undo()
        assert _snapshot(scene) == grouped
        win._on_undo()
        assert _snapshot(scene) == start
        win._on_redo()
        assert _snapshot(scene) == grouped
        assert scene.groups[0] is container
        win._on_redo()
        assert _snapshot(scene) == exploded, "the second redo was lost"
        assert not hist.redo_stack
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_split_into_pieces_then_explode_redoes_both():
    from core.history import SplitIntoPiecesCommand
    from core.pieces import split_into_pieces
    scene = Scene()
    hist = History(scene)
    m = Mesh()
    for x in (0.0, 5.0):                   # two boxes that do not touch
        p = [V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)]
        q = [v + V(0, 0, 1) for v in p]
        m.add_face(list(reversed(p)))
        m.add_face(q)
        for i in range(4):
            j = (i + 1) % 4
            m.add_face([p[i], p[j], q[j], q[i]])
    stool = Group(m, name="stool")
    scene.groups.append(stool)
    _replay(scene, hist,
            SplitIntoPiecesCommand(stool, split_into_pieces(stool)),
            lambda s: ExplodeGroupCommand(stool))
    assert stool not in scene.groups and len(scene.groups) == 2


def test_replace_component_then_explode_redoes_both():
    scene = Scene()
    hist = History(scene)
    scene.groups.extend([_box_group(0, "A"), _box_group(3, "B")])
    hist.execute(MakeComponentOfCommand([], [], list(scene.groups),
                                        name="Banca"))
    source = scene.groups[-1]
    scene.groups.append(_box_group(8, "C"))
    hist.execute(MakeComponentOfCommand([], [], [scene.groups[-1]],
                                        name="Silla"))
    target = scene.groups[-1]
    _replay(scene, hist, ReplaceComponentCommand([target], source),
            lambda s: ExplodeGroupCommand(target))
    assert sorted(g.name for g in scene.groups) == ["A", "B", "Banca"]
