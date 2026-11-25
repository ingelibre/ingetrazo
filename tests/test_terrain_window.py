# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draw ▸ Terrain in the window: Terrain from Scratch, Deform Terrain,
Stamp Platform and Drape are in the Draw menu's own submenu, pick up
their tool and have an icon; their Terrain toolbar starts hidden, can be
turned on, and Restore default toolbars puts it back off."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMenu

_app = QApplication.instance() or QApplication([])

KEYS = ("terrain_grid", "terrain_contours", "terrain_points",
        "terrain_height", "terrain_deform", "terrain_stamp", "terrain_drape")


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.hide()


def _terrain_menu(win):
    from core.i18n import tr
    draw = next(a.menu() for a in win.menuBar().actions()
                if a.menu() is not None and a.text() == tr("Draw"))
    return next(m for m in draw.findChildren(QMenu)
                if m.title() == tr("Terrain"))


def test_the_terrain_tools_are_in_draw_terrain(win):
    from tools.terrain import (TerrainDeformTool, TerrainDrapeTool,
                               TerrainGridTool, TerrainStampTool)
    assert isinstance(win._tools["terrain_grid"], TerrainGridTool)
    assert isinstance(win._tools["terrain_deform"], TerrainDeformTool)
    assert isinstance(win._tools["terrain_stamp"], TerrainStampTool)
    assert isinstance(win._tools["terrain_drape"], TerrainDrapeTool)
    menu = _terrain_menu(win)
    assert [win._tool_actions[k] for k in KEYS] == menu.actions()


def test_the_terrain_toolbar_holds_them_and_starts_hidden(win):
    from core.i18n import tr
    tb = win.toolbars["terrain"]
    assert tb.windowTitle() == tr("Terrain")
    assert tb.actions() == [win._tool_actions[k] for k in KEYS]
    assert not tb.isVisibleTo(win)
    assert not tb.toggleViewAction().isChecked()
    # No other toolbar carries them.
    for name, other in win.toolbars.items():
        if name != "terrain":
            assert not set(tb.actions()) & set(other.actions())


def test_the_terrain_toolbar_turns_on_and_restore_turns_it_off(win):
    tb = win.toolbars["terrain"]
    tb.toggleViewAction().trigger()
    _app.processEvents()
    assert tb.isVisibleTo(win)
    win.restore_default_toolbars()
    for _ in range(3):
        _app.processEvents()
    assert not tb.isVisibleTo(win)
    assert win.toolbars["draw"].isVisibleTo(win)


def test_f3_offers_the_terrain_toolbar_switch(win):
    """Hidden, the bar is still one F3 away: its switch is a command."""
    from views.command_search import commands
    switch = win.toolbars["terrain"].toggleViewAction()
    assert any(c.action is switch for c in commands(win))


def test_the_menu_entries_pick_up_the_tools(win):
    for key in KEYS:
        act = win._tool_actions[key]
        assert not act.icon().isNull()
        act.trigger()
        assert win.viewport.active_tool is win._tools[key]
        assert act.isChecked()


def test_a_saved_layout_keeps_it_on_and_an_older_one_leaves_it_off(win):
    """Turned on, the layout saved on close brings it back on; a layout
    saved before the bar existed (the factory one, a user's old one) does
    not know it and leaves it off."""
    from core.paths import app_root
    tb = win.toolbars["terrain"]
    tb.show()
    state = win.saveState()
    tb.hide()
    win.restoreState(state)
    assert tb.isVisibleTo(win)
    tb.hide()
    factory = app_root() / "resources" / "ui" / "default_layout.state"
    win.restoreState(factory.read_bytes())
    assert not tb.isVisibleTo(win)
