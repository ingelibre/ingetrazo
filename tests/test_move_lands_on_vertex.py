# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving geometry exactly onto other vertices merges them (#341, @pacaeiro).

Lowering a box's top edge onto its bottom edge makes a ramp. The moved
corners landed on the bottom corners but stayed separate vertices, so the
side face became a zero-area sliver with zero-length edges — invisible until
Make Group copied the geometry, welded it, and refused «degenerate edge:
endpoints weld to one vertex»."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.history import History, MakeGroupCommand, MoveVerticesCommand
from core.scene import Scene

P = [V(0, 0, 0), V(3, 0, 0), V(3, 4, 0), V(0, 4, 0),
     V(0, 0, 2.6), V(3, 0, 2.6), V(3, 4, 2.6), V(0, 4, 2.6)]


def _box():
    sc = Scene()
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        sc.mesh.add_face([P[i] for i in idx])
    return sc, History(sc)


def _counts(mesh):
    return len(mesh.vertices), len(mesh.edges), len(mesh.faces)


def _ramp():
    sc, h = _box()
    # The top edge over x = 3 goes down onto the bottom edge: a ramp.
    h.execute(MoveVerticesCommand([P[5], P[6]], V(0, 0, -2.6)))
    assert h.last_error is None
    return sc, h


def test_the_ramp_is_a_clean_closed_solid():
    sc, _h = _ramp()
    m = sc.mesh
    assert _counts(m) == (6, 9, 5)
    assert not [e for e in m.edges
                if (e.v0.position - e.v1.position).length() < 1e-9]
    assert all(len(e.faces) == 2 for e in m.edges)      # closed, no slivers


def test_the_ramp_can_be_grouped():
    sc, h = _ramp()
    h.execute(MakeGroupCommand(list(sc.mesh.faces), list(sc.mesh.edges)))
    assert h.last_error is None
    assert len(sc.groups) == 1
    assert _counts(sc.groups[0].mesh) == (6, 9, 5)


def test_the_ramp_can_become_a_component():
    sc, h = _ramp()
    h.execute(MakeGroupCommand(list(sc.mesh.faces), list(sc.mesh.edges),
                               component=True))
    assert h.last_error is None
    assert sc.groups[0].is_component()


def test_undo_gives_the_box_back_and_redo_the_ramp():
    sc, h = _ramp()
    assert h.undo()
    assert _counts(sc.mesh) == (8, 12, 6)
    assert h.redo()
    assert _counts(sc.mesh) == (6, 9, 5)


def test_a_move_that_lands_nowhere_does_not_weld(monkeypatch):
    sc, h = _box()
    calls = []
    monkeypatch.setattr(type(sc.mesh), "weld_coincident",
                        lambda self: calls.append(1) or False)
    h.execute(MoveVerticesCommand([P[5], P[6]], V(0, 0, -1.0)))
    assert h.last_error is None and calls == []


def test_make_group_skips_a_zero_length_edge_instead_of_failing():
    sc, h = _box()
    a = sc.mesh.add_edge(V(5, 0, 0), V(6, 0, 0))
    # Squash it in place, the way a move that did not weld left them.
    sc.mesh.place_vertex(a.v1, V(5, 0, 0))
    h.execute(MakeGroupCommand(list(sc.mesh.faces), list(sc.mesh.edges)))
    assert h.last_error is None
    assert len(sc.groups) == 1
