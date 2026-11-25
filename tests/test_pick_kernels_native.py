# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The hover picks' own native kernels (Block 6a of 0.6.3) give NumPy's very
answers: a ray's test of every span box of the pick index (which boxes it
meets, from rays along the axes, from inside a box, behind the eye, up to
a reach, against boxes flat or endless or not finite) and the edge grid's
gather of the segments near a pixel (both of its regimes, the cursor on a
cell border or out of the view). Then the picks themselves — the face, the
edge, the corner and the group under the cursor, the ray's per-face
depths, the group edges' distances — at every pixel of a few views of a
field of groups with hidden, locked and coplanar ones, with the kernels on
and off. The engine's half is skipped without the module."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core import edge_grid  # noqa: E402
from core.edge_grid import EdgeGrid  # noqa: E402
from views.viewport import _support as sup  # noqa: E402

_app = QApplication.instance() or QApplication([])
mod = _native.native
needs_native = pytest.mark.skipif(
    mod is None or not hasattr(mod, "ray_boxes_meet")
    or not hasattr(mod, "edge_grid_near"),
    reason="native module not built")


# --- The span boxes a ray meets ----------------------------------------------

def _boxes(rng, n):
    c = rng.normal(size=(n, 3)) * 10.0 ** rng.uniform(-2, 3, (n, 1))
    half = np.abs(rng.normal(size=(n, 3))) * 10.0 ** rng.uniform(-3, 2, (n, 1))
    lo, hi = c - half, c + half
    k = n // 8
    lo[:k] = np.round(lo[:k])                  # on whole units, as the rays
    hi[:k] = np.round(hi[:k]) + 1.0
    hi[k:2 * k, 2] = lo[k:2 * k, 2]            # flat in z: a face's span
    hi[2 * k:2 * k + 10, 0] = lo[2 * k:2 * k + 10, 0]   # flat in x
    lo[2 * k + 10:2 * k + 20] = -np.inf        # unboxed spans
    hi[2 * k + 10:2 * k + 20] = np.inf
    lo[2 * k + 20, 0] = np.nan                 # not finite, every way
    hi[2 * k + 21, 1] = np.nan
    lo[2 * k + 22, 2] = np.inf
    hi[2 * k + 23, 0] = -np.inf
    lo[2 * k + 24:2 * k + 30] = hi[2 * k + 24:2 * k + 30]   # points
    return lo, hi


def _rays(rng):
    out = []
    for _ in range(12):
        o = rng.normal(size=3) * 10.0 ** rng.uniform(-1, 2)
        d = rng.normal(size=3)
        out.append((o, d / np.linalg.norm(d)))
    for axis in range(3):                      # the standard views' rays
        for sign in (1.0, -1.0):
            d = np.zeros(3)
            d[axis] = sign
            o = np.round(rng.normal(size=3) * 5.0)
            out.append((o, d))
    tiny = np.array([1e-13, -1e-12, 1.0])      # under the 1e-12 cut, and on it
    out.append((np.array([0.5, 0.5, -40.0]), tiny))
    out.append((np.zeros(3), np.array([-0.0, 0.0, -1.0])))
    return out


@needs_native
@pytest.mark.parametrize("seed", range(4))
def test_the_boxes_a_ray_meets_are_numpys(seed):
    rng = np.random.default_rng(seed)
    lo, hi = _boxes(rng, [400, 2000, 65, 9000][seed])
    for o, d in _rays(rng):
        # A ray from inside a box and one from its corner, too.
        for oo in (o, (lo[3] + hi[3]) * 0.5, lo[4].copy()):
            for reach in (None, 0.0, 1e-9, 3.5, 1e300, float("inf")):
                with np.errstate(all="ignore"):
                    want = sup._boxes_meet_numpy(oo, d, lo, hi, reach)
                got = sup._boxes_meet_native(oo, d, lo, hi, reach)
                assert got is not None
                assert got.dtype == want.dtype
                assert np.array_equal(got, want), (seed, oo, d, reach)


@needs_native
def test_a_ray_along_an_axis_meets_a_flat_box_on_its_plane():
    # tmin == tmax for a box flat across the ray: a meeting, as NumPy's >=.
    lo = np.array([[0.0, 0.0, 2.0], [0.0, 0.0, -2.0], [5.0, 5.0, 2.0]])
    hi = np.array([[1.0, 1.0, 2.0], [1.0, 1.0, -2.0], [6.0, 6.0, 2.0]])
    o, d = np.array([0.5, 0.5, 0.0]), np.array([0.0, 0.0, 1.0])
    got = sup._boxes_meet_native(o, d, lo, hi)
    assert got.tolist() == [0] == sup._boxes_meet_numpy(o, d, lo, hi).tolist()
    # On the box's very border, and at the reach's very end.
    o = np.array([1.0, 0.0, 0.0])
    for reach in (2.0, np.nextafter(2.0, 0.0)):
        assert (sup._boxes_meet_native(o, d, lo, hi, reach).tolist()
                == sup._boxes_meet_numpy(o, d, lo, hi, reach).tolist())


@needs_native
def test_the_box_test_refuses_what_it_cannot_read():
    o, d = np.zeros(3), np.array([0.0, 0.0, 1.0])
    lo = np.zeros((4, 3), np.float32)
    assert sup._boxes_meet_native(o, d, lo, lo + 1) is None
    lo = np.zeros((4, 2))
    assert sup._boxes_meet_native(o, d, lo, lo + 1) is None
    lo = np.zeros((4, 6))[:, ::2]               # not contiguous: copied
    assert sup._boxes_meet_native(o, d, lo, lo + 1).tolist() == [0, 1, 2, 3]


def test_without_the_switch_the_box_test_stays_in_numpy(monkeypatch):
    monkeypatch.setattr(sup, "_PICK_NATIVE", False)
    o, d = np.zeros(3), np.array([0.0, 0.0, 1.0])
    assert sup._boxes_meet_native(o, d, np.zeros((2, 3)), np.ones((2, 3))) is None


# --- The edge grid's gather --------------------------------------------------

def _segments(rng, n, w, h, longest=3.2):
    ax = rng.uniform(-200, w + 200, n)
    ay = rng.uniform(-200, h + 200, n)
    ln = 10.0 ** rng.uniform(-1, longest, n)
    ang = rng.uniform(0, 2 * np.pi, n)
    bx, by = ax + ln * np.cos(ang), ay + ln * np.sin(ang)
    k = n // 10
    ax[:k] = np.round(ax[:k] / 32.0) * 32.0          # on cell borders
    by[k:2 * k] = ay[k:2 * k]
    bx[2 * k:3 * k] = ax[2 * k:3 * k]
    ok = rng.random(n) < 0.92
    return ax, ay, bx, by, ok


def _near_both(grid, px, py, reach, monkeypatch):
    got = grid.near(px, py, reach)
    with monkeypatch.context() as m:
        m.setattr(edge_grid, "_GRID_NATIVE", False)
        want = grid.near(px, py, reach)
    return got, want


@needs_native
@pytest.mark.parametrize("seed", range(4))
def test_the_segments_near_a_pixel_are_numpys(seed, monkeypatch):
    rng = np.random.default_rng(seed)
    w, h = [(900.0, 640.0), (1400.0, 900.0), (31.0, 17.0), (900.0, 640.0)][seed]
    n = [5000, 40000, 300, 1][seed]
    # Short ones on the big view: few long ones, so a small reach meets
    # few segments (the sort) and a big one many (the mask).
    ax, ay, bx, by, ok = _segments(rng, n, w, h, 1.5 if seed == 1 else 3.2)
    if seed == 1:
        # A dense knot (an imported part far off): thousands of segments in
        # a few cells, past near's 1/16 of all of them.
        ax[:4000] = rng.uniform(690, 730, 4000)
        ay[:4000] = rng.uniform(440, 470, 4000)
        bx[:4000], by[:4000] = ax[:4000] + 3.0, ay[:4000] - 2.0
    grid = EdgeGrid(ax, ay, bx, by, ok, w, h, 48.0)
    pts = [(rng.uniform(0, w), rng.uniform(0, h)) for _ in range(60)]
    pts += [(0.0, 0.0), (w, h), (32.0, 64.0), (w / 2, h / 2),
            (-1.0, 5.0), (w + 1.0, 5.0)]            # out of the view: None
    regimes = set()
    for px, py in pts:
        for reach in (None, 8.0, 48.0, 0.0, 500.0):
            got, want = _near_both(grid, px, py, reach, monkeypatch)
            if want is None:
                assert got is None
                continue
            assert got.dtype == want.dtype
            assert np.array_equal(got, want), (seed, px, py, reach)
            regimes.add(len(want) * 16 < grid.n)
    if seed == 1:
        assert regimes == {True, False}             # both of near's regimes


# --- The picks of a hover ----------------------------------------------------

def _sheet(mesh, n, at=(0.0, 0.0, 0.0), step=1.0):
    ox, oy, oz = at
    for i in range(n):
        for j in range(n):
            z = oz + 0.25 * math.sin(i * 0.7) * math.cos(j * 0.4)
            x0, y0 = ox + i * step, oy + j * step
            mesh.add_face([V(x0, y0, z), V(x0 + step, y0, z),
                           V(x0 + step, y0 + step, z), V(x0, y0 + step, z)])


def _box(mesh, x0, y0, z0, s):
    p = [V(x0, y0, z0), V(x0 + s, y0, z0), V(x0 + s, y0 + s, z0),
         V(x0, y0 + s, z0)]
    q = [v + V(0, 0, s) for v in p]
    mesh.add_face([p[0], p[3], p[2], p[1]])
    mesh.add_face(q)
    for k in range(4):
        a, b = p[k], p[(k + 1) % 4]
        mesh.add_face([a, b, b + V(0, 0, s), a + V(0, 0, s)])


def _window():
    """A field of 90 placements (more span boxes than the slab test's 64),
    one hidden, one locked, two coplanar sheets one over the other, and a
    loose sheet."""
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(700, 500)
    sc = vp.scene
    sc.clear()
    sheet = Mesh()
    _sheet(sheet, 4, step=0.5)
    cube = Mesh()
    _box(cube, 0.0, 0.0, 0.0, 1.2)
    for i in range(10):
        for j in range(9):
            g = Group(cube if (i + j) % 2 else sheet, name=f"G{i}{j}")
            m = QMatrix4x4()
            m.translate(3.0 * i, 3.0 * j, 0.1 * (i - j))
            m.rotate(9.0 * i + 4.0 * j, 0.0, 0.0, 1.0)
            if (i * j) % 7 == 3:
                m.scale(-1.0, 1.0, 1.0)              # mirrored
            g.xform = m
            sc.groups.append(g)
    sc.groups[11].hidden = True
    sc.groups[23].locked = True
    for k, dz in enumerate((0.0, 0.0)):              # coplanar, overlapping
        g = Group(sheet, name=f"Cop{k}")
        m = QMatrix4x4()
        m.translate(10.0 + 0.5 * k, -5.0, 0.3 + dz)
        g.xform = m
        sc.groups.append(g)
    _sheet(sc.mesh, 10, at=(-6.0, -6.0, -0.5), step=0.9)
    sc.version += 1
    win._activate_tool("line")
    return win, vp


VIEWS = ((30.0, 35.0, True, 45.0), (200.0, 20.0, True, 30.0),
         (0.0, 89.9, False, 40.0), (0.0, 0.0, False, 40.0),
         (135.0, -30.0, True, 20.0))


def _set_view(vp, view):
    yaw, pitch, persp, dist = view
    cam = vp.camera
    cam.perspective = persp
    cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)
    cam.target = V(13.0, 12.0, 0.5)
    cam.distance = dist


def _key(p):
    return None if p is None else (p.x(), p.y(), p.z())


def _fkey(f):
    if f is None:
        return None
    return tuple(_key(v) for v in f.vertices)


def _ekey(e):
    return None if e is None else (_key(e.a), _key(e.b),
                                   bool(getattr(e, "in_group", False)))


def _bits(a):
    if a is None:
        return None
    a = np.asarray(a, dtype=np.float64)
    return np.where(np.isnan(a), np.nan, a).tobytes()


def _answers(vp, x, y):
    from views.viewport import Viewport
    vp._tick = getattr(vp, "_tick", 0) + 1
    vp._last_mouse_pos = None
    face, owner = vp.pick_face_any(x, y)
    inf_face, inf_place = vp.pick_face_inference(x, y)
    grp = vp.pick_group(x, y)
    o, d = vp._pixel_to_ray(x, y)
    idx = vp._pick_index(near="skip")
    ray = (None if o is None else
           Viewport._ray_hits(vp, idx, o, d, idx.ent_sel))
    reach = (None if o is None else
             Viewport._ray_hits(vp, idx, o, d, idx.ent_vis, reach=12.5))
    return (_fkey(face), getattr(owner, "name", None),
            _fkey(inf_face), getattr(inf_place, "name", None),
            getattr(grp, "name", None), _bits(ray), _bits(reach),
            _ekey(vp.pick_edge_any(x, y)), _ekey(vp.pick_edge(x, y)),
            _ekey(vp.pick_visible_edge(x, y)),
            _bits(vp._gedge_dist(x, y)), _key(vp.pick_vertex(x, y)))


@pytest.fixture
def pair(monkeypatch):
    from views.viewport import Viewport
    # The group edges through the screen grid, as on a big model.
    monkeypatch.setattr(Viewport, "GEDGE_GRID_MIN", 100)
    a, va = _window()
    b, vb = _window()
    try:
        yield va, vb
    finally:
        for w in (a, b):
            w._saved_version = w.viewport.scene.version
            w.close()


@needs_native
@pytest.mark.parametrize("view", VIEWS)
def test_the_picks_under_the_cursor_are_pythons(pair, view, monkeypatch):
    va, vb = pair
    _set_view(va, view)
    _set_view(vb, view)
    w, h = va.width(), va.height()
    hits = faces = 0
    calls = {"meet": 0, "near": 0}

    def counted(name):
        real = getattr(mod, name)

        def call(*a, **k):
            calls[name.split("_")[-1]] += 1
            return real(*a, **k)
        return call
    monkeypatch.setattr(mod, "ray_boxes_meet", counted("ray_boxes_meet"))
    monkeypatch.setattr(mod, "edge_grid_near", counted("edge_grid_near"))
    for gx in range(0, 23):
        for gy in range(0, 17):
            x, y = 3.0 + gx * (w - 6.0) / 22.0, 3.0 + gy * (h - 6.0) / 16.0
            # Twice: the group edges' grid waits for the second hover.
            for _ in range(2):
                got = _answers(va, x, y)
                with monkeypatch.context() as m:
                    m.setattr(sup, "_PICK_NATIVE", False)
                    m.setattr(edge_grid, "_GRID_NATIVE", False)
                    m.setattr(edge_grid, "NATIVE_MIN", 10 ** 12)
                    want = _answers(vb, x, y)
                assert got == want, (view, x, y)
            hits += got[7] is not None
            faces += got[0] is not None
    # The views do look at the field, through the kernels.
    assert hits > 5 and faces > 10
    assert len(va._pick_index(near="skip").tri_spans) > 64
    assert calls["meet"] > 0 and calls["near"] > 0


def test_the_picks_answer_without_the_engine(pair, monkeypatch):
    # Python alone (the engine off) answers what the kernels' fallback does.
    va, vb = pair
    monkeypatch.setattr(_native, "native", None)
    _set_view(va, VIEWS[0])
    _set_view(vb, VIEWS[0])
    for x, y in ((350.0, 250.0), (120.0, 400.0), (600.0, 90.0)):
        got = _answers(va, x, y)
        with monkeypatch.context() as m:
            m.setattr(sup, "_PICK_NATIVE", False)
            m.setattr(edge_grid, "_GRID_NATIVE", False)
            want = _answers(vb, x, y)
        assert got == want
