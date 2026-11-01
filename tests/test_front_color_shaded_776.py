# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The style's Front color dresses the faces that wear no material in every
face mode that draws faces, not only in Hidden line and Monochrome (issue
#776): picked, the default faces take it in Textures, Shaded and X-ray;
the stock white keeps the stock warm-white look to the pixel; a painted
face keeps its paint; the back faces keep the back tint; a group's faces
take it too.

The rendering cases need a GL context; skipped where there is none."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

V = QVector3D


def _rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    buf = np.frombuffer(img.constBits(), np.uint8)
    px = buf.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return px.reshape(img.height(), img.width(), 4)[..., :3].astype(np.int32)


def _box(mesh, x0=0.0, color=None):
    p = [V(x0, 0, 0), V(x0 + 2, 0, 0), V(x0 + 2, 2, 0), V(x0, 2, 0),
         V(x0, 0, 2), V(x0 + 2, 0, 2), V(x0 + 2, 2, 2), V(x0, 2, 2)]
    faces = []
    for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        f = mesh.add_face([p[i] for i in idx])
        if color is not None:
            f.attrs["color"] = color
        faces.append(f)
    return faces


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    try:
        w.show()
        _app.processEvents()
        vp = w.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        yield w
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()


def _frame(vp, lo, hi):
    vp.camera.set_view("iso")
    vp.camera.fit_to(lo, hi)
    for _ in range(3):
        _app.processEvents()


def _shot(vp):
    return _rgb(vp.render_image(320, 240, overlays=False))


@pytest.mark.parametrize("mode", ["textures", "shaded", "xray"])
def test_front_color_paints_the_default_faces(win, mode):
    vp = win.viewport
    sc = vp.scene
    _box(sc.mesh)                                    # default material
    _box(sc.mesh, x0=4.0, color=(0.1, 0.6, 0.1))     # painted green
    sc.version += 1
    _frame(vp, V(-1, -1, 0), V(7, 3, 2))
    sc.display_style.face_mode = mode
    stock = _shot(vp)
    sc.display_style.front_color = (1.0, 0.0, 0.0)
    red = _shot(vp)
    diff = np.abs(red - stock).sum(axis=2)
    changed = diff > 30
    assert changed.mean() > 0.02, "the default box did not take the colour"
    # What changed went red: green and blue fell, red held.
    assert (red[changed][:, 1] < stock[changed][:, 1] - 20).mean() > 0.9
    # The painted box is the same picture: only the left half moved.
    h, w = changed.shape
    cols = np.flatnonzero(changed.any(axis=0))
    assert cols.max() < w * 0.62, "the painted box changed colour too"
    # Back to the stock white: the very same picture as before.
    sc.display_style.front_color = (1.0, 1.0, 1.0)
    assert np.array_equal(_shot(vp), stock)


def test_back_faces_keep_the_back_tint(win):
    vp = win.viewport
    sc = vp.scene
    faces = _box(sc.mesh)
    # Open the box at the top and look in: the inner walls are backs.
    sc.mesh.remove_face(faces[1])
    sc.version += 1
    vp.camera.set_view("top")
    vp.camera.fit_to(V(-0.5, -0.5, 0), V(2.5, 2.5, 2))
    for _ in range(3):
        _app.processEvents()
    sc.display_style.face_mode = "shaded"
    stock = _shot(vp)
    sc.display_style.front_color = (1.0, 0.0, 0.0)
    red = _shot(vp)
    h, w = stock.shape[:2]
    # The floor seen from above is the bottom face's BACK (its front
    # points down): it keeps the back tint.
    c = (slice(h // 2 - 5, h // 2 + 5), slice(w // 2 - 5, w // 2 + 5))
    assert np.array_equal(red[c], stock[c])


def test_a_group_takes_it_and_a_painted_group_keeps_its_paint(win):
    from core.group import Group
    from core.mesh import Mesh
    vp = win.viewport
    sc = vp.scene
    plain = Mesh()
    _box(plain)
    painted = Mesh()
    _box(painted, x0=4.0)
    sc.groups.append(Group(name="plain", mesh=plain))
    gp = Group(name="painted", mesh=painted)
    gp.material = {"color": (0.1, 0.2, 0.8)}
    sc.groups.append(gp)
    sc.version += 1
    _frame(vp, V(-1, -1, 0), V(7, 3, 2))
    sc.display_style.face_mode = "shaded"
    stock = _shot(vp)
    sc.display_style.front_color = (1.0, 0.0, 0.0)
    red = _shot(vp)
    changed = np.abs(red - stock).sum(axis=2) > 30
    assert changed.mean() > 0.02
    w = changed.shape[1]
    assert np.flatnonzero(changed.any(axis=0)).max() < w * 0.62


def test_the_stock_white_bakes_nothing_new():
    from core.style import Style
    from views.viewport import _front_tint
    assert _front_tint(Style()) is None
    assert _front_tint(Style(face_mode="hidden_line",
                             front_color=(1, 0, 0))) is None
    assert _front_tint(Style(front_color=(1, 0, 0)))[1] == 0.0
