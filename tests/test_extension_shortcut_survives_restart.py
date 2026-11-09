# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#595 (@tomlai-git): a keyboard shortcut given to an extension's entry in
Preferences ▸ Keyboard Shortcuts was gone after a restart — in 0.5.8, not in
0.5.7. The keys the user saved are put on the window's actions while it is
built, and since #440 the extensions load after the window shows: their
entries did not exist yet. The keys of the app's own commands kept working.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

PLUGIN = ("def setup(app):\n"
          "    app.add_menu_action('Unfold Faces', lambda: None, {key})\n")


def _close(w):
    w._saved_version = w.viewport.scene.version
    w.close()


def _window(tmp_path, monkeypatch, key="None"):
    from core import extensions
    from core.paths import app_root
    from views.main_window import MainWindow
    (tmp_path / "unfold.py").write_text(PLUGIN.format(key=key))
    monkeypatch.setattr(extensions, "plugin_dirs",
                        lambda: [app_root() / "plugins", tmp_path])
    w = MainWindow(defer_extensions=True)       # as main.py builds it
    w.load_extensions()
    return w, {a.text(): a for a in w._ext_menu.actions()}["Unfold Faces"]


def _forget(act):
    from PySide6.QtCore import QSettings
    from views import shortcuts
    st = QSettings()
    st.remove(f"{shortcuts._GROUP}/{shortcuts._store_key(shortcuts.action_key(act))}")
    st.sync()


def test_a_key_given_to_an_extension_is_there_after_a_restart(tmp_path, monkeypatch):
    from views import shortcuts
    w, act = _window(tmp_path, monkeypatch)
    try:
        assert act.shortcut().isEmpty()
        shortcuts.save_shortcut(act, [QKeySequence("Ctrl+Alt+U")])
    finally:
        _close(w)
    w, act = _window(tmp_path, monkeypatch)       # the restart
    try:
        assert act.shortcut().toString() == "Ctrl+Alt+U"
    finally:
        _forget(act)
        _close(w)


def test_an_extensions_own_key_is_its_factory_key(tmp_path, monkeypatch):
    """The key the extension asks for is its default: «Reset» in
    Preferences goes back to it, and a user key replaces it."""
    from views import shortcuts
    w, act = _window(tmp_path, monkeypatch, key="'Ctrl+Alt+J'")
    try:
        assert [q.toString() for q in shortcuts.default_shortcuts(act)] == ["Ctrl+Alt+J"]
        shortcuts.save_shortcut(act, [QKeySequence("Ctrl+Alt+K")])
    finally:
        _close(w)
    w, act = _window(tmp_path, monkeypatch, key="'Ctrl+Alt+J'")
    try:
        assert act.shortcut().toString() == "Ctrl+Alt+K"
        assert [q.toString() for q in shortcuts.default_shortcuts(act)] == ["Ctrl+Alt+J"]
    finally:
        _forget(act)
        _close(w)
