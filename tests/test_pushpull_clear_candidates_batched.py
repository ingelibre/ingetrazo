# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull's mid-drag references ask whether each candidate corner is
hidden (#270). Asked in blocks through ``_occluded_many`` (night of 18-11:
1 300 rays one by one were ~0.2 s of a pointer move inside a big group)
they come out the same, in the same order, as asked one by one — behind
a wall, in front of it, cut away by a section plane."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _box(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in idx])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(900, 700)
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.mark.parametrize("cut", [False, True])
@pytest.mark.parametrize("view", ["iso", "front", "top"])
def test_blocks_of_rays_say_what_one_ray_at_a_time_says(win, view, cut):
    from tools.pushpull import PushPullTool
    from core.topology import _key
    vp = win.viewport
    sc = vp.scene
    for i in range(6):
        for j in range(5):
            _box(sc.mesh, 2 * i, 2 * j, 0, 2 * i + 1.2, 2 * j + 1.1,
                 0.5 + 0.3 * ((i + j) % 4))
    sc.mesh.add_face([V(-1, 5, 0), V(13, 5, 0), V(13, 5, 3), V(-1, 5, 3)])
    sc.version += 1
    if cut:
        from core.section import SectionPlane
        sc.section_planes.append(SectionPlane(V(6, 0, 0), V(1, 0, 0),
                                              active=True))
        sc.version += 1
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-1, -1, -1), V(13, 11, 4))
    _app.processEvents()
    verts = list(sc.mesh.vertices)
    arr = np.array([[v.position.x(), v.position.y(), v.position.z()]
                    for v in verts])
    cand = np.arange(len(verts))
    exclude = {_key(verts[3].position), _key(verts[40].position)}
    tool = PushPullTool()
    batched = list(tool._clear_candidates(vp, arr, cand, exclude, verts))
    vp._occluded_many = None                    # one ray at a time
    vp._first_clear = None
    single = list(tool._clear_candidates(vp, arr, cand, exclude, verts))
    del vp._occluded_many, vp._first_clear
    assert batched == single
    assert 0 < len(single) < len(verts) - 2     # some hidden, some not


@pytest.mark.parametrize("view", ["iso", "front"])
def test_the_nearest_visible_midpoint_is_the_same(win, view):
    """``_infer_edge_midpoint``: the nearest midpoint not hidden, the
    first of equals — with every ray cast at once, as one by one."""
    from tools.pushpull import PushPullTool
    vp = win.viewport
    sc = vp.scene
    for i in range(5):
        _box(sc.mesh, 1.5 * i, 0, 0, 1.5 * i + 1, 1, 1 + 0.2 * i)
    sc.mesh.add_face([V(-1, -2, 0), V(8, -2, 0), V(8, -2, 1.5),
                      V(-1, -2, 1.5)])
    sc.version += 1
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-1, -3, -1), V(8, 2, 3))
    _app.processEvents()
    tool = PushPullTool()
    edges = list(sc.mesh.edges)
    vp._nearby_loose_edges = lambda sx, sy, radius_px: edges
    seen = 0
    for k in range(40):
        sx = vp.width() * (0.1 + 0.8 * (k % 8) / 7.0)
        sy = vp.height() * (0.25 + 0.5 * (k // 8) / 4.0)
        got = tool._infer_edge_midpoint(vp, sx, sy, 60.0, set())
        vp._occluded_many = None
        want = tool._infer_edge_midpoint(vp, sx, sy, 60.0, set())
        del vp._occluded_many
        assert (got is None) == (want is None)
        if got is not None:
            assert (got - want).length() == 0.0
            seen += 1
    assert seen > 5
