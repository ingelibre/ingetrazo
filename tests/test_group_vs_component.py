"""A group of groups is a GROUP, a component is what Make Component makes
(issue #90, @fafecm: «the parent group always becomes a component, and if I
try to make it unique, it explodes all the subgroups»; Marco, 24-09: Make
Component over several groups must make ONE component holding them)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group
from core.history import (GroupToComponentCommand, History,
                          MakeComponentOfCommand, MakeNestedGroupCommand,
                          MakeUniqueCommand)
from core.mesh import Mesh
from core.scene import Scene


def _box_group(x, name):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return Group(m, name=name)


def _two_groups():
    scene = Scene()
    a, b = _box_group(0, "A"), _box_group(3, "B")
    scene.groups.extend([a, b])
    return scene, History(scene), a, b


def test_a_group_of_groups_is_a_group_and_can_become_a_component():
    scene, hist, a, b = _two_groups()
    hist.execute(MakeNestedGroupCommand([], [], [a, b], name="Banca"))
    box = scene.groups[-1]
    assert box.xform is not None and not box.is_component()
    hist.execute(GroupToComponentCommand(box, "Banca"))
    assert box.is_component() and box.children == [a, b]
    hist.undo()
    assert not box.is_component()


def test_make_component_over_several_groups_makes_one_holding_them():
    scene, hist, a, b = _two_groups()
    hist.execute(MakeComponentOfCommand([], [], [a, b], name="Banca"))
    assert len(scene.groups) == 1
    comp = scene.groups[0]
    assert comp.is_component() and comp.children == [a, b]
    hist.undo()
    assert scene.groups == [a, b]


def test_make_unique_keeps_a_component_with_subgroups_a_component():
    """A component of its own, with this one copy (#620) — it used to come
    out a group."""
    scene, hist, a, b = _two_groups()
    hist.execute(MakeComponentOfCommand([], [], [a, b], name="Banca"))
    comp = scene.groups[0]
    sibling = copy_group(comp, V(10, 0, 0))
    scene.groups.append(sibling)
    assert sibling.is_component()
    hist.execute(MakeUniqueCommand(comp))
    assert comp.is_component() and len(comp.children) == 2
    assert comp.mesh is not sibling.mesh            # its own definition
    assert sibling.is_component()
    hist.undo()
    assert comp.is_component() and comp.mesh is sibling.mesh


def test_the_panel_says_group_for_a_group_of_groups(monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        a, b = _box_group(0, "A"), _box_group(3, "B")
        scene.groups.extend([a, b])
        win.viewport.history.execute(
            MakeNestedGroupCommand([], [], [a, b], name="Banca"))
        box = [g for g in scene.groups if g.children][0]
        text = win.tray.entity_info._describe([box])
        assert "Component" not in text and "Group" in text
        win.viewport.history.execute(GroupToComponentCommand(box, "Banca"))
        assert "Component" in win.tray.entity_info._describe([box])
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_flag_survives_the_igz_and_old_files_read_as_groups(tmp_path):
    from formats import igz
    scene, hist, a, b = _two_groups()
    hist.execute(MakeNestedGroupCommand([], [], [a, b], name="Banca"))
    c, d = _box_group(6, "C"), _box_group(9, "D")
    scene.groups.extend([c, d])
    hist.execute(MakeComponentOfCommand([], [], [c, d], name="Silla"))
    path = tmp_path / "g.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    kinds = {g.name: g.is_component() for g in back.groups}
    assert kinds == {"Banca": False, "Silla": True}
    assert all(len(g.children) == 2 for g in back.groups)


def test_a_copied_group_becomes_its_own_when_opened():
    """Copies of a GROUP share their geometry only until one is edited —
    editing one never reaches the others, unlike a component."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene = vp.scene
        g = _box_group(0, "Muro")
        scene.groups.append(g)
        scene.selection.clear()
        scene.selection.add(g)
        vp.copy_selection()
        tpl = vp.clipboard["groups"][0]
        assert not tpl.is_component()
        s1, s2 = copy_group(tpl, V(5, 0, 0)), copy_group(tpl, V(9, 0, 0))
        scene.groups.extend([s1, s2])
        assert s1.mesh is s2.mesh
        vp.begin_group_edit(s1)
        vp.end_group_edit()
        assert s1.mesh is not s2.mesh
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_an_older_file_reads_its_groups_of_groups_as_groups(tmp_path):
    """Saved before the key existed: a container holding a classic group
    can only be Make Group's (a .skp import places every child with a
    matrix) — a group. A container of placements stays a component."""
    import json
    from formats import igz
    scene, hist, a, b = _two_groups()
    hist.execute(MakeNestedGroupCommand([], [], [a, b], name="Banca"))
    placed = Group(_box_group(0, "P").mesh, name="Pieza")
    placed.xform = QMatrix4x4()
    imported = Group(Mesh(), name="Import")
    imported.adopt([placed])
    scene.groups.append(imported)
    new = tmp_path / "new.igz"
    igz.save_scene(scene, new)
    doc = json.loads(new.read_text(encoding="utf-8"))   # no textures: JSON

    def strip(entry):
        entry.pop("component", None)
        for c in entry.get("children", []):
            strip(c)
    for g in doc["scene"]["groups"]:
        strip(g)
    old = tmp_path / "old.igz"
    old.write_text(json.dumps(doc), encoding="utf-8")
    back = Scene()
    igz.load_into(back, old)
    kinds = {g.name: g.is_component() for g in back.groups}
    assert kinds == {"Banca": False, "Import": True}
