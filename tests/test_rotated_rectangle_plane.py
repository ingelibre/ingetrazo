# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rotated Rectangle draws in a PLANE, which is the point of the tool.

Marco, 2026-09-10, after reading how SketchUp's works: «sospecho que no es
igual». It was not. `work_plane` was declared, reset and read — and never
assigned — so `_perp` always fell back to world +Z:

* on a wall the width shot off the wall horizontally,
* a vertical base edge made cross(Z, Z) zero, and the tool then did nothing
  at all without a word,
* and the class was `RotatedRectangleTool(Tool)` while Rectangle, Circle,
  Polygon and every arc are `(PlaneLock, Tool)` — the arrow keys never even
  reached it.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.mesh import Mesh
from tools.base import PLANE_LOCK_KEYS, PlaneLock, ToolContext
from tools.rotated_rectangle import RotatedRectangleTool

WALL_N = QVector3D(0.0, 1.0, 0.0)      # a wall in the XZ plane


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _VP:
    """Just enough viewport: a face under the cursor, and a loud status bar."""

    def __init__(self, face=None):
        self.face = face
        self.said = []

    def pick_face_any(self, x, y):
        return (self.face, None)

    def flash_status(self, text, msec=2500):
        self.said.append(text)

    def update(self):
        pass


def _ctx(vp, world):
    return ToolContext(viewport=vp, world=world, screen=QPointF(0.0, 0.0),
                       modifiers=Qt.NoModifier, snap=None)


def _wall_face():
    mesh = Mesh()
    return mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)])


def _off_plane(corners, origin, normal):
    n = normal.normalized()
    return [round(QVector3D.dotProduct(p - origin, n), 6) for p in corners]


def test_it_is_a_plane_locking_tool_like_every_other_planar_one():
    assert issubclass(RotatedRectangleTool, PlaneLock)
    assert hasattr(RotatedRectangleTool, "on_key")


def test_the_arrow_keys_reach_it():
    tool = RotatedRectangleTool()
    vp = _VP()
    key = next(k for k, axis in PLANE_LOCK_KEYS.items() if axis == "y")
    assert tool.on_key(vp, key, None) is True
    assert tool.plane_lock == "y"
    tool._reset()
    assert tool.plane_lock is None, "the lock must not outlive the shape"


def test_the_first_click_captures_the_face_it_landed_on():
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())
    tool.on_click(_ctx(vp, V(1, 0, 1)))
    assert tool.work_plane is not None, "the face under the click was ignored"
    _point, normal = tool.work_plane
    assert abs(abs(normal.normalized().y()) - 1.0) < 1e-6


def test_a_rectangle_on_a_wall_stays_on_the_wall():
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(3, 0, 0)))
    assert tool.base_point is not None
    corners = tool._corners(1.0)
    assert corners
    assert _off_plane(corners, V(0, 0, 0), WALL_N) == [0.0, 0.0, 0.0, 0.0]


def test_a_vertical_base_edge_works_on_a_wall():
    """cross(Z, Z) was zero and the tool went quiet; in the wall's own plane
    a vertical edge is perfectly ordinary."""
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(0, 0, 3)))
    assert tool.base_point is not None
    assert tool._corners(1.0)
    assert not vp.said


def test_an_edge_perpendicular_to_the_plane_is_refused_OUT_LOUD():
    tool = RotatedRectangleTool()
    vp = _VP(face=None)                       # no face: the ground plane
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    assert tool.work_plane is None
    tool.on_click(_ctx(vp, V(0, 0, 3)))       # straight up, off the ground
    assert tool.base_point is None, "it accepted an impossible base edge"
    assert vp.said, "it refused without a word"


def test_the_ground_case_is_unchanged():
    tool = RotatedRectangleTool()
    vp = _VP(face=None)
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(3, 0, 0)))
    corners = tool._corners(2.0)
    assert corners == [V(0, 0, 0), V(3, 0, 0), V(3, 2, 0), V(0, 2, 0)]


def test_an_arrow_lock_beats_the_face_under_the_cursor():
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())               # a wall says XZ...
    key = next(k for k, axis in PLANE_LOCK_KEYS.items() if axis == "z")
    tool.on_key(vp, key, None)                # ...but the user asked for XY
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    _point, normal = tool.work_plane
    assert abs(abs(normal.normalized().z()) - 1.0) < 1e-6
