# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #1693 (@moominot): a new group gets no origin of its own.

A 1x1 m face whose lowest corner is (10, 20, 0), grouped at the top level,
kept the drawing's origin (0, 0, 0) — and moving it 2 m along X moved that
borrowed origin to (2, 0, 0). Make Component already put its origin at the
lowest corner (10, 20, 0), moving to (12, 20, 0). A top-level group now
gets the same origin: the selection's lowest corner, as a pure translation
frame. The mesh stays in world coordinates; only the frame moves. Groups
already in a document keep the origin they were saved with.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.group import frame_axes, group_frame
from core.history import History, MakeGroupCommand, MoveGroupCommand
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _close(a, b, tol=1e-5):
    return (a - b).length() < tol


def _scene_with_face(x0=10.0, y0=20.0):
    scene = Scene()
    scene.mesh.add_face([V(x0, y0), V(x0 + 1, y0),
                         V(x0 + 1, y0 + 1), V(x0, y0 + 1)])
    return scene


def _origin(g):
    return frame_axes(group_frame(g))[0]


def test_top_level_group_origin_is_the_lowest_corner():
    scene = _scene_with_face()
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    g = scene.groups[-1]
    assert g.xform is None  # a plain group, not an instance
    assert _close(_origin(g), V(10, 20, 0))
    # The mesh itself stays in world coordinates.
    assert min(v.position.x() for v in g.mesh.vertices) == 10.0
    assert min(v.position.y() for v in g.mesh.vertices) == 20.0


def test_moving_the_group_moves_its_origin_with_it():
    scene = _scene_with_face()
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    g = scene.groups[-1]
    hist.execute(MoveGroupCommand(g, V(2, 0, 0)))
    assert _close(_origin(g), V(12, 20, 0))
    hist.undo()
    assert _close(_origin(g), V(10, 20, 0))
    hist.redo()
    assert _close(_origin(g), V(12, 20, 0))


def test_make_component_origin_is_unchanged():
    scene = _scene_with_face()
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges), component=True))
    c = scene.groups[-1]
    assert _close(_origin(c), V(10, 20, 0))
