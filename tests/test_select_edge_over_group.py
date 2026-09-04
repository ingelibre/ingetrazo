# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A loose line drawn on a group's face is selectable by clicking it: the
visible edge outranks the group behind it (SketchUp). A line hidden behind
the group does not steal the click. (Marco, 2026-09-04: 'hice una línea en
la cara de ese bloque, quiero seleccionarla y no selecciona')."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Edge, Mesh
from tools.select import SelectTool


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _box(mesh, s=1.0):
    pts = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
           V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    return [mesh.add_face([pts[i] for i in q]) for q in quads]


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    box = Group(Mesh(), name="Bloque")
    _box(box.mesh)
    vp.scene.groups.append(box)
    # a loose line lying ON the box's top face, and one hidden underneath
    on_top = vp.scene.mesh.add_edge(V(0.2, 0.5, 1.0), V(0.8, 0.5, 1.0))
    below = vp.scene.mesh.add_edge(V(0.2, 0.5, -0.3), V(0.8, 0.5, -0.3))
    vp.scene.version += 1
    vp.resize(800, 600)
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(20.0), math.radians(55.0)   # from above
    cam.target = V(0.5, 0.5, 0.5)
    cam.distance = 4.0
    return win, vp, box, on_top, below


def test_a_line_on_a_group_face_is_picked_before_the_group():
    win, vp, box, on_top, below = _window()
    try:
        if not vp._pick_index().entities:
            pytest.skip("no pick index offscreen")
        tool = SelectTool()
        px = vp._world_to_pixel(V(0.5, 0.5, 1.0))          # on the line
        assert px is not None
        assert vp.pick_group(px[0], px[1]) is box            # the group IS there
        assert tool._pick(vp, px[0], px[1]) is on_top        # …but the line wins
        px2 = vp._world_to_pixel(V(0.5, 0.15, 1.0))         # face, away from it
        assert tool._pick(vp, px2[0], px2[1]) is box
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_line_hidden_behind_the_group_does_not_steal_the_click():
    win, vp, box, on_top, below = _window()
    try:
        if not vp._pick_index().entities:
            pytest.skip("no pick index offscreen")
        vp.scene.mesh.remove_edge(on_top)
        vp.scene.version += 1
        px = vp._world_to_pixel(V(0.5, 0.5, -0.3))          # over the hidden line
        pick = SelectTool()._pick(vp, px[0], px[1])
        assert pick is box or not isinstance(pick, Edge)
        p = vp.edge_point_under_cursor(below, px[0], px[1])
        assert p is not None and vp._is_occluded(p)
    finally:
        win._saved_version = vp.scene.version
        win.close()
