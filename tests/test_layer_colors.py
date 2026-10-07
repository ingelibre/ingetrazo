# SPDX-License-Identifier: GPL-3.0-or-later
from array import array
from types import SimpleNamespace as NS

import pytest
from PySide6.QtGui import QVector3D as V, QMatrix4x4

from core.group import Group
from core.layer_display import layer_display_buffers
from core.layers import Layer, LayerFolder, assign_layer
from core.mesh import Mesh
from core.scene import Scene
from core.style import Style
from formats import igz, skp, skp_openskp, skp_out


def triangle(mesh):
    return mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])


def buffers(scene, **kwargs):
    return layer_display_buffers(scene, lambda f: f.triangulate(), **kwargs)


def test_native_file_preserves_colors_and_display_switch(tmp_path):
    scene = Scene()
    scene.layers.append(Layer('Walls', color=(1., .25, 0.)))
    scene.layers[0].color = (.1, .2, .3)
    scene.display_style.color_by_layer = True
    path = tmp_path / 'colors.igz'
    igz.save_scene(scene, path)
    restored = Scene()
    igz.load_into(restored, path)
    assert restored.layer('Walls').color == (1., .25, 0.)
    assert restored.layers[0].color == (.1, .2, .3)
    assert restored.display_style.color_by_layer
    assert not Style.from_dict({}).color_by_layer
    assert len(Layer.from_dict({'name': 'Old tag'}).color) == 3


def test_nested_instance_inheritance_transform_and_material_preservation():
    scene = Scene()
    scene.layers += [Layer('Red', color=(1., 0., 0.)),
                     Layer('Blue', color=(0., 0., 1.))]
    shared = Mesh()
    face = triangle(shared)
    face.attrs.update(color=[0., 1., 0.], opacity=.2, texture={'path': 'original.png'})
    root = Group()
    root.layer = 'Red'
    middle = Group()
    child = Group(shared)
    child.xform = QMatrix4x4()
    child.xform.translate(4, 0, 0)
    middle.children.append(child)
    root.children.append(middle)
    sibling = Group(shared)
    sibling.layer = 'Blue'
    sibling.xform = QMatrix4x4()
    sibling.xform.translate(10, 0, 0)
    root.children.append(sibling)
    scene.groups.append(root)
    (data, runs), _ = buffers(scene)
    coords = array('f'); coords.frombytes(data)
    assert [r[0] for r in runs] == [(1., 0., 0.), (0., 0., 1.)]
    assert coords[0] == 4 and coords[9] == 10
    assert face.attrs['color'] == [0., 1., 0.]
    assert face.attrs['opacity'] == .2
    assert face.attrs['texture']['path'] == 'original.png'
    assign_layer(face, 'Blue')
    assert buffers(scene)[0][1][0][0] == (0., 0., 1.)
    root.hidden = True
    assert buffers(scene)[0] == (b'', [])


def test_hidden_folder_locked_layer_edges_and_edit_context():
    scene = Scene()
    folder = LayerFolder('Folder', visible=False)
    scene.layer_folders.append(folder)
    layer = Layer('Walls', folder_id=folder.uid, locked=True, color=(1., 0., 0.))
    scene.layers.append(layer)
    group = Group()
    group.layer = 'Walls'
    face = triangle(group.mesh)
    scene.groups.append(group)
    assert buffers(scene)[0] == (b'', [])
    folder.visible = True
    assert buffers(scene)[0][1][0][3] == 3
    assert buffers(scene)[1][1][0][0] == (0., 0., 0.)
    scene.begin_group_edit(group)
    triangle(scene.loose_mesh)
    (data, runs), _ = buffers(scene, rest_mode='hide')
    assert len(data) == 36 and runs[0][0] == layer.color
    assert not runs[0][1]
    assert len(buffers(scene, suppressed={face})[0][0]) == 36


def test_skp_adapter_carries_layer_rgb_and_writer_receives_it():
    model = NS(layers=[NS(name='Walls', hidden=False, color_r=255,
                         color_g=64, color_b=0)])
    records = skp_openskp.file_layer_records(model)
    assert records[0]['color'] == [1., 64 / 255, 0.]
    scene = Scene()
    skp.apply_payload(scene, dict(groups=[], protos=[], layers=records))
    class Builder:
        def add_layer(self, name, color=None, hidden=False):
            self.received = (name, color, hidden)
            return 1
    builder = Builder()
    skp_out._collect_layers(scene, builder)
    assert builder.received == ('Walls', (255, 64, 0), False)


def test_real_skp_layer_color_round_trip(tmp_path):
    openskp = pytest.importorskip('openskp')
    scene = Scene()
    scene.layers.append(Layer('Walls', color=(1., 64 / 255, 0.)))
    assign_layer(triangle(scene.mesh), 'Walls')
    path = tmp_path / 'colors.skp'
    skp_out.save_skp(scene, path)
    model = openskp.SkpFile.open(str(path)).parse()
    tag = next(ly for ly in model.layers if ly.name == 'Walls')
    assert (tag.color_r, tag.color_g, tag.color_b) == (255, 64, 0)


def test_layer_panel_switch_and_color_swatch():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from views.tray import LayersPanel
    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.layers.append(Layer('Walls', color=(1., 0., 0.)))
    viewport = NS(scene=scene, update=lambda: None)
    panel = LayersPanel(NS(viewport=viewport))
    panel._color_by_layer.setChecked(True)
    assert scene.display_style.color_by_layer
    item = next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                if panel.tree.topLevelItem(i).data(0, Qt.UserRole) == 'Walls')
    assert item.data(3, Qt.UserRole + 2).redF() == 1.
    assert item.background(3).style() == Qt.NoBrush
    assert panel.tree.columnWidth(3) == 44
    panel._color_by_layer.setChecked(False)
    assert not scene.display_style.color_by_layer
    panel.close()
