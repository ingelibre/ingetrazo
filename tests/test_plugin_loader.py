# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The plugin discovery engine (core.extensions) and its Extensions menu.

Each test below pins one clause of the engine's contract — most of them are
regression tests for the failure modes the original contribution (PR #1)
shipped with: a plugin raising in its constructor took the whole app down at
startup, a plugin that merely *imported* a built-in tool re-registered it
(duplicating the menu entry and cloning its shortcut), and plugins were
imported by package name, which breaks inside a PyInstaller bundle.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import textwrap
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.extensions as extensions                              # noqa: E402
from core.extensions import (                                     # noqa: E402
    discover_plugins, plugin_dirs, user_plugins_dir)


def _write(dirpath: Path, name: str, source: str) -> Path:
    path = dirpath / name
    path.write_text(textwrap.dedent(source))
    return path


GOOD = """
    from tools.base import Tool

    class HelloTool(Tool):
        name = "Hello"

        def on_activate(self, viewport):
            pass

        def on_deactivate(self, viewport):
            pass
"""


# ---- Discovery ------------------------------------------------------------

def test_good_plugin_discovered(tmp_path):
    _write(tmp_path, "hello.py", GOOD)
    plugins, errors = discover_plugins([tmp_path])
    assert errors == []
    assert [t.name for p in plugins for t in p.tools] == ["Hello"]
    assert plugins[0].stem == "hello"


def test_package_plugin_discovered(tmp_path):
    pkg = tmp_path / "hola"
    pkg.mkdir()
    _write(pkg, "__init__.py", GOOD)
    plugins, errors = discover_plugins([tmp_path])
    assert errors == []
    assert len(plugins) == 1 and plugins[0].stem == "hola"


def test_import_leaves_sys_path_alone(tmp_path):
    """By-path loading must not put the plugin dir on sys.path, or a user
    file named json.py would shadow the stdlib for the whole app."""
    _write(tmp_path, "hello.py", GOOD)
    before = list(sys.path)
    discover_plugins([tmp_path])
    assert sys.path == before


def test_missing_directory_is_fine(tmp_path):
    plugins, errors = discover_plugins([tmp_path / "no-existe"])
    assert plugins == [] and errors == []


def test_default_dirs_shape():
    dirs = plugin_dirs()
    assert dirs[0].name == "plugins"
    assert user_plugins_dir().parts[-2:] == ("ingetrazo", "plugins")


# ---- Failure isolation (the app must always start) ------------------------

def test_broken_import_reported_not_raised(tmp_path):
    _write(tmp_path, "roto.py", "import modulo_que_no_existe\n")
    plugins, errors = discover_plugins([tmp_path])
    assert plugins == []
    assert len(errors) == 1 and errors[0].stem == "roto"
    assert "ModuleNotFoundError" in errors[0].error


def test_broken_constructor_reported_not_raised(tmp_path):
    """The PR #1 regression: its try wrapped only the import, so a tool
    raising in __init__ crashed the whole application at startup."""
    _write(tmp_path, "explota.py", """
        from tools.base import Tool

        class Boom(Tool):
            name = "Boom"

            def __init__(self):
                raise RuntimeError("missing optional dependency")

            def on_activate(self, viewport):
                pass

            def on_deactivate(self, viewport):
                pass
    """)
    plugins, errors = discover_plugins([tmp_path])
    assert plugins == []
    assert len(errors) == 1 and "RuntimeError" in errors[0].error


def test_one_bad_plugin_does_not_sink_the_good_one(tmp_path):
    _write(tmp_path, "aaa_roto.py", "import modulo_que_no_existe\n")
    _write(tmp_path, "hello.py", GOOD)
    plugins, errors = discover_plugins([tmp_path])
    assert [p.stem for p in plugins] == ["hello"]
    assert [e.stem for e in errors] == ["aaa_roto"]


# ---- Registration filter --------------------------------------------------

def test_imported_builtin_tool_not_reregistered(tmp_path):
    """A plugin importing LineTool (to reuse or subclass it) must not
    duplicate the built-in Line entry — or clone its 'L' shortcut."""
    _write(tmp_path, "reusa.py", """
        from tools.line import LineTool
        from tools.base import Tool

        class Mine(Tool):
            name = "Mine"

            def on_activate(self, viewport):
                pass

            def on_deactivate(self, viewport):
                pass
    """)
    plugins, errors = discover_plugins([tmp_path])
    assert errors == []
    assert [t.name for p in plugins for t in p.tools] == ["Mine"]


def test_abstract_subclass_skipped(tmp_path):
    """A Tool subclass that never implements the abstract hooks is a base
    class, not a tool — instantiating it would raise TypeError."""
    _write(tmp_path, "base_extra.py", """
        from tools.base import Tool

        class StillAbstract(Tool):
            name = "Nope"
    """)
    plugins, errors = discover_plugins([tmp_path])
    assert plugins == [] and errors == []


def test_duplicate_stem_first_dir_wins(tmp_path):
    d1 = tmp_path / "app"
    d2 = tmp_path / "user"
    d1.mkdir(), d2.mkdir()
    _write(d1, "dup.py", GOOD)
    _write(d2, "dup.py", GOOD.replace('"Hello"', '"Second"'))
    plugins, _errors = discover_plugins([d1, d2])
    assert [t.name for p in plugins for t in p.tools] == ["Hello"]


# ---- The Extensions menu itself -------------------------------------------

def _extensions_menu(window):
    for menu_action in window.menuBar().actions():
        if menu_action.text().replace("&", "") == "Extensions":
            return menu_action.menu()
    raise AssertionError("no Extensions menu in the menubar")


@pytest.fixture
def main_window(tmp_path, monkeypatch):
    """A MainWindow whose plugin search is confined to tmp_path."""
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow

    def build():
        win = MainWindow()
        win.close()
        return win

    return build


def test_menu_lists_tools_and_disabled_errors(tmp_path, main_window):
    _write(tmp_path, "hello.py", GOOD)
    _write(tmp_path, "roto.py", "import modulo_que_no_existe\n")
    win = main_window()
    entries = {a.text(): a.isEnabled() for a in _extensions_menu(win).actions()}
    assert entries.get("Hello") is True
    assert any(t.startswith("⚠ roto") and not on for t, on in entries.items())
    assert "plugin_hello_HelloTool" in win._tools


def test_menu_placeholder_when_no_plugins(main_window):
    win = main_window()
    actions = _extensions_menu(win).actions()
    assert actions[0].text() == "(no plugins found)"
    assert not actions[0].isEnabled()
    # The plugin-author on-ramp is always at the bottom of the menu.
    texts = [a.text() for a in actions]
    assert "Open plugins folder" in texts
    assert "Develop a plugin…" in texts


def test_plugin_cannot_steal_a_builtin_shortcut(tmp_path, main_window):
    """'L' belongs to the Line tool; a plugin asking for it gets its menu
    entry without the shortcut instead of creating a Qt ambiguity that
    disables the key for both."""
    _write(tmp_path, "ladron.py", GOOD.replace(
        'name = "Hello"', 'name = "Ladron"\n        shortcut = "L"'))
    win = main_window()
    (action,) = [a for a in _extensions_menu(win).actions()
                 if a.text() == "Ladron"]
    assert action.shortcut().isEmpty()
    assert not win._tool_actions["line"].shortcut().isEmpty()


def test_fresh_shortcut_is_honoured(tmp_path, main_window):
    _write(tmp_path, "consola.py", GOOD.replace(
        'name = "Hello"',
        'name = "Consola"\n        shortcut = "Ctrl+Shift+P"'))
    win = main_window()
    (action,) = [a for a in _extensions_menu(win).actions()
                 if a.text() == "Consola"]
    assert action.shortcut().toString() == "Ctrl+Shift+P"


def test_activating_a_plugin_keeps_the_real_tool_active(tmp_path, main_window):
    """Plugin entries are one-shot: running one must not lie about the
    active drawing tool (PR #1 rewrote the status label without actually
    changing the tool)."""
    _write(tmp_path, "hello.py", GOOD.replace(
        "def on_activate(self, viewport):\n            pass",
        "def on_activate(self, viewport):\n            viewport._plugin_ran = True"))
    win = main_window()
    active_before = win.viewport.active_tool
    label_before = win._tool_label.text()
    win._activate_plugin_tool("plugin_hello_HelloTool")
    assert win.viewport._plugin_ran is True
    assert win.viewport.active_tool is active_before
    assert win._tool_label.text() == label_before
