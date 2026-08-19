# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid Inspector plugin: the diagnosis must agree with the engine.

The verdicts and volumes come from the same primitives the BIM layer
uses, so whatever this dialog says must match what the takeoff would do."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from plugins.solid_inspector import (                             # noqa: E402
    SolidInspectorDialog, SolidInspectorTool, inspect_mesh)


def _box(mesh, x0=0.0, y0=0.0, z0=0.0, dx=2.0, dy=2.0, dz=2.0,
         skip_top=False):
    """An axis-aligned box with consistent outward windings (the floor is
    clockwise seen from above — the showcase-script lesson)."""
    P = QVector3D
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    quads = [
        [P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0), P(x0, y0, z0)],
        [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)],
        [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)],
        [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)],
        [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
    ]
    if not skip_top:
        quads.append([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1),
                      P(x0, y1, z1)])
    return [mesh.add_face(q) for q in quads]


# ---- Diagnosis ------------------------------------------------------------

def test_closed_cube_is_watertight_with_volume():
    mesh = Mesh()
    _box(mesh)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is True
    assert rep["open"] == [] and rep["stray"] == [] and rep["over"] == []
    assert abs(rep["volume"] - 8.0) < 1e-6          # 2 × 2 × 2


def test_open_box_reports_the_rim():
    """A box without its top: the four rim edges are open borders — the
    exact edges a user needs to see to close the hole."""
    mesh = Mesh()
    _box(mesh, skip_top=True)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is False
    assert len(rep["open"]) == 4
    assert rep["volume"] is None
    for e in rep["open"]:
        assert abs(e.v0.position.z() - 2.0) < 1e-6   # all on the top rim
        assert abs(e.v1.position.z() - 2.0) < 1e-6


def test_stray_edge_detected():
    mesh = Mesh()
    _box(mesh)
    mesh.add_edge(QVector3D(10, 10, 0), QVector3D(12, 10, 0))
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is False
    assert len(rep["stray"]) == 1 and rep["open"] == []


def test_internal_wall_is_overconnected_but_interior_flag_heals():
    """Two boxes sharing a wall: the shared edges see 3 faces —
    overconnected. Marked interior (what core.orient does), the wall stops
    counting and the union is watertight again — same rule as the engine."""
    mesh = Mesh()
    _box(mesh, dx=2.0)
    shared = _box(mesh, x0=2.0, dx=2.0)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is False and len(rep["over"]) == 4

    # The wall between the boxes is the first quad of the second box's
    # x0-plane... find it: the face whose 4 verts all sit at x == 2.
    for f in mesh.faces:
        if all(abs(v.position.x() - 2.0) < 1e-6 for v in f.loop):
            f.interior = True
    rep2 = inspect_mesh(mesh)
    assert rep2["watertight"] is True
    assert abs(rep2["volume"] - 16.0) < 1e-6         # 4 × 2 × 2 shell


def test_empty_mesh_is_not_a_solid():
    rep = inspect_mesh(Mesh())
    assert rep["watertight"] is False and rep["volume"] is None


# ---- Dialog ---------------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_dialog_rows_and_highlight(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)                  # broken loose solid
    g = Group(Mesh(), name="Caja OK")
    _box(g.mesh)                                     # closed group
    scene.groups.append(g)

    dlg = SolidInspectorDialog(win.viewport, parent=win)
    names = [dlg._table.item(i, 0).text()
             for i in range(dlg._table.rowCount())]
    assert names[0] == "Loose geometry" and "Caja OK" in names
    # The scale figure is a billboard — flat by design, never listed.
    assert not any(getattr(g, "billboard", False) and g.name in names
                   for g in scene.groups)
    assert "Sumari" not in names

    # The group row shows its closed volume.
    i_g = names.index("Caja OK")
    assert "8.000" in dlg._table.item(i_g, 4).text()

    # Highlighting the active row selects the 4 rim edges in the viewport.
    dlg._table.setCurrentCell(0, 0)
    dlg.highlight()
    assert len(scene.selection) == 4
    assert all(e in scene.mesh.edges for e in scene.selection)

    # Highlighting the group row selects the group itself.
    dlg._table.setCurrentCell(i_g, 0)
    dlg.highlight()
    assert scene.selection == {g}
    dlg.close()


def test_dialog_group_edit_context(win):
    """Inside a group the active row inspects THAT mesh, and the group's
    own listing row is not duplicated."""
    scene = win.viewport.scene
    g = Group(Mesh(), name="Caseta")
    _box(g.mesh, skip_top=True)
    scene.groups.append(g)
    scene.begin_group_edit(g)
    try:
        dlg = SolidInspectorDialog(win.viewport, parent=win)
        names = [dlg._table.item(i, 0).text()
                 for i in range(dlg._table.rowCount())]
        assert names[0] == "Open group: Caseta"
        assert names.count("Caseta") == 0            # not listed twice
        assert "4 open borders" in dlg._table.item(0, 3).text()
        dlg.close()
    finally:
        scene.end_group_edit()


def test_tool_metadata_and_singleton(win):
    tool = SolidInspectorTool()
    assert tool.name == "Solid Inspector"
    assert tool.shortcut is None and tool.uses_snap is False
    tool.on_activate(win.viewport)
    first = win._solid_inspector
    tool.on_activate(win.viewport)
    assert win._solid_inspector is first
    first.close()
