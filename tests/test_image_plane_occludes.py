# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An opaque reference image hides what lies BEHIND it, and still shows
what is traced ON it (a user's video, 25-09): a triangle traced on a photo
on the ground, pushed DOWN into a prism, painted its sides over the photo
seen from above — the image wrote no depth at all, so anything drawn after
it won. It writes depth now, pushed back by a polygon offset.

Needs a GL context; skipped where the offscreen platform has none."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
PHOTO = (0x30, 0xC0, 0x40)          # a green the model never uses


def _photo_share(img: QImage) -> float:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    buf = np.frombuffer(img.constBits(), np.uint8)
    px = buf.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    px = px.reshape(img.height(), img.width(), 4)[..., :3].astype(int)
    near = np.abs(px - np.array(PHOTO)).sum(axis=2) < 40
    return float(near.mean())


def test_a_box_below_an_opaque_image_does_not_paint_over_it(tmp_path):
    from core.image_plane import ImagePlane
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        scene = vp.scene
        V = QVector3D
        pic = QImage(8, 8, QImage.Format_RGBA8888)
        pic.fill(0xFF000000 | (PHOTO[0] << 16) | (PHOTO[1] << 8) | PHOTO[2])
        path = tmp_path / "photo.png"
        pic.save(str(path))
        scene.image_planes.append(ImagePlane(
            str(path), V(0, 0, 0), V(10, 0, 0), V(0, 10, 0)))
        scene.version += 1
        vp.camera.set_view("iso")                  # from above the ground
        vp.camera.fit_to(V(-2, -2, -5), V(12, 12, 0))
        for _ in range(5):
            _app.processEvents()
        alone = _photo_share(vp.render_image(400, 300, overlays=False))
        if alone < 0.05:
            # a context that draws nothing textured (the offscreen platform
            # inside the full suite): nothing here could be measured
            pytest.skip("this GL context renders no textures")
        # a box hanging BELOW the photo, wider than it, seen from above
        lo, hi = -2.0, 12.0
        p = [V(lo, lo, -5), V(hi, lo, -5), V(hi, hi, -5), V(lo, hi, -5),
             V(lo, lo, -1), V(hi, lo, -1), V(hi, hi, -1), V(lo, hi, -1)]
        for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                    (2, 3, 7, 6), (3, 0, 4, 7)):
            scene.mesh.add_face([p[i] for i in idx])
        scene.version += 1
        under = _photo_share(vp.render_image(400, 300, overlays=False))
        assert under == pytest.approx(alone, abs=0.01)   # the photo still shows
        # …and a face traced ON the photo still covers it
        scene.mesh.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 10, 0),
                             V(0, 10, 0)])
        scene.version += 1
        traced = _photo_share(vp.render_image(400, 300, overlays=False))
        assert traced < alone * 0.2
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_grouped_photo_remains_visible_in_every_display_style(tmp_path):
    from core.history import MakeImageGroupCommand
    from core.image_plane import ImagePlane
    from core.style import Style
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        scene = vp.scene
        V = QVector3D
        pic = QImage(8, 8, QImage.Format_RGBA8888)
        pic.fill(0xFF000000 | (PHOTO[0] << 16) | (PHOTO[1] << 8) | PHOTO[2])
        path = tmp_path / "grouped-photo.png"
        pic.save(str(path))
        image = ImagePlane(str(path), V(0, 0, 0), V(10, 0, 0), V(0, 10, 0))
        scene.image_planes.append(image)
        vp.history.execute(MakeImageGroupCommand([image]))
        vp.camera.set_view("iso")
        vp.camera.fit_to(V(-2, -2, -1), V(12, 12, 1))

        shares = {}
        for mode in ("textures", "shaded", "hidden_line", "monochrome",
                     "wireframe", "xray"):
            scene.display_style = Style(name=mode, face_mode=mode)
            scene.version += 1
            for _ in range(3):
                _app.processEvents()
            shares[mode] = _photo_share(
                vp.render_image(400, 300, overlays=False))
        if shares["textures"] < 0.05:
            pytest.skip("this GL context renders no textures")
        assert all(share > 0.05 for share in shares.values()), shares
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
