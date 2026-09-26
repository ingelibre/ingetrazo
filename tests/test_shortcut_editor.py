# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Keyboard shortcuts of one's own (issue #138, @pacaeiro)."""
from __future__ import annotations

import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _action(win, english):
    from views.shortcuts import action_key, collect_actions
    return next(a for a in collect_actions(win)
                if action_key(a) == "text:" + english)


def _keys(act):
    return [s.toString(QKeySequence.PortableText) for s in act.shortcuts()]


def test_a_shortcut_of_ones_own_survives_a_restart_and_the_language(
        monkeypatch):
    from core.i18n import set_language
    from views.shortcuts import ShortcutsDialog
    QSettings().remove("shortcuts")
    win = _window()
    try:
        act = _action(win, "Explode Group")
        dlg = ShortcutsDialog(win)
        assert dlg.assign(act, [QKeySequence("Ctrl+Alt+E")])
        assert _keys(act) == ["Ctrl+Alt+E"]
    finally:
        _close(win)
    set_language("es")                       # the menus now in Spanish
    try:
        win = _window()
        try:
            assert _keys(_action(win, "Explode Group")) == ["Ctrl+Alt+E"]
        finally:
            _close(win)
    finally:
        set_language("en")
        QSettings().remove("shortcuts")


def test_a_clash_takes_the_keys_from_the_other_action(monkeypatch):
    from views.shortcuts import ShortcutsDialog, collect_actions
    QSettings().remove("shortcuts")
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win = _window()
    try:
        group = _action(win, "Make Group")
        explode = _action(win, "Explode Group")
        taken = _keys(group)[0]
        ShortcutsDialog(win).assign(explode, [QKeySequence(taken)])
        assert _keys(explode) == [taken]
        assert taken not in _keys(group)            # only one holds it
        seen: dict = {}
        for a in collect_actions(win):                # no key twice
            for k in _keys(a):
                assert k not in seen, (k, seen.get(k), a.text())
                seen[k] = a.text()
    finally:
        _close(win)
        QSettings().remove("shortcuts")


def test_default_puts_the_factory_keys_back(monkeypatch):
    from views.shortcuts import ShortcutsDialog, default_shortcuts
    QSettings().remove("shortcuts")
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win = _window()
    try:
        act = _action(win, "Make Group")
        factory = _keys(act)
        dlg = ShortcutsDialog(win)
        dlg.assign(act, [])
        assert _keys(act) == []
        dlg.assign(act, default_shortcuts(act))
        assert _keys(act) == factory
        assert not QSettings().contains("shortcuts/text:Make Group")
    finally:
        _close(win)
        QSettings().remove("shortcuts")
