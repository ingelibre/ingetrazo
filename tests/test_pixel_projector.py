# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The snap search projects thousands of points per pointer move through a
projector made once per search (#158): it must give exactly the pixels of
_world_to_pixel, point for point, on every camera."""
from __future__ import annotations

import math
import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_the_projector_gives_the_pixels_of_world_to_pixel():
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1234, 777)
    cam = vp.camera
    rng = random.Random(20261023)
    for case in range(40):
        cam.yaw = rng.uniform(-math.pi, math.pi)
        cam.pitch = rng.uniform(-1.4, 1.4)
        cam.distance = 10 ** rng.uniform(-1, 4)
        cam.target = V(rng.uniform(-500, 500), rng.uniform(-500, 500),
                       rng.uniform(-50, 50))
        cam.perspective = case % 3 != 0
        cam.two_point = case % 5 == 0
        cam.set_aspect(vp.width(), vp.height())
        project = vp._pixel_projector()
        for _ in range(50):
            p = V(rng.uniform(-2000, 2000), rng.uniform(-2000, 2000),
                  rng.uniform(-300, 300))
            assert project(p) == vp._world_to_pixel(p)


def test_a_stand_in_world_to_pixel_is_what_the_search_gets():
    from views.viewport import Viewport
    vp = Viewport(None)
    vp._world_to_pixel = lambda w: (1.0, 2.0)
    assert vp._pixel_projector()(V(0, 0, 0)) == (1.0, 2.0)
