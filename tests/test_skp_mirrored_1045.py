"""A component scaled by -1 in a .skp keeps its faces' fronts outward (#1045).

A placement with a negative determinant reverses the winding of every ring it
maps, so a face copied through it shows its back unless its ring is reversed
back. Instances that stay instances (``Group.xform``) are handled by the
viewport; these tests cover the nested ones the importer flattens.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from PySide6.QtGui import QMatrix4x4

from formats import skp_openskp


def _square_def(id, name, instances=()):
    # A 10 in square in the XY plane, wound counter-clockwise seen from +Z,
    # so its front faces up (the fake face's stored normal says so too).
    return NS(
        id=id, name=name,
        vertices={1: NS(id=1, x=0, y=0, z=0), 2: NS(id=2, x=10, y=0, z=0),
                  3: NS(id=3, x=10, y=10, z=0), 4: NS(id=4, x=0, y=10, z=0)},
        edges={10: NS(id=10, v1_id=1, v2_id=2), 11: NS(id=11, v1_id=2, v2_id=3),
               12: NS(id=12, v1_id=3, v2_id=4), 13: NS(id=13, v1_id=4, v2_id=1)},
        faces={20: NS(id=20, loops=[[(10, 1), (11, 1), (12, 1), (13, 1)]],
                      normal=(0, 0, 1), material_id=None)},
        instances=list(instances),
    )


def _empty_def(id, name, instances=()):
    return NS(id=id, name=name, vertices={}, edges={}, faces={},
              instances=list(instances))


def _ring_normal_z(ring):
    """Z of the ring's Newell normal: positive when it winds counter-clockwise
    seen from +Z, i.e. when its front faces up."""
    pts = [tuple(float(c) for c in p[:3]) for p in ring]
    nz = 0.0
    for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:] + pts[:1]):
        nz += (x0 - x1) * (y0 + y1)
    return nz


def _mirror_x():
    m = QMatrix4x4()
    m.scale(-1.0, 1.0, 1.0)
    return m


def test_a_mirrored_placement_keeps_the_face_front_up():
    door = _square_def(6, "Door")
    out: list = []
    skp_openskp._collect(door, _mirror_x(), {6: door}, {}, out, 0, frozenset())
    assert len(out) == 1
    outer, holes, _attrs = out[0]
    assert _ring_normal_z(outer) > 0, "mirrored copy shows its back"


def test_an_unmirrored_placement_is_left_as_it_was():
    door = _square_def(6, "Door")
    out: list = []
    skp_openskp._collect(door, QMatrix4x4(), {6: door}, {}, out, 0, frozenset())
    assert _ring_normal_z(out[0][0]) > 0


@pytest.mark.parametrize("matrix, mirrored", [
    ([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1], False),
    ([-1, 0, 0, 0, 1, 0, 0, 0, 1, 40, 0, 0, 1], True),     # scaled -1 in X
    ([1, 0, 0, 0, -1, 0, 0, 0, 1, 0, 40, 0, 1], True),     # scaled -1 in Y
    ([-1, 0, 0, 0, -1, 0, 0, 0, 1, 40, 40, 0, 1], False),  # a half turn, not a mirror
])
def test_a_nested_door_and_its_mirrored_twin_both_face_out(matrix, mirrored):
    # The report: a cupboard door made a component, copied and scaled by -1
    # in X for the other hand. Both doors sit inside one cupboard group; the
    # importer flattens them into the cupboard, and both must keep their
    # painted side out.
    door = _square_def(6, "Door")
    left = NS(ref_idx=6, matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1])
    right = NS(ref_idx=6, matrix=matrix)
    cupboard = _empty_def(5, "Cupboard", instances=[left, right])
    root = _empty_def(0, "ROOT_MODEL",
                      instances=[NS(ref_idx=5, matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1,
                                                       0, 0, 0, 1])])
    payload = skp_openskp._adapt(NS(definitions={0: root, 5: cupboard, 6: door}),
                                 "kitchen")
    faces = [f for p in payload.get("protos", []) for f in p["faces"]]
    faces += [f for g in payload.get("groups", []) for f in g["faces"]]
    assert len(faces) == 2
    for outer, _holes, _attrs in faces:
        assert _ring_normal_z(outer) > 0
