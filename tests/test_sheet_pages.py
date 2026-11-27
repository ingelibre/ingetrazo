# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Reordering sheets by dragging their tabs, and every sheet as a page, as
a PDF reader lists them (Marco, 19-11: «me gustaria poder cambiar el orden
arrastrando una pestaña … como un gestor de laminas … que se muestren en
miniatura»; 20-11: «láminas deberían ser parecido a las vistas de
miniatura de ciertos programas conocidos de pdf, de allí podría mover el
orden, copiar, pegar, eliminar»). The pages are the Sheets tab's Pages
view — only the pages, no scenes under them; the folders and the Print
switch are its List view."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])


def _no_render(self, frame):
    raise AssertionError("the Sheets panel must never render a frame")


@pytest.fixture
def composer(monkeypatch):
    """The composer open on sheet A of a document with sheets A B C D; no
    frame can render (a render would fail the test)."""
    from core.composition import Composicion
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", _no_render)
    monkeypatch.setattr(ComposerWindow, "compute_hlr", _no_render)
    monkeypatch.setattr(ComposerWindow, "_auto_render_stale",
                        lambda self: None)
    from PySide6.QtCore import QSettings
    from views.sheet_browser import SheetExplorer
    # The Pages view, whatever an earlier test left chosen.
    QSettings().setValue(SheetExplorer.THUMBS_KEY, True)
    win = MainWindow()
    for name in "ABCD":
        win.viewport.scene.compositions.append(Composicion(name=name))
    win._update_title()
    win._sheet_tabs.click(1)
    comp = win._composer
    comp.resize(1400, 900)
    _spin()
    yield comp
    from views.sheet_browser import SheetExplorer
    SheetExplorer.clipboard = []
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _spin(ms: int = 0) -> None:
    end = time.monotonic() + ms / 1000.0
    while True:
        _app.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)
    _app.processEvents()


def _order(comp) -> list:
    return [c.name for c in comp._scene().compositions]


def _explorer(comp):
    return comp.views_panel.sheets


def _sheet_items(comp) -> list:
    """The explorer's sheet rows, top to bottom."""
    out = []
    tree = _explorer(comp).tree

    def walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            d = child.data(0, Qt.UserRole)
            if d and d[0] == "sheet":
                out.append(child)
            walk(child)
    walk(tree.invisibleRootItem())
    return out


def _rows(comp) -> list:
    _explorer(comp).refresh()
    return [it.text(0) for it in _sheet_items(comp)]


# ---- the strip ------------------------------------------------------------------
def _drag_tab(tabs, src: int, to_x: int) -> None:
    """Press displayed tab ``src``, drag it to ``to_x`` and drop it."""
    start = tabs.tabRect(src).center()
    QTest.mousePress(tabs, Qt.LeftButton, Qt.NoModifier, start)
    x = start.x()
    step = 6 if to_x > x else -6
    while (to_x - x) * step > 0:
        x += step
        QTest.mouseMove(tabs, QPoint(x, start.y()))
        _app.processEvents()
    QTest.mouseRelease(tabs, Qt.LeftButton, Qt.NoModifier,
                       QPoint(to_x, start.y()))
    _spin()


def test_dragging_a_sheet_tab_reorders_the_sheets_with_undo(composer):
    tabs = composer._sheet_tabs
    tabs.show()
    _spin()
    scene = composer._scene()
    version = scene.version
    before_win = composer._window._saved_version
    # «A» (tab 1) dragged past «C»: B C A D. Dropped on C's middle: 2 px
    # inside C's right edge, A's own right edge lands on D's middle, and
    # whether Qt slides A past D too then depends on the font's tab widths
    # (it did on the Linux CI runner).
    _drag_tab(tabs, 1, tabs.tabRect(3).center().x())
    assert _order(composer) == ["B", "C", "A", "D"]
    assert tabs.names() == ["Model", "B", "C", "A", "D"]
    assert composer.comp.name == "A"                  # still the sheet open
    assert tabs.current() == 2
    assert scene.version > version                    # the file is modified
    assert scene.version != before_win
    assert _rows(composer) == ["B", "C", "A", "D"]    # the panel follows
    composer.history.undo()
    _spin()
    assert _order(composer) == ["A", "B", "C", "D"]
    assert tabs.names() == ["Model", "A", "B", "C", "D"]
    assert _rows(composer) == ["A", "B", "C", "D"]
    composer.history.redo()
    _spin()
    assert _order(composer) == ["B", "C", "A", "D"]
    assert tabs.names() == ["Model", "B", "C", "A", "D"]


def test_model_and_plus_stay_put(composer):
    tabs = composer._sheet_tabs
    tabs.show()
    _spin()
    # «D» dragged far past «Model»: it stops right after it.
    _drag_tab(tabs, 4, -200)
    assert _order(composer) == ["D", "A", "B", "C"]
    assert tabs.names()[0] == "Model"
    assert tabs.tabText(0) == "Model"
    # …and «A» past «+»: it stops right before it.
    _drag_tab(tabs, 2, tabs.width() + 400)
    assert _order(composer) == ["D", "B", "C", "A"]
    assert tabs.tabText(tabs.count() - 1) == "+"
    # «Model» itself does not drag.
    _drag_tab(tabs, 0, tabs.tabRect(3).center().x())
    assert _order(composer) == ["D", "B", "C", "A"]
    assert tabs.tabText(0) == "Model"


def test_a_drag_back_to_where_it_was_changes_nothing(composer):
    tabs = composer._sheet_tabs
    tabs.show()
    _spin()
    version = composer._scene().version
    start = tabs.tabRect(2).center()
    QTest.mousePress(tabs, Qt.LeftButton, Qt.NoModifier, start)
    for dx in (6, 12, 18, 12, 6, 0):
        QTest.mouseMove(tabs, QPoint(start.x() + dx, start.y()))
    QTest.mouseRelease(tabs, Qt.LeftButton, Qt.NoModifier, start)
    _spin()
    assert _order(composer) == ["A", "B", "C", "D"]
    assert not composer.history._undo
    assert composer._scene().version >= version


def test_the_model_window_strip_does_not_drag(composer):
    win = composer._window
    assert not win._sheet_tabs.isMovable()
    assert composer._sheet_tabs.isMovable()


def test_a_reorder_is_not_taken_for_a_model_change(composer):
    """The move bumps the version; taken for a model edit it made every
    frame stale (and the auto pass rendered them all again)."""
    from core.composition import MarcoVista
    frame = MarcoVista(x_mm=20, y_mm=20, w_mm=80, h_mm=60)
    composer.comp.frames.append(frame)
    composer._stale.discard(id(frame))
    seen = []
    after = composer._after_sheet_order

    def spy(old, new):
        after(old, new)
        seen.append(composer._scene().version)   # the move's own bump
    composer._after_sheet_order = spy
    composer.move_sheet(0, 3)
    composer.history.undo()
    assert len(seen) == 2
    for version in seen + [composer._scene().version]:
        composer._on_model_version(version)
    assert not composer.is_stale(frame)


# ---- one panel for the sheets ---------------------------------------------------
def _open_panel(composer):
    composer._show_page("views")
    _spin(50)
    return _explorer(composer)


def test_there_is_one_sheets_panel_not_two(composer):
    """The old «Sheets» page of thumbnails is the explorer's Thumbnails
    mode now: no page of its own beside the explorer's."""
    assert "sheets" not in composer._pages
    tabs = composer._side_tabs("right")
    keys = [composer.page_key(tabs.widget(i)) for i in range(tabs.count())]
    assert keys == ["layout", "views", "scenes", "items", "props"]
    assert composer._page_titles["views"] == "Sheets"


def test_pages_or_a_list_and_the_choice_is_kept(composer):
    from PySide6.QtCore import QSettings
    from views.sheet_browser import SheetExplorer
    panel = _open_panel(composer)
    assert panel.thumbnails                     # Pages: what Marco asked for
    assert panel.stack.currentWidget() is panel.pages
    assert panel.view_btn is not None
    assert [a.text() for a in panel.view_btn.menu().actions()] == [
        "Pages", "List"]
    assert not panel.search.isVisible()         # the filter is the List's
    assert not panel.add_folder_btn.isVisible()
    panel.list_action.trigger()
    assert not panel.thumbnails
    assert panel.stack.currentWidget() is panel.tree
    assert panel.search.isVisible() and panel.add_folder_btn.isVisible()
    assert QSettings().value(panel.THUMBS_KEY) in (False, "false")
    again = SheetExplorer(composer._window, composer=composer)
    assert not again.thumbnails                 # remembered
    assert again.stack.currentWidget() is again.tree
    again.deleteLater()
    panel.thumbs_action.trigger()
    _spin(100)
    assert panel.thumbnails and panel.stack.currentWidget() is panel.pages
    assert all(panel.page_pixmap(c) is not None
               for c in composer._scene().compositions)


def test_a_tab_dragged_in_a_document_with_folders_joins_that_folder(
        composer):
    """The sheet order follows the explorer's tree (PR #932): a tab
    dropped among the sheets of a folder puts the sheet in that folder —
    a plain reorder would be sorted back to the tree at once."""
    from core import sheet_folders as sf
    scene = composer._scene()
    a, b, c, d = scene.compositions
    folder = sf.SheetFolder(name="Cortes")
    folder.pos = 2                              # after A and B
    scene.sheet_folders.append(folder)
    c.folder_id = d.folder_id = folder.id
    sf.sync_order(scene)
    assert _order(composer) == ["A", "B", "C", "D"]
    composer.move_sheet(0, 2)                   # «A» between C and D
    assert _order(composer) == ["B", "C", "A", "D"]
    assert a.folder_id == folder.id
    assert sf.tree_order(scene) == scene.compositions   # tree and strip agree
    assert _rows(composer) == ["B", "C", "A", "D"]
    composer.history.undo()
    assert _order(composer) == ["A", "B", "C", "D"] and a.folder_id is None
    composer.history.redo()
    assert _order(composer) == ["B", "C", "A", "D"]
    assert a.folder_id == folder.id


def test_the_explorer_follows_a_sheet_moved_in_the_model_window(composer):
    _open_panel(composer)
    win = composer._window
    from core.history import MoveSheetCommand
    sheet = composer._scene().compositions[3]
    win.viewport.history.execute(MoveSheetCommand(sheet, 0))
    win._refresh_sheet_tabs()
    _spin()
    assert _rows(composer) == ["D", "A", "B", "C"]


# ---- the pictures ---------------------------------------------------------------
def test_pictures_are_in_proportion_to_the_paper(composer):
    from views.sheet_pages import THUMB_PX, thumb_box
    a, b = composer._scene().compositions[:2]
    a.paper, a.landscape = "A3", True
    b.paper, b.landscape = "A4", False
    wa, ha = a.page_size_mm()
    box = thumb_box(a)
    assert box.width() == THUMB_PX
    assert abs(box.height() / box.width() - ha / wa) < 0.02
    box = thumb_box(b)
    assert box.height() == THUMB_PX and box.width() < THUMB_PX


def test_every_page_gets_a_picture_without_any_render(composer):
    panel = _open_panel(composer).pictures
    _spin(100)
    assert all(panel.pixmap_for(id(c)) is not None
               for c in composer._scene().compositions)
    # one each — and the open one again, at most, after its canvas settled
    assert 4 <= panel.painted <= 5


def test_a_changed_sheet_gets_a_new_picture_and_only_it(composer):
    from core.composition import AddItemCommand, FormaItem
    panel = _open_panel(composer).pictures
    _spin(100)
    comps = composer._scene().compositions
    before = {id(c): panel.pixmap_for(id(c)).toImage() for c in comps}
    painted = panel.painted
    big = FormaItem(x_mm=10, y_mm=10, w_mm=300, h_mm=200)
    big.fill, big.fill_color = True, "#000000"
    composer.history.execute(AddItemCommand(composer.comp, big))
    _spin(100)
    assert panel.painted == painted                   # not yet: it waits
    _spin(panel.DELAY_MS + 200)
    assert panel.painted == painted + 1               # the open sheet only
    assert panel.pixmap_for(id(comps[0])).toImage() != before[id(comps[0])]
    for c in comps[1:]:
        assert panel.pixmap_for(id(c)).toImage() == before[id(c)]


def test_a_thumbnail_leaves_the_sheet_fields_on_the_open_sheet(composer):
    from core.composition import TextoItem
    from core.composition import expand_fields
    composer.comp.texts.append(TextoItem(x_mm=20, y_mm=20, text="{hoja}"))
    composer._set_field_context(composer.comp)
    want = expand_fields("{hoja}")
    assert want == "1"
    composer.sheet_thumbnail(composer._scene().compositions[2], 60, 40)
    assert expand_fields("{hoja}") == want


def test_the_order_is_saved_in_the_igz(composer, tmp_path):
    from core.scene import Scene
    from formats import igz
    composer._sheet_tabs.drag(3, 0)
    _spin()
    assert _order(composer) == ["D", "A", "B", "C"]
    path = tmp_path / "orden.igz"
    igz.save_scene(composer._scene(), path)
    back = Scene()
    igz.load_into(back, path)
    assert [c.name for c in back.compositions] == ["D", "A", "B", "C"]


# ---- the Pages view: only the pages, and what a PDF reader does with them ------
def _pages(comp):
    return _explorer(comp).pages


def _page_names(comp) -> list:
    pages = _pages(comp)
    return [pages.item(i).text() for i in range(pages.count())]


def _pick_pages(comp, *names) -> None:
    """Select the pages called ``names``, the last one current."""
    pages = _pages(comp)
    pages.clearSelection()
    for i in range(pages.count()):
        if pages.item(i).text() in names:
            pages.item(i).setSelected(True)
            if pages.item(i).text() == names[-1]:
                from PySide6.QtCore import QItemSelectionModel
                pages.setCurrentItem(pages.item(i),
                                     QItemSelectionModel.NoUpdate)


def _key(comp, key, mods=Qt.NoModifier) -> None:
    pages = _pages(comp)
    pages.setFocus()
    QTest.keyClick(pages, key, mods)
    _spin(30)


def _yes(monkeypatch) -> list:
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: (asked.append(a[2]),
                                         QMessageBox.Yes)[1])
    return asked


def test_the_pages_are_only_the_sheets_in_their_order(composer):
    """One page per sheet, in the order of the set — no row of a frame or
    a scene, however many a sheet holds (Marco, 20-11: «no me gusta que se
    vean cada escena que tiene cada lámina, se contamina»)."""
    from core.composition import MarcoVista
    panel = _open_panel(composer)
    comps = composer._scene().compositions
    comps[1].frames = [MarcoVista(view_key="std:front"),
                       MarcoVista(view_key="std:top")]
    panel.refresh(force=True)
    assert _page_names(composer) == ["A", "B", "C", "D"]
    assert _pages(composer).count() == 4
    assert set(panel.page_items) == {id(c) for c in comps}
    # Pages fill the panel's width, in proportion to their paper.
    comps[2].paper, comps[2].landscape = "A4", False
    box = panel.page_box(comps[0])
    assert box.width() >= panel.cell_width() - 40
    tall = panel.page_box(comps[2])
    assert tall.height() > tall.width()


def test_a_click_opens_the_sheet_and_ctrl_click_only_picks(composer):
    panel = _open_panel(composer)
    pages = _pages(composer)
    comps = composer._scene().compositions
    rect = pages.visualItemRect(pages.item(2))
    QTest.mouseClick(pages.viewport(), Qt.LeftButton, Qt.NoModifier,
                     rect.center())
    _spin(20)
    assert composer.comp is comps[2]
    rect = pages.visualItemRect(pages.item(0))
    QTest.mouseClick(pages.viewport(), Qt.LeftButton, Qt.ControlModifier,
                     rect.center())
    _spin(20)
    assert composer.comp is comps[2]                 # still C open
    assert [c.name for c in panel.selected_sheets()] == ["A", "C"]


def _drop(comp, sheets_rows, at_row, upper=True) -> None:
    """Drag the pages at ``sheets_rows`` and drop them on page ``at_row``
    (its upper or lower half), through the list's own drag events."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QDragMoveEvent, QDropEvent
    pages = _pages(comp)
    items = [pages.item(r) for r in sheets_rows]
    mime = pages.mimeData(items)
    rect = pages.visualItemRect(pages.item(at_row))
    pos = QPoint(rect.center().x(),
                 rect.top() + 4 if upper else rect.bottom() - 4)
    move = QDragMoveEvent(pos, Qt.MoveAction, mime, Qt.LeftButton,
                          Qt.NoModifier)
    pages.dragMoveEvent(move)
    assert pages.gap == (at_row if upper else at_row + 1)   # the line
    drop = QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton,
                      Qt.NoModifier)
    pages.dropEvent(drop)
    assert pages.gap is None
    _spin(30)


def test_dragging_pages_reorders_them_in_one_undo_step(composer):
    _open_panel(composer)
    tabs = composer._sheet_tabs
    _drop(composer, [0], 2, upper=False)            # A after C
    assert _order(composer) == ["B", "C", "A", "D"]
    assert _page_names(composer) == ["B", "C", "A", "D"]
    assert tabs.names() == ["Model", "B", "C", "A", "D"]
    assert composer.comp.name == "A"                # still the sheet open
    composer.history.undo()
    _spin()
    assert _order(composer) == ["A", "B", "C", "D"]
    assert _page_names(composer) == ["A", "B", "C", "D"]
    composer.history.redo()
    assert _order(composer) == ["B", "C", "A", "D"]


def test_several_pages_drag_together_in_one_undo_step(composer):
    _open_panel(composer)
    undo = len(composer.history._undo)
    _drop(composer, [0, 2], 3, upper=False)         # A and C to the end
    assert _order(composer) == ["B", "D", "A", "C"]
    assert len(composer.history._undo) == undo + 1
    assert [c.name for c in _explorer(composer).selected_sheets()] == [
        "A", "C"]                                    # still picked
    _drop(composer, [3], 0)                         # C to the front
    assert _order(composer) == ["C", "B", "D", "A"]
    composer.history.undo()
    composer.history.undo()
    assert _order(composer) == ["A", "B", "C", "D"]
    # A drop where they already are is no step at all.
    _drop(composer, [1], 1)
    assert len(composer.history._undo) == undo


def test_alt_arrows_move_the_picked_pages(composer):
    _open_panel(composer)
    _pick_pages(composer, "B")
    _key(composer, Qt.Key_Down, Qt.AltModifier)
    assert _order(composer) == ["A", "C", "B", "D"]
    _key(composer, Qt.Key_Up, Qt.AltModifier)
    _key(composer, Qt.Key_Up, Qt.AltModifier)
    assert _order(composer) == ["B", "A", "C", "D"]
    _key(composer, Qt.Key_Up, Qt.AltModifier)       # already first
    assert _order(composer) == ["B", "A", "C", "D"]


def test_copy_and_paste_pages_after_the_current_one(composer):
    _open_panel(composer)
    scene = composer._scene()
    composer.comp.texts.append(__import__(
        "core.composition", fromlist=["TextoItem"]).TextoItem(text="hola"))
    _pick_pages(composer, "A", "C")
    _key(composer, Qt.Key_C, Qt.ControlModifier)
    assert len(_explorer(composer).clipboard) == 2
    assert _order(composer) == ["A", "B", "C", "D"]  # a copy changes nothing
    _pick_pages(composer, "B")
    undo = len(composer.history._undo)
    _key(composer, Qt.Key_V, Qt.ControlModifier)
    assert _order(composer) == ["A", "B", "A (copy)", "C (copy)", "C", "D"]
    assert len(composer.history._undo) == undo + 1  # one step for both
    pasted = scene.compositions[2]
    assert pasted is not scene.compositions[0]
    assert [t.text for t in pasted.texts] == ["hola"]          # its content
    assert pasted.texts[0] is not scene.compositions[0].texts[0]
    assert [c.name for c in _explorer(composer).selected_sheets()] == [
        "A (copy)", "C (copy)"]
    composer.history.undo()
    _spin()
    assert _order(composer) == ["A", "B", "C", "D"]
    assert _page_names(composer) == ["A", "B", "C", "D"]
    composer.history.redo()
    assert len(scene.compositions) == 6


def test_duplicate_pages_with_ctrl_d(composer):
    _open_panel(composer)
    _pick_pages(composer, "B", "D")
    _key(composer, Qt.Key_D, Qt.ControlModifier)
    assert _order(composer) == ["A", "B", "B (copy)", "C", "D", "D (copy)"]
    composer.history.undo()
    assert _order(composer) == ["A", "B", "C", "D"]


def test_delete_pages_asks_once_and_undoes_in_one_step(composer, monkeypatch):
    asked = _yes(monkeypatch)
    _open_panel(composer)
    _pick_pages(composer, "B", "C")
    _key(composer, Qt.Key_Delete)
    assert asked == ["Delete these 2 sheets?"]
    assert _order(composer) == ["A", "D"]
    assert _page_names(composer) == ["A", "D"]
    composer.history.undo()
    _spin()
    assert _order(composer) == ["A", "B", "C", "D"]
    # The open sheet: the next one opens; undone, it opens again.
    _pick_pages(composer, "A")
    _key(composer, Qt.Key_Delete)
    assert asked[-1] == "Delete 'A'?"
    assert _order(composer) == ["B", "C", "D"]
    assert composer.comp.name == "B"
    composer.history.undo()
    assert _order(composer) == ["A", "B", "C", "D"]
    assert composer.comp.name == "A"
    # «No»: nothing goes; every sheet: one must stay.
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.No)
    _pick_pages(composer, "C")
    _key(composer, Qt.Key_Delete)
    assert _order(composer) == ["A", "B", "C", "D"]
    told = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: told.append(a[2]))
    _pick_pages(composer, "A", "B", "C", "D")
    _key(composer, Qt.Key_Delete)
    assert told and _order(composer) == ["A", "B", "C", "D"]


def test_f2_renames_a_page_under_it_in_one_undo_step(composer):
    from PySide6.QtWidgets import QAbstractItemView, QLineEdit
    _open_panel(composer)
    _pick_pages(composer, "C")
    _key(composer, Qt.Key_F2)
    pages = _pages(composer)
    assert pages.state() == QAbstractItemView.EditingState
    editor = pages.findChild(QLineEdit)
    assert editor is not None and editor.text() == "C"
    # The editor sits under the page, where its name is.
    rect = pages.visualItemRect(pages.item(2))
    assert editor.geometry().top() > rect.center().y()
    editor.setText("C-102 Cortes")
    QTest.keyClick(editor, Qt.Key_Return)
    _spin(30)
    assert _order(composer) == ["A", "B", "C-102 Cortes", "D"]
    assert _page_names(composer)[2] == "C-102 Cortes"
    assert composer._sheet_tabs.names()[3] == "C-102 Cortes"
    composer.history.undo()
    _spin()
    assert _order(composer) == ["A", "B", "C", "D"]


def test_the_undo_of_a_page_step_survives_opening_another_page(composer):
    """Pages are opened all the time: the undo of a paste must not go with
    the sheet it was made on (each sheet's own edits still do)."""
    _open_panel(composer)
    _pick_pages(composer, "A")
    _key(composer, Qt.Key_D, Qt.ControlModifier)
    assert _order(composer) == ["A", "A (copy)", "B", "C", "D"]
    _explorer(composer).open_sheet(composer._scene().compositions[3])
    assert composer.comp.name == "C"
    composer.history.undo()
    assert _order(composer) == ["A", "B", "C", "D"]
    assert composer.comp.name == "C"                # not dragged elsewhere


def test_the_new_sheet_button_puts_it_after_the_current_page(composer):
    _open_panel(composer)
    _pick_pages(composer, "B")
    _explorer(composer).add_sheet_btn.click()
    _spin()
    names = _order(composer)
    assert names[:2] == ["A", "B"] and names[3:] == ["C", "D"]
    assert composer.comp is composer._scene().compositions[2]
    composer.history.undo()
    assert _order(composer) == ["A", "B", "C", "D"]


def test_the_page_keys_act_only_with_the_focus_on_the_pages(composer):
    """Ctrl+C / Ctrl+V / Ctrl+D / Delete are the canvas's own keys for its
    items: the pages take them only while they have the focus."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    _open_panel(composer)
    pages = _pages(composer)
    for key, mods in ((Qt.Key_C, Qt.ControlModifier),
                      (Qt.Key_V, Qt.ControlModifier),
                      (Qt.Key_D, Qt.ControlModifier),
                      (Qt.Key_Delete, Qt.NoModifier),
                      (Qt.Key_F2, Qt.NoModifier),
                      (Qt.Key_Up, Qt.AltModifier)):
        ev = QKeyEvent(QEvent.ShortcutOverride, key, mods)
        assert pages.event(ev) and ev.isAccepted(), key
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
    pages.event(ev)
    assert not ev.isAccepted()          # Ctrl+Z stays the composer's undo
    # On the canvas the same keys never touch the sheets.
    from views.sheet_browser import SheetExplorer
    _pick_pages(composer, "B")
    SheetExplorer.clipboard = []
    view = composer._view
    view.setFocus()
    for key in (Qt.Key_C, Qt.Key_V, Qt.Key_D):
        QTest.keyClick(view, key, Qt.ControlModifier)
    QTest.keyClick(view, Qt.Key_Delete)
    _spin(30)
    assert _order(composer) == ["A", "B", "C", "D"]
    assert SheetExplorer.clipboard == []          # the canvas copied, not us
    # …and with the focus back on the pages, Ctrl+C is ours again.
    _key(composer, Qt.Key_C, Qt.ControlModifier)
    assert len(SheetExplorer.clipboard) == 1
    SheetExplorer.clipboard = []


def test_the_page_menu_has_the_keys_actions(composer):
    panel = _open_panel(composer)
    sheet = composer._scene().compositions[1]
    texts = [a.text() for a in panel.build_page_menu(sheet).actions()
             if not a.isSeparator()]
    for want in ("Open sheet", "Rename… (F2)", "Duplicate (Ctrl+D)",
                 "Copy (Ctrl+C)", "Paste (Ctrl+V)", "Delete",
                 "Move up (Alt+↑)", "Move down (Alt+↓)", "New sheet"):
        assert want in texts, want
    below = [a.text() for a in panel.build_page_menu(None).actions()
             if not a.isSeparator()]
    assert "Paste (Ctrl+V)" in below and "New sheet" in below


# ---- the pictures: at once, the ones on screen first, filled in later ----------
def _fake_small_renders(composer, monkeypatch, colour=Qt.red) -> list:
    """Small renders that paint the frame ``colour`` (no GL) — counted."""
    from PySide6.QtGui import QImage
    made = []

    def small(self, frame):
        made.append(frame)
        w, h = frame.render_px(self.THUMB_RENDER_DPI)
        image = QImage(max(1, w), max(1, h), QImage.Format_RGB32)
        image.fill(colour)
        self._thumb_store().put(frame, image, None)
        return image
    monkeypatch.setattr(type(composer), "thumbnail_render", small)
    return made


def _centre_colour(pm):
    img = pm.toImage()
    return img.pixelColor(img.width() // 2, img.height() // 2)


def test_a_page_shows_at_once_and_fills_in_when_its_frames_render(
        composer, monkeypatch):
    """A frame never rendered does not hold its page back: the page shows
    at once with what there is, and a small render of the frame — never
    the frame's own render — fills it in afterwards."""
    from core.composition import MarcoVista
    made = _fake_small_renders(composer, monkeypatch)
    comps = composer._scene().compositions
    c = comps[2]
    pw, ph = c.page_size_mm()
    frame = MarcoVista(x_mm=0, y_mm=0, w_mm=pw, h_mm=ph,
                       view_key="std:front")
    c.frames = [frame]
    panel = _explorer(composer)
    assert panel.page_pixmap(c) is None          # a grey page, for now
    pics = _open_panel(composer).pictures
    _spin(150)
    assert made == [frame]                       # one small render, no more
    assert pics.filled == 1
    assert id(frame) not in composer.render_cache     # the canvas's untouched
    pm = panel.page_pixmap(c)
    assert pm is not None
    colour = _centre_colour(pm)
    assert colour.red() > 200 and colour.green() < 60  # the render is in
    assert pics.painted_keys.count(id(c)) == 2   # with and without it
    _spin(pics.DELAY_MS + 200)
    assert not pics.busy()


def test_a_frame_render_repaints_only_its_own_page(composer, monkeypatch):
    """A render landing on sheet C — or any change of C — paints C's page
    again, and no other."""
    from core.composition import MarcoVista
    _fake_small_renders(composer, monkeypatch)
    comps = composer._scene().compositions
    frame = MarcoVista(view_key="std:front")
    comps[2].frames = [frame]
    pics = _open_panel(composer).pictures
    _spin(150)
    before = list(pics.painted_keys)
    composer._touch_frame_sheet(frame)
    _spin(pics.DELAY_MS + 200)
    new = pics.painted_keys[len(before):]
    assert new.count(id(comps[2])) == 1
    # Only C — and the open sheet A at most, when its canvas settled late.
    assert set(new) <= {id(comps[2]), id(composer.comp)}
    assert composer.comp is comps[0]


def test_a_model_change_renders_the_small_renders_again_later(
        composer, monkeypatch):
    from core.composition import MarcoVista
    made = _fake_small_renders(composer, monkeypatch)
    comps = composer._scene().compositions
    comps[1].frames = [MarcoVista(view_key="std:front")]
    pics = _open_panel(composer).pictures
    _spin(150)
    assert len(made) == 1
    monkeypatch.setattr(pics, "SETTLE_MS", 50)
    composer._forget_thumbnail_renders()
    assert composer.thumbnail_missing(comps[1]) is not None   # old now
    assert pics.pixmap_for(id(comps[1])) is not None          # still shown
    _spin(300)
    assert len(made) == 2


def test_the_pages_on_screen_are_painted_first(composer):
    from core.composition import Composicion
    scene = composer._scene()
    for k in range(16):
        scene.compositions.append(Composicion(name=f"E{k}"))
    composer._reload_comp_combo()
    panel = _open_panel(composer)
    pages = _pages(composer)
    _spin(400)
    pages.scrollToBottom()
    _spin(50)
    shown = pages.on_screen()
    assert shown and shown[-1] is scene.compositions[-1]
    assert scene.compositions[0] not in shown
    pics = panel.pictures
    pics._pixmaps.clear()
    pics.painted_keys.clear()
    pics.wanted(list(scene.compositions))
    _spin(10)
    first = pics.painted_keys[:len(shown)]
    assert first and all(k in {id(c) for c in shown} for k in first)


# ---- review 20-11: sheets are themselves, two undos, pictures while away -------
def _pick_rows(comp, *rows) -> None:
    """Select the pages at ``rows``, the last one current — by place, for
    sheets that share a name."""
    from PySide6.QtCore import QItemSelectionModel
    pages = _pages(comp)
    pages.clearSelection()
    for r in rows:
        pages.item(r).setSelected(True)
    pages.setCurrentItem(pages.item(rows[-1]), QItemSelectionModel.NoUpdate)


def _cortes_folder(scene):
    """Sheets C and D in a folder «Cortes»."""
    from core import sheet_folders as sf
    a, b, c, d = scene.compositions
    folder = sf.SheetFolder(name="Cortes")
    folder.pos = 2
    scene.sheet_folders.append(folder)
    c.folder_id = d.folder_id = folder.id
    sf.sync_order(scene)
    return folder


def test_two_copies_of_a_sheet_are_two_sheets(composer, monkeypatch):
    """Pasted twice, a sheet's two copies are equal in every field — and
    still two sheets: Delete takes only the page picked, F2 renames only
    it (equality made Delete take both and F2 rename the other one)."""
    asked = _yes(monkeypatch)
    _open_panel(composer)
    scene = composer._scene()
    _pick_pages(composer, "B")
    _key(composer, Qt.Key_C, Qt.ControlModifier)
    _key(composer, Qt.Key_V, Qt.ControlModifier)
    _pick_pages(composer, "D")
    _key(composer, Qt.Key_V, Qt.ControlModifier)
    assert _order(composer) == ["A", "B", "B (copy)", "C", "D", "B (copy)"]
    first, second = scene.compositions[2], scene.compositions[5]
    assert first is not second and first.to_dict() == second.to_dict()
    assert scene.compositions.index(second) == 5
    _pick_rows(composer, 5)
    _key(composer, Qt.Key_Delete)
    assert asked == ["Delete 'B (copy)'?"]
    assert _order(composer) == ["A", "B", "B (copy)", "C", "D"]
    assert scene.compositions[2] is first
    # F2 on the second of two equal copies renames that one.
    _pick_pages(composer, "B")
    _key(composer, Qt.Key_D, Qt.ControlModifier)
    copies = [c for c in scene.compositions if c.name == "B (copy)"]
    assert len(copies) == 2 and copies[0].to_dict() == copies[1].to_dict()
    _explorer(composer).rename_page(copies[1], "Z")
    _spin(30)
    assert copies[1].name == "Z" and copies[0].name == "B (copy)"


def test_pasting_and_duplicating_twice_in_a_folder(composer):
    """In a document with folders the second paste — and the second
    Ctrl+D — of one sheet lands too, each as its own undo step (it did
    nothing, yet marked the document modified)."""
    scene = composer._scene()
    folder = _cortes_folder(scene)
    _open_panel(composer)
    _explorer(composer).refresh(force=True)
    _pick_pages(composer, "C")
    _key(composer, Qt.Key_C, Qt.ControlModifier)
    n0 = len(composer.history._undo)
    _key(composer, Qt.Key_V, Qt.ControlModifier)
    _pick_pages(composer, "D")
    _key(composer, Qt.Key_V, Qt.ControlModifier)
    assert _order(composer) == ["A", "B", "C", "C (copy)", "D", "C (copy)"]
    assert len(composer.history._undo) - n0 == 2
    assert all(c.folder_id == folder.id for c in scene.compositions[2:])
    _pick_rows(composer, 2)
    _key(composer, Qt.Key_D, Qt.ControlModifier)
    _pick_rows(composer, 2)
    _key(composer, Qt.Key_D, Qt.ControlModifier)
    assert _order(composer).count("C (copy)") == 4
    assert len(composer.history._undo) - n0 == 4


def test_a_step_that_changes_nothing_leaves_the_document_alone(composer):
    scene = composer._scene()
    v0, n0 = scene.version, len(composer.history._undo)
    assert composer._sheet_set_step(lambda: None) is False
    assert not composer.move_sheets([scene.compositions[1]], 1)
    assert composer.duplicate_sheets([]) == []
    assert scene.version == v0 and len(composer.history._undo) == n0


def test_undoing_a_paste_keeps_what_the_list_changed_since(composer):
    """The composer's undo of a paste takes the pasted sheet away and
    nothing else: a Print switch flipped and a folder renamed afterwards
    — steps of the model window's undo — stay (it put the whole tree
    back and undid them behind that undo's back)."""
    from core.history import RenameSheetFolderCommand
    scene = composer._scene()
    folder = _cortes_folder(scene)
    a, b, c, d = scene.compositions
    _open_panel(composer)
    panel = _explorer(composer)
    panel.refresh(force=True)
    _pick_pages(composer, "A")
    _key(composer, Qt.Key_C, Qt.ControlModifier)
    _key(composer, Qt.Key_V, Qt.ControlModifier)
    assert _order(composer) == ["A", "A (copy)", "B", "C", "D"]
    panel.set_printed([d], False)
    panel._history().execute(RenameSheetFolderCommand(folder, "Secciones"))
    _spin(30)
    composer.history.undo()
    _spin(30)
    assert _order(composer) == ["A", "B", "C", "D"]
    assert d.print_in_all is False
    assert folder.name == "Secciones"
    assert c.folder_id == d.folder_id == folder.id
    composer.history.redo()
    _spin(30)
    assert _order(composer) == ["A", "A (copy)", "B", "C", "D"]
    assert d.print_in_all is False and folder.name == "Secciones"


def test_a_step_rebuilds_the_canvas_once(composer, monkeypatch):
    """One rebuild per step of the Sheets tab, done or undone (three: the
    step's own, the history's and the sheet strip's call back)."""
    calls = []
    real = type(composer)._rebuild_canvas
    monkeypatch.setattr(type(composer), "_rebuild_canvas",
                        lambda self, *a, **k: (calls.append(1),
                                               real(self, *a, **k))[1])
    _open_panel(composer)
    _pick_pages(composer, "B")
    _key(composer, Qt.Key_D, Qt.ControlModifier)
    _spin(30)
    assert len(calls) == 1
    composer.history.undo()
    _spin(30)
    assert len(calls) == 2


def test_the_pages_leave_keys_with_other_modifiers_alone(composer,
                                                         monkeypatch):
    """Shift+Del, Ctrl+Shift+D and Ctrl+F2 are not the pages' keys."""
    asked = _yes(monkeypatch)
    _open_panel(composer)
    _pick_pages(composer, "B")
    panel = _explorer(composer)
    renamed = []
    monkeypatch.setattr(panel, "rename_current", lambda: renamed.append(1))
    _key(composer, Qt.Key_Delete, Qt.ShiftModifier)
    _key(composer, Qt.Key_D, Qt.ControlModifier | Qt.ShiftModifier)
    _key(composer, Qt.Key_F2, Qt.ControlModifier)
    assert _order(composer) == ["A", "B", "C", "D"]
    assert asked == [] and renamed == []
    _key(composer, Qt.Key_F2)
    assert renamed == [1]


def test_the_small_renders_wait_while_the_composer_is_not_in_use(
        composer, monkeypatch):
    """Behind the model window (or minimized) the composer makes no small
    render — each one stalled the modelling — and goes on as it is
    activated again."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from core.composition import MarcoVista
    from views.sheet_pages import SheetPictures
    made = _fake_small_renders(composer, monkeypatch)
    away = [True]
    monkeypatch.setattr(SheetPictures, "away", lambda self: away[0])
    comps = composer._scene().compositions
    comps[1].frames = [MarcoVista(view_key="std:front")]
    pics = _open_panel(composer).pictures
    _spin(300)
    assert made == []
    away[0] = False
    QApplication.sendEvent(composer, QEvent(QEvent.ActivationChange))
    _spin(300)
    assert len(made) == 1


def test_frames_that_render_alike_share_one_small_render(composer,
                                                         monkeypatch):
    """Eight 3D views of one scene and camera on a sheet: one small
    render, not eight."""
    from core.composition import MarcoVista
    made = _fake_small_renders(composer, monkeypatch)
    comps = composer._scene().compositions
    comps[1].frames = [MarcoVista(x_mm=10 + 30 * k, y_mm=10,
                                  view_key="std:iso") for k in range(8)]
    comps[2].frames = [MarcoVista(view_key="std:top")]
    pics = _open_panel(composer).pictures
    _spin(600)
    assert len(made) == 2
    assert not any(composer.thumbnail_missing(c) for c in comps)
    assert pics.filled == 2


def test_the_small_renders_are_kept_for_live_frames_only():
    """A frame gone takes its small render with it; a new frame that gets
    its id never sees the old render."""
    import gc
    from core.composition import MarcoVista
    from views.sheet_pages import ThumbRenders
    store = ThumbRenders()
    frame = MarcoVista(view_key="std:front")
    store.put(frame, "picture", None)
    assert store.get(frame) == ("picture", None) and len(store) == 1
    del frame
    gc.collect()
    other = MarcoVista(view_key="std:top")
    assert store.get(other) is None
    store.forget()
    assert len(store) == 0
