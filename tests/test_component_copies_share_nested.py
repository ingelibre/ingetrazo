# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Copies of a component share the groups inside it (issue #97).

Make two groups → Make Component → copy it. Editing a group inside one copy
must change every copy, as in SketchUp: the nested groups are part of the
definition. Copies of a plain GROUP stay independent, and what leaves a
component (Make Unique, Explode) stops sharing on the way out."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.group import Group, copy_group, iter_placements
from core.history import History, MakeComponentOfCommand, MakeNestedGroupCommand
from core.mesh import Mesh
from core.scene import Scene


def _box_group(x, name):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return Group(m, name=name)


def _component_and_copy(kind=MakeComponentOfCommand):
    scene = Scene()
    hist = History(scene)
    a, b = _box_group(0, "A"), _box_group(3, "B")
    scene.groups.extend([a, b])
    hist.execute(kind([], [], [a, b], name="Banca"))
    comp = scene.groups[0]
    dup = copy_group(comp, V(0, 5, 0))
    scene.groups.append(dup)
    return scene, comp, dup


def _raise_first_child(scene, container):
    """Open the container, open its first group, lift its face 0.5 m."""
    scene.begin_group_edit(container)
    child = container.children[0]
    scene.begin_group_edit(child)
    for v in {id(v): v for f in child.mesh.faces for v in f.loop}.values():
        v.position = v.position + V(0, 0, 0.5)
    scene.end_group_edit()
    scene.end_group_edit()


def _world_z(group):
    return sorted({round(p.z(), 3)
                   for g, m in iter_placements(group)
                   for f in g.mesh.faces for p in (
                       (m.map(v) if m is not None else v) for v in f.vertices)})


def test_editing_a_group_inside_one_copy_changes_every_copy():
    scene, comp, dup = _component_and_copy()
    _raise_first_child(scene, dup)
    assert 0.5 in _world_z(comp)           # the original copy follows


def test_copies_of_a_group_of_groups_stay_independent():
    scene, grp, dup = _component_and_copy(MakeNestedGroupCommand)
    _raise_first_child(scene, dup)
    assert _world_z(grp) == [0.0]


def test_a_group_exploded_out_of_a_copy_is_its_own_when_opened():
    """Explode frees the groups of one copy; opening one of them must not
    edit the groups still inside the other copies."""
    import sys
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    from core.history import ExplodeGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        scene = vp.scene
        a, b = _box_group(0, "A"), _box_group(3, "B")
        scene.groups.extend([a, b])
        vp.history.execute(MakeComponentOfCommand([], [], [a, b], name="Banca"))
        comp = scene.groups[-1]
        dup = copy_group(comp, V(0, 5, 0))
        scene.groups.append(dup)
        vp.history.execute(ExplodeGroupCommand(dup))
        freed = dup.children[0]
        assert freed in scene.groups
        vp.begin_group_edit(freed)
        assert freed.mesh is not comp.children[0].mesh   # made unique
        for v in {id(v): v for f in freed.mesh.faces for v in f.loop}.values():
            v.position = v.position + V(0, 0, 0.5)
        vp.scene.version += 1
        while vp.scene.edit_group is not None:
            vp.escape()
        assert _world_z(comp) == [0.0]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_sharing_survives_the_igz(tmp_path):
    from formats import igz
    scene, comp, dup = _component_and_copy()
    path = tmp_path / "banca.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    c1, c2 = loaded.groups
    assert all(x.mesh is y.mesh for x, y in zip(c1.children, c2.children))
    _raise_first_child(loaded, c2)
    assert 0.5 in _world_z(c1)


def test_through_the_viewport_the_edit_reaches_the_other_copy_and_undoes():
    import sys
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        scene = vp.scene
        a, b = _box_group(0, "A"), _box_group(3, "B")
        scene.groups.extend([a, b])
        vp.history.execute(MakeComponentOfCommand([], [], [a, b], name="Banca"))
        comp = scene.groups[-1]
        dup = copy_group(comp, V(0, 5, 0))
        scene.groups.append(dup)
        vp.begin_group_edit(dup)
        child = dup.children[0]
        vp.begin_group_edit(child)
        assert child.mesh is not comp.children[0].mesh   # the world copy …
        for v in {id(v): v for f in child.mesh.faces for v in f.loop}.values():
            v.position = v.position + V(0, 0, 0.5)
        scene.version += 1
        while scene.edit_group is not None:
            vp.escape()
        assert 0.5 in _world_z(comp)                     # … shared back
        assert dup.children[0].mesh is comp.children[0].mesh
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
