# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Wheel zoom must never feel stuck: from a 2 cm close-up, zooming out
retreats perceptibly and zooming in keeps sliding toward the cursor point
(Marco, 2026-09-04: 'el zoom se traba, tengo que hacer zoom extents')."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.camera import MIN_DISTANCE, OrbitCamera as Camera


def _close_up(focus):
    cam = Camera()
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(30.0), math.radians(20.0)
    cam.target = QVector3D(focus)
    cam.distance = MIN_DISTANCE
    return cam


def test_zooming_out_from_the_minimum_distance_retreats_perceptibly():
    focus = QVector3D(3.0, 2.0, 1.0)
    cam = _close_up(focus)
    eye0 = cam.eye()
    cam.zoom_to(-1.0, focus)                        # the old behaviour: 2 mm
    naive = (cam.eye() - eye0).length()
    assert naive < 0.01
    cam = _close_up(focus)
    cam.zoom_to(-1.0, focus, min_step=0.2)
    moved = (cam.eye() - eye0).length()
    assert moved >= 0.2 - 1e-5
    # ten notches back put the eye metres away, not centimetres
    for _ in range(10):
        cam.zoom_to(-1.0, focus, min_step=0.2)
    assert (cam.eye() - focus).length() > 2.0


def test_zooming_in_at_the_minimum_keeps_sliding_toward_the_focus():
    focus = QVector3D(3.0, 2.0, 1.0)
    cam = _close_up(QVector3D(3.5, 2.0, 1.0))       # target half a metre off
    cam.zoom_to(1.0, focus)
    assert cam.distance == MIN_DISTANCE
    assert abs((cam.target - focus).length() - 0.45) < 1e-5   # 10 % closer


def test_a_normal_zoom_keeps_the_focus_fixed_and_ignores_the_floor():
    focus = QVector3D(0.0, 0.0, 0.0)
    cam = Camera()
    cam.target = QVector3D(1.0, 0.0, 0.0)
    cam.distance = 10.0
    eye0 = cam.eye()
    cam.zoom_to(1.0, focus, min_step=0.2)
    # the frame scaled by 0.9 toward the focus: eye and target alike
    assert abs(cam.distance - 9.0) < 1e-9
    assert (cam.target - focus * 0.1 - QVector3D(0.9, 0.0, 0.0)).length() < 1e-5
    assert abs((cam.eye() - focus).length() - (eye0 - focus).length() * 0.9) < 1e-6
