# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""New objects go to the active layer (#1366, @fzadow: with «Ebene 1»
active — pencil icon — a circle drawn still landed on «Layer 0» and
«colour by layer» showed it in Layer 0's colour).

Groups, components, dimensions, texts and guides already went to the
active layer (core.layers.tag_new_objects); loose lines and faces —
what the line, rectangle, arc and circle tools actually draw — stayed
on the default layer. Now they follow the active layer too, while
geometry a command only splits or rebuilds out of an old object, and
geometry inside a group, keeps the layer it had."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D as V

import core.layers as L
from core.edits import build_add_edge, build_add_edges
from core.history import (AddEdgeCommand, AddFaceCommand, History,
                          InsertGroupCommand, MakeGroupCommand,
                          RebuildPlanarFacesCommand, TagCurveCommand)
from core.layers import DEFAULT_LAYER, Layer, layer_of
from core.orient import orient_outward
from core.scene import Scene

ACTIVE = "Ebene 1"


def _scene(active: bool = True):
    scene = Scene()
    history = History(scene)
    scene.layers.append(Layer(ACTIVE))
    if active:
        L.set_active(scene, ACTIVE)
    return scene, history


def _circle_points(cx=0.0, cy=0.0, r=3.0, sides=24):
    return [V(cx + r * math.cos(2 * math.pi * k / sides),
              cy + r * math.sin(2 * math.pi * k / sides), 0)
            for k in range(sides)]


def _draw_circle(scene, extra):
    pts = _circle_points()
    segments = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    return build_add_edges(scene, segments, detect_faces=False, extra=extra)


def test_a_drawn_line_goes_to_the_active_layer():
    scene, history = _scene()
    history.execute(AddEdgeCommand(V(0, 0, 0), V(5, 0, 0)))
    assert [layer_of(e) for e in scene.mesh.edges] == [ACTIVE]


def test_a_drawn_face_and_its_edges_go_to_the_active_layer():
    scene, history = _scene()
    history.execute(AddFaceCommand(
        [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]))
    assert [layer_of(f) for f in scene.mesh.faces] == [ACTIVE]
    assert all(layer_of(e) == ACTIVE for e in scene.mesh.edges)


def test_a_drawn_circle_goes_to_the_active_layer():
    scene, history = _scene()
    history.execute(_draw_circle(scene, [AddFaceCommand(_circle_points())]))
    assert [layer_of(f) for f in scene.mesh.faces] == [ACTIVE]
    assert all(layer_of(e) == ACTIVE for e in scene.mesh.edges)


def test_a_circle_rebuilt_over_a_square_only_moves_the_disc():
    """The reporter's screenshot, through the circle tool's flat path:
    the planar rebuild redraws every face on the plane, yet only the
    disc is new — the square it landed on stays on Layer 0."""
    scene, history = _scene(active=False)
    history.execute(AddFaceCommand(
        [V(-5, -5, 0), V(5, -5, 0), V(5, 5, 0), V(-5, 5, 0)]))
    L.set_active(scene, ACTIVE)
    extra = [TagCurveCommand(_circle_points(), closed=True),
             RebuildPlanarFacesCommand()]
    history.execute(_draw_circle(scene, extra))
    assert sorted(layer_of(f) for f in scene.mesh.faces) == [
        ACTIVE, DEFAULT_LAYER]
    assert {layer_of(e) for e in scene.mesh.edges} == {ACTIVE, DEFAULT_LAYER}


def test_a_line_across_a_face_moves_but_the_face_pieces_stay():
    scene, history = _scene(active=False)
    history.execute(AddFaceCommand(
        [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)]))
    L.set_active(scene, ACTIVE)
    history.execute(build_add_edge(scene, V(0, 5, 0), V(10, 5, 0)))
    assert all(layer_of(f) == DEFAULT_LAYER for f in scene.mesh.faces)
    assert ACTIVE in {layer_of(e) for e in scene.mesh.edges}
    assert DEFAULT_LAYER in {layer_of(e) for e in scene.mesh.edges}


def test_pieces_of_a_split_tagged_edge_keep_its_layer_not_the_active():
    scene, history = _scene(active=False)
    scene.layers.append(Layer("Other"))
    L.set_active(scene, "Other")
    history.execute(AddFaceCommand(
        [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)]))
    L.set_active(scene, ACTIVE)
    history.execute(build_add_edge(scene, V(0, 5, 0), V(10, 5, 0)))
    assert all(layer_of(f) == "Other" for f in scene.mesh.faces)
    assert {layer_of(e) for e in scene.mesh.edges} == {"Other", ACTIVE}


def test_without_an_active_layer_new_objects_stay_on_layer_0():
    scene, history = _scene(active=False)
    history.execute(AddEdgeCommand(V(0, 0, 0), V(5, 0, 0)))
    history.execute(AddFaceCommand(
        [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]))
    assert all(layer_of(x) == DEFAULT_LAYER
               for x in list(scene.mesh.edges) + list(scene.mesh.faces))


def test_a_hidden_active_layer_leaves_new_objects_on_layer_0():
    scene, history = _scene()
    scene.layer(ACTIVE).visible = False
    history.execute(AddEdgeCommand(V(0, 0, 0), V(5, 0, 0)))
    assert [layer_of(e) for e in scene.mesh.edges] == [DEFAULT_LAYER]


def test_undo_and_redo_keep_the_active_layer():
    scene, history = _scene()
    history.execute(AddEdgeCommand(V(0, 0, 0), V(5, 0, 0)))
    history.undo()
    history.redo()
    assert [layer_of(e) for e in scene.mesh.edges] == [ACTIVE]


def test_an_object_that_already_carries_a_layer_keeps_it():
    scene, history = _scene()
    scene.layers.append(Layer("Other"))
    history.execute(AddFaceCommand(
        [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)],
        attrs={"layer": "Other"}, auto=False))
    assert [layer_of(f) for f in scene.mesh.faces] == ["Other"]


def test_drawing_inside_an_open_group_follows_the_group_not_the_active():
    scene, history = _scene(active=False)
    face = scene.mesh.add_face(
        [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)])
    history.execute(MakeGroupCommand([face], list(scene.mesh.edges)))
    scene.groups[-1].layer = ACTIVE
    scene.layers.append(Layer("Other"))
    L.set_active(scene, "Other")
    scene.begin_group_edit(scene.groups[-1])
    history.execute(AddEdgeCommand(V(0, 0, 0), V(1, 1, 0)))
    inside = list(scene.mesh.edges)
    scene.end_group_edit()
    assert all(layer_of(e) == DEFAULT_LAYER for e in inside)


def test_a_cut_opening_puts_its_rim_and_reveals_on_the_active_layer():
    """Placing a window marked «Cut opening» cuts its hole AFTER the
    post-command tagging (the opening followers run after it), so the
    rim edges and reveal faces it draws stayed on Layer 0 while the
    window itself took the active layer. They are new geometry too."""
    from PySide6.QtGui import QMatrix4x4

    from core import openings
    from core.group import Group

    scene, history = _scene(active=False)
    wall = scene.mesh
    p = [V(0, 0, 0), V(3, 0, 0), V(3, 0.2, 0), V(0, 0.2, 0)]
    q = [V(0, 0, 2.5), V(3, 0, 2.5), V(3, 0.2, 2.5), V(0, 0.2, 2.5)]
    wall.add_face(p)
    wall.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        wall.add_face([p[i], p[j], q[j], q[i]])
    orient_outward(wall)
    L.set_active(scene, ACTIVE)
    before_edges = {id(e) for e in wall.edges}
    before_faces = {id(f) for f in wall.faces}
    window = Group(name="Window")
    outer = [V(0, 0, 0), V(1, 0, 0), V(1, 1.2, 0), V(0, 1.2, 0)]
    inner = [V(.05, .05, 0), V(.95, .05, 0), V(.95, 1.15, 0), V(.05, 1.15, 0)]
    window.mesh.add_face(outer, [inner])
    on_front = QMatrix4x4(1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1)
    place = QMatrix4x4()
    place.translate(1.0, 0, 0.9)
    window.xform = place * on_front
    openings.set_ext_entry(window, {"on": True})
    history.execute(InsertGroupCommand(window))
    new_edges = [e for e in wall.edges if id(e) not in before_edges]
    new_faces = [f for f in wall.faces if id(f) not in before_faces]
    assert new_edges and new_faces
    assert all(layer_of(e) == ACTIVE for e in new_edges)
    assert all(layer_of(f) == ACTIVE for f in new_faces)
