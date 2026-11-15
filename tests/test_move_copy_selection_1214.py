# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Move-copy selects its result, so the next edit cannot move the original."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4

from core.group import Group
from core.guide import Guide
from core.history import Command, CommandRejected, CompoundCommand
from core.mesh import Edge, Face, Mesh
from core.scene import Scene
from tests.test_move_copy import V, _ctx, _square, _Vp
from tools.move import MoveTool


def _source(scene, kind):
    if kind == "face":
        return _square(scene)
    if kind == "edge":
        return scene.mesh.add_edge(V(0, 0), V(1, 0))
    if kind == "guide":
        guide = Guide(V(0, 0), V(0, 1))
        scene.guides.append(guide)
        return guide
    mesh = Mesh()
    mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    group = Group(mesh, name=kind)
    if kind == "component":
        group.xform = QMatrix4x4()
        group.component = "shared-definition"
    scene.groups.append(group)
    return group


def _copy(vp, distance=3):
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, distance, 0))
    assert vp.history.last_error is None
    return tool


def _live(scene):
    return set(scene.mesh.faces) | set(scene.mesh.edges) | set(scene.groups) | set(scene.guides)


@pytest.mark.parametrize("kind", ["face", "edge", "group", "component", "guide"])
def test_copy_selects_the_copy_and_undo_redo_keep_selection_live(kind):
    scene = Scene()
    original = _source(scene, kind)
    scene.select([original])
    vp = _Vp(scene)
    before = _live(scene)
    _copy(vp)

    assert scene.selection
    assert original not in scene.selection
    assert scene.selection <= _live(scene) - before
    assert len(scene.selection) == 1
    if kind == "component":
        clone = next(iter(scene.selection))
        assert clone.mesh is original.mesh
        assert clone.component == original.component

    vp.history.undo()
    assert scene.selection == {original}
    assert _live(scene) == before
    vp.history.redo()
    assert scene.selection
    assert original not in scene.selection
    assert scene.selection <= _live(scene) - before


def test_a_second_move_changes_the_copied_face_not_the_original():
    scene = Scene()
    original = _square(scene)
    scene.select([original])
    vp = _Vp(scene)
    _copy(vp)

    move = MoveTool()
    move.on_click(_ctx(vp, 3, 0))
    move.on_click(_ctx(vp, 5, 0))
    assert min(p.x() for p in original.vertices) == pytest.approx(0)
    assert sorted(min(p.x() for p in f.vertices) for f in scene.mesh.faces) == [0, 5]


def test_undo_redo_after_leaving_a_group_do_not_select_its_hidden_contents():
    scene = Scene()
    container = _source(scene, "group")
    scene.begin_group_edit(container)
    original = scene.mesh.faces[0]
    scene.select([original])
    vp = _Vp(scene)
    _copy(vp)
    assert original not in scene.selection
    assert scene.selection <= set(container.mesh.faces)

    scene.end_group_edit()
    scene.select([container])
    vp.history.undo()
    assert len(container.mesh.faces) == 1
    assert scene.selection == {container}
    vp.history.redo()
    assert len(container.mesh.faces) == 2
    assert scene.selection == {container}


def test_mixed_copy_selects_all_results_instead_of_just_the_last_group():
    scene = Scene()
    originals = [_source(scene, kind) for kind in ("group", "component", "face", "guide")]
    scene.select(originals)
    vp = _Vp(scene)
    _copy(vp)

    assert not set(originals) & scene.selection
    assert len(scene.selection) == 4
    assert sum(isinstance(ent, Group) for ent in scene.selection) == 2
    assert sum(isinstance(ent, Face) for ent in scene.selection) == 1
    assert sum(isinstance(ent, Guide) for ent in scene.selection) == 1


@pytest.mark.parametrize("kind", ["face", "edge", "group", "guide"])
def test_retyping_an_array_selects_only_the_current_copies(kind):
    scene = Scene()
    original = _source(scene, kind)
    scene.select([original])
    vp = _Vp(scene)
    tool = _copy(vp)

    for count, mode in ((3, "x"), (2, "/"), (4, "x")):
        assert tool.on_array_value(vp, count, mode)
        assert len(scene.selection) == count
        assert original not in scene.selection
        assert scene.selection <= _live(scene)
        assert len(vp.history.undo_stack) == 1
    vp.history.undo()
    assert scene.selection == {original}
    vp.history.redo()
    assert len(scene.selection) == 4
    assert original not in scene.selection
    assert scene.selection <= _live(scene)


def _segment(edge):
    return frozenset(tuple(round(x, 5) for x in point.toTuple()) for point in (edge.a, edge.b))


def test_a_copied_edge_split_at_a_crossing_selects_both_fragments():
    scene = Scene()
    original = scene.mesh.add_edge(V(0, 0), V(4, 0))
    crossing = scene.mesh.add_edge(V(2, 1), V(2, 3))
    scene.select([original])
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 0, 2))

    assert scene.selection
    assert all(isinstance(edge, Edge) for edge in scene.selection)
    assert {_segment(edge) for edge in scene.selection} == {
        frozenset(((0.0, 2.0, 0.0), (2.0, 2.0, 0.0))),
        frozenset(((2.0, 2.0, 0.0), (4.0, 2.0, 0.0))),
    }
    assert original not in scene.selection
    assert crossing not in scene.selection
    vp.history.undo()
    assert scene.selection == {original}
    vp.history.redo()
    assert len(scene.selection) == 2
    assert scene.selection <= _live(scene)


def test_a_copy_welded_to_an_existing_edge_selects_that_edge():
    scene = Scene()
    original = scene.mesh.add_edge(V(0, 0), V(1, 0))
    target = scene.mesh.add_edge(V(3, 0), V(4, 0))
    scene.select([original])
    vp = _Vp(scene)
    _copy(vp)
    assert scene.selection == {target}
    assert len(scene.mesh.edges) == 2
    vp.history.undo()
    assert scene.selection == {original}
    assert len(scene.mesh.edges) == 2


def test_a_rejected_copy_keeps_the_original_selection(monkeypatch):
    class Refused(Command):
        def do(self, scene):
            raise CommandRejected("copy refused")

        def undo(self, scene):
            pass

    scene = Scene()
    original = _source(scene, "group")
    scene.select([original])
    vp = _Vp(scene)
    build_copy = MoveTool._make_copy_builder

    def rejecting_builder(self, scene=None):
        build = build_copy(self, scene)

        def reject(deltas):
            command = build(deltas)
            if not isinstance(command, CompoundCommand):
                command = CompoundCommand([command])
            # A late refusal after the inserted group has changed selection.
            command.commands.append(Refused())
            return command

        return reject

    monkeypatch.setattr(MoveTool, "_make_copy_builder", rejecting_builder)
    _copy(vp)
    assert vp.history.last_rejected == "copy refused"
    assert not vp.history.undo_stack
    assert scene.groups == [original]
    assert scene.selection == {original}
