# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Window ▸ Preferences… on Ctrl+, (Control + comma), the usual key for
Preferences, free everywhere else."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

KEY = QKeySequence("Ctrl+,")


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_preferences_has_ctrl_comma(win):
    act = win._act_preferences
    assert act.text().endswith("…")
    assert act.shortcut() == KEY


def test_nobody_else_has_ctrl_comma(win):
    others = [a.text() for a in win.findChildren(QAction)
              if a is not win._act_preferences and KEY in a.shortcuts()]
    assert others == []


def test_ctrl_comma_opens_preferences_on_its_first_page(win, monkeypatch):
    from views import preferences_dialog as prefs
    opened = {}

    def fake_exec(dlg):
        opened["page"] = dlg._tabs.currentIndex()
        return QDialog.Rejected

    monkeypatch.setattr(prefs.PreferencesDialog, "exec", fake_exec)
    win._act_preferences.trigger()
    assert opened == {"page": 0}            # opened, not on Units or Keys


def test_opening_preferences_flashes_no_loose_window(win):
    """Building the dialog showed «Check for new versions at startup» for
    an instant as a window of its own (setVisible before it had a
    parent): a flicker over the panels on every opening."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QDialog as _Dialog
    from views.preferences_dialog import PreferencesDialog

    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if (ev.type() == QEvent.Show and obj.isWidgetType()
                    and obj.isWindow() and obj is not win
                    and not isinstance(obj, _Dialog)):
                shown.append(type(obj).__name__)
            return False

    spy = Spy()
    app = QApplication.instance()
    app.installEventFilter(spy)
    try:
        dlg = PreferencesDialog(win)
    finally:
        app.removeEventFilter(spy)
    dlg.deleteLater()
    assert shown == []
