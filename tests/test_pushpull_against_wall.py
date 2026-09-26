# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pulling a face up against a wall (issue #94, @xyont: «cannot pull up
meet outer face… push down working properly»).

A square drawn on a step's lower tread, touching the riser, pulled UP: its
side lands flat against the riser. That strip is inside the solid now, so
the riser loses it and the side is never built — as in SketchUp. The riser
used to stay as an «interior partition» with the side standing on it, and
the guard refused the pull; with that fixed, the riser and the tread (both
U-shaped now) were probed from their vertex average, which sits in the
notch, and got marked interior — a closed solid 2.3 m³ short."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import History
from core.orient import is_closed, signed_volume
from core.scene import Scene
from tests import test_pushpull_ux as T


def _on(scene, pred):
    return [f for f in scene.faces if all(pred(v) for v in f.vertices)]


def _step_with_square():
    """A 4×4×3 block with its front half lowered 1 m (a step), and a 1 m
    square drawn on the tread against the riser."""
    scene = Scene()
    hist = History(scene)
    T._cube(scene, hist, size=4.0, height=3.0)
    hist.execute(build_add_edges(scene, [(V(0, 2, 3), V(4, 2, 3))]))
    front = [f for f in _on(scene, lambda v: abs(v.z() - 3) < 1e-9)
             if max(v.y() for v in f.vertices) <= 2 + 1e-9][0]
    T._push(scene, front, -1.0)
    hist.execute(build_add_edges(scene, [(V(1, 1, 2), V(2, 1, 2)),
                                         (V(2, 1, 2), V(2, 2, 2)),
                                         (V(1, 1, 2), V(1, 2, 2))]))
    square = [f for f in _on(scene, lambda v: abs(v.z() - 2) < 1e-9)
              if len(f.vertices) == 4 and abs(f.area() - 1.0) < 1e-6][0]
    assert abs(signed_volume(scene.mesh) - 40.0) < 1e-6
    return scene, square


@pytest.mark.parametrize("d", [0.5, 1.0, 1.5, -0.5])
def test_pulling_against_the_riser_keeps_a_true_solid(d):
    scene, square = _step_with_square()
    vp = T._push(scene, square, d)
    m = scene.mesh
    assert vp.last_status is None                     # not refused
    assert is_closed(m)
    assert not any(f.interior for f in m.faces)      # no fake partitions
    assert all(len(e.faces) == 2 for e in m.edges)
    assert abs(signed_volume(m) - (40.0 + d)) < 1e-6


def test_the_riser_loses_the_strip_the_pull_covers():
    scene, square = _step_with_square()
    T._push(scene, square, 0.5)
    riser = _on(scene, lambda v: abs(v.y() - 2) < 1e-9)
    assert len(riser) == 1                            # no side left on it
    assert abs(riser[0].area() - (4.0 * 1.0 - 1.0 * 0.5)) < 1e-6
