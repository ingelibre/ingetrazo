"""Creating a folder groups selected rows without breaking nested contents."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from core.camera import OrbitCamera
from core.layers import DEFAULT_LAYER, Layer, LayerFolder
from core.saved_views import SavedView, SceneFolder
from core.scene import Scene
from formats.igz import load_into, save_scene
from views.tray import LayersPanel, ScenesPanel


@pytest.fixture(params=['layers', 'scenes'])
def setup(request):
    scene = Scene()
    viewport = SimpleNamespace(scene=scene, camera=OrbitCamera(), update=lambda: None)
    is_layers = request.param == 'layers'
    panel = (LayersPanel if is_layers else ScenesPanel)(SimpleNamespace(viewport=viewport))
    tree = panel.tree if is_layers else panel.list
    folders = scene.layer_folders if is_layers else scene.scene_folders
    rows = scene.layers if is_layers else scene.saved_views
    Folder = LayerFolder if is_layers else SceneFolder
    Row = Layer if is_layers else SavedView
    yield scene, panel, tree, folders, rows, Folder, Row
    panel.close()


def item_named(tree, name):
    def find(parent):
        for index in range(parent.childCount()):
            item = parent.child(index)
            if item.text(0) == name:
                return item
            match = find(item)
            if match is not None:
                return match
    return find(tree.invisibleRootItem())


def test_group_selected_siblings_in_display_order_and_save(setup, tmp_path):
    scene, panel, tree, folders, rows, Folder, Row = setup
    parent = Folder('Parent')
    folders.append(parent)
    a, b, keep = [Row(name, folder_id=parent.uid, position=i)
                  for i, name in enumerate(['A', 'B', 'Keep'])]
    rows.extend([a, b, keep])
    panel.refresh()
    tree.setCurrentItem(item_named(tree, 'B'))
    item_named(tree, 'A').setSelected(True)
    panel._on_add_folder()
    new = folders[-1]
    assert new.parent_id == parent.uid
    assert a.folder_id == b.folder_id == new.uid
    assert keep.folder_id == parent.uid
    assert (a.position, b.position) == (0, 1)
    assert new.position == 0
    assert len(tree.selectedItems()) == 1
    assert tree.currentItem().data(0, Qt.UserRole) is new
    assert [tree.currentItem().child(i).text(0) for i in range(2)] == ['A', 'B']
    path = tmp_path / 'grouped.igz'
    save_scene(scene, path)
    loaded = Scene()
    load_into(loaded, path)
    loaded_rows = loaded.layers if isinstance(panel, LayersPanel) else loaded.saved_views
    assert all(row.folder_id == new.uid for row in loaded_rows if row.name in ['A', 'B'])


def test_group_folder_and_selected_descendant_without_cycles(setup):
    scene, panel, tree, folders, rows, Folder, Row = setup
    root, child = Folder('Root'), Folder('Child')
    child.parent_id = root.uid
    folders.extend([root, child])
    a, b = Row('A', folder_id=child.uid), Row('B', position=1)
    rows.extend([a, b])
    panel.refresh()
    tree.setCurrentItem(item_named(tree, 'Root'))
    for name in ['Child', 'A', 'B']:
        item_named(tree, name).setSelected(True)
    panel._on_add_folder()
    new = folders[-1]
    assert new.parent_id is None
    assert root.parent_id == new.uid
    assert child.parent_id == root.uid
    assert a.folder_id == child.uid
    assert b.folder_id == new.uid


def test_group_rows_from_different_folders_at_common_parent(setup):
    scene, panel, tree, folders, rows, Folder, Row = setup
    root = Folder('Root')
    left, right = Folder('Left', parent_id=root.uid), Folder('Right', parent_id=root.uid)
    folders.extend([root, left, right])
    a, b = Row('A', folder_id=left.uid), Row('B', folder_id=right.uid)
    rows.extend([a, b])
    panel.refresh()
    tree.setCurrentItem(item_named(tree, 'A'))
    item_named(tree, 'B').setSelected(True)
    panel._on_add_folder()
    new = folders[-1]
    assert new.parent_id == root.uid
    assert a.folder_id == b.folder_id == new.uid
    assert left.parent_id == right.parent_id == root.uid


def test_empty_selection_creates_empty_root_folder(setup):
    scene, panel, tree, folders, rows, Folder, Row = setup
    root = Folder('Root')
    folders.append(root)
    panel.refresh()
    tree.setCurrentItem(item_named(tree, 'Root'))
    tree.clearSelection()
    panel._on_add_folder()
    assert folders[-1].parent_id is None
    assert root.parent_id is None
    assert tree.currentItem().childCount() == 0


def test_default_layer_stays_at_root_when_grouping():
    scene = Scene()
    scene.layers.append(Layer('A'))
    panel = LayersPanel(SimpleNamespace(viewport=SimpleNamespace(scene=scene, update=lambda: None)))
    try:
        panel.tree.setCurrentItem(item_named(panel.tree, DEFAULT_LAYER))
        item_named(panel.tree, 'A').setSelected(True)
        panel._on_add_folder()
        assert scene.layer(DEFAULT_LAYER).folder_id is None
        assert scene.layer('A').folder_id == scene.layer_folders[-1].uid
        assert item_named(panel.tree, DEFAULT_LAYER).parent() is None
    finally:
        panel.close()
