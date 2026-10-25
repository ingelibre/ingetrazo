# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Sheets tab (views/sheet_browser.py): Scenes above, the sheet
explorer below — beside the Browser in the main window and as the
composer's Sheets page, the same panels in both.

The explorer lists the sheets in their folders, each with the scenes placed
on it and a printer that says whether Print all takes it (a folder's
printer switches every sheet inside). A filter field and small icon buttons
sit above the tree; the right-click menu offers the same actions plus
rename and delete. A double-click opens a sheet; new sheets and folders go
into the selected folder; deleting a folder moves what it holds one level
up; Print all and Export all take the marked sheets, in the order shown."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import sheet_folders as sf  # noqa: E402
from core.composition import Composicion, MarcoVista  # noqa: E402
from core.sheet_folders import SheetFolder  # noqa: E402
from views.outliner import node_icon  # noqa: E402
from views.sheet_browser import (  # noqa: E402
    COL_NAME, COL_PRINT, SheetExplorer, SheetsTab,
)

_app = QApplication.instance() or QApplication([])


def _window():
    """A window whose document has Plans ▸ (G) with Details ▸ (D) inside
    it, and A at the top."""
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
    explorer = win.sheets_tray.tab.sheets
    explorer.refresh(force=True)
    return win, scene, explorer, plans, details


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
    return "some" if not item.icon(COL_PRINT).isNull() else None


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
    explorer.tree.setCurrentItem(explorer.items[id(objs[-1])])
    for obj in objs:
        explorer.items[id(obj)].setSelected(True)
    return explorer.items[id(objs[-1])]


def _click_printer(explorer, obj):
    explorer._on_item_clicked(explorer.items[id(obj)], COL_PRINT)
    QTest.qWait(20)                       # the tree is rebuilt next turn


def _sheet(scene, name):
    return next(c for c in scene.compositions if c.name == name)


def _texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# ---- Where it lives ---------------------------------------------------------

def test_the_sheets_tab_sits_beside_the_browser():
    win, *_ = _window()
    dock = win.sheets_tray
    assert dock.objectName() == "tray_sheets"
    assert dock.windowTitle() == "Sheets"
    order = win._default_tray_order()
    assert order.index(dock) == order.index(win.project_browser) + 1
    assert dock in win.tabifiedDockWidgets(win.tray)
    win.show()
    _app.processEvents()
    rows = [[tb.tabText(i) for i in range(tb.count())]
            for tb in win._dock_tab_bars()]
    row = next(r for r in rows if "Browser" in r)
    assert row[row.index("Browser") + 1] == "Sheets"
    _close(win)


def test_a_layout_saved_before_the_sheets_tab_takes_it_beside_the_browser():
    """A profile whose saved layout predates the tab (it does not name it):
    the tab lands right after the Browser the first time, not outside the
    tabs."""
    from PySide6.QtCore import QSettings
    from views.main_window import MainWindow
    win = MainWindow()
    st = QSettings()
    known = [k for k in (st.value("ui/known_trays", []) or [])
             if k != "tray_sheets"]
    st.setValue("ui/known_trays", known)
    win.removeDockWidget(win.sheets_tray)          # as Qt leaves it
    win.sheets_tray.show()
    win._place_new_trays(st)
    win.show()
    _app.processEvents()
    assert win.sheets_tray in win.tabifiedDockWidgets(win.project_browser)
    row = next([tb.tabText(i) for i in range(tb.count())]
               for tb in win._dock_tab_bars()
               if "Browser" in [tb.tabText(i) for i in range(tb.count())])
    assert row[row.index("Browser") + 1] == "Sheets"
    _close(win)


def test_scenes_above_sheets_in_the_tab_and_in_the_composer():
    from views.tray import ScenesPanel
    win, *_ = _window()
    tab = win.sheets_tray.tab
    comp = win._ensure_composer().views_panel
    for page in (tab, comp):
        assert isinstance(page, SheetsTab)
        assert isinstance(page.scenes, ScenesPanel)
        assert isinstance(page.sheets, SheetExplorer)
        split = page.splitter
        assert split.orientation() == Qt.Vertical
        assert split.widget(0).isAncestorOf(page.scenes)
        assert split.widget(1).isAncestorOf(page.sheets)
    assert tab.sheets._composer_win is None
    assert comp.sheets._composer_win is win._composer
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


def test_each_sheet_lists_the_scenes_placed_on_it():
    win, scene, explorer, *_ = _window()
    g = _sheet(scene, "G")
    g.frames = [MarcoVista(view_key="scene:Plan", scale_n=100.0),
                MarcoVista(view_key="std:top", scale_n=50.0)]
    scene.version += 1
    explorer.refresh(force=True)
    item = explorer.items[id(g)]
    assert item.isExpanded()
    names = [item.child(i).text(COL_NAME) for i in range(item.childCount())]
    assert names[0].startswith("Plan") and "1:100" in names[0]
    assert "1:50" in names[1]
    # A scene row has no printer and opens its sheet.
    assert item.child(0).icon(COL_PRINT).isNull()
    explorer.activate(item.child(0))
    assert win._composer.comp is g
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


def test_the_printer_is_one_undo_step():
    win, scene, explorer, *_ = _window()
    _click_printer(explorer, _sheet(scene, "G"))
    assert not _sheet(scene, "G").print_in_all
    assert _print_state(explorer.items[id(_sheet(scene, "G"))]) == "off"
    win.viewport.history.undo()
    assert _sheet(scene, "G").print_in_all
    _close(win)


def test_a_folder_printer_switches_every_sheet_inside_and_shows_some():
    win, scene, explorer, plans, details = _window()
    _click_printer(explorer, plans)             # all on → all off
    assert not _sheet(scene, "G").print_in_all
    assert not _sheet(scene, "D").print_in_all  # inside Details, too
    assert _print_state(explorer.items[id(plans)]) == "off"
    _click_printer(explorer, _sheet(scene, "D"))
    assert _print_state(explorer.items[id(plans)]) == "some"
    assert _print_state(explorer.items[id(details)]) == "on"
    _click_printer(explorer, plans)             # some → all on
    assert _sheet(scene, "G").print_in_all and _sheet(scene, "D").print_in_all
    win.viewport.history.undo()
    assert not _sheet(scene, "G").print_in_all
    _close(win)


def test_space_flips_the_printer_of_the_selection():
    win, scene, explorer, *_ = _window()
    _pick(explorer, _sheet(scene, "A"), _sheet(scene, "G"))
    QTest.keyClick(explorer.tree, Qt.Key_Space)
    assert not _sheet(scene, "A").print_in_all
    assert not _sheet(scene, "G").print_in_all
    assert _sheet(scene, "D").print_in_all
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


def test_renaming_a_folder_is_one_undo_step():
    win, scene, explorer, plans, _details = _window()
    explorer.items[id(plans)].setText(COL_NAME, "Floor plans")
    assert plans.name == "Floor plans"
    win.viewport.history.undo()
    assert plans.name == "Plans"
    _close(win)


# ---- Actions ----------------------------------------------------------------------

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
    assert [c.name for c in scene.compositions] == ["D", "G"]
    _close(win)


def test_a_double_click_opens_the_sheet_in_the_composer():
    win, scene, explorer, *_ = _window()
    g = _sheet(scene, "G")
    explorer.activate(explorer.items[id(g)])
    assert win._composer.comp is g
    # The composer's own copy marks the sheet open beside it.
    page = win._composer.views_panel.sheets
    page.refresh(force=True)
    assert page.items[id(g)].font(COL_NAME).bold()
    assert not page.items[id(_sheet(scene, "A"))].font(COL_NAME).bold()
    _close(win)


def test_a_double_click_on_a_folder_opens_nothing():
    win, scene, explorer, plans, _details = _window()
    explorer.activate(explorer.items[id(plans)])
    assert getattr(win, "_composer", None) is None or \
        not win._composer.isVisible()
    _close(win)


def test_the_main_window_and_the_composer_list_the_same_tree():
    win, scene, explorer, plans, _details = _window()
    page = win._ensure_composer().views_panel.sheets
    page.refresh(force=True)
    assert _rows(page) == _rows(explorer)
    _pick(explorer, plans)
    explorer.add_folder()                          # made in the main window
    page.refresh()
    assert _rows(page) == _rows(explorer)
    _close(win)


# ---- Right-click ------------------------------------------------------------------

def test_the_sheet_menu_has_the_bar_s_actions_rename_and_delete():
    win, scene, explorer, *_ = _window()
    g = _sheet(scene, "G")
    _pick(explorer, g)
    texts = _texts(explorer.build_menu(("sheet", g)))
    for want in ("Open sheet", "Rename… (F2)", "Duplicate sheet", "Delete",
                 "Exclude from Print all", "Print…", "Export PDF…",
                 "New sheet here", "New folder here"):
        assert want in texts, want
    _close(win)


def test_the_folder_menu_and_the_empty_space_menu():
    win, scene, explorer, plans, _details = _window()
    _pick(explorer, plans)
    texts = _texts(explorer.build_menu(("folder", plans)))
    for want in ("Rename… (F2)", "Exclude all from Print all", "Print…",
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


def test_print_all_prints_the_marked_sheets_each_at_its_paper(tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    win, scene, explorer, *_ = _window()
    _sheet(scene, "G").landscape = False
    _sheet(scene, "A").print_in_all = False
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "print.pdf"))
    printer.setFullPage(True)
    comp = win._ensure_composer()
    assert comp.print_sheets(sf.printed_sheets(scene), printer=printer)
    pages = _pdf_pages(tmp_path / "print.pdf")
    # D (A4 landscape), then G (A4 portrait).
    assert pages == [(842, 595), (595, 842)]
    _close(win)


def test_nothing_marked_prints_nothing(monkeypatch):
    win, scene, explorer, *_ = _window()
    for c in scene.compositions:
        c.print_in_all = False
    called = []
    comp = win._ensure_composer()
    monkeypatch.setattr(comp, "print_sheets",
                        lambda *a, **k: called.append(a))
    monkeypatch.setattr(comp, "export_all_pdf",
                        lambda *a, **k: called.append(a) or [])
    explorer.print_all()
    explorer.export_all("never.pdf")
    assert not called
    _close(win)
