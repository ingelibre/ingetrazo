# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A mesh face-me (SketchUp's Susan: many solid-colour faces on one plane)
must give the renderer a 3-D anchor. v0.3.9 built a 2-D one and paintGL
raised IndexError on every frame — a blank viewport for any model that
carried such a figure (plaza Yanque(2).skp, 2026-09-04)."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def test_mesh_faceme_anchor_is_three_dimensional_at_the_feet():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        g = Group(Mesh(), name="Susan")
        g.billboard = True
        # two coloured faces standing in the XZ plane, feet at z = 0.4
        f1 = g.mesh.add_face([V(1, 2, 0.4), V(2, 2, 0.4), V(2, 2, 1.4), V(1, 2, 1.4)])
        f2 = g.mesh.add_face([V(1.2, 2, 1.4), V(1.8, 2, 1.4), V(1.8, 2, 2.0), V(1.2, 2, 2.0)])
        f1.attrs["color"] = (0.5, 0.5, 0.5)
        f2.attrs["color"] = (0.9, 0.7, 0.6)
        vp.scene.groups.append(g)
        base = vp._faceme_base(g)
        if base is None:
            pytest.skip("face-me base unavailable offscreen")
        arrays, colors, anchor, nh = base
        assert len(anchor) == 3
        assert abs(anchor[0] - 1.5) < 1e-6 and abs(anchor[1] - 2.0) < 1e-6
        assert abs(anchor[2] - 0.4) < 1e-6                 # the feet
        assert abs(abs(nh[1]) - 1.0) < 1e-6                # faces +/-Y
    finally:
        win._saved_version = vp.scene.version
        win.close()
