# SPDX-License-Identifier: GPL-3.0-or-later
"""The Iso command from a low camera (#1181).

Held about level — at eye height, after Walk or Look Around — the camera
went to an isometric view from BELOW (a degree up was enough), turned
about a point half a metre before the eyes, and the model left the
picture. A view from below now needs the camera clearly looking up, and
the model is framed when the turn took it out of sight; a zoom on a
detail is kept."""
from __future__ import annotations

import math
import sys

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.camera import OrbitCamera

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.mark.parametrize("pitch_deg", [5.0, 1.0, 0.0, -1.0, -5.0, -9.0])
def test_a_camera_about_level_gets_an_iso_from_above(pitch_deg):
    c = OrbitCamera()
    c.yaw = math.radians(-80.0)
    c.pitch = math.radians(pitch_deg)
    c.snap_iso()
    assert c.pitch == pytest.approx(math.radians(30.0), abs=1e-9)


@pytest.mark.parametrize("pitch_deg", [-12.0, -20.0, -60.0])
def test_a_camera_clearly_looking_up_gets_an_iso_from_below(pitch_deg):
    c = OrbitCamera()
    c.yaw = math.radians(-80.0)
    c.pitch = math.radians(pitch_deg)
    c.snap_iso()
    assert c.pitch == pytest.approx(math.radians(-30.0), abs=1e-9)


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    vp = w.viewport
    vp.scene.groups.clear()
    vp.scene.mesh.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 8, 0),
                            V(0, 8, 0)])
    vp.scene.mesh.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 0, 3),
                            V(0, 0, 3)])
    vp.scene.version += 1
    vp.camera.set_aspect(vp.width(), vp.height())
    yield w
    w._saved_version = vp.scene.version
    w.close()


def _corners_on_screen(vp) -> int:
    n = 0
    for x in (0.0, 10.0):
        for y in (0.0, 8.0):
            for z in (0.0, 3.0):
                p = vp._world_to_pixel(V(x, y, z))
                if p and 0 <= p[0] <= vp.width() and 0 <= p[1] <= vp.height():
                    n += 1
    return n


def test_iso_after_walking_up_to_the_model_frames_it_from_above(win):
    vp = win.viewport
    cam = vp.camera
    # Standing before the façade at eye height, looking a hair up: the
    # camera's target half a metre before the eyes, as Walk leaves it.
    cam.set_view("front")
    cam.target = V(5.0, -6.0, 1.6)
    cam.distance = 0.5
    cam.pitch = math.radians(-3.0)
    win._on_standard_view("iso")
    assert cam.pitch == pytest.approx(math.radians(30.0), abs=1e-9)
    assert _corners_on_screen(vp) == 8          # the whole model in view


def test_iso_keeps_a_zoom_on_a_detail(win):
    vp = win.viewport
    cam = vp.camera
    cam.set_view("iso")
    cam.fit_to(V(0, 0, 0), V(10, 8, 3))
    cam.target = V(9.5, 0.2, 2.8)               # a corner of the model
    cam.distance = 1.2
    cam.yaw = math.radians(-60.0)
    cam.pitch = math.radians(20.0)
    win._on_standard_view("iso")
    assert cam.distance == pytest.approx(1.2)
    assert cam.target == V(9.5, 0.2, 2.8)
