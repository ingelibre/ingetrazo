# SPDX-License-Identifier: GPL-3.0-or-later
"""A cylinder drawn the usual way — Circle, Push/Pull, Make Group — keeps
its circles as curves through a Subtract, its undo and its redo: one click
still selects the whole rim the cut did not touch."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core import solids
from core.history import MakeGroupCommand
from tests import test_pushpull_ux as T
from tests.test_solid_tools import BLUE, _box
from tools.circle import CircleTool

pytest.importorskip("manifold3d")


@pytest.fixture(scope="module")
def viewport():
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.flash_status = lambda *a, **k: None
    return vp


def _rim_curves(mesh, z):
    """Curve sizes of the edges lying at height ``z`` on the radius."""
    sizes: dict = {}
    for e in mesh.edges:
        if (abs(e.a.z() - z) < 1e-6 and abs(e.b.z() - z) < 1e-6
                and abs(math.hypot(e.a.x(), e.a.y()) - 1) < 1e-6
                and abs(math.hypot(e.b.x(), e.b.y()) - 1) < 1e-6):
            sizes[e.curve] = sizes.get(e.curve, 0) + 1
    return sorted(sizes.items(), key=lambda kv: -kv[1])


def test_a_drawn_cylinder_keeps_its_circles_through_a_subtract(viewport):
    scene = viewport.scene
    scene.mesh.clear()
    scene.groups.clear()
    pts = [V(math.cos(2 * math.pi * k / 24), math.sin(2 * math.pi * k / 24), 0)
           for k in range(24)]
    CircleTool()._commit(viewport, pts)
    disc = scene.mesh.faces[0]
    T._push(scene, disc, 2.0 if disc.normal().z() > 0 else -2.0)
    viewport.history.execute(MakeGroupCommand(list(scene.mesh.faces),
                                              list(scene.mesh.edges)))
    (cyl,) = scene.groups
    cutter = _box(0.5, -0.3, 0.5, 3, 0.3, 1.5, BLUE)
    scene.groups.append(cutter)
    cmd = solids.SolidOperationCommand(solids.SUBTRACT, [cutter, cyl])
    cmd.prepare()
    viewport.history.execute(cmd)
    (res,) = cmd.created
    for z in (0.0, 2.0):
        ((cid, n),) = _rim_curves(res.mesh, z)
        assert cid is not None and n == 24
    viewport.history.undo()
    viewport.history.redo()
    for z in (0.0, 2.0):
        ((cid, n),) = _rim_curves(res.mesh, z)
        assert cid is not None and n == 24


def _cylinder_group(viewport):
    scene = viewport.scene
    scene.mesh.clear()
    scene.groups.clear()
    pts = [V(math.cos(2 * math.pi * k / 24), math.sin(2 * math.pi * k / 24), 0)
           for k in range(24)]
    CircleTool()._commit(viewport, pts)
    disc = scene.mesh.faces[0]
    T._push(scene, disc, 2.0 if disc.normal().z() > 0 else -2.0)
    viewport.history.execute(MakeGroupCommand(list(scene.mesh.faces),
                                              list(scene.mesh.edges)))
    return scene.groups[0]


def test_a_copied_cylinder_keeps_its_circles(viewport):
    """Copying a cylinder group re-split its curves, and a rim's every
    vertex has a side seam on it: the copy's circles came out as 24 curves
    of one segment each, and a Subtract on the copy kept them broken."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group, transformed_mesh
    cyl = _cylinder_group(viewport)
    m = QMatrix4x4()
    m.translate(5, 0, 0)
    copy = Group(transformed_mesh(cyl.mesh, m), name="copy")
    for z in (0.0, 2.0):
        sizes = {}
        for e in copy.mesh.edges:
            if abs(e.a.z() - z) < 1e-6 and abs(e.b.z() - z) < 1e-6:
                sizes[e.curve] = sizes.get(e.curve, 0) + 1
        assert list(sizes.values()) == [24] and None not in sizes
    cutter = _box(5.5, -0.3, 0.5, 8, 0.3, 1.5, BLUE)
    _gone, (res,) = solids.run(solids.SUBTRACT, [cutter, copy])
    for z in (0.0, 2.0):
        sizes = {}
        for e in res.mesh.edges:
            if abs(e.a.z() - z) < 1e-6 and abs(e.b.z() - z) < 1e-6:
                sizes[e.curve] = sizes.get(e.curve, 0) + 1
        assert list(sizes.values()) == [24] and None not in sizes


def test_an_exploded_cylinder_keeps_its_circles(viewport):
    from core.history import ExplodeGroupCommand
    cyl = _cylinder_group(viewport)
    viewport.history.execute(ExplodeGroupCommand(cyl))
    mesh = viewport.scene.mesh
    for z in (0.0, 2.0):
        ((cid, n),) = _rim_curves(mesh, z)
        assert cid is not None and n == 24
