# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A sheet frame whose scene switches on a layer the live model hides —
the upper floor's plan while the model shows the attic — snaps to that
layer's geometry. The snap set used to be collected with the LIVE model's
layers only, so nothing on such a sheet snapped (a user's file: every
wall corner of «Grundriss_OG»)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.layers import Layer
from core.saved_views import SavedView

_app = QApplication.instance() or QApplication([])


def _box(scene, layer):
    """A 6 × 2 × 3 m box as a GROUP on *layer* — how a BIM file's walls
    arrive; the viewport's fast geometry takes groups from its pick index,
    which knows only the live model's layers."""
    from core.group import Group
    from core.mesh import Mesh
    group = Group(Mesh(), name="Wand")
    group.layer = layer
    mesh = group.mesh
    p = [V(0, 0, 0), V(6, 0, 0), V(6, 2, 0), V(0, 2, 0),
         V(0, 0, 3), V(6, 0, 3), V(6, 2, 3), V(0, 2, 3)]
    for f in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
              (4, 5, 6, 7), (3, 2, 1, 0)):
        mesh.add_face([p[i] for i in f])
    scene.groups.append(group)


def test_a_frame_snaps_to_a_layer_only_its_scene_shows():
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        scene = win.viewport.scene
        scene.layers.append(Layer("OG", visible=False))   # off in the model
        _box(scene, "OG")
        scene.saved_views.append(SavedView(
            "Plan OG", target=(3.0, 1.0, 1.5), distance=20.0, yaw=0.0,
            pitch=0.0, perspective=False, hidden_layers=[]))
        comp = ComposerWindow(win)
        comp._auto_render = False
        frame = comp.comp.frames[0]
        frame.view_key = "scene:Plan OG"
        comp._invalidate_geometry_caches()
        pts, world = comp.frame_snap_points(frame)
        assert len(pts) > 0                       # the box's corners
        hit = comp.nearest_snap_point(float(pts[0][0]), float(pts[0][1]), 1.0)
        assert hit is not None and hit[3] is frame
        # the live model is left as it was
        assert not next(ly for ly in scene.layers if ly.name == "OG").visible
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
