# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pick index takes component placements lazily on a big model (issue
#158): only those near the query are baked, under a cap. Here the threshold
is lowered so a small scene runs in that mode, and every answer is compared
with the ordinary index."""
from __future__ import annotations

import math
import sys

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _cube():
    from core.mesh import Mesh
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    return m


@pytest.fixture
def vp():
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    v = win.viewport
    v.resize(1000, 700)
    v.scene.guides.clear()
    proto = _cube()
    for i in range(6):
        for j in range(4):
            g = Group(proto, name=f"C{i}{j}")
            m = QMatrix4x4()
            m.translate(3.0 * i, 3.0 * j, 0.0)
            if (i + j) % 3 == 0:
                m.scale(-1.0, 1.0, 1.0)              # some mirrored
            g.xform = m
            v.scene.groups.append(g)
    v.scene.version += 1
    v.camera.set_view("top")
    v.camera.perspective = False
    v.camera.fit_to(V(-2, -2, 0), V(18, 12, 1))
    try:
        yield v
    finally:
        win._saved_version = v.scene.version
        win.close()


def _lazy(v, on, cap=None):
    v._PICK_LAZY_MIN_FACES = 1 if on else 10 ** 12
    if cap is not None:
        v._PICK_LIVE_MAX_FACES = cap
    v._pick_index_cache = None
    v._pick_block = None
    v._pick_lazy_memo = None
    v._pick_near_memo = None
    v._pick_live = None
    getattr(v, "_inst_chunks", {}).clear()
    v._hover_hits_cache = None


def _centre(v, name):
    g = next(g for g in v.scene.groups if g.name == name)
    c = g.xform.map(V(0.5, 0.5, 1.0))
    return V(c.x(), c.y(), 1.0)


def _answers(v, pts):
    out = []
    for p in pts:
        x, y = v._world_to_pixel(p)
        f, pl = v.pick_face_placement(x, y)
        g = v.pick_group(x, y)
        where = None
        if f is not None:
            c = f.centroid()
            if pl is not None and getattr(pl, "xform", None) is not None:
                c = pl.xform.map(c)
            where = (round(c.x(), 4), round(c.y(), 4), round(c.z(), 4))
        out.append((where, g.name if g is not None else None))
    return out


def test_lazy_answers_equal_the_full_index(vp):
    pts = [_centre(vp, f"C{i}{j}") for i in range(6) for j in range(4)]
    pts += [V(1.5, 1.5, 0.0), V(-1.0, -1.0, 0.0)]           # gaps
    _lazy(vp, False)
    full = _answers(vp, pts)
    _lazy(vp, True)
    lazy = _answers(vp, pts)
    assert lazy == full


def test_only_the_placements_near_the_cursor_are_baked(vp):
    _lazy(vp, True)
    x, y = vp._world_to_pixel(_centre(vp, "C10"))
    vp.pick_face_any(x, y)
    live = vp._pick_live
    assert 0 < len(live) < 24
    baked = [k for k in getattr(vp, "_inst_chunks", {})]
    assert len(baked) <= len(live)


def test_the_cap_lets_old_ones_go(vp):
    _lazy(vp, True, cap=12)                   # two cubes' worth of faces
    for i in range(6):
        x, y = vp._world_to_pixel(_centre(vp, f"C{i}0"))
        assert vp.pick_group(x, y).name == f"C{i}0"
    assert sum(n for _g, n in vp._pick_live.values()) <= 12 + 6


def test_everything_when_the_whole_model_is_asked_for(vp):
    _lazy(vp, True)
    vp._pick_index(near="all")
    assert len(vp._pick_live) == 24


def test_a_ray_bakes_what_it_crosses(vp):
    _lazy(vp, True)
    c = _centre(vp, "C21")
    d = vp.ray_distance(V(c.x(), c.y(), 10.0), V(0, 0, -1))
    assert d == pytest.approx(9.0, abs=1e-5)                 # top of C21


def _near_edges(v, x, y):
    got = v._nearby_group_edges(x, y) or []
    return sorted((round(e.a.x(), 4), round(e.a.y(), 4), round(e.a.z(), 4),
                   round(e.b.x(), 4), round(e.b.y(), 4), round(e.b.z(), 4))
                  for e in got)


def test_the_edges_near_the_cursor_for_the_snap_are_the_same(vp):
    probes = [_centre(vp, n) for n in ("C00", "C21", "C53")]
    probes = [V(p.x() + 0.45, p.y(), 1.0) for p in probes]  # near an edge
    _lazy(vp, False)
    full = [_near_edges(vp, *vp._world_to_pixel(p)) for p in probes]
    _lazy(vp, True)
    lazy = [_near_edges(vp, *vp._world_to_pixel(p)) for p in probes]
    assert lazy == full and all(full)


def test_occlusion_is_the_same(vp):
    vp.camera.set_view("iso") if hasattr(vp.camera, "set_view") else None
    vp.camera.fit_to(V(-2, -2, 0), V(18, 12, 1))
    probes = []
    for n in ("C10", "C32", "C43"):
        c = _centre(vp, n)
        probes += [V(c.x(), c.y(), 0.0), V(c.x(), c.y(), 1.0),
                   V(c.x() + 0.5, c.y() + 0.5, 0.5)]
    def run():
        out = []
        for p in probes:
            vp._last_mouse_pos = None
            from PySide6.QtCore import QPointF
            vp._last_mouse_pos = QPointF(*vp._world_to_pixel(p))
            out.append(vp._is_occluded(p))
        return out
    _lazy(vp, False)
    full = run()
    _lazy(vp, True)
    assert run() == full


def test_with_a_frame_on_screen_the_depth_cull_changes_no_answer(vp):
    """With a painted frame the lazy mode also leaves out placements wholly
    behind what the screen shows; picks and snap edges stay the same."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.platformName() == "offscreen":
        # The offscreen platform opens a compatibility-profile context whose
        # instanced draw of many placements crashes in the driver (it did
        # before 0.5.7 too; xcb, hardware or llvmpipe, draws them fine).
        pytest.skip("instanced draw needs a real window platform")
    win = vp.window()
    win.show()
    for _ in range(10):
        QApplication.processEvents()
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    vp.camera.set_view("iso") if hasattr(vp.camera, "set_view") else None
    vp.camera.fit_to(V(-2, -2, 0), V(18, 12, 1))
    vp.grabFramebuffer()
    if vp._depth_world_at(10, 10) is None:
        pytest.skip("this GL context gives no depth read-back")
    pts = [_centre(vp, f"C{i}{j}") for i in range(6) for j in range(4)]
    _lazy(vp, False)
    full = _answers(vp, pts)
    full_e = [_near_edges(vp, *vp._world_to_pixel(p)) for p in pts[:6]]
    _lazy(vp, True)
    assert _answers(vp, pts) == full
    assert [_near_edges(vp, *vp._world_to_pixel(p)) for p in pts[:6]] == full_e
