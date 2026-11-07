# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A dimension on an edge a push collapses comes back with the edge.

#254 (@RaphaelNunes10): a box, a dimension on a vertical edge, then the
top pushed all the way down. The top vertex welds into the bottom one and
the endpoint took that one; undo brought the box back but the dimension
stayed flat on the floor. The oldest hold still alive now wins, so undo
puts it back on its vertex."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.dimension import Dimension
from core.history import AddDimensionCommand, History
from core.scene import Scene
from tests import test_pushpull_ux as T


def _box():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 3, 0), V(0, 3, 0)])
    T._push(scene, scene.mesh.faces[0], 2.0)
    d = Dimension(V(4, 0, 0), V(4, 0, 2), V(1, 0, 0))
    hist.execute(AddDimensionCommand(d))
    assert d.anchored and d.value() == pytest.approx(2.0)
    return scene, hist, d


def _top(scene):
    return next(f for f in scene.mesh.faces
                if f.normal().z() > 0.99
                and all(abs(v.z() - 2.0) < 1e-6 for v in f.vertices))


def test_undo_of_the_collapse_brings_the_dimension_back():
    scene, hist, d = _box()
    vp = T._push(scene, _top(scene), -2.0)
    assert len(scene.mesh.faces) < 6       # collapsed flat
    d.value()                              # the end falls onto the floor
    vp.history.undo()
    assert len(scene.mesh.faces) == 6
    assert d.b == V(4, 0, 2) and d.value() == pytest.approx(2.0)
    assert d.anchored

