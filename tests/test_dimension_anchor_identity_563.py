# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A dimension keeps ITS vertex when a move passes it over another one.

Discussion #563 (@BastelBaus): a dimension on a rectangle's edge, the
corner dragged with Move over a corner of another rectangle. The hold
asked the mesh «which vertex stands at this vertex's position?» — and a
moved vertex standing on another one waits behind it in the registry, so
the hold read as dead for those frames and the dimension froze. Landing
there for good (the two corners join, the other one survives) left the
dimension frozen at a spot read before the move, off the geometry, and
moving the joined corner away left it behind for ever. The hold now
checks the vertex by identity, and a hold that dies in a join takes the
vertex at the spot where it died."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.dimension import Dimension
from core.history import (AddDimensionCommand, History,
                          MoveVerticesCommand)
from core.mesh import Mesh
from core.scene import Scene
from core.snap import SnapResult
from formats import igz
from tools.base import ToolContext
from tools.move import MoveTool

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def T(p):
    return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None

    def pick_group(self, x, y):
        return None

    def pick_dimension(self, x, y):
        return None


def _ctx(vp, p, kind="endpoint"):
    snap = SnapResult(V(p.x(), p.y(), p.z()), kind)
    snap.context = None
    return ToolContext(viewport=vp, world=QVector3D(p), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=snap)


LEFT = [V(0, 0), V(4, 0), V(4, 3), V(0, 3)]
RIGHT = [V(6, -2), V(9, -2), V(9, -4), V(6, -4)]
B, O = V(4, 0), V(6, -2)


def _two_rects(right_first: bool):
    """The report's drawing: a dimension on the left rectangle's front
    edge, a second rectangle whose corner O the drag goes over. Drawn
    first, the right one's corner is the one that survives a join."""
    sc = Scene()
    vp = _Vp(sc)
    for r in ((RIGHT, LEFT) if right_first else (LEFT, RIGHT)):
        sc.mesh.add_face(list(r))
    d = Dimension(V(0, 0), B, V(0, -1))
    vp.history.execute(AddDimensionCommand(d))
    assert d.anchored
    return sc, vp, d


@pytest.mark.parametrize("right_first", [False, True])
def test_the_preview_over_another_corner_keeps_the_hold(right_first):
    sc, vp, d = _two_rects(right_first)
    held = d.anchor_b.vertex
    tool = MoveTool()
    tool.on_click(_ctx(vp, B))
    for p in (V(5, -1), O, O, V(7, -3)):
        tool.on_hover(_ctx(vp, p, "endpoint" if p == O else "none"))
        assert T(d.b) == T(p)              # rides along, also ON the corner
        assert d.anchor_b is not None and d.anchor_b.vertex is held
    tool.on_click(_ctx(vp, V(7, -3), "none"))
    assert T(d.b) == T(V(7, -3)) and d.anchor_b.vertex is held
    vp.history.undo()
    assert T(d.b) == T(B) and d.anchor_b.vertex is held
    vp.history.redo()
    assert T(d.b) == T(V(7, -3))


@pytest.mark.parametrize("right_first", [False, True])
def test_landing_on_a_corner_then_moving_it_away(right_first):
    sc, vp, d = _two_rects(right_first)
    tool = MoveTool()
    tool.on_click(_ctx(vp, B))
    tool.on_hover(_ctx(vp, V(5, -1), "none"))
    tool.on_hover(_ctx(vp, O))
    assert T(d.b) == T(O)
    tool.on_click(_ctx(vp, O))                 # the corners join
    assert len(sc.mesh.vertices) == 7
    assert T(d.b) == T(O) and d.anchored
    tool = MoveTool()
    tool.on_click(_ctx(vp, O))
    for p in (V(6.5, -1), V(7, 0)):
        tool.on_hover(_ctx(vp, p, "none"))
        assert T(d.b) == T(p)
    tool.on_click(_ctx(vp, V(7, 0), "none"))
    assert T(d.b) == T(V(7, 0))
    vp.history.undo()
    assert T(d.b) == T(O)
    vp.history.undo()
    assert T(d.b) == T(B)
    vp.history.redo()
    assert T(d.b) == T(O)
    vp.history.redo()
    assert T(d.b) == T(V(7, 0)) and d.anchored


def test_a_join_with_no_read_in_between_takes_the_vertex_where_it_died():
    """Nothing reads the dimension between the commands (a script, the
    AI bridge): its frozen spot is the one from before the move, where
    another vertex stands now. A chain p0–p1–p2 slid one length along
    itself puts p0 where p1 was and p1 on p2 (which survives the join);
    the dimension on p1 belongs on p2, not on p0."""
    sc = Scene()
    h = History(sc)
    sc.mesh.add_edge(V(8, 0), V(8, 5))         # p2 filed first: it survives
    sc.mesh.add_edge(V(0, 0), V(4, 0))         # p0–p1
    sc.mesh.add_edge(V(4, 0), V(8, 0))         # p1–p2
    d = Dimension(V(4, 0), V(8, 5), V(-1, 0))  # on p1 and the far end
    h.execute(AddDimensionCommand(d))
    assert d.anchored
    h.execute(MoveVerticesCommand([V(0, 0), V(4, 0)], V(4, 0)))
    assert h.last_error is None
    assert T(d.a) == T(V(8, 0))
    assert d.anchor_a is not None and d.anchor_a.vertex.edges
    h.undo()
    assert T(d.a) == T(V(4, 0))


def test_the_mesh_registers_a_vertex_by_identity():
    m = Mesh()
    m.add_edge(V(0, 0), V(1, 0))
    m.add_edge(V(5, 0), V(6, 0))
    a = m.vertex_at(V(1, 0))
    other = m.vertex_at(V(5, 0))
    assert m.registers(a) and m.registers(other)
    m.place_vertex(a, V(5, 0))                 # a waits behind ``other``
    assert m.vertex_at(V(5, 0)) is other
    assert m.registers(a) and m.registers(other)
    m.place_vertex(a, V(2, 0))
    assert m.registers(a) and m.vertex_at(V(2, 0)) is a
    m.place_vertex(a, V(5, 0))
    m.weld_coincident()
    survivor = m.vertex_at(V(5, 0))
    dead = a if survivor is other else other
    assert not m.registers(dead) or not dead.edges
    assert m.registers(survivor)


def test_the_holds_survive_save_and_reopen(tmp_path):
    sc, vp, d = _two_rects(right_first=True)
    tool = MoveTool()
    tool.on_click(_ctx(vp, B))
    tool.on_hover(_ctx(vp, O))
    tool.on_click(_ctx(vp, V(7, -3), "none"))
    assert T(d.b) == T(V(7, -3))
    path = tmp_path / "563.igz"
    igz.save_scene(sc, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    (e,) = loaded.dimensions
    assert e.anchored
    assert (T(e.a), T(e.b)) == (T(d.a), T(d.b))
    lv = _Vp(loaded)
    tool = MoveTool()
    tool.on_click(_ctx(lv, V(7, -3)))
    tool.on_hover(_ctx(lv, V(6, -4)))           # over the other corner
    assert T(e.b) == T(V(6, -4)) and e.anchored
    tool.on_click(_ctx(lv, V(8, -1), "none"))
    assert T(e.b) == T(V(8, -1))
    again = tmp_path / "563b.igz"
    igz.save_scene(loaded, again)
    third = Scene()
    igz.load_into(third, again)
    (f,) = third.dimensions
    assert f.anchored and T(f.b) == T(V(8, -1))
