# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A parallel view's depth range fits what it holds (issue #874): ±10 km
split into 24-bit steps left 1.2 mm of depth per step, and a smooth surface
and the lines over it traded places in a zigzag that perspective never
showed. Two faces 0.4 mm apart now stack the same way in both projections;
without a known reach the range is the one it always was, and it is never
wider than that."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

from core.camera import OrbitCamera

_app = QApplication.instance() or QApplication([])

V = QVector3D


def test_without_a_reach_the_range_is_the_old_one():
    cam = OrbitCamera()
    cam.perspective = False
    assert cam.parallel_depth() == cam.far_plane()


def test_the_reach_covers_what_the_view_holds_and_never_widens():
    cam = OrbitCamera()
    cam.perspective = False
    cam.target = V(0.5, 0.5, 0.0)
    cam.distance = 3.0
    cam.depth_reach = (V(0.5, 0.5, 0.5), 0.9)
    d = cam.parallel_depth()
    held = (cam.eye() - V(0.5, 0.5, 0.5)).length() + 0.9
    assert held * 2 < d < 100.0
    # A huge model: capped at the old far plane.
    cam.depth_reach = (V(0, 0, 0), 1e7)
    assert cam.parallel_depth() == cam.far_plane()
    cam.depth_reach = (V(0, 0, 0), float("inf"))
    assert cam.parallel_depth() == cam.far_plane()


def _rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    buf = np.frombuffer(img.constBits(), np.uint8)
    px = buf.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return px.reshape(img.height(), img.width(), 4)[..., :3].astype(np.int32)


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


def test_faces_close_together_do_not_fight_in_parallel(win):
    vp = win.viewport
    m = vp.scene.mesh
    gap = 0.0004
    # The upper face first: drawn first, a tie in depth would let the lower
    # one win (LEQUAL) — the fight shows as red through the blue.
    top = m.add_face([V(0.1, 0.1, gap), V(0.9, 0.1, gap), V(0.9, 0.9, gap),
                      V(0.1, 0.9, gap)])
    top.attrs["color"] = (0.0, 0.0, 1.0)
    low = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    low.attrs["color"] = (1.0, 0.0, 0.0)
    vp.scene.version += 1
    st = vp.scene.display_style
    st.edges = False
    st.profiles = False
    counts = {}
    for proj in ("perspective", "parallel"):
        vp.camera.set_view("iso")
        vp.camera.set_projection(proj)
        vp.camera.fit_to(V(0, 0, 0), V(1, 1, 0.01))
        _app.processEvents()
        px = _rgb(vp.render_image(400, 300, overlays=False))
        red = (px[..., 0] > 150) & (px[..., 2] < 100)
        blue = (px[..., 2] > 150) & (px[..., 0] < 100)
        counts[proj] = (int(red.sum()), int(blue.sum()))
        # The blue face covers the middle of the red one: the red is only
        # its rim, a minority of the two.
        assert blue.sum() > 1.5 * red.sum(), (proj, counts)
