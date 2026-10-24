# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Where two faces cross with no edge between them, the cursor snaps to
the crossing (#819, @xcd-droid).

A box sunk into the floor, a beam through a wall: SketchUp offers
«Intersection» along the line where the two faces meet; IngeTrazo only
said «On face», so a line could not start exactly on it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.snap import compute_snap  # noqa: E402


class _Edge:
    def __init__(self, a, b):
        self.a, self.b = a, b


class _Scene:
    def __init__(self, edges=()):
        self.edges = list(edges)


def _w2p(p):
    return (p.x() * 100.0, p.y() * 100.0)


def _snap(scene, cursor, crossing, **kw):
    return compute_snap(
        candidate_world=cursor, candidate_pixel=_w2p(cursor), scene=scene,
        world_to_pixel=_w2p, threshold_px=9.0, edge_threshold_px=14.0,
        face_under_cursor=kw.pop("face_under_cursor", True),
        face_crossing=crossing, **kw)


def test_the_engine_offers_the_crossing_over_a_face():
    hit = V(1.0, 1.0, 0.0)
    snap = _snap(_Scene(), V(1.02, 1.0, 0.0), lambda: (hit, "group"))
    assert snap.kind == "intersection" and snap.point == hit
    assert snap.context == "group"


def test_a_real_edge_or_point_still_wins_and_open_air_asks_nothing():
    asked = []

    def crossing():
        asked.append(1)
        return (V(1.0, 1.0, 0.0), None)

    edge = _Edge(V(0.0, 1.0, 0.0), V(2.0, 1.0, 0.0))
    snap = _snap(_Scene([edge]), V(0.6, 1.03, 0.0), crossing)
    assert snap.kind == "on_edge" and asked == []
    snap = _snap(_Scene(), V(1.0, 1.0, 0.0), crossing,
                 face_under_cursor=False)
    assert snap.kind == "none" and asked == []
    snap = _snap(_Scene(), V(1.0, 1.0, 0.0), lambda: None)
    assert snap.kind == "on_face"


def _sunk_box_window():
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    vp = win.viewport
    vp.resize(900, 600)
    scene = vp.scene
    scene.mesh.add_face([V(-5, -5, 0), V(5, -5, 0), V(5, 5, 0), V(-5, 5, 0)])
    m = Mesh()
    p = [V(0, 0, -0.5), V(1, 0, -0.5), V(1, 1, -0.5), V(0, 1, -0.5),
         V(0, 0, 1.5), V(1, 0, 1.5), V(1, 1, 1.5), V(0, 1, 1.5)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    scene.groups.append(Group(m, "box"))
    scene.version += 1
    cam = vp.camera
    cam.target = V(0.5, 0.5, 0.3)
    cam.distance = 5.0
    win._activate_tool("line")
    return win, vp


def test_the_line_tool_snaps_where_a_sunk_box_meets_the_floor():
    win, vp = _sunk_box_window()
    try:
        for on_line in (V(0.5, 0.0, 0.0), V(1.0, 0.5, 0.0)):
            px = vp._world_to_pixel(on_line)
            assert px is not None
            for dy in (0.0, -4.0, 4.0):
                snap = vp._snap_at(px[0], px[1] + dy, Qt.NoModifier)
                assert snap.kind == "intersection", (on_line, dy, snap.kind)
                assert abs(snap.point.z()) < 1e-4          # on the floor…
                assert snap.context == "group"            # …and the box
            far = vp._snap_at(px[0], px[1] - 40.0, Qt.NoModifier)
            assert far.kind == "on_face"
    finally:
        win._saved_version = vp.scene.version
        win.close()
