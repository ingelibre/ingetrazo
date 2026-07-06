# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Face.area() — the discriminator pick_face uses to choose the inner face
when coplanar faces overlap under the cursor.

When a small rectangle is drawn on a bigger face that didn't subdivide it, both
faces are hit by the cursor ray at the same depth. pick_face picks the smaller
one (the rectangle the user is pointing at) instead of the big face behind it.
This covers the area computation that decision relies on.

Headless: ``QVector3D`` value types only.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.geometry import Face


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def test_area_axis_aligned_rectangle():
    wall = Face([V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)])  # 4 × 3 vertical
    assert wall.area() == 12.0


def test_area_triangle():
    tri = Face([V(0, 0, 0), V(2, 0, 0), V(0, 0, 2)])
    assert tri.area() == 2.0


def test_area_independent_of_winding():
    cw = Face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    ccw = Face([V(0, 0, 0), V(0, 2, 0), V(2, 2, 0), V(2, 0, 0)])
    assert cw.area() == ccw.area() == 4.0


def test_degenerate_face_has_zero_area():
    assert Face([V(0, 0, 0), V(1, 0, 0)]).area() == 0.0
    assert Face([]).area() == 0.0


def test_inner_face_is_smaller_than_mother():
    # The exact scenario behind the pick: a door drawn on a wall.
    wall = Face([V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)])
    door = Face([V(1, 0, 0), V(2, 0, 0), V(2, 0, 2), V(1, 0, 2)])
    assert door.area() < wall.area()
    assert min([wall, door], key=lambda f: f.area()) is door
