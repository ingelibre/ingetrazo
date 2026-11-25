# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Hidden Geometry draws a curved surface's soft edges (#1361).

The soft edges a cylinder's side or a bevel reads smooth with were never
drawn: the hidden-geometry pass took only the edges Hide put away, while
the pick, with the view on, already took the soft ones too. So turning the
view on showed nothing of a cylinder's seams, yet a click could land on one.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QVector3D

_app = QGuiApplication.instance() or QGuiApplication([])

from core.layers import Layer
from core.scene import Scene
from views.viewport import _ghost_edge_points


def _box(mesh):
    P = [QVector3D(i & 1, (i >> 1) & 1, i >> 2) for i in range(8)]
    for q in ([0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3],
              [0, 4, 6, 2], [1, 3, 7, 5]):
        mesh.add_face([P[i] for i in q])
    return mesh


def test_soft_and_hidden_edges_are_drawn_plain_ones_are_not():
    scene = Scene()
    _box(scene.mesh)
    edges = list(scene.mesh.edges)
    assert len(edges) == 12
    assert len(_ghost_edge_points(scene)) == 0      # nothing soft or hidden
    edges[0].soft = True
    edges[1].soft = True
    edges[2].hidden = True
    points = _ghost_edge_points(scene)
    assert len(points) == 3 * 6                     # two soft, one hidden
    ends = {tuple(round(v, 6) for v in points[i:i + 3])
            for i in range(0, len(points), 3)}
    for e in edges[:3]:
        assert (e.a.x(), e.a.y(), e.a.z()) in ends
        assert (e.b.x(), e.b.y(), e.b.z()) in ends


def test_a_soft_edge_on_a_hidden_layer_stays_hidden():
    scene = Scene()
    _box(scene.mesh)
    edge = next(iter(scene.mesh.edges))
    edge.soft = True
    edge.layer = "Off"
    scene.layers.append(Layer("Off", visible=False))
    assert len(_ghost_edge_points(scene)) == 0
