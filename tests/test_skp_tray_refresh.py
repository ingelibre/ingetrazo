"""Imported tag names must stay exact while Qt renders their labels."""
from types import SimpleNamespace

from PySide6.QtCore import Qt

from core.layers import Layer
from core.scene import Scene
from formats.skp import apply_payload
from views.tray import LayersPanel, ScenesPanel, Tray


def test_skp_tags_with_bom_do_not_abort_tray_refresh():
    name = '\ufeffSkalp Pattern Layer - wit'
    scene = Scene()
    apply_payload(scene, {
        'groups': [], 'protos': [],
        'layers': [{'name': name, 'visible': False}],
        'scenes': [{'name': 'Plan', 'eye': [0, 0, 10],
                    'target': [0, 0, 0], 'hidden_layers': [name]}],
    })
    window = SimpleNamespace(viewport=SimpleNamespace(scene=scene, update=lambda: None))
    layers, scenes = LayersPanel(window), ScenesPanel(window)
    refresh = SimpleNamespace(refresh=lambda: None, refresh_in_model=lambda: None)
    # Exercise the same sequential refresh used after an import: Layers used
    # to throw after detaching every row, preventing Scenes from refreshing.
    tray = SimpleNamespace(entity_info=refresh, layers=layers, scenes=scenes,
                           components=refresh, parts=refresh,
                           _mat_refresh_timer=SimpleNamespace(start=lambda _: None))
    try:
        Tray.on_scene_changed(tray)
        assert layers.tree.topLevelItemCount() == 2
        assert scenes.list.topLevelItemCount() == 1
        assert scenes.list.topLevelItem(0).text(0) == 'Plan'
        assert scene.saved_views[0].hidden_layers == [name]
        assert not layers._updating
        item = layers.tree.topLevelItem(1)
        assert item.checkState(1) == Qt.Unchecked
        item.setCheckState(1, Qt.Checked)
        assert scene.layer(name).visible
        layers.tree.setCurrentItem(item)
        layers.refresh()
        assert layers._item_value(layers.tree.currentItem()) == name
    finally:
        layers.close()
        scenes.close()


def test_moving_and_renaming_a_bom_tag_keeps_its_model_key():
    name = '\ufeffSkalp Pattern Layer - hout'
    scene = Scene()
    scene.layers.append(Layer(name))
    window = SimpleNamespace(viewport=SimpleNamespace(scene=scene, update=lambda: None))
    panel = LayersPanel(window)
    try:
        panel._on_tree_moved()
        assert [ly.name for ly in scene.layers] == ['Layer 0', name]
        item = panel.tree.topLevelItem(1)
        item.setText(0, 'Wood')
        assert scene.layer(name) is None
        assert scene.layer('Wood') is not None
        assert panel.tree.topLevelItem(1).text(0) == 'Wood'
    finally:
        panel.close()
