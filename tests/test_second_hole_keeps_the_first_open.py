# SPDX-License-Identifier: GPL-3.0-or-later
"""A second hole through a thin board leaves the first one open (tutorial
hunt 2, B3).

The birdhouse front: a 50.8 mm entrance through a 15.9 mm board, then a
12.7 mm perch hole -- and the entrance came back as a disc over the face,
24 edges with three faces. On a 0.2 m board with holes of 40 and 10 mm the
small hole's wall quads are under 1 cm², the floor the face tracer used to
read as noise (see test_small_outlines_make_faces)."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.topology import _point_in_face_solid
from tools.circle import CircleTool


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _hole(vp, cx, cy, r, z):
    from tests import test_pushpull_ux as T
    pts = [V(cx + r * math.cos(2 * math.pi * k / 24),
             cy + r * math.sin(2 * math.pi * k / 24), z) for k in range(24)]
    CircleTool()._commit(vp, pts)
    disc = next(f for f in vp.scene.mesh.faces
                if len(f.vertices) == 24 and not f.hole_loops
                and all(abs(v.z() - z) < 1e-9 for v in f.vertices)
                and abs(f.centroid().x() - cx) < 1e-6)
    T._push(vp.scene, disc, -z)


def test_the_entrance_stays_open_after_the_perch_hole(app):
    from tests import test_pushpull_ux as T
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.flash_status = lambda *a, **k: None
    T._cube(vp.scene, vp.history, size=0.2, height=0.025)
    m = vp.scene.mesh
    _hole(vp, 0.06, 0.12, 0.04, 0.025)
    assert len(m.faces) == 30
    _hole(vp, 0.14, 0.05, 0.01, 0.025)
    assert len(m.faces) == 54
    assert sum(1 for e in m.edges if len(e.faces) > 2) == 0
    top = [f for f in m.faces
           if all(abs(v.z() - 0.025) < 1e-9 for v in f.vertices)]
    assert not any(_point_in_face_solid(f, V(0.06, 0.12, 0.025)) for f in top)
