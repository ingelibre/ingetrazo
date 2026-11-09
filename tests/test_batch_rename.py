# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rename selected (#565, @fafecm; #87): several Browser rows renamed at
once — a name and a number (W01, W02…), find and replace, or a prefix and
a suffix — previewed before and after, in the tree's order, as one undo
step. F2 on several selected rows opens it too."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication, QDialog

from core import outliner
from core.group import Group
from core.mesh import Mesh
from views.outliner import COL_NAME, BatchRenameDialog, outliner_common_prefix


# --- the names ------------------------------------------------------------------

def test_numbered_names_are_padded_and_start_where_asked():
    assert outliner.numbered_names(3, "W") == ["W01", "W02", "W03"]
    assert outliner.numbered_names(2, "Muro ", start=9, digits=3) == \
        ["Muro 009", "Muro 010"]


def test_find_and_replace_ignores_case_unless_asked():
    names = ["Muro 1", "muro 2", "Ventana"]
    assert outliner.replaced_names(names, "MURO", "Pared") == \
        ["Pared 1", "Pared 2", "Ventana"]
    assert outliner.replaced_names(names, "Muro", "Pared",
                                   match_case=True) == \
        ["Pared 1", "muro 2", "Ventana"]
    assert outliner.replaced_names(names, "", "x") == names
    # the replacement is text, not a pattern
    assert outliner.replaced_names(["a.b"], ".", "\\\\1") == ["a\\\\1b"]


def test_prefix_and_suffix():
    assert outliner.affixed_names(["A", "B"], "P-", "-01") == \
        ["P-A-01", "P-B-01"]


def test_the_base_is_guessed_from_what_the_names_share():
    assert outliner_common_prefix(["Muro 01", "Muro 02"]) == "Muro"
    assert outliner_common_prefix(["Ventana", "Puerta"]) == ""


# --- the window -----------------------------------------------------------------

def test_the_preview_shows_before_and_after_and_ok_needs_a_change():
    dlg = BatchRenameDialog(["Muro 1", "Muro 2", "Puerta"])
    try:
        assert dlg.names() == ["W01", "W02", "W03"]     # nothing shared
        dlg.base.setText("W")
        assert dlg.preview.item(0, 0).text() == "Muro 1"
        assert dlg.preview.item(0, 1).text() == "W01"
        assert dlg.ok.isEnabled()
        dlg.mode.setCurrentIndex(dlg.REPLACE)
        dlg.find.setText("nothing like it")
        assert not dlg.ok.isEnabled()            # nothing would change
        dlg.find.setText("muro")
        dlg.replace.setText("Pared")
        assert dlg.names() == ["Pared 1", "Pared 2", "Puerta"]
        assert dlg.preview.item(2, 1).font().bold() is False
        assert dlg.preview.item(0, 1).font().bold() is True
        dlg.mode.setCurrentIndex(dlg.AFFIX)
        dlg.prefix.setText("N-")
        assert dlg.names()[2] == "N-Puerta"
    finally:
        dlg.close()


def test_an_empty_name_is_not_allowed():
    dlg = BatchRenameDialog(["A", "B"])
    try:
        dlg.mode.setCurrentIndex(dlg.REPLACE)
        dlg.find.setText("A")
        dlg.replace.setText("")
        assert not dlg.ok.isEnabled()            # «A» would be left empty
    finally:
        dlg.close()


# --- in the Browser -------------------------------------------------------------

def _quad(x):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return m


def _setup():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    groups = [Group(_quad(i * 2.0), name=n)
              for i, n in enumerate(("Puerta", "Muro", "Ventana"))]
    scene.groups[:] = groups
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel, groups


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_the_names_follow_the_trees_order_in_one_undo_step(monkeypatch):
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        seen = {}

        def fake_exec(self):
            seen["old"] = list(self.old)
            self.base.setText("W")
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(BatchRenameDialog, "exec", fake_exec)
        steps = len(win.viewport.history.undo_stack)
        # given out of order: the tree's order wins
        assert panel.ask_batch_rename([ventana, puerta, muro])
        assert seen["old"] == ["Puerta", "Muro", "Ventana"]
        assert [puerta.name, muro.name, ventana.name] == ["W01", "W02", "W03"]
        assert len(win.viewport.history.undo_stack) == steps + 1
        assert panel._items[id(muro)].text(COL_NAME) == "W02"
        win.viewport.history.undo()
        assert [puerta.name, muro.name, ventana.name] == \
            ["Puerta", "Muro", "Ventana"]
    finally:
        _close(win)


def test_cancelling_changes_nothing(monkeypatch):
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        monkeypatch.setattr(BatchRenameDialog, "exec",
                            lambda self: QDialog.DialogCode.Rejected)
        steps = len(win.viewport.history.undo_stack)
        assert not panel.ask_batch_rename([puerta, muro])
        assert puerta.name == "Puerta"
        assert len(win.viewport.history.undo_stack) == steps
    finally:
        _close(win)


def test_f2_on_several_rows_opens_it_and_on_one_renames_in_place(
        monkeypatch):
    from PySide6.QtTest import QTest
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        opened = []
        monkeypatch.setattr(panel, "ask_batch_rename",
                            lambda groups: opened.append(list(groups)))
        root = panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(root.child(0))
        root.child(0).setSelected(True)
        root.child(1).setSelected(True)
        QTest.keyClick(panel.tree, Qt.Key_F2)
        assert opened and {g.name for g in opened[0]} == {"Puerta", "Muro"}
        panel.tree.clearSelection()
        panel.tree.setCurrentItem(root.child(2))
        opened.clear()
        QTest.keyClick(panel.tree, Qt.Key_F2)
        assert not opened                          # one row: in place
        QApplication.processEvents()
    finally:
        _close(win)


def test_the_row_menu_offers_it_for_several_rows():
    from PySide6.QtCore import QTimer
    from core.i18n import tr
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        root = panel.tree.topLevelItem(0)
        texts = []

        def read():
            m = QApplication.activePopupWidget()
            if m is None:
                QTimer.singleShot(10, read)
                return
            texts.append([a.text() for a in m.actions()])
            m.close()
        item = root.child(1)
        panel.tree.setCurrentItem(item)
        QTimer.singleShot(0, read)
        panel._on_context_menu(panel.tree.visualItemRect(item).center())
        assert tr("Rename selected…") not in texts[-1]      # one row
        root.child(0).setSelected(True)
        root.child(1).setSelected(True)
        QTimer.singleShot(0, read)
        panel._on_context_menu(panel.tree.visualItemRect(item).center())
        assert tr("Rename selected…") in texts[-1]
    finally:
        _close(win)


def test_names_sharing_a_start_offer_it_as_the_base():
    dlg = BatchRenameDialog(["Muro 01", "Muro 02", "Muro 07"])
    try:
        assert dlg.base.text() == "Muro"
        assert dlg.names() == ["Muro01", "Muro02", "Muro03"]
    finally:
        dlg.close()


# --- the ✎ button in the Browser's bar ----------------------------------------

def test_the_rename_button_follows_the_selection_and_opens_the_window(
        monkeypatch):
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        b = panel._rename_btn
        root = panel.tree.topLevelItem(0)
        panel.tree.clearSelection()
        assert b.isEnabled()                 # nothing selected: every row
        opened = []
        monkeypatch.setattr(panel, "ask_batch_rename",
                            lambda groups: opened.append(list(groups)))
        root.child(0).setSelected(True)
        root.child(2).setSelected(True)
        assert b.isEnabled()
        b.click()
        assert opened and {g.name for g in opened[0]} == {"Puerta",
                                                           "Ventana"}
    finally:
        _close(win)


def test_with_one_row_the_button_renames_it_in_its_cell():
    from PySide6.QtWidgets import QAbstractItemView
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        win.show()
        QApplication.processEvents()
        root = panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(root.child(1))
        panel._rename_btn.click()
        assert panel.tree.state() == QAbstractItemView.EditingState
    finally:
        _close(win)


def test_with_nothing_selected_the_button_renames_every_row(monkeypatch):
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        opened = []
        monkeypatch.setattr(panel, "ask_batch_rename",
                            lambda groups: opened.append(list(groups)))
        panel.tree.clearSelection()
        scene.selection.clear()
        panel._rename_btn.click()
        assert [g.name for g in opened[0]] == ["Puerta", "Muro", "Ventana"]
    finally:
        _close(win)


def test_with_a_filter_it_renames_the_rows_the_filter_matches(monkeypatch):
    from PySide6.QtGui import QMatrix4x4
    win, scene, panel, (puerta, muro, ventana) = _setup()
    try:
        # «Muro» inside a group: the group shows to hold it, not renamed
        casa = Group(_quad(9.0), name="Casa")
        casa.xform = QMatrix4x4()
        casa.component = False
        otro = Group(_quad(11.0), name="Muro norte")
        casa.children = [otro]
        scene.groups.append(casa)
        scene.version += 1
        panel.refresh()
        opened = []
        monkeypatch.setattr(panel, "ask_batch_rename",
                            lambda groups: opened.append(list(groups)))
        panel.tree.clearSelection()
        scene.selection.clear()
        panel.search.setText("muro")
        panel._rename_btn.click()
        assert [g.name for g in opened[0]] == ["Muro", "Muro norte"]
    finally:
        panel.search.setText("")
        _close(win)


def test_an_empty_model_greys_the_button():
    win, scene, panel, groups = _setup()
    try:
        scene.groups[:] = []
        scene.version += 1
        panel.refresh()
        assert not panel._rename_btn.isEnabled()
    finally:
        _close(win)
