# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The default backs take the same matte light as the fronts in the shaded
modes (issue #873): looking into an open box, its inner walls — all backs
— read in different tones the way its outer walls do, instead of one flat
blue-grey that turns the inside of a sphere into a disc. Monochrome keeps
its flat plan tint.

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


@pytest.fixture
def open_box():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        m = vp.scene.mesh
        p = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0),
             V(0, 0, 4), V(4, 0, 4), V(4, 4, 4), V(0, 4, 4)]
        # Outward walls and floor, no lid.
        for idx in ((3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5),
                    (2, 3, 7, 6), (3, 0, 4, 7)):
            m.add_face([p[i] for i in idx])
        vp.scene.version += 1
        # From above and in front-left, looking down into the box: the far
        # walls (+x, +y) show their insides — their backs.
        vp.camera.set_view("iso")
        vp.camera.fit_to(V(0, 0, 0), V(4, 4, 4))
        for _ in range(3):
            _app.processEvents()
        yield vp
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _inner_tones(vp, mode):
    """The colours of the two far inner walls: sampled where the inside
    shows, found as the pixels that change when the back tint does."""
    st = vp.scene.display_style
    st.face_mode = mode
    st.back_color = (0.62, 0.70, 0.78)
    a = _rgb(vp.render_image(320, 240, overlays=False))
    st.back_color = (0.9, 0.3, 0.3)
    b = _rgb(vp.render_image(320, 240, overlays=False))
    st.back_color = None
    inside = np.abs(a - b).sum(axis=2) > 40
    assert inside.mean() > 0.02, "no back face in the picture"
    return a, inside, None


@pytest.mark.parametrize("mode", ["shaded", "textures"])
def test_the_inner_walls_are_shaded(open_box, mode):
    a, inside, _tones = _inner_tones(open_box, mode)
    # Two walls at right angles (and a floor) under the fixed light: at
    # least two tones that each cover a good share of the inside, clearly
    # apart (the antialiased seams are a sliver).
    vals, counts = np.unique(a[inside].sum(axis=1), return_counts=True)
    big = vals[counts > 0.1 * counts.sum()]
    assert len(big) >= 2 and big.max() - big.min() > 15, (vals, counts)


def test_monochrome_keeps_its_flat_back(open_box):
    a, inside, _tones = _inner_tones(open_box, "monochrome")
    # The seams' antialiasing aside, one flat tone.
    vals, counts = np.unique(a[inside].sum(axis=1), return_counts=True)
    assert counts.max() / counts.sum() > 0.85, (vals, counts)
