# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Window ▸ Restore default toolbars, also at the foot of the right-click
menu over a toolbar: every toolbar back in its factory place and order,
the hidden ones shown again — and the side panels left as they are."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def _settle():
    for _ in range(3):
        _app.processEvents()


def _own_bars(win):
    from PySide6.QtWidgets import QToolBar
    return [*win.toolbars.values(), win.findChild(QToolBar, "panels_toolbar")]


def _layout(win):
    """Area, row-and-order and visibility of every toolbar."""
    out = {}
    for area in (Qt.LeftToolBarArea, Qt.RightToolBarArea,
                 Qt.TopToolBarArea, Qt.BottomToolBarArea):
        bars = sorted((tb for tb in _own_bars(win)
                       if win.toolBarArea(tb) == area),
                      key=lambda tb: (tb.geometry().y(), tb.geometry().x()))
        for i, tb in enumerate(bars):
            out[tb.objectName()] = (area, i, tb.isVisibleTo(win))
    return out


@pytest.fixture
def win(settings_file):
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1280, 800)
    w.show()
    _settle()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _scramble(win):
    """What a user's afternoon does: bars moved, swapped and hidden."""
    draw, views = win.toolbars["draw"], win.toolbars["views"]
    win.removeToolBar(draw)
    win.addToolBar(Qt.BottomToolBarArea, draw)
    draw.show()
    main = win.toolbars["main"]
    win.removeToolBar(main)
    win.addToolBar(Qt.RightToolBarArea, main)
    main.show()
    views.hide()
    # Solid Tools is younger than the factory blob: it must come back too
    solids = win.toolbars["solids"]
    win.removeToolBar(solids)
    win.addToolBar(Qt.LeftToolBarArea, solids)
    solids.hide()
    _own_bars(win)[-1].hide()                          # the Panels bar
    _settle()


def test_restore_puts_every_toolbar_back_and_shows_the_hidden(win):
    factory = _layout(win)
    _scramble(win)
    assert _layout(win) != factory
    win.restore_default_toolbars()
    _settle()
    assert _layout(win) == factory
    assert all(tb.isVisibleTo(win) for tb in _own_bars(win))


def test_restore_leaves_the_side_panels_as_they_are(win):
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    win.set_tray_shown(win.bim_tray, True)
    _settle()
    docks = {d.objectName(): (win.dockWidgetArea(d), d.isVisibleTo(win))
             for d in win._sidebar_docks()}
    _scramble(win)
    win.restore_default_toolbars()
    _settle()
    assert {d.objectName(): (win.dockWidgetArea(d), d.isVisibleTo(win))
            for d in win._sidebar_docks()} == docks
    # and every dock keeps its own name (the layout is saved by name)
    assert win.project_browser.objectName() == "tray_project_browser"
    assert win.dockWidgetArea(win.project_browser) == Qt.LeftDockWidgetArea


def _tabs(win):
    """Each row of side-panel tabs: their order and the one in front (once:
    Qt may leave a spent bar behind with the same tabs)."""
    from PySide6.QtWidgets import QTabBar
    return sorted({
        (tuple(bar.tabText(i) for i in range(bar.count())),
         bar.tabText(bar.currentIndex()))
        for bar in win.findChildren(QTabBar)
        if bar.parent() is win and bar.isVisibleTo(win) and bar.count()})


def test_restore_keeps_the_order_of_the_panel_tabs_and_the_one_in_front(win):
    """The tabs came back reordered — Properties last, another in front
    (2026-10-16: «al restablecer … se mueve de lugar»)."""
    _settle()
    tabs = _tabs(win)
    assert tabs, "no row of panel tabs to compare"
    _scramble(win)
    win.restore_default_toolbars()
    _settle()
    assert _tabs(win) == tabs


def test_restore_keeps_the_window_s_height_and_the_sidebar_handle(win,
                                                                 monkeypatch):
    """The factory blob finds none of the docks, so Qt lays them out again
    one under the other — with a saved layout whose right side is split in
    two, it did: tall panels added up past the window, which grew, and the
    sidebar's handle slid down with the view (2026-10-16: «el botón
    mostrar ocultar barra … ha bajado»). Stack them here the same way."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QDockWidget
    tabbed = [d for d in win.findChildren(QDockWidget)
              if d.isVisible() and win.tabifiedDockWidgets(d)]
    assert len(tabbed) > 1, "no row of panel tabs to stack"
    for d in tabbed:
        d.widget().setMinimumHeight(450)
    restore = win.restoreState

    def stacking(state):
        done = restore(state)
        for d in tabbed:
            win.addDockWidget(Qt.RightDockWidgetArea, d, Qt.Vertical)
        return done
    monkeypatch.setattr(win, "restoreState", stacking)
    _settle()
    height = win.height()
    win.restore_default_toolbars()
    _settle()
    assert win.height() == height
    centre = win.viewport.mapTo(win, QPoint(0, win.viewport.height() // 2))
    handle = win._sidebar_handle
    assert abs(handle.y() + handle.height() // 2 - centre.y()) <= 2


def test_the_right_click_menu_over_a_toolbar_offers_it(win):
    menu = win.createPopupMenu()
    acts = [a for a in menu.actions() if not a.isSeparator()]
    assert acts[-1] is win._act_reset_toolbars
    # Qt's list of toolbars is still there, above it
    assert win.toolbars["draw"].toggleViewAction() in acts
    _scramble(win)
    acts[-1].trigger()
    _settle()
    assert win.toolbars["views"].isVisibleTo(win)
    assert win.toolBarArea(win.toolbars["draw"]) == Qt.LeftToolBarArea


def test_the_window_menu_has_it_too(win):
    from PySide6.QtWidgets import QMenu
    from core.i18n import tr
    window_menu = next(m for m in win.menuBar().findChildren(QMenu)
                       if m.title().replace("&", "") == tr("Window"))
    assert win._act_reset_toolbars in window_menu.actions()


def test_the_entry_is_translated():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "i18n"
    from views import main_window as mw
    keys = ("Restore default toolbars", mw._RESET_TOOLBARS_TIP)
    for p in root.glob("*.json"):
        if p.stem == "en":
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), (p.name, k)
