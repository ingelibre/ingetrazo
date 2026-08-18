# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Python Console plugin: executions are honest citizens of the document.

The regression targets are PR #3's three sins: code ran outside the command
layer (no Ctrl+Z, no dirty flag, no repaint — scene.version never moved), a
failing script left half its mutations behind, and the scope captured the
scene once at open (stale after New/Open or entering a group)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from plugins.python_console import (                              # noqa: E402
    PythonConsoleDialog, PythonConsoleTool)


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    # Console runs DO dirty the document (that is the feature); mark it
    # saved before closing or closeEvent's modal "Quit IngeTrazo?" box
    # blocks forever under the offscreen platform.
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.fixture
def console(win):
    dlg = PythonConsoleDialog(win.viewport, parent=win)
    yield dlg
    dlg.close()


ADD_FACE = ("mesh.add_face([QVector3D(0,0,0), QVector3D(1,0,0), "
            "QVector3D(1,1,0), QVector3D(0,1,0)])")


def test_tool_metadata():
    tool = PythonConsoleTool()
    assert tool.name == "Python Console"
    assert tool.shortcut == "Ctrl+Shift+P"
    assert tool.uses_snap is False


def test_mutation_is_undoable_and_dirties(console, win):
    """PR #3 regression: exec ran outside the command layer, so scripted
    geometry had no Ctrl+Z, never marked the document dirty, and the VBO
    rebuild (keyed on scene.version) never saw it."""
    scene = win.viewport.scene
    faces0 = len(scene.mesh.faces)
    depth0 = len(win.viewport.history.undo_stack)
    version0 = scene.version

    console._run_code(ADD_FACE, "<test>")

    assert len(scene.mesh.faces) == faces0 + 1
    assert len(win.viewport.history.undo_stack) == depth0 + 1   # one step
    assert scene.version > version0                             # dirty+repaint
    assert scene.version != win._saved_version                  # asks to save

    assert win.viewport.history.undo()                          # Ctrl+Z
    assert len(scene.mesh.faces) == faces0


def test_inspection_leaves_no_undo_entry(console, win):
    history = win.viewport.history
    console._run_code(ADD_FACE, "<test>")           # a real step to protect
    depth = len(history.undo_stack)

    console._run_code("print(len(mesh.faces))", "<test>")

    assert len(history.undo_stack) == depth         # no phantom entry
    assert "1" in console._output.toPlainText()

    # ... and it must not have eaten the redo stack either.
    history.undo()
    console._run_code("len(mesh.faces)", "<test>")
    assert history.redo()                           # redo still available


def test_failing_script_rolls_back_whole(console, win):
    """PR #3 regression: an exception mid-script left the geometry created
    before the raise. One command = all-or-nothing."""
    scene = win.viewport.scene
    faces0 = len(scene.mesh.faces)
    depth0 = len(win.viewport.history.undo_stack)

    console._run_code(ADD_FACE + "\nraise RuntimeError('a medio camino')",
                      "<test>")

    assert len(scene.mesh.faces) == faces0          # nothing half-applied
    assert len(win.viewport.history.undo_stack) == depth0
    out = console._output.toPlainText()
    assert "RuntimeError" in out and "a medio camino" in out


def test_scope_rebinds_to_the_current_mesh(console, win):
    """PR #3 regression: the scope captured scene.mesh once at open; after
    entering a group (or New/Open) it pointed at the wrong mesh."""
    scene = win.viewport.scene
    group = scene.groups[0]                         # the scale figure
    scene.begin_group_edit(group)
    try:
        console._run_code("es_del_grupo = mesh is scene.mesh", "<test>")
        assert console._scope["es_del_grupo"] is True
        assert console._scope["mesh"] is group.mesh
    finally:
        scene.end_group_edit()
    console._run_code("pass", "<test>")
    assert console._scope["mesh"] is scene.mesh     # re-bound after leaving


def test_expression_result_shown_and_kept(console):
    console._run_code("2 + 40", "<test>")
    assert "42" in console._output.toPlainText()
    assert console._scope["_"] == 42


def test_one_console_per_window(win):
    tool = PythonConsoleTool()
    tool.on_activate(win.viewport)
    first = win._python_console
    tool.on_activate(win.viewport)
    assert win._python_console is first
    first.close()


def test_showcase_script_produces_real_bim(console, win):
    """The demo script must build geometry the BIM layer actually sees —
    tagged through core.bim, undoable as a single step."""
    from core import bim
    scene = win.viewport.scene
    depth0 = len(win.viewport.history.undo_stack)
    source = open("scripts/create_architectural_showcase.py").read()

    console._scope["__file__"] = "scripts/create_architectural_showcase.py"
    console._run_code(source, "showcase")

    objects = bim.collect_objects(scene)
    classes = {o["class"] for o in objects}
    assert {"IfcSlab", "IfcColumn", "IfcWall", "IfcRoof"} <= classes
    assert len([o for o in objects if o["class"] == "IfcColumn"]) == 4

    # The quantities must be the REAL ones. The script once wound the boxes'
    # bottom faces backwards, and the signed-volume sum reported 3.20 m³ for
    # the 9.60 m³ floor slab and 122.03 m³ (!) for the 8.51 m³ roof — caught
    # by an engineer reading the numbers on a screenshot.
    by_name = {o["name"]: o for o in objects}
    assert abs(by_name["Losa de piso"]["volume"] - 8.0 * 6.0 * 0.20) < 1e-4
    assert abs(by_name["Cubierta"]["volume"] - 8.6 * 6.6 * 0.15) < 1e-4
    for o in objects:
        if o["class"] == "IfcColumn":
            assert abs(o["volume"] - 0.30 * 0.30 * 3.0) < 1e-4
    assert len(win.viewport.history.undo_stack) == depth0 + 1

    assert win.viewport.history.undo()              # one Ctrl+Z, all gone
    assert bim.collect_objects(scene) == []
    assert not any(g.name.startswith("Columna") for g in scene.groups)
