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
    cam = OrbitCamera()
    cam.distance = 0.6
    cam.zoom_to(5.0, QVector3D(0, 0, 0))   # would go below the 0.5 floor
    assert cam.distance >= 0.5
