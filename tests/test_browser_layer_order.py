# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ordering the Browser's rows by layer: a way of reading the tree, not a
change to the model. Siblings take the layers' order — the Layers tab's
own, folders included: the layers of a folder stay together where the
folder sits — and a group stays inside its parent, so drag, rename,
isolate and delete go on working on the same groups.

Every model here is generated, as in tests/test_outliner.py.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMenu

from core import layers as L
from core import outliner
from core.group import Group
from core.layers import DEFAULT_LAYER, Layer
from core.mesh import Mesh
from views.outliner import COL_LAYER, node_icon

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


def _group(name, layer=None, at=(0.0, 0.0, 0.0)) -> Group:
    g = Group(_box(at), name=name)
    g.layer = layer
    return g


def _container(name, kids, layer=None) -> Group:
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    g.layer = layer
    return g


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


@pytest.fixture(autouse=True)
def _document_order():
    """Each test starts and ends in the document's own order: the choice is
    remembered in the settings, and one test must not sort the next one."""
    QSettings().remove("browser/order")
    QSettings().remove("layers/sort_by")        # the Layers tab: by name
    yield
    QSettings().remove("browser/order")
    QSettings().remove("layers/sort_by")


def _layers(scene, *names):
    scene.layers[:] = [Layer(DEFAULT_LAYER)] + [Layer(n) for n in names]
    scene.version += 1


def _root_order(panel):
    """The model's top-level groups as the rows list them, through the
    layer headings when ordering by layer."""
    out = []

    def walk(item):
        for i in range(item.childCount()):
            row = item.child(i)
            g = panel._group_of(row)
            if g is not None:
                out.append(g.name)
            elif panel._head_of(row) is not None:
                walk(row)
    walk(panel.tree.topLevelItem(0))
    return out


# ---- The order itself, without a window -------------------------------------

def test_siblings_are_ordered_by_layer_and_stay_inside_their_parent():
    walls = _group("Walls", "Walls")
    roof = _group("Roof", "Roof")
    plain = _group("Plain")
    kid = _group("Kid", "Roof")
    host = _container("Host", [kid])
    groups = [walls, host, plain, roof]          # the document's own order
    rank = {DEFAULT_LAYER: 0, "Walls": 1, "Roof": 2}

    rows = outliner.walk_by_layer(groups, rank)
    assert [g.name for g, _p, _d in rows] == [
        "Host", "Kid", "Plain", "Walls", "Roof"]
    by_name = {g.name: (g, p, d) for g, p, d in rows}
    assert by_name["Kid"][1] is host              # inside its parent still
    assert by_name["Kid"][2] == 1
    # The model itself is left alone: this is a way of reading it.
    assert [g.name for g in groups] == ["Walls", "Host", "Plain", "Roof"]
    assert host.children == [kid]


def test_the_default_layer_comes_first_and_the_rest_as_the_tab_lists_them():
    scene = type("Scene", (), {
        "layers": [Layer(DEFAULT_LAYER), Layer("Roof"), Layer("Walls")]})()
    rank = outliner.layer_rank(scene)
    assert rank == {DEFAULT_LAYER: 0, "Roof": 1, "Walls": 2}
    assert rank[DEFAULT_LAYER] < rank["Roof"] < rank["Walls"]


def test_a_layer_that_no_longer_exists_sorts_after_every_one_of_them():
    scene = type("Scene", (), {"layers": [Layer(DEFAULT_LAYER)]})()
    gone = _group("Gone", "Deleted layer")
    plain = _group("Plain")
    rows = outliner.walk_by_layer([gone, plain], outliner.layer_rank(scene))
    assert [g.name for g, _p, _d in rows] == ["Plain", "Gone"]


def test_ten_thousand_rows_order_quickly():
    groups = [_group(f"G{i}", ("Walls", "Roof", None)[i % 3])
              for i in range(10_000)]
    scene = type("Scene", (), {
        "layers": [Layer(DEFAULT_LAYER), Layer("Walls"), Layer("Roof")]})()
    t0 = time.perf_counter()
    rows = outliner.walk_by_layer(groups, outliner.layer_rank(scene))
    elapsed = time.perf_counter() - t0
    assert len(rows) == 10_000
    assert rows[0][0].layer is None               # the default layer first
    assert elapsed < 1.0


# ---- Folder folders: the layers of a folder stay together --------------------

def _scene_with(*names, folders=(), parents=None):
    scene = type("Scene", (), {
        "layers": [Layer(DEFAULT_LAYER)] + [Layer(n) for n in names]})()
    scene.layer_folders = list(folders)
    scene.folder_parents = dict(parents or {})
    return scene


def test_the_layers_of_a_folder_are_ordered_together():
    """A layer filed into a folder takes the folder's place, however far
    apart the layers were made: the rows on them stay together."""
    scene = _scene_with("Muros", "Acero", "Vidrio", "Tabique",
                        folders=("Acabados", "Obra gris"))
    scene.layers[2].folder = "Acabados"          # Acero
    scene.layers[3].folder = "Acabados"          # Vidrio
    scene.layers[4].folder = "Obra gris"         # Tabique, made last
    assert L.ordered_names(scene) == [
        DEFAULT_LAYER, "Acero", "Vidrio", "Tabique", "Muros"]
    rank = outliner.layer_rank(scene)
    assert rank["Acero"] < rank["Vidrio"] < rank["Tabique"] < rank["Muros"]


def test_a_folder_inside_a_folder_holds_its_layers_first():
    scene = _scene_with("A", "B", "C", folders=("Estructura", "Hormigón"),
                        parents={"Hormigón": "Estructura"})
    scene.layers[1].folder = "Estructura"        # A
    scene.layers[2].folder = "Hormigón"          # B
    assert L.ordered_names(scene) == [DEFAULT_LAYER, "B", "A", "C"]


# ---- The Browser's rows ------------------------------------------------------

def test_ordering_by_layer_reorders_the_rows_and_is_remembered():
    house = _group("House", "Walls")
    site = _group("Site")
    trees = _group("Trees", "Vegetation")
    win, scene, panel = _window_with(house, site, trees)
    try:
        _layers(scene, "Walls", "Vegetation")
        panel.refresh()
        assert _root_order(panel) == ["House", "Site", "Trees"]

        panel.set_order_by("layer")
        # The Layers tab lists them by name: Vegetation before Walls.
        assert _root_order(panel) == ["Site", "Trees", "House"]
        assert QSettings().value("browser/order") == "layer"

        panel.set_order_by("document")
        assert _root_order(panel) == ["House", "Site", "Trees"]
        assert QSettings().value("browser/order") == "document"
        # Nothing of this reached the model.
        assert scene.groups == [house, site, trees]
    finally:
        _close(win)


def test_a_group_stays_inside_its_parent_and_its_children_order_between_themselves():
    kid_a = _group("Kid A", "Roof")
    kid_b = _group("Kid B")
    host = _container("Host", [kid_a, kid_b], layer="Walls")
    win, scene, panel = _window_with(host)
    try:
        _layers(scene, "Walls", "Roof")
        panel.set_order_by("layer")
        host_row = panel._items[id(host)]
        assert panel._items[id(kid_a)].parent() is host_row
        assert panel._items[id(kid_b)].parent() is host_row
        assert host_row.child(0) is panel._items[id(kid_b)]
        assert host_row.child(1) is panel._items[id(kid_a)]
        # The Layer column still says the truth of each row.
        assert host_row.text(COL_LAYER) == "Walls"
        assert panel._items[id(kid_a)].text(COL_LAYER) == "Roof"
    finally:
        _close(win)


def test_ordering_by_layer_keeps_the_rows_of_a_folder_together():
    muros = _group("Muros 1", "Muros")
    acero = _group("Pilar", "Acero")
    vidrio = _group("Vidrio 1", "Vidrio")
    site = _group("Site")
    win, scene, panel = _window_with(muros, acero, vidrio, site)
    try:
        _layers(scene, "Muros", "Acero", "Vidrio")
        scene.layer_folders = ["Estructura"]
        scene.layer("Acero").folder = "Estructura"
        scene.layer("Vidrio").folder = "Estructura"
        panel.set_order_by("layer")
        # The folder's layers first, in the order the folder lists them,
        # then the layer made before them but left out of any folder.
        assert _root_order(panel) == ["Site", "Pilar", "Vidrio 1", "Muros 1"]
        first = panel._items[id(acero)]
        second = panel._items[id(vidrio)]
        third = panel._items[id(muros)]
        folder = panel._heads[("folder", "Estructura")]
        assert first.parent() is panel._heads[("layer", "Acero")]
        assert second.parent() is panel._heads[("layer", "Vidrio")]
        assert first.parent().parent() is folder
        assert second.parent().parent() is folder
        assert third.parent() is panel._heads[("layer", "Muros")]
        assert first.text(COL_LAYER) == "Acero"      # the column tells the truth
    finally:
        _close(win)


def test_filing_a_layer_into_a_folder_reorders_the_rows():
    """No switch to flip again: the layers' order is part of what tells
    the rows are stale, so filing a layer moves its rows at once."""
    muros = _group("Muros 1", "Muros")
    acero = _group("Pilar", "Acero")
    win, scene, panel = _window_with(muros, acero)
    try:
        _layers(scene, "Muros", "Acero")
        win.layers_dock.panel.set_sort_by("created")   # Muros made first
        panel.set_order_by("layer")
        assert _root_order(panel) == ["Muros 1", "Pilar"]

        L.move_to_folder(scene, ["Acero"], "Estructura")
        panel.refresh()
        assert _root_order(panel) == ["Pilar", "Muros 1"]

        L.move_to_folder(scene, ["Acero"], None)
        panel.refresh()
        assert _root_order(panel) == ["Muros 1", "Pilar"]
    finally:
        _close(win)


def test_assigning_a_layer_reorders_and_undo_puts_the_row_back():
    house = _group("House", "Walls")
    site = _group("Site")
    win, scene, panel = _window_with(house, site)
    try:
        _layers(scene, "Walls", "Zinc")
        panel.set_order_by("layer")
        assert _root_order(panel) == ["Site", "House"]

        panel.assign_layer([site], "Zinc")
        assert panel._items[id(site)].text(COL_LAYER) == "Zinc"
        assert _root_order(panel) == ["House", "Site"]

        win.viewport.history.undo()
        panel.refresh()
        assert panel._items[id(site)].text(COL_LAYER) == DEFAULT_LAYER
        assert _root_order(panel) == ["Site", "House"]
    finally:
        _close(win)


def test_the_order_menu_offers_the_two_ways_and_ticks_the_one_in_use():
    house = _group("House", "Walls")
    site = _group("Site")
    win, scene, panel = _window_with(house, site)
    try:
        _layers(scene, "Walls")
        panel.refresh()
        menu = QMenu(panel)
        panel._fill_order_actions(menu)
        acts = {a.text(): a for a in menu.actions()}
        assert set(acts) == {"Document order", "Order by layer",
                             "Order by name"}
        assert acts["Document order"].isChecked()
        assert not acts["Order by layer"].isChecked()

        acts["Order by layer"].trigger()
        assert _root_order(panel) == ["Site", "House"]
        menu2 = QMenu(panel)
        panel._fill_order_actions(menu2)
        acts2 = {a.text(): a for a in menu2.actions()}
        assert acts2["Order by layer"].isChecked()
        assert not acts2["Document order"].isChecked()
    finally:
        _close(win)


def test_the_order_button_opens_the_menu_with_the_two_ways():
    from PySide6.QtCore import QTimer
    win, _scene, panel = _window_with(_group("House"))
    try:
        texts = []

        def read():
            m = QApplication.activePopupWidget()
            if m is None:
                QTimer.singleShot(10, read)
                return
            texts.extend(a.text() for a in m.actions())
            m.close()
        QTimer.singleShot(0, read)
        panel._order_btn.click()
        assert "Document order" in texts
        assert "Order by layer" in texts
    finally:
        _close(win)


def test_the_header_menu_offers_the_order_beside_the_columns():
    from PySide6.QtCore import QTimer
    house = _group("House")
    win, _scene, panel = _window_with(house)
    try:
        texts = []

        def read():
            m = QApplication.activePopupWidget()
            if m is None:
                QTimer.singleShot(10, read)
                return
            texts.extend(a.text() for a in m.actions())
            m.close()
        QTimer.singleShot(0, read)
        panel._on_header_menu(QPoint(10, 10))
        assert "Document order" in texts
        assert "Order by layer" in texts
    finally:
        _close(win)


def test_a_choice_of_order_in_the_header_menu_closes_it():
    """The header's list stays open for the column switches; an order is a
    choice, so picking one closes it."""
    from PySide6.QtTest import QTest
    win, scene, panel = _window_with(_group("House", "Walls"))
    try:
        _layers(scene, "Walls")
        seen = []

        def choose():
            m = QApplication.activePopupWidget()
            if m is None:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(10, choose)
                return
            act = next(a for a in m.actions() if a.text() == "Order by layer")
            QTest.mouseClick(m, Qt.LeftButton, Qt.NoModifier,
                             m.actionGeometry(act).center())
            QApplication.processEvents()
            seen.append((not m.isVisible(), act.isChecked()))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, choose)
        panel._on_header_menu(QPoint(10, 10))
        assert seen == [(True, True)]
        assert panel.order_by == "layer"
    finally:
        _close(win)


def test_the_bar_has_an_order_button_with_the_drawn_icon():
    win, _scene, panel = _window_with(_group("House"))
    try:
        b = panel._order_btn
        assert b is not None and b.parent() is panel
        assert b.toolTip() == ("Order the rows: as the model holds them, "
                               "by layer or by name")
        assert b.icon().cacheKey() == node_icon("layers_order").cacheKey()
        from views.icons import tool_icon
        assert not tool_icon("layers_order").isNull()
    finally:
        _close(win)


def test_a_drop_still_finds_the_group_under_the_pointer_when_sorted():
    guest = _group("Guest", "Roof")
    host = _group("Host")
    win, scene, panel = _window_with(guest, host)
    try:
        _layers(scene, "Roof")
        panel.set_order_by("layer")
        t = panel.tree
        host_row = panel._items[id(host)]
        token = t.drop_target(t.visualItemRect(host_row).center())
        assert token == ("into", host_row)
        steps = len(win.viewport.history.undo_stack)
        t.apply_drop(token, [panel._items[id(guest)]])
        assert guest in host.children
        assert guest not in scene.groups
        assert len(win.viewport.history.undo_stack) == steps + 1
    finally:
        _close(win)


def test_restore_default_panels_puts_the_document_order_back():
    house = _group("House", "Walls")
    site = _group("Site")
    win, scene, panel = _window_with(house, site)
    try:
        _layers(scene, "Walls")
        panel.set_order_by("layer")
        assert _root_order(panel) == ["Site", "House"]

        panel.reset_columns()
        assert panel.order_by == "document"
        assert QSettings().value("browser/order") is None
        assert _root_order(panel) == ["House", "Site"]
    finally:
        _close(win)
