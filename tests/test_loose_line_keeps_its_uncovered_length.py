# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A loose line lying partly along another edge keeps the rest of its length.

Every plane rebuild and every heal pass prunes the loose edges (bounding no
face) that lie collinearly over another edge: the duplicate "division line"
a face's full-length side leaves once the planner has split it. The prune
removed the WHOLE loose edge when any part of it overlapped: a 8.6 m line
with a face pasted across it kept only the 2.5 m the face now held, and two
overlapping lines of an imported drawing lost 9 of their 16 m at the next
Delete. Only the covered stretch goes now.

Headless: ``QVector3D`` value types only.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.edits import build_add_edge
from core.history import EraseSelectionCommand, History
from core.scene import Scene
from core.topology import prune_collinear_orphan_edges


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _covered(mesh, a, b, loose_only=False) -> float:
    """How much of segment ``a``–``b`` the mesh's edges run along."""
    u = (b - a).normalized()
    length = (b - a).length()
    spans = []
    for e in mesh.edges:
        if loose_only and e.faces:
            continue
        if any(QVector3D.crossProduct(p - a, u).length() > 1e-4 for p in (e.a, e.b)):
            continue
        t0, t1 = sorted(QVector3D.dotProduct(p - a, u) for p in (e.a, e.b))
        t0, t1 = max(0.0, t0), min(length, t1)
        if t1 > t0:
            spans.append((t0, t1))
    total = at = 0.0
    for t0, t1 in sorted(spans):
        if t1 > at:
            total += t1 - max(t0, at)
            at = t1
    return total


def _loose(mesh):
    return [e for e in mesh.edges if not e.faces]


def test_a_loose_line_partly_along_a_face_s_side_keeps_the_rest():
    scene = Scene()
    m = scene.mesh
    m.add_face([V(0, 0), V(4, 0), V(4, 2), V(0, 2)])
    m.add_edge(V(2, 0), V(9, 0))           # 2 m along the face's side, 5 m beyond
    m.add_edge(V(1, 2), V(3, 2))           # wholly along the face's top: a duplicate
    prune_collinear_orphan_edges(m)
    assert abs(_covered(m, V(0, 0), V(9, 0)) - 9.0) < 1e-6
    assert abs(_covered(m, V(4, 0), V(9, 0), loose_only=True) - 5.0) < 1e-6   # 0 before
    assert not any(abs(e.a.y() - 2) < 1e-9 for e in _loose(m))   # the duplicate goes
    corner = m.vertex_at(V(4, 0))
    assert len(corner.edges) == 3          # what is left starts on the face's corner


def test_the_piece_left_carries_the_line_s_flags():
    scene = Scene()
    m = scene.mesh
    m.add_face([V(2, 0), V(4, 0), V(4, 2), V(2, 2)])
    e = m.add_edge(V(0, 0), V(6, 0))
    e.soft, e.layer, e.curve = True, "Fence", 7
    prune_collinear_orphan_edges(m)
    pieces = _loose(m)
    assert len(pieces) == 2
    assert all(p.soft and p.layer == "Fence" for p in pieces)
    assert all(p.curve is not None for p in pieces)
    assert pieces[0].curve != pieces[1].curve      # two separate stretches, two curves


def test_a_line_beside_a_side_ends_on_its_corner():
    """Half a millimetre beside the face's side, inside the collinear
    tolerance: the stretch left starts on the face's corner, not on a vertex
    of its own beside it."""
    scene = Scene()
    m = scene.mesh
    m.add_face([V(0, 0), V(4, 0), V(4, 2), V(0, 2)])
    m.add_edge(V(2, 0.0005), V(9, 0.0005))
    prune_collinear_orphan_edges(m)
    assert len(m.vertex_at(V(4, 0)).edges) == 3
    assert m.vertex_at(V(4, 0.0005)) is None
    assert abs(sum(e.length() for e in _loose(m)) - 5.0) < 1e-3


def test_a_cover_reaching_within_a_millimetre_of_the_end_takes_it_all():
    scene = Scene()
    m = scene.mesh
    m.add_face([V(0, 0), V(6.99995, 0), V(6.99995, 1), V(0, 1)])
    m.add_edge(V(0, 0), V(7, 0))           # covered but for 50 µm
    prune_collinear_orphan_edges(m)
    assert _loose(m) == []


class _VP:
    def __init__(self, scene, history, clipboard):
        self.scene, self.history, self.clipboard = scene, history, clipboard

    def update(self):
        pass


def test_a_face_pasted_across_a_loose_line_keeps_the_line():
    from tools.base import ToolContext
    from tools.paste import PasteTool
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(10, 0), V(10, 10), V(0, 10)])
    hist.clear()
    a, b = V(1, 2), V(8, 7)
    hist.execute(build_add_edge(scene, a, b))      # a line lying on the floor
    assert abs(_covered(scene.mesh, a, b) - (b - a).length()) < 1e-6

    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 3), V(0, 3)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    vp = _VP(scene, hist, clip)
    tool = PasteTool()
    tool.on_activate(vp)
    tool.on_click(ToolContext(viewport=vp, world=V(3, 3, 0), screen=QPointF(0, 0),
                              modifiers=Qt.NoModifier, snap=None))
    # The pasted 2 x 3 m face is there (the line now divides it in two).
    pasted = [f for f in scene.faces
              if all(3 - 1e-6 <= v.x() <= 5 + 1e-6 and 3 - 1e-6 <= v.y() <= 6 + 1e-6
                     for v in f.vertices)]
    assert abs(sum(f.area() for f in pasted) - 6.0) < 1e-6
    assert abs(_covered(scene.mesh, a, b) - (b - a).length()) < 1e-4   # 2.46 of 8.60 m before

    hist.undo()
    assert abs(_covered(scene.mesh, a, b) - (b - a).length()) < 1e-6


def test_overlapping_lines_of_an_imported_drawing_survive_the_next_delete():
    scene = Scene()
    hist = History(scene)
    m = scene.mesh
    for p, q in (((0, 0), (5, 0)), ((3, 0), (8, 0)),     # two lines overlapping
                 ((0, 2), (8, 2)), ((2, 2), (4, 2))):    # a line drawn twice
        m.add_edge(V(*p), V(*q))
    elsewhere = m.add_face([V(30, 30), V(31, 30), V(31, 31), V(30, 31)])
    hist.clear()
    hist.execute(EraseSelectionCommand([], [elsewhere]))
    assert abs(_covered(m, V(0, 0), V(8, 0), loose_only=True) - 8.0) < 1e-6   # 5 before
    assert abs(_covered(m, V(0, 2), V(8, 2), loose_only=True) - 8.0) < 1e-6   # 2 before
    # No line is left lying over another (the erased face keeps its outline,
    # 30 m away).
    drawing = [e for e in _loose(m) if max(e.a.x(), e.b.x()) < 10]
    assert abs(sum(e.length() for e in drawing) - 16.0) < 1e-6
