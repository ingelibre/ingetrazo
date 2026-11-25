# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Zooming in on a small part (#653, #692).

The camera stopped 2 cm from what it looked at, so a 10 mm part for a 3D
printer never filled the screen. Near the origin it now comes to 5 mm.
Everything else stays as it was: farther from the origin the floor rises
back to 2 cm (float32 positions tremble at a closer look there), the near
plane never comes closer than at the old floor (the depth buffer is no
coarser), and away from a close-up the wheel backs out as before."""
from __future__ import annotations

import math
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.camera import (MIN_DISTANCE, MIN_DISTANCE_FAR, NEAR_FLOOR,  # noqa: E402
                         OrbitCamera)


def _framed_part(size=0.01, at=V(0, 0, 0)):
    cam = OrbitCamera()
    cam.set_aspect(1200, 800)
    half = V(size, size, size) * 0.5
    cam.fit_box(at - half, at + half)
    return cam


def test_a_10_mm_part_fills_the_screen():
    cam = _framed_part()
    for _ in range(60):                      # the wheel, all the way in
        cam.zoom_to(1.0, V(0, 0, 0))
    assert cam.distance == pytest.approx(MIN_DISTANCE)
    assert cam.distance < 0.02               # closer than the old floor
    seen = 2.0 * cam.distance * math.tan(math.radians(cam.fov_deg) / 2.0)
    assert seen < 0.005                      # under 5 mm fill the height


def test_the_floor_rises_back_to_2_cm_far_from_the_origin():
    cam = OrbitCamera()
    assert cam.min_distance(V(0, 0, 0)) == pytest.approx(0.005)
    assert cam.min_distance(V(40, 0, 0)) == pytest.approx(0.005)
    assert cam.min_distance(V(1000, -300, 20)) == pytest.approx(0.02)
    prev = 0.0
    for d in (0, 20, 50, 100, 150, 200, 5000):
        m = cam.min_distance(V(d, 0, 0))
        assert prev <= m <= MIN_DISTANCE_FAR
        prev = m
    assert cam.min_distance(V(float("inf"), 0, 0)) == MIN_DISTANCE_FAR


def test_far_from_the_origin_the_close_up_is_what_it_was():
    far = V(1000.0, 500.0, 0.0)
    cam = _framed_part(at=far)
    for _ in range(80):
        cam.zoom_to(1.0, far)
    assert cam.distance == pytest.approx(0.02)


def _near_of(m):
    """The near distance a perspective matrix was built with."""
    a, b = m.row(2).z(), m.row(2).w()
    return b / (a - 1.0)


def test_the_near_plane_is_never_closer_than_at_the_old_floor():
    cam = OrbitCamera()
    cam.set_aspect(1200, 800)
    cam.distance = MIN_DISTANCE
    assert cam.near_plane() == pytest.approx(NEAR_FLOOR)
    assert _near_of(cam.projection_matrix()) == pytest.approx(NEAR_FLOOR,
                                                              rel=1e-3)
    cam.distance = 0.02                      # the old floor: 2 % of it
    assert cam.near_plane() == pytest.approx(0.02 * 0.02)
    cam.distance = 20.0                      # working distance: as always
    assert cam.near_plane() == pytest.approx(0.1)


def test_an_empty_scene_is_framed_as_before():
    cam = OrbitCamera()
    cam.fit_to(V(0, 0, 0), V(0, 0, 0))
    old = 0.02 * 1.3 / (2.0 * math.tan(math.radians(cam.fov_deg) / 2.0))
    assert cam.distance == pytest.approx(old)


def _stub(distance, diag, perspective=True):
    cam = OrbitCamera()
    cam.distance = distance
    cam.perspective = perspective
    return SimpleNamespace(camera=cam, _model_diag=lambda: diag,
                           _ZOOM_OUT_STEP=0.05, _CLIP_W=1e-3)


def test_zoom_out_step_is_as_before_away_from_a_close_up():
    from views.viewport import Viewport
    step = Viewport._zoom_out_step
    assert step(_stub(0.005, 0.0)) == 0.05           # empty scene: 5 cm
    assert step(_stub(0.02, 0.01)) == pytest.approx(0.05)
    assert step(_stub(3.0, 0.01)) == pytest.approx(0.05)
    assert step(_stub(0.005, 20.0)) == pytest.approx(0.2)  # 1 % of 20 m
    # up close to a 10 mm part: 1.25 cm, not the 5 cm that lost it
    assert step(_stub(0.005, 0.01)) == pytest.approx(0.0125)


def test_one_notch_out_keeps_the_small_part_in_sight():
    from views.viewport import Viewport
    cam = _framed_part()
    for _ in range(60):
        cam.zoom_to(1.0, V(0, 0, 0))
    stub = SimpleNamespace(camera=cam, _model_diag=lambda: 0.017,
                           _ZOOM_OUT_STEP=0.05)
    cam.zoom_to(-1.0, V(0, 0, 0), min_step=Viewport._zoom_out_step(stub))
    assert (cam.eye() - V(0, 0, 0)).length() < 0.02


def test_cursor_zoom_reads_model_size_only_when_retreating():
    from PySide6.QtCore import QPointF
    from views.viewport import Viewport

    stub = _stub(MIN_DISTANCE, 20.0)
    focus = V(0.0, 0.0, 0.0)
    stub.camera.target = focus
    stub.scene = SimpleNamespace(version=0)
    stub._world_under_cursor = lambda *_: focus
    measured = []
    stub._model_diag = lambda: measured.append(True) or 20.0
    stub._zoom_out_step = lambda: Viewport._zoom_out_step(stub)
    pos = QPointF(100.0, 200.0)

    for steps in (1.0, 0.0, 0.25):
        Viewport._zoom_at(stub, steps, pos)
    assert measured == []
    eye = stub.camera.eye()
    Viewport._zoom_at(stub, -0.25, pos, floor_share=0.25)
    assert measured == [True]
    assert (stub.camera.eye() - eye).length() == pytest.approx(0.05, abs=1e-6)


def test_zoom_out_diagonal_cache_follows_box_arrays():
    import numpy as np
    from views.viewport import Viewport

    table = (None, np.zeros((1, 3)), np.array([[3.0, 4.0, 0.0]]))
    scene = SimpleNamespace(version=1, bounds=lambda: (V(), V(0, 0, 12)))
    stub = SimpleNamespace(scene=scene, _pick_lazy_table=lambda: table)
    diagonal = Viewport._model_diag

    assert diagonal(stub) == 5.0
    memo = stub._zoom_diag_memo
    assert diagonal(stub) == 5.0 and stub._zoom_diag_memo is memo

    scene._bounds_cache = (scene.version,)
    assert diagonal(stub) == 12.0 and stub._zoom_diag_memo is memo
    scene.version += 1
    table = (None, table[1], np.array([[0.0, 0.0, 8.0]]))
    assert diagonal(stub) == 8.0
    assert memo[1]() is None

    memo = stub._zoom_diag_memo
    table = None
    assert memo[0]() is None and memo[1]() is None
    assert diagonal(stub) == 12.0


def test_preview_cut_follows_the_near_plane_only_up_close():
    from views.viewport import Viewport
    clip = Viewport._clip_w
    assert clip(_stub(20.0, 1.0)) == pytest.approx(1e-3)       # as always
    assert clip(_stub(0.02, 1.0)) == pytest.approx(4e-4)
    assert clip(_stub(MIN_DISTANCE, 1.0)) == pytest.approx(NEAR_FLOOR)
    assert clip(_stub(MIN_DISTANCE, 1.0, perspective=False)) == 1e-3


def test_a_preview_just_in_front_of_the_eye_is_drawn():
    """At the 5 mm close-up, a segment 0.5–0.9 mm in front of the eye was
    cut whole by the fixed 1 mm; now it shows."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(1000, 700)
        cam = vp.camera
        cam.set_aspect(1000, 700)
        cam.target = V(0, 0, 0)
        cam.distance = MIN_DISTANCE
        eye, f = cam.eye(), cam.forward()
        side = V.crossProduct(f, cam.up_vector()).normalized() * 0.0001
        p0 = eye + f * 0.0005 + side
        p1 = eye + f * 0.0009 - side
        assert vp._segment_to_pixels(p0, p1) is not None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
