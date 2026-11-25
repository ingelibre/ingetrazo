# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The snap scene reads a plain edge's snappability by its layer
(``views.viewport._support._edges_snappable``): the very answers
``Scene.edge_snappable`` gives edge by edge — loose edges and the rest of
the model's, on visible and hidden layers, on the default layer inside an
open group with and without a layer of its own, hidden edges with the
hidden-geometry view off and on, edges a scene subclass rules otherwise,
and things that are not plain edges."""
from __future__ import annotations

import random

from PySide6.QtGui import QVector3D as V

from core.history import History, MakeGroupCommand
from core.layers import Layer
from core.scene import Scene
from views.viewport._support import _edges_snappable

LAYERS = ("Layer 0", "Planta", "Muebles", "Oculta", None, "Sin capa")


def _scene(rng):
    scene = Scene()
    m = scene.mesh
    for k in range(rng.randint(3, 8)):
        o = V(k * 3.0, rng.uniform(0, 5), 0)
        m.add_face([o, o + V(1, 0, 0), o + V(1, 1, 0), o + V(0, 1, 0)])
    for name in ("Planta", "Muebles", "Oculta"):
        scene.layers.append(Layer(name))
    scene.layer("Oculta").visible = False
    if rng.random() < 0.3:
        scene.layer("Layer 0").visible = False
    group = None
    if rng.random() < 0.7:
        picked = rng.sample(m.faces, 2)
        History(scene).execute(MakeGroupCommand(
            picked, [e for e in m.edges
                     if e.faces and all(f in picked for f in e.faces)]))
        group = scene.groups[0]
        group.layer = rng.choice(("Planta", "Oculta", None))
    for e in list(m.edges):
        _mark(rng, e)
    if group is not None:
        for e in group.mesh.edges:
            _mark(rng, e)
        if rng.random() < 0.8:
            scene.begin_group_edit(group)
    scene.show_hidden_geometry = rng.random() < 0.4
    return scene


def _mark(rng, e):
    r = rng.random()
    if r < 0.5:
        e.layer = rng.choice(LAYERS)
    if rng.random() < 0.25:
        e.hidden = True


def test_the_same_answers_as_edge_by_edge():
    rng = random.Random(1210)
    seen = set()
    for _ in range(150):
        scene = _scene(rng)
        outer = (scene.loose_mesh.edges
                 if scene.loose_mesh is not scene.mesh else [])
        for edges in (list(scene.mesh.edges), list(outer),
                      list(scene.mesh.edges) + list(outer)):
            want = [scene.edge_snappable(e) for e in edges]
            assert _edges_snappable(scene, edges) == want
            seen.update(want)
    assert seen == {True, False}


def test_a_scene_with_its_own_rules_is_asked_edge_by_edge():
    class Strict(Scene):
        def edge_snappable(self, edge):
            return False
    scene = Strict()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    assert _edges_snappable(scene, scene.mesh.edges) == [False] * 3


def test_other_entities_are_asked_as_they_are():
    from views.viewport._support import _SnapEdge
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    other = _SnapEdge(V(0, 0, 0), V(1, 0, 0))
    edges = list(scene.mesh.edges) + [other]
    assert _edges_snappable(scene, edges) == [scene.edge_snappable(e)
                                              for e in edges]
