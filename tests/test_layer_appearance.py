# SPDX-License-Identifier: GPL-3.0-or-later
"""Combined folder inheritance, appearance, rendering and tray interaction."""
from array import array
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QWidget

from core.group import Group
from core.layer_display import layer_face_buffers
from core.layers import Layer, LayerFolder
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def triangle(mesh):
    return mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 0, 1)])


def test_compounded_opacity_tints_and_persistence(tmp_path):
    scene = Scene()
    root = LayerFolder('Building', transparency=20, tint_color=(.8, .2, .1))
    child = LayerFolder('Plans', parent_id=root.uid)
    layer = Layer('Walls', folder_id=child.uid, transparency=50)
    scene.layer_folders = [root, child]; scene.layers.append(layer)
    assert scene.layer_opacity('Walls') == pytest.approx(.4)
    assert scene.layer_opacity('Walls', ('Walls',)) == pytest.approx(.4)
    assert scene.layer_setting('Walls', 'tint_color') == root.tint_color
    path = tmp_path / 'appearance.igz'
    igz.save_scene(scene, path)
    restored = Scene(); igz.load_into(restored, path)
    assert restored.layer_opacity('Walls') == pytest.approx(.4)
    assert [f.to_dict() for f in restored.layer_folders] == [f.to_dict() for f in scene.layer_folders]
    assert restored.layer('Walls').to_dict() == layer.to_dict()
    default = Scene()
    default.layers[0].tint_color = (.2, .3, .4); default.layers[0].transparency = 35
    igz.save_scene(default, path); igz.load_into(restored, path)
    assert restored.layers[0].to_dict() == default.layers[0].to_dict()


@pytest.mark.parametrize('raw, expected', [(None, 0), ('bad', 0), (float('nan'), 0),
                                          (float('inf'), 0), (-20, 0), (150, 100), (25.4, 25)])
def test_malformed_transparency(raw, expected):
    for cls in (Layer, LayerFolder):
        assert cls.from_dict({'name': 'Safe', 'transparency': raw}).transparency == expected


def test_nested_tint_inheritance_keeps_materials():
    scene = Scene()
    folder = LayerFolder('Plans', tint_color=(1., 0., 0.), transparency=20)
    scene.layer_folders.append(folder)
    scene.layers.append(Layer('Walls', folder_id=folder.uid, transparency=50))
    root = Group(); root.layer = 'Walls'
    middle, child = Group(), Group()
    child.xform = QMatrix4x4(); child.xform.translate(4, 0, 0)
    face = triangle(child.mesh)
    face.attrs.update(color=[0., 1., 0.], opacity=.5, texture={'path': 'original.png'})
    original = dict(face.attrs)
    middle.children.append(child); root.children.append(middle); scene.groups.append(root)
    data, runs = layer_face_buffers(scene, lambda face: face.triangulate(), tint=True)
    assert runs[0][:3] == ((1., 0., 0.), pytest.approx(.096), False)
    coordinates = array('f'); coordinates.frombytes(data)
    assert coordinates[0] == 4. and face.attrs == original
    folder.tint_color = None
    assert layer_face_buffers(scene, lambda f: f.triangulate(), tint=True) == (b'', [])
    assert layer_face_buffers(scene, lambda f: f.triangulate())[1][0][1] == pytest.approx(.4)
    folder.visible = False
    assert layer_face_buffers(scene, lambda f: f.triangulate()) == (b'', [])


def test_opacity_updates_front_back_and_instance_variants():
    from views.viewport import Viewport
    vp = Viewport()
    try:
        vp._chunk_cache_load = vp._chunk_cache_store = None
        scene = vp.scene; folder = LayerFolder('Plans')
        scene.layer_folders.append(folder)
        layer = Layer('Walls', folder_id=folder.uid); scene.layers.append(layer)
        group = Group(); group.layer = 'Walls'; group.xform = QMatrix4x4()
        face = triangle(group.mesh)
        face.attrs.update(color=[1., 0., 0.], opacity=.5,
                          back={'color': [0., 0., 1.], 'opacity': .75})
        scene.groups.append(group)
        before = vp._group_chunk(group)
        assert (.5, 1) in before['tcol']
        layer.transparency, folder.transparency = 50, 20
        after = vp._group_chunk(group)
        assert (.2, 1) in after['tcol'] and .3 in after['back_tcol']
        assert before['uid'] != after['uid']
        sibling = Group(group.mesh); sibling.xform = QMatrix4x4()
        assert (.5, 1) in vp._group_chunk(sibling)['tcol']
        layer.transparency = folder.transparency = 0
        assert (.5, 1) in vp._group_chunk(group)['tcol']
    finally:
        vp.close()


def test_only_transparent_placements_leave_instancing():
    from views.viewport import Viewport
    vp = Viewport()
    try:
        vp._chunk_cache_load = vp._chunk_cache_store = None
        opaque = Group(); opaque.xform = QMatrix4x4(); triangle(opaque.mesh)
        vp.scene.layers.append(Layer('Glass', transparency=50))
        transparent = Group(opaque.mesh); transparent.layer = 'Glass'; transparent.xform = QMatrix4x4()
        assert vp._instanced_eligible(opaque) and not vp._instanced_eligible(transparent)
        root, middle = Group(), Group(); root.layer = 'Glass'
        child = Group(opaque.mesh); child.xform = QMatrix4x4()
        middle.children.append(child); root.children.append(middle)
        proxy = vp._expand_placements(root)[-1]
        assert proxy.layer == 'Glass' and not vp._instanced_eligible(proxy)
    finally:
        vp.close()


@pytest.fixture
def panel():
    from views.tray import LayersPanel
    window = QWidget(); window.viewport = SimpleNamespace(scene=Scene(), update=lambda: None)
    panel = LayersPanel(window)
    yield panel
    panel._action_timer.stop(); panel.close(); window.close()
    QSettings().remove('layers/panel_height'); QSettings().remove('layers/columns/tint')


def test_filter_keeps_folder_state_and_selection(panel):
    root = LayerFolder('Building', expanded=False)
    panel._scene().layer_folders.append(root)
    panel._scene().layers.extend([Layer('Walls', folder_id=root.uid), Layer('Site')])
    panel.refresh(); folder = panel.tree.topLevelItem(1); wall = folder.child(0)
    wall.setSelected(True); panel.filter_input.setText('walls')
    assert folder.isExpanded() and not folder.isHidden() and not wall.isHidden()
    assert not root.expanded and wall.isSelected()
    assert panel.tree.topLevelItem(2).isHidden() and not panel.tree.dragEnabled()
    panel.filter_input.clear()
    assert not folder.isExpanded() and not panel.tree.topLevelItem(2).isHidden()
    assert panel.tree.dragEnabled()


def test_sort_cycles_keep_default_and_folders_first(panel):
    scene = panel._scene()
    scene.layers.extend([Layer('Zulu', position=1), Layer('Alpha', position=2)])
    scene.layer_folders.append(LayerFolder('Folder')); panel.refresh()
    def names():
        return [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]
    assert names() == ['Layer 0', 'Folder', 'Alpha', 'Zulu']
    panel._on_header_clicked(0)
    assert names()[-2:] == ['Alpha', 'Zulu'] and not panel.tree.dragEnabled()
    panel._on_header_clicked(0)
    assert names() == ['Layer 0', 'Folder', 'Zulu', 'Alpha']
    panel._on_header_clicked(0)
    assert names()[-2:] == ['Zulu', 'Alpha'] and panel.tree.dragEnabled()
    assert [ly.name for ly in scene.layers] == ['Layer 0', 'Zulu', 'Alpha']


def test_columns_height_and_appearance_dialog(panel):
    from views.tray import LayerAppearanceDialog
    layer = Layer('Walls', color=(.1, .2, .3)); panel._scene().layers.append(layer); panel.refresh()
    action = next(a for a in panel._columns_menu.actions() if a.text() == 'Tint')
    action.setChecked(True)
    assert not panel.tree.isColumnHidden(6) and QSettings().value('layers/columns/tint', type=bool)
    panel._set_height(310); panel.refresh(); assert panel.tree.height() == 310
    dialog = LayerAppearanceDialog(layer)
    dialog._set_tint((1., 0., 0.)); dialog._transparency.setValue(40); dialog._set_color((0., 0., 1.))
    dialog._line_style.setCurrentIndex(dialog._line_style.findData('dotted')); dialog.apply_to(layer)
    assert layer.tint_color == (1., 0., 0.) and layer.transparency == 40
    assert layer.color == (.1, .2, .3) and layer.line_style == 'dotted'
    panel.refresh(); item = panel.tree.topLevelItem(1)
    assert item.text(7) == '40%' and item.data(6, Qt.UserRole + 2).redF() == 1.
    dialog.close()


@pytest.mark.parametrize('by_layer', [False, True])
@pytest.mark.parametrize('mode', ['textures', 'hidden_line', 'monochrome', 'shaded'])
def test_native_opacity_and_tint_preserve_original_face_material(mode, by_layer):
    from PySide6.QtWidgets import QApplication
    from views.viewport import Viewport
    vp = Viewport()
    try:
        vp.resize(640, 480)
        style = vp.scene.display_style
        style.face_mode, style.color_by_layer = mode, by_layer
        style.sky = style.edges = style.profiles = False
        style.front_color = (.2, .3, .4)
        style.background = (1., 1., 1.)
        vp.style_override = style
        vp.camera.set_view('front'); vp.camera.distance = 2.
        vp.camera.target = V(.33, 0, .33); vp.camera.perspective = False
        folder = LayerFolder('Plans')
        vp.scene.layer_folders.append(folder)
        layer = Layer('Walls', folder_id=folder.uid, color=(.1, .2, .7))
        vp.scene.layers.append(layer)
        root, middle, child = Group(), Group(), Group()
        root.layer = 'Walls'; child.xform = QMatrix4x4()
        face = triangle(child.mesh); face.attrs['color'] = [.7, .1, .2]
        middle.children.append(child); root.children.append(middle); vp.scene.groups.append(root)
        vp.scene.version += 1; vp.show()
        for _ in range(10):
            QApplication.processEvents()
        if vp.context() is None or not vp.context().isValid() or vp._gl is None:
            pytest.skip('no native OpenGL context')
        def pixel():
            image = vp.render_image(400, 300, overlays=False)
            assert image is not None
            color = image.pixelColor(200, 150)
            return color.red(), color.green(), color.blue()
        original = pixel()
        assert min(original) < 200
        folder.transparency = 50; vp.scene.version += 1
        faded = pixel()
        assert faded == pytest.approx(tuple((c + 255) / 2 for c in original), abs=3)
        layer.transparency = 50; vp.scene.version += 1
        combined = pixel()
        assert combined == pytest.approx(tuple(c * .25 + 255 * .75 for c in original), abs=3)
        # Style overrides can switch without a scene-version change.
        style.color_by_layer = not by_layer
        assert pixel() != combined
        style.color_by_layer = by_layer
        assert pixel() == combined
        layer.transparency = 0
        folder.transparency = 0
        folder.tint_color = (0., 1., 0.); vp.scene.version += 1
        tinted = pixel()
        assert tinted[1] > original[1] and tinted[0] < original[0]
        assert face.attrs['color'] == [.7, .1, .2]
        folder.tint_color = None; vp.scene.version += 1
        assert pixel() == original
    finally:
        vp.close()


def test_layer_color_picker_transparency_reaches_display_and_saved_file(panel, monkeypatch, tmp_path):
    from PySide6.QtGui import QColor
    from views import tray
    layer = Layer('Glass', color=(.2, .4, .6), transparency=25)
    scene = panel._scene()
    scene.layers.append(layer)
    scene.display_style.color_by_layer = True
    face = triangle(scene.mesh)
    face.attrs.update(layer='Glass', opacity=.8)
    panel.refresh()
    item = panel.tree.topLevelItem(1)
    captured = {}
    def choose(initial, parent, title, **options):
        captured.update(alpha=initial.alphaF(), options=options)
        return QColor.fromRgbF(.7, .2, .3, .4)
    monkeypatch.setattr(tray, 'get_color', choose)
    panel._on_color_clicked(item, 3)
    assert captured['alpha'] == pytest.approx(.75, abs=.001)
    assert captured['options']['checker_preview']
    assert layer.transparency == 60
    _, runs = layer_face_buffers(scene, lambda face: face.triangulate())
    assert runs[0][1] == pytest.approx(.4)
    assert face.attrs['opacity'] == .8
    chip = panel.tree.topLevelItem(1).data(3, Qt.UserRole + 2)
    assert chip.alphaF() == pytest.approx(.4, abs=.001)
    path = tmp_path / 'transparent-layer.igz'
    igz.save_scene(scene, path)
    restored = Scene()
    igz.load_into(restored, path)
    assert restored.layer('Glass').transparency == 60
    assert restored.display_style.color_by_layer


def test_transparent_swatch_composites_over_checkerboard():
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from views.color_dialog import paint_color_swatch
    image = QImage(32, 16, QImage.Format_ARGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    paint_color_swatch(painter, QRect(0, 0, 32, 16), QColor(255, 0, 0, 128))
    painter.end()
    dark, light = image.pixelColor(2, 2), image.pixelColor(6, 2)
    assert dark.red() > dark.green() and light.red() > light.green()
    assert dark.green() < light.green()
    painter = QPainter(image)
    paint_color_swatch(painter, QRect(0, 0, 32, 16), QColor(255, 0, 0))
    painter.end()
    assert image.pixelColor(2, 2) == image.pixelColor(6, 2) == QColor(255, 0, 0)


def test_repeated_layer_geometry_is_triangulated_once_with_independent_opacity():
    from core.layer_display import layer_line_buffers
    scene = Scene()
    scene.layers += [Layer('Red', color=(1., 0., 0.), transparency=50),
                     Layer('Blue', color=(0., 0., 1.), transparency=75)]
    mesh = Mesh(); face = triangle(mesh)
    for name, offset in [('Red', 0), ('Blue', 4)]:
        group = Group(mesh); group.layer = name; group.xform = QMatrix4x4()
        group.xform.translate(offset, 0, 0); scene.groups.append(group)
    calls = []
    def triangulate(face):
        calls.append(face)
        return face.triangulate()
    data, runs = layer_face_buffers(scene, triangulate)
    assert calls == [face]
    assert [run[1] for run in runs] == [.5, .25]
    vertices = array('f'); vertices.frombytes(data)
    assert min(vertices[runs[0][3] * 3::3]) == 0
    assert min(vertices[runs[1][3] * 3::3]) == 4
    lines, spans = layer_line_buffers(scene, (0., 0., 0.))
    assert sum(span[-1] for span in spans) == 2 * len(mesh.edges) * 2
    # A later geometry edit must not reuse the previous call's local data.
    mesh.add_face([V(2, 0, 0), V(3, 0, 0), V(2, 0, 1)])
    calls.clear(); layer_face_buffers(scene, triangulate)
    assert len(calls) == 2


def test_color_by_layer_keeps_transparent_instances_shared_and_rekeys_modes():
    from views.viewport import Viewport
    vp = Viewport()
    try:
        vp._chunk_cache_load = vp._chunk_cache_store = None
        scene = vp.scene
        scene.layers.append(Layer('Glass', transparency=50))
        group = Group(); group.layer = 'Glass'; group.xform = QMatrix4x4()
        triangle(group.mesh); scene.groups.append(group)
        assert not vp._instanced_eligible(group)
        before = vp._placements_epoch()
        scene.display_style.color_by_layer = True
        assert vp._instanced_eligible(group)
        assert vp._placements_epoch() != before
        scene.display_style.color_by_layer = False
        assert not vp._instanced_eligible(group)
        assert vp._placements_epoch() == before
    finally:
        vp.close()


def test_many_layer_chunk_checks_reuse_opacity_resolution(monkeypatch):
    """Profiles and picking revisit chunks; they must not resolve every tag."""
    from views.viewport import Viewport
    vp = Viewport()
    try:
        vp._chunk_cache_load = vp._chunk_cache_store = None
        scene = vp.scene
        folder = LayerFolder('Glass', transparency=20)
        scene.layer_folders.append(folder)
        scene.layers.extend(Layer(f'Tag {i}', folder_id=folder.uid)
                            for i in range(80))
        group = Group(); group.layer = 'Tag 79'; triangle(group.mesh)
        scene.groups.append(group)
        before = vp._group_chunk(group)
        original = Scene.layer_opacity
        calls = []

        def counted(self, *args, **kwargs):
            calls.append(args)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Scene, 'layer_opacity', counted)
        for _ in range(10):
            assert vp._group_chunk(group) is before
        assert calls == []
        # Appearance can be changed without a version bump; both caches
        # must see it, including reparenting and removal of transparency.
        folder.transparency = 50
        after = vp._group_chunk(group)
        assert after['uid'] != before['uid'] and (.5, 0) in after['tcol']
        assert vp._layer_opacity_state()[2]['Tag 79'] == .5
        scene.layer('Tag 79').folder_id = None
        assert vp._layer_opacity_state()[2]['Tag 79'] == 1.0
        folder.transparency = 0
        assert vp._layer_opacity_state()[1] is False
    finally:
        vp.close()
