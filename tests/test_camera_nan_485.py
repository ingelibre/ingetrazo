# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A camera that went NaN while orbiting zoomed in (#485, #383).

Zoomed right in, the depth read-back that picks the orbit pivot unprojected
to a point absurdly far away — or to infinity. The orbit turned the camera
about it, threw the view off, and once the target held a NaN the save was
refused ("Where: scene › camera › target[0]"), so unsaved work was at risk.
Three guards: the orbit never leaves a NaN pose, a bad pivot is ignored, and
a broken view never blocks saving the model.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera
from core.scene import Scene
from formats import igz


def _finite(cam) -> bool:
    return cam.is_finite()


def test_an_orbit_about_an_absurdly_far_pivot_keeps_a_real_pose():
    cam = OrbitCamera()
    cam.distance = 0.02                      # zoomed right in
    far = QVector3D(3e38, -3e38, 3e38)       # what the depth read-back gave
    for _ in range(20):
        cam.orbit_about(far, 35.0, -20.0, 600)
    assert _finite(cam)


def test_an_orbit_about_a_nan_pivot_turns_about_the_target():
    cam = OrbitCamera()
    target = QVector3D(cam.target)
    yaw = cam.yaw
    cam.orbit_about(QVector3D(math.nan, 0.0, 0.0), 40.0, 0.0, 600)
    assert _finite(cam)
    assert cam.yaw != yaw                    # it still orbits
    assert (cam.target - target).length() < 1e-9


def test_a_nan_view_does_not_block_the_save(tmp_path):
    path = tmp_path / "puente.igz"
    scene = Scene()
    scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                         QVector3D(1, 1, 0)])
    scene.camera_home = {"target": [math.nan, 0.0, 0.0], "distance": 5.0,
                         "yaw": 0.3, "pitch": 0.4}
    igz.save_scene(scene, path)              # no NonFiniteDocumentError
    back = Scene()
    igz.load_into(back, path)
    assert len(back.faces) == 1              # the model is all there
    assert back.camera_home is None          # opens framed on the model


def test_a_good_view_is_still_saved(tmp_path):
    path = tmp_path / "puente.igz"
    scene = Scene()
    scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                         QVector3D(1, 1, 0)])
    cam = {"target": [1.0, 2.0, 0.0], "distance": 5.0, "yaw": 0.3,
           "pitch": 0.4}
    scene.camera_home = dict(cam)
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.camera_home == cam
