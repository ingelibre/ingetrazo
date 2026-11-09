# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Reverse Faces inside a group must show at once (#197, @fafecm,
@joejivaros: «shows no change until the face is deleted and the deletion
undone»).

The face data was flipped; the cached group chunk was not. Reversing a
loop changes no count, no coordinate and no paint — everything the
chunk's fingerprint looks at — so the viewport went on serving the old
triangles until some edit changed a count.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QVector3D

from core.group import Group
from core.history import FlipFacesCommand, History
from core.mesh import Mesh
from core.scene import Scene
from tests.test_chunk_stale_materials import _stub


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _facing_z(chunk) -> float:
    """The z of the first cached triangle's normal: its winding."""
    e1 = np.asarray(chunk["e1"], dtype=float).reshape(-1, 3)[0]
    e2 = np.asarray(chunk["e2"], dtype=float).reshape(-1, 3)[0]
    return float(np.cross(e1, e2)[2])


def _group_with_a_floor(scene):
    mesh = Mesh()
    face = mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(mesh, name="Piso")
    scene.groups.append(g)
    return g, face


def test_reverse_faces_inside_a_group_redraws_the_group():
    scene = Scene()
    g, face = _group_with_a_floor(scene)
    vp = _stub(scene)
    before = _facing_z(vp._group_chunk(g))
    history = History(scene)
    history.execute(FlipFacesCommand([face]))
    after = _facing_z(vp._group_chunk(g))
    assert before * after < 0, "the group still draws the old winding"
    history.undo()
    assert _facing_z(vp._group_chunk(g)) * before > 0, \
        "undo did not bring the old winding back on screen"


def test_an_untouched_group_keeps_its_chunk():
    """The fix must not cost the other groups their cached chunk."""
    scene = Scene()
    g, face = _group_with_a_floor(scene)
    other, _ = _group_with_a_floor(scene)
    vp = _stub(scene)
    vp._group_chunk(g)
    kept = vp._group_chunk(other)
    History(scene).execute(FlipFacesCommand([face]))
    assert vp._group_chunk(other) is kept
