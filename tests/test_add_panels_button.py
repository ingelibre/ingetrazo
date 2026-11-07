# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A «+» after the tray tabs shows at a glance that more panels can be
added: it opens the Window ▸ Panels list, wherever the tabs are."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QToolButton

_app = QApplication.instance() or QApplication([])


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.hide()


def _bar_on_screen(win):
    """Qt keeps spare tab bars around: the one on screen, in the window."""
    return next(tb for tb in win._dock_tab_bars() if tb.isVisible()
                and win.rect().contains(tb.mapTo(win, QPoint(0, 0))))


def _plus(bar):
    return bar.findChild(QToolButton, "add_panels_button")


def test_the_tabs_end_with_a_plus():
    win = _window()
    bar = _bar_on_screen(win)
    btn = _plus(bar)
    assert btn is not None and btn.isVisible() and btn.text() == "+"
    assert btn.toolTip()
    _close(win)


def test_the_plus_follows_the_last_tab():
    win = _window()
    # Few tabs, so they fit: the «+» right after the last one.
    keep = (win.tray, win.project_browser)
    for dock in win._sidebar_docks():
        win.set_tray_shown(dock, dock in keep)
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    bar = _bar_on_screen(win)
    btn = _plus(bar)
    last = bar.tabRect(bar.count() - 1)
    assert last.right() < btn.x() <= last.right() + 6
    # One more tab: it moves along.
    before = btn.x()
    win.set_tray_shown(win.bim_tray, True)
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    bar = _bar_on_screen(win)
    btn = _plus(bar)
    assert btn.x() > before
    assert btn.x() > bar.tabRect(bar.count() - 1).right()
    win._show_all_trays()
    _close(win)


def test_the_plus_stays_inside_the_bar_when_the_tabs_do_not_fit():
    win = _window()
    win._show_all_trays()
    win.resizeDocks([win.tray], [220], Qt.Horizontal)
    _app.processEvents()
    bar = _bar_on_screen(win)
    btn = _plus(bar)
    arrows = [b for b in bar.findChildren(QToolButton)   # Qt's scroll arrows
              if b is not btn and b.isVisible()]
    assert arrows                                  # they really do not fit
    for arrow in arrows:
        assert not btn.geometry().intersects(arrow.geometry())
        assert arrow.x() > btn.x()                 # «+», then the arrows,
        assert arrow.width() == bar.property("ingetrazo_arrow_px")
    assert max(a.geometry().right() for a in arrows) == bar.width() - 1
    # A whole cell of the bar's height: the cut tab ends at its edge
    # instead of showing around a small «+».
    assert btn.height() == bar.height()
    _close(win)


def test_a_tray_alone_on_its_side_has_the_plus_too():
    from views.main_window import _DockTitleTab
    win = _window()
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    _app.processEvents()
    tab = win.project_browser.titleBarWidget()
    assert isinstance(tab, _DockTitleTab)
    btn = _plus(tab)
    assert btn is not None and btn.isVisible()
    assert btn.x() > tab.tabRect(0).right()
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)
    _close(win)


def test_the_plus_opens_the_panels_list(monkeypatch):
    win = _window()
    shown = []
    monkeypatch.setattr(win, "_popup_menu",
                        lambda menu, pos: shown.append(
                            [act.text() for act in menu.actions()]))
    _plus(_bar_on_screen(win)).click()
    assert len(shown) == 1
    names = shown[0]
    for dock in win._sidebar_docks():               # every tray, as in
        assert dock.windowTitle() in names           # Window ▸ Panels
    _close(win)


def test_choosing_a_panel_from_the_plus_opens_it(monkeypatch):
    win = _window()
    win.set_tray_shown(win.georef_tray, False)
    title = win.georef_tray.windowTitle()

    def pick(menu, pos):
        next(a for a in menu.actions() if a.text() == title).trigger()
    monkeypatch.setattr(win, "_popup_menu", pick)
    _plus(_bar_on_screen(win)).click()
    assert not win.georef_tray.isHidden()
    _close(win)


def test_the_list_stays_open_to_switch_several_panels(monkeypatch):
    """Clicking a panel in the «+» list shows or hides it and leaves the
    list open for the next one; «Show all panels» closes it."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    win = _window()
    for dock in (win.bim_tray, win.georef_tray):
        win.set_tray_shown(dock, False)
    menus = []
    monkeypatch.setattr(win, "_popup_menu", lambda menu, pos: menus.append(
        menu) or menu.popup(pos))
    _plus(_bar_on_screen(win)).click()
    menu = menus[0]
    _app.processEvents()

    def click(text):
        act = next(a for a in menu.actions() if a.text() == text)
        centre = QPointF(menu.actionGeometry(act).center())
        menu.setActiveAction(act)
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            QApplication.sendEvent(menu, QMouseEvent(
                kind, centre, centre, Qt.LeftButton,
                Qt.LeftButton if kind == QEvent.MouseButtonPress
                else Qt.NoButton, Qt.NoModifier))
        _app.processEvents()

    click(win.bim_tray.windowTitle())
    assert not win.bim_tray.isHidden() and menu.isVisible()
    click(win.georef_tray.windowTitle())
    assert not win.georef_tray.isHidden() and menu.isVisible()
    bim = next(a for a in menu.actions()
               if a.text() == win.bim_tray.windowTitle())
    assert bim.isChecked()                       # the ticks follow
    click(win.bim_tray.windowTitle())            # and off again
    assert win.bim_tray.isHidden() and menu.isVisible()
    click("Show all panels")
    assert not menu.isVisible()                  # a one-off: it closes
    _close(win)
