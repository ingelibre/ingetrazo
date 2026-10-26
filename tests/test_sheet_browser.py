# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer's Sheets page (views/sheet_browser.py): the scenes as
a plain list above, the sheet explorer below.

The explorer lists the sheets in their folders, each with the scenes placed
on it and a printer that says whether Print all takes it (a folder's
printer switches every sheet inside). A filter field and small icon buttons
sit above the tree; the right-click menu offers the same actions plus
rename and delete. Sheets and folders drag to reorder and re-file, Alt+↑/↓
moves them; a scene dragged from the list onto a sheet is placed on it. A
double-click opens a sheet; deleting a folder moves what it holds one level
up; Print all and Export all take the marked sheets, in the order shown."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QMessageBox,
)

from core import outliner  # noqa: E402
from core import sheet_folders as sf  # noqa: E402
from core.composition import Composicion, MarcoVista  # noqa: E402
from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.sheet_folders import SheetFolder  # noqa: E402
from views.outliner import node_icon  # noqa: E402
from views.sheet_browser import (  # noqa: E402
    COL_NAME, COL_PRINT, SCENE_ROWS, TREE_MIME, SheetExplorer, SheetsTab,
)

_app = QApplication.instance() or QApplication([])

_ON, _BELOW, _ABOVE = (QAbstractItemView.OnItem,
                       QAbstractItemView.BelowItem,
                       QAbstractItemView.AboveItem)


def _window():
    """A window whose document has Plans ▸ (G) with Details ▸ (D) inside
    it, and A at the top — and the composer's Sheets page on it."""
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    plans = SheetFolder("Plans")
    details = SheetFolder("Details", parent_id=plans.id)
    scene.sheet_folders[:] = [plans, details]
    scene.compositions[:] = [
        Composicion(name="A"),
        Composicion(name="G", folder_id=plans.id),
        Composicion(name="D", folder_id=details.id)]
    sf.sync_order(scene)
    scene.version += 1
    explorer = win._ensure_composer().views_panel.sheets
    explorer.refresh(force=True)
    return win, scene, explorer, plans, details


def _sheets_model(win):
    """Scenes «Plan L1» and «North elevation»; A101 (A3) shows Plan L1 and
    a scene the model lost (Section A), A102 shows Plan L1 and the front."""
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
    scene.version += 1
    return a101, a102


def _model_window():
    from views.main_window import MainWindow
    win = MainWindow()
    a101, a102 = _sheets_model(win)
    comp = win._ensure_composer()
    page = comp.views_panel
    page.on_scene_changed()
    page.sheets.refresh(force=True)
    return win, win.viewport.scene, page, a101, a102


def _close(win):
    win._saved_version = win.viewport.scene.version
    composer = getattr(win, "_composer", None)
    if composer is not None:
        composer._dirty = False
        composer.hide()


def _print_state(item):
    key = item.icon(COL_PRINT).cacheKey()
    if key == node_icon("print").cacheKey():
        return "on"
    if key == node_icon("print_off").cacheKey():
        return "off"
    return "inherited" if not item.icon(COL_PRINT).isNull() else None


def _rows(explorer, item=None, depth=0, shown_only=False):
    """``[(depth, name, printer)]`` top to bottom."""
    out = []
    parent = item or explorer.tree.invisibleRootItem()
    for i in range(parent.childCount()):
        it = parent.child(i)
        if shown_only and it.isHidden():
            continue
        out.append((depth, it.text(COL_NAME), _print_state(it)))
        out.extend(_rows(explorer, it, depth + 1, shown_only))
    return out


def _pick(explorer, *objs):
    explorer.tree.clearSelection()
    explorer.tree.setCurrentItem(explorer.items[id(objs[-1])])
    for obj in objs:
        explorer.items[id(obj)].setSelected(True)
    return explorer.items[id(objs[-1])]


def _click_printer(explorer, obj):
    explorer._on_item_clicked(explorer.items[id(obj)], COL_PRINT)
    QTest.qWait(20)                       # the tree is rebuilt next turn


def _drag(explorer, *objs, onto=None, where=_ON):
    """Drag the rows of ``objs`` and drop them on ``onto``'s row (``None``:
    empty space) at ``where``, as the tree would."""
    rows = [explorer.items[id(o)] for o in objs]
    mime = explorer.tree.mimeData(rows)
    target = explorer.items[id(onto)] if onto is not None else None
    explorer.drop(target, where, mime)
    QTest.qWait(20)


def _drop_scenes(explorer, names, onto=None):
    from views.composer import SCENE_MIME
    mime = QMimeData()
    mime.setData(SCENE_MIME, "\n".join(names).encode("utf-8"))
    target = explorer.items[id(onto)] if onto is not None else None
    explorer.drop(target, _ON, mime)
    QTest.qWait(20)


def _sheet(scene, name):
    return next(c for c in scene.compositions if c.name == name)


def _texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _names(scene):
    return [c.name for c in scene.compositions]


# ---- Where it lives ---------------------------------------------------------

def test_the_sheets_live_only_in_the_composer():
    from views.tray import ScenesPanel
    win, *_ = _window()
    assert not hasattr(win, "sheets_tray")
    assert all(d.windowTitle() != "Sheets" for d in win._sidebar_docks())
    page = win._composer.views_panel
    assert isinstance(page, SheetsTab)
    assert isinstance(page.scenes, ScenesPanel)
    assert isinstance(page.sheets, SheetExplorer)
    split = page.splitter
    assert split.orientation() == Qt.Vertical
    assert split.widget(0).isAncestorOf(page.scenes)
    assert split.widget(1).isAncestorOf(page.sheets)
    assert page.sheets._composer_win is win._composer
    _close(win)


def test_the_scenes_are_just_a_list_with_room_for_seven():
    """Above the sheets the scenes are there to drag onto them: no buttons,
    no hint, no renaming or deleting (that is the Properties panel's), and
    room for seven before the list scrolls."""
    from PySide6.QtWidgets import QLabel, QPushButton
    win, scene, page, *_ = _model_window()
    panel = page.scenes
    assert not panel.findChildren(QPushButton)
    assert not panel.findChildren(QLabel)
    item = panel.list.item(0)
    assert item.text() == "Plan L1"
    assert not item.flags() & Qt.ItemIsEditable
    panel.list.setCurrentItem(item)
    QTest.keyClick(panel.list, Qt.Key_Delete)
    assert [v.name for v in scene.saved_views] == ["Plan L1",
                                                   "North elevation"]
    lst = panel.list
    row = max(lst.fontMetrics().height(), lst.iconSize().height()) + 6
    assert lst.maximumHeight() == SCENE_ROWS * row + 2 * lst.frameWidth()
    assert SCENE_ROWS == 7
    assert win.tray.scenes.findChildren(QPushButton)   # Properties: all
    _close(win)


def test_the_bar_is_a_filter_and_small_icons_with_tips():
    win, scene, explorer, *_ = _window()
    assert explorer.search.placeholderText()
    for btn in (explorer.add_sheet_btn, explorer.add_folder_btn,
                explorer.rename_btn, explorer.delete_btn, explorer.print_btn,
                explorer.export_btn):
        assert btn.text() == "" and not btn.icon().isNull()
        assert btn.toolTip()
    _close(win)


# ---- The tree -------------------------------------------------------------------

def test_the_tree_shows_folders_sheets_and_their_printers():
    win, scene, explorer, *_ = _window()
    assert explorer.tree.columnCount() == 2
    assert explorer.tree.headerItem().text(COL_NAME) == "Name"
    assert not explorer.tree.headerItem().icon(COL_PRINT).isNull()
    _sheet(scene, "A").print_in_all = False
    scene.version += 1
    explorer.refresh(force=True)
    assert _rows(explorer) == [
        (0, "Plans", "on"), (1, "Details", "on"), (2, "D", "on"),
        (1, "G", "on"), (0, "A", "off")]
    _close(win)


def test_each_sheet_lists_its_scenes_and_flags_a_lost_one():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    item = explorer.items[id(a101)]
    assert item.isExpanded()
    assert [item.child(i).text(COL_NAME) for i in range(item.childCount())] \
        == ["Plan L1 · 1:100", "Section A · 1:50"]
    lost = item.child(1)
    assert "Section A" in lost.toolTip(COL_NAME)
    assert lost.icon(COL_NAME).cacheKey() == node_icon("warning").cacheKey()
    assert item.child(0).icon(COL_PRINT).isNull()      # no printer of its own
    _close(win)


def test_deleting_a_scene_flags_its_frames_instead_of_breaking():
    win, scene, page, a101, _a102 = _model_window()
    explorer = page.sheets
    first = explorer.items[id(a101.frames[0])]
    assert first.icon(COL_NAME).cacheKey() == node_icon("scene").cacheKey()
    del scene.saved_views[0]                           # «Plan L1» goes
    explorer.refresh(force=True)
    first = explorer.items[id(a101.frames[0])]
    assert first.icon(COL_NAME).cacheKey() == node_icon("warning").cacheKey()
    assert a101.frames[0].view_key == "scene:Plan L1"  # untouched
    _close(win)


def test_a_scene_marks_its_views_and_a_view_marks_its_scene():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    page.scenes.list.setCurrentRow(0)                  # «Plan L1»
    marked = explorer.related()
    assert sorted(it.text(COL_NAME) for it in marked) == [
        "Plan L1 · 1:100", "Plan L1 · 1:200"]
    assert all(it.data(COL_NAME, Qt.UserRole + 1) for it in marked)
    explorer.tree.setCurrentItem(explorer.items[id(a102.frames[0])])
    assert page.scenes.list.item(0).data(Qt.UserRole + 1)
    assert not page.scenes.list.item(1).data(Qt.UserRole + 1)
    explorer.tree.setCurrentItem(explorer.items[id(a101.frames[1])])
    assert not page.scenes.list.item(0).data(Qt.UserRole + 1)  # lost: none
    page.scenes.list.setCurrentRow(1)                  # on no sheet
    assert explorer.related() == []
    assert not marked[0].data(COL_NAME, Qt.UserRole + 1)       # cleared
    _close(win)


def test_a_folder_opens_the_way_it_was_left():
    win, scene, explorer, plans, details = _window()
    details.expanded = False
    explorer.refresh(force=True)
    assert explorer.items[id(plans)].isExpanded()
    assert not explorer.items[id(details)].isExpanded()
    explorer.items[id(details)].setExpanded(True)       # opened by hand
    assert details.expanded
    _close(win)


def test_a_sheet_added_in_the_composer_reaches_the_explorer():
    win, scene, page, *_ = _model_window()
    explorer = page.sheets
    win._composer.show()
    win._composer._show_page("views")              # on screen: it follows
    _app.processEvents()
    scene.compositions.append(Composicion(name="A103 Details"))
    win._refresh_sheet_tabs()          # what the composer calls on add
    assert [r[1] for r in _rows(explorer) if r[0] == 0][-1] == "A103 Details"
    scene.compositions[2].name = "A103 Joints"
    explorer._poll.timeout.emit()      # the composer's in-place edits
    assert explorer.items[id(scene.compositions[2])].text(COL_NAME) == \
        "A103 Joints"
    _close(win)


def test_the_filter_keeps_matches_with_their_folders():
    win, scene, explorer, *_ = _window()
    explorer.search.setText("d")              # Details and D
    assert _rows(explorer, shown_only=True) == [
        (0, "Plans", "on"), (1, "Details", "on"), (2, "D", "on")]
    explorer.search.setText("plans")          # a folder: all of it shows
    assert [r[1] for r in _rows(explorer, shown_only=True)] == [
        "Plans", "Details", "D", "G"]
    explorer.search.setText("")
    assert len(_rows(explorer, shown_only=True)) == 5
    _close(win)


# ---- The printer -------------------------------------------------------------------

def test_the_printer_is_one_undo_step():
    win, scene, explorer, *_ = _window()
    _click_printer(explorer, _sheet(scene, "G"))
    assert not _sheet(scene, "G").print_in_all
    assert _print_state(explorer.items[id(_sheet(scene, "G"))]) == "off"
    win.viewport.history.undo()
    assert _sheet(scene, "G").print_in_all
    _close(win)


def test_a_folder_keeps_its_own_printer_whatever_moves_in_or_out():
    """A folder's printer is its own, on by default: emptying the folder or
    filling it changes nothing (it read «off» once all its sheets left)."""
    win, scene, explorer, plans, details = _window()
    assert _print_state(explorer.items[id(plans)]) == "on"
    _drag(explorer, _sheet(scene, "G"), _sheet(scene, "D"), onto=None)
    _drag(explorer, details, onto=None)
    assert sf.sheets_in(scene, plans.id) == [] and \
        sf.subfolders(scene, plans.id) == []
    assert plans.print_in_all
    assert _print_state(explorer.items[id(plans)]) == "on"
    _click_printer(explorer, _sheet(scene, "A"))     # a sheet switched off…
    _drag(explorer, _sheet(scene, "A"), onto=plans)  # …moved in
    assert _print_state(explorer.items[id(plans)]) == "on"
    _close(win)


def test_a_folder_switched_off_leaves_out_what_it_holds():
    win, scene, explorer, plans, details = _window()
    _click_printer(explorer, plans)
    assert not plans.print_in_all
    # The sheets keep their own switches; they are left out, shown faded.
    assert _sheet(scene, "G").print_in_all and _sheet(scene, "D").print_in_all
    assert _print_state(explorer.items[id(plans)]) == "off"
    for obj in (details, _sheet(scene, "G"), _sheet(scene, "D")):
        assert _print_state(explorer.items[id(obj)]) == "inherited"
    assert "Plans" in explorer.items[id(_sheet(scene, "D"))].toolTip(
        COL_PRINT)
    assert [c.name for c in sf.printed_sheets(scene)] == ["A"]
    # A click on a sheet left out by its folder says so and changes nothing.
    _click_printer(explorer, _sheet(scene, "G"))
    assert _sheet(scene, "G").print_in_all
    _click_printer(explorer, plans)                   # back on: all of it
    assert [c.name for c in sf.printed_sheets(scene)] == ["D", "G", "A"]
    win.viewport.history.undo()
    assert not plans.print_in_all
    _close(win)


def test_a_sheet_s_own_switch_survives_its_folder_switching():
    win, scene, explorer, plans, _details = _window()
    _click_printer(explorer, _sheet(scene, "G"))      # G off itself
    _click_printer(explorer, plans)                   # the folder off …
    _click_printer(explorer, plans)                   # … and on again
    assert not _sheet(scene, "G").print_in_all        # G kept its own
    assert _print_state(explorer.items[id(_sheet(scene, "G"))]) == "off"
    _close(win)


def test_space_flips_the_printer_of_the_selection():
    win, scene, explorer, plans, details = _window()
    _pick(explorer, _sheet(scene, "A"), _sheet(scene, "G"), details)
    QTest.keyClick(explorer.tree, Qt.Key_Space)
    assert not _sheet(scene, "A").print_in_all
    assert not _sheet(scene, "G").print_in_all
    assert not details.print_in_all                   # the folder's own
    assert _sheet(scene, "D").print_in_all
    _close(win)


# ---- Renaming ----------------------------------------------------------------------

def test_renaming_a_folder_is_one_undo_step():
    win, scene, explorer, plans, _details = _window()
    explorer.items[id(plans)].setText(COL_NAME, "Floor plans")
    assert plans.name == "Floor plans"
    win.viewport.history.undo()
    assert plans.name == "Plans"
    _close(win)


def test_renaming_a_sheet_and_a_rename_to_the_same_name_does_nothing():
    win, scene, page, a101, _a102 = _model_window()
    explorer = page.sheets
    explorer.items[id(a101)].setText(COL_NAME, "A-101")
    assert a101.name == "A-101"
    QTest.qWait(20)
    assert explorer.items[id(a101)].text(COL_NAME) == "A-101"
    assert win._composer.comp_combo.findText("A-101") >= 0
    version = scene.version
    explorer.items[id(a101)].setText(COL_NAME, "A-101")  # to itself
    assert scene.version == version
    _close(win)


# ---- Opening -------------------------------------------------------------------------

def test_a_double_click_opens_the_sheet_and_marks_it():
    win, scene, explorer, *_ = _window()
    g = _sheet(scene, "G")
    explorer.activate(explorer.items[id(g)])
    assert win._composer.comp is g
    assert explorer.items[id(g)].font(COL_NAME).bold()
    assert not explorer.items[id(_sheet(scene, "A"))].font(COL_NAME).bold()
    _close(win)


def test_a_scene_row_opens_its_sheet_and_a_folder_opens_nothing():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    explorer.activate(explorer.items[id(a102.frames[1])])
    assert win._composer.comp is a102
    plans = SheetFolder("Plans")
    scene.sheet_folders.append(plans)
    explorer.refresh(force=True)
    explorer.activate(explorer.items[id(plans)])
    assert win._composer.comp is a102
    _close(win)


# ---- New, delete -------------------------------------------------------------------

def test_a_new_folder_goes_into_the_selected_one():
    win, scene, explorer, plans, _details = _window()
    _pick(explorer, plans)
    explorer.add_folder()
    new = scene.sheet_folders[-1]
    assert new.parent_id == plans.id and new.name == "New folder"
    _pick(explorer, plans)
    explorer.add_folder()
    assert scene.sheet_folders[-1].name == "New folder 2"
    win.viewport.history.undo()
    win.viewport.history.undo()
    assert [f.name for f in scene.sheet_folders] == ["Plans", "Details"]
    _close(win)


def test_a_new_folder_beside_a_selected_sheet_and_at_the_top():
    win, scene, explorer, plans, details = _window()
    _pick(explorer, _sheet(scene, "D"))
    explorer.add_folder()
    assert scene.sheet_folders[-1].parent_id == details.id
    explorer.tree.clearSelection()
    explorer.add_folder()
    assert scene.sheet_folders[-1].parent_id is None
    _close(win)


def test_a_new_sheet_goes_into_the_selected_folder_and_opens():
    win, scene, explorer, _plans, details = _window()
    _pick(explorer, details)
    explorer.add_sheet()
    assert len(scene.compositions) == 4
    new = win._composer.comp                      # opened in the composer
    assert new.folder_id == details.id
    assert scene.compositions.index(new) == 1
    assert scene.compositions == sf.tree_order(scene)
    _close(win)


def test_deleting_a_folder_moves_its_sheets_up():
    win, scene, explorer, plans, details = _window()
    _pick(explorer, plans)
    explorer.delete_selected()
    assert plans not in scene.sheet_folders
    assert details.parent_id is None
    assert _sheet(scene, "G").folder_id is None
    assert len(scene.compositions) == 3
    assert _rows(explorer)[0] == (0, "Details", "on")
    _close(win)


def test_delete_takes_a_sheet_after_asking(monkeypatch):
    win, scene, explorer, *_ = _window()
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    _pick(explorer, _sheet(scene, "A"))
    QTest.keyClick(explorer.tree, Qt.Key_Delete)
    assert _names(scene) == ["D", "G"]
    _close(win)


def test_undoing_a_folder_never_brings_back_or_drops_a_sheet(monkeypatch):
    """The composer makes and deletes sheets outside the tree's undo: a
    sheet deleted there came back on undoing a folder, and one made there
    vanished — while the composer still showed it."""
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    win, scene, explorer, plans, _details = _window()
    explorer.tree.clearSelection()
    explorer.add_folder()                          # an undoable step
    folder = scene.sheet_folders[-1]
    _pick(explorer, folder)
    explorer.add_sheet()                           # the composer's own
    new = win._composer.comp
    _pick(explorer, _sheet(scene, "A"))
    explorer.delete_selected()                     # the composer's own
    win.viewport.history.undo()                    # the folder goes
    assert new in scene.compositions and new.folder_id is None
    assert "A" not in _names(scene)
    assert win._composer.comp in scene.compositions
    explorer.refresh(force=True)
    assert id(new) in explorer.items
    _close(win)


# ---- Moving: drag & drop and Alt+↑/↓ ----------------------------------------------

def test_a_sheet_dropped_on_a_folder_goes_into_it():
    win, scene, explorer, plans, details = _window()
    _drag(explorer, _sheet(scene, "A"), onto=details)
    assert _sheet(scene, "A").folder_id == details.id
    assert _names(scene) == ["D", "A", "G"]           # the tabs follow
    assert [win._composer.comp_combo.itemText(i)
            for i in range(win._composer.comp_combo.count())] == \
        ["D", "A", "G"]
    win.viewport.history.undo()
    assert _sheet(scene, "A").folder_id is None
    assert _names(scene) == ["D", "G", "A"]
    _close(win)


def test_a_sheet_dropped_above_or_below_another_takes_that_place():
    win, scene, explorer, plans, details = _window()
    _drag(explorer, _sheet(scene, "A"), onto=_sheet(scene, "G"),
          where=_ABOVE)
    assert _sheet(scene, "A").folder_id == plans.id
    assert _names(scene) == ["D", "A", "G"]
    _drag(explorer, _sheet(scene, "A"), onto=_sheet(scene, "G"),
          where=_BELOW)
    assert _names(scene) == ["D", "G", "A"]
    _close(win)


def test_a_folder_moves_with_everything_inside_but_never_into_itself():
    win, scene, explorer, plans, details = _window()
    _drag(explorer, details, onto=None)               # empty space: the top
    assert details.parent_id is None
    assert _names(scene) == ["G", "A", "D"]             # at the very end
    _drag(explorer, plans, onto=details)              # Plans into Details
    assert plans.parent_id == details.id
    _drag(explorer, details, onto=plans)              # into its own child
    assert details.parent_id is None and plans.parent_id == details.id
    _drag(explorer, details, onto=details)            # into itself
    assert details.parent_id is None
    _close(win)


def test_a_folder_drops_below_a_sheet_and_alt_moves_it_past_sheets():
    win, scene, explorer, plans, details = _window()
    a = _sheet(scene, "A")
    _drag(explorer, plans, onto=a, where=_BELOW)        # under the sheet
    assert [r[1] for r in _rows(explorer) if r[0] == 0] == ["A", "Plans"]
    assert _names(scene) == ["A", "D", "G"]             # the tabs follow
    explorer.tree.setCurrentItem(explorer.items[id(plans)])
    QTest.keyClick(explorer.tree, Qt.Key_Up, Qt.AltModifier)
    assert [r[1] for r in _rows(explorer) if r[0] == 0] == ["Plans", "A"]
    explorer.tree.setCurrentItem(explorer.items[id(_sheet(scene, "G"))])
    QTest.keyClick(explorer.tree, Qt.Key_Up, Qt.AltModifier)  # G above Details
    assert [r[1] for r in _rows(explorer) if r[0] == 1] == ["G", "Details"]
    _close(win)


def test_pdfs_are_offered_under_the_project_s_name(tmp_path, monkeypatch):
    from views.filedialogs import file_dialogs
    win, scene, explorer, *_ = _window()
    asked = []
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda parent, title, name, *a, **k:
                        asked.append(name) or ("", ""))
    explorer.export_all()                            # never saved: generic
    assert asked[-1] == "sheets.pdf"
    win._current_path = tmp_path / "Casa.igz"
    explorer.export_all()
    explorer.export_sheets([_sheet(scene, "A")])
    win._composer._on_export_all()
    win._composer._on_export_pdf()
    assert asked[1:] == [str(tmp_path / "Casa.pdf")] * 4
    win._current_path = None
    _close(win)


def test_a_scene_row_dropped_on_means_its_sheet():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    folder = SheetFolder("Elevations")
    scene.sheet_folders.append(folder)
    explorer.refresh(force=True)
    _drag(explorer, folder, onto=a101.frames[0])      # beside A101
    assert folder.parent_id is None
    _close(win)


def test_alt_arrows_move_a_sheet_among_its_neighbours():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    explorer.tree.setCurrentItem(explorer.items[id(a101)])
    QTest.keyClick(explorer.tree, Qt.Key_Down, Qt.AltModifier)
    assert scene.compositions == [a102, a101]
    assert explorer.current_sheet() is a101
    win.viewport.history.undo()
    assert scene.compositions == [a101, a102]
    _close(win)


# ---- Scenes onto sheets ---------------------------------------------------------------

def test_the_scene_list_drags_scenes_by_name():
    from views.composer import SCENE_MIME
    win, scene, page, *_ = _model_window()
    lst = page.scenes.list
    data = lst.mimeData([lst.item(0), lst.item(1)])
    assert bytes(data.data(SCENE_MIME)).decode() == \
        "Plan L1\nNorth elevation"
    _close(win)


def test_a_scene_dropped_on_a_sheet_is_placed_in_a_free_spot():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    north = scene.saved_views[1]                      # on no sheet yet
    assert outliner.unplaced_scenes(scene) == [north]
    frames0 = list(a102.frames)
    _drop_scenes(explorer, ["North elevation"], onto=a102)
    new = [f for f in a102.frames if f not in frames0]
    assert len(new) == 1 and new[0].view_key == "scene:North elevation"
    for other in frames0:                             # nothing covered
        f = new[0]
        assert (f.x_mm >= other.x_mm + other.w_mm
                or f.x_mm + f.w_mm <= other.x_mm
                or f.y_mm >= other.y_mm + other.h_mm
                or f.y_mm + f.h_mm <= other.y_mm)
    assert outliner.unplaced_scenes(scene) == []
    win._composer.history.undo()                      # the composer's undo
    assert new[0] not in a102.frames
    _close(win)


def test_a_scene_dropped_on_a_scene_row_goes_onto_its_sheet():
    win, scene, page, a101, a102 = _model_window()
    _drop_scenes(page.sheets, ["North elevation"], onto=a101.frames[0])
    assert any(f.view_key == "scene:North elevation" for f in a101.frames)
    _close(win)


def test_a_scene_dropped_on_no_sheet_makes_one_in_one_undo_step():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    _drop_scenes(explorer, ["North elevation"], onto=None)
    new = scene.compositions[-1]
    assert new.name == "North elevation" and len(new.frames) == 1
    win.viewport.history.undo()                       # sheet and view go
    assert new not in scene.compositions
    _close(win)


def test_a_scene_dropped_on_a_folder_makes_a_sheet_in_it():
    win, scene, explorer, plans, _details = _window()
    from core.saved_views import SavedView
    scene.saved_views.append(SavedView.capture(
        "Plan", scene, win.viewport.camera))
    _drop_scenes(explorer, ["Plan"], onto=plans)
    new = next(c for c in scene.compositions if c.name == "Plan")
    assert new.folder_id == plans.id and len(new.frames) == 1
    _close(win)


def test_double_click_on_a_scene_places_it_on_the_open_sheet():
    win, scene, page, a101, a102 = _model_window()
    win._composer.show_sheet(1)                       # A102 open
    frames0 = list(a102.frames)
    page.scenes._on_activate(page.scenes.list.item(1))   # «North elevation»
    new = [f for f in a102.frames if f not in frames0]
    assert len(new) == 1
    for other in frames0:
        f = new[0]
        assert (f.x_mm >= other.x_mm + other.w_mm
                or f.x_mm + f.w_mm <= other.x_mm
                or f.y_mm >= other.y_mm + other.h_mm
                or f.y_mm + f.h_mm <= other.y_mm)
    _close(win)


def test_the_place_a_scene_menu_puts_it_on_that_sheet():
    win, scene, page, a101, a102 = _model_window()
    explorer = page.sheets
    _pick(explorer, a101)
    menu = explorer.build_menu(("sheet", a101))
    sub = next(a.menu() for a in menu.actions()
               if a.text() == "Place a scene here")
    assert [a.text() for a in sub.actions()][0] == "North elevation"  # free
    sub.actions()[0].trigger()
    assert any(f.view_key == "scene:North elevation" for f in a101.frames)
    _close(win)


def test_the_scene_pictures_do_not_rebuild_the_list_nor_touch_the_document():
    """A new icon is an item change to Qt: it used to go through the rename
    path, touch the document and rebuild the list, which queued the
    pictures again — the scenes flickered and the file read as modified."""
    from PySide6.QtGui import QIcon, QPixmap
    win, scene, page, *_ = _model_window()
    pm = QPixmap(8, 8)
    pm.fill(Qt.red)
    panel = page.scenes
    panel._icon_for = lambda name: QIcon(pm)
    win._composer.show()
    win._composer._show_page("views")
    fills = []
    real = panel.refresh
    panel.refresh = lambda: (fills.append(1), real())
    panel._shape = None                               # as if new scenes
    panel.refresh()                                   # one fill, pictures queued
    version = scene.version
    for _ in range(40):
        _app.processEvents()
    assert len(fills) == 1
    assert scene.version == version                   # nothing «modified»
    assert not panel.list.item(0).icon().isNull()
    _close(win)


def test_creating_a_plan_shows_its_scene_in_the_composer():
    def box(name, at):
        mesh = Mesh()
        x, y = at
        mesh.add_face([__import__("PySide6.QtGui", fromlist=["QVector3D"])
                       .QVector3D(x + dx, y + dy, 0.0)
                       for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))])
        return Group(mesh, name=name)
    win, scene, page, *_ = _model_window()
    level1, level2 = box("Level 1", (0, 0)), box("Level 2", (3, 0))
    scene.groups[:] = [level1, level2]
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    panel.create_plan(level2, 1.2, sheet=False)
    current = page.scenes.list.currentItem()          # its scene, marked
    assert current is not None and current.text() == "Plan Level 2"
    _close(win)


def test_the_icon_buttons_work_when_clicked(monkeypatch, tmp_path):
    """Clicked for real: ``clicked`` hands its ``checked`` flag over, which
    the slots took for their argument — a new sheet landed in a folder
    called False and never showed, Export all got the path False."""
    from views.filedialogs import file_dialogs
    win, scene, explorer, plans, details = _window()
    _pick(explorer, details)
    explorer.add_sheet_btn.click()
    new = win._composer.comp
    assert new.folder_id == details.id and id(new) in explorer.items
    _pick(explorer, plans)
    explorer.add_folder_btn.click()
    folder = scene.sheet_folders[-1]
    assert folder.parent_id == plans.id and id(folder) in explorer.items
    _pick(explorer, plans)
    explorer.rename_btn.click()                       # no error
    explorer.tree.closePersistentEditor(explorer.items[id(plans)])
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "b.pdf"), ""))
    explorer.export_btn.click()
    assert (tmp_path / "b.pdf").is_file()
    _pick(explorer, folder)
    explorer.delete_btn.click()
    assert folder not in scene.sheet_folders
    _close(win)


def test_a_sheet_naming_an_unknown_folder_shows_at_the_top():
    win, scene, explorer, *_ = _window()
    lost = Composicion(name="Lost", folder_id="no-such-folder")
    scene.compositions.append(lost)
    explorer.refresh(force=True)
    assert id(lost) in explorer.items
    assert explorer.items[id(lost)].parent() is None
    assert lost in sf.tree_order(scene)
    _close(win)


# ---- Right-click ------------------------------------------------------------------

def test_the_sheet_menu_has_the_bar_s_actions_rename_and_delete():
    win, scene, explorer, *_ = _window()
    g = _sheet(scene, "G")
    _pick(explorer, g)
    texts = _texts(explorer.build_menu(("sheet", g)))
    for want in ("Open sheet", "Rename… (F2)", "Duplicate sheet", "Delete",
                 "Exclude from Print all", "Print…", "Export PDF…",
                 "Move up (Alt+↑)", "Move down (Alt+↓)",
                 "New sheet here", "New folder here"):
        assert want in texts, want
    _close(win)


def test_the_folder_menu_and_the_empty_space_menu():
    win, scene, explorer, plans, _details = _window()
    _pick(explorer, plans)
    texts = _texts(explorer.build_menu(("folder", plans)))
    for want in ("Rename… (F2)", "Exclude from Print all", "Print…",
                 "Export PDF…", "New sheet here", "New folder here"):
        assert want in texts, want
    assert any(t.startswith("Delete folder") for t in texts)
    texts = _texts(explorer.build_menu(None))
    for want in ("New sheet", "New folder", "Print all…",
                 "Export all (PDF)…"):
        assert want in texts, want
    _close(win)


def test_the_menu_s_delete_takes_the_folder():
    win, scene, explorer, plans, _details = _window()
    _pick(explorer, plans)
    menu = explorer.build_menu(("folder", plans))
    next(a for a in menu.actions()
         if a.text().startswith("Delete folder")).trigger()
    assert plans not in scene.sheet_folders
    _close(win)


# ---- Print all / Export all ------------------------------------------------------

def _pdf_pages(path) -> list:
    """``[(width, height)]`` in points of each page of a PDF."""
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    doc.load(str(path))
    return [(round(doc.pagePointSize(i).width()),
             round(doc.pagePointSize(i).height()))
            for i in range(doc.pageCount())]


def test_export_all_takes_the_marked_sheets_in_tree_order(tmp_path):
    win, scene, explorer, *_ = _window()
    _sheet(scene, "D").paper = "A3"
    _sheet(scene, "G").print_in_all = False
    explorer.export_all(str(tmp_path / "all.pdf"))
    pages = _pdf_pages(tmp_path / "all.pdf")
    # D (A3 landscape), then A (A4 landscape); G is not marked.
    assert pages == [(1191, 842), (842, 595)]
    _close(win)


def test_the_composer_s_own_export_all_takes_the_same_sheets(tmp_path,
                                                             monkeypatch):
    from views.filedialogs import file_dialogs
    win, scene, explorer, *_ = _window()
    _sheet(scene, "G").print_in_all = False
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "c.pdf"), ""))
    win._composer._on_export_all()
    assert len(_pdf_pages(tmp_path / "c.pdf")) == 2      # D and A
    _close(win)


def test_the_selected_sheets_export_to_one_pdf(tmp_path):
    win, scene, page, a101, a102 = _model_window()
    asked = []
    win._composer.export_all_pdf = lambda path, chosen=None: asked.append(
        (path, chosen)) or []
    page.sheets.export_sheets([a102], path=str(tmp_path / "out.pdf"))
    assert asked == [(str(tmp_path / "out.pdf"), [a102])]
    _close(win)


def test_print_all_prints_the_marked_sheets_each_at_its_paper(tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    win, scene, explorer, *_ = _window()
    _sheet(scene, "G").landscape = False
    _sheet(scene, "A").print_in_all = False
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "print.pdf"))
    printer.setFullPage(True)
    assert win._composer.print_sheets(sf.printed_sheets(scene),
                                      printer=printer)
    pages = _pdf_pages(tmp_path / "print.pdf")
    # D (A4 landscape), then G (A4 portrait).
    assert pages == [(842, 595), (595, 842)]
    _close(win)


def test_nothing_marked_prints_nothing(monkeypatch):
    win, scene, explorer, *_ = _window()
    for c in scene.compositions:
        c.print_in_all = False
    called = []
    comp = win._composer
    monkeypatch.setattr(comp, "print_sheets",
                        lambda *a, **k: called.append(a))
    monkeypatch.setattr(comp, "export_all_pdf",
                        lambda *a, **k: called.append(a) or [])
    explorer.print_all()
    explorer.export_all("never.pdf")
    comp._on_export_all()
    assert not called
    _close(win)
