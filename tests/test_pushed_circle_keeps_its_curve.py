# SPDX-License-Identifier: GPL-3.0-or-later
"""The ring a pushed circle leaves on top is a curve again (#626, and the
tutorial hunt's A10).

A circle selects whole with one click because its edges share a curve id;
the cap Push/Pull built was new edges without one, so a click on the top
rim of a cylinder took one segment of 24."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from tests import test_pushpull_ux as T
from tools.circle import CircleTool


@pytest.fixture(scope="module")
def viewport():
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.flash_status = lambda *a, **k: None
    return vp


def _top_rim(mesh, z):
    return [e for e in mesh.edges
            if abs(e.a.z() - z) < 1e-6 and abs(e.b.z() - z) < 1e-6]


def test_the_top_of_a_cylinder_selects_whole(viewport):
    viewport.scene.mesh.clear()
    pts = [V(math.cos(2 * math.pi * k / 24), math.sin(2 * math.pi * k / 24), 0)
           for k in range(24)]
    CircleTool()._commit(viewport, pts)
    mesh = viewport.scene.mesh
    disc = mesh.faces[0]
    T._push(viewport.scene, disc, 2.0 if disc.normal().z() > 0 else -2.0)
    rim = _top_rim(mesh, 2.0)
    assert len(rim) == 24
    assert len(mesh.curve_edges(rim[0])) == 24
    bottom = _top_rim(mesh, 0.0)
    assert len(mesh.curve_edges(bottom[0])) == 24
    assert rim[0].curve != bottom[0].curve      # two curves, not one
