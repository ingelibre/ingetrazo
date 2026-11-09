# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Zooming back out after a deep zoom-in restores the depth precision (#579).

@jonson7777 and @ncamaa: after zooming into a corner, zooming out left lines
and faces centimetres apart flickering through each other. The retreat that
unsticks the close-up pushed the TARGET back and left the orbit distance at
2 cm with the eye tens of metres away — and the near plane is derived from
that distance (0.4 mm: a depth step of ~0.4 m at 50 m). The distance grows
now; the eye ends up exactly where it did."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.camera import OrbitCamera


def _deep_zoom_then_out(cam: OrbitCamera, notches: int):
    focus = V(3.0, 2.0, 0.5)
    cam.target = V(focus)
    cam.distance = cam.min_distance(focus)          # pinned at the floor
    eyes = []
    for _ in range(notches):
        cam.zoom_to(-1, focus, min_step=0.5)        # ~1 % of a 50 m model
        eyes.append(cam.eye())
    return focus, eyes


def test_the_distance_follows_the_eye_back_out():
    cam = OrbitCamera()
    focus, _eyes = _deep_zoom_then_out(cam, 30)
    eye_gap = (cam.eye() - focus).length()
    assert eye_gap > 10.0
    # The distance is how far the camera is from what it looks at…
    assert abs(cam.distance - (cam.eye() - cam.target).length()) < 1e-6
    assert (cam.target - focus).length() < 1e-6     # …still the model
    assert cam.distance > 0.9 * eye_gap
    # …so the near plane is back at its working value.
    assert cam.near_plane() == cam.znear


def test_the_eye_backs_off_by_the_same_steps_as_before():
    """The picture does not change: only what the distance means."""
    cam = OrbitCamera()
    focus, eyes = _deep_zoom_then_out(cam, 5)
    for i, e in enumerate(eyes, start=1):
        assert (e - focus).length() >= 0.5 * i - 1e-6
