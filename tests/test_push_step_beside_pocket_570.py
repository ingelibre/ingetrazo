# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pushing up the corner triangle of a notch must leave clean outer walls
(#570, @pacaeiro: «When push triangle face up some faces appear wrong»).

His model, coordinates rounded: a box with a rotated pocket sunk in its top
whose corner reaches the outer walls, and the triangle between the pocket
and that corner on the same floor. Raised, the triangle's new side wall and
the pocket's wall meet along a short vertical line that only touches each
outer wall. The per-plane rebuild kept that line as a crease of the wall,
so the wall's outline ran up it and back: a spur that split nothing,
triangulated into slivers facing the wrong way and left two edges with
four faces."""
from __future__ import annotations

from collections import Counter

import pytest
from PySide6.QtGui import QVector3D as V

from core.history import History
from core.orient import is_closed, signed_volume
from core.scene import Scene
from tests import test_pushpull_ux as T

_FACES = [
    [(4.676, 3.397, 0.0), (4.676, 0.583, 0.0), (2.942, 0.583, 0.0), (2.942, 3.397, 0.0)],
    [(2.942, 3.397, 1.663), (2.942, 3.397, 0.0), (2.942, 0.583, 0.0), (2.942, 0.583, 1.663)],
    [(4.676, 3.397, 1.663), (4.676, 3.397, 0.0), (2.942, 3.397, 0.0), (2.942, 3.397, 1.663)],
    [(3.938, 1.685, 1.026), (3.938, 1.685, 1.663), (3.529, 1.095, 1.663), (3.529, 1.095, 1.026)],
    [(4.676, 1.173, 1.026), (4.676, 1.173, 1.663), (3.938, 1.685, 1.663), (3.938, 1.685, 1.026)],
    [(4.267, 0.583, 1.663), (4.267, 0.583, 1.026), (3.529, 1.095, 1.026), (3.529, 1.095, 1.663)],
    [(2.942, 0.583, 1.663), (4.267, 0.583, 1.663), (3.529, 1.095, 1.663), (3.938, 1.685, 1.663),
     (4.676, 1.173, 1.663), (4.676, 3.397, 1.663), (2.942, 3.397, 1.663)],
    [(2.942, 0.583, 0.0), (4.676, 0.583, 0.0), (4.676, 0.583, 1.026), (4.267, 0.583, 1.026),
     (4.267, 0.583, 1.663), (2.942, 0.583, 1.663)],
    [(4.676, 0.583, 0.0), (4.676, 3.397, 0.0), (4.676, 3.397, 1.663), (4.676, 1.173, 1.663),
     (4.676, 1.173, 1.026), (4.676, 0.583, 1.026)],
    [(4.676, 1.173, 1.026), (4.267, 0.583, 1.026), (4.676, 0.583, 1.026)],
    [(3.529, 1.095, 1.026), (4.267, 0.583, 1.026), (4.676, 1.173, 1.026), (3.938, 1.685, 1.026)],
]


def _model():
    scene = Scene()
    for pts in _FACES:
        scene.mesh.add_face([V(*p) for p in pts])
    triangle = next(f for f in scene.mesh.faces if len(f.vertices) == 3)
    return scene, triangle


def _spurs(mesh) -> list:
    """Face loops that run out along an edge and straight back."""
    out = []
    for f in mesh.faces:
        for lp in (f.vertices, *f.holes):
            n = len(lp)
            if any((lp[i - 1] - lp[(i + 1) % n]).length() < 1e-6
                   for i in range(n)):
                out.append(f)
                break
    return out


@pytest.mark.parametrize("d", [0.3, 0.6369, 0.9, 1.5])
def test_raising_the_corner_triangle_leaves_clean_walls(d):
    scene, triangle = _model()
    History(scene)
    v0, area = signed_volume(scene.mesh), triangle.area()
    vp = T._push(scene, triangle, d)
    m = scene.mesh
    assert vp.last_status is None
    assert _spurs(m) == []
    assert set(Counter(len(e.faces) for e in m.edges)) == {2}
    assert is_closed(m)
    assert signed_volume(m) == pytest.approx(v0 + area * d, abs=1e-4)
