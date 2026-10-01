# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""X-ray fades the edges that sit behind a face.

Every edge used to come out equally dark, so looking down into a box you
could not tell whether it had a lid: the form read the same open or closed.
Now an edge with a face in front of it is washed toward the background and
one with nothing in front keeps its full colour — the form is kept and a
face shows where it is, without the faces losing their transparency.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _viewport():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    return win, vp


def _pixels(img: QImage):
    a = img.convertToFormat(QImage.Format_RGB32)
    buf = np.frombuffer(a.constBits(), np.uint8).reshape(
        a.height(), a.bytesPerLine())[:, :a.width() * 4]
    return buf.reshape(a.height(), a.width(), 4)[..., :3].astype(int).copy()


def _contrast(before, after) -> int:
    """How much an edge changed the picture — a difference, since MSAA
    blends a one-pixel line with whatever lies behind it."""
    return int(np.abs(after - before).sum())


def test_an_edge_under_a_face_is_fainter_than_one_in_the_open():
    from core.style import style_by_name
    win, vp = _viewport()
    scene = vp.scene
    try:
        # A lid over the left half (x < 0), two metres up; nothing on the
        # right. Seen from above.
        scene.mesh.add_face([V(-60, -60, 2), V(0, -60, 2), V(0, 60, 2),
                             V(-60, 60, 2)])
        scene.version += 1
        cam = vp.camera
        cam.target = V(0, 0, 0)
        cam.distance, cam.yaw, cam.pitch = 30.0, 0.0, 1.5
        cam.perspective = False
        vp.style_override = style_by_name("X-ray")
        bare = _pixels(vp.render_image(300, 300, overlays=False))

        under = scene.add_edge(V(-5, -4, 0), V(-5, 4, 0))
        scene.version += 1
        hidden = _contrast(bare, _pixels(
            vp.render_image(300, 300, overlays=False)))
        scene.mesh.remove_edge(under)

        scene.add_edge(V(5, -4, 0), V(5, 4, 0))
        scene.version += 1
        shown = _contrast(bare, _pixels(
            vp.render_image(300, 300, overlays=False)))

        assert hidden > 0, "X-ray must still show the edge through the lid"
        assert hidden < 0.7 * shown, (
            f"the edge under the lid must read fainter "
            f"(hidden={hidden}, open={shown})")
    finally:
        vp.style_override = None
        win._saved_version = scene.version
        win.close()
