# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ordering the Browser's rows by name, the numbers read as numbers
(«Muro 2» before «Muro 10», «Oct 26» before «Oct 28»): a way of reading
the tree, not a change to the model — a group stays inside its parent.

Every model here is generated, as in tests/test_browser_layer_order.py.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMenu

from core import outliner
from core.group import Group
from core.mesh import Mesh

_app = QApplication.instance() or QApplication([])


def _group(name) -> Group:
    return Group(Mesh(), name=name)


def _container(name, kids) -> Group:
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    return g


@pytest.fixture(autouse=True)
def _document_order():
    QSettings().remove("browser/order")
    yield
    QSettings().remove("browser/order")


def _window_with(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = groups
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version


def _root_order(panel):
    root = panel.tree.topLevelItem(0)
    return [panel._group_of(root.child(i)).name
            for i in range(root.childCount())
            if panel._group_of(root.child(i)) is not None]


def test_the_numbers_in_a_name_sort_as_numbers():
    groups = [_group(n) for n in ("Muro 10", "Oct 31", "muro 2", "Oct 26",
                                  "Oct 28", "Muro 1")]
    rows = outliner.walk_by_name(groups)
    assert [g.name for g, _p, _d in rows] == [
        "Muro 1", "muro 2", "Muro 10", "Oct 26", "Oct 28", "Oct 31"]
    # The model itself is left alone.
    assert [g.name for g in groups][0] == "Muro 10"


def test_children_sort_inside_their_parent_and_equal_names_keep_their_order():
    a, b = _group("Pieza"), _group("Pieza")
    kid2, kid10 = _group("Hijo 10"), _group("Hijo 2")
    host = _container("Casa", [kid2, kid10])
    rows = outliner.walk_by_name([b, host, a])
    assert [(g.name, d) for g, _p, d in rows] == [
        ("Casa", 0), ("Hijo 2", 1), ("Hijo 10", 1), ("Pieza", 0),
        ("Pieza", 0)]
    assert rows[3][0] is b and rows[4][0] is a          # as the model holds
    assert rows[1][1] is host                           # inside its parent


def test_ordering_by_name_reorders_the_rows_and_is_remembered():
    groups = [_group(n) for n in ("Oct 31", "Oct 26", "Oct 28")]
    win, scene, panel = _window_with(*groups)
    try:
        assert _root_order(panel) == ["Oct 31", "Oct 26", "Oct 28"]
        panel.set_order_by("name")
        assert _root_order(panel) == ["Oct 26", "Oct 28", "Oct 31"]
        assert QSettings().value("browser/order") == "name"
        assert panel._heads == {}                       # no layer headings
        panel.set_order_by("document")
        assert _root_order(panel) == ["Oct 31", "Oct 26", "Oct 28"]
        assert scene.groups == groups                   # the model untouched
    finally:
        _close(win)


def test_a_renamed_row_moves_to_its_place():
    a, b = _group("Muro 1"), _group("Muro 2")
    win, scene, panel = _window_with(a, b)
    try:
        panel.set_order_by("name")
        assert _root_order(panel) == ["Muro 1", "Muro 2"]
        assert panel.batch_rename([a], ["Muro 10"])
        panel.refresh()
        assert _root_order(panel) == ["Muro 2", "Muro 10"]
    finally:
        _close(win)


def test_the_order_menu_offers_name_and_ticks_it():
    win, _scene, panel = _window_with(_group("B"), _group("A"))
    try:
        menu = QMenu(panel)
        panel._fill_order_actions(menu)
        acts = {a.text(): a for a in menu.actions()}
        assert list(acts) == ["Document order", "Order by layer",
                              "Order by name"]
        acts["Order by name"].trigger()
        assert _root_order(panel) == ["A", "B"]
        menu2 = QMenu(panel)
        panel._fill_order_actions(menu2)
        assert {a.text(): a.isChecked() for a in menu2.actions()} == {
            "Document order": False, "Order by layer": False,
            "Order by name": True}
    finally:
        _close(win)


def test_an_unknown_order_falls_back_to_the_document():
    QSettings().setValue("browser/order", "nonsense")
    win, _scene, panel = _window_with(_group("B"), _group("A"))
    try:
        assert panel.order_by == "document"
        assert _root_order(panel) == ["B", "A"]
    finally:
        _close(win)
