# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A group turned about its own centre must be redrawn (Marco, 25-09).

The chunk cache recognises «unchanged» by a fingerprint whose geometric term
is a SUM of coordinates — and a turn about the centroid keeps that sum. The
rotation grips of Move (#115) always turn about the box centre, so the
viewport kept drawing the cube where it was while its box (computed from
the live vertices) showed where it is: a ghost, every time."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V


def _cube(scene):
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    p = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0),
         V(0, 0, 2), V(2, 0, 2), V(2, 2, 2), V(0, 2, 2)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    g = Group(m)
    scene.groups.append(g)
    scene.version += 1
    return g


@pytest.mark.parametrize("deg", [30.0, 90.0])
def test_turning_a_group_about_its_centre_rebuilds_its_chunk(deg):
    from core.history import RotateGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        g = _cube(vp.scene)
        before = vp._group_chunk(g)
        geometry_fp = vp._group_fp(g)
        assert before["fp"][:len(geometry_fp)] == geometry_fp
        assert before["fp"][len(geometry_fp)][0] == "paint"
        vp.history.execute(RotateGroupCommand(g, V(1, 1, 1), V(0, 0, 1), deg))
        after = vp._group_chunk(g)
        # the samples the chunk was built from are where the vertices ARE
        for i, p in after["samples"]:
            q = g.mesh.vertices[i].position
            assert (q - V(*p)).length() < 1e-5
        # and the drawn triangles moved with them
        import numpy as np
        pts = np.frombuffer(after["vcol"], dtype=np.float32).reshape(-1, 6)[:, :2]
        live = {(round(v.position.x(), 3), round(v.position.y(), 3))
                for v in g.mesh.vertices}
        drawn = {(round(float(x), 3), round(float(y), 3)) for x, y in pts}
        assert drawn <= live
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_layer_line_style_change_rebuilds_group_edge_chunk():
    from core.layers import Layer
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        group = _cube(vp.scene)
        layer = vp.scene.layer("Layer 0")
        assert layer is not None
        initial = vp._group_chunk(group)
        assert len(initial["edges"]) > 0

        layer.line_style = "dashed"
        updated = vp._group_chunk(group)
        assert len(updated["edges"]) == 0

        # A child layer inherits the line pattern, and that inherited change
        # must also invalidate chunks tagged to it.
        vp.scene.layers.append(Layer("Plans", line_style="dotted"))
        group.layer = "Walls"
        vp.scene.layers.append(Layer("Walls", parent="Plans"))
        inherited = vp._group_chunk(group)
        assert len(inherited["edges"]) == 0
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
