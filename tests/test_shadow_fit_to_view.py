# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sun's map fitted to the settled view (#958).

The view's shadow map spreads 2048 texels over the whole model: on a 200 m
site each is 12 cm, so a lattice of 5 cm slats casts one even half-shade.
Once the view has stayed put, a second map of the same size over only what
it shows is drawn and the slats come out one by one; the moment the camera
moves, the whole-model map is back (orbiting costs what it always did).
Marco, playa Yanque: «la sombra no tan nítida… ¿será por el rendimiento?»."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _lum(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    buf = np.frombuffer(img.constBits(), np.uint8)
    px = buf.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return px.reshape(img.height(), img.width(), 4)[..., :3].astype(
        np.float32).mean(axis=2)


@pytest.fixture
def lattice():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(900, 700)
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        mesh = vp.scene.mesh
        mesh.add_face([V(-100, -100, 0), V(100, -100, 0), V(100, 100, 0),
                       V(-100, 100, 0)])
        for k in range(20):                     # 5 cm slats, 5 cm apart
            x0 = -1.0 + k * 0.1
            x1 = x0 + 0.05
            p = [V(x0, -1, 2.5), V(x1, -1, 2.5), V(x1, 1, 2.5), V(x0, 1, 2.5),
                 V(x0, -1, 2.55), V(x1, -1, 2.55), V(x1, 1, 2.55),
                 V(x0, 1, 2.55)]
            for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                mesh.add_face([p[i] for i in idx])
        vp.scene.version += 1
        sh = vp.scene.shadows
        sh.enabled = True
        sh.month, sh.day, sh.hour = 6, 21, 12
        d = vp._sun_dir_now()
        t = 2.5 / d[2]                          # where the lattice's shadow lies
        cam = vp.camera
        cam.target = V(-d[0] * t, -d[1] * t, 0)
        cam.yaw = math.radians(-60)
        cam.pitch = math.radians(55)
        cam.distance = 4.0
        yield vp
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _settle(vp):
    """Stay put past the settle delay, painting as the view would (an
    offscreen window gets no expose from ``update``)."""
    vp.grabFramebuffer()
    for _ in range(3):
        _wait(vp.SHADOW_SETTLE_MS + 120)
        vp.grabFramebuffer()


def test_the_settled_view_draws_the_slats_one_by_one(lattice):
    vp = lattice
    moving = _lum(vp.grabFramebuffer())
    assert vp._frame_shadow is vp._shadow_fbo           # whole-model map
    _settle(vp)
    still = _lum(vp.grabFramebuffer())
    assert vp._shadow_fit is not None
    assert vp._frame_shadow is vp._fine_shadow_fbo
    # The floor under the lattice: an even half-shade before, stripes now.
    h, w = still.shape
    win = (slice(h // 3, 2 * h // 3), slice(w // 3, 2 * w // 3))
    assert still[win].std() > 2.0 * moving[win].std() + 2.0


def test_the_camera_moving_brings_the_whole_model_map_back(lattice):
    vp = lattice
    _settle(vp)
    vp.grabFramebuffer()
    assert vp._frame_shadow is vp._fine_shadow_fbo
    vp.camera.yaw += math.radians(5)
    vp.grabFramebuffer()
    assert vp._frame_shadow is vp._shadow_fbo


def test_an_edit_brings_the_whole_model_map_back(lattice):
    vp = lattice
    _settle(vp)
    vp.grabFramebuffer()
    assert vp._frame_shadow is vp._fine_shadow_fbo
    vp.scene.mesh.add_face([V(5, 5, 0.01), V(6, 5, 0.01), V(6, 6, 0.01),
                            V(5, 6, 0.01)])
    vp.scene.version += 1
    vp.grabFramebuffer()
    assert vp._frame_shadow is vp._shadow_fbo


def test_an_export_keeps_its_own_map(lattice):
    vp = lattice
    _settle(vp)
    vp.grabFramebuffer()
    fine = vp._fine_shadow_fbo
    vp.render_image(400, 300, overlays=False, sharp_shadows=True)
    vp.grabFramebuffer()
    assert vp._frame_shadow is fine                     # still fitted after
