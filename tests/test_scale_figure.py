# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Sumari scale figure in a fresh document: 1.72 m tall and OFF to the
left of the origin (SketchUp-style), so the origin stays visible as the
drawing reference."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def test_scale_figure_left_of_origin_and_172():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        fig = next(g for g in win.viewport.scene.groups
                   if getattr(g, "billboard", False))
        assert fig.name == "Sumari"
        xs = [v.position.x() for v in fig.mesh.vertices]
        ys = [v.position.y() for v in fig.mesh.vertices]
        zs = [v.position.z() for v in fig.mesh.vertices]
        anchor_x = (min(xs) + max(xs)) / 2
        anchor_y = (min(ys) + max(ys)) / 2
        assert abs(anchor_x + 0.65) < 1e-6         # 65 cm left of the origin
        assert abs(anchor_y + 0.60) < 1e-6         # 60 cm toward the viewer
        assert min(zs) == 0.0                      # feet on the ground
        assert abs(max(zs) - 1.72) < 1e-6          # the reference height
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_billboard_group_position_offsets_anchor():
    from PySide6.QtGui import QVector3D
    from core.group import make_billboard_group
    g = make_billboard_group("x.png", 2.0, "P", 0.5,
                             position=QVector3D(-3.0, 1.0, 0.0))
    xs = [v.position.x() for v in g.mesh.vertices]
    ys = [v.position.y() for v in g.mesh.vertices]
    zs = [v.position.z() for v in g.mesh.vertices]
    assert abs((min(xs) + max(xs)) / 2 + 3.0) < 1e-9
    assert ys == [1.0] * 4
    assert (min(zs), max(zs)) == (0.0, 2.0)


def test_faceme_follows_the_view_direction_in_parallel_projection():
    """A parallel camera has no real eye: every face-me sprite faces the
    VIEW direction, so a figure far from the orbit target no longer turns
    away when zoomed in (Marco's front elevation, 2026-09-02). Perspective
    keeps turning toward the eye, like SketchUp."""
    import math
    from PySide6.QtGui import QVector3D
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        fig = next(g for g in vp.scene.groups if getattr(g, "billboard", False))
        cam = vp.camera
        cam.set_view("front")
        cam.target = QVector3D(3.0, 0.0, 1.0)     # figure 3.65 m off-target
        cam.distance = 3.0

        def turn_deg():
            c0, c1 = vp._billboard_quad(fig)[0][:2]
            r = (c1 - c0).normalized()
            v = cam.eye() - cam.target
            v = QVector3D(v.x(), v.y(), 0.0).normalized()
            return math.degrees(math.asin(abs(QVector3D.dotProduct(r, v))))

        cam.perspective = False
        assert turn_deg() < 1e-6                  # square to the view
        cam.perspective = True
        assert turn_deg() > 30.0                  # turns toward the eye
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
