# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The tray's «In model» list counts the copies nested inside groups (#599,
@chakkreetiya: a component put into a group from the Browser dropped off
the list), and Select Instances opens the group that holds them, as the
Browser does, since the view selects inside one open group at a time."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group
from core.mesh import Mesh


def _quad(size=1.0, z=0.0):
    m = Mesh()
    m.add_face([V(0, 0, z), V(size, 0, z), V(size, size, z), V(0, size, z)])
    return m


def _component(mesh, name, dx=0.0):
    g = Group(mesh, name=name)
    xf = QMatrix4x4()
    xf.translate(dx, 0.0, 0.0)
    g.xform = xf
    return g


def _rows(win):
    panel = win.tray.components
    panel.refresh_in_model()
    out = {}
    for i in range(panel._in_model.count()):
        item = panel._in_model.item(i)
        groups = item.data(Qt.UserRole) or []
        if groups:
            out[groups[0].name] = (groups, item.text())
    return panel, out


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_copy_inside_a_group_is_listed():
    win = _window()
    try:
        scene = win.viewport.scene
        varilla = _component(_quad(), "Varilla")
        muro = Group(_quad(3.0), name="Muro")
        muro.children = [varilla]
        scene.groups.append(muro)
        _panel, rows = _rows(win)
        assert "Varilla" in rows
        assert rows["Varilla"][0] == [varilla]
        assert "(1×" in rows["Varilla"][1]
    finally:
        _close(win)


def test_copies_at_the_top_and_nested_make_one_row():
    win = _window()
    try:
        scene = win.viewport.scene
        silla = _component(_quad(), "Silla")
        arriba = copy_group(silla, V(5, 0, 0))
        dentro = copy_group(silla, V(10, 0, 0))
        mesa = Group(_quad(2.0), name="Comedor")
        mesa.children = [dentro]
        scene.groups.extend([silla, arriba, mesa])
        _panel, rows = _rows(win)
        assert set(rows["Silla"][0]) == {silla, arriba, dentro}
        assert "(3×" in rows["Silla"][1]
        assert "Comedor" not in rows            # a plain group: no row
    finally:
        _close(win)


def test_a_component_inside_each_copy_of_another_is_one_row():
    """Each copy of «Caja» carries its «Tornillo»: one row, a copy per box,
    and Select Instances takes the one in the first box (a tie)."""
    win = _window()
    try:
        scene = win.viewport.scene
        tornillo = _component(_quad(0.2), "Tornillo")
        caja = _component(_quad(2.0), "Caja")
        caja.children = [tornillo]
        otra = copy_group(caja, V(5, 0, 0))
        scene.groups.extend([caja, otra])
        panel, rows = _rows(win)
        assert len(rows["Tornillo"][0]) == 2
        assert all(g.mesh is tornillo.mesh for g in rows["Tornillo"][0])
        assert len(rows["Caja"][0]) == 2
        panel._select_groups(rows["Tornillo"][0])
        assert scene.edit_group is caja
        assert set(scene.selection) == {tornillo}
    finally:
        _close(win)


def test_select_instances_opens_the_group_that_holds_them():
    win = _window()
    try:
        scene = win.viewport.scene
        varilla = _component(_quad(), "Varilla")
        otra = copy_group(varilla, V(2, 0, 0))
        muro = Group(_quad(3.0), name="Muro")
        muro.children = [varilla, otra]
        scene.groups.append(muro)
        panel, rows = _rows(win)
        panel._in_model_actions(rows["Varilla"][0])[0][1]()
        assert scene.edit_group is muro
        assert set(scene.selection) == {varilla, otra}
    finally:
        _close(win)


def test_copies_in_several_groups_select_where_most_are():
    win = _window()
    try:
        scene = win.viewport.scene
        silla = _component(_quad(), "Silla")
        arriba = copy_group(silla, V(5, 0, 0))
        dentro = copy_group(silla, V(10, 0, 0))
        comedor = Group(_quad(2.0), name="Comedor")
        comedor.children = [dentro]
        scene.groups.extend([silla, arriba, comedor])
        panel, rows = _rows(win)
        panel._select_groups(rows["Silla"][0])
        assert scene.edit_group is None         # two at the top beat one
        assert set(scene.selection) == {silla, arriba}
        message = win.statusBar().currentMessage()
        assert "2" in message and "1" in message
    finally:
        _close(win)


def test_a_tie_keeps_the_group_already_open():
    win = _window()
    try:
        scene = win.viewport.scene
        silla = _component(_quad(), "Silla")
        dentro = copy_group(silla, V(10, 0, 0))
        comedor = Group(_quad(2.0), name="Comedor")
        comedor.children = [dentro]
        scene.groups.extend([silla, comedor])
        win.viewport.begin_group_edit(comedor)
        panel, rows = _rows(win)
        panel._select_groups(rows["Silla"][0])
        assert scene.edit_group is comedor
        assert set(scene.selection) == {dentro}
    finally:
        _close(win)


def test_a_locked_group_around_them_is_not_opened():
    win = _window()
    try:
        scene = win.viewport.scene
        varilla = _component(_quad(), "Varilla")
        muro = Group(_quad(3.0), name="Muro")
        muro.children = [varilla]
        muro.locked = True
        otro = Group(_quad(1.0), name="Suelo")
        scene.groups.extend([muro, otro])
        scene.selection.add(otro)
        panel, rows = _rows(win)
        panel._select_groups(rows["Varilla"][0])
        assert scene.edit_group is None
        assert set(scene.selection) == {otro}   # untouched
    finally:
        _close(win)


def test_all_at_the_top_select_as_before():
    from core.i18n import tr
    win = _window()
    try:
        scene = win.viewport.scene
        silla = _component(_quad(), "Silla")
        scene.groups.extend([silla, copy_group(silla, V(5, 0, 0))])
        panel, rows = _rows(win)
        panel._select_groups(rows["Silla"][0])
        assert scene.edit_group is None
        assert len(scene.selection) == 2
        assert win.statusBar().currentMessage() == tr(
            "{n} entities selected", n=2)
    finally:
        _close(win)
