# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Groups: isolate geometry into its own mesh so it doesn't weld to the rest."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import (
    ExplodeGroupCommand,
    History,
    MakeGroupCommand,
    MoveGroupCommand,
)
from core.scene import Scene


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _two_squares():
    scene = Scene()
    hist = History(scene)
    a = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    scene.mesh.add_face([V(5, 0), V(7, 0), V(7, 2), V(5, 2)])
    return scene, hist, a


def test_make_group_moves_geometry_off_the_loose_mesh():
    scene, hist, a = _two_squares()
    hist.execute(MakeGroupCommand([a], []))
    assert len(scene.groups) == 1
    assert len(scene.mesh.faces) == 1           # only the other square stays loose
    assert len(scene.groups[0].mesh.faces) == 1
    assert scene.groups[0] in scene.selection   # the group is selected
    assert hist.undo() is True
    assert len(scene.groups) == 0
    assert len(scene.mesh.faces) == 2


def test_moving_a_group_does_not_drag_loose_geometry():
    scene, hist, a = _two_squares()
    hist.execute(MakeGroupCommand([a], []))
    g = scene.groups[0]
    loose_x_before = sorted({round(v.position.x()) for v in scene.mesh.vertices})

    hist.execute(MoveGroupCommand(g, V(10, 0, 0)))
    group_x = sorted({round(v.position.x()) for v in g.mesh.vertices})
    loose_x = sorted({round(v.position.x()) for v in scene.mesh.vertices})
    assert group_x == [10, 12]                  # the group moved
    assert loose_x == loose_x_before            # the loose square did not

    assert hist.undo() is True
    assert sorted({round(v.position.x()) for v in g.mesh.vertices}) == [0, 2]


def test_explode_merges_group_back_into_loose_mesh():
    scene, hist, a = _two_squares()
    hist.execute(MakeGroupCommand([a], []))
    g = scene.groups[0]
    hist.execute(ExplodeGroupCommand(g))
    assert len(scene.groups) == 0
    assert len(scene.mesh.faces) == 2           # back among the loose geometry
    assert hist.undo() is True
    assert len(scene.groups) == 1
