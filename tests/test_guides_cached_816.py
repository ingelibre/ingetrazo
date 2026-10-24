# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tape Measure guides no longer slow every frame down (#816).

Each guide line was re-dashed in a Python loop on EVERY repaint — about
2 ms a guide, so forty guides took a frame on the Plaza model from 18 to
110 ms even with the cursor merely hovering. The dashes are built in one
NumPy pass now, and reused (with their upload) until the camera, the
guides or their selection change."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import views.viewport as vpmod  # noqa: E402
from core.guide import Guide  # noqa: E402


def test_dashes_match_a_point_by_point_construction():
    g = Guide(V(1, 2, 3), V(1, 1, 0))
    coords, spans = vpmod._guide_vertices([g], 0.5, centre=V(0, 0, 0),
                                          reach=10.0)
    a = np.frombuffer(coords, np.float32).reshape(-1, 2, 3)
    d = g.direction
    tf = V.dotProduct(V(0, 0, 0) - g.point, d)
    for k in (0, 7, len(a) - 1):
        t = tf - 10.0 + k * 0.5
        want0 = g.point + d * t
        want1 = g.point + d * (t + 0.25)
        assert np.allclose(a[k, 0], (want0.x(), want0.y(), want0.z()),
                           atol=1e-5)
        assert np.allclose(a[k, 1], (want1.x(), want1.y(), want1.z()),
                           atol=1e-5)
    assert spans == [(0, 2 * len(a), False)]


def test_a_repaint_without_change_reuses_the_dashes(monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    try:
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        calls = []
        real = vpmod._guide_vertices
        monkeypatch.setattr(vpmod, "_guide_vertices",
                            lambda *a, **k: calls.append(1) or real(*a, **k))
        vp.scene.guides.append(Guide(V(0, 0, 0), V(1, 0, 0)))
        vp.scene.version += 1
        for _ in range(3):
            vp.render_image(200, 150, overlays=False)
        assert len(calls) == 1
        vp.camera.distance *= 2.0                   # the camera moved
        vp.render_image(200, 150, overlays=False)
        assert len(calls) == 2
        vp.scene.guides[0].point = V(0, 5, 0)       # a guide moved
        vp.render_image(200, 150, overlays=False)
        assert len(calls) == 3
        vp.scene.selection.add(vp.scene.guides[0])  # selected: new colour
        vp.render_image(200, 150, overlays=False)
        assert len(calls) == 4
    finally:
        win._saved_version = vp.scene.version
        win.close()


def _pixels(img):
    a = img.convertToFormat(img.Format.Format_RGB32)
    buf = np.frombuffer(a.constBits(), np.uint8).reshape(
        a.height(), a.bytesPerLine())[:, :a.width() * 4]
    return buf.copy()


def test_the_edit_box_sharing_the_buffer_does_not_eat_the_guides():
    """The dashed box of the group being edited reuses the guides' buffer;
    a cached frame must not draw the box where the guides were."""
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    try:
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        m = Mesh()
        m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
        g = Group(m, "g")
        vp.scene.groups.append(g)
        vp.scene.guides.append(Guide(V(0, 3, 0), V(1, 0, 0)))
        vp.camera.target, vp.camera.distance = V(0.5, 1.5, 0), 8.0
        vp.camera.set_view("top")
        vp.scene.begin_group_edit(g)
        vp.scene.version += 1
        first = _pixels(vp.render_image(300, 300, overlays=False))
        second = _pixels(vp.render_image(300, 300, overlays=False))
        assert (first == second).all()
        # And the guide is really there: a row of guide-blue pixels.
        vp.scene.guides[:] = []
        bare = _pixels(vp.render_image(300, 300, overlays=False))
        assert (first != bare).any()
    finally:
        win._saved_version = vp.scene.version
        win.close()
