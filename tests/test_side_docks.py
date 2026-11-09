# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model window's side trays work like the sheet composer's side
panels: tabs on top with their whole names, moved to the other side by
dragging a tab there or from its menu, each side folding on its own."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtWidgets import QApplication, QTabBar, QTabWidget

_app = QApplication.instance() or QApplication([])


def _window():
    """The window with BIM and Terrain opened too (they start closed), so
    the right side is a group of tabs as in everyday use."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    for dock in (win.bim_tray, win.georef_tray):
        dock.show()
    _app.processEvents()
    win._style_dock_tabs()
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.hide()


def test_tray_tabs_sit_on_top_with_their_whole_names():
    win = _window()
    assert win.tabPosition(Qt.RightDockWidgetArea) == QTabWidget.North
    assert win.tabPosition(Qt.LeftDockWidgetArea) == QTabWidget.North
    bars = win._dock_tab_bars()
    assert bars
    for tb in bars:
        assert tb.elideMode() == Qt.ElideNone and tb.usesScrollButtons()
        assert tb.isMovable()                          # reorder by dragging
    _close(win)


def test_a_tray_moves_to_the_left_and_back():
    win = _window()
    dock = win.bim_tray
    win.move_dock(dock, Qt.LeftDockWidgetArea)
    _app.processEvents()
    assert win.dockWidgetArea(dock) == Qt.LeftDockWidgetArea
    assert not dock.isHidden()
    assert dock in win._side_docks(Qt.LeftDockWidgetArea)
    win.move_dock(win.georef_tray, Qt.LeftDockWidgetArea)   # joins it, tabbed
    _app.processEvents()
    assert win.georef_tray in win.tabifiedDockWidgets(dock)
    win.move_dock(dock, Qt.RightDockWidgetArea)
    _app.processEvents()
    assert win.dockWidgetArea(dock) == Qt.RightDockWidgetArea
    win.move_dock(win.georef_tray, Qt.RightDockWidgetArea)
    _close(win)


def test_each_side_folds_on_its_own():
    win = _window()
    win.move_dock(win.bim_tray, Qt.LeftDockWidgetArea)
    _app.processEvents()
    assert win._act_left_sidebar.shortcut().toString() == "Ctrl+F6"
    win._act_left_sidebar.setChecked(False)          # Ctrl+F6
    assert win.bim_tray.isHidden()
    assert not win.tray.isHidden()                    # the right side stays
    win._act_left_sidebar.setChecked(True)
    assert not win.bim_tray.isHidden()
    win._act_sidebar.setChecked(False)                # Ctrl+F5: right only
    assert win.tray.isHidden() and not win.bim_tray.isHidden()
    win._act_sidebar.setChecked(True)
    assert not win.tray.isHidden()
    win.move_dock(win.bim_tray, Qt.RightDockWidgetArea)
    _close(win)


def test_a_tab_dropped_on_the_viewport_goes_to_that_half():
    from PySide6.QtGui import QDropEvent
    win = _window()
    vp = win.viewport
    data = QMimeData()
    data.setData(win.DOCK_MIME, win.project_browser.objectName().encode())
    ev = QDropEvent(QPointF(20, vp.height() / 2), Qt.MoveAction, data,
                    Qt.LeftButton, Qt.NoModifier)
    vp.dropEvent(ev)
    assert win.dockWidgetArea(win.project_browser) == Qt.LeftDockWidgetArea
    ev = QDropEvent(QPointF(vp.width() - 20, vp.height() / 2), Qt.MoveAction,
                    data, Qt.LeftButton, Qt.NoModifier)
    vp.dropEvent(ev)
    assert win.dockWidgetArea(win.project_browser) == Qt.RightDockWidgetArea
    _close(win)


def test_the_tab_under_the_pointer_names_its_tray():
    win = _window()
    from PySide6.QtCore import QPoint
    # Qt keeps spare tab bars around: the one on screen, inside the window.
    bar = next(tb for tb in win._dock_tab_bars() if tb.isVisible()
               and win.rect().contains(tb.mapTo(win, QPoint(0, 0))))
    i = next(i for i in range(bar.count()) if bar.tabText(i) == "BIM")
    centre = bar.tabRect(i).center()
    pos = bar.mapTo(win, centre)
    assert win._dock_tab_at(pos) is win.bim_tray
    _close(win)


def test_a_tray_alone_on_its_side_still_has_a_tab():
    from views.main_window import _DockTitleTab
    win = _window()
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    _app.processEvents()
    tab = win.project_browser.titleBarWidget()
    assert isinstance(tab, _DockTitleTab)
    assert tab.isVisible() and tab.tabText(0) == "Browser"
    centre = tab.mapTo(win, tab.tabRect(0).center())
    assert win._dock_tab_at(centre) is win.project_browser
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)
    _close(win)


def test_a_tabbed_tray_does_not_name_itself_twice():
    win = _window()
    from views.main_window import _DockTitleTab
    win._style_dock_tabs()
    assert not isinstance(win.tray.titleBarWidget(), _DockTitleTab)  # tabbed
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    win._style_dock_tabs()
    assert isinstance(win.project_browser.titleBarWidget(), _DockTitleTab)
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)
    _close(win)


def _dock_mime(win, text: str) -> QMimeData:
    data = QMimeData()
    data.setData(win.DOCK_MIME, text.encode("utf-8"))
    return data


def test_drop_zones_show_at_the_viewports_edges_while_dragging():
    win = _window()
    win.show_drop_zones(True)
    left, right = win._drop_zones()
    vp = win.viewport
    origin = vp.mapTo(win, vp.rect().topLeft())
    assert left.isVisible() and right.isVisible()
    assert left.geometry().left() == origin.x()
    assert right.geometry().right() == origin.x() + vp.width() - 1
    assert left.height() == vp.height()
    win.show_drop_zones(False)
    assert not left.isVisible() and not right.isVisible()
    _close(win)


def test_a_tab_dropped_on_a_zone_docks_on_that_side():
    from PySide6.QtGui import QDropEvent
    win = _window()
    win.show_drop_zones(True)
    left, right = win._drop_zones()
    # The event does not own its mime data: keep it alive while it is used.
    mime = _dock_mime(win, win.tray.objectName())
    ev = QDropEvent(QPointF(30, 30), Qt.MoveAction, mime, Qt.LeftButton,
                    Qt.NoModifier)
    left.dropEvent(ev)
    assert win.dockWidgetArea(win.tray) == Qt.LeftDockWidgetArea
    ev = QDropEvent(QPointF(30, 30), Qt.MoveAction, mime, Qt.LeftButton,
                    Qt.NoModifier)
    right.dropEvent(ev)
    assert win.dockWidgetArea(win.tray) == Qt.RightDockWidgetArea
    win.show_drop_zones(False)
    _close(win)


def test_the_whole_sidebar_crosses_over_and_back():
    win = _window()
    right = win._side_docks(Qt.RightDockWidgetArea)
    assert len(right) >= 3
    payload = f"group:{int(Qt.RightDockWidgetArea.value)}"
    win.drop_on_side(_dock_mime(win, payload), Qt.LeftDockWidgetArea)
    _app.processEvents()
    assert win._side_docks(Qt.RightDockWidgetArea) == []
    assert set(right) <= set(win._side_docks(Qt.LeftDockWidgetArea))
    payload = f"group:{int(Qt.LeftDockWidgetArea.value)}"
    win.drop_on_side(_dock_mime(win, payload), Qt.RightDockWidgetArea)
    _app.processEvents()
    assert set(right) <= set(win._side_docks(Qt.RightDockWidgetArea))
    _close(win)


def test_both_folds_are_in_the_window_menu():
    """Window shows Ctrl+F6 next to Ctrl+F5, so the left fold can be
    found from the menu as the right one can."""
    win = _window()
    from PySide6.QtWidgets import QMenu
    menus = [m for m in win._act_sidebar.associatedObjects()
             if isinstance(m, QMenu)]
    assert menus                                      # Window ▸ Sidebar
    acts = menus[0].actions()
    i = acts.index(win._act_sidebar)
    assert acts[i + 1] is win._act_left_sidebar
    assert win._act_left_sidebar.shortcut().toString() == "Ctrl+F6"
    _close(win)
