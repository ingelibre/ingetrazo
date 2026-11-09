# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoing an added face takes back the edges and corners it brought
(#355, @pacaeiro: «undo leaves edges behind»).

AddFaceCommand made the face through ``mesh.add_face``, which also creates
any missing boundary edges and vertices; undo removed the face alone, so a
rotated or moved COPY, a paste, anything built on AddFaceCommand, left its
outline behind as loose edges. Edges and corners that were already there —
a shared edge, a line drawn first — must stay."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.history import (AddEdgeCommand, AddFaceCommand, CompoundCommand,
                          History, rotation_matrix)
from core.scene import Scene

SQUARE = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)]


def _counts(m):
    return len(m.vertices), len(m.edges), len(m.faces)


def _registry_ok(m):
    return {id(v) for v in m._registry.values()} <= {id(v) for v in m.vertices}


def test_undoing_a_rotated_copy_leaves_nothing_behind():
    # The video: a square, Rotate with Ctrl about the middle of a side, 90°.
    sc = Scene()
    h = History(sc)
    f = sc.mesh.add_face(SQUARE)
    edges = list(sc.mesh.edges)
    m = rotation_matrix(V(0, 2, 0), V(0, 0, 1), 90)
    cmds = [AddFaceCommand([m.map(v.position) for v in f.loop], auto=False)]
    cmds += [AddEdgeCommand(m.map(e.a), m.map(e.b)) for e in edges]
    h.execute(CompoundCommand(cmds))
    assert _counts(sc.mesh) == (8, 8, 2)
    assert h.undo()
    assert _counts(sc.mesh) == (4, 4, 1)
    assert _registry_ok(sc.mesh)


def test_redo_and_undo_again_stay_exact():
    sc = Scene()
    h = History(sc)
    h.execute(AddFaceCommand(SQUARE))
    for _ in range(3):
        assert h.undo()
        assert _counts(sc.mesh) == (0, 0, 0)
        assert _registry_ok(sc.mesh)
        assert h.redo()
        assert _counts(sc.mesh) == (4, 4, 1)
        assert all(len(e.faces) == 1 for e in sc.mesh.edges)
    # The face welds to its corners again after a redo.
    assert sc.mesh.vertex_at(V(4, 4, 0)) is not None


def test_a_shared_edge_stays_when_the_neighbour_is_undone():
    sc = Scene()
    h = History(sc)
    sc.mesh.add_face(SQUARE)
    # A second square sharing the edge x = 4.
    h.execute(AddFaceCommand([V(4, 0, 0), V(8, 0, 0), V(8, 4, 0), V(4, 4, 0)],
                             auto=False))
    assert _counts(sc.mesh) == (6, 7, 2)
    assert h.undo()
    assert _counts(sc.mesh) == (4, 4, 1)
    shared = sc.mesh.find_edge(sc.mesh.vertex_at(V(4, 0, 0)),
                               sc.mesh.vertex_at(V(4, 4, 0)))
    assert shared is not None and len(shared.faces) == 1


def test_lines_drawn_first_stay_when_their_face_is_undone():
    sc = Scene()
    h = History(sc)
    for a, b in zip(SQUARE, SQUARE[1:] + SQUARE[:1]):
        sc.mesh.add_edge(a, b)               # the outline, drawn as lines
    h.execute(AddFaceCommand(SQUARE, auto=False))
    assert _counts(sc.mesh) == (4, 4, 1)
    assert h.undo()
    assert _counts(sc.mesh) == (4, 4, 0)     # the lines are still there
