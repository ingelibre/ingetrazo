# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Panning a two-point perspective slides the picture across the frame,
like a drafting canvas: the eye, the target and the perspective stay as
they are (José Castro Basso, FADU–UDELAR). An ordinary pan still moves
the camera."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D, QVector4D

from core.camera import MAX_SHIFT, OrbitCamera

W, H = 1600, 900


def _screen(cam, p):
    q = (cam.projection_matrix() * cam.view_matrix()).map(
        QVector4D(p.x(), p.y(), p.z(), 1.0))
    return q.x() / q.w(), q.y() / q.w()


def _cam(two_point=True):
    cam = OrbitCamera()
    cam.set_aspect(W, H)
    cam.target = QVector3D(2.0, 3.0, 1.5)
    cam.yaw = math.radians(-35.0)
    cam.pitch = math.radians(20.0)
    cam.distance = 25.0
    if two_point:
        cam.toggle_two_point()
    return cam


def _pose(cam):
    e = cam.eye()
    t = cam.target
    return ((e.x(), e.y(), e.z()), (t.x(), t.y(), t.z()), cam.yaw,
            cam.pitch, cam.distance, cam.fov_deg, cam.perspective)


def test_a_two_point_pan_leaves_the_camera_where_it_is():
    cam = _cam()
    before = _pose(cam)
    cam.pan(120.0, -40.0, H)
    assert _pose(cam) == before


def test_a_two_point_pan_moves_the_picture_with_the_drag():
    cam = _cam()
    p = QVector3D(8.0, -4.0, 2.0)
    x0, y0 = _screen(cam, p)
    cam.pan(160.0, 90.0, H)             # right and down, in pixels
    x1, y1 = _screen(cam, p)
    # 160 of 1600 px is a tenth of the width: 0.2 in clip space; 90 px
    # down of 900 is 0.2 down.
    assert x1 - x0 == pytest.approx(0.2, abs=1e-4)
    assert y1 - y0 == pytest.approx(-0.2, abs=1e-4)


def test_the_perspective_is_the_same_after_a_two_point_pan():
    """The whole picture moves as one: every point by the same offset, so
    nothing in it changes shape, and verticals stay vertical."""
    cam = _cam()
    pts = [QVector3D(8.0, -4.0, 0.0), QVector3D(8.0, -4.0, 9.0),
           QVector3D(-3.0, 6.0, 0.5), QVector3D(0.0, 0.0, 4.0)]
    before = [_screen(cam, p) for p in pts]
    cam.pan(-230.0, 75.0, H)
    after = [_screen(cam, p) for p in pts]
    dx = after[0][0] - before[0][0]
    dy = after[0][1] - before[0][1]
    assert abs(dx) > 1e-3 and abs(dy) > 1e-3
    for (bx, by), (ax, ay) in zip(before, after):
        assert ax - bx == pytest.approx(dx, abs=1e-4)
        assert ay - by == pytest.approx(dy, abs=1e-4)
    assert after[0][0] == pytest.approx(after[1][0], abs=1e-5)  # vertical


def test_an_ordinary_pan_still_moves_the_camera():
    for perspective in (True, False):
        cam = _cam(two_point=False)
        cam.perspective = perspective
        target = QVector3D(cam.target)
        cam.pan(120.0, -40.0, H)
        assert (cam.target - target).length() > 1e-3
        assert cam.pan_shift_x == 0.0 and cam.pan_shift_y == 0.0


def test_a_steep_two_point_view_pans_as_an_ordinary_one():
    """Looking nearly straight down, two-point falls back to an ordinary
    perspective: its pan moves the camera as before."""
    cam = _cam()
    cam.pitch = math.radians(85.0)
    target = QVector3D(cam.target)
    cam.pan(120.0, -40.0, H)
    assert (cam.target - target).length() > 1e-3
    assert cam.pan_shift_x == 0.0 and cam.pan_shift_y == 0.0


def test_the_slide_stops_at_the_lens_shift_limit():
    cam = _cam()
    cam.pan(-50 * W, 50 * H, H)
    assert cam.pan_shift_x == pytest.approx(MAX_SHIFT)
    assert cam.pan_shift_y == pytest.approx(MAX_SHIFT)


def test_a_scene_keeps_the_slide_and_an_ordinary_lens_takes_it_off():
    cam = _cam()
    cam.pan(160.0, 90.0, H)
    lens = cam.lens_dict()
    assert lens["pan_shift_x"] == pytest.approx(-0.1)
    assert lens["pan_shift_y"] == pytest.approx(0.1)
    other = _cam()
    other.apply_lens(lens)
    assert (other.projection_matrix() * other.view_matrix()
            == cam.projection_matrix() * cam.view_matrix())
    other.apply_lens({})
    assert other.pan_shift_x == 0.0 and other.pan_shift_y == 0.0


def test_a_lens_setting_typed_in_the_camera_window_keeps_the_slide():
    """Camera settings rebuild the lens from their boxes: the slide, which
    has no box, must come along, or a typed roll put the picture back."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        cam = win.viewport.camera
        cam.set_projection("perspective")
        cam.two_point = True
        cam.pan_shift_x, cam.pan_shift_y = -0.25, 0.1
        win._show_camera_settings()
        dlg = win._camera_settings
        dlg.shift_y.setValue(20.0)
        assert cam.shift_y == pytest.approx(0.2)
        assert cam.pan_shift_x == pytest.approx(-0.25)
        assert cam.pan_shift_y == pytest.approx(0.1)
        dlg.reset.click()                       # Reset Lens takes it off
        assert cam.pan_shift_x == 0.0 and cam.pan_shift_y == 0.0
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
