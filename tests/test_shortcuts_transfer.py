# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #142 (@pacaeiro): take the keyboard shortcuts to another
computer — Preferences ▸ Keyboard shortcuts ▸ Export… / Import…."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core.extensions as extensions  # noqa: E402
from views import shortcuts as sc  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def ventana(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    QSettings().remove("shortcuts")
    from views.main_window import MainWindow
    win = MainWindow()
    yield win
    QSettings().remove("shortcuts")
    win._saved_version = win.viewport.scene.version   # no "save?" modal
    win.close()


def _action(win, key):
    return next(a for a in sc.collect_actions(win) if sc.action_key(a) == key)


def _keys(act):
    return [s.toString(QKeySequence.PortableText) for s in act.shortcuts()]


def test_export_then_import_brings_the_keys_back(ventana):
    line = ventana._tool_actions["line"]
    key = sc.action_key(line)
    line.setShortcuts([QKeySequence("Ctrl+Alt+L")])
    sc.save_shortcut(line, line.shortcuts())
    data = sc.export_shortcuts(ventana)
    assert data["format"] == sc.EXPORT_FORMAT
    assert data["shortcuts"][key] == "Ctrl+Alt+L"
    # Another machine: factory keys.
    line.setShortcuts(sc.default_shortcuts(line))
    QSettings().remove("shortcuts")
    applied, skipped = sc.import_shortcuts(ventana, data)
    assert applied > 0 and skipped == 0
    assert _keys(_action(ventana, key)) == ["Ctrl+Alt+L"]
    assert QSettings().value(f"shortcuts/{key}") == "Ctrl+Alt+L"  # remembered


def test_a_key_the_file_gives_away_is_taken_from_the_other_action(ventana):
    line = ventana._tool_actions["line"]
    rect = ventana._tool_actions["rectangle"]
    rect_keys = _keys(rect)
    assert rect_keys                                   # R, the factory key
    data = {"format": sc.EXPORT_FORMAT, "version": 1,
            "shortcuts": {sc.action_key(line): rect_keys[0]}}
    sc.import_shortcuts(ventana, data)
    assert _keys(line) == [rect_keys[0]]
    assert rect_keys[0] not in _keys(rect)             # never both: Qt kills both


def test_unknown_actions_and_reserved_keys_are_left_out(ventana):
    line = ventana._tool_actions["line"]
    data = {"format": sc.EXPORT_FORMAT, "version": 1,
            "shortcuts": {"a_plugin_not_installed": "Ctrl+Alt+9",
                          sc.action_key(line): "Esc"}}
    applied, skipped = sc.import_shortcuts(ventana, data)
    assert (applied, skipped) == (1, 1)
    assert "Esc" not in _keys(line)                    # the tools own Esc


def test_a_foreign_file_is_refused(ventana):
    with pytest.raises(ValueError):
        sc.import_shortcuts(ventana, {"keys": {"L": "Line"}})
    with pytest.raises(ValueError):
        sc.import_shortcuts(ventana, ["not", "a", "file"])
