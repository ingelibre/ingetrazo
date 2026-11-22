# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Transforms read a QMatrix4x4 without calling it (#1405).

Some PySide6 builds (Qt 6.10) dropped ``QMatrix4x4.__call__``: reading an
element as ``m(row, col)`` raised "object is not callable" when a textured
group was transformed (``_remap_uvws``), when loose textured faces were
copied (``transformed_attrs``) and when a part's points were measured
(``part_points``). ``_NoCall`` stands for such a build on any machine."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, transformed_attrs, transformed_mesh
from core.mesh import Mesh
from core.parts import part_points


class _NoCall(QMatrix4x4):
    """A QMatrix4x4 that, like the Qt 6.10 one, cannot be called."""

    def __call__(self, *args):
        raise TypeError("'PySide6.QtGui.QMatrix4x4' object is not callable")

    def inverted(self):
        inv, ok = super().inverted()
        return _NoCall(inv), ok


def _turn_and_move() -> _NoCall:
    m = _NoCall()
    m.translate(2.0, -1.0, 0.5)
    m.rotate(30.0, 0.0, 0.0, 1.0)
    m.rotate(15.0, 1.0, 0.0, 0.0)
    m.scale(1.5)
    return m


# A world→UV map that is not the plain projection: U and V both lean.
UVW = [2.0, 0.5, 0.0, 0.25, -0.5, 3.0, 0.0, -0.75]
TEX = {"path": "/x/wood.png", "sw": 0.5, "sh": 0.5, "rot": 0.0}
SQUARE = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)]


def _uv(uvw, p):
    return (uvw[0] * p.x() + uvw[1] * p.y() + uvw[2] * p.z() + uvw[3],
            uvw[4] * p.x() + uvw[5] * p.y() + uvw[6] * p.z() + uvw[7])


def _textured_square(uvw=None) -> Mesh:
    mesh = Mesh()
    f = mesh.add_face(list(SQUARE))
    f.attrs["texture"] = {**TEX, "uvw": list(uvw)} if uvw else dict(TEX)
    return mesh


def test_the_stand_in_matrix_cannot_be_called():
    with pytest.raises(TypeError):
        _turn_and_move()(0, 3)


def test_a_transformed_textured_mesh_keeps_its_uvs():
    m = _turn_and_move()
    new = transformed_mesh(_textured_square(UVW), m)
    (face,) = new.faces
    uvw = face.attrs["texture"]["uvw"]
    assert all(isinstance(c, float) for c in uvw)
    for p in SQUARE:
        want = _uv(UVW, p)
        got = _uv(uvw, m.map(p))
        assert got == pytest.approx(want, abs=1e-5)


def test_the_implicit_projection_is_carried_along_too():
    """A face still on the planar projection gets it written out first."""
    new = transformed_mesh(_textured_square(), _turn_and_move())
    (face,) = new.faces
    assert len(face.attrs["texture"]["uvw"]) == 8


def test_copied_loose_face_attrs_keep_their_uvs():
    m = _turn_and_move()
    out = transformed_attrs({"texture": {**TEX, "uvw": list(UVW)}}, m)
    uvw = out["texture"]["uvw"]
    for p in SQUARE:
        assert _uv(uvw, m.map(p)) == pytest.approx(_uv(UVW, p), abs=1e-5)


def test_a_parts_points_follow_its_placement():
    m = _turn_and_move()
    g = Group(_textured_square(), name="board")
    g.xform = m
    pts = part_points(g)
    assert pts.shape == (4, 3)
    for row, p in zip(pts, SQUARE):
        q = m.map(p)
        assert tuple(row) == pytest.approx((q.x(), q.y(), q.z()), abs=1e-5)
