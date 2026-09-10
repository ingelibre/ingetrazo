# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An Offset on a CONCAVE face must keep both halves.

Plaza Yanque, 2026-09-10: Offset 0.10 on a paved slab "worked, but only the
inner face is kept". The tool did its job — the command chain deleted the
base and created ring + inner, both. What removed the ring was the heal pass
SnapshotCompound runs afterwards, which drops a "redundant mother": a big
face covered by the smaller coplanar faces inside it.

That pass already exempts a legitimate ring, one whose inner faces merely
FILL its holes. The exemption failed because _loop_inside_loop judged
containment by the average of the loop's vertices — and for a concave loop
that average can land outside the loop itself, so the inner face read as
"not in the hole" and the ring was judged spurious.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from core.topology import (_interior_point, _loop_inside_loop,
                           _point_inside_2d, heal_overlapping_faces)
from core.triangulate import plane_axes
from tools.offset import OffsetTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


#: A U: the notch between the arms swallows the average of the vertices.
U = [V(0, 0), V(6, 0), V(6, 5), V(4, 5), V(4, 2), V(2, 2), V(2, 5), V(0, 5)]


def _average(loop):
    n = len(loop)
    return QVector3D(sum(p.x() for p in loop) / n,
                     sum(p.y() for p in loop) / n,
                     sum(p.z() for p in loop) / n)


def _inside(point, loop, normal):
    u, w = plane_axes(normal)
    origin = loop[0]

    def proj(p):
        rel = p - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    return _point_inside_2d(proj(point), [proj(p) for p in loop])


def test_the_vertex_average_of_a_concave_loop_lands_outside_it():
    """The premise, pinned: this is why the average cannot judge."""
    assert not _inside(_average(U), U, V(0, 0, 1))


def test_an_interior_point_really_is_inside():
    p = _interior_point(U, V(0, 0, 1))
    assert p is not None
    assert _inside(p, U, V(0, 0, 1))


def test_a_concave_loop_is_inside_itself():
    assert _loop_inside_loop(U, U, V(0, 0, 1))


def test_heal_keeps_a_concave_ring_and_the_face_filling_its_hole():
    inner = [V(p.x() * 0.9 + 0.3, p.y() * 0.9 + 0.25) for p in U]
    mesh = Mesh()
    ring = mesh.add_face([QVector3D(p) for p in U], [inner])
    filling = mesh.add_face([QVector3D(p) for p in inner])
    heal_overlapping_faces(mesh)
    assert ring in mesh.faces, "the ring was healed away"
    assert filling in mesh.faces


class _VP:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass


def test_offset_on_a_concave_face_keeps_both_halves():
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(p) for p in U])
    face.attrs["mat"] = "Piedra laja"
    vp = _VP(scene)
    tool = OffsetTool()
    tool.base_face = face
    tool._loop = [QVector3D(v) for v in face.vertices]
    tool._normal = face.normal()
    tool.distance = 0.10
    tool._commit(vp)
    assert len(scene.mesh.faces) == 2, \
        f"expected ring + inner, got {len(scene.mesh.faces)}"
    assert sum(1 for f in scene.mesh.faces if f.holes) == 1, "no ring left"
    for f in scene.mesh.faces:
        assert f.attrs.get("mat") == "Piedra laja"
