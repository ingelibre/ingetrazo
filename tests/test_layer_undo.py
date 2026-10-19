# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Deleting a layer can be undone; creating and renaming stay off the stack.

The Layers panel used to change ``scene.layers`` directly: Ctrl+Z after
deleting a layer did not bring it back, and everything it carried stayed on
the default layer. Deleting is a command now, and asks first when the layer
has content. Creating and renaming are easy to redo by hand and stay out of
the history, so they never get between Ctrl+Z and the drawing. Deleting and
renaming both reach geometry inside groups, kept definitions and the scenes
that hide the layer.
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

from core.group import Group
from core.history import DeleteLayerCommand, History
from core.layers import (DEFAULT_LAYER, Layer, assign_layer, layer_of,
                         rename_layer)
from core.mesh import Mesh
from core.purge import layer_carriers
from core.saved_views import SavedView
from core.scene import Scene


def _square(mesh, x0=0.0, y0=0.0):
    return mesh.add_face([QVector3D(x0, y0, 0), QVector3D(x0 + 1, y0, 0),
                          QVector3D(x0 + 1, y0 + 1, 0),
                          QVector3D(x0, y0 + 1, 0)])


def _state(scene) -> tuple:
    """Everything the layer actions may touch, by value: the layer list
    (order, names, visibility, lock), the label of every carrier, and the
    hidden layers of every scene."""
    layers = tuple((ly.name, ly.visible, ly.locked) for ly in scene.layers)
    labels = tuple(layer_of(e) for e in layer_carriers(scene))
    views = tuple(tuple(v.hidden_layers) for v in scene.saved_views)
    return layers, labels, views


def _document(seed: int):
    """A random document: loose squares, a group with a nested group, a
    kept definition, and scenes hiding some layers. Every entity gets a
    random layer from the list."""
    rng = random.Random(seed)
    scene = Scene()
    names = [f"L{i}" for i in range(rng.randint(2, 5))]
    for name in names:
        scene.layers.append(Layer(name, visible=rng.random() < 0.7,
                                  locked=rng.random() < 0.2))
    pool = [DEFAULT_LAYER] + names

    for i in range(rng.randint(1, 4)):
        _square(scene.mesh, x0=2.0 * i)
    outer = Group(Mesh(), name="outer")
    _square(outer.mesh)
    inner = Group(Mesh(), name="inner")
    _square(inner.mesh, y0=3.0)
    outer.children.append(inner)
    scene.groups.append(outer)
    kept = Group(Mesh(), name="kept")
    _square(kept.mesh, x0=10.0)
    scene.kept_components.append(kept)

    for e in layer_carriers(scene):
        assign_layer(e, rng.choice(pool))
    for k in range(rng.randint(1, 3)):
        hidden = rng.sample(names, rng.randint(0, len(names)))
        scene.saved_views.append(SavedView(f"S{k}", hidden_layers=hidden))
    return scene, rng


def _nested_document():
    scene = Scene()
    scene.layers.append(Layer("Muros", visible=False))
    loose = _square(scene.mesh)
    g = Group(Mesh(), name="caja")
    inside = _square(g.mesh)
    nested = Group(Mesh(), name="anidado")
    deep = _square(nested.mesh)
    g.children.append(nested)
    scene.groups.append(g)
    kept = Group(Mesh(), name="guardado")
    kept_face = _square(kept.mesh)
    scene.kept_components.append(kept)
    tagged = (loose, g, inside, nested, deep, kept, kept_face)
    for e in tagged:
        assign_layer(e, "Muros")
    scene.saved_views.append(SavedView("Planta", hidden_layers=["Muros"]))
    return scene, tagged


# ---- Rename (not on the undo stack) -----------------------------------------

def test_rename_reaches_groups_kept_definitions_and_scenes():
    scene, tagged = _nested_document()
    assert rename_layer(scene, "Muros", "Tabiques")
    assert scene.layer("Muros") is None
    assert not scene.layer("Tabiques").visible
    assert all(layer_of(e) == "Tabiques" for e in tagged)
    assert scene.saved_views[0].hidden_layers == ["Tabiques"]


@pytest.mark.parametrize("old,new", [
    (DEFAULT_LAYER, "Otra"),        # the default is permanent
    ("Muros", DEFAULT_LAYER),       # cannot take the default's name
    ("Muros", "Losas"),             # name already in use
    ("Muros", ""),
    ("No existe", "Otra"),
])
def test_rename_refused(old, new):
    scene = Scene()
    scene.layers += [Layer("Muros"), Layer("Losas")]
    _square(scene.mesh)
    before = _state(scene)
    assert not rename_layer(scene, old, new)
    assert _state(scene) == before


# ---- Delete (one undo step) -------------------------------------------------

def test_delete_moves_content_to_default_and_undo_restores_everything():
    scene, tagged = _nested_document()
    history = History(scene)
    scene.layers.insert(1, Layer("A"))
    scene.layer("Muros").locked = True
    scene.saved_views[0].hidden_layers = ["A", "Muros"]
    ly = scene.layer("Muros")

    history.execute(DeleteLayerCommand("Muros"))
    assert scene.layer("Muros") is None
    assert all(layer_of(e) == DEFAULT_LAYER for e in tagged)
    assert scene.saved_views[0].hidden_layers == ["A"]

    history.undo()
    assert scene.layers[2] is ly                      # same place in the list
    assert not ly.visible and ly.locked
    assert all(layer_of(e) == "Muros" for e in tagged)
    assert scene.saved_views[0].hidden_layers == ["A", "Muros"]

    history.redo()
    assert scene.layer("Muros") is None
    assert all(layer_of(e) == DEFAULT_LAYER for e in tagged)


def test_delete_default_or_missing_is_refused():
    scene = Scene()
    history = History(scene)
    history.execute(DeleteLayerCommand(DEFAULT_LAYER))
    history.execute(DeleteLayerCommand("No existe"))
    assert scene.layer(DEFAULT_LAYER) is not None
    assert history.undo_stack == []


def test_undo_delete_after_a_new_layer_took_the_name_makes_no_twin():
    """Renaming is not on the stack, so a layer with the deleted name can
    exist again by the time the delete is undone: the entities go back
    onto it, and the list never holds two layers with one name."""
    scene = Scene()
    history = History(scene)
    scene.layers.append(Layer("Muros"))
    face = _square(scene.mesh)
    assign_layer(face, "Muros")
    history.execute(DeleteLayerCommand("Muros"))
    scene.layers.append(Layer("Capa 1"))
    assert rename_layer(scene, "Capa 1", "Muros")
    history.undo()
    assert [ly.name for ly in scene.layers].count("Muros") == 1
    assert layer_of(face) == "Muros"


@pytest.mark.parametrize("seed", range(40))
def test_random_deletes_undo_to_the_start_and_redo_to_the_end(seed):
    """Synthetic documents and random sequences of deletes: undoing all of
    them gives back the starting document exactly, redoing all of them
    the final one, and nothing ever carries a layer the document lacks."""
    scene, rng = _document(seed)
    history = History(scene)
    start = _state(scene)
    while True:
        names = [ly.name for ly in scene.layers if ly.name != DEFAULT_LAYER]
        if not names or rng.random() < 0.2:
            break
        history.execute(DeleteLayerCommand(rng.choice(names)))
        known = {ly.name for ly in scene.layers}
        assert {layer_of(e) for e in layer_carriers(scene)} <= known
    end = _state(scene)
    while history.undo():
        pass
    assert _state(scene) == start
    while history.redo():
        pass
    assert _state(scene) == end


@pytest.mark.parametrize("seed", range(20))
def test_random_renames_keep_every_label_on_a_real_layer(seed):
    scene, rng = _document(seed)
    for k in range(rng.randint(1, 6)):
        names = [ly.name for ly in scene.layers if ly.name != DEFAULT_LAYER]
        old = rng.choice(names)
        count = sum(1 for e in layer_carriers(scene) if layer_of(e) == old)
        assert rename_layer(scene, old, f"R{k}")
        assert sum(1 for e in layer_carriers(scene)
                   if layer_of(e) == f"R{k}") == count
        known = {ly.name for ly in scene.layers}
        assert {layer_of(e) for e in layer_carriers(scene)} <= known
        for view in scene.saved_views:
            assert set(view.hidden_layers) <= known


# ---- Panel ------------------------------------------------------------------

def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def _item(tree, name):
    return tree.parent().item_for(name)


def test_panel_add_and_rename_stay_off_the_undo_stack():
    """Draw, then make and rename a layer: Ctrl+Z takes back the drawing,
    not the layer — the case that made the panel's undo a problem."""
    from core.history import AddFaceCommand
    win = _window()
    try:
        scene = win.viewport.scene
        history = win.viewport.history
        panel = win.layers_dock.panel
        history.execute(AddFaceCommand([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                                        QVector3D(1, 1, 0), QVector3D(0, 1, 0)]))
        assert scene.mesh.faces
        depth = len(history.undo_stack)

        panel._on_add()
        added = scene.layers[-1].name
        _item(panel.tree, added).setText(0, "Muros")   # rename by editing
        assert scene.layer("Muros") is not None
        assert len(history.undo_stack) == depth

        win._on_undo()
        assert not scene.mesh.faces                     # the drawing went
        assert scene.layer("Muros") is not None         # the layer stayed
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_panel_delete_asks_when_the_layer_has_content(monkeypatch):
    win = _window()
    try:
        scene = win.viewport.scene
        panel = win.layers_dock.panel
        face = _square(scene.mesh)
        scene.layers.append(Layer("Muros"))
        scene.layers.append(Layer("Vacia"))
        for e in [face] + list(scene.mesh.edges):     # 1 face + 4 edges
            assign_layer(e, "Muros")
        panel.refresh()
        asked = []

        def answer(reply):
            def question(_parent, _title, text, *a, **k):
                asked.append(text)
                return reply
            return question

        # An empty layer goes without a question.
        monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.No))
        panel.tree.setCurrentItem(_item(panel.tree, "Vacia"))
        panel._on_delete()
        assert scene.layer("Vacia") is None and not asked

        # «No» keeps the layer and everything on it.
        panel.tree.setCurrentItem(_item(panel.tree, "Muros"))
        panel._on_delete()
        assert len(asked) == 1 and "Muros" in asked[0] and "5" in asked[0]
        assert scene.layer("Muros") is not None and layer_of(face) == "Muros"

        # «Yes» deletes; Ctrl+Z brings it back with its content.
        monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.Yes))
        panel.tree.setCurrentItem(_item(panel.tree, "Muros"))
        panel._on_delete()
        assert scene.layer("Muros") is None
        assert layer_of(face) == DEFAULT_LAYER

        win._on_undo()
        assert scene.layer("Muros") is not None
        assert layer_of(face) == "Muros"
        assert _item(panel.tree, "Muros") is not None   # the panel follows
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
