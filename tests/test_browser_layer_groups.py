# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ordering the Browser by layer files the model's top-level groups under a
heading per layer — and per layer folder — in the order the Layers tab
lists them, each heading folding on its own. Another way of reading the
tree: the document's order stays as it was, and nothing reaches the model.

Every model here is generated, as in tests/test_browser_layer_order.py.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core import layers as L
from core import outliner
from core.group import Group
from core.layers import DEFAULT_LAYER, Layer
from core.mesh import Mesh
from views.outliner import COL_EYE, COL_LAYER, COL_NAME

_app = QApplication.instance() or QApplication([])

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]


def _box(size=0.1) -> Mesh:
    mesh = Mesh()
    c = [QVector3D(dx * size, dy * size, dz * size)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    return mesh


def _group(name, layer=None) -> Group:
    g = Group(_box(), name=name)
    g.layer = layer
    return g


def _container(name, kids, layer=None) -> Group:
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    g.layer = layer
    return g


@pytest.fixture(autouse=True)
def _settings():
    """The Browser in the document's order and the Layers tab by name, at
    the start and the end of every test: both are remembered."""
    for key in ("browser/order", "layers/sort_by"):
        QSettings().remove(key)
    yield
    for key in ("browser/order", "layers/sort_by"):
        QSettings().remove(key)


def _window(layers, *groups, folders=None):
    """A window whose model holds ``groups`` on ``layers`` (names), the
    layers filed as ``folders`` says: ``{layer: folder}``."""
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.layers[:] = [Layer(DEFAULT_LAYER)] + [Layer(n) for n in layers]
    for name, folder in (folders or {}).items():
        if folder not in L.folders_of(scene):
            scene.layer_folders = L.folders_of(scene) + [folder]
        scene.layer(name).folder = folder
    scene.groups[:] = groups
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version


def _headings(panel, item=None, depth=0):
    """``(depth, kind, name)`` of the heading rows, top to bottom."""
    item = item or panel.tree.topLevelItem(0)
    out = []
    for i in range(item.childCount()):
        row = item.child(i)
        head = panel._head_of(row)
        if head is not None:
            out.append((depth, *head))
            out += _headings(panel, row, depth + 1)
    return out


def _under(panel, kind, name):
    """The group names right under a heading."""
    head = panel._heads[(kind, name)]
    return [panel._group_of(head.child(i)).name
            for i in range(head.childCount())
            if panel._group_of(head.child(i)) is not None]


# ---- The headings, without a window -----------------------------------------

def test_the_outline_lists_folders_before_what_they_hold():
    scene = type("Scene", (), {
        "layers": [Layer(DEFAULT_LAYER), Layer("Muros"), Layer("Acero"),
                   Layer("Losa")]})()
    scene.layer_folders = ["Estructura", "Hormigón"]
    scene.folder_parents = {"Hormigón": "Estructura"}
    scene.layers[2].folder = "Estructura"
    scene.layers[3].folder = "Hormigón"
    assert outliner.layer_outline(scene) == [
        ("layer", DEFAULT_LAYER, 0),
        ("folder", "Estructura", 0),
        ("folder", "Hormigón", 1),
        ("layer", "Losa", 2),
        ("layer", "Acero", 1),
        ("layer", "Muros", 0)]
    # The layers' own order follows the same list.
    assert outliner.outline_rank(outliner.layer_outline(scene)) == {
        DEFAULT_LAYER: 0, "Losa": 1, "Acero": 2, "Muros": 3}


def test_only_the_layers_in_use_and_their_folders_get_a_heading():
    outline = [("layer", DEFAULT_LAYER, 0), ("folder", "Vacía", 0),
               ("layer", "Nada", 1), ("folder", "Estructura", 0),
               ("folder", "Hormigón", 1), ("layer", "Losa", 2),
               ("layer", "Muros", 0)]
    assert outliner.layer_headings(outline, {"Losa", "Muros"}) == [
        ("folder", "Estructura", None),
        ("folder", "Hormigón", "Estructura"),
        ("layer", "Losa", "Hormigón"),
        ("layer", "Muros", None)]


def test_a_layer_the_outline_does_not_list_comes_last():
    outline = [("layer", DEFAULT_LAYER, 0), ("layer", "Muros", 0)]
    assert outliner.layer_headings(outline, {"Muros", "Borrada"}) == [
        ("layer", "Muros", None), ("layer", "Borrada", None)]


# ---- The Browser's rows ------------------------------------------------------

def test_the_document_order_has_no_headings_and_stays_as_it_was():
    house, site = _group("House", "Walls"), _group("Site")
    win, scene, panel = _window(["Walls"], house, site)
    try:
        assert panel._heads == {}
        root = panel.tree.topLevelItem(0)
        assert [root.child(i) for i in range(root.childCount())] == [
            panel._items[id(house)], panel._items[id(site)]]
    finally:
        _close(win)


def test_ordering_by_layer_files_the_groups_under_their_layer():
    house = _group("House", "Walls")
    shed = _group("Shed", "Walls")
    site = _group("Site")
    kid = _group("Kid", "Roof")
    host = _container("Host", [kid], layer="Walls")
    win, scene, panel = _window(["Walls", "Roof"], house, site, host, shed)
    try:
        panel.set_order_by("layer")
        # Layer 0 first, then the layers by name as the Layers tab lists
        # them; «Roof» has no group at the top level, so no heading.
        assert _headings(panel) == [(0, "layer", DEFAULT_LAYER),
                                    (0, "layer", "Walls")]
        assert _under(panel, "layer", DEFAULT_LAYER) == ["Site"]
        assert _under(panel, "layer", "Walls") == ["House", "Host", "Shed"]
        # A group stays inside its parent, whatever its own layer.
        assert panel._items[id(kid)].parent() is panel._items[id(host)]
        head = panel._heads[("layer", "Walls")]
        assert head.text(COL_NAME) == "Walls · 3"         # with its count
        assert head.text(COL_LAYER) == ""
        # Nothing of this reached the model.
        assert scene.groups == [house, site, host, shed]
    finally:
        _close(win)


def test_a_folder_heading_holds_the_headings_of_its_layers():
    acero, vidrio = _group("Pilar", "Acero"), _group("Ventana", "Vidrio")
    muros = _group("Muro", "Muros")
    win, scene, panel = _window(["Muros", "Acero", "Vidrio"],
                                muros, acero, vidrio,
                                folders={"Acero": "Estructura",
                                         "Vidrio": "Estructura"})
    try:
        panel.set_order_by("layer")
        assert _headings(panel) == [(0, "folder", "Estructura"),
                                    (1, "layer", "Acero"),
                                    (1, "layer", "Vidrio"),
                                    (0, "layer", "Muros")]
        folder = panel._heads[("folder", "Estructura")]
        assert folder.text(COL_NAME) == "Estructura · 2"  # its layers' count
    finally:
        _close(win)


def test_each_heading_folds_on_its_own_and_stays_folded():
    house, site = _group("House", "Walls"), _group("Site")
    trees = _group("Trees", "Vegetation")
    win, scene, panel = _window(["Walls", "Vegetation"], house, site, trees)
    try:
        panel.set_order_by("layer")
        heads = panel._heads
        assert all(h.isExpanded() for h in heads.values())
        heads[("layer", "Walls")].setExpanded(False)
        assert heads[("layer", "Vegetation")].isExpanded()
        assert heads[("layer", DEFAULT_LAYER)].isExpanded()

        # A rebuild (a layer assigned, an undo) keeps it folded.
        panel.assign_layer([site], "Vegetation")
        assert not panel._heads[("layer", "Walls")].isExpanded()
        assert panel._heads[("layer", "Vegetation")].isExpanded()

        # So does a trip to the document's order and back.
        panel.set_order_by("document")
        panel.set_order_by("layer")
        assert not panel._heads[("layer", "Walls")].isExpanded()
        assert panel._heads[("layer", "Vegetation")].isExpanded()
    finally:
        _close(win)


def test_another_document_starts_with_every_heading_open():
    house = _group("House", "Walls")
    win, scene, panel = _window(["Walls"], house)
    try:
        panel.set_order_by("layer")
        panel._heads[("layer", "Walls")].setExpanded(False)
        panel._forget_rows()                 # what New and Open do
        panel.refresh()
        assert panel._heads[("layer", "Walls")].isExpanded()
    finally:
        _close(win)


def test_expand_all_and_collapse_all_reach_the_headings():
    house, site = _group("House", "Walls"), _group("Site")
    win, scene, panel = _window(["Walls"], house, site)
    try:
        panel.set_order_by("layer")
        assert panel._all_expanded()
        panel._expand_or_collapse()                  # ⊟: everything folds
        assert not any(h.isExpanded() for h in panel._heads.values())
        assert not panel._all_expanded()
        panel._expand_or_collapse()                  # ⊞: everything opens
        assert all(h.isExpanded() for h in panel._heads.values())
        panel._heads[("layer", "Walls")].setExpanded(False)
        assert not panel._all_expanded()             # the button says ⊞
    finally:
        _close(win)


def test_the_filter_leaves_no_empty_heading():
    house, shed = _group("House", "Walls"), _group("Shed", "Walls")
    site = _group("Site")
    win, scene, panel = _window(["Walls"], house, shed, site)
    try:
        panel.set_order_by("layer")
        panel.search.setText("site")
        assert panel._heads[("layer", "Walls")].isHidden()
        assert not panel._heads[("layer", DEFAULT_LAYER)].isHidden()
        panel.search.setText("")
        assert not panel._heads[("layer", "Walls")].isHidden()

        house.hidden = True
        panel.refresh()
        panel.set_state_filter("hidden")
        assert not panel._heads[("layer", "Walls")].isHidden()
        assert panel._heads[("layer", DEFAULT_LAYER)].isHidden()
        panel.set_state_filter("all")
        assert not panel._heads[("layer", DEFAULT_LAYER)].isHidden()
    finally:
        _close(win)


def test_a_folder_heading_hides_with_its_last_shown_layer():
    pilar = _group("Pilar", "Acero")
    muro = _group("Muro", "Muros")
    win, scene, panel = _window(["Muros", "Acero"], muro, pilar,
                                folders={"Acero": "Estructura"})
    try:
        panel.set_order_by("layer")
        panel.search.setText("muro")
        assert panel._heads[("layer", "Acero")].isHidden()
        assert panel._heads[("folder", "Estructura")].isHidden()
        assert not panel._heads[("layer", "Muros")].isHidden()
    finally:
        _close(win)


def test_a_heading_is_not_a_group_it_never_drags_selects_or_hides():
    house = _group("House", "Walls")
    win, scene, panel = _window(["Walls"], house)
    try:
        panel.set_order_by("layer")
        head = panel._heads[("layer", "Walls")]
        assert panel._group_of(head) is None
        from PySide6.QtCore import Qt
        assert not head.flags() & Qt.ItemIsSelectable
        assert not head.flags() & Qt.ItemIsDragEnabled
        assert not head.flags() & Qt.ItemIsEditable
        panel._on_item_clicked(head, COL_EYE)         # nothing to hide
        assert not house.hidden
        panel.open_item(head)                         # nothing to open
        assert scene.edit_group is None
    finally:
        _close(win)


def test_a_drop_on_a_heading_goes_to_the_top_level_and_keeps_the_layer():
    guest = _group("Guest", "Roof")
    host = _container("Host", [guest], layer="Walls")
    win, scene, panel = _window(["Walls", "Roof"], host)
    try:
        panel.set_order_by("layer")
        t = panel.tree
        head = panel._heads[("layer", "Walls")]
        token = t.drop_target(t.visualItemRect(head).center())
        assert token is None
        assert t.drop_text(token) == "At the top level"
        steps = len(win.viewport.history.undo_stack)
        t.apply_drop(token, [panel._items[id(guest)]])
        assert guest in scene.groups and guest not in host.children
        assert guest.layer == "Roof"                  # no layer assigned
        assert len(win.viewport.history.undo_stack) == steps + 1
        panel.refresh()
        assert _under(panel, "layer", "Roof") == ["Guest"]
    finally:
        _close(win)


def test_sorting_the_layers_tab_reorders_the_headings():
    a, b = _group("A", "Alfa"), _group("B", "Beta")
    win, scene, panel = _window(["Alfa", "Beta"], a, b)
    try:
        panel.set_order_by("layer")
        assert [n for _d, _k, n in _headings(panel)] == ["Alfa", "Beta"]
        from views.layers_panel import COL_NAME as LAYERS_NAME
        layers = win.layers_dock.panel
        told = []
        layers.orderChanged.connect(lambda: told.append(1))
        layers._on_header_clicked(LAYERS_NAME)        # by name, Z → A
        assert told == [1]
        panel.refresh()                               # the hidden Browser
        assert [n for _d, _k, n in _headings(panel)] == ["Beta", "Alfa"]
        layers.refresh()                              # same order: no news
        assert told == [1]
    finally:
        _close(win)


def test_the_order_made_follows_the_layers_tab_too():
    z, a = _group("Z", "Zinc"), _group("A", "Acero")
    win, scene, panel = _window(["Zinc", "Acero"], z, a)
    try:
        panel.set_order_by("layer")
        assert [n for _d, _k, n in _headings(panel)] == ["Acero", "Zinc"]
        win.layers_dock.panel.set_sort_by("created")
        panel.refresh()
        assert [n for _d, _k, n in _headings(panel)] == ["Zinc", "Acero"]
    finally:
        _close(win)


def test_a_layer_made_while_the_layers_tab_waits_is_read_in_its_place():
    """Behind the Browser's tab the Layers list is not rebuilt per edit:
    the Browser brings it up to date before reading its order."""
    m = _group("M", "Muros")
    win, scene, panel = _window(["Muros"], m)
    try:
        panel.set_order_by("layer")
        scene.layers.append(Layer("Acero"))
        scene.version += 1
        a = _group("A", "Acero")
        scene.groups.append(a)
        panel.refresh()
        assert [n for _d, _k, n in _headings(panel)] == ["Acero", "Muros"]
    finally:
        _close(win)


def test_the_layers_list_is_not_rebuilt_under_a_name_being_typed():
    """Bringing the Layers list up to date must wait for the name of a new
    layer to be typed: rebuilt under it, the editor closed."""
    from PySide6.QtWidgets import QAbstractItemView
    m = _group("M", "Muros")
    win, scene, panel = _window(["Muros"], m)
    try:
        panel.set_order_by("layer")
        layers = win.layers_dock.panel
        win.layers_dock.raise_()
        _app.processEvents()
        layers.add_layer()
        _app.processEvents()
        assert layers.tree.state() == QAbstractItemView.EditingState
        scene.layers.append(Layer("Acero"))     # made elsewhere meanwhile
        scene.version += 1
        panel.refresh()
        assert layers.tree.state() == QAbstractItemView.EditingState
        layers.tree.closePersistentEditor(layers.tree.currentItem())
    finally:
        _close(win)


def test_selecting_in_the_model_unfolds_its_heading():
    house, site = _group("House", "Walls"), _group("Site")
    win, scene, panel = _window(["Walls"], house, site)
    try:
        panel.set_order_by("layer")
        panel._heads[("layer", "Walls")].setExpanded(False)
        scene.selection.clear()
        scene.selection.add(house)
        panel.refresh()
        assert panel._heads[("layer", "Walls")].isExpanded()
        assert panel._items[id(house)].isSelected()
    finally:
        _close(win)


def test_ten_thousand_rows_by_layer_build_quickly():
    groups = [_group(f"G{i}", ("Walls", "Roof", None)[i % 3])
              for i in range(10_000)]
    win, scene, panel = _window(["Walls", "Roof"], *groups)
    try:
        QSettings().setValue("browser/order", "layer")
        panel._shape = None
        t0 = time.perf_counter()
        panel.refresh()
        elapsed = time.perf_counter() - t0
        assert len(panel._heads) == 3
        assert sum(h.childCount() for h in panel._heads.values()) == 10_000
        assert elapsed < 10.0
    finally:
        _close(win)


# ---- The headings' count, eye, padlock and double click ----------------------

def test_a_heading_counts_its_top_level_objects():
    kid = _group("Kid", "Walls")
    host = _container("Host", [kid], layer="Walls")
    win, scene, panel = _window(["Walls", "Acero"], host, _group("Shed", "Walls"),
                                _group("Pilar", "Acero"),
                                folders={"Acero": "Estructura"})
    try:
        panel.set_order_by("layer")
        # Top-level objects only: the kid is counted inside its host.
        assert panel._heads[("layer", "Walls")].text(COL_NAME) == "Walls · 2"
        assert panel._heads[("layer", "Acero")].text(COL_NAME) == "Acero · 1"
        assert panel._heads[("folder", "Estructura")].text(COL_NAME) == \
            "Estructura · 1"
        panel.assign_layer([host], "Acero")
        assert panel._heads[("layer", "Walls")].text(COL_NAME) == "Walls · 1"
        assert panel._heads[("layer", "Acero")].text(COL_NAME) == "Acero · 2"
    finally:
        _close(win)


def test_the_eye_of_a_heading_hides_its_layer_as_the_layers_tab_does():
    """Through the Layers tab: the same change as there, which «Previous
    layer state» brings back (a layer's visibility is not Ctrl+Z's)."""
    from views.outliner import mark_icon
    house = _group("House", "Walls")
    win, scene, panel = _window(["Walls"], house, _group("Site"))
    try:
        panel.set_order_by("layer")
        head = panel._heads[("layer", "Walls")]
        assert head.icon(COL_EYE).cacheKey() == mark_icon("eye").cacheKey()
        panel.cell_clicked(head, COL_EYE)
        assert not scene.layer("Walls").visible
        assert not house.hidden                      # the layer, not the row
        head = panel._heads[("layer", "Walls")]
        assert head.icon(COL_EYE).cacheKey() == mark_icon("eye_off").cacheKey()
        panel.cell_clicked(head, COL_EYE)            # and back
        assert scene.layer("Walls").visible
        panel.cell_clicked(head, COL_EYE)
        assert win.layers_dock.panel.previous_state()
        panel.refresh()
        assert scene.layer("Walls").visible
        assert panel._heads[("layer", "Walls")].icon(COL_EYE).cacheKey() ==             mark_icon("eye").cacheKey()
    finally:
        _close(win)


def test_the_padlock_of_a_heading_locks_its_layer():
    from views.outliner import COL_LOCK, mark_icon
    win, scene, panel = _window(["Walls"], _group("House", "Walls"))
    try:
        panel.set_order_by("layer")
        head = panel._heads[("layer", "Walls")]
        panel.cell_clicked(head, COL_LOCK)
        assert scene.layer("Walls").locked
        assert panel._heads[("layer", "Walls")].icon(COL_LOCK).cacheKey() == \
            mark_icon("lock").cacheKey()
        panel.cell_clicked(head, COL_LOCK)
        assert not scene.layer("Walls").locked
    finally:
        _close(win)


def test_the_eye_of_a_folder_heading_hides_every_layer_in_it():
    win, scene, panel = _window(["Acero", "Vidrio", "Muros"],
                                _group("Pilar", "Acero"),
                                _group("Ventana", "Vidrio"),
                                _group("Muro", "Muros"),
                                folders={"Acero": "Estructura",
                                         "Vidrio": "Estructura"})
    try:
        panel.set_order_by("layer")
        panel.cell_clicked(panel._heads[("folder", "Estructura")], COL_EYE)
        assert not scene.layer("Acero").visible
        assert not scene.layer("Vidrio").visible
        assert scene.layer("Muros").visible
        # A layer shown again by hand: the folder's eye opens, and a click
        # shows the whole folder rather than hiding that one.
        scene.layer("Acero").visible = True
        panel.refresh()
        panel.cell_clicked(panel._heads[("folder", "Estructura")], COL_EYE)
        assert not scene.layer("Acero").visible
        assert not scene.layer("Vidrio").visible
    finally:
        _close(win)


def test_a_double_click_on_a_heading_selects_its_objects_and_keeps_it_open():
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    house, shed = _group("House", "Walls"), _group("Shed", "Walls")
    kid = _group("Kid", "Walls")
    host = _container("Host", [kid])
    site = _group("Site")
    win, scene, panel = _window(["Walls"], house, shed, host, site)
    try:
        panel.set_order_by("layer")
        win.show()
        _app.processEvents()
        head = panel._heads[("layer", "Walls")]
        rect = panel.tree.visualItemRect(head)
        pos = QPointF(panel.tree.header().sectionViewportPosition(COL_NAME)
                      + 30, rect.center().y())
        ev = QMouseEvent(QEvent.MouseButtonDblClick, pos,
                         panel.tree.viewport().mapToGlobal(pos),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        panel.tree.mouseDoubleClickEvent(ev)
        # The top-level objects of the layer; the kid is inside another
        # group, a context of its own.
        assert set(scene.selection) == {house, shed}
        assert panel._heads[("layer", "Walls")].isExpanded()
        assert panel._items[id(house)].isSelected()
        assert not panel._items[id(site)].isSelected()
    finally:
        _close(win)
        win.close()


def test_a_heading_of_a_locked_layer_picks_its_rows_here_only():
    house = _group("House", "Walls")
    win, scene, panel = _window(["Walls"], house)
    try:
        panel.set_order_by("layer")
        scene.layer("Walls").locked = True
        panel.refresh()
        panel.open_item(panel._heads[("layer", "Walls")])   # Enter
        assert house not in scene.selection         # the view cannot take it
        assert panel._items[id(house)].isSelected()  # picked in the tree
    finally:
        _close(win)


def test_a_double_click_on_a_heading_leaves_an_open_group():
    house = _group("House", "Walls")
    kid = _group("Kid")
    host = _container("Host", [kid])
    win, scene, panel = _window(["Walls"], house, host)
    try:
        panel.set_order_by("layer")
        win.viewport.begin_group_edit(host)
        panel.select_head(("layer", "Walls"))
        assert scene.edit_group is None
        assert set(scene.selection) == {house}
    finally:
        _close(win)
