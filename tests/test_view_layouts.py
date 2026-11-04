# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""One, two, three or four views of a project (views/multi_view.py): the
views button left of the project tabs offers the layouts as drawings of
their panes; each project keeps its own (a new one opens in its one 3D
view); the grid takes the tab's slot the way an extension's widget does;
choosing a layout is not an edit; the views follow the document, pick up
the window's tool and frame the model with Zoom Extents."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QEnterEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 800)
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _grid(win):
    return win._doc.view_grid


def _shown(win):
    return sorted(c.index for c in _grid(win).cells if not c.isHidden())


def _dirty(win):
    win.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    win.viewport.scene.version += 1


def _pick(win, key):
    """Click the views button, then the layout ``key`` in its popup."""
    win._project_tabs.views_button.click()
    picker = win._layout_picker
    assert picker.isVisible()
    picker.buttons[key].click()
    assert not picker.isVisible()


def test_one_view_by_default_and_nothing_made(win):
    button = win._project_tabs.views_button
    assert win.view_layout() == "single"
    assert button.isCheckable() and not button.isChecked()
    assert not button.icon().isNull()
    assert win._doc.view_grid is None          # nothing made until asked
    assert win._doc.slot_widget() is win.viewport


@pytest.mark.parametrize("key, cells", [
    ("two", [0, 1]), ("two_wide", [0, 1]), ("two_stacked", [1, 3]),
    ("three", [0, 1, 2]), ("three_mirror", [0, 1, 2]),
    ("four", [0, 1, 2, 3]),
])
def test_each_layout_shows_its_views_in_the_tabs_slot(win, key, cells):
    win.show()
    _pick(win, key)
    assert win.view_layout() == key
    assert _shown(win) == cells
    grid = _grid(win)
    assert win._doc.slot_widget() is grid       # the tab's slot
    assert win.viewport.parentWidget() is grid.cells[1]
    for vp in grid.extras():
        assert vp.scene is win.viewport.scene
        assert vp.history is win.viewport.history
    assert win._project_tabs.views_button.isChecked()
    assert not win._is_dirty()


def test_back_to_one_view(win):
    win.show()
    _pick(win, "four")
    _pick(win, "single")
    assert _shown(win) == [1]
    assert not win._project_tabs.views_button.isChecked()


def test_the_picker_marks_the_current_layout(win):
    from views.multi_view import LAYOUT_KEYS
    win.show()
    win.set_view_layout("three")
    win._project_tabs.views_button.click()
    picker = win._layout_picker
    assert list(picker.buttons) == list(LAYOUT_KEYS)
    assert picker.buttons["three"].isChecked()
    assert all(b.toolTip() for b in picker.buttons.values())
    picker.hide()


def test_two_wide_and_three_put_the_3d_view_first_and_wider(win):
    win.show()
    QApplication.processEvents()
    win.set_view_layout("two_wide")
    QApplication.processEvents()
    grid = _grid(win)
    persp, top = grid.cells[1], grid.cells[0]
    assert persp.mapTo(grid, persp.rect().topLeft()).x() \
        < top.mapTo(grid, top.rect().topLeft()).x()
    assert persp.width() > top.width() * 1.5
    win.set_view_layout("three")
    QApplication.processEvents()
    assert persp.height() > top.height() * 1.5


def test_each_project_keeps_its_own_layout(win):
    first = win._doc
    win.set_view_layout("three")
    _dirty(win)
    second = win._new_document()
    assert win.view_layout() == "single"       # a new one: one 3D view
    assert not win._project_tabs.views_button.isChecked()
    win.set_view_layout("two")
    win.activate_document(first)
    assert win.view_layout() == "three"
    assert win._project_tabs.views_button.isChecked()
    win.activate_document(second)
    assert win.view_layout() == "two"


def test_closing_a_project_takes_its_views_along(win):
    import gc
    import weakref
    _dirty(win)
    doc = win._new_document()
    win.set_view_layout("four")
    ref = weakref.ref(doc.view_grid)
    win.close_document(doc, ask=False)
    QApplication.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
    assert doc.view_grid is None
    assert ref() is None or not ref().isVisible()


def test_an_extension_still_sees_the_viewport_of_the_project_in_front(win):
    _dirty(win)
    win.set_view_layout("four")               # the first project: a grid
    win._new_document()
    assert win.centralWidget() is win.viewport  # the one in front


def test_an_extra_view_picks_up_the_windows_tool(win):
    win.show()
    win.set_view_layout("four")
    win._activate_tool("line")
    top = _grid(win).extras()[0]
    QApplication.sendEvent(top, QEnterEvent(QPointF(5, 5), QPointF(5, 5),
                                            QPointF(5, 5)))
    assert top.active_tool is win.viewport.active_tool


def test_zoom_extents_frames_every_view_shown(win):
    win.viewport.scene.mesh.add_face(
        [V(100, 100, 0), V(110, 100, 0), V(110, 110, 0), V(100, 110, 0)])
    win.viewport.scene.version += 1
    win.set_view_layout("four")
    before = [V(vp.camera.target) for vp in _grid(win).extras()]
    win._on_zoom_extents()
    for vp, old in zip(_grid(win).extras(), before):
        assert old.x() < 20
        assert vp.camera.target.x() > 30


def test_a_views_name_is_a_small_label_over_its_corner(win):
    win.show()
    win.set_view_layout("four")
    QApplication.processEvents()
    grid = _grid(win)
    cell = grid.cells[0]
    header = cell.header
    assert cell.layout().indexOf(header) == -1   # not a strip above
    assert header.geometry().topLeft().x() == header.MARGIN
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    QApplication.sendEvent(cell.viewport, QFocusEvent(QEvent.FocusIn))
    assert grid.active_cell() is cell


def test_the_labels_menu_says_maximize_or_restore(win):
    from core.i18n import tr
    win.show()
    win.set_view_layout("four")
    QApplication.processEvents()
    header = _grid(win).cells[2].header

    def entry():
        header.menu().aboutToShow.emit()
        return header.menu().actions()[0]               # first of all
    assert entry().text() == tr("Maximize") + "\tCtrl+Space"
    assert header.menu().actions()[1].isSeparator()
    assert entry().shortcut().isEmpty(), "the window's action holds the key"
    entry().trigger()
    assert _shown(win) == [2] and _grid(win).active_cell() is _grid(win).cells[2]
    assert entry().text() == tr("Restore") + "\tCtrl+Space"
    entry().trigger()
    assert _shown(win) == [0, 1, 2, 3]
    assert len(header.menu().actions()) == 10, "the views, once"


def test_the_key_takes_the_view_under_the_pointer_and_comes_back(win, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QAction, QKeySequence
    from core.i18n import tr
    import views.multi_view as mv
    act = win._act_maximize_view
    assert act.shortcut() == QKeySequence("Ctrl+Space")
    assert [a for a in win.findChildren(QAction)
            if QKeySequence("Ctrl+Space") in a.shortcuts()] == [act]
    assert not act.isEnabled(), "nothing to maximize with one view"
    win.show()
    win.set_view_layout("four")
    QApplication.processEvents()
    assert act.isEnabled()
    cell = _grid(win).cells[3]
    centre = cell.mapToGlobal(cell.rect().center())
    monkeypatch.setattr(mv.QCursor, "pos", staticmethod(lambda: centre))
    act.trigger()
    assert _shown(win) == [3] and act.text() == tr("Restore views")
    monkeypatch.setattr(mv.QCursor, "pos",
                        staticmethod(lambda: QPoint(-9000, -9000)))
    act.trigger()
    assert _shown(win) == [0, 1, 2, 3] and act.text() == tr("Maximize view")
    # Off the views: the one being worked in.
    _grid(win).set_active_cell(_grid(win).cells[2])
    act.trigger()
    assert _shown(win) == [2]
    act.trigger()
    win.set_view_layout("single")
    assert not act.isEnabled() and win._act_maximize_view.text() == tr("Maximize view")


def test_each_project_keeps_its_maximized_view_and_the_action_follows(win):
    from core.i18n import tr
    win.show()
    first = win._doc
    win.set_view_layout("four")
    QApplication.processEvents()
    _grid(win).toggle_maximized(_grid(win).cells[0])
    second = win._new_document()
    QApplication.processEvents()
    assert win._doc is second and not win._act_maximize_view.isEnabled()
    win.activate_document(first)
    QApplication.processEvents()
    assert _shown(win) == [0]
    assert win._act_maximize_view.text() == tr("Restore views")


def test_a_views_label_covers_little_of_the_view(win):
    win.show()
    win.set_view_layout("four")
    QApplication.processEvents()
    header = _grid(win).cells[1].header
    fm = header.fontMetrics()
    assert header.height() <= fm.height() + 4
    # Its name and the small padding: no room kept for an arrow.
    assert header.width() <= fm.horizontalAdvance(header.text()) + 14


def test_the_sidebar_handle_stays_on_the_views_edge(win):
    from PySide6.QtCore import QPoint
    win.show()
    QApplication.processEvents()
    win.set_view_layout("three")
    QApplication.processEvents()
    QApplication.processEvents()
    win._place_sidebar_handle()
    stack = win._doc_stack
    edge = stack.mapTo(win, QPoint(stack.width(), 0)).x()
    handle = win._sidebar_handle
    assert abs(handle.x() + handle.width() // 2 - edge) <= 1


def test_the_moved_viewport_is_shown_in_its_cell(win):
    win.show()
    win.set_view_layout("four")
    QApplication.processEvents()
    assert win.viewport.isVisibleTo(win)


def test_one_view_first_then_by_use(win):
    from views.multi_view import LAYOUT_KEYS
    assert LAYOUT_KEYS[0] == "single"
    assert LAYOUT_KEYS == ("single", "four", "two", "three", "two_stacked",
                           "three_mirror", "two_wide")
    win.show()
    win._project_tabs.views_button.click()
    picker = win._layout_picker
    xs = [picker.buttons[k].x() for k in LAYOUT_KEYS]
    assert xs == sorted(xs)                    # shown in that order
    picker.hide()


def test_two_stacked_puts_the_plan_under_the_3d_view(win):
    win.show()
    win.resize(1400, 900)
    QApplication.processEvents()
    win.set_view_layout("two_stacked")
    QApplication.processEvents()
    grid = _grid(win)
    persp, below = grid.cells[1], grid.cells[3]
    assert below.view == "top"
    assert persp.mapTo(grid, persp.rect().topLeft()).y()         < below.mapTo(grid, below.rect().topLeft()).y()
    assert abs(persp.width() - below.width()) <= 2      # full width, both


def test_three_mirror_puts_the_3d_view_on_the_right(win):
    win.show()
    win.resize(1400, 900)
    QApplication.processEvents()
    win.set_view_layout("three_mirror")
    QApplication.processEvents()
    grid = _grid(win)
    persp, top, front = grid.cells[1], grid.cells[0], grid.cells[2]
    assert persp.mapTo(grid, persp.rect().topLeft()).x()         > top.mapTo(grid, top.rect().topLeft()).x()
    assert persp.height() > top.height() * 1.5
    assert abs(top.x() - front.x()) <= 1           # Top over Front, left


def test_a_view_the_user_picked_stays_through_layouts(win):
    win.show()
    win.set_view_layout("four")
    grid = _grid(win)
    grid.cells[3].pick_view("back")
    win.set_view_layout("two_stacked")
    assert grid.cells[3].view == "back"           # not the suggested plan


def test_the_extra_views_share_what_extensions_registered(win):
    """Overlays, snap providers and pickables are one list per window
    (MainWindow._make_viewport); the extra views have to draw and snap to
    them too."""
    win.set_view_layout("four")
    main = win.viewport
    for vp in _grid(win).extras():
        assert vp._ext_overlays is main._ext_overlays
        assert vp._ext_snap_providers is main._ext_snap_providers
        assert vp._ext_pickables is main._ext_pickables


def test_opening_the_views_keeps_hide_similar(win):
    win.viewport.scene.hide_similar_components = True
    win.set_view_layout("four")
    assert win.viewport.scene.hide_similar_components is True
