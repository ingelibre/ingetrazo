"""Active-layer creation, persistence and the pencil in the layers tree."""
from types import SimpleNamespace
import json

import pytest

from PySide6.QtGui import QVector3D
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.dimension import Dimension
from core.textlabel import TextLabel
from core.history import (AddDimensionCommand, AddEdgeCommand, AddFaceCommand,
                          AddTextLabelCommand, CompoundCommand,
                          History, InsertGroupCommand, MakeGroupCommand, SnapshotCompound,
                          SnapshotImport, SnapshotMutation)
from core.layers import DEFAULT_LAYER, Layer, LayerFolder, assign_layer, layer_of
from core.mesh import Mesh
from core.purge import unused_layers
from core.scene import Scene
from formats.igz import load_into, save_scene
from views.tray import LayersPanel


def active_scene():
    scene = Scene()
    scene.layers += [Layer('Walls'), Layer('Furniture')]
    scene.active_layer = 'Walls'
    return scene, History(scene)


def square(mesh):
    return mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                          QVector3D(1, 1, 0), QVector3D(0, 1, 0)])


def test_draw_and_redo_keep_original_active_layer():
    scene, history = active_scene()
    existing = scene.mesh.add_edge(QVector3D(5, 0, 0), QVector3D(6, 0, 0))
    cmd = SnapshotCompound([AddFaceCommand([
        QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)])])
    history.execute(cmd)
    assert history.last_error is None
    assert layer_of(scene.faces[0]) == 'Walls'
    assert all(layer_of(e) == 'Walls' for e in scene.edges if e is not existing)
    assert layer_of(existing) == DEFAULT_LAYER
    history.undo()
    assert scene.faces == []
    scene.active_layer = 'Furniture'
    history.redo()
    assert layer_of(scene.faces[0]) == 'Walls'
    assert layer_of(existing) == DEFAULT_LAYER


def test_compound_and_reused_edge():
    scene, history = active_scene()
    existing = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    history.execute(CompoundCommand([
        AddEdgeCommand(QVector3D(), QVector3D(1, 0, 0)),
        AddEdgeCommand(QVector3D(2, 0, 0), QVector3D(3, 0, 0))]))
    assert history.last_error is None
    assert layer_of(existing) == DEFAULT_LAYER
    assert layer_of(scene.edges[-1]) == 'Walls'


def test_redo_follows_renamed_or_deleted_active_layer():
    scene, history = active_scene()
    history.execute(AddEdgeCommand(QVector3D(), QVector3D(1, 0, 0)))
    history.undo()
    layer = scene.layer('Walls')
    layer.name = 'Structure'
    history.redo()
    assert layer_of(scene.edges[0]) == 'Structure'
    history.undo()
    scene.layers.remove(layer)
    history.redo()
    assert layer_of(scene.edges[0]) == DEFAULT_LAYER


def test_new_models_keep_explicit_imported_layers():
    scene, history = active_scene()
    group = Group(Mesh())
    history.execute(InsertGroupCommand(group))
    assert layer_of(group) == 'Walls'
    history.undo()
    scene.active_layer = 'Furniture'
    history.redo()
    assert layer_of(group) == 'Walls'
    tagged = Group(Mesh())
    assign_layer(tagged, 'Walls')
    history.execute(InsertGroupCommand(tagged))
    assert layer_of(tagged) == 'Walls'


def test_import_and_snapshot_creation():
    scene, history = active_scene()
    history.execute(SnapshotImport(lambda s: s.groups.append(Group(Mesh()))))
    assert layer_of(scene.groups[0]) == 'Walls'
    history.execute(SnapshotMutation(lambda s: square(s.mesh)))
    assert layer_of(scene.faces[0]) == 'Walls'
    history.undo()
    scene.active_layer = 'Furniture'
    history.redo()
    assert layer_of(scene.faces[0]) == 'Walls'


def test_group_edit_creation_uses_active_layer():
    scene, history = active_scene()
    group = Group(Mesh())
    scene.groups.append(group)
    scene.begin_group_edit(group)
    history.execute(AddEdgeCommand(QVector3D(), QVector3D(1, 0, 0)))
    assert history.last_error is None
    assert layer_of(group.mesh.edges[0]) == 'Walls'


@pytest.mark.parametrize('entity, command, collection', [
    (Dimension(QVector3D(), QVector3D(1, 0, 0), QVector3D(0, 1, 0)),
     AddDimensionCommand, 'dimensions'),
    (TextLabel(QVector3D(), QVector3D(0, 1, 0), 'Wall'),
     AddTextLabelCommand, 'text_labels'),
])
def test_annotations_use_active_layer_and_keep_it_on_redo(entity, command, collection):
    scene, history = active_scene()
    history.execute(command(entity))
    assert history.last_error is None
    assert layer_of(entity) == 'Walls'
    history.undo()
    assert getattr(scene, collection) == []
    scene.active_layer = 'Furniture'
    history.redo()
    assert layer_of(getattr(scene, collection)[0]) == 'Walls'


def test_group_creation_assigns_container_without_retagging_contents():
    scene, history = active_scene()
    face = square(scene.mesh)
    assign_layer(face, 'Furniture')
    history.execute(MakeGroupCommand([face], list(scene.edges)))
    assert history.last_error is None
    group = scene.groups[0]
    assert layer_of(group) == 'Walls'
    assert layer_of(group.mesh.faces[0]) == 'Furniture'
    history.undo()
    assert layer_of(scene.faces[0]) == 'Furniture'
    history.redo()
    assert layer_of(scene.groups[0]) == 'Walls'


@pytest.mark.parametrize('active', [None, 'Missing layer'])
def test_legacy_or_invalid_active_layer_loads_as_default(tmp_path, active):
    scene, _ = active_scene()
    path = tmp_path / 'legacy.igz'
    save_scene(scene, path)
    data = json.loads(path.read_text())
    data['scene'].pop('active_layer', None)
    if active is not None:
        data['scene']['active_layer'] = active
    path.write_text(json.dumps(data))
    loaded, _ = active_scene()
    load_into(loaded, path)
    assert loaded.active_layer == DEFAULT_LAYER


def test_save_load_clear_and_purge(tmp_path):
    scene, _ = active_scene()
    assert scene.layer('Walls') not in unused_layers(scene)
    path = tmp_path / 'active.igz'
    save_scene(scene, path)
    loaded = Scene()
    load_into(loaded, path)
    assert loaded.active_layer == 'Walls'
    loaded.clear()
    assert loaded.active_layer == DEFAULT_LAYER


def test_pencil_click_folder_rename_and_delete():
    scene, _ = active_scene()
    folder = LayerFolder('Building')
    scene.layer_folders.append(folder)
    panel = LayersPanel(SimpleNamespace(viewport=SimpleNamespace(
        scene=scene, update=lambda: None)))
    try:
        def row(name):
            return next(panel.tree.topLevelItem(i)
                        for i in range(panel.tree.topLevelItemCount())
                        if panel.tree.topLevelItem(i).text(0) == name)
        assert not row('Walls').icon(8).isNull()
        assert panel.tree.header().visualIndex(8) == panel.tree.columnCount() - 1
        assert row('Furniture').icon(8).isNull()
        panel._on_active_layer_clicked(row('Building'), 8)
        assert scene.active_layer == 'Walls'
        panel.resize(360, 450)
        panel.show()
        QApplication.processEvents()
        pencil_cell = panel.tree.visualRect(panel.tree.indexFromItem(row('Furniture'), 8))
        QTest.mouseClick(panel.tree.viewport(), Qt.LeftButton, pos=pencil_cell.center())
        assert scene.active_layer == 'Furniture'
        assert not row('Furniture').icon(8).isNull()
        assert row('Walls').icon(8).isNull()
        panel._rename(scene.layer('Furniture'), 'Furniture', 'Chairs')
        panel.refresh()
        assert scene.active_layer == 'Chairs'
        panel.tree.setCurrentItem(row('Chairs'))
        panel._on_delete()
        assert scene.active_layer == DEFAULT_LAYER
        assert not row(DEFAULT_LAYER).icon(8).isNull()
    finally:
        panel.close()
