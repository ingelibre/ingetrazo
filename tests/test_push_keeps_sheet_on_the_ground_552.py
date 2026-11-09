# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pushing a square down must not delete a sheet drawn on the ground beside
the solid (#552, @pacaeiro: «after starting to Push/pull the square face
down, the faces with Z = 0 disappear»).

His model, coordinates rounded: an L-shaped box with a square column in its
notch (open underneath) and a triangle on the ground that runs into the
notch. The per-plane rebuild reaches the ground through the column's open
bottom and hands every face there back as a new object; the triangle came
back unchanged, was then counted as one of the push's own faces, and the
next round dropped it as debris."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.history import History
from core.scene import Scene
from tests import test_pushpull_ux as T

_FACES = [
    [(4.0, -1.2, 0.0), (4.0, -2.6, 0.0), (5.4, -2.6, 0.0), (5.4, -3.5, 0.0), (6.4, -3.5, 0.0), (6.4, -1.2, 0.0)],
    [(4.0, -2.6, 0.0), (3.0, -2.6, 0.0), (5.4, -5.0, 0.0), (5.4, -3.5, 0.0), (4.0, -3.5, 0.0)],
    [(4.0, -1.2, 2.1), (4.0, -2.6, 2.1), (5.4, -2.6, 2.1), (5.4, -3.5, 2.1), (6.4, -3.5, 2.1), (6.4, -1.2, 2.1)],
    [(4.0, -1.2, 0.0), (4.0, -2.6, 0.0), (4.0, -2.6, 2.1), (4.0, -1.2, 2.1)],
    [(4.0, -2.6, 0.0), (5.4, -2.6, 0.0), (5.4, -2.6, 2.1), (4.0, -2.6, 2.1)],
    [(5.4, -2.6, 0.0), (5.4, -3.5, 0.0), (5.4, -3.5, 2.1), (5.4, -2.6, 2.1)],
    [(5.4, -3.5, 0.0), (6.4, -3.5, 0.0), (6.4, -3.5, 2.1), (5.4, -3.5, 2.1)],
    [(6.4, -3.5, 0.0), (6.4, -1.2, 0.0), (6.4, -1.2, 2.1), (6.4, -3.5, 2.1)],
    [(6.4, -1.2, 0.0), (4.0, -1.2, 0.0), (4.0, -1.2, 2.1), (6.4, -1.2, 2.1)],
    [(4.0, -2.6, 2.1), (4.0, -3.5, 2.1), (5.4, -3.5, 2.1), (5.4, -2.6, 2.1)],
    [(4.0, -2.6, 0.0), (4.0, -3.5, 0.0), (4.0, -3.5, 2.1), (4.0, -2.6, 2.1)],
    [(4.0, -3.5, 0.0), (5.4, -3.5, 0.0), (5.4, -3.5, 2.1), (4.0, -3.5, 2.1)],
]
_TRIANGLE_AREA = 1.62     # the 5-gon on the ground: triangle minus the notch


def _model():
    scene = Scene()
    for pts in _FACES:
        scene.mesh.add_face([V(*p) for p in pts])
    square = next(f for f in scene.mesh.faces
                  if len(f.vertices) == 4 and abs(f.area() - 1.26) < 1e-4
                  and all(abs(v.z() - 2.1) < 1e-5 for v in f.vertices))
    return scene, square


def _ground(scene):
    return [f for f in scene.mesh.faces
            if all(abs(v.z()) < 1e-5 for v in f.vertices)]


def test_the_model_has_the_triangle_on_the_ground():
    scene, _ = _model()
    assert any(len(f.vertices) == 5 and abs(f.area() - _TRIANGLE_AREA) < 1e-4
               for f in _ground(scene))


@pytest.mark.parametrize("d", [-0.02, -1.1, -1.5, -2.1, 0.9])
def test_pushing_the_square_keeps_the_triangle(d):
    scene, square = _model()
    History(scene)
    vp = T._push(scene, square, d)
    assert vp.last_status is None
    assert any(len(f.vertices) == 5 and abs(f.area() - _TRIANGLE_AREA) < 1e-4
               for f in _ground(scene))
