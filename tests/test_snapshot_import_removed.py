# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SnapshotImport undoes what the mutation removed, not only what it added.

An extension that replaces its own container group (remove the old one,
append the new one) lost the old group on undo: undo took the new one away
and never put the old one back. A console line that only deleted a group
was worse: the run looked unchanged, so it left no undo step at all."""
from __future__ import annotations

from core.group import Group
from core.history import History, SnapshotImport
from core.layers import Layer
from core.mesh import Mesh
from core.scene import Scene


def _names(items):
    return [x.name for x in items]


def _scene_with_groups(*names):
    scene = Scene()
    for name in names:
        scene.groups.append(Group(Mesh(), name=name))
    return scene


def test_replacing_a_group_undoes_and_redoes():
    scene = _scene_with_groups("old")
    old = scene.groups[0]
    history = History(scene)

    def replace(s):
        s.groups.remove(old)
        s.groups.append(Group(Mesh(), name="new"))

    history.execute(SnapshotImport(replace))
    assert _names(scene.groups) == ["new"]
    history.undo()
    assert _names(scene.groups) == ["old"]
    assert scene.groups[0] is old                   # the same object back
    history.redo()
    assert _names(scene.groups) == ["new"]
    history.undo()
    assert _names(scene.groups) == ["old"]


def test_a_removed_group_goes_back_to_its_place():
    scene = _scene_with_groups("a", "b", "c", "d")
    b, c = scene.groups[1], scene.groups[2]
    history = History(scene)

    def remove_two(s):
        s.groups.remove(b)
        s.groups.remove(c)

    history.execute(SnapshotImport(remove_two))
    assert _names(scene.groups) == ["a", "d"]
    history.undo()
    assert _names(scene.groups) == ["a", "b", "c", "d"]
    history.redo()
    assert _names(scene.groups) == ["a", "d"]


def test_redo_leaves_no_removed_group_selected():
    scene = _scene_with_groups("old")
    old = scene.groups[0]
    history = History(scene)
    history.execute(SnapshotImport(lambda s: s.groups.remove(old)))
    history.undo()
    scene.selection.add(old)
    history.redo()
    assert old not in scene.groups
    assert old not in scene.selection


def test_a_removed_layer_comes_back_on_undo():
    scene = Scene()
    walls = Layer("Walls")
    scene.layers.append(walls)
    before = list(scene.layers)
    history = History(scene)
    history.execute(SnapshotImport(lambda s: s.layers.remove(walls)))
    assert walls not in scene.layers
    history.undo()
    assert scene.layers == before


def test_a_run_that_only_removes_counts_as_a_change():
    scene = _scene_with_groups("old")
    old = scene.groups[0]
    cmd = SnapshotImport(lambda s: s.groups.remove(old))
    History(scene).execute(cmd)
    assert cmd.changed
    assert cmd.removed_groups == [(0, old)]


def test_a_run_that_touches_nothing_is_unchanged():
    scene = _scene_with_groups("a")
    cmd = SnapshotImport(lambda s: None)
    History(scene).execute(cmd)
    assert not cmd.changed


def test_a_failed_run_still_restores_everything():
    scene = _scene_with_groups("a", "b")
    groups = list(scene.groups)
    history = History(scene)

    def boom(s):
        s.groups.remove(groups[0])
        s.groups.append(Group(Mesh(), name="half"))
        raise ValueError("halfway")

    history.execute(SnapshotImport(boom))
    assert scene.groups == groups
    assert history.undo_stack == []
