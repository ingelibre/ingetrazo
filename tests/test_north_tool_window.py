# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tools ▸ North in the window: in the Tools menu and the Annotate bar, and
the Shadows panel's North field — typed there, one undo step, kept in step
with what the tool sets."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.hide()


def test_the_tool_is_in_the_tools_menu_and_the_annotate_bar(win):
    from tools.north import NorthTool
    assert isinstance(win._tools["north"], NorthTool)
    act = win._tool_actions["north"]
    assert act in win.toolbars["annotate"].actions()
    menus = [a.menu() for a in win.menuBar().actions() if a.menu()]
    assert any(act in m.actions() for m in menus)


def test_shift_n_picks_up_the_tool(win):
    from PySide6.QtGui import QKeySequence
    act = win._tool_actions["north"]
    assert QKeySequence("Shift+N") in act.shortcuts()
    act.trigger()
    assert win.viewport.active_tool is win._tools["north"]


def test_shadows_panel_north_field_sets_and_follows(win):
    panel = win.shadows_panel
    scene = win.viewport.scene
    panel._north.setValue(-60.0)
    panel._on_north_edited()
    assert scene.north_deg == pytest.approx(-60.0)
    win.viewport.history.undo()
    assert scene.north_deg == 0.0
    # Aimed with the tool: the field shows it next time.
    win._tools["north"].commit(win.viewport, 15.0)
    panel.refresh()
    assert panel._north.value() == pytest.approx(15.0)


def test_the_on_screen_button_picks_up_the_tool(win):
    win.shadows_panel._on_north_tool()
    assert win.viewport.active_tool is win._tools["north"]
