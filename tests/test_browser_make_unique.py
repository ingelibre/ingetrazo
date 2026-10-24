# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser's right-click on component rows (#87, #620): «Make Unique»,
every chosen copy a group of its own with a name of its own, as ONE undo
step; «Select Instances (n)», every copy of the same components — nested
ones too — selected in the view. Inside a component, Make Unique is greyed
with the reason."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group, copy_group
from core.i18n import tr
from core.mesh import Mesh


def _quad(x=0.0):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return m


def _setup():
    from views.main_window import MainWindow
    win = MainWindow()
    silla = Group(_quad(), name="Silla")
    silla.xform = QMatrix4x4()
    b = copy_group(silla, V(2, 0, 0))
    c = copy_group(silla, V(4, 0, 0))
    comedor = Group(_quad(8.0), name="Comedor")
    comedor.xform = QMatrix4x4()
    comedor.component = False
    d = copy_group(silla, V(6, 0, 0))
    comedor.children = [d]                      # a copy inside a group
    muro = Group(_quad(12.0), name="Muro")
    scene = win.viewport.scene
    scene.groups[:] = [silla, b, c, comedor, muro]
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel, (silla, b, c, d, comedor, muro)


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _menu(panel, item):
    """``{text: (enabled, tooltip)}`` of the row's menu, read open."""
    found = {}

    def read():
        m = QApplication.activePopupWidget()
        if m is None:
            QTimer.singleShot(10, read)
            return
        for a in m.actions():
            found[a.text()] = (a.isEnabled(), a.toolTip())
        m.close()
    QTimer.singleShot(0, read)
    panel._on_context_menu(panel.tree.visualItemRect(item).center())
    return found


def test_the_menu_offers_both_on_a_component_and_neither_on_a_group():
    win, scene, panel, (silla, b, c, d, comedor, muro) = _setup()
    try:
        entries = _menu(panel, panel._items[id(b)])
        assert entries[tr("Make Unique")][0]
        assert tr("Select Instances ({n})", n=4) in entries   # 3 + nested
        plain = _menu(panel, panel._items[id(muro)])
        assert tr("Make Unique") not in plain
    finally:
        _close(win)


def test_make_unique_on_several_rows_is_one_undo_step_with_own_names():
    win, scene, panel, (silla, b, c, d, comedor, muro) = _setup()
    try:
        steps = len(win.viewport.history.undo_stack)
        assert panel.make_unique_rows([b, c])
        # components of their own, each its definition (#620)
        assert b.is_component() and c.is_component()
        assert b.mesh is not silla.mesh and c.mesh is not silla.mesh
        assert b.mesh is not c.mesh
        assert {b.name, c.name} == {"Silla #2", "Silla #3"}
        assert silla.is_component() and silla.name == "Silla"
        assert len(win.viewport.history.undo_stack) == steps + 1
        win.viewport.history.undo()
        assert b.mesh is silla.mesh and c.mesh is silla.mesh
        assert b.name == c.name == "Silla"
    finally:
        _close(win)


def test_select_instances_takes_every_copy_nested_ones_too():
    win, scene, panel, (silla, b, c, d, comedor, muro) = _setup()
    try:
        assert set(panel.copies_of_rows([b])) == {silla, b, c, d}
        panel.select_copies([b])
        # three at the top beat the one in «Comedor»: the top stays open
        assert scene.edit_group is None
        assert set(scene.selection) == {silla, b, c}
        assert "1" in win.statusBar().currentMessage()   # one elsewhere
    finally:
        _close(win)


def test_inside_a_component_make_unique_is_greyed_with_the_reason():
    win, scene, panel, (silla, b, c, d, comedor, muro) = _setup()
    try:
        tornillo = Group(_quad(20.0), name="Tornillo")
        tornillo.xform = QMatrix4x4()
        mueble = Group(_quad(18.0), name="Mueble")
        mueble.xform = QMatrix4x4()
        mueble.children = [tornillo]            # a component of a component
        scene.groups.append(mueble)
        scene.version += 1
        panel.refresh()
        why = tr("Components keep their parts: Make Unique first to change "
                 "what is inside one")
        panel._items[id(mueble)].setExpanded(True)     # the row in sight
        entries = _menu(panel, panel._items[id(tornillo)])
        assert entries[tr("Make Unique")] == (False, why)
        said = []
        win.viewport.flash_status = lambda text, *a, **k: said.append(text)
        assert not panel.make_unique_rows([tornillo])
        assert said == [why] and tornillo.is_component()
    finally:
        _close(win)
