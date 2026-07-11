# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Layers / tags (Fase 6): visibility, locking, assignment, persistence."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.layers import DEFAULT_LAYER, Layer, assign_layer, layer_of
from core.scene import Scene
from formats import igz


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _slab(scene, x0=0.0):
    f = scene.mesh.add_face([V(x0, 0), V(x0 + 2, 0), V(x0 + 2, 2), V(x0, 2)])
    return f


def test_entities_default_to_layer_zero():
    scene = Scene()
    f = _slab(scene)
    e = scene.mesh.edges[0]
    assert layer_of(f) == DEFAULT_LAYER
    assert layer_of(e) == DEFAULT_LAYER
    assert scene.entity_visible(f) and scene.entity_selectable(e)


def test_hidden_layer_filters_render_views():
    scene = Scene()
    f1 = _slab(scene, 0)
    f2 = _slab(scene, 5)
    scene.layers.append(Layer("Estructura", visible=False))
    assign_layer(f2, "Estructura")
    for lp in [f2.loop]:
        for i in range(len(lp)):
            e = scene.mesh.find_edge(lp[i], lp[(i + 1) % len(lp)])
            assign_layer(e, "Estructura")
    faces = list(scene.render_faces())
    edges = list(scene.render_edges())
    assert f1 in faces and f2 not in faces
    assert len(edges) == 4                          # only slab 1's edges
    assert not scene.entity_selectable(f2)


def test_locked_layer_visible_but_unselectable():
    scene = Scene()
    f = _slab(scene)
    scene.layers.append(Layer("Fondo", locked=True))
    assign_layer(f, "Fondo")
    assert scene.entity_visible(f)
    assert not scene.entity_selectable(f)


def test_group_layer_hides_whole_group():
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    g = Group(Mesh())
    g.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    scene.groups.append(g)
    scene.layers.append(Layer("Mobiliario", visible=False))
    assign_layer(g, "Mobiliario")
    assert list(scene.render_faces()) == []
    assert not scene.entity_selectable(g)


def test_layers_and_labels_round_trip_igz(tmp_path):
    scene = Scene()
    f = _slab(scene)
    e = scene.mesh.edges[0]
    scene.layers.append(Layer("Muros", visible=False, locked=True))
    assign_layer(f, "Muros")
    assign_layer(e, "Muros")
    p = tmp_path / "capas.igz"
    igz.save_scene(scene, p)

    scene2 = Scene()
    igz.load_into(scene2, p)
    names = {ly.name: (ly.visible, ly.locked) for ly in scene2.layers}
    assert names[DEFAULT_LAYER] == (True, False)
    assert names["Muros"] == (False, True)
    f2 = scene2.mesh.faces[0]
    assert layer_of(f2) == "Muros"
    tagged = [e2 for e2 in scene2.mesh.edges if layer_of(e2) == "Muros"]
    assert len(tagged) == 1


def test_edge_layer_survives_split_and_snapshot():
    scene = Scene()
    e = scene.mesh.add_edge(V(0, 0), V(4, 0))
    assign_layer(e, "Instalaciones")
    snap = scene.mesh.capture_state()
    mid = scene.mesh.vertex(V(2, 0, 0))
    scene.mesh.split_edge_at(e, mid)
    assert all(layer_of(k) == "Instalaciones" for k in scene.mesh.edges)
    scene.mesh.restore_state(snap)
    assert all(layer_of(k) == "Instalaciones" for k in scene.mesh.edges)
