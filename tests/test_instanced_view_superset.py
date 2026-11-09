# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What the instanced pass leaves out of a camera frame (#158, «sin lag»).

Two things, both measured on the plant of #158: placements whose bounding
sphere comes out under a pixel are not drawn (70 % of the instanced faces
from the whole-model view, 14 pixels of 1.4 million changed); and the
batches drawn are a superset of the view — the frustum widened, the pixel
floor halved — kept while the view stays inside them, so an orbit replays
the recorded pass instead of re-recording 3 800 prototypes a frame
(66 → 6 ms of Python close to the plant)."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh


def _box_mesh(s):
    m = Mesh()
    m.add_face([V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0)])
    return m


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(800, 600)
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _place(vp, mesh, x, y, z=0.0):
    g = Group(mesh, name=f"P{len(vp.scene.groups)}")
    m = QMatrix4x4()
    m.translate(x, y, z)
    g.xform = m
    vp.scene.groups.append(g)
    return g


def _look(vp, distance):
    cam = vp.camera
    cam.perspective = True
    cam.target = V(0, 0, 0)
    cam.distance, cam.yaw, cam.pitch = distance, 0.3, 0.4
    vp._frame_planes = vp._frustum_planes(
        cam.projection_matrix() * cam.view_matrix())


def _drawn(vp):
    return {id(g) for _m, _p, batch, _mir in vp._gather_instanced().values()
            for g in batch}


def test_a_sphere_under_a_pixel_is_small_and_one_over_it_is_not():
    win = _window()
    try:
        vp = win.viewport
        _look(vp, 50.0)
        h = vp._fb_size()[1]
        eye = vp.camera.eye()
        fwd = vp.camera.forward()
        sy = abs(vp.camera.projection_matrix().data()[5]) * h * 0.5
        depth = 40.0
        c = eye + fwd * depth
        # radius whose sphere spans exactly 1 px at its nearest point
        r1 = depth / (2.0 * sy + 1.0)
        ctr = np.array([[c.x(), c.y(), c.z()]] * 3)
        rad = np.array([r1 * 0.9, r1 * 1.1, np.inf])
        small = vp._spheres_below_a_pixel(ctr, rad, 1.0)
        assert small.tolist() == [True, False, False]
    finally:
        _close(win)


def test_a_box_reaching_behind_the_eye_is_never_small():
    win = _window()
    try:
        vp = win.viewport
        _look(vp, 30.0)
        e = vp.camera.eye()
        ctr = np.array([[e.x(), e.y(), e.z()]])
        assert not vp._spheres_below_a_pixel(ctr, np.array([1e-4]), 1.0)[0]
    finally:
        _close(win)


def test_far_tiny_placements_drop_out_and_near_ones_stay():
    win = _window()
    try:
        vp = win.viewport
        _look(vp, 5.0)
        eye, fwd = vp.camera.eye(), vp.camera.forward()
        near = _place(vp, _box_mesh(0.2), 0.0, 0.0)
        tiny = _box_mesh(0.01)
        far = []
        for i in range(3):
            p = eye + fwd * (300.0 + 20.0 * i)
            far.append(_place(vp, tiny, p.x(), p.y(), p.z()))
        vp.scene.version += 1
        assert all(vp._aabb_visible(vp._frame_planes, *vp._placement_bbox(g))
                   for g in far + [near])
        vp._INST_MIN_PX = 0.0
        all_in = _drawn(vp)
        vp._INST_MIN_PX = 1.0
        vp._inst_frame_memo = {}
        culled = _drawn(vp)
        assert {id(g) for g in far + [near]} <= all_in
        assert id(near) in culled
        assert not any(id(g) in culled for g in far)
    finally:
        _close(win)


def test_widened_planes_hold_the_view_and_more():
    win = _window()
    try:
        vp = win.viewport
        _look(vp, 20.0)
        planes = vp._frame_planes
        wide = vp._widened_planes(planes, 0.25)
        rng = np.random.default_rng(3)
        pts = rng.uniform(-60, 60, size=(4000, 3))

        def inside(pls, p):
            return all(pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2] + pl[3]
                       >= 0.0 for pl in pls)
        inn = [inside(planes, p) for p in pts]
        win_ = [inside(wide, p) for p in pts]
        assert any(inn)
        assert all(w for i, w in zip(inn, win_) if i)     # a superset
        assert sum(win_) > sum(inn)                       # and wider
    finally:
        _close(win)


def test_an_orbit_step_keeps_the_batches_while_the_view_stays_inside():
    win = _window()
    try:
        vp = win.viewport
        m = _box_mesh(1.0)
        mine = [_place(vp, m, i * 4.0 - 24.0, j * 4.0 - 24.0)
                for i in range(12) for j in range(12)]
        vp.scene.version += 1
        _look(vp, 30.0)
        first = vp._gather_instanced()
        drawn = _drawn(vp)
        # a small turn: what is in view now is still inside what is drawn
        vp.camera.yaw += math.radians(1.0)
        vp._frame_planes = vp._frustum_planes(
            vp.camera.projection_matrix() * vp.camera.view_matrix())
        assert vp._gather_instanced() is first
        exact = {id(g) for g in mine
                 if vp._aabb_visible(vp._frame_planes,
                                     *vp._placement_bbox(g))}
        assert exact <= drawn
        # a half turn leaves it: new batches, again holding the view
        vp.camera.yaw += math.pi
        vp._frame_planes = vp._frustum_planes(
            vp.camera.projection_matrix() * vp.camera.view_matrix())
        second = vp._gather_instanced()
        exact = {id(g) for g in mine
                 if vp._aabb_visible(vp._frame_planes,
                                     *vp._placement_bbox(g))}
        assert exact <= _drawn(vp)
        assert second is not first or exact <= drawn
    finally:
        _close(win)
