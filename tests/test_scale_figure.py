# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Sumari scale figure in a fresh document: 1.72 m tall and OFF to the
left of the origin (SketchUp-style), so the origin stays visible as the
drawing reference."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

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
        assert anchor_x < -1.0                     # clear of the origin, left
        assert abs((min(ys) + max(ys)) / 2) < 1e-6
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
