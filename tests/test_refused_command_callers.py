# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Callers stop when History refuses a command.

``History.execute`` took a refused command (``CommandRejected``) or a
failed one (rolled back) as a quiet no-op, and returned nothing, so a
caller could not tell. Simplify Mesh then read an empty undo stack
(IndexError), the Materials panel reported «updated» and moved the paint
tool to a material that was never stamped, and a plan opened on a new
sheet looked for a sheet that was never added (ValueError). Now
``execute`` says whether the command ran, and those callers stop."""
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
from core.history import Command, CommandRejected, History        # noqa: E402
from core.materials import Material                               # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from tools.paint import PaintTool                                 # noqa: E402

_REASON = "refused on purpose"


def _refuse(self, scene):
    raise CommandRejected(_REASON)


def _quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(4, 0, z),
                          QVector3D(4, 4, z), QVector3D(0, 4, z)])


class _Noop(Command):
    def do(self, scene):
        pass

    def undo(self, scene):
        pass


class _Refused(_Noop):
    do = _refuse


class _Broken(_Noop):
    def do(self, scene):
        raise RuntimeError("boom")


def test_execute_says_whether_the_command_ran():
    history = History(Scene())
    assert history.execute(_Noop()) is True
    assert len(history.undo_stack) == 1
    assert history.execute(_Refused()) is False
    assert history.last_rejected == _REASON
    assert history.execute(_Broken()) is False
    assert history.last_error
    assert len(history.undo_stack) == 1


@pytest.fixture
def window():
    from views.main_window import MainWindow
    saved = (PaintTool.recent, PaintTool.current_material,
             PaintTool.current_color, PaintTool.current_texture,
             PaintTool.current_is_default)
    PaintTool.recent = []
    w = MainWindow()
    try:
        yield w
    finally:
        w.viewport.scene.end_group_edit()
        w._saved_version = w.viewport.scene.version
        w.close()
        (PaintTool.recent, PaintTool.current_material,
         PaintTool.current_color, PaintTool.current_texture,
         PaintTool.current_is_default) = saved


def test_simplify_mesh_stops_when_refused(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from core.history import SimplifyMeshCommand
    _quad(window.viewport.scene.mesh)
    window.viewport.history.undo_stack.clear()
    monkeypatch.setattr(QInputDialog, "getDouble",
                        staticmethod(lambda *a, **k: (1.0, True)))
    monkeypatch.setattr(SimplifyMeshCommand, "do", _refuse)
    said = []
    monkeypatch.setattr(window.viewport, "flash_status",
                        lambda text, *a, **k: said.append(text))
    window._on_simplify_mesh()                  # IndexError before the fix
    assert said == [_REASON]
    assert window.viewport.history.undo_stack == []


def test_restamp_stops_when_refused(window, monkeypatch):
    import views.tray as T
    from core.history import RestampMaterialCommand
    panel = window.findChild(T.MaterialsPanel)
    azul = Material("Azul", color=(0.1, 0.4, 0.9))
    window.viewport.scene.materials["Azul"] = azul
    face = _quad(window.viewport.scene.mesh)
    face.attrs.update(azul.face_attrs())
    PaintTool.current_material = azul
    monkeypatch.setattr(RestampMaterialCommand, "do", _refuse)
    new = Material("Azul", color=(0.9, 0.1, 0.1))
    assert panel._restamp("Azul", new) is False
    assert PaintTool.current_material is azul
    assert window.statusBar().currentMessage() == _REASON


def test_a_plan_on_a_sheet_stops_when_refused(window, monkeypatch):
    from core.history import CreatePlanCommand
    scene = window.viewport.scene
    group = Group(Mesh(), name="Slab")
    _quad(group.mesh)
    scene.groups[:] = [group]
    scene.version += 1
    panel = window.project_browser.outliner
    sheets0 = list(scene.compositions)
    monkeypatch.setattr(CreatePlanCommand, "do", _refuse)
    # ValueError before the fix: the sheet to open was never added.
    view = panel.create_plan(group, 1.2, sheet=True, open_sheet=True)
    assert view is None
    assert scene.compositions == sheets0
