# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What an exported picture says about its alpha, read back from the PNG.

The scene's blending used to treat the alpha like a colour: a pane of 30 %
over an opaque background left 201 in the file and two panes 164, in every
picture, so a viewer showed a hole behind the glass. With the Transparent
background box of Export image the file is opaque only where the model is.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
V = QVector3D
WIDTH = 900
GLASS = {"color": (0.2, 0.55, 0.85), "opacity": 0.3}


def _box(mesh, x0, x1, y0, y1, z0, z1, **attrs):
    c = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([c[i] for i in q]).attrs.update(attrs)


def _pane(mesh, x0, x1, y, **attrs):
    mesh.add_face([V(x0, y, 0), V(x1, y, 0), V(x1, y, 3),
                   V(x0, y, 3)]).attrs.update(attrs)


#: Where to look, as points on the front pane's plane.
ZONES = {"background": V(-9, -2, 6), "glass": V(-3, -2, 2.8),
         "double": V(-5, -2, 2.8), "glass_on_solid": V(-1, -2, 1.5),
         "solid": V(1.5, -2, 1.5), "tex_on_solid": V(4, -2, 1.5)}


@pytest.fixture
def view(tmp_path):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        win._saved_version = vp.scene.version
        win.close()
        pytest.skip("no OpenGL context on this platform")
    mesh = vp.scene.mesh
    tex = tmp_path / "blue.png"
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(40, 90, 200))
    img.save(str(tex))
    _box(mesh, -2, 6, 0, 4, 0, 3, color=(0.75, 0.35, 0.25))
    _pane(mesh, -6, 0, -2, **GLASS)
    _pane(mesh, -6, -4, -1.5, **GLASS)
    _pane(mesh, 3, 5, -2, opacity=0.3,
          texture={"path": str(tex), "sw": 1, "sh": 1})
    vp.scene.version += 1
    cam = vp.camera
    cam.perspective = False
    cam.target = V(0, 0, 1.5)
    cam.distance, cam.yaw, cam.pitch = 22.0, -1.5707963, 0.12
    yield win, vp, tmp_path
    vp.style_override = None
    vp.scene.shadows.enabled = False
    win._saved_version = vp.scene.version
    win.close()


def _saved(vp, folder, style, **kw):
    """The picture as a viewer gets it: written to disk and read back."""
    from core.style import style_by_name
    vp.style_override = style_by_name(style)
    path = folder / "out.png"
    assert vp.render_image(WIDTH, sharp_shadows=True, **kw).save(str(path))
    return QImage(str(path)).convertToFormat(QImage.Format_ARGB32)


def _at(vp, img, zone):
    x, y = vp._world_to_pixel(ZONES[zone])
    scale = WIDTH / vp.width()
    return img.pixelColor(int(x * scale), int(y * scale))


@pytest.mark.parametrize("style", ["Default", "Shaded", "Monochrome",
                                   "Hidden line", "X-ray"])
@pytest.mark.parametrize("sun", [False, True])
def test_a_normal_picture_is_opaque_behind_the_glass(view, style, sun):
    _win, vp, folder = view
    vp.scene.shadows.enabled = sun
    img = _saved(vp, folder, style)
    for zone in ZONES:
        assert _at(vp, img, zone).alpha() == 255, zone


def test_the_occlusion_pass_leaves_the_same_blending(view, monkeypatch):
    """It multiplies with a blending of its own and puts the scene's back
    before the glass draws."""
    _win, vp, folder = view
    monkeypatch.setenv("INGETRAZO_AO", "1")
    img = _saved(vp, folder, "Default")
    for zone in ZONES:
        assert _at(vp, img, zone).alpha() == 255, zone
