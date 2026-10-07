"""Layer organization, inherited state and saved-view persistence."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera
from core.layers import DEFAULT_LAYER, Layer, LayerFolder, assign_layer, layer_of
from core.saved_views import SavedView
from core.scene import Scene
from formats.igz import load_into, save_scene
from views.tray import LayersPanel


@pytest.fixture
def panel():
    scene = Scene()
    viewport = SimpleNamespace(scene=scene, update=lambda: None)
    widget = LayersPanel(SimpleNamespace(viewport=viewport))
    yield widget
    widget.close()


def populate(panel):
    scene = panel._scene()
    root = LayerFolder("Building", position=1)
    child = LayerFolder("Ground", parent_id=root.uid)
    layer = Layer("Walls", folder_id=child.uid)
    scene.layer_folders = [root, child]
    scene.layers += [layer, Layer("Furniture", position=2)]
    panel.refresh()
    return scene, root, child, layer


def test_folder_state_filters_geometry_and_selection(panel):
    scene, root, child, layer = populate(panel)
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, layer.name)
    scene.selection.add(edge)
    item = panel.tree.topLevelItem(1)
    item.setCheckState(2, Qt.Checked)
    assert scene.entity_visible(edge)
    assert not scene.entity_selectable(edge)
    assert not scene.selection
    item.setCheckState(2, Qt.Unchecked)
    item.setCheckState(1, Qt.Unchecked)
    assert not scene.entity_visible(edge)
    assert not list(scene.render_edges())
    assert layer.visible  # folder switches preserve individual layer switches
    item.setCheckState(1, Qt.Checked)
    assert scene.entity_visible(edge)
    child.visible = False
    assert not scene.entity_visible(edge)
    assert scene.layer_state(DEFAULT_LAYER) == (True, False)


def test_nested_folders_round_trip_and_clear(panel, tmp_path):
    scene, root, child, layer = populate(panel)
    root.visible = False
    root.locked = True
    root.expanded = False
    layer.position = 4
    scene.saved_views = [SavedView.capture("Plan", scene, OrbitCamera())]
    path = tmp_path / "folders.igz"
    save_scene(scene, path)
    fresh = Scene()
    load_into(fresh, path)
    assert [f.to_dict() for f in fresh.layer_folders] == [f.to_dict() for f in scene.layer_folders]
    assert fresh.layer("Walls").to_dict() == layer.to_dict()
    assert fresh.layer_state("Walls") == (False, True)
    root2 = fresh.layer_folders[0]
    root2.visible = True
    fresh.saved_views[0].apply(fresh, OrbitCamera())
    assert not root2.visible
    fresh.clear()
    assert fresh.layer_folders == []
    assert [ly.name for ly in fresh.layers] == [DEFAULT_LAYER]


def test_move_reorder_and_root(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    ground = tree.topLevelItem(1).child(0)
    furniture = tree.takeTopLevelItem(2)
    ground.insertChild(0, furniture)
    panel._on_tree_moved()
    assert scene.layer("Furniture").folder_id == child.uid
    assert scene.layer("Furniture").position < layer.position
    ground = tree.topLevelItem(1).child(0)
    tree.setCurrentItem(ground.child(0))
    panel._on_move_to_root()
    assert scene.layer("Furniture").folder_id is None
    assert layer.folder_id == child.uid


def test_delete_folder_keeps_layers_and_subfolders(panel):
    scene, root, child, layer = populate(panel)
    panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
    panel._on_delete()
    assert scene.layer_folders == [child]
    assert child.parent_id is None
    assert layer in scene.layers and layer.folder_id == child.uid
    panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
    panel._on_delete()
    assert scene.layer_folders == []
    assert layer.folder_id is None


def test_add_and_collapse(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    tree.setCurrentItem(tree.topLevelItem(1).child(0))
    panel._on_add()
    assert scene.layers[-1].folder_id == child.uid
    height = tree.height()
    tree.topLevelItem(1).setExpanded(False)
    assert not root.expanded and tree.height() < height
    panel.refresh()
    assert not tree.topLevelItem(1).isExpanded()
    tree.setCurrentItem(tree.topLevelItem(1))
    panel._on_add_folder()
    assert scene.layer_folders[-1].parent_id is None
    assert root.parent_id == scene.layer_folders[-1].uid


def test_alphabetical_order_and_invalid_parents(panel):
    scene = panel._scene()
    scene.layers += [Layer.from_dict({"name": name}) for name in ("B", "A", "C")]
    panel.refresh()
    assert [panel.tree.topLevelItem(i).text(0) for i in range(4)] == [DEFAULT_LAYER, "A", "B", "C"]
    root = LayerFolder("Root", uid="a", parent_id="b")
    child = LayerFolder("Child", uid="b", parent_id="a", visible=False)
    scene.layer_folders = [root, child]
    scene.layer("B").folder_id = root.uid
    panel.refresh()
    assert panel.tree.topLevelItemCount() == 5
    assert scene.layer_state("B") == (False, False)
    assert not panel.tree.topLevelItem(0).flags() & Qt.ItemIsDragEnabled
    assert not panel.tree.topLevelItem(0).flags() & Qt.ItemIsDropEnabled


def test_legacy_scene_recall_restores_flat_visibility(panel):
    scene, root, child, layer = populate(panel)
    root.visible = False
    SavedView.from_dict({"name": "Old", "hidden_layers": ["Walls"]}).apply(scene, OrbitCamera())
    assert root.visible and child.visible and not layer.visible
    root.visible = False
    view = SavedView.capture("New", scene, OrbitCamera())
    root.visible = True
    view.recapture(scene, OrbitCamera())
    assert not view.hidden_layer_folders


def test_empty_folder_document_clears():
    scene = Scene()
    scene.layer_folders.append(LayerFolder("Empty"))
    scene.clear()
    assert not scene.layer_folders


@pytest.mark.parametrize("fail", [False, True])
def test_sheet_scene_restores_live_folder_visibility(panel, fail):
    from core.composition import MarcoVista
    import views.composer as composer
    scene, root, child, layer = populate(panel)
    camera = OrbitCamera()
    root.visible = False
    scene.saved_views = [SavedView.capture("Plan", scene, camera)]
    root.visible = True
    owner = next(c for c in vars(composer).values()
                 if isinstance(c, type) and hasattr(c, "_with_frame_camera"))
    fake = SimpleNamespace(_window=SimpleNamespace(viewport=SimpleNamespace(
        scene=scene, camera=camera, update=lambda: None)))
    frame = MarcoVista(view_key="scene:Plan")
    def render():
        assert not root.visible
        assert not scene.layer_state(layer.name)[0]
        if fail:
            raise RuntimeError("Rendering failed")
        return "ok"
    if fail:
        with pytest.raises(RuntimeError):
            owner._with_frame_camera(fake, frame, render)
    else:
        assert owner._with_frame_camera(fake, frame, render) == "ok"
    assert root.visible


def test_rename_nested_layer_updates_geometry_and_saved_views(panel):
    from core.group import Group
    from core.mesh import Mesh
    from core.textlabel import TextLabel
    scene, root, child, layer = populate(panel)
    group = Group(Mesh())
    edge = group.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, layer.name)
    scene.groups.append(group)
    label = TextLabel(QVector3D(), QVector3D(1, 1, 0), "Wall")
    assign_layer(label, layer.name)
    scene.text_labels.append(label)
    scene.saved_views.append(SavedView("Plan", hidden_layers=[layer.name]))
    panel.tree.topLevelItem(1).child(0).child(0).setText(0, "Structure")
    assert edge.layer == label.layer == "Structure"
    assert scene.saved_views[0].hidden_layers == ["Structure"]
    assert layer.folder_id == child.uid


def test_multiple_selection_survives_refresh_and_rename(panel):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    panel.show()
    QApplication.processEvents()
    walls = tree.topLevelItem(1).child(0).child(0)
    furniture = tree.topLevelItem(2)
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier,
                     tree.visualItemRect(walls).center())
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.ShiftModifier,
                     tree.visualItemRect(furniture).center())
    assert {panel._item_value(i) for i in tree.selectedItems()} == {'Walls', 'Furniture'}
    panel.refresh()
    assert {panel._item_value(i) for i in tree.selectedItems()} == {'Walls', 'Furniture'}
    assert panel._item_value(tree.currentItem()) == 'Furniture'
    tree.topLevelItem(1).child(0).child(0).setText(0, 'Structure')
    assert {panel._item_value(i) for i in tree.selectedItems()} == {'Structure', 'Furniture'}
    assert panel._item_value(tree.currentItem()) == 'Furniture'


def test_move_multiple_layers_and_parent_to_root(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    ground = tree.topLevelItem(1).child(0)
    furniture = tree.takeTopLevelItem(2)
    ground.addChild(furniture)
    for item in (ground.child(0), furniture):
        item.setSelected(True)
    panel._on_tree_moved()
    assert layer.folder_id == scene.layer('Furniture').folder_id == child.uid
    assert len(tree.selectedItems()) == 2
    panel._on_move_to_root()
    assert layer.folder_id is None and scene.layer('Furniture').folder_id is None
    assert len(tree.selectedItems()) == 2
    # A selected descendant must stay inside its selected parent.
    building = tree.topLevelItem(1)
    ground = building.child(0)
    tree.clearSelection()
    building.setSelected(True)
    ground.setSelected(True)
    panel._on_move_to_root()
    assert child.parent_id == root.uid


@pytest.mark.parametrize('parent_first', [True, False])
def test_delete_multiple_folders_and_layers_keeps_unselected_contents(panel, parent_first):
    from core.group import Group
    from core.mesh import Mesh
    from core.textlabel import TextLabel
    scene, root, child, layer = populate(panel)
    scene.layers.append(Layer('Keep', folder_id=child.uid))
    group = Group(Mesh())
    edge = group.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, 'Walls')
    assign_layer(group, 'Furniture')
    scene.groups.append(group)
    label = TextLabel(QVector3D(), QVector3D(1, 1, 0), 'Wall')
    assign_layer(label, 'Walls')
    scene.text_labels.append(label)
    panel.refresh()
    tree = panel.tree
    building = tree.topLevelItem(1)
    ground = building.child(0)
    walls = next(ground.child(i) for i in range(ground.childCount())
                 if ground.child(i).text(0) == 'Walls')
    furniture = tree.topLevelItem(2)
    items = [building, ground, walls, furniture, tree.topLevelItem(0)]
    for item in items if parent_first else reversed(items):
        item.setSelected(True)
    panel._on_delete()
    assert scene.layer_folders == []
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER, 'Keep']
    assert scene.layer('Keep').folder_id is None
    assert layer_of(edge) == layer_of(group) == layer_of(label) == DEFAULT_LAYER


def test_context_menu_keeps_multiple_selection(panel, monkeypatch):
    from PySide6.QtWidgets import QApplication
    scene, root, child, layer = populate(panel)
    panel.show()
    QApplication.processEvents()
    tree = panel.tree
    walls = tree.topLevelItem(1).child(0).child(0)
    furniture = tree.topLevelItem(2)
    tree.setCurrentItem(furniture)
    walls.setSelected(True)
    import views.tray as tray
    class Menu:
        def __init__(self, *args):
            pass
        def addAction(self, *args):
            pass
        def exec(self, *args):
            pass
    monkeypatch.setattr(tray, 'QMenu', Menu)
    panel._on_context_menu(tree.visualItemRect(walls).center())
    assert {panel._item_value(i) for i in tree.selectedItems()} == {'Walls', 'Furniture'}
    assert panel._item_value(tree.currentItem()) == 'Walls'


def test_assign_uses_active_layer_with_multiple_selected(panel):
    from core.history import History
    scene, root, child, layer = populate(panel)
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    scene.selection.add(edge)
    panel._window.viewport.history = History(scene)
    panel._window.statusBar = lambda: SimpleNamespace(showMessage=lambda *args: None)
    tree = panel.tree
    tree.setCurrentItem(tree.topLevelItem(2))
    tree.topLevelItem(1).child(0).child(0).setSelected(True)
    panel._on_assign()
    assert edge.layer == 'Furniture'
    panel._window.viewport.history.undo()
    assert layer_of(edge) == DEFAULT_LAYER


def test_multiple_selected_layers_toggle_visibility_together(panel):
    scene, root, child, layer = populate(panel)
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, 'Walls')
    scene.selection.add(edge)
    tree = panel.tree
    walls = tree.topLevelItem(1).child(0).child(0)
    furniture = tree.topLevelItem(2)
    tree.setCurrentItem(walls)
    furniture.setSelected(True)
    version = scene.version
    walls.setCheckState(1, Qt.Unchecked)
    assert not layer.visible and not scene.layer('Furniture').visible
    assert furniture.checkState(1) == Qt.Unchecked
    assert root.visible and child.visible and scene.layer(DEFAULT_LAYER).visible
    assert not scene.selection
    assert len(tree.selectedItems()) == 2
    assert scene.version == version + 1
    furniture.setCheckState(1, Qt.Checked)
    assert layer.visible and scene.layer('Furniture').visible
    assert walls.checkState(1) == Qt.Checked


def test_selected_folder_and_layer_toggle_without_changing_unselected_children(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    building = tree.topLevelItem(1)
    furniture = tree.topLevelItem(2)
    tree.setCurrentItem(building)
    furniture.setSelected(True)
    building.setCheckState(1, Qt.Unchecked)
    assert not root.visible and not scene.layer('Furniture').visible
    assert child.visible and layer.visible
    assert not scene.layer_state('Walls')[0]
    # Updating an unselected row leaves the selected rows untouched.
    walls = building.child(0).child(0)
    walls.setCheckState(1, Qt.Unchecked)
    walls.setCheckState(1, Qt.Checked)
    assert not root.visible and not scene.layer('Furniture').visible
    building.setCheckState(1, Qt.Checked)
    assert root.visible and scene.layer('Furniture').visible
    assert scene.layer_state('Walls')[0]


@pytest.mark.parametrize('column', [1, 2])
def test_click_selected_checkbox_applies_to_whole_selection(panel, column):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem
    scene, root, child, layer = populate(panel)
    panel.show()
    QApplication.processEvents()
    tree = panel.tree
    walls = tree.topLevelItem(1).child(0).child(0)
    furniture = tree.topLevelItem(2)
    tree.setCurrentItem(walls)
    furniture.setSelected(True)
    index = tree.indexFromItem(walls, column)
    option = QStyleOptionViewItem()
    option.initFrom(tree)
    option.rect = tree.visualRect(index)
    option.features |= QStyleOptionViewItem.HasCheckIndicator
    option.checkState = walls.checkState(column)
    rect = tree.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, tree)
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, 'Walls')
    scene.selection.add(edge)
    version = scene.version
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    for target in (layer, scene.layer('Furniture')):
        assert target.visible == (column == 2)
        assert target.locked == (column == 2)
    assert not scene.selection
    assert scene.version == version + 1
    assert len(tree.selectedItems()) == 2
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    for target in (layer, scene.layer('Furniture')):
        assert target.visible and not target.locked
    assert len(tree.selectedItems()) == 2


def test_selected_folder_and_layer_lock_together_preserving_visibility(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    building = tree.topLevelItem(1)
    furniture = tree.topLevelItem(2)
    scene.layer('Furniture').visible = False
    panel.refresh()
    building = tree.topLevelItem(1)
    furniture = tree.topLevelItem(2)
    tree.setCurrentItem(building)
    furniture.setSelected(True)
    building.setCheckState(2, Qt.Checked)
    assert root.locked and scene.layer('Furniture').locked
    assert not child.locked and not layer.locked
    assert scene.layer_state('Walls') == (True, True)
    assert root.visible and not scene.layer('Furniture').visible
    assert furniture.checkState(2) == Qt.Checked
    # Unselected rows still change individually.
    walls = building.child(0).child(0)
    walls.setCheckState(2, Qt.Checked)
    walls.setCheckState(2, Qt.Unchecked)
    assert root.locked and scene.layer('Furniture').locked
    furniture.setCheckState(2, Qt.Unchecked)
    assert not root.locked and not scene.layer('Furniture').locked
    assert scene.layer_state('Walls') == (True, False)
    assert root.visible and not scene.layer('Furniture').visible


def test_folders_before_layers_sorted_by_name_at_every_level(panel):
    scene = panel._scene()
    z = LayerFolder('Z folder', position=0)
    a = LayerFolder('A folder', position=99)
    ten = LayerFolder('10 folder', parent_id=a.uid, position=0)
    two = LayerFolder('2 folder', parent_id=a.uid, position=99)
    scene.layer_folders = [z, ten, a, two]
    scene.layers += [Layer('Z layer', position=0), Layer('A layer', position=99),
                     Layer('z nested', folder_id=a.uid, position=0),
                     Layer('a nested', folder_id=a.uid, position=99)]
    panel.refresh()
    tree = panel.tree
    assert [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())] == [
        DEFAULT_LAYER, 'A folder', 'Z folder', 'A layer', 'Z layer']
    parent = tree.topLevelItem(1)
    assert [parent.child(i).text(0) for i in range(parent.childCount())] == [
        '2 folder', '10 folder', 'a nested', 'z nested']
    # Renaming re-sorts while preserving current and selected rows.
    tree.setCurrentItem(tree.topLevelItem(4))
    tree.topLevelItem(3).setSelected(True)
    tree.currentItem().setText(0, '0 layer')
    assert [tree.topLevelItem(i).text(0) for i in range(3, 5)] == ['0 layer', 'A layer']
    assert tree.currentItem().text(0) == '0 layer'
    assert {i.text(0) for i in tree.selectedItems()} == {'0 layer', 'A layer'}
