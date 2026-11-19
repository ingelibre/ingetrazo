# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Daniel Campos Ramos and IngeTrazo contributors.
"""One eye of a stereo pair (``OrbitCamera.eye_camera``), against a closed form.

Each case projects a few thousand points with the two eyes' own matrices and
compares their horizontal disparity with pinhole and shear geometry worked out
without matrices; the vertical disparity must be zero, the orbit target at
screen depth, and a camera with no offset exactly the ordinary view.
"""
import math
import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D, QVector4D

from core.camera import OrbitCamera

W, H = 1920, 1080
#: QMatrix4x4 computes in float32: a thousandth of a pixel is its noise here.
TOL = 1e-3
#: Interaxial over the distance to the zero-parallax plane (the 1/30 rule).
RATIO = 1.0 / 30.0
MODES = ("perspective", "two_point", "parallel")


def project(cam, p):
    clip = (cam.projection_matrix() * cam.view_matrix()).map(
        QVector4D(p.x(), p.y(), p.z(), 1.0))
    if clip.w() <= 1e-12:
        return None
    return ((clip.x() / clip.w() * 0.5 + 0.5) * W,
            (1.0 - (clip.y() / clip.w() * 0.5 + 0.5)) * H)


def base_camera(mode, yaw, pitch, distance=20.0):
    cam = OrbitCamera()
    cam.target = QVector3D(3.0, -2.0, 1.5)
    cam.distance = distance
    cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)
    cam.set_projection(mode)
    cam.set_aspect(W, H)
    return cam


def pair(cam):
    separation = cam.target_depth() * RATIO
    return (cam.eye_camera(-separation / 2.0), cam.eye_camera(separation / 2.0),
            separation)


def sight(cam):
    level = cam._level_forward()
    return level if level is not None else cam.forward()


def predicted_px(cam, p):
    """Right eye minus left eye, in pixels of an eye ``W`` wide, from the
    geometry alone: positive behind the screen, negative in front of it."""
    c = cam.target_depth()
    e = c * RATIO
    z = QVector3D.dotProduct(p - cam.eye(), sight(cam))
    tan = math.tan(math.radians(cam.fov_deg) / 2.0)
    if not cam.perspective:
        return (e * (z - c) / c) / (2.0 * cam.distance * tan * cam.aspect) * W
    return (e * (1.0 - c / z)) / (2.0 * c * tan * cam.aspect) * W


def visible_points(cam, n, rng):
    """Points inside the ordinary view, from 0.3 to 3 times the target's depth."""
    s = sight(cam)
    to_target = (cam.target - cam.eye()).normalized()
    r = QVector3D.crossProduct(cam.forward(), cam.up_vector()).normalized()
    u = QVector3D.crossProduct(r, to_target).normalized()
    c = cam.target_depth()
    out = []
    tries = 0
    while len(out) < n:
        tries += 1
        assert tries < 50 * n, "the generator finds no visible points"
        z = c * rng.uniform(0.3, 3.0)
        along = z / max(QVector3D.dotProduct(to_target, s), 1e-9)
        span = 0.35 * (z if cam.perspective else c)
        p = cam.eye() + to_target * along + r * (rng.uniform(-1, 1) * span * cam.aspect) \
            + u * (rng.uniform(-1, 1) * span)
        q = project(cam, p)
        if q is not None and 0 <= q[0] <= W and 0 <= q[1] <= H:
            out.append(p)
    return out


@pytest.mark.parametrize("mode,yaw,pitch", [
    (mode, yaw, pitch) for mode in MODES
    for yaw, pitch in ((-45, 30), (10, 5), (120, -20), (-90, 60))])
def test_disparity_matches_the_closed_form(mode, yaw, pitch):
    rng = random.Random(296)
    cam = base_camera(mode, yaw, pitch)
    left, right, _ = pair(cam)
    worst_h = worst_v = 0.0
    near_crossed = far_uncrossed = 0
    for p in visible_points(cam, 3000, rng):
        a, b = project(left, p), project(right, p)
        measured = b[0] - a[0]
        worst_h = max(worst_h, abs(measured - predicted_px(cam, p)))
        worst_v = max(worst_v, abs(b[1] - a[1]))
        depth = QVector3D.dotProduct(p - cam.eye(), sight(cam))
        if depth < cam.target_depth() * 0.99:
            near_crossed += measured < 0
        elif depth > cam.target_depth() * 1.01:
            far_uncrossed += measured > 0
    assert worst_h < TOL
    assert worst_v < TOL
    assert near_crossed > 100 and far_uncrossed > 100


@pytest.mark.parametrize("mode", MODES)
def test_the_target_stays_at_screen_depth(mode):
    cam = base_camera(mode, -45, 30)
    left, right, _ = pair(cam)
    a, b, mono = project(left, cam.target), project(right, cam.target), project(cam, cam.target)
    assert abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL
    assert abs(a[0] - mono[0]) < TOL and abs(a[1] - mono[1]) < TOL


@pytest.mark.parametrize("mode", MODES)
def test_no_offset_is_the_ordinary_view(mode):
    cam = base_camera(mode, 30, 20)
    eye = cam.eye_camera(0.0)
    a = (eye.projection_matrix() * eye.view_matrix()).data()
    b = (cam.projection_matrix() * cam.view_matrix()).data()
    assert max(abs(x - y) for x, y in zip(a, b)) < 1e-6


@pytest.mark.parametrize("mode", MODES)
def test_the_camera_it_came_from_is_left_alone(mode):
    cam = base_camera(mode, -45, 30)
    before = (cam.projection_matrix() * cam.view_matrix()).data()
    left, _right, _ = pair(cam)
    left.target.setX(99.0)
    left.up.setX(0.5)
    assert (cam.projection_matrix() * cam.view_matrix()).data() == before
    assert cam.eye_offset == 0.0 and cam.zero_parallax == 0.0


def test_parallel_axes_and_eye_positions():
    cam = base_camera("perspective", -45, 30)
    left, right, sep = pair(cam)
    assert (right.eye() - left.eye()).length() == pytest.approx(sep, rel=1e-5)
    assert QVector3D.dotProduct(left.forward(), right.forward()) == pytest.approx(1.0, abs=1e-6)
    baseline = right.eye() - left.eye()
    assert QVector3D.dotProduct(baseline, cam.forward()) == pytest.approx(0.0, abs=1e-4)


def test_the_top_view_has_no_vertical_disparity():
    cam = base_camera("perspective", 0, 0)
    cam.set_view("top")
    left, right, _ = pair(cam)
    for p in visible_points(cam, 500, random.Random(7)):
        a, b = project(left, p), project(right, p)
        assert abs(a[1] - b[1]) < TOL
        assert abs((b[0] - a[0]) - predicted_px(cam, p)) < TOL


def test_a_parallel_eye_keeps_the_fitted_depth_range():
    """#874: a parallel view's depth range fits what it holds, and so must
    each eye's, or lines and surfaces trade places in a zigzag again."""
    cam = base_camera("parallel", -45, 30)
    cam.depth_reach = (QVector3D(cam.target), 5.0)
    assert cam.parallel_depth() < cam.far_plane()
    left, _right, _ = pair(cam)
    depth = lambda c, z: c.projection_matrix().map(QVector4D(0.0, 0.0, z, 1.0)).z()
    assert depth(left, -3.0) == pytest.approx(depth(cam, -3.0), rel=1e-5)
