# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Offset on a face that has holes keeps the holes (#537).

The commit deletes the face and builds it again: outward, the face comes
back as the hole of the new ring; inward, the inner region comes back as a
face of its own. Both were rebuilt from the outer outline alone, so a ring
on top of four walls came back as a full square: it covered the room
between the walls and left the walls' top edges open."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from core.topology import offset_loop
from tools.offset import OffsetTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.messages: list[str] = []

    def set_hover(self, *_):
        pass

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.messages.append(text)


def _square(x0, size, z=0.0):
    return [V(x0, x0, z), V(x0 + size, x0, z), V(x0 + size, x0 + size, z),
            V(x0, x0 + size, z)]


def _offset(vp, face, distance):
    tool = OffsetTool()
    tool.base_face = face
    tool._loop = [QVector3D(v) for v in face.vertices]
    tool._normal = face.normal()
    tool._chain, tool._closed = False, True
    tool.dragging = True
    tool.distance = distance
    tool._commit(vp)


def _extent(loop):
    xs = [p.x() for p in loop]
    return round(max(xs) - min(xs), 3)


def _faces_on(mesh, z):
    return [f for f in mesh.faces
            if all(abs(v.z() - z) < 1e-6 for v in f.vertices)]


def _shape(mesh, z):
    """Each face on the plane as (outer size, sorted hole sizes)."""
    return sorted((_extent(f.vertices), sorted(_extent(h) for h in f.holes))
                  for f in _faces_on(mesh, z))


def test_outward_offset_keeps_the_face_s_own_hole():
    scene = Scene()
    vp = _Vp(scene)
    ring = scene.mesh.add_face(_square(0, 3.05), [_square(0.15, 2.75)])
    _offset(vp, ring, -0.61)
    # The eave (4.27 around 3.05) and the ring as it was (3.05 around 2.75).
    assert _shape(scene.mesh, 0.0) == [(3.05, [2.75]), (4.27, [3.05])]


def test_inward_offset_keeps_the_hole_inside_the_inner_face():
    scene = Scene()
    vp = _Vp(scene)
    ring = scene.mesh.add_face(_square(0, 3.05), [_square(0.15, 2.75)])
    _offset(vp, ring, 0.05)
    # The 5 cm strip, and inside it the rest of the ring, still holed.
    assert _shape(scene.mesh, 0.0) == [(2.95, [2.75]), (3.05, [2.95])]


def test_inward_offset_into_a_hole_is_refused_and_changes_nothing():
    scene = Scene()
    vp = _Vp(scene)
    ring = scene.mesh.add_face(_square(0, 3.05), [_square(0.15, 2.75)])
    before = _shape(scene.mesh, 0.0)
    _offset(vp, ring, 0.20)              # deeper than the 15 cm wall
    assert _shape(scene.mesh, 0.0) == before
    assert vp.messages                    # it says why


def test_a_face_without_holes_offsets_as_before():
    scene = Scene()
    vp = _Vp(scene)
    face = scene.mesh.add_face(_square(0, 4))
    _offset(vp, face, 1.0)
    assert _shape(scene.mesh, 0.0) == [(2.0, []), (4.0, [2.0])]
    scene2 = Scene()
    vp2 = _Vp(scene2)
    face2 = scene2.mesh.add_face(_square(0, 4))
    _offset(vp2, face2, -1.0)
    assert _shape(scene2.mesh, 0.0) == [(4.0, []), (6.0, [4.0])]


def test_the_eave_on_top_of_four_walls_leaves_the_solid_closed():
    """#537 as reported: 3.05 square, offset 0.15 in, ring pushed 2.44 up,
    then the top ring offset 0.61 out."""
    from tools.pushpull import PushPullTool
    scene = Scene()
    vp = _Vp(scene)
    m = scene.mesh
    outer = _square(0, 3.05)
    inner = offset_loop([QVector3D(p) for p in outer], V(0, 0, 1), 0.15)
    m.add_face([QVector3D(p) for p in inner])          # the room's floor
    ring = m.add_face(list(outer), [list(inner)])      # the walls' footprint
    pp = PushPullTool()
    pp.base_face = ring
    pp.extrusion = 2.44
    pp._normal = ring.normal()
    pp._prism_cap = False
    pp._anchor = ring.centroid()
    pp._mutate(scene)
    assert not [e for e in m.edges if len(e.faces) == 1]
    top = next(f for f in _faces_on(m, 2.44))
    _offset(vp, top, -0.61)
    assert _shape(m, 2.44) == [(3.05, [2.75]), (4.27, [3.05])]
    # Only the eave's own rim is open — it has one face by nature. The
    # inner walls' top edges keep the ring on them (they were open too).
    open_edges = [e for e in m.edges if len(e.faces) == 1]
    assert len(open_edges) == 4
    for e in open_edges:
        for p in (e.a, e.b):
            assert abs(p.z() - 2.44) < 1e-6
            assert abs(abs(p.x() - 1.525) - 2.135) < 1e-6 \
                or abs(abs(p.y() - 1.525) - 2.135) < 1e-6


def test_undo_brings_the_ring_back():
    scene = Scene()
    vp = _Vp(scene)
    ring = scene.mesh.add_face(_square(0, 3.05), [_square(0.15, 2.75)])
    _offset(vp, ring, -0.61)
    assert vp.history.undo() is True
    assert _shape(scene.mesh, 0.0) == [(3.05, [2.75])]
