# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Expand all / Collapse all in every side tree, and the folds kept with the
document (#1694).

Scenes, the composer's scene list, the sheet explorer and BIM get the ⊞/⊟
button the Browser and Layers have; what is folded in Scenes, Layers, the
Browser and BIM is written to the .igz and comes back on open."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import core.extensions as extensions                              # noqa: E402
from core import tree_folds as TF                                 # noqa: E402
from core.scene import Scene                                      # noqa: E402


# ---- The document's record --------------------------------------------------

def test_folds_is_a_live_set_on_the_scene():
    scene = Scene()
    assert scene.tree_folds == {}
    TF.folds(scene, TF.LAYERS).add("Arq")
    assert TF.folds(scene, TF.LAYERS) == {"Arq"}
    assert scene.tree_folds[TF.LAYERS] is TF.folds(scene, TF.LAYERS)


def test_folds_survive_a_save_and_an_open(tmp_path):
    from formats import igz
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    TF.folds(scene, TF.LAYERS).update({"Arq", "Estructura"})
    TF.folds(scene, TF.BROWSER).add("abc123")
    TF.folds(scene, TF.BIM).add("class:IfcWall")
    TF.folds(scene, TF.SCENES)                  # empty: not written
    path = tmp_path / "folds.igz"
    igz.save_scene(scene, path)
    other = Scene()
    igz.load_into(other, path)
    assert other.tree_folds == {TF.LAYERS: {"Arq", "Estructura"},
                                TF.BROWSER: {"abc123"},
                                TF.BIM: {"class:IfcWall"}}
    # A file without them leaves nothing behind.
    plain = tmp_path / "plain.igz"
    igz.save_scene(Scene(), plain)
    igz.load_into(other, plain)
    assert other.tree_folds == {}


def test_the_payload_is_sorted_and_a_bad_one_is_ignored():
    scene = Scene()
    TF.folds(scene, TF.LAYERS).update({"b", "a", ""})
    assert TF.to_payload(scene) == {TF.LAYERS: ["a", "b"]}
    TF.from_payload(scene, {"layers": ["x", 3, None], "bim": "nope", 4: ["y"]})
    assert scene.tree_folds == {TF.LAYERS: {"x"}}
    TF.from_payload(scene, ["not", "a", "map"])
    assert scene.tree_folds == {}


def test_a_new_document_forgets_the_folds():
    scene = Scene()
    TF.folds(scene, TF.SCENES).add("Plantas")
    scene.clear()
    assert scene.tree_folds == {}


# ---- The panels --------------------------------------------------------------

@pytest.fixture
def win(tmp_path, monkeypatch):
    """A window with a throwaway INI; no scene pictures drawn."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    from views.tray import ScenesPanel
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail",
                        lambda self, view: None)
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    for _ in range(3):
        _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _scene_folders(scene):
    """Folders «Plans» (with «Floor 1» inside) and «Views», one scene each."""
    from core.saved_views import SavedView
    scene.scene_folders = ["Plans", "Floor 1", "Views"]
    scene.scene_folder_parents = {"Floor 1": "Plans"}
    scene.saved_views[:] = [SavedView("Ground", folder="Floor 1"),
                            SavedView("Iso", folder="Views"),
                            SavedView("Top", folder="Plans")]
    scene.version += 1


def _folder_rows(panel):
    return {it.text(0): it for it in panel._folder_rows()}


def test_scenes_tab_expands_and_collapses_all_and_keeps_it(win):
    panel = win.scenes_dock.panel
    scene = win.viewport.scene
    _scene_folders(scene)
    panel._shape = None
    panel.refresh()
    rows = _folder_rows(panel)
    assert all(r.isExpanded() for r in rows.values())
    assert panel.expand_btn.isEnabled()
    assert panel.expand_btn.toolTip() == "Collapse all"
    panel.expand_btn.click()
    assert not any(r.isExpanded() for r in panel._folder_rows())
    assert TF.folds(scene, TF.SCENES) >= {"Plans", "Views"}
    assert panel.expand_btn.toolTip() == "Expand all"
    panel.expand_btn.click()
    assert all(r.isExpanded() for r in panel._folder_rows())
    assert TF.folds(scene, TF.SCENES) == set()
    # One folded by hand is the document's, and a rebuild keeps it.
    _folder_rows(panel)["Views"].setExpanded(False)
    assert TF.folds(scene, TF.SCENES) == {"Views"}
    panel._shape = None
    panel.refresh()
    assert not _folder_rows(panel)["Views"].isExpanded()


def test_scenes_tab_opens_folded_as_the_file_says(win):
    panel = win.scenes_dock.panel
    scene = win.viewport.scene
    _scene_folders(scene)
    TF.from_payload(scene, {TF.SCENES: ["Plans"]})
    panel._shape = None
    panel.refresh()
    rows = _folder_rows(panel)
    assert not rows["Plans"].isExpanded() and rows["Views"].isExpanded()


def test_composer_scene_list_has_the_button_and_its_own_folds(win):
    from views.sheet_browser import SceneList
    scene = win.viewport.scene
    _scene_folders(scene)
    lst = SceneList(win)
    assert lst.expand_btn.toolTip() == "Collapse all"
    lst.expand_btn.click()
    assert not any(r.isExpanded() for r in lst._folder_rows())
    assert TF.folds(scene, TF.COMPOSER_SCENES) >= {"Plans", "Views"}
    assert TF.folds(scene, TF.SCENES) == set()     # the Scenes tab's apart
    lst.expand_btn.click()
    assert all(r.isExpanded() for r in lst._folder_rows())


def test_sheet_explorer_expands_and_collapses_its_folders(win):
    from core.composition import Composicion
    from core.sheet_folders import SheetFolder
    from views.sheet_browser import SheetExplorer
    scene = win.viewport.scene
    a, b = SheetFolder("Plans"), SheetFolder("Details")
    scene.sheet_folders[:] = [a, b]
    s1, s2 = Composicion(name="A-101"), Composicion(name="D-1")
    s1.folder_id, s2.folder_id = a.id, b.id
    scene.compositions[:] = [s1, s2]
    ex = SheetExplorer(win)
    ex.refresh(force=True)
    assert ex.expand_btn.isEnabled()
    ex.expand_btn.click()
    assert not a.expanded and not b.expanded       # kept on the folders
    ex.expand_btn.click()
    assert a.expanded and b.expanded


def test_layers_folds_are_the_documents(win):
    from core.layers import Layer
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers += [Layer("Walls", folder="Arch"), Layer("Slabs",
                                                          folder="Struct")]
    scene.layer_folders = ["Arch", "Struct"]
    panel.refresh()
    panel._expand_or_collapse()                     # all open → all shut
    assert TF.folds(scene, TF.LAYERS) == {"Arch", "Struct"}
    TF.from_payload(scene, {TF.LAYERS: ["Struct"]})
    panel.refresh()
    shut = {it.text(0) for it in panel._all_items()
            if it.childCount() and not it.isExpanded()}
    assert shut == {"Struct"}


def _bim_model(scene):
    from core.bim import tag_group
    from core.group import Group
    from core.mesh import Mesh
    floors = []
    for i, name in enumerate(("floor1", "floor2")):
        m = Mesh()
        x = i * 3
        m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
        leaf = Group(m)
        leaf.name = f"W{i + 1}"
        tag_group(leaf, "IfcWall", leaf.name)
        outer = Group(Mesh(), name=name)
        outer.children.append(leaf)
        scene.groups.append(outer)
        floors.append(outer)
    scene.version += 1
    return floors


def test_bim_expands_collapses_all_and_keeps_folds_by_uid(win):
    from views.side_tree import foldable_rows
    scene = win.viewport.scene
    floors = _bim_model(scene)
    panel = win.bim_tray.bim
    panel.refresh()
    rows = foldable_rows(panel.tree)
    assert rows and all(r.isExpanded() for r in rows)
    panel.expand_btn.click()
    assert not any(r.isExpanded() for r in foldable_rows(panel.tree))
    assert f"group:{floors[0].uid}" in TF.folds(scene, TF.BIM)
    panel.expand_btn.click()
    assert TF.folds(scene, TF.BIM) == set()
    # What the file says is folded comes back folded.
    TF.from_payload(scene, {TF.BIM: [f"group:{floors[1].uid}"]})
    panel._build_tree()
    shut = [r.text(0) for r in foldable_rows(panel.tree)
            if not r.isExpanded()]
    assert shut == ["floor2"]


def test_browser_keeps_the_opened_groups_with_the_document(win):
    from core.group import Group
    from core.mesh import Mesh
    scene = win.viewport.scene
    outer = Group(Mesh(), name="House")
    inner = Group(Mesh(), name="Walls")
    outer.children.append(inner)
    scene.groups.append(outer)
    scene.version += 1
    browser = win.project_browser.outliner
    browser.refresh()
    row = browser._items[id(outer)]
    row.setExpanded(True)
    assert outer.uid in TF.folds(scene, TF.BROWSER)
    browser._collapse_all()
    assert outer.uid not in TF.folds(scene, TF.BROWSER)
    browser._expand_all()
    assert outer.uid in TF.folds(scene, TF.BROWSER)
    # A file that says it was shut opens it shut.
    TF.from_payload(scene, {})
    browser._forget_rows()
    browser.__dict__.pop("_kept_expanded", None)
    browser.refresh()
    assert not browser._items[id(outer)].isExpanded()
    TF.from_payload(scene, {TF.BROWSER: [outer.uid]})
    browser._forget_rows()
    browser.__dict__.pop("_kept_expanded", None)
    browser.refresh()
    assert browser._items[id(outer)].isExpanded()


def test_browser_layer_headings_folded_are_the_documents(win):
    from core.group import Group
    from core.layers import Layer
    from core.mesh import Mesh
    scene = win.viewport.scene
    scene.layers.append(Layer("Walls"))
    house = Group(Mesh(), name="House")
    house.layer = "Walls"
    scene.groups.append(house)
    scene.version += 1
    browser = win.project_browser.outliner
    browser.set_order_by("layer")
    browser.refresh()
    browser._heads[("layer", "Walls")].setExpanded(False)
    assert "layer:Walls" in TF.folds(scene, TF.BROWSER_HEADS)
    # Reopened: the heading comes back folded.
    browser._forget_rows()
    browser.refresh()
    assert not browser._heads[("layer", "Walls")].isExpanded()
