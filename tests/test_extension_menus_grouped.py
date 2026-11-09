# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The extensions' menu entries, grouped (Marco, 18-10).

With the whole catalog installed the right-click menu was taller than the
screen (Qt split it in two columns) and the Extensions menu had 62 lines:
one extension's several entries now go into a submenu with its name, the
right-click entries under «Extensions ▸» when there are many, and the
Extensions menu by catalog category when there are many extensions.
Preferences ▸ General ▸ Extension menus picks the way, «flat» as before."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

import core.extensions as extensions  # noqa: E402
from core import general_settings as _gs  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    w = MainWindow()
    w.load_extensions()
    w._ext_catalog_info = {}            # no catalog: names from the ids
    yield w
    _gs.set_value("ext_menus", "auto")
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _context_menu(win, monkeypatch):
    """The right-click menu the window would open, without opening it."""
    import views.main_window as mw
    shown = []

    class _Menu(QMenu):
        def exec(self, *a, **k):            # noqa: A003 — Qt name
            shown.append(self)

    monkeypatch.setattr(mw, "QMenu", _Menu)
    win.show_viewport_context_menu(win.viewport.mapToGlobal(
        win.viewport.rect().center()))
    monkeypatch.setattr(mw, "QMenu", QMenu)
    return shown[0]


def _texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _sub(menu, title):
    return next(a.menu() for a in menu.actions()
                if a.menu() is not None and a.text() == title)


def _extension(win, key, entries):
    from views.extension_api import ExtensionApp
    app = ExtensionApp(win, key)

    def fill(menu, _sel):
        for text in entries:
            menu.addAction(text, lambda: None)
    app.add_context_menu(fill)
    return app


def _select_a_face(win):
    m = win.viewport.scene.mesh
    f = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    win.viewport.scene.selection.add(f)


def test_a_few_extensions_keep_their_entries_in_the_menu(win, monkeypatch):
    _extension(win, "alpha_tool", ["Alpha…"])
    _extension(win, "beta_tool", ["Beta one", "Beta two"])
    menu = _context_menu(win, monkeypatch)
    texts = _texts(menu)
    assert "Alpha…" in texts                       # one entry: as it is
    assert "Beta tool" in texts                    # several: its submenu
    assert _texts(_sub(menu, "Beta tool")) == ["Beta one", "Beta two"]
    assert "Extensions" not in texts


def test_many_extensions_go_under_one_submenu(win, monkeypatch):
    n = win.EXT_CONTEXT_INLINE + 1
    for i in range(n):
        _extension(win, f"ext_{i}", [f"Entry {i}"])
    menu = _context_menu(win, monkeypatch)
    texts = _texts(menu)
    assert not any(t.startswith("Entry ") for t in texts)
    assert _texts(_sub(menu, "Extensions")) == [f"Entry {i}" for i in range(n)]


def test_always_and_flat_follow_the_preference(win, monkeypatch):
    _extension(win, "alpha_tool", ["Alpha…"])
    _extension(win, "beta_tool", ["Beta one", "Beta two"])
    _gs.set_value("ext_menus", "always")
    menu = _context_menu(win, monkeypatch)
    assert "Alpha…" not in _texts(menu)
    assert "Alpha…" in _texts(_sub(menu, "Extensions"))
    _gs.set_value("ext_menus", "flat")
    menu = _context_menu(win, monkeypatch)
    texts = _texts(menu)
    assert {"Alpha…", "Beta one", "Beta two"} <= set(texts)   # as before
    assert "Extensions" not in texts and "Beta tool" not in texts


def test_an_extension_that_raises_does_not_stop_the_menu(win, monkeypatch):
    from views.extension_api import ExtensionApp

    def broken(_menu, _sel):
        raise RuntimeError("an extension's bug")
    ExtensionApp(win, "broken_tool").add_context_menu(broken)
    _extension(win, "alpha_tool", ["Alpha…"])
    menu = _context_menu(win, monkeypatch)
    assert "Alpha…" in _texts(menu)
    assert "Broken tool" not in _texts(menu)       # nothing, not an empty one


def test_make_component_shows_once_with_loose_geometry_and_a_group(
        win, monkeypatch):
    from core.group import Group
    from core.history import InsertGroupCommand
    from core.mesh import Mesh
    gm = Mesh()
    gm.add_face([V(3, 0, 0), V(4, 0, 0), V(4, 1, 0), V(3, 1, 0)])
    g = Group(gm, name="G")
    win.viewport.history.execute(InsertGroupCommand(g))
    _select_a_face(win)
    win.viewport.scene.selection.add(g)
    menu = _context_menu(win, monkeypatch)
    from core.i18n import tr
    assert _texts(menu).count(tr("Make Component…")) == 1


def test_one_extensions_loose_entries_share_a_submenu(win):
    from views.extension_api import ExtensionApp
    app = ExtensionApp(win, "display_thing")
    for t in ("Bigger", "Smaller", "Reset"):
        app.add_menu_action(t, lambda: None)
    ExtensionApp(win, "solo_tool").add_menu_action("Solo…", lambda: None)
    win._group_extension_menu()
    texts = _texts(win._ext_menu)
    assert "Display thing" in texts and "Solo…" in texts
    assert not {"Bigger", "Smaller", "Reset"} & set(texts)
    assert _texts(_sub(win._ext_menu, "Display thing")) == [
        "Bigger", "Smaller", "Reset"]


def test_many_extensions_go_by_catalog_category(win):
    from views.extension_api import ExtensionApp
    n = win.EXT_MENU_INLINE + 1
    win._ext_catalog_info = {
        f"ext_{i}": (f"Ext {i}", ("drawing",) if i % 2 else ("rendering",))
        for i in range(n)}
    for i in range(n):
        ExtensionApp(win, f"ext_{i}").add_menu_action(f"Ext {i}…", lambda: None)
    ExtensionApp(win, "unknown_tool").add_menu_action("Unknown…", lambda: None)
    win._group_extension_menu()
    texts = _texts(win._ext_menu)
    from core.i18n import tr
    assert tr("Drawing") in texts and tr("Rendering") in texts
    assert "Unknown…" in texts                     # not in the catalog: top
    assert not any(t.startswith("Ext ") for t in texts)
    # the categories sit together, above the menu's own entries
    i_cat = texts.index(tr("Drawing"))
    assert texts.index(tr("Rendering")) == i_cat + 1
    assert texts.index(tr("Manage extensions…")) > i_cat


def test_a_tall_extension_panel_scrolls_so_the_window_fits_the_screen(win):
    """One extension's panel asked for 652 px and the window needed 902 px
    of a screen with 890: GNOME would not maximize it (Marco, 18-10)."""
    from PySide6.QtWidgets import QDockWidget, QScrollArea, QWidget
    from PySide6.QtCore import Qt
    win.show()
    _app.processEvents()
    screen_h = win.screen().availableGeometry().height()
    tall = QWidget()
    tall.setMinimumHeight(screen_h + 200)
    dock = QDockWidget("Tall", win)
    dock.setObjectName("extension_tall")
    dock.setWidget(tall)
    win.addDockWidget(Qt.RightDockWidgetArea, dock)
    _app.processEvents()
    assert win.minimumSizeHint().height() > screen_h
    win._fit_docks_to_screen()
    assert isinstance(dock.widget(), QScrollArea)
    assert dock.widget().widget() is tall           # the same panel, inside
    assert win.minimumSizeHint().height() < screen_h + 200
    # a short panel is left alone
    short = QDockWidget("Short", win)
    short.setWidget(QWidget())
    win.addDockWidget(Qt.RightDockWidgetArea, short)
    win._fit_docks_to_screen()
    assert not isinstance(short.widget(), QScrollArea)
