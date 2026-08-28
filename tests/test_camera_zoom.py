# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Zoom-to-cursor: keep the world point under the pointer fixed on screen."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera


def test_zoom_to_keeps_focus_under_cursor():
    cam = OrbitCamera()
    focus = QVector3D(3, 2, 0)
    eye0 = cam.eye()
    dist0 = cam.distance

    cam.zoom_to(1.0, focus)   # one step in

    factor = cam.distance / dist0
    assert factor < 1.0                                  # zoomed in
    v0 = eye0 - focus
    v1 = cam.eye() - focus
    # The eye→focus vector only scales (same direction) — so ``focus`` stays in
    # the same screen direction from the camera: under the cursor.
    assert abs(v1.length() / v0.length() - factor) < 1e-5
    assert QVector3D.dotProduct(v0.normalized(), v1.normalized()) > 0.99999


def test_zoom_to_respects_distance_clamp():
    from core.camera import MIN_DISTANCE
    cam = OrbitCamera()
    cam.distance = MIN_DISTANCE * 1.2
    cam.zoom_to(5.0, QVector3D(0, 0, 0))   # would go through the floor
    assert cam.distance >= MIN_DISTANCE


def test_you_can_get_close_enough_to_look_at_a_component():
    # A library component is centimetres. The old half-metre floor meant a
    # figure's face or a wheel rim could not be looked at at all: the wheel
    # stopped turning while the model was still small on screen.
    from core.camera import MIN_DISTANCE
    cam = OrbitCamera()
    cam.distance = 2.0
    for _ in range(200):
        cam.zoom(1.0)
    assert cam.distance <= 0.1, "the wheel still hits a wall"
    assert cam.distance >= MIN_DISTANCE


def test_the_near_plane_gets_out_of_the_way_when_you_come_close():
    # Lifting the floor is no use if the near plane clips what you came to
    # see; it has to follow the camera in. Far away it must not move at all.
    from PySide6.QtGui import QMatrix4x4
    cam = OrbitCamera()
    cam.distance = 20.0
    unchanged = QMatrix4x4()
    unchanged.perspective(cam.fov_deg, cam.aspect, 0.1, cam.zfar)
    got = cam.projection_matrix()
    for i in range(4):
        for j in range(4):
            assert abs(got(i, j) - unchanged(i, j)) < 1e-9, \
                "the near plane moved at a normal working distance"
    cam.distance = 0.05
    close = cam.projection_matrix()
    # A point 2 cm ahead of the eye must be inside the frustum.
    p = cam.eye() + (cam.target - cam.eye()).normalized() * 0.02
    clip = (close * cam.view_matrix()).map(p)
    assert clip.z() > -1.0
