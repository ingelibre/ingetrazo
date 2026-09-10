# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Purge unused (layers / materials) — the sweep an import makes necessary.

Marco imported a surveyed plaza as a reference, kept one flat drawing and
deleted the rest; the document still carried the big drawing's 13 layers and
47 materials. Layers are labels, not owners, so the delete could not take
them — an explicit sweep must, and it must be undoable.
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.history import History, PurgeUnusedCommand
from core.layers import DEFAULT_LAYER, Layer, assign_layer
from core.materials import Material
from core.mesh import Mesh
from core.purge import (unused_layers, unused_materials, used_layers,
                        used_materials)
from core.saved_views import SavedView
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _quad(mesh, x0=0.0):
    return mesh.add_face([V(x0, 0), V(x0 + 2, 0), V(x0 + 2, 2), V(x0, 2)])


def test_empty_layer_is_unused():
    scene = Scene()
    _quad(scene.mesh)
    scene.layers.append(Layer("CVL_PUNTO"))
    assert [ly.name for ly in unused_layers(scene)] == ["CVL_PUNTO"]


def test_layer_worn_by_a_face_survives():
    scene = Scene()
    f = _quad(scene.mesh)
    scene.layers.append(Layer("VEREDA"))
    assign_layer(f, "VEREDA")
    assert "VEREDA" in used_layers(scene)
    assert unused_layers(scene) == []


def test_the_default_layer_is_never_swept():
    scene = Scene()
    assert scene.layers[0].name == DEFAULT_LAYER
    assert unused_layers(scene) == []


def test_a_layer_used_only_inside_a_group_survives():
    """The flat-list walk deleted this one out from under the group."""
    scene = Scene()
    inner = Mesh()
    f = _quad(inner)
    scene.groups.append(Group(inner, name="Banca"))
    scene.layers.append(Layer("Topografía"))
    assign_layer(f, "Topografía")
    assert unused_layers(scene) == []


def test_a_layer_used_only_inside_a_NESTED_placement_survives():
    scene = Scene()
    deep = Mesh()
    f = _quad(deep)
    child = Group(deep, name="Silla")
    child.xform = QMatrix4x4()
    parent = Group(Mesh(), name="Mesa")
    parent.adopt([child])
    scene.groups.append(parent)
    scene.layers.append(Layer("Muebles"))
    assign_layer(f, "Muebles")
    assert "Muebles" in used_layers(scene)
    assert unused_layers(scene) == []


def test_a_layer_a_scene_hides_is_kept():
    scene = Scene()
    scene.layers.append(Layer("Anotaciones"))
    scene.saved_views.append(SavedView("Planta", hidden_layers=["Anotaciones"]))
    assert unused_layers(scene) == []


def test_purge_removes_and_undo_restores_at_the_same_index():
    scene = Scene()
    _quad(scene.mesh)
    for name in ("BUZON", "CANAL", "limite"):
        scene.layers.append(Layer(name))
    history = History(scene)
    history.execute(PurgeUnusedCommand(layers=True, materials=False))
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER]
    history.undo()
    assert [ly.name for ly in scene.layers] == [
        DEFAULT_LAYER, "BUZON", "CANAL", "limite"]
    history.redo()
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER]


def test_redo_removes_what_the_first_run_chose_not_a_fresh_survey():
    """A layer created after the purge must not vanish on redo."""
    scene = Scene()
    _quad(scene.mesh)
    scene.layers.append(Layer("CVL_CURV_D"))
    history = History(scene)
    history.execute(PurgeUnusedCommand(layers=True, materials=False))
    history.undo()
    scene.layers.append(Layer("Recien creada"))
    history.redo()
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER, "Recien creada"]


def test_unused_materials_are_the_ones_no_face_wears():
    scene = Scene()
    f = _quad(scene.mesh)
    scene.materials["Concreto"] = Material("Concreto", color=(0.5, 0.5, 0.5))
    scene.materials["Celtis_australis"] = Material("Celtis_australis",
                                                   color=(0.1, 0.4, 0.1))
    f.attrs["mat"] = "Concreto"
    assert used_materials(scene) == {"Concreto"}
    assert unused_materials(scene) == ["Celtis_australis"]


def test_a_material_worn_inside_a_group_survives():
    scene = Scene()
    inner = Mesh()
    f = _quad(inner)
    scene.groups.append(Group(inner, name="Pileta"))
    scene.materials["Marble_07_1K"] = Material("Marble_07_1K",
                                               color=(0.9, 0.9, 0.9))
    f.attrs["mat"] = "Marble_07_1K"
    assert unused_materials(scene) == []


def test_purging_materials_is_undoable_with_the_recipe_intact():
    scene = Scene()
    _quad(scene.mesh)
    mat = Material("Brick_Soldier_Bond_1K", color=(0.7, 0.3, 0.2))
    scene.materials["Brick_Soldier_Bond_1K"] = mat
    history = History(scene)
    history.execute(PurgeUnusedCommand(layers=False, materials=True))
    assert scene.materials == {}
    history.undo()
    assert scene.materials["Brick_Soldier_Bond_1K"] is mat


def test_flags_scope_the_sweep():
    scene = Scene()
    _quad(scene.mesh)
    scene.layers.append(Layer("Trees"))
    scene.materials["grass"] = Material("grass", color=(0.2, 0.6, 0.2))
    history = History(scene)
    history.execute(PurgeUnusedCommand(layers=True, materials=False))
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER]
    assert "grass" in scene.materials


def _window():
    import os
    from PySide6.QtWidgets import QApplication
    from views.main_window import MainWindow
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QApplication.instance() is None:
        QApplication([])
    return MainWindow()


def _row(tree, name):
    from PySide6.QtCore import Qt
    return next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                if tree.topLevelItem(i).data(0, Qt.UserRole) == name)


def test_deleting_a_layer_reassigns_faces_INSIDE_groups():
    """The − button walked scene.groups as a flat list, so geometry inside a
    group kept a tag pointing at a layer that no longer existed."""
    from core.layers import layer_of
    win = _window()
    try:
        scene = win.viewport.scene
        panel = win.tray.layers
        inner = Mesh()
        f = _quad(inner)
        deep = Mesh()
        g = _quad(deep)
        child = Group(deep, name="Silla")
        child.xform = QMatrix4x4()
        parent = Group(inner, name="Mesa")
        parent.adopt([child])
        scene.groups.append(parent)
        scene.layers.append(Layer("CANAL"))
        assign_layer(f, "CANAL")
        assign_layer(g, "CANAL")
        panel.refresh()
        panel.tree.setCurrentItem(_row(panel.tree, "CANAL"))
        panel._on_delete()
        assert scene.layer("CANAL") is None
        assert layer_of(f) == DEFAULT_LAYER
        assert layer_of(g) == DEFAULT_LAYER
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_purge_button_sweeps_and_ctrl_z_brings_them_back(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win = _window()
    try:
        scene = win.viewport.scene
        panel = win.tray.layers
        for name in ("CVL_PUNTO", "BUZON", "Trees"):
            scene.layers.append(Layer(name))
        panel.refresh()
        panel._on_purge()
        assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER]
        assert panel.tree.topLevelItemCount() == 1
        win.viewport.history.undo()
        panel.refresh()
        assert [ly.name for ly in scene.layers] == [
            DEFAULT_LAYER, "CVL_PUNTO", "BUZON", "Trees"]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
