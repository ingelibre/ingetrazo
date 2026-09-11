# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Grouping with a group selected must refuse, not half-do it.

Nested groups are not supported yet. The actions filtered the selection down
to loose faces and edges, so selecting a group plus loose geometry and
grouping produced a group of the loose part with the group silently left out —
the wrong result dressed as success. Marco's flow is exactly that: group some
planks, place them in a bench, group again.

Make Group now ANSWERS instead of whispering into the status bar: it asks,
offering the two results that are actually reachable. Cancelling is the
refusal these tests are about, so they drive the dialog that way — see
tests/test_make_group_selection.py for the paths that accept.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

import pytest  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from core.history import AddFaceCommand, MakeGroupCommand  # noqa: E402


@pytest.fixture
def cancels(monkeypatch):
    """Answer Make Group's dialog with Cancel, and report whether it
    was actually shown — a silent refusal would pass these asserts too,
    and silence is the bug they exist to prevent."""
    shown = {"count": 0, "labels": []}

    def fake_exec(self):
        shown["count"] += 1
        shown["labels"] = [b.text() for b in self.buttons()]
        shown["button"] = next(
            b for b in self.buttons()
            if self.buttonRole(b) == QMessageBox.ButtonRole.RejectRole)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda self: shown.get("button"))
    return shown


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _win_with_a_group_and_loose_geometry():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    hist = win.viewport.history
    hist.execute(AddFaceCommand([V(0, 0), V(1, 0), V(1, 1), V(0, 1)]))
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    hist.execute(AddFaceCommand([V(3, 0), V(4, 0), V(4, 1), V(3, 1)]))
    return win, scene


def test_grouping_a_group_with_loose_geometry_NESTS_it(cancels):
    """Esto se negaba, y con razón mientras entrar a un contenedor lo
    horneaba. Con la pila de contextos (2026-09-11) ya no: agrupar una cara
    suelta junto a un grupo mete la cara en la malla del contenedor nuevo y
    el grupo pasa a ser su hijo — lo que hace SketchUp."""
    win, scene = _win_with_a_group_and_loose_geometry()
    try:
        antes = list(scene.groups)
        sueltas = len(scene.mesh.faces)
        scene.selection.clear()
        scene.selection.update(set(scene.mesh.faces) | set(scene.groups))
        win._on_make_group()
        assert cancels["count"] == 0, "ya no hay nada que preguntar"
        nuevos = [g for g in scene.groups if g not in antes]
        assert len(nuevos) == 1
        padre = nuevos[0]
        assert padre.children == antes, "el grupo viejo es ahora su hijo"
        assert len(padre.mesh.faces) == 1        # la cara suelta
        assert len(scene.mesh.faces) == sueltas - 1
    finally:
        win._saved_version = scene.version      # closeEvent asks otherwise
        win.close()


def test_grouping_only_loose_geometry_still_works():
    win, scene = _win_with_a_group_and_loose_geometry()
    try:
        before = len(scene.groups)
        scene.selection.clear()
        scene.selection.update(scene.mesh.faces)
        win._on_make_group()
        assert len(scene.groups) == before + 1
    finally:
        win._saved_version = scene.version
        win.close()


def test_component_from_loose_geometry_plus_a_group_refuses():
    win, scene = _win_with_a_group_and_loose_geometry()
    try:
        before = len(scene.groups)
        scene.selection.clear()
        scene.selection.update(set(scene.mesh.faces) | set(scene.groups))
        win._on_make_component()
        assert len(scene.groups) == before
        assert scene.mesh.faces
    finally:
        win._saved_version = scene.version
        win.close()
