# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A reference image in front of a face takes the click (#426, @joejivaros).

An image is an underlay, so picking tried it LAST, after any face — even a
face far behind it: with the top of a box hidden, the bottom took every
click meant for the picture lying inside, and it could not be selected at
all. A face on the image's plane (traced on it) still wins."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _setup(tmp_path, image_z):
    from core.image_plane import ImagePlane
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(400, 300)
    scene = vp.scene
    p = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0),
         V(0, 0, 2), V(4, 0, 2), V(4, 4, 2), V(0, 4, 2)]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        scene.mesh.add_face([p[i] for i in q])
    top = next(f for f in scene.mesh.faces if f.normal().z() > 0.9)
    top.attrs["hidden"] = True
    pic = QImage(8, 8, QImage.Format_RGBA8888)
    pic.fill(0xFF30C040)
    path = tmp_path / "photo.png"
    pic.save(str(path))
    image = ImagePlane(str(path), V(1, 1, image_z), V(2, 0, 0), V(0, 2, 0))
    scene.image_planes.append(image)
    scene.version += 1
    cam = vp.camera
    cam.set_view("top")
    cam.target, cam.distance = V(2, 2, 1), 12.0
    return vp, image


def _pick_centre(vp):
    from tools.select import SelectTool
    sx, sy = vp.width() / 2, vp.height() / 2
    return SelectTool()._pick(vp, sx, sy)


def test_an_image_inside_a_box_with_its_top_hidden_is_picked(tmp_path):
    vp, image = _setup(tmp_path, image_z=1.0)
    assert _pick_centre(vp) is image


def test_a_face_on_the_image_plane_still_wins(tmp_path):
    vp, image = _setup(tmp_path, image_z=0.0)      # lying on the bottom
    hit = _pick_centre(vp)
    assert hit is not image and hit is not None
