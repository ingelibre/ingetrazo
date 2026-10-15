# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Erasing one edge between two coplanar faces removes that edge only.

#631: a rectangle drawn inside a face shares its whole outline with the
face around it. Erasing one side dissolved every shared edge, so the whole
inner outline went with it. The other three sides must stay.

#356: two coplanar faces wound opposite ways fell into the branch for
faces that are not coplanar, and the erase deleted both faces.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D

from core.history import EraseSelectionCommand, History
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _edge(m, a, b):
    va, vb = m.vertex_at(a), m.vertex_at(b)
    return m.find_edge(va, vb) if va is not None and vb is not None else None


def _inner_rect_scene():
    """A 10 × 10 face with a 2 × 2 rectangle drawn inside: the outer face
    has the rectangle as a hole, and the rectangle is its own face."""
    scene = Scene()
    m = scene.mesh
    inner = [V(2, 2), V(4, 2), V(4, 4), V(2, 4)]
    m.add_face([V(0, 0), V(10, 0), V(10, 10), V(0, 10)], [list(inner)])
    m.add_face(list(inner))
    return scene, inner


def test_erasing_one_side_of_an_inner_rectangle_keeps_the_other_three():
    scene, inner = _inner_rect_scene()
    hist = History(scene)
    m = scene.mesh
    side = _edge(m, inner[0], inner[1])
    assert side is not None and len(side.faces) == 2
    hist.execute(EraseSelectionCommand([side]))
    assert hist.last_error is None
    assert _edge(m, inner[0], inner[1]) is None
    for a, b in ((inner[1], inner[2]), (inner[2], inner[3]),
                 (inner[3], inner[0])):
        assert _edge(m, a, b) is not None, "an unselected side vanished"
    # the open rectangle no longer bounds a face: one face, no hole
    assert len(m.faces) == 1
    assert m.faces[0].area() == pytest.approx(100.0)
    assert not m.faces[0].holes
    assert hist.undo() is True
    assert len(m.faces) == 2
    assert _edge(m, inner[0], inner[1]) is not None


def test_erasing_the_seam_of_opposite_wound_coplanar_faces_merges_them():
    scene = Scene()
    hist = History(scene)
    m = scene.mesh
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])          # +Z
    m.add_face([V(1, 0), V(1, 1), V(2, 1), V(2, 0)])          # −Z
    seam = _edge(m, V(1, 0), V(1, 1))
    assert seam is not None and len(seam.faces) == 2
    assert QVector3D.dotProduct(seam.faces[0].normal(),
                                seam.faces[1].normal()) < -0.999
    hist.execute(EraseSelectionCommand([seam]))
    assert hist.last_error is None
    assert len(m.faces) == 1, "both faces of a coplanar pair were deleted"
    assert m.faces[0].area() == pytest.approx(2.0)
    assert _edge(m, V(1, 0), V(1, 1)) is None


def test_erasing_one_divider_of_three_strips_keeps_the_other():
    scene = Scene()
    hist = History(scene)
    m = scene.mesh
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    m.add_face([V(1, 0), V(2, 0), V(2, 1), V(1, 1)])
    m.add_face([V(2, 0), V(3, 0), V(3, 1), V(2, 1)])
    hist.execute(EraseSelectionCommand([_edge(m, V(1, 0), V(1, 1))]))
    assert sorted(round(f.area(), 6) for f in m.faces) == [1.0, 2.0]
    assert _edge(m, V(2, 0), V(2, 1)) is not None


def test_a_painted_face_keeps_its_paint_when_its_seam_is_erased():
    scene = Scene()
    hist = History(scene)
    m = scene.mesh
    left = m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    right = m.add_face([V(1, 0), V(2, 0), V(2, 1), V(1, 1)])
    left.attrs["material"] = right.attrs["material"] = "brick"
    hist.execute(EraseSelectionCommand([_edge(m, V(1, 0), V(1, 1))]))
    assert len(m.faces) == 1
    assert m.faces[0].attrs.get("material") == "brick"
