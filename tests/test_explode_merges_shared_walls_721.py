# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exploding two boxes that touch leaves ONE face on the wall they share
(issue #721: «ao explodir, os blocos não se unem»).

Explode welded the vertices and edges of the two boxes but added each box's
wall as a face of its own: two coincident faces on the shared wall (twelve
faces for two cubes), which reads as «they stay apart». Faces that come out
of a group onto a plane that already carries overlapping faces now merge
the way Paste merges them (#73): the plane is rebuilt into its regions,
each covered once. Faces that only share an edge, or planes no other face
covers, stay as they are."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4
from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.history import (ExplodeGroupCommand, GroupInContextCommand,
                          History, MakeGroupCommand)
from core.mesh import Mesh
from core.scene import Scene


def _box_faces(x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    return [[p[i] for i in idx] for idx in (
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7))]


def _box_group(*box, name="Caja", xform=None):
    m = Mesh()
    for loop in _box_faces(*box):
        m.add_face(loop)
    g = Group(m, name=name)
    g.xform = xform
    return g


def _key(p):
    return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))


def _coincident(mesh) -> int:
    rings = [frozenset(_key(v) for v in f.vertices) for f in mesh.faces]
    return len(rings) - len(set(rings))


def _covers(mesh, p) -> int:
    """How many faces cover the point ``p`` (on their plane)."""
    n = 0
    for f in mesh.faces:
        nrm = f.normal()
        if abs(V.dotProduct(p - f.vertices[0], nrm)) > 1e-6:
            continue
        for a, b, c in f.triangulate():
            if _in_tri(p, a, b, c, nrm):
                n += 1
                break
    return n


def _in_tri(p, a, b, c, nrm):
    s = [V.dotProduct(V.crossProduct(v - u, p - u), nrm)
         for u, v in ((a, b), (b, c), (c, a))]
    return all(x > 1e-9 for x in s) or all(x < -1e-9 for x in s)


def _explode_all(scene, hist, groups):
    for g in groups:
        hist.execute(ExplodeGroupCommand(g))


def test_two_touching_boxes_share_one_wall():
    scene = Scene()
    hist = History(scene)
    a = _box_group(0, 0, 0, 1, 1, 1, name="A")
    b = _box_group(1, 0, 0, 2, 1, 1, name="B")
    scene.groups.extend([a, b])
    _explode_all(scene, hist, [a, b])
    m = scene.mesh
    assert _coincident(m) == 0
    assert len(m.vertices) == 12 and len(m.edges) == 20
    assert len(m.faces) == 11                 # one wall in the middle
    assert _covers(m, V(1, 0.4, 0.3)) == 1
    # Undo puts both boxes back as they were.
    assert hist.undo() and hist.undo()
    assert len(scene.groups) == 2 and not m.faces


def test_a_smaller_box_against_a_wall_splits_it_once():
    scene = Scene()
    hist = History(scene)
    a = _box_group(0, 0, 0, 1, 1, 1, name="A")
    b = _box_group(1, 0.25, 0, 2, 0.75, 0.5, name="B")
    scene.groups.extend([a, b])
    _explode_all(scene, hist, [a, b])
    m = scene.mesh
    assert _coincident(m) == 0
    assert _covers(m, V(1, 0.4, 0.2)) == 1   # the contact patch
    assert _covers(m, V(1, 0.9, 0.9)) == 1    # the rest of A's wall
    assert _covers(m, V(0, 0.3, 0.6)) == 1    # A's far side untouched
    assert _covers(m, V(1.4, 0.4, 0.5)) == 1  # B's top


def test_exploding_inside_an_open_group_merges_too():
    """The report's case: two blocks inside a group, exploded in place."""
    scene = Scene()
    hist = History(scene)
    outer = Group(Mesh(), name="Casa")
    outer.children = [_box_group(0, 0, 0, 1, 1, 1, name="A"),
                      _box_group(1, 0, 0, 2, 1, 1, name="B")]
    outer.xform = QMatrix4x4()
    scene.groups.append(outer)
    scene.begin_group_edit(outer)
    try:
        ctx = scene.edit_group
        for kid in list(ctx.children):
            hist.execute(GroupInContextCommand(ExplodeGroupCommand(kid), ctx))
        m = scene.mesh
        assert _coincident(m) == 0
        assert len(m.faces) == 11
    finally:
        scene.end_group_edit()


def test_component_instances_merge_in_world_coordinates():
    mv = QMatrix4x4()
    mv.translate(1, 0, 0)
    a = _box_group(0, 0, 0, 1, 1, 1, name="A", xform=QMatrix4x4())
    b = _box_group(0, 0, 0, 1, 1, 1, name="B", xform=mv)
    a.component = b.component = True
    scene = Scene()
    hist = History(scene)
    scene.groups.extend([a, b])
    _explode_all(scene, hist, [a, b])
    assert _coincident(scene.mesh) == 0
    assert len(scene.mesh.faces) == 11


def test_boxes_side_by_side_on_the_floor_keep_their_own_tops():
    """Coplanar faces that only share an edge are not merged (nothing
    overlaps): the tops stay two faces, as drawn."""
    scene = Scene()
    hist = History(scene)
    a = _box_group(0, 0, 0, 1, 1, 1, name="A")
    b = _box_group(1, 0, 0, 2, 1, 1, name="B")
    scene.groups.extend([a, b])
    _explode_all(scene, hist, [a, b])
    tops = [f for f in scene.mesh.faces
            if all(abs(v.z() - 1) < 1e-9 for v in f.vertices)]
    assert len(tops) == 2


def test_a_lone_group_explodes_exactly_as_before():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(5, 5, 0), V(6, 5, 0), V(6, 6, 0), V(5, 6, 0)])
    a = _box_group(0, 0, 0, 1, 1, 1, name="A")
    scene.groups.append(a)
    loops = [[_key(v) for v in f.vertices] for f in a.mesh.faces]
    hist.execute(ExplodeGroupCommand(a))
    got = [[_key(v) for v in f.vertices] for f in scene.mesh.faces[1:]]
    assert got == loops                      # same faces, same winding


def test_make_group_and_explode_again_round_trips():
    scene = Scene()
    hist = History(scene)
    a = _box_group(0, 0, 0, 1, 1, 1, name="A")
    b = _box_group(1, 0, 0, 2, 1, 1, name="B")
    scene.groups.extend([a, b])
    _explode_all(scene, hist, [a, b])
    before = sorted(sorted(_key(v) for v in f.vertices)
                    for f in scene.mesh.faces)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    hist.execute(ExplodeGroupCommand(scene.groups[-1]))
    after = sorted(sorted(_key(v) for v in f.vertices)
                   for f in scene.mesh.faces)
    assert after == before
