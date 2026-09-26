# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rectangle drawn ACROSS a face — every corner on its boundary — splits it
(found by Marco testing #94: a rectangle across a stair tread, from the
nosing to the riser, left the tread whole with the rectangle lying on top,
and pulling it built a broken solid; drawn with lines it was clean)."""
from __future__ import annotations

from collections import Counter

import pytest
from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.orient import is_closed, signed_volume
from core.scene import Scene
from tests import test_pushpull_ux as T


def _rect(scene, hist, x0, x1, y0, y1, z):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    hist.execute(build_add_edges(
        scene, [(c[i], c[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(c))]))   # the tool's way


def _step():
    scene = Scene()
    hist = History(scene)
    T._cube(scene, hist, size=4.0, height=3.0)
    hist.execute(build_add_edges(scene, [(V(0, 2, 3), V(4, 2, 3))]))
    front = [f for f in scene.faces
             if all(abs(v.z() - 3) < 1e-9 for v in f.vertices)
             and max(v.y() for v in f.vertices) <= 2 + 1e-9][0]
    T._push(scene, front, -1.0)
    return scene, hist


def _areas_at(scene, z):
    return sorted(round(f.area(), 6) for f in scene.faces
                  if all(abs(v.z() - z) < 1e-9 for v in f.vertices))


@pytest.mark.parametrize("x0, x1, pieces", [
    (1, 2, [2.0, 2.0, 4.0]),     # a band in the middle: three faces
    (0, 1, [2.0, 6.0]),          # at the corner: left, nosing and riser
    (3, 4, [2.0, 6.0]),
])
def test_the_band_splits_the_tread(x0, x1, pieces):
    scene, hist = _step()
    _rect(scene, hist, x0, x1, 0, 2, 2)
    assert _areas_at(scene, 2) == pieces            # no face on top of another
    assert Counter(len(e.faces) for e in scene.mesh.edges) == {
        2: len(scene.mesh.edges)}
    hist.undo()
    assert _areas_at(scene, 2) == [8.0]             # undo gives the tread back


@pytest.mark.parametrize("d", [0.5, -0.5])
def test_pulling_the_band_keeps_a_true_solid(d):
    scene, hist = _step()
    _rect(scene, hist, 0, 1, 0, 2, 2)
    band = [f for f in scene.faces if abs(f.area() - 2.0) < 1e-9
            and all(abs(v.z() - 2) < 1e-9 for v in f.vertices)
            and max(v.x() for v in f.vertices) <= 1 + 1e-9][0]
    vp = T._push(scene, band, d)
    assert vp.last_status is None
    assert is_closed(scene.mesh)
    assert all(len(e.faces) == 2 for e in scene.mesh.edges)
    assert abs(signed_volume(scene.mesh) - (40.0 + 2.0 * d)) < 1e-6


def test_a_band_across_a_flat_face_on_the_ground():
    scene = Scene()
    hist = History(scene)
    _rect(scene, hist, 0, 4, 0, 3, 0)
    _rect(scene, hist, 1, 2, 0, 3, 0)
    assert _areas_at(scene, 0) == [3.0, 3.0, 6.0]
