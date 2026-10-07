"""Nested scene organization must survive moves, recapture and file saves."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from core.camera import OrbitCamera
from core.saved_views import SavedView, SceneFolder
from core.scene import Scene
from views.tray import ScenesPanel


@pytest.fixture
def panel():
    scene = Scene()
    viewport = SimpleNamespace(scene=scene, camera=OrbitCamera(), update=lambda: None)
    widget = ScenesPanel(SimpleNamespace(viewport=viewport))
    yield widget
    widget.close()


def test_nested_folders_and_order_round_trip(tmp_path):
    from formats.igz import save_scene, load_into
    scene = Scene()
    root = SceneFolder("Plans", position=2, expanded=False)
    child = SceneFolder("Ground", parent_id=root.uid, position=1)
    scene.scene_folders = [root, child]
    scene.saved_views = [SavedView("Plan", folder_id=child.uid, position=3),
                         SavedView("Overview", position=0)]
    path = tmp_path / "folders.igz"
    save_scene(scene, path)
    loaded = Scene()
    load_into(loaded, path)
    assert [f.to_dict() for f in loaded.scene_folders] == [f.to_dict() for f in scene.scene_folders]
    assert loaded.saved_views[0].folder_id == child.uid
    assert loaded.saved_views[0].position == 3
    loaded.saved_views[0].recapture(loaded, OrbitCamera())
    assert loaded.saved_views[0].folder_id == child.uid
    assert loaded.saved_views[0].position == 3
    loaded.clear()
    assert not loaded.scene_folders and not loaded.saved_views


def populate(panel):
    scene = panel._scene()
    root = SceneFolder("Plans", position=0)
    child = SceneFolder("Ground", parent_id=root.uid, position=0)
    scene.scene_folders = [root, child]
    scene.saved_views = [SavedView("Plan", folder_id=child.uid), SavedView("Overview", position=1)]
    panel.refresh()
    return scene, root, child


def test_move_into_subfolder_reorder_and_back_to_root(panel):
    scene, root, child = populate(panel)
    tree = panel.list
    folder_item = tree.topLevelItem(0).child(0)
    overview = tree.takeTopLevelItem(1)
    folder_item.insertChild(0, overview)
    panel._on_tree_moved()
    assert [v.name for v in scene.saved_views] == ["Overview", "Plan"]
    assert all(v.folder_id == child.uid for v in scene.saved_views)
    panel.refresh()
    folder_item = tree.topLevelItem(0).child(0)
    assert [folder_item.child(i).text(0) for i in range(2)] == ["Overview", "Plan"]
    tree.setCurrentItem(folder_item.child(0))
    panel._on_move_to_root()
    assert scene.saved_views[-1].name == "Overview"
    assert scene.saved_views[-1].folder_id is None


def test_delete_folder_preserves_contents(panel):
    scene, root, child = populate(panel)
    panel.list.setCurrentItem(panel.list.topLevelItem(0))
    panel._on_delete()
    assert scene.scene_folders == [child]
    assert child.parent_id is None
    assert len(scene.saved_views) == 2
    assert scene.saved_views[0].folder_id == child.uid


def test_create_scene_in_selected_folder_and_folder_collapse_height(panel):
    scene, root, child = populate(panel)
    item = panel.list.topLevelItem(0).child(0)
    panel.list.setCurrentItem(item)
    panel._on_add()
    assert scene.saved_views[-1].folder_id == child.uid
    assert scene.saved_views[-1].position == 1
    root_item = panel.list.topLevelItem(0)
    height = panel.list.height()
    root_item.setExpanded(False)
    assert panel.list.height() < height
    assert not root.expanded
    panel.refresh()
    assert not panel.list.topLevelItem(0).isExpanded()


def test_only_folders_accept_children_and_bad_parents_fall_back_to_root(panel):
    scene, root, child = populate(panel)
    tree = panel.list
    assert tree.topLevelItem(0).flags() & Qt.ItemIsDropEnabled
    assert not tree.topLevelItem(1).flags() & Qt.ItemIsDropEnabled
    assert not tree.topLevelItem(0).icon(0).isNull()
    root.parent_id = child.uid
    panel.refresh()
    assert tree.topLevelItemCount() == 3
    assert tree.topLevelItem(0).parent() is None


def test_legacy_scene_list_preserves_order(panel):
    panel._scene().saved_views = [SavedView.from_dict({"name": n}) for n in ("B", "A", "C")]
    panel.refresh()
    assert [panel.list.topLevelItem(i).text(0) for i in range(3)] == ["B", "A", "C"]


def test_new_subfolder_rename_and_update_keep_selection(panel):
    scene, root, child = populate(panel)
    panel.list.setCurrentItem(panel.list.topLevelItem(0).child(0))
    panel._on_add_folder()
    created = scene.scene_folders[-1]
    assert created.parent_id == root.uid
    assert child.parent_id == created.uid
    item = panel.list.currentItem()
    item.setText(0, "Details")
    assert created.name == "Details"
    assert panel.list.currentItem().data(0, Qt.UserRole) is created
    panel._on_update()  # Folders never capture camera state.
    assert not hasattr(created, "target")


def test_move_folder_carries_scenes_and_delete_multiple_containers(panel):
    scene, root, child = populate(panel)
    other = SceneFolder("Elevations", position=2)
    scene.scene_folders.append(other)
    panel.refresh()
    tree = panel.list
    root_item = tree.takeTopLevelItem(0)
    other_item = tree.topLevelItem(1)
    other_item.addChild(root_item)
    panel._on_tree_moved()
    assert root.parent_id == other.uid
    assert child.parent_id == root.uid
    assert scene.saved_views[1].folder_id == child.uid
    root_item.setSelected(True)
    other_item.setSelected(True)
    panel._on_delete()
    assert scene.scene_folders == [child]
    assert child.parent_id is None
    assert len(scene.saved_views) == 2
