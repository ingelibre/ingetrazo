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


def test_agrupar_un_grupo_lo_ANIDA(win):
    """Lo que antes era un diálogo pidiendo perdón. Un grupo puede contener
    grupos desde el 2026-09-11, así que agrupar hace lo que dice."""
    scene = win.viewport.scene
    g1 = Group(Mesh(), name="Banca")
    _quad(g1.mesh, 10.0)
    g2 = Group(Mesh(), name="Pérgola")
    _quad(g2.mesh, 14.0)
    scene.groups += [g1, g2]
    scene.select([g1, g2])
    previos = list(scene.groups)
    win._on_make_group()
    assert g1 not in scene.groups and g2 not in scene.groups
    nuevo = _new_groups(scene, previos)
    assert len(nuevo) == 1
    padre = nuevo[0]
    assert padre.children == [g1, g2], "los grupos son HIJOS, no se fundieron"
    assert len(g1.mesh.faces) == 1 and len(g2.mesh.faces) == 1
    assert padre.xform is not None, "un contenedor es siempre instancia"


def test_lo_suelto_de_la_selección_va_a_la_malla_del_contenedor(win):
    """Como SketchUp: dentro del grupo nuevo encuentras las caras sueltas Y
    el grupo, cada uno como lo que era."""
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    g = Group(Mesh(), name="Banca")
    _quad(g.mesh, 10.0)
    scene.groups.append(g)
    scene.select([f, g])
    previos = list(scene.groups)
    sueltas_antes = len(scene.mesh.faces)
    win._on_make_group()
    nuevo = _new_groups(scene, previos)
    assert len(nuevo) == 1
    padre = nuevo[0]
    assert padre.children == [g]
    assert len(padre.mesh.faces) == 1, "la cara suelta es la malla del padre"
    assert len(scene.mesh.faces) == sueltas_antes - 1
    assert len(g.mesh.faces) == 1, "la banca sigue entera"


def test_anidar_se_deshace_en_UN_paso(win):
    scene = win.viewport.scene
    f = _quad(scene.mesh)
    g = Group(Mesh(), name="Banca")
    _quad(g.mesh, 10.0)
    scene.groups.append(g)
    scene.select([f, g])
    antes = [x.name for x in scene.groups]
    sueltas = len(scene.mesh.faces)
    win._on_make_group()
    assert win.viewport.history.undo() is True
    assert [x.name for x in scene.groups] == antes
    assert len(scene.mesh.faces) == sueltas
    assert g.children == [], "y la banca no se queda adoptada"


def test_un_grupo_con_hijos_se_anida_sin_perderlos(win):
    """Anidar un contenedor dentro de otro: el árbol crece, no se aplana."""
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
    win._on_make_group()
    nuevo = _new_groups(scene, previos)
    assert len(nuevo) == 1
    abuelo = nuevo[0]
    assert abuelo.children == [padre]
    assert padre.children == [hijo], "el nieto sigue ahí"
    assert len(hijo.mesh.faces) == 1
