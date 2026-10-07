# SPDX-License-Identifier: GPL-3.0-or-later
"""Line overrides coexist with tag folders, instances and face colours."""
from array import array
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.layer_display import layer_line_buffers
from core.layers import DEFAULT_LAYER, Layer, LayerFolder, assign_layer
from core.scene import Scene
from formats import igz


def test_folder_inheritance_clear_explicit_solid_and_cycle_safety():
    scene = Scene()
    parent = LayerFolder('Plans', edge_color=(1., 0., 0.), line_style='dotted')
    child = LayerFolder('Walls', parent_id=parent.uid, line_style='dashed')
    layer = Layer('Brick', folder_id=child.uid)
    scene.layer_folders = [parent, child]
    scene.layers.append(layer)
    assert scene.layer_setting('Brick', 'edge_color') == (1., 0., 0.)
    assert scene.layer_setting('Brick', 'line_style') == 'dashed'
    layer.line_style = 'solid'
    assert scene.layer_setting('Brick', 'line_style') == 'solid'
    layer.line_style = child.line_style = None
    assert scene.layer_setting('Brick', 'line_style') == 'dotted'
    assert scene.layer_setting(child, 'edge_color') == (1., 0., 0.)
    parent.parent_id = child.uid
    assert scene.layer_setting('Brick', 'missing', 'fallback') == 'fallback'
    scene.layers[0].folder_id = parent.uid  # Layer 0 stays outside folders.
    assert scene.layer_setting(DEFAULT_LAYER, 'edge_color') is None


@pytest.mark.parametrize('cls', [Layer, LayerFolder])
def test_safe_legacy_and_malformed_line_settings(cls):
    assert cls.from_dict({'name': 'Old'}).edge_color is None
    assert cls.from_dict({'name': 'Old'}).line_style is None
    for color in ([float('nan'), 0, 0], [1, 0], 'bad', [0, float('inf'), 0]):
        assert cls.from_dict({'name': 'Bad', 'edge_color': color}).edge_color is None
    restored = cls.from_dict({'name': 'Clamped', 'edge_color': [-1, .5, 2],
                              'line_style': 'unknown'})
    assert restored.edge_color == (0., .5, 1.)
    assert restored.line_style is None


def test_round_trip_single_default_layer_and_nested_folders(tmp_path):
    scene = Scene()
    scene.layers[0].edge_color = (.1, .2, .3)
    scene.layers[0].line_style = 'dashed'
    scene.layers[0].color = (.7, .2, .1)
    path = tmp_path / 'default.igz'
    igz.save_scene(scene, path)
    restored = Scene()
    igz.load_into(restored, path)
    assert restored.layers[0].to_dict() == scene.layers[0].to_dict()
    folder = LayerFolder('Plans', edge_color=(0., .5, 1.), line_style='dotted')
    child = LayerFolder('Child', parent_id=folder.uid)
    scene.layer_folders = [folder, child]
    scene.layers.append(Layer('Walls', folder_id=child.uid, line_style='solid'))
    igz.save_scene(scene, path)
    igz.load_into(restored, path)
    assert [f.to_dict() for f in restored.layer_folders] == [f.to_dict() for f in scene.layer_folders]
    assert restored.layer_setting('Walls', 'edge_color') == (0., .5, 1.)
    assert restored.layer_setting('Walls', 'line_style') == 'solid'


def test_nested_shared_instances_inherit_lines_and_keep_geometry_unchanged():
    scene = Scene()
    scene.layers += [Layer('Red', edge_color=(1., 0., 0.), line_style='dashed'),
                     Layer('Blue', edge_color=(0., 0., 1.), line_style='dotted')]
    root = Group(); root.layer = 'Red'
    middle = Group()
    child = Group()
    edge = child.mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    child.xform = QMatrix4x4(); child.xform.translate(4, 0, 0)
    middle.children.append(child); root.children.append(middle)
    sibling = Group(child.mesh); sibling.layer = 'Blue'
    sibling.xform = QMatrix4x4(); sibling.xform.translate(10, 0, 0)
    root.children.append(sibling); scene.groups.append(root)
    data, runs = layer_line_buffers(scene, (0., 0., 0.))
    assert runs == [((1., 0., 0.), 'dashed', False, 0, 2),
                    ((0., 0., 1.), 'dotted', False, 2, 2)]
    coords = array('f'); coords.frombytes(data)
    assert coords[0] == 4 and coords[6] == 10
    assert edge.layer is None and edge.a == V(0, 0, 0)
    assign_layer(edge, 'Blue')
    assert layer_line_buffers(scene, (0., 0., 0.))[1] == [
        ((0., 0., 1.), 'dotted', False, 0, 4)]
    root.hidden = True
    assert layer_line_buffers(scene, (0., 0., 0.)) == (b'', [])


def test_hidden_locked_soft_edges_and_group_edit_context():
    scene = Scene()
    folder = LayerFolder('Plans', line_style='dashed', visible=False)
    scene.layer_folders.append(folder)
    scene.layers.append(Layer('Walls', folder_id=folder.uid, locked=True))
    group = Group(); group.layer = 'Walls'
    group.mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    group.mesh.add_edge(V(0, 0, 0), V(0, 1, 0)).soft = True
    group.mesh.add_edge(V(0, 0, 0), V(0, 0, 1)).hidden = True
    scene.groups.append(group)
    assert layer_line_buffers(scene, (0., 0., 0.)) == (b'', [])
    folder.visible = True
    assert layer_line_buffers(scene, (0., 0., 0.))[1] == [
        ((0., 0., 0.), 'dashed', False, 0, 2)]
    scene.begin_group_edit(group)
    scene.loose_mesh.add_edge(V(2, 0, 0), V(3, 0, 0))
    runs = layer_line_buffers(scene, (0., 0., 0.), rest_mode='fade')[1]
    assert runs[0] == ((0., 0., 0.), 'solid', True, 0, 2)
    assert runs[1] == ((0., 0., 0.), 'dashed', False, 2, 2)
    assert layer_line_buffers(scene, (0., 0., 0.), rest_mode='hide')[1] == [
        ((0., 0., 0.), 'dashed', False, 0, 2)]
    assert layer_line_buffers(scene, (0., 0., 0.), rest_mode='hide',
                              preview_groups={id(group)}) == (b'', [])


def test_dialog_clears_overrides_and_panel_keeps_face_colour(monkeypatch):
    from PySide6.QtWidgets import QDialog, QWidget
    from views.tray import LayerLineDialog, LayersPanel
    scene = Scene()
    folder = LayerFolder('Plans', edge_color=(0., 0., 1.), line_style='dotted')
    scene.layer_folders.append(folder)
    layer = Layer('Walls', folder_id=folder.uid, color=(1., .5, 0.),
                  edge_color=(1., 0., 0.), line_style='solid')
    scene.layers.append(layer)
    viewport = SimpleNamespace(scene=scene, update=lambda: None)
    window = QWidget()
    window.viewport = viewport
    panel = LayersPanel(window)
    item = panel.tree.topLevelItem(1).child(0)
    panel.tree.setCurrentItem(item)
    initial_version = scene.version

    def accept(dialog):
        dialog._set_color(None)
        dialog._line_style.setCurrentIndex(0)
        return QDialog.Accepted

    monkeypatch.setattr(LayerLineDialog, 'exec', accept)
    panel._on_line_appearance()
    assert layer.edge_color is layer.line_style is None
    assert layer.color == (1., .5, 0.) and scene.version == initial_version + 1
    item = panel.tree.topLevelItem(1).child(0)
    assert item.data(4, Qt.UserRole + 2).blueF() == 1.
    assert item.text(5) == 'Dotted'
    panel.close()


@pytest.mark.parametrize('by_layer', [False, True])
@pytest.mark.parametrize('mode', ['hidden_line', 'wireframe', 'xray'])
def test_rendered_line_patterns_have_gaps_and_update_without_geometry_edits(mode, by_layer):
    """Native GL check: coloured patterns replace rather than cover solids."""
    import numpy as np
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from views.viewport import Viewport
    vp = Viewport()
    try:
        vp.resize(640, 480)
        style = vp.scene.display_style
        style.sky = style.profiles = False
        style.background = (1., 1., 1.)
        style.face_mode = mode
        style.color_by_layer = by_layer
        vp.style_override = style  # Also suppresses the construction axes.
        vp.camera.set_view('front')
        vp.camera.distance = 3.
        vp.camera.perspective = False
        for name, pattern, color, z in (
                ('Solid', 'solid', (.8, 0., 0.), .5),
                ('Dashed', 'dashed', (0., .6, 0.), 0.),
                ('Dotted', 'dotted', (0., 0., .8), -.5)):
            vp.scene.layers.append(Layer(name, edge_color=color, line_style=pattern))
            assign_layer(vp.scene.mesh.add_edge(V(-1, 0, z), V(1, 0, z)), name)
        vp.scene.version += 1
        vp.show()
        for _ in range(10):
            QApplication.processEvents()
        if vp.context() is None or not vp.context().isValid() or vp._gl is None:
            pytest.skip('no native OpenGL context')

        def masks():
            image = vp.render_image(400, 300, overlays=False)
            assert image is not None
            image = image.convertToFormat(QImage.Format_RGBA8888)
            pixels = np.frombuffer(image.constBits(), np.uint8).reshape(
                image.height(), image.bytesPerLine())[:, :image.width() * 4]
            rgb = pixels.reshape(image.height(), image.width(), 4)[..., :3].astype(int)
            return [(rgb[..., c] > np.max(np.delete(rgb, c, axis=2), axis=2) + 40).any(axis=0)
                    for c in range(3)]

        def runs(mask):
            return np.count_nonzero(np.diff(np.r_[False, mask, False].astype(int)) == 1)

        red, green, blue = masks()
        assert runs(red) == 1
        assert runs(green) > 5 and runs(blue) > runs(green)
        assert red.sum() > green.sum() > blue.sum() > 0
        # The display cache must notice style edits even with unchanged geometry.
        vp.scene.layer('Dashed').line_style = 'solid'
        assert runs(masks()[1]) == 1
        vp.scene.layer('Dashed').edge_color = (0., 0., .8)
        assert not masks()[1].any()
        style.edges = False
        if mode != 'wireframe':
            assert not any(mask.any() for mask in masks())
    finally:
        vp.close()
