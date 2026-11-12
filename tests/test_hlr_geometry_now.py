# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A sheet frame showing other layers than the live model takes its
geometry from the placements' cached arrays (``hlr_geometry_now``), not
from the per-face walk that kept Marco waiting ~20 s on the Queñuamarca
plaza before the first dimension snapped (2026-11-12). Same geometry, read
with the layers as they are switched at the time of asking."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.layers import Layer  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _box(scene, layer, x0):
    from core.group import Group
    from core.mesh import Mesh
    group = Group(Mesh(), name=f"box {layer}")
    group.layer = layer
    p = [V(x0, 0, 0), V(x0 + 6, 0, 0), V(x0 + 6, 2, 0), V(x0, 2, 0),
         V(x0, 0, 3), V(x0 + 6, 0, 3), V(x0 + 6, 2, 3), V(x0, 2, 3)]
    for f in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
              (4, 5, 6, 7), (3, 2, 1, 0)):
        group.mesh.add_face([p[i] for i in f])
    scene.groups.append(group)


def _edge_set(arr):
    return sorted(tuple(sorted((tuple(np.round(a, 4)), tuple(np.round(b, 4)))))
                  for a, b in arr)


def _area(tris):
    if not len(tris):
        return 0.0
    return float(np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0],
                                         tris[:, 2] - tris[:, 0]),
                                axis=1).sum() / 2)


def test_the_arrays_match_the_walk_with_the_layers_switched_now():
    from core.hlr import collect_geometry
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene = vp.scene
        scene.layers.append(Layer("OG", visible=False))
        scene.layers.append(Layer("EG"))
        _box(scene, "OG", 0.0)
        _box(scene, "EG", 10.0)
        scene.loose_mesh.add_edge(V(0, -5, 0), V(4, -5, 0))
        scene.version += 1
        vp.hlr_geometry()                     # the live view: OG hidden
        for og, eg in ((True, False), (True, True), (False, True)):
            scene.layer("OG").visible = og
            scene.layer("EG").visible = eg
            tris, hard, soft, _n = vp.hlr_geometry_now()
            w_tris, w_hard, w_soft = collect_geometry(scene)
            w_hard = np.asarray(w_hard, dtype=float).reshape(-1, 2, 3)
            assert _edge_set(hard) == _edge_set(w_hard)
            assert len(soft) == len(w_soft)
            w_tris = np.asarray(w_tris, dtype=float).reshape(-1, 3, 3)
            assert abs(_area(tris) - _area(w_tris)) < 1e-6
            # both boxes or one: 2 × (5 × 18 + 6 × 12)… just: not empty
            assert len(hard) >= 12 * (og + eg)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_frame_with_other_layers_does_not_walk_the_faces(monkeypatch):
    import core.hlr
    from core.saved_views import SavedView
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        scene = win.viewport.scene
        scene.layers.append(Layer("OG", visible=False))
        _box(scene, "OG", 0.0)
        scene.saved_views.append(SavedView(
            "Plan OG", target=(3.0, 1.0, 1.5), distance=20.0, yaw=0.0,
            pitch=0.0, perspective=False, hidden_layers=[]))
        comp = ComposerWindow(win)
        comp._auto_render = False
        frame = comp.comp.frames[0]
        frame.view_key = "scene:Plan OG"
        comp._invalidate_geometry_caches()

        def walk(*a, **k):
            raise AssertionError("the per-face walk ran")
        monkeypatch.setattr(core.hlr, "collect_geometry", walk)
        pts, _world = comp.frame_snap_points(frame)
        assert len(pts) > 0
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
