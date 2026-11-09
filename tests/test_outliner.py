# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Outliner (#219): the model's groups and components as a tree.

Every model here is generated: boxes, nested containers, component copies
and a seeded random tree of ten thousand nodes for the timing."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core import outliner
from core.group import Group, copy_group
from core.mesh import Mesh
from views.outliner import COL_EYE, COL_LAYER, COL_LOCK, COL_TYPE

_app = QApplication.instance() or QApplication([])

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]


def _box(at=(0.0, 0.0, 0.0), size=0.1) -> Mesh:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx * size, y0 + dy * size, z0 + dz * size)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    return mesh


def _group(name, at=(0.0, 0.0, 0.0)) -> Group:
    return Group(_box(at), name=name)


def _container(name, kids) -> Group:
    """A group of groups — what Make Group over groups builds."""
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    return g


def _building():
    """Building ▸ Level 1 ▸ (Wall, Slab) and Level 2 ▸ (Wall), plus a
    loose Tree beside it."""
    wall1, slab = _group("Wall", (0, 0, 0)), _group("Slab", (1, 0, 0))
    wall1.ifc = {"class": "IfcWall"}
    level1 = _container("Level 1", [wall1, slab])
    level2 = _container("Level 2", [_group("Wall", (0, 0, 3))])
    building = _container("Building", [level1, level2])
    tree = _group("Tree", (5, 0, 0))
    return building, tree


def _window_with(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = groups        # without the template's scale figure
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version


def _views(win):
    """The «Views and sheets» panel — in the sheet composer."""
    return win._ensure_composer().views_panel


def _row(panel, group):
    return panel._items[id(group)]


def _eye(panel, group):
    """Click the row's eye."""
    panel._on_item_clicked(_row(panel, group), COL_EYE)


def _shown(panel, group) -> bool:
    return not _row(panel, group).data(COL_EYE, Qt.UserRole)


def _random_tree(n: int, seed: int = 7) -> list:
    """``n`` groups hung at random under the ones made before them."""
    rnd = random.Random(seed)
    roots: list = []
    made: list = []
    for i in range(n):
        g = Group(Mesh(), name=f"Node {i}")
        g.component = False
        if made and rnd.random() < 0.8:
            parent = rnd.choice(made)
            parent.adopt(list(parent.children) + [g])
            parent.component = False
        else:
            roots.append(g)
        made.append(g)
    return roots


# ---- core/outliner.py ------------------------------------------------------

def test_walk_lists_every_group_at_every_depth():
    building, tree = _building()
    rows = [(g.name, p.name if p else None, d)
            for g, p, d in outliner.walk([building, tree])]
    assert rows == [("Building", None, 0), ("Level 1", "Building", 1),
                    ("Wall", "Level 1", 2), ("Slab", "Level 1", 2),
                    ("Level 2", "Building", 1), ("Wall", "Level 2", 2),
                    ("Tree", None, 0)]


def test_path_to_names_the_containers_to_open():
    building, tree = _building()
    level1 = building.children[0]
    wall = level1.children[0]
    groups = [building, tree]
    assert outliner.path_to(groups, wall) == [building, level1]
    assert outliner.path_to(groups, tree) == []
    assert outliner.path_to(groups, Group(name="elsewhere")) is None


def test_a_random_tree_keeps_every_path_consistent():
    roots = _random_tree(2000)
    nodes = list(outliner.walk(roots))
    assert len(nodes) == 2000
    up = outliner.parents(roots)
    for g, parent, depth in nodes:
        path = outliner.path_to(roots, g)
        assert len(path) == depth
        assert (path[-1] if path else None) is parent is up[id(g)]


def test_the_shape_ignores_names_and_visibility_not_structure():
    building, tree = _building()
    groups = [building, tree]
    shape = outliner.structure(groups)
    building.name = "Tower"
    tree.hidden = True
    assert outliner.structure(groups) == shape
    level2 = building.children[1]
    level2.adopt(list(level2.children) + [_group("Roof")])
    assert outliner.structure(groups) != shape


def test_kind_class_and_copies():
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    copies = [proto] + [copy_group(proto, QVector3D(i, 0, 0))
                        for i in (1, 2)]
    building, _tree = _building()
    wall = building.children[0].children[0]
    assert outliner.kind(proto) == "component"
    assert outliner.kind(building) == "group"
    assert outliner.ifc_class(wall) == "IfcWall"
    assert outliner.ifc_class(building) == ""
    assert outliner.instance_counts(copies + [building]) == {
        id(proto.mesh): 3}


# ---- The tray panel --------------------------------------------------------

def test_the_tree_shows_the_whole_model_nested():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    t = panel.tree
    assert t.topLevelItemCount() == 2            # the document, the planes
    assert t.topLevelItem(1).isHidden()          # no planes: no folder
    doc = t.topLevelItem(0)
    assert doc.text(0) == "Untitled" and doc.isExpanded()
    assert doc.childCount() == 2
    top = doc.child(0)
    assert top.text(0) == "Building" and top.text(COL_TYPE) == "Group"
    assert top.text(COL_LAYER) == outliner.layer_name(building)
    assert [top.child(i).text(0) for i in range(top.childCount())] == [
        "Level 1", "Level 2"]
    wall = top.child(0).child(0)
    assert wall.text(0) == "Wall" and wall.text(COL_TYPE) == "IfcWall"
    assert wall.data(COL_TYPE, Qt.UserRole) == "ifc"
    assert top.data(COL_TYPE, Qt.UserRole) == "group"
    assert not top.icon(0).isNull() and not top.icon(COL_EYE).isNull()
    assert _shown(panel, building)
    _close(win)


def test_component_copies_are_counted():
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    other = copy_group(proto, QVector3D(1, 0, 0))
    win, scene, panel = _window_with(proto, other)
    assert _row(panel, proto).text(COL_TYPE) == "Component (2 copies)"
    assert _row(panel, proto).data(COL_TYPE, Qt.UserRole) == "component"
    _close(win)


def test_clicking_a_nested_row_opens_its_containers_and_selects_it():
    building, tree = _building()
    level1 = building.children[0]
    wall = level1.children[0]
    win, scene, panel = _window_with(building, tree)
    t = panel.tree
    t.setCurrentItem(_row(panel, wall))
    assert outliner.open_path(scene) == [building, level1]
    assert scene.selection == {wall}
    panel.refresh()
    assert _row(panel, building).font(0).bold()
    assert _row(panel, level1).font(0).bold()
    assert not _row(panel, wall).font(0).bold()
    # A top-level row closes what was open.
    t.setCurrentItem(_row(panel, tree))
    assert scene.edit_group is None
    assert scene.selection == {tree}
    panel.refresh()
    assert not _row(panel, building).font(0).bold()
    _close(win)


def test_moving_to_a_sibling_branch_steps_out_only_where_it_differs():
    building, tree = _building()
    level1, level2 = building.children
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, level1.children[1]))
    assert outliner.open_path(scene) == [building, level1]
    panel.tree.setCurrentItem(_row(panel, level2.children[0]))
    assert outliner.open_path(scene) == [building, level2]
    assert scene.selection == {level2.children[0]}
    _close(win)


def test_a_selection_in_the_view_is_found_in_the_tree():
    building, tree = _building()
    level2 = building.children[1]
    win, scene, panel = _window_with(building, tree)
    assert not _row(panel, building).isExpanded()
    scene.begin_group_edit(building)
    scene.begin_group_edit(level2)
    scene.selection.add(level2.children[0])
    scene.version += 1
    panel.refresh()
    row = _row(panel, level2.children[0])
    assert row.isSelected()
    assert _row(panel, building).isExpanded()
    assert _row(panel, level2).isExpanded()
    assert panel.tree.currentItem() is row
    _close(win)


def test_rename_in_the_tree_is_one_undo_step_and_keeps_the_uid():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    uid = tree.uid
    _row(panel, tree).setText(0, "Oak")
    assert tree.name == "Oak" and tree.uid == uid
    win.viewport.history.undo()
    panel.refresh()
    assert tree.name == "Tree"
    assert _row(panel, tree).text(0) == "Tree"
    _close(win)


def test_the_eye_hides_every_selected_row_at_once():
    building, tree = _building()
    level1 = building.children[0]
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, wall))
    _row(panel, slab).setSelected(True)
    _eye(panel, slab)
    assert wall.hidden and slab.hidden
    assert not _shown(panel, wall) and not _shown(panel, slab)
    win.viewport.history.undo()
    assert not wall.hidden and not slab.hidden
    _close(win)


def test_double_click_opens_and_esc_steps_out_one_level():
    building, tree = _building()
    level1 = building.children[0]
    win, scene, panel = _window_with(building, tree)
    panel.open_item(_row(panel, level1))
    assert outliner.open_path(scene) == [building, level1]
    panel.step_out()
    assert outliner.open_path(scene) == [building]
    panel.step_out()
    assert scene.edit_group is None
    _close(win)


def test_the_keyboard_alone_hides_opens_and_steps_out():
    from PySide6.QtTest import QTest
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    t = panel.tree
    t.setCurrentItem(_row(panel, tree))
    QTest.keyClick(t, Qt.Key_Space)
    assert tree.hidden
    QTest.keyClick(t, Qt.Key_Space)
    assert not tree.hidden
    t.setCurrentItem(_row(panel, building))
    QTest.keyClick(t, Qt.Key_Return)
    assert scene.edit_group is building
    QTest.keyClick(t, Qt.Key_Escape)
    assert scene.edit_group is None
    _close(win)


def test_the_tree_keys_win_over_the_window_shortcuts():
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    for key in (Qt.Key_Space, Qt.Key_Escape, Qt.Key_F2, Qt.Key_Return):
        ev = QKeyEvent(QEvent.ShortcutOverride, key, Qt.NoModifier)
        assert panel.tree.event(ev) and ev.isAccepted()
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
    panel.tree.event(ev)
    assert not ev.isAccepted()          # Ctrl+Z stays the window's undo
    _close(win)


def test_a_hidden_container_cannot_be_entered_from_the_tree():
    building, tree = _building()
    level1 = building.children[0]
    building.hidden = True
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, level1))
    assert scene.edit_group is None
    assert not scene.selection
    _close(win)


def test_rows_update_in_place_and_rebuild_only_when_groups_change():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    row = _row(panel, tree)
    _row(panel, building).setExpanded(True)
    tree.name = "Pine"
    tree.hidden = True
    panel.refresh()
    assert _row(panel, tree) is row
    assert row.text(0) == "Pine" and not _shown(panel, tree)
    extra = _group("Fence", (9, 0, 0))
    scene.groups.append(extra)
    panel.refresh()
    assert _row(panel, tree) is not row             # rebuilt…
    assert _row(panel, building).isExpanded()       # …keeping what was open
    assert _row(panel, extra).text(0) == "Fence"
    scene.groups.remove(extra)
    panel.refresh()
    assert id(extra) not in panel._items
    _close(win)


def test_a_folded_section_waits_until_it_shows():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    assert not panel.isVisible()
    scene.groups.append(_group("Late"))
    win.project_browser.on_scene_changed()
    assert panel._stale
    assert panel.tree.topLevelItem(0).childCount() == 2
    panel.refresh()
    assert panel.tree.topLevelItem(0).childCount() == 3
    _close(win)


def test_a_scene_remembers_what_the_outliner_hid():
    from core.saved_views import SavedView
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _eye(panel, tree)
    view = SavedView.capture("Without trees", scene, win.viewport.camera)
    _eye(panel, tree)
    assert not tree.hidden
    view.apply(scene, win.viewport.camera)
    panel.refresh()
    assert tree.hidden and not _shown(panel, tree)
    _close(win)


def test_an_empty_model_says_so():
    win, scene, panel = _window_with()
    assert panel._empty.isVisibleTo(panel)
    assert panel.tree.topLevelItem(0).childCount() == 0
    _close(win)


def test_ten_thousand_nodes_build_once_and_refresh_quickly():
    roots = _random_tree(10_000)
    win, scene, panel = _window_with()
    scene.groups.extend(roots)
    t0 = time.perf_counter()
    panel.refresh()
    build = time.perf_counter() - t0
    assert len(panel._items) == 10_000
    t0 = time.perf_counter()
    panel.refresh()
    again = time.perf_counter() - t0
    print(f"\n10 000 nodes: build {build * 1000:.0f} ms, "
          f"refresh {again * 1000:.0f} ms")
    assert build < 5.0
    assert again < 1.0
    _close(win)


def test_the_filter_keeps_the_path_to_every_match():
    building, tree = _building()
    level1, level2 = building.children
    win, scene, panel = _window_with(building, tree)
    panel.search.setText("slab")
    assert not _row(panel, level1.children[1]).isHidden()     # the match
    assert not _row(panel, level1).isHidden()                 # its path
    assert _row(panel, level1).isExpanded()
    assert _row(panel, level1.children[0]).isHidden()
    assert _row(panel, level2).isHidden()
    assert _row(panel, tree).isHidden()
    panel.search.setText("ifcwall")                           # by class
    assert not _row(panel, level1.children[0]).isHidden()
    assert _row(panel, level1.children[1]).isHidden()
    panel.search.setText("")
    assert not any(item.isHidden() for item in panel._items.values())
    _close(win)


def test_the_filter_follows_a_rename():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    panel.search.setText("oak")
    assert _row(panel, tree).isHidden()
    tree.name = "Oak"
    panel.refresh()
    assert not _row(panel, tree).isHidden()
    _close(win)


def test_filter_keep_in_the_core():
    building, tree = _building()
    keep, hit = outliner.filter_keep([building, tree], "wall")
    walls = {id(w) for lvl in building.children for w in lvl.children
             if w.name == "Wall"}
    assert hit == walls
    assert keep == walls | {id(building)} | {id(lvl)
                                             for lvl in building.children}


def test_the_browser_is_the_model_tree_and_the_sheets_live_in_the_composer():
    win, scene, panel = _window_with()
    dock = win.project_browser
    assert dock in win._sidebar_docks()
    assert dock.objectName() == "tray_project_browser"
    assert dock.widget() is dock.outliner
    comp_win = win._ensure_composer()
    assert comp_win._splitter.widget(0) is comp_win._left_panel
    # On the right with the others, second; the left side empty, folded.
    right = comp_win._tabs
    assert right.indexOf(comp_win.views_panel) == 1
    assert right.tabText(1) == "Views and sheets"
    assert comp_win._left_tabs.count() == 0
    assert comp_win._left_panel.isHidden()
    assert not comp_win._act_views.isChecked()
    assert comp_win.views_panel._composer_win is comp_win
    _close(win)


# ---- Sheets 2D -------------------------------------------------------------

def _sheets_model(win):
    from core.composition import Composicion, MarcoVista
    from core.saved_views import SavedView
    scene = win.viewport.scene
    cam = win.viewport.camera
    scene.saved_views[:] = [SavedView.capture("Plan L1", scene, cam),
                            SavedView.capture("North elevation", scene, cam)]
    a101 = Composicion(name="A101 Plans", paper="A3")
    a101.frames = [MarcoVista(view_key="scene:Plan L1", scale_n=100.0),
                   MarcoVista(view_key="scene:Section A", scale_n=50.0)]
    a102 = Composicion(name="A102 Elevations")
    a102.frames = [MarcoVista(view_key="scene:Plan L1", scale_n=200.0),
                   MarcoVista(view_key="std:front", scale_n=100.0)]
    scene.compositions[:] = [a101, a102]
    return a101, a102


def test_scene_usage_and_orphans_in_the_core():
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    assert outliner.scene_usage(scene) == {
        "Plan L1": ["A101 Plans", "A102 Elevations"],
        "Section A": ["A101 Plans"]}
    assert outliner.is_orphan(scene, a101.frames[1])
    assert not outliner.is_orphan(scene, a101.frames[0])
    assert not outliner.is_orphan(scene, a102.frames[1])     # a std view
    _close(win)


def test_the_sheets_tab_lists_scenes_sheets_and_their_views():
    win, scene, panel = _window_with()
    _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    scenes_root, sheets_root = sheets.scenes_root, sheets.sheets_root
    assert [scenes_root.child(i).text(0)
            for i in range(scenes_root.childCount())] == [
        "Plan L1", "North elevation"]
    assert scenes_root.child(0).text(1) == "On A101 Plans, A102 Elevations"
    assert scenes_root.child(1).text(1) == "Not on a sheet"
    a101 = sheets_root.child(0)
    assert a101.text(0) == "A101 Plans" and a101.text(1).startswith("A3")
    assert a101.child(0).text(0) == "Plan L1 · 1:100"
    orphan = a101.child(1)
    assert orphan.text(1) == "Scene missing"
    assert "Section A" in orphan.toolTip(0)
    assert sheets_root.child(1).child(1).text(1) == "Standard view"
    _close(win)


def test_deleting_a_scene_flags_its_frames_instead_of_breaking():
    win, scene, panel = _window_with()
    a101, _a102 = _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    assert sheets.sheets_root.child(0).child(0).text(1) == "Scene"
    del scene.saved_views[0]                      # «Plan L1» goes
    sheets.refresh()
    assert sheets.sheets_root.child(0).child(0).text(1) == "Scene missing"
    assert a101.frames[0].view_key == "scene:Plan L1"   # untouched
    _close(win)


def test_double_click_shows_a_scene_and_opens_a_sheet():
    win, scene, panel = _window_with()
    _sheets_model(win)
    tree = _group("Tree")
    scene.groups.append(tree)
    tree.hidden = True
    scene.saved_views[0].hidden_objects = []      # «Plan L1» shows it all
    win.tray.scenes.refresh()
    sheets = _views(win)
    sheets.refresh()
    sheets._show_scene(scene.saved_views[0])         # right-click ▸ Show
    assert not tree.hidden
    opened = []
    win._show_sheet = opened.append
    sheets.activate(sheets.sheets_root.child(1))
    sheets.activate(sheets.sheets_root.child(0).child(1))
    assert opened == [1, 0]
    _close(win)


# ---- Isolate, footer --------------------------------------------------------

def test_isolate_in_the_core_hides_the_siblings_on_the_way_down():
    building, tree = _building()
    level1, level2 = building.children
    wall, slab = level1.children
    hide = outliner.isolate_hides([building, tree], [wall])
    assert {g.name for g in hide} == {"Slab", "Level 2", "Tree"}
    assert outliner.isolate_hides([building, tree], [building]) == [tree]


def test_isolate_and_show_all_are_one_undo_step_each():
    building, tree = _building()
    level1, level2 = building.children
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, wall))
    panel.isolate()
    assert slab.hidden and level2.hidden and tree.hidden
    assert not wall.hidden and not level1.hidden and not building.hidden
    win.viewport.history.undo()
    assert not (slab.hidden or level2.hidden or tree.hidden)
    panel.isolate()
    panel.show_all()
    assert not any(g.hidden for g, _p, _d in outliner.walk(scene.groups))
    win.viewport.history.undo()
    assert tree.hidden
    _close(win)


def test_the_footer_counts_and_follows_the_filter():
    building, tree = _building()
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    tree.hidden = True
    win, scene, panel = _window_with(building, tree, proto)
    assert panel.summary.text() == "7 groups · 1 components · 1 hidden"
    panel.search.setText("wall")
    assert panel.summary.text() == "2 of 8 match"
    _close(win)


# ---- Rename, links, live refresh (2D) ----------------------------------------

def test_renaming_a_scene_carries_its_sheet_views_along():
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    view = scene.saved_views[0]
    assert outliner.rename_scene(scene, view, "Ground floor")
    assert a101.frames[0].view_key == "scene:Ground floor"
    assert a102.frames[0].view_key == "scene:Ground floor"
    assert not outliner.is_orphan(scene, a101.frames[0])
    # A name another scene has is refused, and nothing moves.
    assert not outliner.rename_scene(scene, view, "North elevation")
    assert view.name == "Ground floor"
    _close(win)


def test_f2_renames_a_scene_and_a_sheet_in_the_browser():
    win, scene, panel = _window_with()
    a101, _a102 = _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    sheets.scenes_root.child(0).setText(0, "Ground floor")
    assert scene.saved_views[0].name == "Ground floor"
    assert a101.frames[0].view_key == "scene:Ground floor"
    assert win.tray.scenes.list.item(0).text() == "Ground floor"
    sheets.sheets_root.child(0).setText(0, "A-101")
    assert a101.name == "A-101"
    _app.processEvents()
    assert sheets.sheets_root.child(0).text(0) == "A-101"
    assert sheets.sheets_root.child(0).child(0).text(1) == "Scene"
    _close(win)


def test_the_scenes_panel_rename_no_longer_orphans_sheet_views():
    win, scene, panel = _window_with()
    a101, _a102 = _sheets_model(win)
    scenes = win.tray.scenes
    scenes.refresh()
    scenes.list.item(0).setText("Ground floor")
    assert a101.frames[0].view_key == "scene:Ground floor"
    _close(win)


def test_a_scene_marks_its_views_and_a_view_marks_its_scene():
    win, scene, panel = _window_with()
    _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    plan = sheets.scenes_root.child(0)                     # «Plan L1»
    sheets.tree.setCurrentItem(plan)
    marked = sheets.related()
    assert sorted(it.text(0) for it in marked) == ["Plan L1 · 1:100",
                                                   "Plan L1 · 1:200"]
    assert all(it.data(0, Qt.UserRole + 1) for it in marked)
    view = sheets.sheets_root.child(1).child(0)            # on A102
    sheets.tree.setCurrentItem(view)
    assert sheets.related() == [plan]
    assert not marked[0].data(0, Qt.UserRole + 1)          # cleared
    sheets.tree.setCurrentItem(sheets.sheets_root.child(0).child(1))
    assert sheets.related() == []                          # orphan: none
    _close(win)


def test_a_sheet_added_in_the_composer_reaches_the_browser():
    from core.composition import Composicion
    win, scene, panel = _window_with()
    _sheets_model(win)
    sheets = _views(win)
    win._ensure_composer().show()
    win._composer._show_page("views")  # its tab in front
    _app.processEvents()
    sheets.refresh()
    scene.compositions.append(Composicion(name="A103 Details"))
    win._refresh_sheet_tabs()          # what the composer calls on add
    assert sheets.sheets_root.childCount() == 3
    scene.compositions[2].name = "A103 Joints"
    sheets._poll.timeout.emit()        # the composer's in-place edits
    assert sheets.sheets_root.child(2).text(0) == "A103 Joints"
    win._composer.hide()
    _close(win)


# ---- Re-nesting (drag and drop, Tab / Shift+Tab) ----------------------------

def _world_points(groups, group) -> list:
    """Every vertex of ``group``'s own mesh, in world coordinates, rounded."""
    m = outliner.world_matrix(groups, group)
    out = []
    for v in group.mesh.vertices:
        p = m.map(v.position) if m is not None else v.position
        out.append((round(p.x(), 6), round(p.y(), 6), round(p.z(), 6)))
    return sorted(out)


def _moved_container():
    """A container moved and turned: its frame is not the world's."""
    m = QMatrix4x4()
    m.translate(QVector3D(10, 5, 0))
    m.rotate(30, 0, 0, 1)
    kid = Group(_box((0, 0, 0)), name="Kid")
    kid.xform = QMatrix4x4()
    kid.component = False
    box = _container("Shelf", [kid])
    box.xform = m
    return box


def test_a_classic_group_dropped_into_a_turned_group_stays_put():
    from core.history import ReparentGroupsCommand
    from core.scene import Scene
    scene = Scene()
    shelf = _moved_container()
    loose = _group("Loose", (3, 4, 0))
    scene.groups[:] = [shelf, loose]
    before = _world_points(scene.groups, loose)
    mesh0 = loose.mesh
    cmd = ReparentGroupsCommand([loose], shelf)
    cmd.do(scene)
    assert loose in shelf.children and loose not in scene.groups
    assert _world_points(scene.groups, loose) == before
    cmd.undo(scene)
    assert scene.groups == [shelf, loose] and shelf.children[-1] is not loose
    assert loose.mesh is mesh0 and loose.xform is None


def test_an_instance_taken_out_keeps_its_place_and_children():
    from core.history import ReparentGroupsCommand
    from core.scene import Scene
    scene = Scene()
    shelf = _moved_container()
    kid = shelf.children[0]
    scene.groups[:] = [shelf]
    before = _world_points(scene.groups, kid)
    cmd = ReparentGroupsCommand([kid], None)
    cmd.do(scene)
    assert scene.groups == [shelf, kid] and not shelf.children
    assert _world_points(scene.groups, kid) == before
    cmd.undo(scene)
    assert shelf.children == [kid] and scene.groups == [shelf]
    assert _world_points(scene.groups, kid) == before


def test_a_plain_target_becomes_a_group_of_groups_not_a_component():
    from core.history import ReparentGroupsCommand
    from core.scene import Scene
    scene = Scene()
    a, b = _group("A"), _group("B", (2, 0, 0))
    scene.groups[:] = [a, b]
    cmd = ReparentGroupsCommand([b], a)
    cmd.do(scene)
    assert a.xform is not None and not a.is_component()
    assert outliner.kind(a) == "group"
    cmd.undo(scene)
    assert a.xform is None


def test_moving_a_group_and_its_child_moves_the_group_once():
    building, tree = _building()
    level1 = building.children[0]
    assert outliner.topmost([building, tree],
                            [level1.children[0], level1, tree]) == [
        level1, tree]


def test_what_cannot_be_re_nested():
    building, tree = _building()
    level1 = building.children[0]
    groups = [building, tree]
    assert outliner.reparent_problem(groups, [building], level1) == "cycle"
    assert outliner.reparent_problem(groups, [level1], level1) == "cycle"
    chair = Group(_box(), name="Chair")
    chair.xform = QMatrix4x4()
    part = Group(_box(), name="Seat")
    part.xform = QMatrix4x4()
    part.component = False
    chair.adopt([part])
    chair.component = True
    groups = [building, tree, chair]
    assert outliner.reparent_problem(groups, [tree], chair) == "component"
    assert outliner.reparent_problem(groups, [part], None) == "component"
    tree.locked = True
    assert outliner.reparent_problem(groups, [tree], building) == "locked"
    assert outliner.reparent_problem(groups, [level1], None) is None


def test_dropping_rows_on_a_group_is_one_undo_step():
    building, tree = _building()
    level2 = building.children[1]
    win, scene, panel = _window_with(building, tree)
    assert panel.reparent([tree], level2)
    assert tree in level2.children
    assert _row(panel, tree).parent() is _row(panel, level2)
    assert _row(panel, level2).isExpanded()
    win.viewport.history.undo()
    panel.refresh()
    assert tree in scene.groups
    assert _row(panel, tree).parent() is panel.tree.topLevelItem(0)
    _close(win)


def test_a_refused_drop_changes_nothing():
    building, tree = _building()
    level1 = building.children[0]
    win, scene, panel = _window_with(building, tree)
    steps = len(win.viewport.history.undo_stack)
    assert not panel.reparent([building], level1)
    assert level1 in building.children and building in scene.groups
    assert len(win.viewport.history.undo_stack) == steps
    _close(win)


def test_tab_and_shift_tab_move_in_and_out():
    from PySide6.QtTest import QTest
    building, tree = _building()
    fence = _group("Fence", (8, 0, 0))
    win, scene, panel = _window_with(building, tree, fence)
    t = panel.tree
    t.setCurrentItem(_row(panel, fence))
    QTest.keyClick(t, Qt.Key_Tab)              # into «Tree», the row above
    assert fence in tree.children
    t.setCurrentItem(_row(panel, fence))
    QTest.keyClick(t, Qt.Key_Backtab)          # back out to the model
    assert fence in scene.groups and fence not in tree.children
    _close(win)


# ---- Lock --------------------------------------------------------------------

def test_a_locked_group_cannot_be_picked_nor_what_it_holds():
    from core.scene import Scene
    building, tree = _building()
    scene = Scene()
    scene.groups[:] = [building, tree]
    building.locked = True
    assert not scene.entity_selectable(building)
    proxy = Group(name="placement")
    proxy.owner = building                     # what the viewport picks
    assert not scene.entity_selectable(proxy)
    assert scene.entity_selectable(tree)


def test_the_padlock_locks_and_unlocks_in_one_undo_step():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    panel._on_item_clicked(_row(panel, tree), COL_LOCK)
    assert tree.locked
    assert _row(panel, tree).data(COL_LOCK, Qt.UserRole)
    panel.tree.setCurrentItem(_row(panel, tree))
    assert not scene.selection                 # a locked row selects nothing
    win.viewport.history.undo()
    panel.refresh()
    assert not tree.locked
    assert not _row(panel, tree).data(COL_LOCK, Qt.UserRole)
    _close(win)


def test_nothing_opens_through_a_locked_group():
    building, tree = _building()
    level1 = building.children[0]
    building.locked = True
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, level1.children[0]))
    assert scene.edit_group is None and not scene.selection
    panel.open_item(_row(panel, building))
    assert scene.edit_group is None
    _close(win)


def test_the_lock_is_saved_in_the_igz_and_kept_by_copies(tmp_path):
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    building, tree = _building()
    tree.locked = True
    assert copy_group(tree).locked
    scene = Scene()
    scene.groups[:] = [building, tree]
    path = tmp_path / "locked.igz"
    save_scene(scene, path)
    back = Scene()
    load_into(back, path)
    by_name = {g.name: g for g, _p, _d in outliner.walk(back.groups)}
    assert by_name["Tree"].locked and not by_name["Building"].locked


# ---- Section planes ------------------------------------------------------------

def _two_planes(scene):
    from core.section import SectionPlane
    a = SectionPlane(QVector3D(0, 0, 1.2), QVector3D(0, 0, 1),
                     name="Plan cut", symbol="A", active=True)
    b = SectionPlane(QVector3D(2, 0, 0), QVector3D(1, 0, 0),
                     name="Cross", symbol="B")
    scene.section_planes[:] = [a, b]
    return a, b


def test_section_modes_in_the_core():
    from core.scene import Scene
    scene = Scene()
    a, b = _two_planes(scene)
    assert outliner.section_mode(a) == "both"
    assert outliner.section_mode(b) == "frame"
    b.hidden = True
    assert outliner.section_mode(b) == "off"
    a.hidden = True
    assert outliner.section_mode(a) == "cut"
    assert outliner.section_label(a) == "A — Plan cut"


def test_the_section_folder_lists_every_plane_with_its_mode():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    sec = panel._sec_root
    assert not sec.isHidden() and sec.childCount() == 2
    assert sec.text(COL_TYPE) == "2 planes"
    row_a, row_b = sec.child(0), sec.child(1)
    assert row_a.text(0) == "A — Plan cut"
    assert row_a.text(COL_TYPE) == "Cut and frame"
    assert row_b.text(COL_TYPE) == "Frame only (no cut)"
    assert row_a.data(COL_LOCK, Qt.UserRole) is True     # it cuts
    assert row_b.data(COL_LOCK, Qt.UserRole) is False
    _close(win)


def test_the_section_folder_keeps_its_name_when_the_tree_is_rebuilt():
    from core.group import Group
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _two_planes(scene)
    panel.refresh()
    scene.groups.append(Group(name="New"))          # rows rebuilt
    panel.refresh()
    sec = panel._sec_root
    assert sec.text(0) == "Section planes"
    assert sec.text(COL_TYPE) == "2 planes"
    _close(win)


def test_the_frame_goes_and_the_cut_stays():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    panel._on_item_clicked(panel._sec_root.child(0), COL_EYE)
    assert a.hidden and a.active                     # cut only
    assert scene.active_section() is a
    assert panel._sec_root.child(0).text(COL_TYPE) == "Cut only (no frame)"
    win.viewport.history.undo()
    assert not a.hidden and a.active
    _close(win)


def test_the_cut_goes_and_the_frame_stays_and_one_plane_cuts_at_a_time():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    panel._on_item_clicked(panel._sec_root.child(0), COL_LOCK)
    assert not a.active and not a.hidden             # frame only
    assert scene.active_section() is None
    panel._on_item_clicked(panel._sec_root.child(1), COL_LOCK)
    assert b.active and scene.active_section() is b
    panel.set_section_mode(a, "cut")                 # A takes the cut
    assert a.active and not b.active and a.hidden
    panel.set_section_mode(a, "off")
    assert not a.active and a.hidden
    assert panel._sec_root.child(0).text(COL_TYPE) == "Off"
    win.viewport.history.undo()
    assert a.active and a.hidden
    _close(win)


def test_the_folder_row_drives_the_view_menu_switches():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _two_planes(scene)
    panel.refresh()
    panel._on_item_clicked(panel._sec_root, COL_EYE)
    assert not scene.show_section_planes
    assert not win._act_show_splanes.isChecked()
    panel._on_item_clicked(panel._sec_root, COL_LOCK)
    assert not scene.show_section_cuts
    assert not win._act_show_scuts.isChecked()
    win._act_show_scuts.setChecked(True)              # from the toolbar
    assert panel._stale                               # off screen: later
    panel.refresh()
    assert panel._sec_folder[2] is True               # cuts on again
    _close(win)


def test_keyboard_on_a_plane_row():
    from PySide6.QtTest import QTest
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    t = panel.tree
    t.setCurrentItem(panel._sec_root.child(1))
    assert scene.selection == {b}                     # selected in the view
    QTest.keyClick(t, Qt.Key_Space)                   # frame off
    assert b.hidden
    QTest.keyClick(t, Qt.Key_Return)                  # it cuts
    assert b.active and not a.active
    _close(win)


def test_a_hidden_frame_is_saved_and_not_picked(tmp_path):
    from core.scene import Scene
    from core.section import SectionPlane
    from formats.igz import load_into, save_scene
    scene = Scene()
    a, b = _two_planes(scene)
    a.hidden = True
    path = tmp_path / "sections.igz"
    save_scene(scene, path)
    back = Scene()
    load_into(back, path)
    assert [sp.hidden for sp in back.section_planes] == [True, False]
    assert back.section_planes[0].active
    assert SectionPlane.from_dict(b.to_dict()).hidden is False


def test_the_filter_finds_planes_by_name():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _two_planes(scene)
    panel.refresh()
    panel.search.setText("cross")
    sec = panel._sec_root
    assert not sec.isHidden()
    assert sec.child(0).isHidden() and not sec.child(1).isHidden()
    panel.search.setText("slab")
    assert sec.isHidden()
    _close(win)


def test_the_section_fill_switch_on_the_folder_and_the_cutting_plane():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    style = scene.display_style
    style.section_fill = True
    panel.refresh()
    sec = panel._sec_root
    assert sec.data(COL_LAYER, Qt.UserRole) is True
    assert sec.child(0).data(COL_LAYER, Qt.UserRole) is True   # A cuts
    assert sec.child(1).data(COL_LAYER, Qt.UserRole) is None   # B does not
    panel._on_item_clicked(sec, COL_LAYER)
    assert not style.section_fill
    assert not win._act_section_fill.isChecked()               # menu follows
    assert sec.text(COL_LAYER) == "No fill"
    panel._on_item_clicked(sec.child(0), COL_LAYER)            # on A
    assert style.section_fill
    panel._on_item_clicked(sec.child(1), COL_LAYER)            # B: no cell
    assert style.section_fill
    win._act_section_fill.setChecked(False)                    # the toolbar
    panel.refresh()
    assert sec.data(COL_LAYER, Qt.UserRole) is False
    _close(win)


def test_the_fill_cell_moves_with_the_cut():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    panel.set_section_mode(b, "both")
    sec = panel._sec_root
    assert sec.child(0).data(COL_LAYER, Qt.UserRole) is None
    assert sec.child(1).data(COL_LAYER, Qt.UserRole) is not None
    _close(win)


def test_the_fill_colour_comes_from_the_styles_panel_picker():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _two_planes(scene)
    panel.refresh()
    asked = []
    win.styles_panel._pick_color = lambda title, attr: asked.append(attr)
    panel.pick_section_fill_color()
    assert asked == ["section_fill_color"]
    _close(win)


# ---- A cut's own fill, renaming planes, column widths -----------------------

def test_a_plane_takes_its_own_pattern_colour_and_spacing():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    scene.display_style.section_fill = True
    panel.refresh()
    panel.set_plane_fill(a, pattern="hatch")
    assert a.fill == {"pattern": "hatch"}
    assert panel._sec_root.child(0).text(COL_LAYER) == "Hatched 45°"
    panel.set_plane_fill(a, color=(1.0, 0.0, 0.0))
    assert a.fill == {"pattern": "hatch", "color": (1.0, 0.0, 0.0)}
    win.viewport.history.undo()
    assert a.fill == {"pattern": "hatch"}
    panel.set_plane_fill(a, pattern=None)              # «As the style»
    assert a.fill is None
    assert panel._sec_root.child(0).text(COL_LAYER) == "Solid"
    _close(win)


def test_the_hatch_spacing_is_typed_as_a_length(monkeypatch):
    from views import prompts
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    monkeypatch.setattr(prompts, "get_text",
                        lambda *a_, **k: ("8cm", True))
    panel.ask_plane_hatch_spacing(a)
    assert abs(a.fill["spacing"] - 0.08) < 1e-9
    monkeypatch.setattr(prompts, "get_text",
                        lambda *a_, **k: ("lots", True))
    panel.ask_plane_hatch_spacing(a)                   # refused
    assert abs(a.fill["spacing"] - 0.08) < 1e-9
    _close(win)


def test_a_plane_is_renamed_in_one_undo_step():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    assert panel.set_plane_name(a, "Ground floor plan", "P1")
    assert (a.name, a.symbol) == ("Ground floor plan", "P1")
    assert panel._sec_root.child(0).text(0) == "P1 — Ground floor plan"
    win.viewport.history.undo()
    assert (a.name, a.symbol) == ("Plan cut", "A")
    assert not panel.set_plane_name(a, "  ", "")       # nothing to change
    _close(win)


def test_f2_on_a_plane_row_opens_its_name_dialog(monkeypatch):
    from PySide6.QtTest import QTest
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    a, b = _two_planes(scene)
    panel.refresh()
    asked = []
    monkeypatch.setattr(panel, "rename_plane", asked.append)
    panel.tree.setCurrentItem(panel._sec_root.child(1))
    QTest.keyClick(panel.tree, Qt.Key_F2)
    assert asked == [b]
    _close(win)


def test_the_name_column_width_is_the_users_and_is_remembered():
    from PySide6.QtWidgets import QHeaderView
    win, scene, panel = _window_with()
    head = panel.tree.header()
    assert head.sectionResizeMode(0) == QHeaderView.Interactive
    panel._header_pressed = True        # a drag on the header, mouse down
    head.resizeSection(0, 321)
    panel._header_pressed = False
    _close(win)
    win2, scene2, panel2 = _window_with()
    assert panel2.tree.header().sectionSize(0) == 321
    _close(win2)


# ---- 8 · What an extension says a group is ------------------------------------

def test_an_extension_names_its_groups_in_the_type_column():
    from views.extension_api import ExtensionApp
    building, tree = _building()
    tree.ext = {"stairs": {"steps": 14}}
    win, scene, panel = _window_with(building, tree)
    app = ExtensionApp(win, "stairs")
    app.add_outliner_kind(lambda g: {
        "type": "Stair", "props": [("Steps", g.ext["stairs"]["steps"])]}
        if "stairs" in (g.ext or {}) else None)
    row = _row(panel, tree)
    assert row.text(COL_TYPE) == "Stair"
    assert row.toolTip(COL_TYPE) == "Steps: 14"
    assert _row(panel, building).text(COL_TYPE) == "Group"   # not its own
    panel.search.setText("stair")
    assert not row.isHidden() and _row(panel, building).isHidden()
    _close(win)


def test_a_failing_kind_provider_is_skipped():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    win._outliner_kinds = [lambda g: 1 / 0,
                           lambda g: {"type": "Thing"}]
    panel._shape = None
    panel.refresh()
    assert _row(panel, tree).text(COL_TYPE) == "Thing"
    assert outliner.custom_kind(tree, [lambda g: None]) is None
    assert outliner.custom_kind(tree, [lambda g: {"props": []}]) is None
    _close(win)


# ---- 9 · Columns and several rows at once -------------------------------------

def test_the_header_shows_and_hides_columns_and_remembers():
    from views.outliner import COL_COPIES, COL_IFC, COL_MATERIAL
    building, tree = _building()
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    other = copy_group(proto, QVector3D(1, 0, 0))
    tree.material = {"color": [1.0, 0.0, 0.0]}
    win, scene, panel = _window_with(building, tree, proto, other)
    t = panel.tree
    assert t.isColumnHidden(COL_MATERIAL) and t.isColumnHidden(COL_IFC)
    assert not t.isColumnHidden(COL_TYPE)
    panel.set_column_shown(COL_MATERIAL, True)
    panel.set_column_shown(COL_COPIES, True)
    panel.set_column_shown(COL_IFC, True)
    panel.set_column_shown(COL_LAYER, False)
    assert _row(panel, tree).text(COL_MATERIAL) == "#ff0000"
    assert _row(panel, proto).text(COL_COPIES) == "2"
    wall = building.children[0].children[0]
    assert _row(panel, wall).text(COL_IFC) == "IfcWall"
    _close(win)
    win2, scene2, panel2 = _window_with()
    assert not panel2.tree.isColumnHidden(COL_MATERIAL)
    assert panel2.tree.isColumnHidden(COL_LAYER)
    panel2.set_column_shown(COL_LAYER, True)           # leave it as found
    for col in (COL_MATERIAL, COL_COPIES, COL_IFC):
        panel2.set_column_shown(col, False)
    _close(win2)


def test_several_rows_go_to_a_layer_in_one_step():
    building, tree = _building()
    level1 = building.children[0]
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    panel.assign_layer([wall, slab], "Structure")
    assert outliner.layer_name(wall) == "Structure" == \
        outliner.layer_name(slab)
    assert _row(panel, slab).text(COL_LAYER) == "Structure"
    win.viewport.history.undo()
    assert outliner.layer_name(wall) != "Structure"
    _close(win)


def test_several_rows_painted_and_unpainted_in_one_step():
    building, tree = _building()
    level1 = building.children[0]
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    red = {"color": [0.8, 0.1, 0.1]}
    panel.paint_groups([wall, slab], material=red)
    assert wall.material == red and slab.material == red
    panel.paint_groups([wall, slab], clear=True)
    assert wall.material is None and slab.material is None
    win.viewport.history.undo()
    assert wall.material == red and slab.material == red
    _close(win)


# ---- 10 · A plan of a group ------------------------------------------------

def test_a_plan_of_a_group_is_a_cut_a_scene_and_a_sheet_in_one_step():
    building, tree = _building()
    level2 = building.children[1]                 # its wall stands on z = 3
    win, scene, panel = _window_with(building, tree)
    planes0, views0 = len(scene.section_planes), len(scene.saved_views)
    view = panel.create_plan(level2, 1.2, sheet=True, scale=50.0)
    assert view is not None and view.name == "Plan Level 2"
    plane = scene.section_planes[-1]
    assert scene.active_section() is plane
    assert abs(plane.point.z() - 3.0 - 1.2) < 1e-6        # 1.20 over its base
    assert abs(plane.normal.z() - 1.0) < 1e-9
    assert view.perspective is False
    assert abs(view.pitch - math.radians(90.0)) < 1e-6      # looking down
    assert view.section["active"] == plane.uid
    sheet = scene.compositions[-1]
    assert sheet.frames[-1].view_key == "scene:Plan Level 2"
    assert sheet.frames[-1].scale_n == 50.0
    assert not outliner.is_orphan(scene, sheet.frames[-1])
    win.viewport.history.undo()                   # all three, at once
    assert len(scene.section_planes) == planes0
    assert len(scene.saved_views) == views0
    assert sheet not in scene.compositions
    _close(win)


def test_a_second_plan_gets_its_own_name_and_no_sheet_when_asked():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    sheets0 = len(scene.compositions)
    panel.create_plan(building, 1.2, sheet=False)
    second = panel.create_plan(building, 1.5, sheet=False)
    assert second.name == "Plan Building 2"
    assert len(scene.compositions) == sheets0
    _close(win)


def test_world_bounds_follow_the_matrices_down_the_tree():
    shelf = _moved_container_for_bounds()
    lo, hi = outliner.world_bounds([shelf], shelf.children[0])
    assert abs(lo[0] - 10.0) < 1e-6 and abs(lo[2] - 2.0) < 1e-6
    assert abs(hi[0] - 10.1) < 1e-6
    assert outliner.world_bounds([Group(name="empty")],
                                 Group(name="empty")) is None


def _moved_container_for_bounds():
    m = QMatrix4x4()
    m.translate(QVector3D(10, 0, 2))
    kid = Group(_box((0, 0, 0)), name="Kid")
    kid.xform = QMatrix4x4()
    kid.component = False
    box = _container("Shelf", [kid])
    box.xform = m
    return box


def test_an_open_composer_learns_of_a_new_plan_sheet_and_of_its_undo():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    comp_win = win._ensure_composer()
    comp_win.show()
    _app.processEvents()
    first = comp_win.comp
    panel.create_plan(building.children[1], 1.2, sheet=True)
    sheet = scene.compositions[-1]
    names = [comp_win.comp_combo.itemText(i)
             for i in range(comp_win.comp_combo.count())]
    assert sheet.name in names                       # listed, while open
    view_keys = [comp_win.view_combo.itemData(i)
                 for i in range(comp_win.view_combo.count())]
    assert "scene:Plan Level 2" in view_keys          # its scene too
    win._show_sheet(scene.compositions.index(sheet))
    assert comp_win.comp is sheet                    # it opens on it
    win.viewport.history.undo()                      # the sheet goes
    win.project_browser.on_scene_changed()
    assert comp_win.comp in scene.compositions       # not a ghost
    assert comp_win.comp is first
    comp_win._saved_version = scene.version
    comp_win.hide()
    _close(win)


def test_creating_a_plan_shows_where_it_went():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    opened = []
    win._show_sheet = opened.append
    panel.create_plan(building.children[0], 1.2, sheet=True,
                      open_sheet=True)
    assert opened == [len(scene.compositions) - 1]   # straight to it
    views = _views(win)                              # the composer exists
    panel.create_plan(building.children[1], 1.2, sheet=False)
    current = views.tree.currentItem()               # its scene, marked
    assert current is not None and current.text(0) == "Plan Level 2"
    _close(win)


def test_a_view_of_a_vertical_cut_looks_at_it_square_on():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    from core.section import SectionPlane
    cut = SectionPlane(QVector3D(4, 3, 0), QVector3D(1, 0, 0),
                       name="Cross section", symbol="C")
    scene.section_planes[:] = [cut]
    planes = list(scene.section_planes)
    view = panel.create_cut_view(cut, sheet=True, scale=50.0)
    assert view.name == "Cross section"
    assert scene.section_planes == planes            # no plane added
    assert scene.active_section() is cut
    assert view.perspective is False
    assert abs(view.yaw) < 1e-9 and abs(view.pitch) < 1e-9
    assert view.target[0] == 4.0                      # on the plane
    assert view.section["active"] == cut.uid
    sheet = scene.compositions[-1]
    assert sheet.frames[-1].view_key == "scene:Cross section"
    assert sheet.frames[-1].scale_n == 50.0
    win.viewport.history.undo()
    assert scene.section_planes == planes             # the cut stays
    assert sheet not in scene.compositions
    _close(win)


def test_a_horizontal_cut_gives_a_plan():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    from core.section import SectionPlane
    cut = SectionPlane(QVector3D(0, 0, 1.4), QVector3D(0, 0, 1),
                       symbol="A")
    scene.section_planes[:] = [cut]
    view = panel.create_cut_view(cut, sheet=False)
    assert view.name == "Section A"
    assert abs(view.pitch - math.radians(90.0)) < 1e-9
    _close(win)


def test_the_composer_says_a_frame_lost_its_scene():
    from core.composition import Composicion, MarcoVista
    win, scene, panel = _window_with()
    comp_win = win._ensure_composer()
    page = Composicion(name="Orphans")
    gone = MarcoVista(view_key="scene:Deleted cut")
    std = MarcoVista(view_key="std:top")
    page.frames[:] = [gone, std]
    scene.compositions[:] = [page]
    assert comp_win.missing_scene(gone) == "Deleted cut"
    assert comp_win.missing_scene(std) is None
    assert comp_win.render_frame(gone) is None        # nothing rendered
    assert id(gone) not in comp_win.render_cache
    comp_win._saved_version = scene.version
    _close(win)


# ---- Sheets 2D as a place to work ----------------------------------------------

def test_a_scene_dropped_on_a_sheet_is_placed_in_a_free_spot():
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    north = scene.saved_views[1]                      # on no sheet yet
    assert outliner.unplaced_scenes(scene) == [north]
    assert sheets.scenes_root.text(1) == "2 saved · 1 on no sheet"
    assert sheets.scenes_root.child(1).font(0).italic()
    frames0 = len(a102.frames)
    frame = sheets.place_scene(north, a102)
    assert frame in a102.frames and frame.view_key == "scene:North elevation"
    for other in a102.frames[:frames0]:               # nothing covered
        assert (frame.x_mm >= other.x_mm + other.w_mm
                or frame.x_mm + frame.w_mm <= other.x_mm
                or frame.y_mm >= other.y_mm + other.h_mm
                or frame.y_mm + frame.h_mm <= other.y_mm)
    assert outliner.unplaced_scenes(scene) == []
    win._composer.history.undo()                      # the composer's undo
    assert frame not in a102.frames
    _close(win)


def test_dragging_a_scene_onto_a_sheet_row_places_it():
    from PySide6.QtCore import QMimeData, QPoint, QPointF
    from PySide6.QtGui import QDropEvent
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    sheets = _views(win)
    win._composer.show()
    _app.processEvents()
    sheets.refresh()
    t = sheets.tree
    t.clearSelection()
    sheets.scenes_root.child(1).setSelected(True)      # «North elevation»
    target = sheets.sheets_root.child(1)               # A102
    t.scrollToItem(target)
    pos = t.visualItemRect(target).center()
    ev = QDropEvent(QPointF(pos), Qt.MoveAction, QMimeData(),
                    Qt.LeftButton, Qt.NoModifier)
    t.dropEvent(ev)
    assert any(f.view_key == "scene:North elevation" for f in a102.frames)
    win._composer.hide()
    _close(win)


def test_a_scene_on_a_new_sheet_and_sheets_reordered_in_one_step_each():
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    north = scene.saved_views[1]
    sheets.place_scene(north, None)
    new = scene.compositions[-1]
    assert new.name == "North elevation" and len(new.frames) == 1
    win.viewport.history.undo()                       # sheet and view go
    assert new not in scene.compositions
    sheets.move_sheet(a102, -1)
    assert scene.compositions == [a102, a101]
    assert sheets.current_sheet() is a102
    win.viewport.history.undo()
    assert scene.compositions == [a101, a102]
    _close(win)


def test_alt_arrows_move_a_sheet():
    from PySide6.QtTest import QTest
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    sheets = _views(win)
    sheets.refresh()
    sheets.tree.setCurrentItem(sheets.sheets_root.child(0))
    QTest.keyClick(sheets.tree, Qt.Key_Down, Qt.AltModifier)
    assert scene.compositions == [a102, a101]
    _close(win)


def test_the_selected_sheets_export_to_one_pdf(tmp_path):
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    sheets = _views(win)
    asked = []
    comp_win = win._ensure_composer()
    comp_win.export_all_pdf = lambda path, chosen=None: asked.append(
        (path, chosen)) or []
    sheets.export_pdf([a102], path=str(tmp_path / "out.pdf"))
    assert asked == [(str(tmp_path / "out.pdf"), [a102])]
    _close(win)


def test_export_all_pdf_can_take_only_some_sheets(tmp_path):
    win, scene, panel = _window_with()
    a101, a102 = _sheets_model(win)
    for c in (a101, a102):
        c.frames[:] = []                              # no GL renders
    comp_win = win._ensure_composer()
    path = tmp_path / "one.pdf"
    assert comp_win.export_all_pdf(str(path), [a102]) == []
    assert path.stat().st_size > 0                    # one page, written
    comp_win._saved_version = scene.version
    _close(win)


def test_free_slot_fills_the_page_then_steps():
    from core.composition import Composicion, MarcoVista
    sheet = Composicion(name="S", paper="A3")
    pw, ph = sheet.page_size_mm()
    w, h = (pw - 20) / 2 - 15, (ph - 20) / 2 - 15
    spots = []
    for _ in range(4):
        x, y = outliner.free_slot(sheet, w, h)
        sheet.frames.append(MarcoVista(x_mm=x, y_mm=y, w_mm=w, h_mm=h))
        spots.append((x, y))
    assert len(set(spots)) == 4
    assert all(x + w <= pw - 10 and y + h <= ph - 10 for x, y in spots)



# ---- The «Views and sheets» panel, in the composer ------------------------------

def _composer_with_model(win):
    building, tree = _building()
    win.viewport.scene.groups[:] = [building, tree]
    win.viewport.scene.version += 1
    a101, a102 = _sheets_model(win)
    comp_win = win._ensure_composer()
    comp_win.show_sheet(1)                            # A102 open
    return comp_win, a101, a102


def test_a_scene_dropped_on_the_page_lands_where_it_is_dropped():
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent
    from views.composer import SCENE_MIME
    win, scene, panel = _window_with()
    comp_win, a101, a102 = _composer_with_model(win)
    _app.processEvents()
    view = comp_win._view
    target = view.mapFromScene(QPointF(150.0, 100.0))
    data = QMimeData()
    data.setData(SCENE_MIME, b"North elevation")
    before = len(a102.frames)
    ev = QDropEvent(QPointF(target), Qt.CopyAction, data, Qt.LeftButton,
                    Qt.NoModifier)
    view.dropEvent(ev)
    assert len(a102.frames) == before + 1
    f = a102.frames[-1]
    assert f.view_key == "scene:North elevation"
    assert abs(f.x_mm + f.w_mm / 2 - 150.0) < 1.0      # centred on the drop
    assert abs(f.y_mm + f.h_mm / 2 - 100.0) < 1.0
    assert f.scale_n in outliner.STANDARD_SCALES
    comp_win.history.undo()                           # the composer's undo
    assert f not in a102.frames
    comp_win.hide()
    _close(win)


def test_double_click_on_a_scene_places_it_in_a_free_spot():
    win, scene, panel = _window_with()
    comp_win, a101, a102 = _composer_with_model(win)
    views = comp_win.views_panel
    views.refresh()
    frames0 = list(a102.frames)
    views.activate(views.scenes_root.child(1))        # «North elevation»
    new = [f for f in a102.frames if f not in frames0]
    assert len(new) == 1
    for other in frames0:
        f = new[0]
        assert (f.x_mm >= other.x_mm + other.w_mm
                or f.x_mm + f.w_mm <= other.x_mm
                or f.y_mm >= other.y_mm + other.h_mm
                or f.y_mm + f.h_mm <= other.y_mm)
    _close(win)


def test_the_panel_drags_scenes_by_name():
    from views.composer import SCENE_MIME
    win, scene, panel = _window_with()
    comp_win, a101, a102 = _composer_with_model(win)
    views = comp_win.views_panel
    views.refresh()
    data = views.tree.mimeData([views.scenes_root.child(0),
                                views.sheets_root.child(0)])
    assert bytes(data.data(SCENE_MIME)).decode() == "Plan L1"
    _close(win)


def test_the_scale_fits_the_model_in_the_frame():
    from core.saved_views import SavedView
    from core.camera import OrbitCamera
    building, tree = _building()                     # 5.1 m wide, 6 m tall
    win, scene, panel = _window_with(building, tree)
    cam = OrbitCamera()
    cam.set_view("front")
    cam.perspective = False
    view = SavedView.capture("Front", scene, cam)
    n = outliner.fit_scale(scene, view, 120.0, 90.0)
    assert n in outliner.STANDARD_SCALES
    lo, hi = scene.bounds()
    tall_mm = (hi.z() - lo.z()) * 1000.0 / n
    assert tall_mm <= 90.0                            # it fits …
    bigger = [s for s in outliner.STANDARD_SCALES if s < n]
    assert not bigger or (hi.z() - lo.z()) * 1000.0 / bigger[-1] > 90 * 0.85
    _close(win)


def test_the_scene_pictures_do_not_rebuild_the_list_nor_touch_the_document():
    """A new icon is an item change to Qt: it used to go through the rename
    path, touch the document and rebuild the list, which queued the
    pictures again — the scenes flickered and the file read as modified."""
    from PySide6.QtGui import QIcon, QPixmap
    win, scene, panel = _window_with()
    comp_win, a101, a102 = _composer_with_model(win)
    views = comp_win.views_panel
    pm = QPixmap(8, 8)
    pm.fill(Qt.red)
    comp_win.scene_thumbnail = lambda name: QIcon(pm)
    fills = []
    real_fill = views._fill
    views._fill = lambda sc: (fills.append(1), real_fill(sc))
    views._shape = None
    views.refresh()                                   # one fill, pictures queued
    version = scene.version
    for _ in range(40):
        _app.processEvents()
    assert len(fills) == 1
    assert scene.version == version                   # nothing «modified»
    assert not views.scenes_root.child(0).icon(0).isNull()
    _close(win)


def test_a_rename_to_the_same_name_does_nothing():
    win, scene, panel = _window_with()
    _sheets_model(win)
    views = _views(win)
    views.refresh()
    version = scene.version
    item = views.scenes_root.child(0)
    item.setText(0, item.text(0))                     # «renamed» to itself
    assert scene.version == version
    _close(win)



def test_the_left_panel_folds_away_like_the_other_panel():
    """Ctrl+F6 and the handle on its line fold the left panel («Views and
    sheets») away and back, remembered; clean screen takes it away and
    brings it back."""
    from PySide6.QtCore import QSettings
    win, scene, panel = _window_with()
    comp_win = win._ensure_composer()
    comp_win.resize(1200, 800)
    comp_win.show()
    _app.processEvents()
    views = comp_win._left_panel
    assert comp_win._act_views.shortcut().toString() == "Ctrl+F6"
    assert views.isHidden()                           # empty: folded
    comp_win.move_page("views", "left")               # a tab there opens it
    assert not views.isHidden()
    comp_win._views_handle.click()                    # the handle folds it
    assert views.isHidden() and not comp_win._act_views.isChecked()
    assert comp_win._splitter.sizes()[0] == 0
    assert QSettings().value("composer/views_visible") == "0"
    comp_win._act_views.trigger()                     # Ctrl+F6 brings it back
    assert not views.isHidden() and comp_win._splitter.sizes()[0] > 0
    comp_win._act_clean_screen.setChecked(True)
    assert views.isHidden()
    comp_win._act_clean_screen.setChecked(False)
    assert not views.isHidden()
    comp_win._act_sidebar.setChecked(False)           # the right one, alone
    assert comp_win._side_panel.isHidden() and not views.isHidden()
    comp_win._act_sidebar.setChecked(True)
    comp_win.hide()
    QSettings().remove("composer/tab_layout")         # leave it as found
    QSettings().remove("composer/views_visible")
    _close(win)



def test_side_tabs_move_between_sides_reorder_and_are_remembered():
    from PySide6.QtCore import QSettings
    win, scene, panel = _window_with()
    comp_win = win._ensure_composer()
    left, right = comp_win._left_tabs, comp_win._tabs
    assert [right.tabText(i) for i in range(right.count())] == [
        "Layout", "Views and sheets", "Items", "Item properties"]
    assert left.count() == 0
    comp_win.move_page("views", "right", 3)           # reordered on the right
    assert right.indexOf(comp_win.views_panel) == 3
    assert right.currentWidget() is comp_win.views_panel
    comp_win.move_page("props", "left")               # and to the other side
    assert left.widget(0) is comp_win.props
    assert comp_win._act_views.isChecked()            # which opens
    comp_win._show_page("props")                      # jumps find it there
    assert left.currentWidget() is comp_win.props
    assert QSettings().value("composer/tab_layout")
    comp_win._saved_version = scene.version
    _close(win)
    # A new composer opens with the tabs where they were left.
    from views.composer import ComposerWindow
    again = ComposerWindow(win)
    assert again._left_tabs.widget(0) is again.props
    assert again._tabs.indexOf(again.views_panel) == 2
    QSettings().remove("composer/tab_layout")         # leave it as found
    QSettings().remove("composer/views_visible")
    again.deleteLater()


def test_a_side_left_empty_folds_and_the_tabs_reset_to_the_factory_layout():
    from PySide6.QtCore import QSettings
    win, scene, panel = _window_with()
    comp_win = win._ensure_composer()
    left, right = comp_win._left_tabs, comp_win._tabs
    comp_win.move_page("items", "left")
    assert comp_win._act_views.isChecked()
    comp_win.move_page("items", "right")              # the left empties
    assert left.count() == 0 and not comp_win._act_views.isChecked()
    comp_win.move_page("views", "left")
    comp_win.move_page("props", "left", 0)
    comp_win.restore_default_tabs()                   # tab menu entry
    assert [right.tabText(i) for i in range(right.count())] == [
        "Layout", "Views and sheets", "Items", "Item properties"]
    assert left.count() == 0 and not comp_win._act_views.isChecked()
    assert comp_win._act_sidebar.isChecked()
    assert not QSettings().contains("composer/tab_layout")
    QSettings().remove("composer/views_visible")
    _close(win)


def test_a_tab_dropped_on_the_other_side_moves_there():
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent
    from views.composer import TAB_MIME
    win, scene, panel = _window_with()
    comp_win = win._ensure_composer()
    data = QMimeData()
    data.setData(TAB_MIME, b"items")
    ev = QDropEvent(QPointF(10, 10), Qt.MoveAction, data, Qt.LeftButton,
                    Qt.NoModifier)
    comp_win._left_tabs.dropEvent(ev)
    assert comp_win._left_tabs.indexOf(comp_win._pages["items"]) >= 0
    assert comp_win._tabs.indexOf(comp_win._pages["items"]) < 0
    from PySide6.QtCore import QSettings
    QSettings().remove("composer/tab_layout")
    QSettings().remove("composer/views_visible")
    _close(win)
