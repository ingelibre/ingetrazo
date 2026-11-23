# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Variables tab and the value box: a variable defined in the panel
is read by «=ancho/2» while drawing, every edit can be undone, and the tab
waits in Window ▸ Panels until it is opened."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import units  # noqa: E402
from views.variables_panel import COL_NAME, COL_RESULT, COL_VALUE  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    units.bind_scene(w.viewport.scene)
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()
    units.bind_scene(None)


def _type(vp, text):
    for ch in text:
        vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch))


def _enter(vp):
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                               Qt.NoModifier, "\r"))


def _set_cell(panel, row, col, text):
    panel.table.item(row, col).setText(text)


def test_the_tab_is_in_the_tray_and_starts_closed(win):
    dock = win.variables_dock
    assert dock.objectName() == "tray_variables"
    assert dock in win._sidebar_docks()
    assert "tray_variables" in win._hidden_tray_names(QSettings())
    assert dock.property("icon_key") == "panel_variables"


def test_add_rename_and_value_go_through_history(win):
    panel = win.variables_dock.panel
    vp = win.viewport
    name = panel.add_variable()
    assert vp.scene.variables == {name: "0"}
    _set_cell(panel, 0, COL_NAME, "ancho")
    _set_cell(panel, 0, COL_VALUE, "3.20m")
    assert vp.scene.variables == {"ancho": "3.20m"}
    assert "3" in panel.table.item(0, COL_RESULT).text()
    vp.history.undo()
    assert vp.scene.variables == {"ancho": "0"}
    vp.history.undo()
    assert vp.scene.variables == {name: "0"}
    vp.history.redo()
    vp.history.redo()
    assert vp.scene.variables == {"ancho": "3.20m"}


def test_a_bad_name_is_refused_with_a_reason(win):
    panel = win.variables_dock.panel
    vp = win.viewport
    panel.add_variable()
    _set_cell(panel, 0, COL_NAME, "ancho")
    panel.add_variable()
    _set_cell(panel, 1, COL_NAME, "cm")
    assert "cm" not in vp.scene.variables
    assert not panel.message.isHidden()
    _set_cell(panel, 1, COL_NAME, "Ancho")             # taken, any case
    assert list(vp.scene.variables)[0] == "ancho"
    assert len(vp.scene.variables) == 2


def test_renaming_follows_into_the_calculations(win):
    panel = win.variables_dock.panel
    vp = win.viewport
    vp.history.execute(__import__("core.history", fromlist=["x"])
                       .SetVariablesCommand({"ancho": "3m",
                                             "media": "=ancho/2"}))
    panel.refresh()
    _set_cell(panel, 0, COL_NAME, "luz")
    assert vp.scene.variables == {"luz": "3m", "media": "=luz/2"}


def test_remove_selected(win):
    panel = win.variables_dock.panel
    vp = win.viewport
    panel.add_variable()
    panel.add_variable()
    panel.table.selectRow(0)
    panel.remove_selected()
    assert list(vp.scene.variables) == ["variable2"]


def test_an_error_shows_in_the_result_column(win):
    panel = win.variables_dock.panel
    panel.add_variable()
    _set_cell(panel, 0, COL_VALUE, "=alto*2")
    assert "alto" in panel.table.item(0, COL_RESULT).text()


def test_a_line_drawn_from_a_variable(win):
    from core.history import SetVariablesCommand
    vp = win.viewport
    vp.history.execute(SetVariablesCommand({"ancho": "3.20m"}))
    win._activate_tool("line")
    tool = vp.active_tool
    tool.start_point = QVector3D(0, 0, 0)
    tool.hover_point = QVector3D(1, 0, 0)
    _type(vp, "=ancho/2")
    assert vp._value_buffer == "=ancho/2"              # letters type in
    _enter(vp)
    edges = list(vp.scene.mesh.edges)
    assert len(edges) == 1
    edge = edges[0]
    a, b = edge.v0.position, edge.v1.position
    assert (b - a).length() == pytest.approx(1.6, abs=1e-6)


def test_an_unknown_variable_stays_in_the_box(win):
    vp = win.viewport
    win._activate_tool("line")
    flashed = []
    vp.flash_status = lambda text, ms=0: flashed.append(text)
    tool = vp.active_tool
    tool.start_point = QVector3D(0, 0, 0)
    tool.hover_point = QVector3D(1, 0, 0)
    _type(vp, "=alto/2")
    _enter(vp)
    assert vp._value_buffer == "=alto/2"
    assert flashed and "alto" in flashed[0]
