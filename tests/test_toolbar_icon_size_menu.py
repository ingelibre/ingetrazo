# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Right-click over a toolbar ▸ Icon size: the four sizes of Preferences
▸ General ▸ Toolbar icons, one click away; Small (20 px) stays the
default."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
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


@pytest.fixture
def win(settings_file):
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1280, 800)
    w.show()
    for _ in range(3):
        _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _size_menu(win):
    # Found through menuAction(), never QAction.menu() (dead wrappers on
    # some PySide builds).
    menu = win.createPopupMenu()
    for sub in menu.findChildren(type(menu)):
        if sub.menuAction() in menu.actions() and any(
                a.isCheckable() and a.data() in (20, 24, 32, 40)
                for a in sub.actions()):
            return menu, sub
    raise AssertionError("no Icon size submenu")


def test_the_menu_offers_the_four_sizes_with_small_checked(win):
    from views.icons import DEFAULT_TOOLBAR_ICON_PX
    menu, sub = _size_menu(win)
    sizes = [a.data() for a in sub.actions()]
    assert sizes == [20, 24, 32, 40]
    checked = [a.data() for a in sub.actions() if a.isChecked()]
    assert checked == [DEFAULT_TOOLBAR_ICON_PX] == [20]
    assert all(tb.iconSize().width() == 20 for tb in win.toolbars.values())


def test_a_size_from_the_menu_reaches_every_toolbar_and_is_kept(win):
    from views.icons import toolbar_icon_px
    _menu, sub = _size_menu(win)
    big = next(a for a in sub.actions() if a.data() == 32)
    big.trigger()
    assert toolbar_icon_px() == 32
    assert all(tb.iconSize().width() == 32 for tb in win.toolbars.values())
    _menu, sub = _size_menu(win)          # built again: 32 is now checked
    assert [a.data() for a in sub.actions() if a.isChecked()] == [32]
    small = next(a for a in sub.actions() if a.data() == 20)
    small.trigger()
    assert all(tb.iconSize().width() == 20 for tb in win.toolbars.values())
