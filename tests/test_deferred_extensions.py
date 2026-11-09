# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #440 (@cdblue999): with many extensions installed, their setup()
held the first frame for seconds. The app now builds the window, shows it,
and only then runs the plugins (main.py: ``MainWindow(defer_extensions=True)``
+ ``load_extensions()``). Everything else keeps loading them at once."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _close(w):
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _plugin_tools(w):
    return [k for k in w._tools if k.startswith("plugin_")]


def _menu_texts(w):
    return [a.text() for a in w._ext_menu.actions()]


@pytest.fixture
def deferred():
    from views.main_window import MainWindow
    w = MainWindow(defer_extensions=True)
    yield w
    _close(w)


def test_a_deferred_window_has_no_plugin_until_asked(deferred):
    assert not getattr(deferred, "_extensions_loaded", False)
    assert _plugin_tools(deferred) == []
    deferred.load_extensions()
    assert deferred._extensions_loaded


def test_loading_twice_adds_nothing_the_second_time(deferred):
    deferred.load_extensions()
    first = (_plugin_tools(deferred), _menu_texts(deferred))
    deferred.load_extensions()
    assert (_plugin_tools(deferred), _menu_texts(deferred)) == first


def test_deferred_and_immediate_windows_end_up_the_same():
    from views.main_window import MainWindow
    now = MainWindow()
    later = MainWindow(defer_extensions=True)
    try:
        later.load_extensions()
        assert sorted(_plugin_tools(later)) == sorted(_plugin_tools(now))
        assert _menu_texts(later) == _menu_texts(now)
    finally:
        _close(now)
        _close(later)


def test_plugin_entries_sit_above_the_fixed_entries(deferred):
    deferred.load_extensions()
    from core.i18n import tr
    acts = deferred._ext_menu.actions()
    anchor = acts.index(deferred._ext_anchor)
    folder = next(i for i, a in enumerate(acts)
                  if a.text() == tr("Open extensions folder"))
    assert anchor >= 1                  # something was put above the mark
    assert folder > anchor              # the fixed entries stay below it


def test_deferred_plugin_entries_sit_above_the_menus_own_entries(deferred):
    # 0.5.7 ran setup() before the menu's own entries were added, so the
    # plugins' commands sat on top. Deferred (#440), add_menu_action and
    # add_menu appended them under «Develop an extension…» — a jumbled menu.
    deferred.load_extensions()
    texts = _menu_texts(deferred)
    fixed = texts.index("Manage extensions…")
    for entry in ("AI Assistant", "AI Bridge (MCP)", "Render with Blender…"):
        if entry in texts:
            assert texts.index(entry) < fixed, texts
    assert texts[-1] == "Develop an extension…", texts


def test_the_python_console_comes_after_the_model_tools(deferred):
    # Marco, 09-10: Model Info, Solid Inspector, then the Python Console —
    # a tool for developers — not in between by file name.
    deferred.load_extensions()
    texts = _menu_texts(deferred)
    order = [texts.index(t) for t in ("Model Info", "Solid Inspector",
                                      "Python Console") if t in texts]
    assert order == sorted(order) and len(order) == 3, texts


def test_an_extension_cannot_take_a_bundled_tools_shortcut(tmp_path, monkeypatch):
    # Extension bench (10-10): Point Cloud Splat's setup() asked for
    # Ctrl+Shift+P before the Python Console's entry was made, and the
    # console lost its key. The tools that ship with IngeTrazo reserve theirs.
    from core import extensions
    from core.paths import app_root
    from views.main_window import MainWindow
    (tmp_path / "grabby.py").write_text(
        "def setup(app):\n"
        "    app.add_menu_action('Grabby', lambda: None, 'Ctrl+Shift+P')\n")
    monkeypatch.setattr(extensions, "plugin_dirs",
                        lambda: [app_root() / "plugins", tmp_path])
    w = MainWindow(defer_extensions=True)
    try:
        w.load_extensions()
        acts = {a.text(): a for a in w._ext_menu.actions()}
        assert acts["Python Console"].shortcut().toString() == "Ctrl+Shift+P"
        assert acts["Grabby"].shortcut().isEmpty()
    finally:
        _close(w)
