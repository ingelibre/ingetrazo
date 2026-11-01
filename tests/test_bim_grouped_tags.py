# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Grouping never drops a BIM tag from the takeoff.

A tagged group grouped again sat one level down the tree, and tagged faces
grouped went into a group's mesh: the takeoff, the CSV and the IFC export
only read the loose faces and the top-level groups, so both objects
vanished from them while the Browser still showed the class."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4
from PySide6.QtGui import QVector3D as V

from core import bim
from core.bim import collect_objects, next_object_id, tag_faces, tag_group
from core.history import History, MakeGroupCommand, MakeNestedGroupCommand
from core.scene import Scene
from formats import igz


def _box(scene, x0=0.0, size=(2.0, 1.0, 3.0)):
    """A closed box on the loose mesh; its six faces."""
    sx, sy, sz = size
    c = [V(x0 + dx * sx, dy * sy, dz * sz)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [scene.mesh.add_face([c[i] for i in q]) for q in quads]


def _group(scene, history, faces, component=False):
    """Group ``faces`` — all the loose geometry: each test builds a box
    right before grouping it, so the box's edges are the loose edges."""
    assert set(faces) == set(scene.mesh.faces)
    cmd = MakeGroupCommand(faces, list(scene.mesh.edges), component=component)
    history.execute(cmd)
    return cmd.group


def _nest(scene, history, groups):
    cmd = MakeNestedGroupCommand([], [], groups)
    history.execute(cmd)
    return cmd.container


def _moved(g, x):
    m = QMatrix4x4()
    m.translate(x, 0.0, 0.0)
    g.xform = m * (g.xform if g.xform is not None else QMatrix4x4())


def test_a_tagged_group_grouped_again_stays_in_the_takeoff():
    scene = Scene()
    h = History(scene)
    col = _group(scene, h, _box(scene))
    tag_group(col, "IfcColumn", "C-1")
    _nest(scene, h, [col])
    (obj,) = collect_objects(scene)
    assert (obj["class"], obj["name"]) == ("IfcColumn", "C-1")
    assert obj["group"] is col
    assert abs(obj["volume"] - 6.0) < 1e-6


def test_a_nested_object_measures_in_world_space():
    scene = Scene()
    h = History(scene)
    col = _group(scene, h, _box(scene))
    tag_group(col, "IfcColumn", "C-1")
    outer = _nest(scene, h, [col])
    _moved(outer, 7.0)
    (obj,) = collect_objects(scene)
    assert abs(obj["volume"] - 6.0) < 1e-6        # the move keeps it closed


def test_tagged_faces_grouped_stay_in_the_takeoff():
    scene = Scene()
    h = History(scene)
    faces = _box(scene)
    tag_faces(faces, "IfcWall", "Muro", next_object_id(scene))
    g = _group(scene, h, faces)
    (obj,) = collect_objects(scene)
    assert (obj["class"], obj["name"]) == ("IfcWall", "Muro")
    assert obj["owner"] is g
    assert abs(obj["volume"] - 6.0) < 1e-6
    assert bim.quantities_csv(scene).count("IfcWall") == 1


def test_tagged_faces_in_a_moved_component_measure_in_world_space():
    scene = Scene()
    h = History(scene)
    faces = _box(scene)
    tag_faces(faces, "IfcBeam", "V-1", next_object_id(scene))
    comp = _group(scene, h, faces, component=True)
    _moved(comp, 3.0)
    (obj,) = collect_objects(scene)
    assert abs(obj["volume"] - 6.0) < 1e-6
    xs = [v.x() for f in obj["faces"] for v in f.vertices]
    assert min(xs) >= 3.0 - 1e-6                  # where the copy stands


def test_a_tagged_group_inside_a_tagged_group_is_counted_once():
    scene = Scene()
    h = History(scene)
    small = _group(scene, h, _box(scene, 0.0, (1.0, 1.0, 1.0)))
    tag_group(small, "IfcColumn", "C-1")
    big = _group(scene, h, _box(scene, 5.0))
    outer = _nest(scene, h, [small, big])
    tag_group(outer, "IfcFooting", "Z-1")
    by_class = {o["class"]: o for o in collect_objects(scene)}
    assert set(by_class) == {"IfcColumn", "IfcFooting"}
    assert abs(by_class["IfcColumn"]["volume"] - 1.0) < 1e-6
    # The footing is its own geometry: the 2 × 1 × 3 box, not the column.
    assert abs(by_class["IfcFooting"]["volume"] - 6.0) < 1e-6


def test_the_next_id_sees_the_tags_inside_groups():
    scene = Scene()
    h = History(scene)
    faces = _box(scene)
    tag_faces(faces, "IfcWall", "Muro", 4)
    _group(scene, h, faces)
    assert next_object_id(scene) == 5             # ungrouping won't merge


def test_the_takeoff_memo_sees_a_tag_added_inside_a_group():
    scene = Scene()
    h = History(scene)
    g = _group(scene, h, _box(scene))
    memo: dict = {}
    assert collect_objects(scene, memo) == []
    tag_faces(list(g.mesh.faces), "IfcSlab", "Losa", 1)
    (obj,) = collect_objects(scene, memo)
    assert obj["class"] == "IfcSlab"
    bim.untag_faces(list(g.mesh.faces))
    assert collect_objects(scene, memo) == []


def test_a_nested_tagged_group_survives_save_and_load(tmp_path):
    scene = Scene()
    h = History(scene)
    col = _group(scene, h, _box(scene))
    tag_group(col, "IfcColumn", "C-1")
    _nest(scene, h, [col])
    p = tmp_path / "nested.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    (obj,) = collect_objects(scene2)
    assert obj["class"] == "IfcColumn" and obj["group"] is not None
    assert abs(obj["volume"] - 6.0) < 1e-6


def test_the_bim_panel_lists_and_picks_grouped_objects():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        h = win.viewport.history
        col = _group(scene, h, _box(scene))
        tag_group(col, "IfcColumn", "C-1")
        outer = _nest(scene, h, [col])
        faces = _box(scene, 5.0)
        tag_faces(faces, "IfcWall", "Muro", next_object_id(scene))
        wall = _group(scene, h, faces)
        panel = win.bim_tray.bim
        panel.refresh()
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        items = []
        it = QTreeWidgetItemIterator(panel.tree)
        while it.value() is not None:
            items.append(it.value())
            it += 1
        rows = {i.text(1): i for i in items if i.text(1)}
        assert set(rows) == {"C-1", "Muro"}
        # Each row sits under the group that holds it.
        assert rows["C-1"].parent().data(0, Qt.UserRole) < 0
        assert rows["Muro"].parent().data(0, Qt.UserRole) < 0
        assert panel._containers[-rows["C-1"].parent().data(
            0, Qt.UserRole) - 1] is outer
        assert panel._containers[-rows["Muro"].parent().data(
            0, Qt.UserRole) - 1] is wall
        # The column sits inside «outer»: picking it opens that group.
        panel._on_pick_object(rows["C-1"], 0)
        assert scene.edit_group is outer
        assert scene.selection == {col}
        # The wall's faces are inside «wall»: picking opens it, selects them.
        panel._on_pick_object(rows["Muro"], 0)
        assert scene.edit_group is wall
        assert len(scene.selection) == 6
        assert all(f.attrs["ifc"]["name"] == "Muro" for f in scene.selection)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
