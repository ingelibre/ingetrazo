# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Styles is a tab of the sidebar, closed until enabled in the panels list;
its toolbar button opens it for a while when it is closed — a dashed tab,
«temporary» in its header, «Pin» to keep it and ✕ to close it — and the
tab that was in front comes back when it goes."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QMenu, QToolButton

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A throwaway INI for every QSettings() the windows open."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


@pytest.fixture
def real_tabs(monkeypatch):
    """On a real screen only the tab in front of a group is visible; the
    offscreen platform shows them all — play the real screen."""
    real = QDockWidget.isVisible

    def visible(dock):
        if not real(dock):
            return False
        win = dock.parent()
        mates = [d for d in getattr(win, "_sidebar_docks", lambda: [])()
                 if d is not dock and not d.isHidden()
                 and d in win.tabifiedDockWidgets(dock)]
        front = getattr(win, "_test_front", None)
        return not mates or front is dock or front not in mates

    monkeypatch.setattr(QDockWidget, "isVisible", visible)
    real_raise = QDockWidget.raise_

    def raise_(dock):
        dock.parent()._test_front = dock
        real_raise(dock)

    monkeypatch.setattr(QDockWidget, "raise_", raise_)


def _shown(win):
    win.show()
    for _ in range(5):
        _app.processEvents()
    return win


def _settle():
    for _ in range(5):
        _app.processEvents()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _button(win):
    return win.findChild(QToolButton, "styles_button")


def _menu_entry(win):
    menu = win._test_menu = QMenu(win)            # kept: its actions live in it
    win._fill_panels_menu(menu)
    return next(a for a in menu.actions() if a.text() == "Styles")


def test_styles_is_a_closed_tab_on_a_first_run(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    assert win.styles_dock in win._sidebar_docks()
    assert win.styles_dock.isHidden()
    assert win.styles_dock.widget().widget() is win.styles_panel
    entry = _menu_entry(win)
    assert entry.isCheckable() and not entry.isChecked()
    # No window of its own any more, nor a drop-down.
    assert _button(win).menu() is None
    _close(win)


def test_a_used_profile_gets_the_new_tab_closed(settings_file):
    QSettings(str(settings_file), QSettings.IniFormat).setValue(
        "ui/hidden_trays", ["tray_bim"])        # chosen before Styles was a tab
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    assert win.styles_dock.isHidden()
    assert not win.georef_tray.isHidden()         # the old choice still rules
    _close(win)


def test_the_button_opens_it_for_a_while_and_a_second_click_closes_it(
        settings_file, real_tabs):
    from views.main_window import MainWindow, _DockHeader
    win = _shown(MainWindow())
    win.tray.raise_()
    dock = win.styles_dock
    _button(win).click()
    _settle()
    assert not dock.isHidden() and dock.isVisible()
    assert win.tray_is_temporary(dock)
    assert dock in win.tabifiedDockWidgets(win.tray)   # a tab among the others
    win._style_dock_tabs()
    header = dock.titleBarWidget()
    assert isinstance(header, _DockHeader) and header.temporary
    # No «temporary» to read: it simply goes when left (Marco, 25-11).
    assert header.findChild(QLabel, "dock_header_temporary") is None
    assert header.pin is not None and header.close_button is not None
    assert not _menu_entry(win).isChecked()             # not enabled
    # The live editor, as in its window: the menu's checks follow it.
    panel = win.styles_panel
    win._act_style_edges.setChecked(False)
    assert not panel._edges.isChecked()
    panel._xray.setChecked(True)
    assert win.viewport.scene.display_style.xray

    _button(win).click()                                # again: it goes
    _settle()
    assert dock.isHidden() and not win.tray_is_temporary(dock)
    assert win._test_front is win.tray                  # Properties is back
    win._style_dock_tabs()
    assert not dock.titleBarWidget().temporary
    _close(win)


def test_choosing_another_tab_closes_it_unless_pinned(settings_file, real_tabs):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.tray.raise_()
    dock = win.styles_dock
    _button(win).click()
    _settle()
    win.project_browser.raise_()                        # another tab chosen
    dock.visibilityChanged.emit(False)
    _settle()
    assert dock.isHidden() and not win.tray_is_temporary(dock)
    assert win._test_front is win.project_browser       # the one chosen stays

    _button(win).click()                                # pinned: it stays
    _settle()
    win._style_dock_tabs()
    dock.titleBarWidget().pin.click()
    win.tray.raise_()
    dock.visibilityChanged.emit(False)
    _settle()
    assert not dock.isHidden()
    _close(win)


def test_folding_the_sidebar_does_not_close_it(settings_file, real_tabs):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    _button(win).click()
    _settle()
    win._set_sidebar_visible(False)
    _settle()
    assert win.tray_is_temporary(win.styles_dock)
    win._set_sidebar_visible(True)
    _settle()
    assert not win.styles_dock.isHidden()
    assert win.tray_is_temporary(win.styles_dock)
    _close(win)


def test_closing_it_from_its_header_and_never_at_the_next_start(
        settings_file, real_tabs):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    _button(win).click()
    _settle()
    _close(win)                                         # left open, for a while
    win = _shown(MainWindow())
    assert win.styles_dock.isHidden()
    _button(win).click()
    _settle()
    win._style_dock_tabs()
    win.styles_dock.titleBarWidget().close_button.click()
    assert win.styles_dock.isHidden()
    assert not win.tray_is_temporary(win.styles_dock)
    _close(win)


def test_pin_keeps_it_from_now_on(settings_file, real_tabs):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    _button(win).click()
    _settle()
    win._style_dock_tabs()
    win.styles_dock.titleBarWidget().pin.click()
    assert not win.tray_is_temporary(win.styles_dock)
    assert not win.styles_dock.isHidden()
    assert _menu_entry(win).isChecked()
    _close(win)
    win = _shown(MainWindow())
    assert not win.styles_dock.isHidden()
    _close(win)


def test_enabled_in_the_panels_list_the_button_only_brings_it_forward(
        settings_file, real_tabs):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    _menu_entry(win).trigger()                          # enabled
    assert not win.styles_dock.isHidden()
    assert not win.tray_is_temporary(win.styles_dock)
    win.tray.raise_()
    _button(win).click()
    assert win._test_front is win.styles_dock
    _button(win).click()                                # stays: it is enabled
    assert not win.styles_dock.isHidden()
    _close(win)


def test_ticking_it_in_the_panels_list_while_temporary_keeps_it(
        settings_file, real_tabs):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    _button(win).click()
    _settle()
    _menu_entry(win).trigger()
    assert not win.tray_is_temporary(win.styles_dock)
    assert not win.styles_dock.isHidden()
    _close(win)


def test_a_temporary_tab_wears_a_dashed_icon_until_it_closes(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    plain = win.styles_dock.windowIcon().cacheKey()
    win.show_tray_temporarily(win.styles_dock)
    marked = win.styles_dock.windowIcon().cacheKey()
    assert marked != plain
    win._refresh_toolbar_icons()                        # a theme change
    assert win.styles_dock.windowIcon().cacheKey() != plain
    win.end_temporary_tray(win.styles_dock)
    image = win.styles_dock.windowIcon().pixmap(20, 20).toImage()
    assert image.pixelColor(0, 10).alpha() == 0         # no frame left
    _close(win)


def test_restore_default_panels_closes_a_temporary_tab(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.show_tray_temporarily(win.styles_dock)
    win.restore_default_trays()
    _settle()
    assert win.styles_dock.isHidden()
    assert not win.tray_is_temporary(win.styles_dock)
    _close(win)


def test_any_tray_can_open_for_a_while(settings_file):
    from views.extension_api import ExtensionApp
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    quiet = ExtensionApp(win, "quiet").add_panel("Quiet", QLabel("q"),
                                                 start_hidden=True)
    win.show_tray_temporarily(quiet)
    assert not quiet.isHidden() and win.tray_is_temporary(quiet)
    win.end_temporary_tray(quiet)
    assert quiet.isHidden()
    _close(win)
