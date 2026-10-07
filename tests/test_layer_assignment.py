# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Changing an object's layer where people look for it.

Rafael, 2026-09-16 (39:00–40:00): «no sé cómo cambiar el objeto de capa…
las propiedades del objeto… no lo veo. Botón derecho… no lo veo tampoco.
Asignar selección… algo no había seleccionado bien». The only road was
the Layers panel's button, silent when nothing was selected or no layer
highlighted. Now Entity Info has a Layer field, the right-click has a
Layer submenu, and all three go through one undoable command.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.group import Group
from core.history import AssignLayerCommand, History
from core.layers import Layer, layer_of
from core.mesh import Mesh
from core.scene import Scene


def _square(mesh, x0=0.0):
    return mesh.add_face([QVector3D(x0, 0, 0), QVector3D(x0 + 1, 0, 0),
                          QVector3D(x0 + 1, 1, 0), QVector3D(x0, 1, 0)])


def test_assign_layer_command_moves_a_mixed_selection_and_undoes_exactly():
    scene = Scene()
    history = History(scene)
    scene.layers.append(Layer("Muros"))
    face = _square(scene.mesh)
    edge = scene.mesh.edges[0]
    g = Group(Mesh(), name="caja")
    g.layer = "Muros"
    scene.groups.append(g)

    history.execute(AssignLayerCommand([face, edge, g], "Mobiliario"))
    assert layer_of(face) == layer_of(edge) == layer_of(g) == "Mobiliario"
    assert scene.layer("Mobiliario") is not None      # created on the way

    history.undo()
    assert layer_of(face) == "Layer 0" and layer_of(edge) == "Layer 0"
    assert layer_of(g) == "Muros"
    assert scene.layer("Mobiliario") is None          # …and taken back
    history.redo()
    assert layer_of(g) == "Mobiliario"


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def test_entity_info_shows_the_layer_and_changes_it():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Muros"))
        face = _square(scene.mesh)
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        panel = win.tray.entity_info

        scene.select([face])
        panel.refresh()
        assert panel._layer_box.isVisibleTo(panel)
        assert panel._layer_box.currentData() == "Layer 0"

        idx = panel._layer_box.findData("Muros")
        panel._layer_box.setCurrentIndex(idx)          # the user picks Muros
        assert layer_of(face) == "Muros"
        vp.history.undo()
        assert layer_of(face) == "Layer 0"

        # a mixed selection reads as such, and picking moves everything
        g.layer = "Muros"
        scene.select([face, g])
        panel.refresh()
        assert panel._layer_box.currentData() is None
        assert panel._layer_box.currentText() == "(several)"
        panel._layer_box.setCurrentIndex(panel._layer_box.findData("Muros"))
        assert layer_of(face) == "Muros" and layer_of(g) == "Muros"

        scene.clear_selection()
        panel.refresh()
        assert not panel._layer_box.isVisibleTo(panel)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_entity_info_sorts_layers_and_keeps_assignment_after_refresh():
    from types import SimpleNamespace
    from core.layers import DEFAULT_LAYER
    from views.tray import EntityInfoPanel

    scene = Scene()
    scene.layers += [Layer("90 TERREIN NT"), Layer("bomen"),
                     Layer("10 walls"),
                     Layer("2 WALLS"), Layer("arco")]
    original_order = [ly.name for ly in scene.layers]
    history = History(scene)
    viewport = SimpleNamespace(scene=scene, history=history, update=lambda: None)
    window = SimpleNamespace(
        viewport=viewport,
        statusBar=lambda: SimpleNamespace(showMessage=lambda *args: None))
    panel = EntityInfoPanel(window)
    group = Group(Mesh(), name="wall")
    group.layer = "10 walls"
    scene.groups.append(group)
    scene.select([group])
    try:
        panel.refresh()
        box = panel._layer_box
        expected = [DEFAULT_LAYER, "2 WALLS", "10 walls", "90 TERREIN NT",
                    "arco", "bomen"]
        assert [box.itemText(i) for i in range(box.count())] == expected
        assert box.currentData() == "10 walls"
        assert group.layer == "10 walls"
        assert [ly.name for ly in scene.layers] == original_order

        box.setCurrentIndex(box.findData("2 WALLS"))
        assert group.layer == "2 WALLS"
        history.undo()
        panel.refresh()
        assert box.currentData() == "10 walls"

        face = _square(scene.mesh)
        scene.select([group, face])
        panel.refresh()
        assert box.currentData() is None
        assert [box.itemText(i) for i in range(1, box.count())] == expected
        box.setCurrentIndex(box.findData("arco"))
        assert layer_of(group) == layer_of(face) == "arco"
    finally:
        panel.close()


def test_entity_info_sorts_layers_in_c_locale():
    from PySide6.QtCore import QLocale

    previous = QLocale()
    QLocale.setDefault(QLocale.c())
    try:
        test_entity_info_sorts_layers_and_keeps_assignment_after_refresh()
    finally:
        QLocale.setDefault(previous)


def test_right_click_layer_submenu_and_new_layer():
    from PySide6.QtWidgets import QInputDialog, QMenu
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Muros"))
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        scene.select([g])
        menu = QMenu()
        win._add_layer_submenu(menu, list(scene.selection))
        sub = [a for a in menu.actions() if a.menu() is not None][0].menu()
        names = [a.text() for a in sub.actions() if not a.isSeparator()]
        assert names[:2] == ["Layer 0", "Muros"] and names[-1] == "New layer…"
        ticked = [a.text() for a in sub.actions() if a.isChecked()]
        assert ticked == ["Layer 0"]
        [a for a in sub.actions() if a.text() == "Muros"][0].trigger()
        assert layer_of(g) == "Muros"

        QInputDialog.getText = staticmethod(lambda *a, **k: ("Jardín", True))
        win._assign_new_layer()
        assert layer_of(g) == "Jardín" and scene.layer("Jardín") is not None
        vp.history.undo()
        assert layer_of(g) == "Muros" and scene.layer("Jardín") is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_layers_panel_assign_button_speaks_and_undoes():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Muros"))
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        panel = win.tray.layers
        panel.refresh()
        # nothing highlighted in the list: it says so instead of doing nothing
        panel.tree.setCurrentItem(None)
        scene.select([g])
        panel._on_assign()
        assert layer_of(g) == "Layer 0"
        assert "layer" in win.statusBar().currentMessage().lower()
        # highlight Muros, nothing selected in the model: says so too
        item = [panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                if panel.tree.topLevelItem(i).text(0) == "Muros"][0]
        panel.tree.setCurrentItem(item)
        scene.clear_selection()
        panel._on_assign()
        assert "select" in win.statusBar().currentMessage().lower()
        # both in place: moves, undoably
        scene.select([g])
        panel._on_assign()
        assert layer_of(g) == "Muros"
        vp.history.undo()
        assert layer_of(g) == "Layer 0"
    finally:
        win._saved_version = vp.scene.version
        win.close()
