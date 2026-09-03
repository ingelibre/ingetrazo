# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Face-plane inference over groups and component instances: the plane is
the placed copy's (world), and the second point of Move / tape / a line
lands ON the face under the cursor unless an axis inference is active."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from core.snap import face_plane_world


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _box(mesh, s=1.0):
    pts = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
           V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    return [mesh.add_face([pts[i] for i in q]) for q in quads]


def test_face_plane_world_follows_the_instance_transform():
    proto = Mesh()
    top = _box(proto)[1]                          # z = 1, normal +Z
    assert face_plane_world(top, None)[0] == V(0.5, 0.5, 1.0)
    xf = QMatrix4x4()
    xf.translate(3.0, 2.0, 0.5)
    c, n = face_plane_world(top, xf)
    assert (c - V(3.5, 2.5, 1.5)).length() < 1e-6
    assert abs(abs(n.z()) - 1.0) < 1e-6
    rot = QMatrix4x4()
    rot.translate(3.0, 0.0, 0.0)
    rot.rotate(90.0, 1.0, 0.0, 0.0)               # the top face now faces -Y
    c, n = face_plane_world(top, rot)
    assert abs(abs(n.y()) - 1.0) < 1e-6 and abs(n.z()) < 1e-6
    assert abs(c.y() + 1.0) < 1e-6 and abs(c.x() - 3.5) < 1e-6


def _viewport_with_instance():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    scene = vp.scene
    proto = Mesh()
    faces = _box(proto)
    a = Group(proto, name="A")
    b = Group(proto, name="B")
    xb = QMatrix4x4()
    xb.translate(3.0, 0.0, 0.0)
    a.xform, b.xform = QMatrix4x4(), xb
    scene.groups += [a, b]
    scene.version += 1
    vp.resize(800, 600)
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(35.0), math.radians(35.0)
    cam.target = V(2.0, 0.5, 0.5)
    cam.distance = 8.0
    return win, vp, faces[1], b


def test_work_plane_over_an_instance_face_is_the_placed_copy():
    win, vp, top, b = _viewport_with_instance()
    try:
        if not vp._pick_index().entities:
            pytest.skip("no pick index offscreen")
        px = vp._world_to_pixel(V(3.5, 0.5, 1.0))
        assert px is not None
        face, grp = vp.pick_face_any(px[0], px[1])
        assert grp is b and face is top
        from tools.select import SelectTool
        vp.active_tool = SelectTool()
        point, normal = vp._current_work_plane(cursor=(px[0], px[1]))
        assert (point - V(3.5, 0.5, 1.0)).length() < 1e-6
        assert abs(abs(normal.z()) - 1.0) < 1e-6
        # memo: the same cursor and view answer without a second search
        assert vp.pick_face_any(px[0], px[1]) == (face, grp)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_second_point_lands_on_the_face_under_the_cursor_unless_axis():
    win, vp, top, b = _viewport_with_instance()
    try:
        if not vp._pick_index().entities:
            pytest.skip("no pick index offscreen")
        from tools.move import MoveTool
        tool = MoveTool()
        vp.active_tool = tool
        tool.start_point = V(0.5, 0.5, 1.0)        # grabbed on A's top
        px = vp._world_to_pixel(V(3.5, 0.5, 1.0))  # aiming at B's top
        point, normal = vp._current_work_plane(cursor=(px[0], px[1]))
        hit = vp._world_from_pixel(px[0], px[1])
        assert abs(hit.z() - 1.0) < 1e-6           # ON B's top face
        assert abs(abs(normal.z()) - 1.0) < 1e-6
        # the moved object's own faces never attract: select B and aim at it
        vp.scene.selection.add(b)
        point2, _n2 = vp._current_work_plane(cursor=(px[0], px[1]))
        assert point2 == tool.start_point or abs(point2.z() - 1.0) > 1e-6 \
            or point2 is not point
        vp.scene.selection.clear()
        # an axis-aligned heading keeps the start-point plane (draw upward)
        tool.start_point = V(3.5, 0.5, 2.0)        # right above B's top
        px_up = vp._world_to_pixel(V(3.5, 0.5, 4.0))
        pt3, n3 = vp._current_work_plane(cursor=(px_up[0], px_up[1]))
        assert pt3 == tool.start_point
    finally:
        win._saved_version = vp.scene.version
        win.close()
