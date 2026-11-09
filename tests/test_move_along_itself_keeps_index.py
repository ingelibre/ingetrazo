# SPDX-License-Identifier: GPL-3.0-or-later
"""A selection moved onto spots it still holds keeps every vertex findable.

Two chained lines 0–1–2 moved 1 m along their own axis: each vertex lands
where the next one still stands. The newcomer could not take the position
key, and when the holder moved on nothing filed it again — Delete missed
those edges and a new line to them welded a duplicate vertex (tutorial hunt
2, A3)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.history import (DeleteEdgesCommand, History, MoveVerticesCommand,
                          RotateVerticesCommand)
from core.scene import Scene


def _chain():
    sc = Scene()
    sc.mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    sc.mesh.add_edge(V(1, 0, 0), V(2, 0, 0))
    return sc, History(sc)


def _found(mesh, xs):
    return [mesh.vertex_at(V(x, 0, 0)) for x in xs]


def test_every_moved_vertex_is_found_at_its_new_spot():
    sc, h = _chain()
    h.execute(MoveVerticesCommand([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0)],
                                  V(1, 0, 0)))
    assert h.last_error is None
    assert _found(sc.mesh, (1, 2, 3)) == sorted(
        sc.mesh.vertices, key=lambda v: v.position.x())
    assert sc.mesh.vertex_at(V(0, 0, 0)) is None


def test_the_moved_lines_can_be_deleted():
    sc, h = _chain()
    h.execute(MoveVerticesCommand([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0)],
                                  V(1, 0, 0)))
    edges = list(sc.mesh.edges)
    h.execute(DeleteEdgesCommand(edges))
    assert sc.mesh.edges == []


def test_a_new_line_to_a_moved_vertex_welds_to_it():
    sc, h = _chain()
    h.execute(MoveVerticesCommand([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0)],
                                  V(1, 0, 0)))
    sc.mesh.add_edge(V(1, 0, 0), V(1, 1, 0))
    assert len(sc.mesh.vertices) == 4


def test_undo_and_redo_keep_the_index():
    sc, h = _chain()
    h.execute(MoveVerticesCommand([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0)],
                                  V(1, 0, 0)))
    h.undo()
    assert all(v is not None for v in _found(sc.mesh, (0, 1, 2)))
    h.redo()
    assert all(v is not None for v in _found(sc.mesh, (1, 2, 3)))


def test_a_square_turned_a_quarter_keeps_every_corner():
    # Each corner of a square turned 90° about its centre lands on the next.
    sc = Scene()
    pts = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        sc.mesh.add_edge(a, b)
    h = History(sc)
    h.execute(RotateVerticesCommand(pts, V(0.5, 0.5, 0), V(0, 0, 1), 90.0))
    assert h.last_error is None
    assert len({id(sc.mesh.vertex_at(p)) for p in pts}) == 4
    assert all(sc.mesh.vertex_at(p) is not None for p in pts)
