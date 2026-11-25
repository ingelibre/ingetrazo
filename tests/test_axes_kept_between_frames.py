# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The drawing axes are built and uploaded once per spacing and context.

Every frame used to build the 3 × 520 dashes of the axes in a Python loop
and upload them again, ~1 ms of each frame of an orbit on a large plaza,
while an orbit or a pan keeps the camera distance the dashes follow.

* ``_axes_vertices`` builds the dashes in numpy: the bytes are the ones
  the loop wrote, world axes and a turned group's alike.
* A frame whose spacing and drawing axes are the last frame's keeps the
  buffer; a zoom (another spacing) or another context (a group's own axes)
  builds it again, and the picture is the one a fresh build draws.

The GL part needs a context that renders; it is skipped where there is
none (run with QT_QPA_PLATFORM=xcb or wayland)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from array import array  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core import axes  # noqa: E402


def _loop_axes_vertices(spacing, pos_len=1.0e5):
    """The axes as the per-dash Python loop built them."""
    from views.viewport._support import _AXIS_DIRS
    coords = array("f")
    spans = {}
    spacing = max(spacing, 1e-4)
    dash = spacing * 0.18
    n = 520
    o = axes.ORIGIN
    ox, oy, oz = o.x(), o.y(), o.z()
    for name in ("x", "y", "z"):
        if axes.is_world():
            dx, dy, dz = _AXIS_DIRS[name]
        else:
            dx, dy, dz = axes.as_tuple(name)
        start = len(coords) // 3
        coords.extend([ox, oy, oz, ox + dx * pos_len, oy + dy * pos_len,
                       oz + dz * pos_len])
        for k in range(n):
            t0 = k * spacing
            t1 = t0 + dash
            coords.extend([ox - dx * t0, oy - dy * t0, oz - dz * t0,
                           ox - dx * t1, oy - dy * t1, oz - dz * t1])
        spans[name] = (start, len(coords) // 3 - start)
    return coords, spans


def _turned_frame():
    m = QMatrix4x4()
    m.translate(2.37, -1.11, 0.73)
    m.rotate(31.7, 0.2, 0.3, 1.0)
    return m


SPACINGS = (1e-7, 1e-4, 0.000731, 0.0123, 0.08, 0.3333333, 1.7,
            12.345678, 345.6789, 9876.54321)


@pytest.mark.parametrize("frame", [None, "turned"])
def test_the_dashes_are_the_bytes_the_loop_wrote(frame):
    from views.viewport._support import _axes_vertices
    axes.sync(_turned_frame() if frame else None)
    try:
        for s in SPACINGS:
            got, spans = _axes_vertices(s)
            want, wspans = _loop_axes_vertices(s)
            assert isinstance(got, array) and got.typecode == "f"
            assert spans == wspans
            assert got.tobytes() == want.tobytes(), f"spacing {s}"
    finally:
        axes.sync(None)


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
    w.resize(900, 650)
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    yield w
    axes.sync(None)
    w._saved_version = vp.scene.version
    w._saved_content = getattr(vp.scene, "content_version", None)
    w.close()


def _frame(vp):
    return vp.grabFramebuffer()


def _fresh_frame(vp):
    """The frame drawn whole with the axes built anew (no kept picture)."""
    vp._axes_key = None
    vp._frame_cache = None
    return vp.grabFramebuffer()


def test_an_orbit_keeps_the_axes_a_zoom_or_a_group_builds_them(win, monkeypatch):
    from core.group import Group
    from core.mesh import Mesh
    from views.viewport import render
    vp = win.viewport
    sc = vp.scene
    _box(sc.mesh, -1, -1, 0, 1, 1, 1.5)
    m = Mesh()
    _box(m, 0, 0, 0, 1, 1, 1)
    g = Group(m, name="turned")
    g.axes = _turned_frame()
    sc.groups.append(g)
    sc.version += 1
    built = []
    real = render._axes_vertices

    def counting(spacing, *a, **k):
        built.append(spacing)
        return real(spacing, *a, **k)
    monkeypatch.setattr(render, "_axes_vertices", counting)

    vp._axes_key = None                       # the window drew them already
    _frame(vp)
    assert built, "the first frame builds the axes"
    n = len(built)
    cam = vp.camera
    for _k in range(4):                       # an orbit: same distance
        cam.yaw += 0.05
        _frame(vp)
    assert len(built) == n, "an orbit built the axes again"
    kept = _frame(vp)
    fresh = _fresh_frame(vp)                  # what a fresh build draws
    assert len(built) == n + 1
    assert kept == fresh, "the kept axes do not draw as a fresh build"

    cam.distance *= 1.37                      # a zoom: another spacing
    _frame(vp)
    assert len(built) == n + 2, "a zoom kept the dashes of the last spacing"

    n = len(built)
    vp.begin_group_edit(g)                    # the group's own axes
    _app.processEvents()
    _frame(vp)
    assert len(built) > n, "the group's axes were not built"
    assert not axes.is_world()
    kept = _frame(vp)
    assert kept == _fresh_frame(vp)

    n = len(built)
    vp.end_group_edit()                       # back to the world's
    _app.processEvents()
    _frame(vp)
    assert len(built) > n, "leaving the group kept the group's axes"
    assert axes.is_world()
    kept = _frame(vp)
    assert kept == _fresh_frame(vp)
