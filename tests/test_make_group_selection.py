# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Create group over a selection that is not plain loose geometry.

Reported as "I press Create group and it doesn't create": every group Marco
made put another group in the drawing, so his next rubber-band selection
included one, and the action refused — into the status bar, for five
seconds, while he was looking at the model. An empty selection returned in
total silence. Both now answer.
"""
from __future__ import annotations

import os

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMessageBox

from core.group import Group
from core.mesh import Mesh


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


@pytest.fixture
def win():
    from views.main_window import MainWindow
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QApplication.instance() is None:
        QApplication([])
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _quad(mesh, x0=0.0, y0=0.0):
    return mesh.add_face([V(x0, y0), V(x0 + 2, y0), V(x0 + 2, y0 + 2),
                          V(x0, y0 + 2)])


def _new_groups(scene, before):
    """Groups added since *before* — a fresh MainWindow already ships the
    startup template's scale figure, which is not what these tests measure."""
    known = {id(g) for g in before}
    return [g for g in scene.groups if id(g) not in known]


def _answer(monkeypatch, label_fragment):
    """Drive the dialog: click the button whose text contains *fragment*
    (None = Cancel). Returns a dict that records the button labels offered."""
    seen: dict = {}

    def fake_exec(self):
        seen["labels"] = [b.text() for b in self.buttons()]
        target = None
        if label_fragment is not None:
            target = next((b for b in self.buttons()
                           if label_fragment.lower() in b.text().lower()), None)
        if target is None:
            target = next(b for b in self.buttons()
                          if self.buttonRole(b)
                          == QMessageBox.ButtonRole.RejectRole)
        seen["clicked"] = target
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda self: seen.get("clicked"))
    return seen


def test_empty_selection_says_so_instead_of_going_silent(win):
    scene = win.viewport.scene
    scene.select([])
    win.statusBar().clearMessage()
    before = len(scene.groups)
    win._on_make_group()
    assert len(scene.groups) == before
    assert win.statusBar().currentMessage(), "the silent no-op is the bug"


def test_plain_loose_geometry_still_groups(win):
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    scene.select([f])
    before = len(scene.groups)
    win._on_make_group()
    assert len(scene.groups) == before + 1


def test_cancel_changes_nothing(win, monkeypatch):
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    g = Group(Mesh(), name="Banca")
    _quad(g.mesh, 10.0)
    scene.groups.append(g)
    scene.select([f, g])
    before = len(scene.groups)
    _answer(monkeypatch, None)
    win._on_make_group()
    assert len(scene.groups) == before


def test_group_only_the_loose_part_leaves_the_group_alone(win, monkeypatch):
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    g = Group(Mesh(), name="Banca")
    _quad(g.mesh, 10.0)
    scene.groups.append(g)
    scene.select([f, g])
    previos = list(scene.groups)
    seen = _answer(monkeypatch, "loose")
    win._on_make_group()
    assert len(seen["labels"]) == 3          # loose / explode / cancel
    assert g in scene.groups                 # untouched
    nuevo = _new_groups(scene, previos)
    assert len(nuevo) == 1
    assert len(nuevo[0].mesh.faces) == 1


def test_explode_and_group_it_all_absorbs_the_groups(win, monkeypatch):
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    g = Group(Mesh(), name="Banca")
    _quad(g.mesh, 10.0)
    _quad(g.mesh, 14.0)
    scene.groups.append(g)
    scene.select([f, g])
    previos = list(scene.groups)
    _answer(monkeypatch, "explode")
    win._on_make_group()
    assert g not in scene.groups, "the original group must be absorbed"
    nuevo = _new_groups(scene, previos)
    assert len(nuevo) == 1
    assert len(nuevo[0].mesh.faces) == 3     # 1 loose + 2 from the group


def test_explode_and_group_undoes_in_ONE_step(win, monkeypatch):
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    g = Group(Mesh(), name="Banca")
    _quad(g.mesh, 10.0)
    scene.groups.append(g)
    scene.select([f, g])
    before = [x.name for x in scene.groups]
    before_loose = len(scene.mesh.faces)
    _answer(monkeypatch, "explode")
    win._on_make_group()
    win.viewport.history.undo()
    assert [x.name for x in scene.groups] == before
    assert len(scene.mesh.faces) == before_loose


def test_a_group_with_NESTED_placements_keeps_its_insides(win, monkeypatch):
    """world_mesh folds children in, so absorbing a component does not
    quietly drop the geometry it placed inside itself."""
    from PySide6.QtGui import QMatrix4x4
    scene = win.viewport.scene
    hondo = Mesh()
    _quad(hondo, 0.0)
    hijo = Group(hondo, name="Tabla")
    hijo.xform = QMatrix4x4()
    padre = Group(Mesh(), name="Banca")
    _quad(padre.mesh, 20.0)
    padre.adopt([hijo])
    scene.groups.append(padre)
    scene.select([padre])
    previos = list(scene.groups)
    _answer(monkeypatch, "explode")
    win._on_make_group()
    nuevo = _new_groups(scene, previos)
    assert len(nuevo) == 1
    assert len(nuevo[0].mesh.faces) == 2, "the nested plank was lost"
