# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Reordering sheets by dragging their tabs, and the composer's «Sheets»
panel — every sheet as a page, as a PDF reader lists them (Marco, 19-11:
«me gustaria poder cambiar el orden arrastrando una pestaña … como un
gestor de laminas … que se muestren en miniatura»)."""
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
    win = MainWindow()
    for name in "ABCD":
        win.viewport.scene.compositions.append(Composicion(name=name))
    win._update_title()
    win._sheet_tabs.click(1)
    comp = win._composer
    comp.resize(1400, 900)
    _spin()
    yield comp
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


def _rows(comp) -> list:
    lst = comp._sheet_pages.list
    return [lst.item(i).text() for i in range(lst.count())]


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
    # «A» (tab 1) dragged past «C»: B C A D.
    _drag_tab(tabs, 1, tabs.tabRect(3).right() - 2)
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


# ---- the Sheets panel -----------------------------------------------------------
def _open_panel(composer):
    composer._show_page("sheets")
    _spin(50)
    return composer._sheet_pages


def test_the_panel_is_a_new_tab_at_the_end_of_the_right_side(composer):
    assert composer.page_side("sheets") == "right"
    tabs = composer._side_tabs("right")
    keys = [composer.page_key(tabs.widget(i)) for i in range(tabs.count())]
    assert keys[-1] == "sheets"
    assert keys[:-1] == [k for k in ("layout", "views", "items", "props")
                         if k in keys]


def test_the_panel_lists_the_pages_and_marks_the_open_one(composer):
    panel = _open_panel(composer)
    assert _rows(composer) == ["A", "B", "C", "D"]
    assert panel.list.currentRow() == 0
    composer.show_sheet(2)
    _spin()
    assert panel.list.currentRow() == 2


def test_a_click_on_a_page_opens_that_sheet(composer):
    panel = _open_panel(composer)
    lst = panel.list
    QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier,
                     lst.visualItemRect(lst.item(3)).center())
    _spin()
    assert composer.comp.name == "D"
    assert composer._sheet_tabs.current() == 3


def test_a_page_dropped_among_the_others_moves_the_sheet(composer):
    panel = _open_panel(composer)
    lst = panel.list
    # Where a drop lands: above a page's middle, before it; below, after.
    r = lst.visualItemRect(lst.item(2))
    assert lst.drop_row(QPoint(r.center().x(), r.top() + 3)) == 2
    assert lst.drop_row(QPoint(r.center().x(), r.bottom() - 3)) == 3
    panel.move(0, 2)                                  # what the drop calls
    _spin()
    assert _order(composer) == ["B", "C", "A", "D"]
    assert _rows(composer) == ["B", "C", "A", "D"]
    assert composer._sheet_tabs.names() == ["Model", "B", "C", "A", "D"]
    assert lst.currentRow() == 2                      # «A» is still open
    composer.history.undo()
    _spin()
    assert _rows(composer) == ["A", "B", "C", "D"]
    composer.history.redo()
    _spin()
    assert _rows(composer) == ["B", "C", "A", "D"]


def test_a_real_drop_on_the_list_goes_through_the_composer(composer):
    """The drop event itself: Qt must not shuffle the rows, the composer
    moves the sheet and the rows follow."""
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent
    panel = _open_panel(composer)
    lst = panel.list
    lst.setCurrentRow(0)
    _spin()
    r = lst.visualItemRect(lst.item(3))
    ev = QDropEvent(QPointF(r.center().x(), r.bottom() - 3), Qt.MoveAction,
                    QMimeData(), Qt.LeftButton, Qt.NoModifier)
    lst.dropEvent(ev)
    assert ev.dropAction() == Qt.IgnoreAction
    _spin()
    assert _order(composer) == ["B", "C", "D", "A"]
    assert _rows(composer) == ["B", "C", "D", "A"]


def test_rename_from_the_panel(composer):
    panel = _open_panel(composer)
    panel.rename(1, "Cortes")
    _spin()
    assert _order(composer) == ["A", "Cortes", "C", "D"]
    assert composer._sheet_tabs.names()[2] == "Cortes"
    assert _rows(composer)[1] == "Cortes"
    panel.rename(1, "   ")                            # empty: not a rename
    _spin()
    assert _rows(composer)[1] == "Cortes"
    assert _order(composer)[1] == "Cortes"


def test_delete_from_the_panel_asks_first(composer, monkeypatch):
    panel = _open_panel(composer)
    asked = []

    def answer(reply):
        def question(*a, **k):
            asked.append(a)
            return reply
        return question

    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.No))
    lst = panel.list
    lst.setCurrentRow(2)
    _spin()
    QTest.keyClick(lst, Qt.Key_Delete)
    _spin()
    assert len(asked) == 1 and _order(composer) == ["A", "B", "C", "D"]
    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.Yes))
    QTest.keyClick(lst, Qt.Key_Delete)
    _spin()
    assert _order(composer) == ["A", "B", "D"]
    assert _rows(composer) == ["A", "B", "D"]
    assert composer._sheet_tabs.names() == ["Model", "A", "B", "D"]


def test_the_panel_follows_sheets_added_and_duplicated(composer):
    _open_panel(composer)
    composer._on_comp_add()
    _spin()
    assert len(_rows(composer)) == 5
    composer.duplicate_sheet(0)
    _spin()
    assert _rows(composer)[1].startswith("A")
    assert len(_rows(composer)) == 6


def test_the_panel_follows_a_sheet_moved_in_the_model_window(composer):
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
    panel = _open_panel(composer)
    _spin(100)
    assert all(panel.pixmap_for(id(c)) is not None
               for c in composer._scene().compositions)
    # one each — and the open one again, at most, after its canvas settled
    assert 4 <= panel.painted <= 5


def test_a_changed_sheet_gets_a_new_picture_and_only_it(composer):
    from core.composition import AddItemCommand, FormaItem
    panel = _open_panel(composer)
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
