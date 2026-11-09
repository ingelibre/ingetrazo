# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rectangle with a small square drawn in one corner; the L is pulled up.

#550 (@tomlai-git: «PushPull ends up with initial face facing inwards»):
the L shares an edge with the square, a sheet, so the new block was part
of an open piece the orientation pass leaves alone, and its base stayed
facing into it."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import History
from core.orient import signed_volume
from core.scene import Scene
from tests import test_pushpull_ux as T


def _model():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 3, 0), V(0, 3, 0)])
    hist.execute(build_add_edges(
        scene, [(V(3, 0, 0), V(3, 1, 0)), (V(3, 1, 0), V(4, 1, 0))],
        detect_faces=True))
    return scene


def _on_ground(scene, area):
    return next(f for f in scene.mesh.faces
                if abs(f.area() - area) < 1e-6
                and all(abs(v.z()) < 1e-6 for v in f.vertices))


@pytest.mark.parametrize("h", [2.0, -2.0])
def test_the_l_block_faces_outward(h):
    scene = _model()
    T._push(scene, _on_ground(scene, 11.0), h)
    base = _on_ground(scene, 11.0)
    # The base faces away from the sweep; the whole block winds outward.
    assert base.normal().z() * h < 0
    assert signed_volume(scene.mesh) == pytest.approx(22.0, abs=1e-6)
