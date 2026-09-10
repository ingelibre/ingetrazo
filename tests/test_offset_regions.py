# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Offset that can DROP what collapses — and split when the shape does.

`core.topology.offset_loop` slides each edge and re-intersects its
neighbours: exact while every corner survives, and it gives up the moment
one disappears. Marco's paved slab carries the segmented bite the round
plaza takes out of it, and refused any inward offset past 2.65 cm; SketchUp
does it, because it removes what closes.

`core.offset` slides, mitres, hands the segments to the planar arrangement —
which already computes every crossing for RebuildPlaneFacesCommand — and
keeps the regions that really sit `d` inside.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History
from core.mesh import Mesh
from core.offset import interior_point, offset_regions
from core.scene import Scene
from core.topology import offset_loop
from tools.offset import OffsetTool

N = QVector3D(0.0, 0.0, 1.0)


def V(x, y):
    return QVector3D(float(x), float(y), 0.0)


def _area(loop):
    return Mesh().add_face(list(loop)).area()


def _perimeter(loop):
    n = len(loop)
    return sum((loop[(i + 1) % n] - loop[i]).length() for i in range(n))


#: A saw-toothed edge, the shape of a segmented arc bitten out of a strip.
SAW = ([V(0, 0), V(10, 0), V(10, 5)]
       + [V(10 - 0.5 * k, 5 - (0.3 if k % 2 else 0.0)) for k in range(1, 19)]
       + [V(0, 5)])

#: Two 4x4 blocks joined by a 60 cm neck: it comes apart when pinched.
DUMBBELL = [V(0, 0), V(4, 0), V(4, 1.7), V(6, 1.7), V(6, 0), V(10, 0),
            V(10, 4), V(6, 4), V(6, 2.3), V(4, 2.3), V(4, 4), V(0, 4)]

#: 2.4 m x 20 cm: 10 cm inward is exactly nothing.
KERB = [V(0, 0), V(2.4, 0), V(2.4, 0.2), V(0, 0.2)]


def test_a_simple_offset_matches_the_slide_and_intersect_area():
    square = [V(0, 0), V(10, 0), V(10, 5), V(0, 5)]
    assert offset_loop(square, N, 0.10) is not None      # the old path agrees
    regions = offset_regions(square, N, 0.10)
    assert len(regions) == 1
    got = _area(regions[0][0])
    # Mitre corners add a hair over the naive perimeter estimate.
    assert _area(square) - _perimeter(square) * 0.10 <= got <= _area(square)


def test_a_concave_loop_offsets_too():
    ell = [V(0, 0), V(10, 0), V(10, 4), V(6, 4), V(6, 8), V(0, 8)]
    regions = offset_regions(ell, N, 0.10)
    assert len(regions) == 1
    assert _area(regions[0][0]) < _area(ell)


def test_a_saw_toothed_edge_no_longer_refuses():
    """The shape of Marco's slab. Its teeth are 30 cm, so 20 cm inward eats
    every pocket — and the rest of the face must still come through."""
    assert offset_regions(SAW, N, 0.10)
    deep = offset_regions(SAW, N, 0.20)
    assert deep, "the whole face was thrown away with its pockets"
    assert _area(deep[0][0]) < _area(SAW)


def test_a_pinched_shape_comes_apart():
    assert len(offset_regions(DUMBBELL, N, 0.25)) == 1
    halves = offset_regions(DUMBBELL, N, 0.40)
    assert len(halves) == 2
    for loop, _holes in halves:
        assert abs(_area(loop) - 3.2 * 3.2) < 0.05      # 4 m block, 0.4 in


def test_an_offset_that_consumes_everything_returns_nothing():
    assert offset_regions(KERB, N, 0.10) == []
    assert offset_regions(KERB, N, 0.50) == []


def test_outward_offset_grows_the_shape():
    square = [V(0, 0), V(10, 0), V(10, 5), V(0, 5)]
    regions = offset_regions(square, N, -0.10)
    assert len(regions) == 1
    assert _area(regions[0][0]) > _area(square)


def test_degenerate_input_is_refused_quietly():
    assert offset_regions([V(0, 0), V(1, 0)], N, 0.1) == []
    assert offset_regions([V(0, 0), V(1, 0), V(2, 0)], N, 0.1) == []
    assert offset_regions(DUMBBELL, QVector3D(0, 0, 0), 0.1) == []


def test_interior_point_of_a_concave_loop_is_really_inside():
    ell = [V(0, 0), V(10, 0), V(10, 4), V(6, 4), V(6, 8), V(0, 8)]
    p = interior_point(ell, N)
    assert p is not None
    from core.offset import _inside
    assert _inside(p, ell, N)


# ---- through the tool -------------------------------------------------------

class _VP:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.said = []

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.said.append(text)


def _offset(vp, face, distance):
    tool = OffsetTool()
    tool.base_face = face
    tool._loop = [QVector3D(v) for v in face.vertices]
    tool._normal = face.normal()
    tool.distance = distance
    tool._commit(vp)


def test_the_tool_builds_a_ring_with_one_hole_per_piece():
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(p) for p in DUMBBELL])
    face.attrs["mat"] = "Piedra laja"
    vp = _VP(scene)
    _offset(vp, face, 0.40)
    assert not vp.said
    rings = [f for f in scene.mesh.faces if f.holes]
    assert len(rings) == 1
    assert len(rings[0].holes) == 2, "the two halves must both be holes"
    assert len(scene.mesh.faces) == 3            # ring + two halves
    for f in scene.mesh.faces:
        assert f.attrs.get("mat") == "Piedra laja"


def test_the_tool_undoes_a_split_offset_in_one_step():
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(p) for p in DUMBBELL])
    vp = _VP(scene)
    _offset(vp, face, 0.40)
    assert len(scene.mesh.faces) == 3
    vp.history.undo()
    assert len(scene.mesh.faces) == 1


def test_the_tool_still_refuses_out_loud_when_nothing_survives():
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(p) for p in KERB])
    vp = _VP(scene)
    _offset(vp, face, 0.10)
    assert len(scene.mesh.faces) == 1
    assert vp.said


#: The face Marco reported, lifted from his session and moved to the origin:
#: a strip with the segmented bite the round plaza takes out of it. The
#: slide-and-intersect path refuses anything past 2.65 cm on it.
#:
#: Its normal points DOWN, and that is not a detail: with +Z the winding
#: reads the other way round, "inward" becomes outward and every distance
#: sails through. Getting that wrong is how a test proves nothing.
PLAZA_YANQUE = [
    V(0.0000, 0.0000),
    V(0.0000, 2.4000),
    V(3.8167, 2.4000),
    V(3.6874, 2.1498),
    V(3.5576, 1.7338),
    V(3.5021, 1.3015),
    V(3.5224, 0.8662),
    V(3.6180, 0.4411),
    V(3.7860, 0.0390),
    V(3.8109, 0.0000),
]


PLAZA_YANQUE_N = QVector3D(0.0, 0.0, -1.0)


def test_the_face_from_the_report_takes_the_offset_it_was_asked_for():
    assert offset_loop(PLAZA_YANQUE, PLAZA_YANQUE_N, 0.10) is None, \
        "the old path is supposed to refuse this one"
    for distance in (0.05, 0.10, 0.20, 0.30):
        regions = offset_regions(PLAZA_YANQUE, PLAZA_YANQUE_N, distance)
        assert len(regions) == 1, (distance, len(regions))
        got = _area(regions[0][0])
        assert got < _area(PLAZA_YANQUE)
        assert got > 0.5 * _area(PLAZA_YANQUE)
