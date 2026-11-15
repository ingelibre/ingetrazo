# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Erasing a hole's edge must not leave a hole without a boundary (#1191).

The report came from an offset: a rectangle offset outward leaves a ring
face whose hole is the original rectangle. Erasing one of the hole's
edges removed the segment but left the face still claiming the hole —
the opening stayed in the drawing (and in the saved file) with part of
its boundary gone and unpickable. A face cannot outlive a *bounding*
edge, but it can outlive a hole edge: the hole goes with the edge and
the face fills in. The hole's other edges stay as free lines."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import (AddFaceCommand, CompoundCommand, DeleteFaceCommand,
                          EraseSelectionCommand, History)
from core.scene import Scene
from core.topology import offset_loop


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _offset_ring():
    """A 4×4 face offset outward by 0.5, built the way OffsetTool._commit
    builds it: a ring (offset loop, original as its hole) + the original
    face inside."""
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    face = scene.mesh.add_face(loop)
    outer = offset_loop(loop, V(0, 0, 1), -0.5)
    hist.execute(CompoundCommand([
        DeleteFaceCommand(face),
        AddFaceCommand(list(outer), auto=False, holes=[list(loop)]),
        AddFaceCommand(list(loop), auto=False),
    ]))
    return scene, hist


def _edge(scene, p, q):
    m = scene.mesh
    return m.find_edge(m.vertex_at(V(*p)), m.vertex_at(V(*q)))


def _ring(scene):
    return next(f for f in scene.mesh.faces if f.holes)


def _inner(scene):
    return next(f for f in scene.mesh.faces if not f.holes)


def test_erasing_a_hole_edge_fills_the_hole_and_keeps_the_face():
    scene, hist = _offset_ring()
    hist.execute(EraseSelectionCommand([], [_inner(scene)]))
    assert len(scene.mesh.faces) == 1 and _ring(scene).holes

    hist.execute(EraseSelectionCommand([_edge(scene, (0, 0), (4, 0))]))

    (ring,) = scene.mesh.faces
    assert ring.holes == []                       # the opening filled in
    assert abs(ring.area() - 25.0) < 1e-6         # the whole 5×5 outline
    assert len(scene.mesh.edges) == 7             # 4 outer + 3 hole lines
    leftover = _edge(scene, (4, 0), (4, 4))
    assert leftover is not None and leftover.faces == []   # a free line


def test_erasing_the_inner_face_with_two_of_its_edges_keeps_the_ring():
    scene, hist = _offset_ring()
    edges = [_edge(scene, (0, 0), (4, 0)), _edge(scene, (4, 0), (4, 4))]
    hist.execute(EraseSelectionCommand(edges, [_inner(scene)]))

    (ring,) = scene.mesh.faces
    assert ring.holes == []
    assert abs(ring.area() - 25.0) < 1e-6
    assert len(scene.mesh.edges) == 6             # 4 outer + 2 left lines


def test_erasing_the_inner_face_with_all_its_edges_keeps_the_ring():
    scene, hist = _offset_ring()
    loop = [((0, 0), (4, 0)), ((4, 0), (4, 4)),
            ((4, 4), (0, 4)), ((0, 4), (0, 0))]
    edges = [_edge(scene, a, b) for a, b in loop]
    hist.execute(EraseSelectionCommand(edges, [_inner(scene)]))

    (ring,) = scene.mesh.faces
    assert ring.holes == []
    assert len(scene.mesh.edges) == 4             # the outer outline only


def test_undo_brings_the_hole_back():
    scene, hist = _offset_ring()
    hist.execute(EraseSelectionCommand([], [_inner(scene)]))
    hist.execute(EraseSelectionCommand([_edge(scene, (0, 0), (4, 0))]))
    (ring,) = scene.mesh.faces
    assert ring.holes == []

    hist.undo()
    assert len(_ring(scene).holes) == 1
    assert _edge(scene, (0, 0), (4, 0)) is not None


def test_erasing_an_outer_edge_still_takes_the_ring_with_it():
    scene, hist = _offset_ring()
    hist.execute(EraseSelectionCommand(
        [_edge(scene, (-0.5, -0.5), (4.5, -0.5))]))

    (inner,) = scene.mesh.faces                   # the ring died, as before
    assert inner.holes == []
    assert abs(inner.area() - 16.0) < 1e-6
    assert len(scene.mesh.edges) == 7


def test_erasing_a_shared_edge_still_merges_the_two_faces():
    scene, hist = _offset_ring()
    hist.execute(EraseSelectionCommand([_edge(scene, (0, 0), (4, 0))]))

    (merged,) = scene.mesh.faces                  # the split line dissolved
    assert merged.holes == []
    assert abs(merged.area() - 25.0) < 1e-6
    assert len(scene.mesh.edges) == 4
