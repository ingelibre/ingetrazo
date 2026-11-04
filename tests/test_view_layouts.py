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


def _four(win):
    from PySide6.QtTest import QTest
    win.show()
    win.set_view_layout("four")
    QTest.qWait(100)                    # the window's layout settles
    return _grid(win)


def _about(sizes, others) -> bool:
    """The same split, but for the pixel or two the grid's height may still
    settle by offscreen."""
    return all(abs(a - b) <= 2 for a, b in zip(sizes, others))


def _send(widget, kind, glob, mods=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    button = Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    QApplication.sendEvent(widget, QMouseEvent(
        kind, QPointF(widget.mapFromGlobal(glob)), QPointF(glob), button,
        buttons, Qt.NoModifier))
    QApplication.processEvents()


def _mouse(handle, kind, along):
    """A mouse event on ``handle``, ``along`` px down its splitter's axis."""
    from PySide6.QtCore import QPoint, Qt
    at = (QPoint(along, handle.height() // 2)
          if handle.orientation() == Qt.Horizontal
          else QPoint(handle.width() // 2, along))
    _send(handle, kind, handle.splitter().mapToGlobal(at))


def _drag(handle, to, release=True):
    from PySide6.QtCore import QEvent, Qt
    start = handle.x() if handle.orientation() == Qt.Horizontal else handle.y()
    _mouse(handle, QEvent.MouseButtonPress, start)
    _mouse(handle, QEvent.MouseMove, to)
    if release:
        _mouse(handle, QEvent.MouseButtonRelease, to)


def test_a_line_shows_the_drag_arrow(win):
    from PySide6.QtCore import Qt
    grid = _four(win)
    assert grid.col_a.handle(1).cursor().shape() == Qt.SizeVerCursor
    assert grid.columns.handle(1).cursor().shape() == Qt.SizeHorCursor


def test_a_line_drags_alone(win):
    grid = _four(win)
    other = grid.col_b.sizes()
    handle = grid.col_a.handle(1)
    start = handle.y()
    _drag(handle, start - 60)
    assert abs(handle.y() - (start - 60)) <= 1
    assert _about(grid.col_b.sizes(), other), "its other half stayed"
    assert _shown(win) == [0, 1, 2, 3]
    assert not grid.divider_guide.isVisible()


def test_nothing_moves_until_it_is_released_and_a_guide_shows_where(win):
    from PySide6.QtCore import QEvent
    grid = _four(win)
    handle = grid.col_a.handle(1)
    before = grid.col_a.sizes()
    to = handle.y() - 60
    _drag(handle, to, release=False)
    assert _about(grid.col_a.sizes(), before)
    guide = grid.divider_guide
    assert guide.isVisible() and not guide.lines[0][1]
    assert abs(guide.lines[0][0].y1() - to) <= 4
    _mouse(handle, QEvent.MouseButtonRelease, to)
    assert not _about(grid.col_a.sizes(), before)


def test_a_line_sticks_to_the_middle_and_shows_it(win):
    from PySide6.QtCore import QEvent
    grid = _four(win)
    handle = grid.col_a.handle(1)
    _drag(grid.col_b.handle(1), grid.col_b.handle(1).y() - 120)
    _drag(handle, handle.y() - 80)                       # away from the middle
    middle = handle.middle()
    assert abs(handle.y() - middle) > 20
    _mouse(handle, QEvent.MouseButtonPress, handle.y())
    _mouse(handle, QEvent.MouseMove, middle + 7)
    assert grid.divider_guide.lines[0][1]
    _mouse(handle, QEvent.MouseButtonRelease, middle + 7)
    assert handle.y() == middle
    # Beyond the tolerance it goes where it is taken.
    _mouse(handle, QEvent.MouseButtonPress, handle.y())
    _mouse(handle, QEvent.MouseMove, middle + 30)
    assert not grid.divider_guide.lines[0][1]
    _mouse(handle, QEvent.MouseButtonRelease, middle + 30)
    assert abs(handle.y() - (middle + 30)) <= 1


def test_a_line_sticks_to_its_other_half_to_line_up_again(win):
    from PySide6.QtCore import QEvent
    grid = _four(win)
    left, right = grid.col_a.handle(1), grid.col_b.handle(1)
    _drag(right, right.y() - 100)
    target = right.y()
    assert abs(target - left.middle()) > 50
    _mouse(left, QEvent.MouseButtonPress, left.y())
    _mouse(left, QEvent.MouseMove, target + 12)
    assert grid.divider_guide.lines[0][1]
    _mouse(left, QEvent.MouseButtonRelease, target + 12)
    assert left.y() == right.y(), "the two halves line up without aiming"


def test_with_a_hidden_column_there_is_no_other_half(win):
    grid = _four(win)
    grid.toggle_maximized(grid.cells[0])
    QApplication.processEvents()
    assert grid.col_a.handle(1).other_half() is None
    grid.toggle_maximized(grid.cells[0])
    win.set_view_layout("two")
    QApplication.processEvents()
    assert grid.columns.handle(1).other_half() is None


def test_the_tolerance_comes_from_the_settings(win):
    from PySide6.QtCore import QEvent, QSettings
    grid = _four(win)
    handle = grid.col_a.handle(1)
    _drag(grid.col_b.handle(1), grid.col_b.handle(1).y() - 120)
    _drag(handle, handle.y() - 80)
    middle = handle.middle()
    QSettings().setValue("views/divider_snap_px", 40)
    try:
        _mouse(handle, QEvent.MouseButtonPress, handle.y())
        _mouse(handle, QEvent.MouseMove, middle + 35)
        assert grid.divider_guide.lines[0][1]
        _mouse(handle, QEvent.MouseButtonRelease, middle + 35)
        assert handle.y() == middle
    finally:
        QSettings().remove("views/divider_snap_px")


def test_esc_leaves_the_line_where_it_was(win):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    grid = _four(win)
    handle = grid.col_a.handle(1)
    before = grid.col_a.sizes()
    _drag(handle, handle.y() - 60, release=False)
    QApplication.sendEvent(handle, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                             Qt.NoModifier))
    assert not grid.divider_guide.isVisible()
    _mouse(handle, QEvent.MouseMove, handle.y() - 90)
    _mouse(handle, QEvent.MouseButtonRelease, handle.y() - 90)
    assert _about(grid.col_a.sizes(), before)


def test_the_line_between_the_columns_drags_too(win):
    grid = _four(win)
    handle = grid.columns.handle(1)
    rows = grid.col_a.sizes(), grid.col_b.sizes()
    start = handle.x()
    _drag(handle, start + 70)
    assert abs(handle.x() - (start + 70)) <= 1
    assert _about(grid.col_a.sizes(), rows[0])
    assert _about(grid.col_b.sizes(), rows[1])


def test_a_line_keeps_the_views_their_least_room(win):
    grid = _four(win)
    _drag(grid.col_a.handle(1), -500)
    assert grid.col_a.sizes()[0] >= grid.cells[0].minimumSizeHint().height()


def test_the_square_comes_only_near_a_crossing(win):
    from PySide6.QtCore import QPoint, Qt
    grid = _four(win)
    cross = grid.cross
    assert not cross.isVisible()
    at = grid.crossings()[0]
    grid.pointer_moved(grid.mapToGlobal(at + QPoint(10, -10)))
    assert cross.isVisible()
    assert cross.centre() == at
    assert cross.cursor().shape() == Qt.SizeAllCursor
    grid.pointer_moved(grid.mapToGlobal(at + QPoint(120, 0)))
    assert not cross.isVisible(), "further along the line, it drags alone"


def _cross_drag(grid, by, release=True):
    from PySide6.QtCore import QEvent
    at = grid.crossings()[0]
    grid.pointer_moved(grid.mapToGlobal(at))
    cross = grid.cross
    assert cross.isVisible()
    glob = grid.mapToGlobal(at)
    _send(cross, QEvent.MouseButtonPress, glob)
    _send(cross, QEvent.MouseMove, glob + by)
    if release:
        _send(cross, QEvent.MouseButtonRelease, glob + by)


def test_the_square_moves_the_block_as_one(win):
    from PySide6.QtCore import QPoint
    grid = _four(win)
    at = grid.crossings()[0]
    _cross_drag(grid, QPoint(70, -50))
    moved = grid.crossings()
    assert len(moved) == 1, "the two halves together"
    assert abs(moved[0].x() - (at.x() + 70)) <= 2
    assert abs(moved[0].y() - (at.y() - 50)) <= 2
    assert not grid.divider_guide.isVisible()


def test_nothing_moves_until_the_square_is_released(win):
    from PySide6.QtCore import QEvent, QPoint
    grid = _four(win)
    before = grid.columns.sizes(), grid.col_a.sizes()
    at = grid.crossings()[0]
    _cross_drag(grid, QPoint(70, -50), release=False)
    assert _about(grid.columns.sizes(), before[0])
    assert _about(grid.col_a.sizes(), before[1])
    assert len(grid.divider_guide.lines) == 3, "the three lines of the block"
    _send(grid.cross, QEvent.MouseButtonRelease,
          grid.mapToGlobal(at) + QPoint(70, -50))


def test_the_square_lines_up_two_halves_that_had_parted(win):
    from PySide6.QtCore import QPoint
    grid = _four(win)
    _drag(grid.col_b.handle(1), grid.col_b.handle(1).y() - 100)
    assert len(grid.crossings()) == 2
    _cross_drag(grid, QPoint(0, -40))
    assert len(grid.crossings()) == 1
    assert grid.col_a.handle(1).y() == grid.col_b.handle(1).y()


def test_the_square_sticks_each_way_to_the_middle(win):
    from PySide6.QtCore import QEvent, QPoint
    grid = _four(win)
    _cross_drag(grid, QPoint(90, -90))
    column, row = grid.columns.handle(1), grid.col_a.handle(1)
    away = QPoint(column.middle() - column.x() + 7, row.middle() - row.y() - 7)
    _cross_drag(grid, away, release=False)
    assert all(stuck for _line, stuck in grid.divider_guide.lines)
    glob = grid.mapToGlobal(grid.cross.centre())
    _send(grid.cross, QEvent.MouseButtonRelease, glob)
    assert column.x() == column.middle()
    assert row.y() == row.middle()


def test_esc_leaves_the_block_where_it_was(win):
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QKeyEvent
    grid = _four(win)
    before = grid.columns.sizes(), grid.col_a.sizes()
    _cross_drag(grid, QPoint(70, -50), release=False)
    QApplication.sendEvent(grid.cross, QKeyEvent(
        QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not grid.divider_guide.isVisible() and grid.cross._drag_offset is None
    assert _about(grid.columns.sizes(), before[0])
    assert _about(grid.col_a.sizes(), before[1])


def test_three_views_have_a_square_too_and_two_do_not(win):
    from PySide6.QtCore import QPoint
    grid = _four(win)
    win.set_view_layout("three")
    QApplication.processEvents()
    assert len(grid.crossings()) == 1
    _cross_drag(grid, QPoint(40, 30))
    win.set_view_layout("two")
    QApplication.processEvents()
    assert grid.crossings() == []
    win.set_view_layout("two_stacked")
    QApplication.processEvents()
    assert grid.crossings() == []


def test_a_maximized_view_has_no_square(win):
    grid = _four(win)
    grid.toggle_maximized(grid.cells[1])
    QApplication.processEvents()
    assert grid.crossings() == []


def test_restore_brings_the_lines_back_where_they_were(win):
    grid = _four(win)
    _drag(grid.col_a.handle(1), grid.col_a.handle(1).y() - 60)
    _drag(grid.columns.handle(1), grid.columns.handle(1).x() + 70)
    QApplication.processEvents()
    kept = grid.columns.sizes(), grid.col_a.sizes(), grid.col_b.sizes()
    grid.toggle_maximized(grid.cells[3])
    QApplication.processEvents()
    assert _shown(win) == [3]
    grid.toggle_maximized(grid.cells[3])
    QApplication.processEvents()
    assert _shown(win) == [0, 1, 2, 3]
    assert _about(grid.columns.sizes(), kept[0])
    assert _about(grid.col_a.sizes(), kept[1])
    assert _about(grid.col_b.sizes(), kept[2])
    # A layout chosen again starts from the middle, as it always did.
    win.set_view_layout("two")
    win.set_view_layout("four")
    QApplication.processEvents()
    a, b = grid.col_a.sizes()
    assert abs(a - b) <= 2


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
