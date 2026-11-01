# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The cursor snaps to a CLOSED group from outside it (#997, @dre87bb2):
its corners, the middles of its edges and its faces, with no need to open
or explode it — and a line drawn towards it stops on its face instead of
passing through."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _box_window():
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    vp = win.viewport
    vp.resize(900, 600)
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    vp.scene.groups.append(Group(m, "box"))
    vp.scene.version += 1
    cam = vp.camera
    cam.target = V(0.5, 0.5, 0.5)
    cam.distance = 5.0
    win._activate_tool("line")
    return win, vp


def test_corners_edges_and_faces_of_a_closed_group_snap():
    win, vp = _box_window()
    try:
        assert vp.scene.edit_group is None
        corner = V(1, 0, 1)
        px = vp._world_to_pixel(corner)
        snap = vp._snap_at(px[0] + 2, px[1] + 2, Qt.NoModifier)
        assert snap.kind == "endpoint"
        assert (snap.point - corner).length() < 1e-6
        mid = V(0.5, 0, 1)
        px = vp._world_to_pixel(mid)
        snap = vp._snap_at(px[0], px[1] + 2, Qt.NoModifier)
        assert snap.kind == "midpoint"
        assert (snap.point - mid).length() < 1e-6
        top = V(0.4, 0.6, 1)
        px = vp._world_to_pixel(top)
        snap = vp._snap_at(*px, Qt.NoModifier)
        assert snap.kind == "on_face"
        # ON the group's top face, not through it to the ground behind
        assert abs(snap.point.z() - 1.0) < 1e-4
    finally:
        win._saved_version = vp.scene.version
        win.close()
