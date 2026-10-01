# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A snapped point off the captured plane picks the shape's plane
(found live, 2026-09-29).

Filling a window opening in a wall 0.20 m thick (Y = 0 … 0.20): first
corner on the midpoint of the right jamb's bottom depth edge, while
hovering the jamb face (plane X = 4); far corner on the midpoint of the
left jamb's top depth edge. On the jamb's plane the two share a vertical
line and the rectangle read «0.00 × 2.41 m». Both are on the wall's middle
plane (Y = 0.10), which is where the rectangle belongs.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from tools.rectangle import RectangleTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


ABAJO_DCHA = V(4.0, 0.10, 0.90)       # midpoint, right jamb, bottom
ARRIBA_IZQ = V(0.27, 0.10, 3.31)      # midpoint, left jamb, top
JAMBA = (V(4.0, 0.0, 0.0), V(-1, 0, 0))


def _tool(**lock):
    t = RectangleTool()
    t.start_point = QVector3D(ABAJO_DCHA)
    t.work_plane = (QVector3D(JAMBA[0]), QVector3D(JAMBA[1]))
    for k, v in lock.items():
        setattr(t, k, v)
    t.hover_point = QVector3D(ARRIBA_IZQ)
    return t


def test_the_opening_fills_on_the_wall_middle_plane():
    t = _tool()
    anchor, far = t._span(t.hover_point)
    du, dv = t._dimensions(anchor, far)
    assert round(abs(du), 2) == 3.73
    assert round(abs(dv), 2) == 2.41
    for c in t._corners(anchor, far):
        assert abs(c.y() - 0.10) < 1e-6


def test_a_corner_on_the_plane_keeps_the_captured_plane():
    """The free cursor lies on the captured plane: nothing changes."""
    t = _tool()
    t.hover_point = V(4.0, 0.15, 2.0)
    assert t.drawing_plane() == t.work_plane


def test_a_true_3d_diagonal_keeps_the_captured_plane():
    """No axis plane holds both corners: still refused, with the message."""
    t = _tool()
    t.hover_point = V(0.27, 0.0, 3.31)
    assert t.drawing_plane() == t.work_plane


def test_an_arrow_lock_never_yields():
    t = _tool(plane_lock="x")
    assert t.drawing_plane() == t.work_plane


# ---- The other planar shapes: same opening, same two midpoints ------------

from tools.arc import ArcTool, CenterArcTool, ThreePointArcTool
from tools.circle import CircleTool, PolygonTool


def _on_jamb(tool):
    tool.start_point = QVector3D(ABAJO_DCHA)
    tool.work_plane = (QVector3D(JAMBA[0]), QVector3D(JAMBA[1]))
    tool.hover_point = None
    return tool


def _on_wall_middle(pts):
    return all(abs(p.y() - 0.10) < 1e-6 for p in pts)


def test_a_circle_turns_to_the_snapped_rim():
    for cls in (CircleTool, PolygonTool):
        t = _on_jamb(cls())
        t.hover_point = QVector3D(ARRIBA_IZQ)
        pts = t._points(t.start_point, t.hover_point)
        assert _on_wall_middle(pts)
        assert (pts[0] - ARRIBA_IZQ).length() < 1e-6, "a vertex on the snap"


def test_a_circle_labels_the_radius_it_draws():
    """A true 3D diagonal keeps the plane and projects the rim: the label
    said the straight distance (R 4.44) over a 2.46 m circle."""
    t = _on_jamb(CircleTool())
    t.hover_point = V(0.27, 0.60, 3.31)
    pts = t._points(t.start_point, t.hover_point)
    r = (pts[0] - t.start_point).length()
    assert t.drawing_plane() == t.work_plane
    assert t.value_label()[0].startswith("R 2.46"), "√(0.5² + 2.41²)"
    assert abs(r - 2.461) < 1e-3


def test_a_two_point_arc_ends_on_the_snapped_end():
    t = _on_jamb(ArcTool())
    t.end_point = QVector3D(ARRIBA_IZQ)
    t.adopt_snapped_plane()
    assert abs(t.work_plane[1].y()) > 0.999, "the bulge is read on the wall"
    bulge = V(2.0, 0.10, 3.9)                 # free cursor, on the new plane
    t.hover_point = bulge
    pts = t._points(bulge)
    assert len(pts) > 2 and _on_wall_middle(pts)
    assert (pts[-1] - ARRIBA_IZQ).length() < 1e-6


def test_a_three_point_arc_takes_the_plane_through_its_points():
    t = _on_jamb(ThreePointArcTool())
    t.mid_point = V(2.0, 0.10, 3.9)
    t.adopt_snapped_plane()
    t.hover_point = QVector3D(ARRIBA_IZQ)
    pts = t._points(t.hover_point)
    assert _on_wall_middle(pts)
    assert (pts[-1] - ARRIBA_IZQ).length() < 1e-6


def test_a_centre_arc_swings_its_snapped_arm():
    t = _on_jamb(CenterArcTool())
    t.hover_point = QVector3D(ARRIBA_IZQ)
    assert t.value_label()[0].startswith("R 4.4")
    t.arm_point = QVector3D(ARRIBA_IZQ)
    t.adopt_snapped_plane()
    pts = t._points(90.0)
    assert _on_wall_middle(pts)
    assert (pts[0] - ARRIBA_IZQ).length() < 1e-6


def test_the_arrow_lock_holds_for_every_shape():
    for cls in (CircleTool, ArcTool, ThreePointArcTool, CenterArcTool):
        t = _on_jamb(cls())
        t.plane_lock = "x"
        t.hover_point = QVector3D(ARRIBA_IZQ)
        assert t.drawing_plane() == t.work_plane
