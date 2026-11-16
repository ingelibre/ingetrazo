# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Gear ▸ Floating panels: the side's trays, all together, out to a window
of their own (another screen, say) and back. Not the floating of single
tabs, which was tried and dropped: the set goes as it is, tabs, «+» and
gear included, and it is off unless chosen.

- the trays of the side go, in their order, the one in front in front;
- their tab bar there has the gear and the «+», and the gear's menu shows
  the option ticked;
- off (or the window's ×), they come back to the side they left, in order;
- a closed tray opened from the «+» of the floating window opens in it;
- remembered: a window closed with them floating opens with them floating,
  and its saved layout has them docked (an older version finds them);
- Restore default panels docks them back.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QTabBar, QToolButton

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A throwaway INI for every QSettings() the windows open (as in
    tests/test_sidebar_trays.py)."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def _settle(n: int = 8) -> None:
    for _ in range(n):
        _app.processEvents()


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    _settle()
    return win


def _close(win) -> None:
    win._saved_version = win.viewport.scene.version
    win.close()
    _settle()


def _right_row(win) -> list:
    return [d for d in win._tab_row(win.tray) if not d.isHidden()]


def _settings():
    """The test's own store: the name main_window uses, patched."""
    import views.main_window as mw
    return mw.QSettings()


def _float_bar(win):
    float_win = win._float_window()
    return next(tb for tb in win._dock_tab_bars()
                if tb.parent() is float_win and tb.count())


def test_the_side_floats_in_its_order_and_comes_back(settings_file):
    win = _window()
    try:
        win.layers_dock.show()
        _settle()
        row = _right_row(win)
        assert len(row) >= 2                      # Properties, Browser, …
        win.project_browser.raise_()
        _settle()
        win.set_panels_floating(True, win.tray)
        _settle()
        float_win = win._float_window()
        assert win.panels_floating() and float_win.isVisible()
        for d in row:
            assert d.parent() is float_win, d.objectName()
            assert win.dockWidgetArea(d) != Qt.RightDockWidgetArea
        assert win._side_docks(Qt.RightDockWidgetArea) == []
        assert [d for d in win._floating_docks()
                if not d.isHidden()] == row                   # same order
        win.set_panels_floating(False)
        _settle()
        assert not win.panels_floating() and not float_win.isVisible()
        for d in row:
            assert d.parent() is win, d.objectName()
            assert win.dockWidgetArea(d) == Qt.RightDockWidgetArea
        assert _right_row(win) == row
    finally:
        _close(win)


def test_the_floating_tabs_keep_their_gear_and_plus(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        bar = _float_bar(win)
        assert bar.findChild(QToolButton, "panel_options_button") is not None
        assert bar.findChild(QToolButton, "add_panels_button") is not None
        assert bar.property("ingetrazo_watched")
        # The gear's menu there: the option ticked, unticking docks back.
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        win._fill_panel_options_menu(menu, win.tray)
        act = next(a for a in menu.actions()
                   if a.text() == "Floating panels")
        assert act.isCheckable() and act.isChecked()
        act.trigger()
        _settle()
        assert not win.panels_floating()
        assert win.dockWidgetArea(win.tray) == Qt.RightDockWidgetArea
    finally:
        _close(win)


def test_the_gear_offers_it_unticked_on_a_docked_side(settings_file):
    win = _window()
    try:
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        win._fill_panel_options_menu(menu, win.tray)
        act = next(a for a in menu.actions()
                   if a.text() == "Floating panels")
        assert act.isCheckable() and not act.isChecked()
        act.trigger()
        _settle()
        assert win.panels_floating()
        assert win.tray.parent() is win._float_window()
    finally:
        _close(win)


def test_a_closed_tray_opened_from_the_floating_plus_opens_there(
        settings_file):
    win = _window()
    try:
        assert win.bim_tray.isHidden()               # closed out of the box
        win.set_panels_floating(True, win.tray)
        _settle()
        area = win._area_of_bar(_float_bar(win))
        win.set_tray_shown(win.bim_tray, True, area)
        _settle()
        assert win.bim_tray.parent() is win._float_window()
        assert not win.bim_tray.isHidden()
        assert win.bim_tray in win._tab_row(win.tray)
    finally:
        _close(win)


def test_closing_the_floating_window_docks_them_back(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        win._float_window().close()
        _settle()
        assert not win.panels_floating()
        assert win.tray.parent() is win
        assert win.dockWidgetArea(win.tray) == Qt.RightDockWidgetArea
    finally:
        _close(win)


def test_dragging_the_last_one_out_ends_the_floating(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        for d in list(win._floating_docks()):
            win.move_dock(d, Qt.LeftDockWidgetArea)
        _settle()
        assert not win.panels_floating()
        assert not win._float_window().isVisible()
        assert win.dockWidgetArea(win.tray) == Qt.LeftDockWidgetArea
    finally:
        _close(win)


def test_a_window_closed_floating_opens_floating(settings_file):
    win = _window()
    win.layers_dock.show()
    _settle()
    win.set_panels_floating(True, win.tray)
    _settle()
    row = win._floating_docks()
    names = [d.objectName() for d in row if not d.isHidden()]
    _close(win)
    st = _settings()
    assert str(st.value("ui/panels_floating")) == "1"
    win = _window()
    try:
        _settle()
        assert win.panels_floating()
        assert [d.objectName() for d in win._floating_docks()
                if not d.isHidden()] == names
    finally:
        _close(win)


def test_the_saved_layout_has_them_docked(settings_file):
    """An older version reads the same layout: the trays must be in it,
    on their side, not lost with the floating window."""
    win = _window()
    win.set_panels_floating(True, win.tray)
    _settle()
    _close(win)
    from views.main_window import MainWindow
    _settings().setValue("ui/panels_floating", "0")    # as an older one
    win = _window()
    try:
        assert not win.panels_floating()
        assert win.tray.parent() is win
        assert win.dockWidgetArea(win.tray) == Qt.RightDockWidgetArea
        assert not win.tray.isHidden()
        assert isinstance(win, MainWindow)
    finally:
        _close(win)


def test_restore_default_panels_docks_them_back(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        win.restore_default_trays()
        _settle()
        assert not win.panels_floating()
        assert win.tray.parent() is win
        assert win.dockWidgetArea(win.tray) == Qt.RightDockWidgetArea
        assert str(_settings().value("ui/panels_floating")) == "0"
    finally:
        _close(win)


def test_ctrl_f5_hides_and_shows_the_floating_window(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        float_win = win._float_window()
        win._act_sidebar.setChecked(False)
        _settle()
        assert not float_win.isVisible()
        win._act_sidebar.setChecked(True)
        _settle()
        assert float_win.isVisible() and not win.tray.isHidden()
    finally:
        _close(win)


def test_clean_screen_hides_the_floating_window_and_brings_it_back(
        settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        float_win = win._float_window()
        win._act_clean_screen.setChecked(True)
        _settle()
        assert not float_win.isVisible()
        win._act_clean_screen.setChecked(False)
        _settle()
        assert float_win.isVisible() and not win.tray.isHidden()
    finally:
        _close(win)


def test_tabs_running_down_apply_to_the_floating_window(settings_file):
    from PySide6.QtWidgets import QTabWidget
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        win.set_dock_tabs_vertical(True)
        _settle()
        assert win._float_window().tabPosition(Qt.RightDockWidgetArea) \
            == QTabWidget.East
        win.set_dock_tabs_vertical(False)
        _settle()
        assert win._float_window().tabPosition(Qt.RightDockWidgetArea) \
            == QTabWidget.North
    finally:
        _close(win)


# --- Dragged near a side, the floating panels dock there ---------------------

def _inner(win):
    """The viewport's rect on the screen: where the drop zones show."""
    from PySide6.QtCore import QRect
    vp = win.viewport
    return QRect(vp.mapToGlobal(vp.rect().topLeft()), vp.size())


def _drag_to(win, x, pointer=None):
    """The floating window moved (as by its title bar) to ``x``, the
    pointer at ``pointer`` (its title bar's middle by default)."""
    from PySide6.QtCore import QPoint
    float_win = win._float_window()
    inner = _inner(win)
    float_win._placing = True                 # the test's own move
    float_win.move(x, inner.top() + 40)
    float_win._placing = False
    _settle()
    frame = float_win.frameGeometry()
    pointer = pointer or QPoint(frame.center().x(), frame.top() + 10)
    win._float_drag_move(pointer)
    return pointer


def test_it_opens_clear_of_the_sides(settings_file):
    """Placed where it would dock at once, a drag would send it back."""
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        float_win = win._float_window()
        frame = float_win.frameGeometry()
        assert win._float_drop_side(
            frame.center()) is None, frame
    finally:
        _close(win)


def test_dragged_near_the_left_side_it_lights_and_docks_there(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        float_win = win._float_window()
        before = bytes(float_win.saveGeometry())
        inner = _inner(win)
        win._float_drag_start()                      # the title bar pressed
        _drag_to(win, inner.left() + 300)            # in the middle: nothing
        assert not any(z._hot for z in win._drop_zones())
        pointer = _drag_to(win, inner.left() + 10)   # its edge by the side
        hot = [z for z in win._drop_zones() if z._hot]
        assert [z.area for z in hot] == [Qt.LeftDockWidgetArea]
        assert all(z.isVisible() for z in win._drop_zones())
        win._float_drag_end(pointer)
        _settle()
        assert not win.panels_floating()
        assert not float_win.isVisible()
        assert win.dockWidgetArea(win.tray) == Qt.LeftDockWidgetArea
        assert not any(z.isVisible() for z in win._drop_zones())
        # Floated again, it opens where it was before the drag.
        assert bytes(_settings().value("ui/panels_float_geometry")) == before
    finally:
        _close(win)


def test_dragged_near_the_right_side_it_docks_on_the_right(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        float_win = win._float_window()
        inner = _inner(win)
        x = inner.right() - float_win.frameGeometry().width() + 10
        pointer = _drag_to(win, x)
        win._float_drag_end(pointer)
        _settle()
        assert not win.panels_floating()
        assert win.dockWidgetArea(win.tray) == Qt.RightDockWidgetArea
    finally:
        _close(win)


def test_let_go_away_from_the_sides_it_keeps_floating(settings_file):
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        inner = _inner(win)
        pointer = _drag_to(win, inner.left() + 300)
        win._float_drag_end(pointer)
        _settle()
        assert win.panels_floating()
        assert win._float_window().isVisible()
        assert not any(z.isVisible() for z in win._drop_zones())
    finally:
        _close(win)


def test_the_pointer_over_a_drop_zone_docks_it_too(settings_file):
    """Its edge need not reach the side: the pointer over the lit zone
    (as with a dragged tab) is enough."""
    from PySide6.QtCore import QPoint
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        inner = _inner(win)
        pointer = _drag_to(win, inner.left() + 300,
                           QPoint(inner.left() + 30, inner.center().y()))
        assert [z.area for z in win._drop_zones() if z._hot] == \
            [Qt.LeftDockWidgetArea]
        win._float_drag_end(pointer)
        _settle()
        assert win.dockWidgetArea(win.tray) == Qt.LeftDockWidgetArea
    finally:
        _close(win)


def test_moves_the_program_makes_are_not_a_drag(settings_file):
    """Placing the window (first float, saved place) must not light a
    side or dock it."""
    win = _window()
    try:
        win.set_panels_floating(True, win.tray)
        _settle()
        assert not win.__dict__.get("_float_dragging")
        assert not any(z.isVisible() for z in win._drop_zones())
        assert win.panels_floating()
    finally:
        _close(win)
