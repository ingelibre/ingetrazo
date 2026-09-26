# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's Items tab (issue #93, @pacaeiro): a sheet navigator on
top, the items below it, the selected item's properties under them — one
tab — and items the user can rename and see grouped by type."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    _app.processEvents()
    return comp, win


def _close(comp, win):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_list_and_properties_share_one_tab(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        titles = [comp._tabs.tabText(i) for i in range(comp._tabs.count())]
        assert len(titles) == 2                          # Layout, Items
        ele = comp._tabs.widget(1)
        assert ele.isAncestorOf(comp.items_list)
        assert ele.isAncestorOf(comp.props)
        assert ele.isAncestorOf(comp.nav_combo)
    finally:
        _close(comp, win)


def test_the_navigator_walks_the_sheets(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        comp._on_comp_add()
        comp._on_comp_add()
        sheets = comp._scene().compositions
        assert comp.nav_combo.count() == len(sheets) == 3
        comp._step_sheet("first")
        assert comp.comp is sheets[0] and comp.nav_combo.currentIndex() == 0
        comp._step_sheet(1)
        assert comp.comp is sheets[1]
        comp._step_sheet("last")
        assert comp.comp is sheets[2]
        comp._step_sheet(1)                              # stays at the end
        assert comp.comp is sheets[2]
        comp.nav_combo.setCurrentIndex(0)                # pick from the list
        assert comp.comp is sheets[0]
    finally:
        _close(comp, win)


def test_an_item_renamed_in_the_list_keeps_its_name_and_undoes(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        frame = comp.comp.frames[0]
        comp._refresh_items_list()
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        row.setText(0, "Planta general")                 # typed in the list
        _app.processEvents()
        assert frame.list_name == "Planta general"
        assert any(r.text(0) == "Planta general" for r in comp._item_rows())
        comp.history.undo()
        assert frame.list_name == ""
        # An empty name, or the automatic one, is no name.
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        row.setText(0, "")
        _app.processEvents()
        assert frame.list_name == ""
    finally:
        _close(comp, win)


def test_grouping_puts_the_items_in_folders(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        comp.items_group_check.setChecked(True)
        folders = [comp.items_list.topLevelItem(i)
                   for i in range(comp.items_list.topLevelItemCount())]
        assert folders and all(f.data(0, Qt.UserRole) is None
                               for f in folders)
        names = [f.text(0) for f in folders]
        assert any(n.startswith("Views") or n.startswith("Vistas")
                   for n in names)
        n_rows = len(list(comp._item_rows()))
        assert n_rows == len(comp.comp.all_items())
        comp.items_group_check.setChecked(False)
        assert all(comp.items_list.topLevelItem(i).data(0, Qt.UserRole)
                   is not None
                   for i in range(comp.items_list.topLevelItemCount()))
    finally:
        _close(comp, win)


def test_the_name_survives_the_igz(tmp_path):
    from core.composition import Composicion, MarcoVista
    c = Composicion()
    c.frames.append(MarcoVista(list_name="Alzado norte"))
    back = Composicion.from_dict(c.to_dict())
    assert back.frames[0].list_name == "Alzado norte"
