# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The BIM panel's ways of reading the takeoff: grouped by the groups that
hold the objects, by IFC class or not at all; a search and a class filter
that hide rows; and a CSV of all objects or of the shown ones."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QTreeWidgetItemIterator

from core import bim
from core.bim import next_object_id, object_matches, tag_faces, tag_group
from tests.test_bim_grouped_tags import _box, _group, _nest


def _rows(tree, shown_only=False):
    flags = (QTreeWidgetItemIterator.NotHidden if shown_only
             else QTreeWidgetItemIterator.All)
    out = []
    it = QTreeWidgetItemIterator(tree, flags)
    while it.value() is not None:
        out.append(it.value())
        it += 1
    return out


def _names(tree, shown_only=False):
    return {i.text(1) for i in _rows(tree, shown_only) if i.text(1)}


_KEYS = ("bim/group_by", "bim/hidden_classes", "bim/hidden_columns")


@pytest.fixture
def panel():
    """A window with a column in «Floor 1/Core», a wall in «Walls» and two
    loose spaces — and the panel's remembered view reset around it."""
    from views.main_window import MainWindow
    for key in _KEYS:
        QSettings().remove(key)
    win = MainWindow()
    try:
        scene = win.viewport.scene
        h = win.viewport.history
        col = _group(scene, h, _box(scene))
        tag_group(col, "IfcColumn", "C-1")
        core = _nest(scene, h, [col])
        core.name = "Core"
        _nest(scene, h, [core]).name = "Floor 1"
        faces = _box(scene, 5.0)
        tag_faces(faces, "IfcWall", "Muro", next_object_id(scene))
        _group(scene, h, faces).name = "Walls"
        for x, name in ((10.0, "Kitchen"), (15.0, "Bath")):
            tag_faces(_box(scene, x), "IfcSpace", name, next_object_id(scene))
        scene.version += 1
        p = win.bim_tray.bim
        p.refresh()
        yield p
    finally:
        for key in _KEYS:
            QSettings().remove(key)
        win._saved_version = win.viewport.scene.version
        win.close()


def test_object_matches_name_class_and_wildcards():
    obj = {"class": "IfcSpace", "name": "Kitchen"}
    assert object_matches(obj, "kitch")
    assert object_matches(obj, "space")
    assert object_matches(obj, "k*n")
    assert not object_matches(obj, "k*x")
    assert not object_matches(obj, "", {"IfcWall"})
    assert object_matches(obj, "", {"IfcSpace"})


def test_by_group_is_the_default_and_keeps_the_containers(panel):
    assert panel.group_by == "group"
    assert _names(panel.tree) == {"C-1", "Muro", "Kitchen", "Bath"}
    assert panel._containers                     # the groups around them


def test_by_class_heads_each_class_with_count_and_totals(panel):
    panel.set_group_by("class")
    heads = {panel.tree.topLevelItem(i).data(0, Qt.UserRole):
             panel.tree.topLevelItem(i)
             for i in range(panel.tree.topLevelItemCount())}
    assert set(heads) == {"class:IfcColumn", "class:IfcSpace",
                          "class:IfcWall"}
    space = heads["class:IfcSpace"]
    assert space.text(0) == "Space (2)"
    assert {space.child(i).text(1) for i in range(2)} == {"Kitchen", "Bath"}
    assert space.text(3) == "12.00"                 # two closed 6 m³ boxes
    assert not panel._containers                    # no group rows


def test_no_grouping_is_a_flat_list(panel):
    panel.set_group_by("none")
    assert panel.tree.topLevelItemCount() == 4
    assert all(panel.tree.topLevelItem(i).childCount() == 0
               for i in range(4))


def test_switching_the_grouping_measures_nothing_again(panel, monkeypatch):
    calls = []
    monkeypatch.setattr(bim, "class_quantities",
                        lambda *a: calls.append(a) or (0, 0, (0, "m2")))
    monkeypatch.setattr(bim, "collect_objects",
                        lambda *a: calls.append(a) or [])
    for how in ("class", "none", "group"):
        panel.set_group_by(how)
    assert calls == []


def test_the_search_hides_rows_and_keeps_the_way_to_a_match(panel):
    panel.search.setText("muro")
    shown = _rows(panel.tree, shown_only=True)
    assert _names(panel.tree, True) == {"Muro"}
    muro = next(i for i in shown if i.text(1) == "Muro")
    assert muro.parent() is not None and not muro.parent().isHidden()
    panel.search.setText("")
    assert _names(panel.tree, True) == {"C-1", "Muro", "Kitchen", "Bath"}


def test_the_class_filter_hides_a_class_and_updates_the_totals(panel):
    panel.set_group_by("class")
    panel.set_hidden_classes({"IfcSpace", "IfcColumn"})
    assert _names(panel.tree, True) == {"Muro"}
    panel.set_hidden_classes(set())
    panel.search.setText("kit")
    space = next(i for i in _rows(panel.tree)
                 if i.data(0, Qt.UserRole) == "class:IfcSpace")
    assert space.text(0) == "Space (1)" and space.text(3) == "6.00"


def test_the_outline_column_is_the_path_of_groups(panel):
    from views.tray import BIM_COL_OUTLINE
    outline = {i.text(1): i.text(BIM_COL_OUTLINE) for i in _rows(panel.tree)
               if i.text(1)}
    assert outline == {"C-1": "Floor 1/Core", "Muro": "Walls",
                       "Kitchen": "", "Bath": ""}


def test_the_search_finds_an_object_by_its_outline(panel):
    panel.search.setText("floor 1")
    assert _names(panel.tree, True) == {"C-1"}
    panel.search.setText("*/core")
    assert _names(panel.tree, True) == {"C-1"}


def test_by_name_heads_each_name(panel):
    panel.set_group_by("name")
    assert panel.group_box.currentData() == "name"
    heads = {panel.tree.topLevelItem(i).data(0, Qt.UserRole):
             panel.tree.topLevelItem(i)
             for i in range(panel.tree.topLevelItemCount())}
    assert set(heads) == {"name:C-1", "name:Muro", "name:Kitchen",
                          "name:Bath"}
    assert heads["name:Kitchen"].text(0) == "Kitchen (1)"
    assert heads["name:Kitchen"].child(0).text(1) == "Kitchen"


def test_the_columns_switch_on_and_off_and_are_remembered(panel):
    from views.tray import BIM_COL_CLASS, BIM_COL_OUTLINE, BIM_COL_VOL
    assert not panel.tree.isColumnHidden(BIM_COL_OUTLINE)   # starts shown
    assert panel._columns_button.text() == "⋮"
    panel.set_column_shown(BIM_COL_OUTLINE, False)
    panel.set_column_shown(BIM_COL_VOL, False)
    assert panel.tree.isColumnHidden(BIM_COL_OUTLINE)
    assert panel.tree.isColumnHidden(BIM_COL_VOL)
    assert panel._columns_button.text() == "+2"
    assert panel.hidden_columns() == {BIM_COL_VOL, BIM_COL_OUTLINE}
    # A rebuild (another grouping) keeps them as chosen.
    panel.set_group_by("class")
    assert panel.tree.isColumnHidden(BIM_COL_OUTLINE)
    # The menu: Show all, one switch per optional column, Default columns.
    menu = panel._columns_menu()
    switches = [a for a in menu.actions() if a.isCheckable()]
    assert len(switches) == 3
    assert not panel.tree.isColumnHidden(BIM_COL_CLASS)       # always shown
    next(a for a in menu.actions()
         if a.text() == "Show all columns").trigger()
    assert panel.hidden_columns() == set()
    assert not panel.tree.isColumnHidden(BIM_COL_OUTLINE)


def test_export_shown_writes_only_what_the_filters_pass(panel):
    panel.set_hidden_classes({"IfcSpace"})
    panel.search.setText("c-1")
    assert [o["name"] for o in panel.shown_objects()] == ["C-1"]
    csv = bim.quantities_csv(panel._scene(), panel.shown_objects())
    assert csv.count("\n") == 2 and "C-1" in csv
    assert bim.quantities_csv(panel._scene()).count("\n") == 5
