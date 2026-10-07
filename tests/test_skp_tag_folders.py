# SPDX-License-Identifier: GPL-3.0-or-later
"""Native tag-folder import/export, including hidden-folder geometry."""
from types import SimpleNamespace as NS

import pytest
from PySide6.QtGui import QVector3D

from core.layers import Layer, LayerFolder, assign_layer
from core.scene import Scene
from formats import skp, skp_openskp, skp_out


def test_payload_maps_duplicate_names_and_scene_visibility_by_id():
    scene = Scene()
    existing = Layer('Existing', visible=False)
    scene.layers.append(existing)
    payload = dict(backend='openskp', groups=[], protos=[],
                   layer_folders=[dict(id=1, name='Same', parent_id=None, visible=False),
                                  dict(id=2, name='Same', parent_id=1)],
                   layers=[dict(name='Walls', folder_id=2, position=3),
                           dict(name='Existing', folder_id=2, visible=True)],
                   scenes=[dict(name='View', eye=[1,1,1], target=[0,0,0],
                                hidden_layer_folders=[1])])
    skp.apply_payload(scene, payload)
    parent, child = scene.layer_folders
    assert parent.name == child.name
    assert parent.uid != child.uid
    assert child.parent_id == parent.uid
    assert scene.layer('Walls').folder_id == child.uid
    assert scene.layer('Walls').position == 3
    assert not scene.layer_state('Walls')[0]
    assert not existing.visible and existing.folder_id is None
    assert scene.saved_views[0].hidden_layer_folders == [parent.uid]
    # Source IDs from another file/import must not collide with local IDs.
    skp.apply_payload(scene, payload)
    assert len({f.uid for f in scene.layer_folders}) == 4
    assert scene.layer('Walls').folder_id == child.uid


def test_adapter_carries_native_folder_ids():
    model = NS(layer_folders=[NS(id=257, name='Folder', parent_id=None,
                                position=2, hidden=True)],
               layers=[NS(name='Walls', hidden=False, folder_id=257, position=4)])
    assert skp_openskp.file_layer_folder_records(model) == [
        dict(id=257, name='Folder', parent_id=None, position=2, visible=False)]
    assert skp_openskp.file_layer_records(model) == [
        dict(name='Walls', visible=True, folder_id=257, position=4)]


def test_folder_import_undo_redo_preserves_membership():
    from core.history import History, SnapshotImport
    scene = Scene()
    history = History(scene)
    payload = dict(backend='openskp', groups=[], protos=[],
                   layer_folders=[dict(id=10, name='Folder', visible=False)],
                   layers=[dict(name='Walls', folder_id=10)])
    history.execute(SnapshotImport(lambda s: skp.apply_payload(s, payload)))
    uid = scene.layer_folders[0].uid
    assert scene.layer('Walls').folder_id == uid
    history.undo()
    assert scene.layer_folders == [] and scene.layer('Walls') is None
    history.redo()
    assert scene.layer_folders[0].uid == uid
    assert scene.layer('Walls').folder_id == uid


def test_failed_folder_import_removes_partial_additions():
    from core.history import History, SnapshotImport
    scene = Scene()
    existing = LayerFolder('Existing')
    scene.layer_folders.append(existing)

    def fail(s):
        skp.apply_payload(s, dict(backend='openskp', groups=[], protos=[],
                                 layer_folders=[dict(id=10, name='Partial')],
                                 layers=[dict(name='Walls', folder_id=10)]))
        raise ValueError('failed import')

    history = History(scene)
    history.execute(SnapshotImport(fail))
    assert scene.layer_folders == [existing]
    assert scene.layer('Walls') is None
    assert history.undo_stack == []
    assert history.last_error == 'SnapshotImport: failed import'


def test_native_export_keeps_hidden_folder_geometry_empty_tags_and_folders(tmp_path):
    openskp = pytest.importorskip('openskp')
    assert hasattr(openskp.SkpBuilder, 'add_layer_folder'), 'install the pinned tag-folder OpenSKP fork'
    scene = Scene()
    parent = LayerFolder('Same', visible=False)
    child = LayerFolder('Same', parent_id=parent.uid)
    empty = LayerFolder('Empty')
    scene.layer_folders = [parent, child, empty]
    scene.layers += [Layer('Walls', folder_id=child.uid, position=5),
                     Layer('First tag', folder_id=child.uid, position=2),
                     Layer('Empty tag', visible=False, folder_id=parent.uid)]
    face = scene.mesh.add_face([QVector3D(0,0,0), QVector3D(1,0,0), QVector3D(0,1,0)])
    assign_layer(face, 'Walls')
    assert not scene.entity_visible(face)
    path = tmp_path/'folders.skp'
    skp_out.save_skp(scene, path)
    model = openskp.SkpFile.open(str(path)).parse()
    folders = model.layer_folders
    assert [f.name for f in folders] == ['Same', 'Same', 'Empty']
    assert folders[0].hidden
    assert folders[1].parent_id == folders[0].id
    layers = {l.name: l for l in model.layers}
    assert layers['Walls'].folder_id == folders[1].id
    assert layers['First tag'].position < layers['Walls'].position
    assert layers['Empty tag'].folder_id == folders[0].id
    assert layers['Empty tag'].hidden
    assert len(model.root.faces) == 1
    fresh = Scene()
    skp.apply_payload(fresh, skp_openskp._adapt(model, 'folders'))
    assert len(fresh.layer_folders) == 3
    assert not fresh.layer_state('Walls')[0]


def test_export_rejects_old_writers_and_cycles():
    scene = Scene()
    folder = LayerFolder('Folder')
    scene.layer_folders = [folder]
    with pytest.raises(RuntimeError, match='native tag folders'):
        skp_out._collect_layer_folders(scene, NS(), {})
    folder.parent_id = folder.uid
    builder = NS(add_layer_folder=lambda *a, **k: 0, set_layer_folder=lambda *a: None)
    with pytest.raises(ValueError, match='Cyclic'):
        skp_out._collect_layer_folders(scene, builder, {})
