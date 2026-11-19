# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pick index's ray pass in the native engine gives NumPy's answers,
bit for bit (Block 6 of 0.6.3, 6f): ``_moller_trumbore`` row by row (t of
every row, hit or not), the per-entity minima and the global minimum of
``Viewport._ray_hits`` — over random triangles aimed at the ray, edges and
corners hit exactly, grazing, tiny, degenerate and collinear triangles,
NaN and infinity, one row and many — and in a real view: every face a ray
meets and every occlusion answer over a grid of pixels, with the engine
and without it. The engine sums its dot products in the modes the first
use found for this NumPy (``_mt_native``); a pass that differs on a live
ray turns it off for the session. The engine's half is skipped without
the module."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from views import viewport as vv  # noqa: E402
from views.viewport import Viewport  # noqa: E402

_app = QApplication.instance() or QApplication([])
mod = _native.native
needs_native = pytest.mark.skipif(
    mod is None or not hasattr(mod, "ray_face_min"),
    reason="native module not built")


def _same(a, b) -> bool:
    return vv._mt_same(a, b)


class _Counting:
    """The engine, counting the passes it answers."""
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        return getattr(mod, name)

    def ray_face_min(self, *a, **k):
        self.calls += 1
        return mod.ray_face_min(*a, **k)


def _counted(monkeypatch):
    spy = _Counting()
    monkeypatch.setattr(vv, "_MT_NATIVE", (spy, vv._MT_NATIVE[1]))
    return spy


@pytest.fixture
def modes(monkeypatch):
    """The engine on, past its trial: it answers alone."""
    monkeypatch.setattr(vv, "_MT_NATIVE", None)
    monkeypatch.setattr(vv, "_MT_SHADOW", [0])
    monkeypatch.setattr(vv, "_MT_NATIVE_ON", True)
    nat = vv._mt_native()
    assert nat is not None, "the ray pass found no mode for this NumPy"
    return nat[1]


def _tris(rng, n, o, d):
    """Triangles aimed at the ray ``o`` + t·``d``, with every special case."""
    size = 10.0 ** rng.uniform(-4, 3, (n, 1))
    e1 = rng.normal(size=(n, 3)) * size
    e2 = rng.normal(size=(n, 3)) * size
    t = rng.uniform(-5.0, 80.0, (n, 1))
    u = rng.uniform(-0.2, 1.2, (n, 1))
    v = rng.uniform(-0.2, 1.2, (n, 1)) * (1.0 - u)
    u[::5] = 0.0
    v[2::5] = 0.0
    v[4::5] = 1.0 - u[4::5]
    u[1::11], v[1::11] = 1.0, 0.0
    v0 = o + t * d - u * e1 - v * e2
    v0[::13] = np.round(v0[::13] * 8) / 8
    k = max(1, n // 10)
    e2[:k] = (e1[:k] * rng.uniform(-2, 2, (k, 1))
              + np.cross(e1[:k], d) * 10.0 ** rng.uniform(-12, -6, (k, 1)))
    if n > k + 60:
        e1[k:k + 10] = 0.0
        e2[k + 10:k + 20] = e1[k + 10:k + 20] * -2.0
        e1[k + 20:k + 40] = np.array([1e-3, 0.0, 0.0])
        e2[k + 20:k + 40] = np.array([0.0, 1e-3, 0.0])
        sp = (np.nan, np.inf, -np.inf, 1e300, -1e300, 0.0, -0.0, 5e-324)
        for j, val in enumerate(sp):
            v0[k + 40 + j, j % 3] = val
            e2[k + 50 + j, (j + 1) % 3] = val
    return (np.ascontiguousarray(v0), np.ascontiguousarray(e1),
            np.ascontiguousarray(e2))


def _rays(rng):
    out = []
    for _ in range(6):
        d = rng.normal(size=3)
        out.append((rng.normal(size=3) * 20.0, d / np.linalg.norm(d)))
    # Axis-aligned (the standard views), head-on onto a 1 mm square, and
    # one not of unit length.
    out += [(np.array([0.3, -0.2, 50.0]), np.array([0.0, 0.0, -1.0])),
            (np.array([2e-4, 3e-4, 1.0]), np.array([0.0, 0.0, -1.0])),
            (np.array([-40.0, 1.0, 2.0]), np.array([1.0, 0.0, 0.0])),
            (np.array([1.0, 2.0, 3.0]), np.array([0.3, -2.0, 0.7]))]
    return out


@needs_native
def test_the_modes_reproduce_numpy_dot_products(modes):
    """Each mode found reproduces its NumPy reading on fresh rows."""
    es, mm, mm1, dd, sq = modes
    for seed, n in ((7, 1), (8, 2), (9, 31), (10, 4000)):
        a, b = vv._mt_dot_sample(seed, n)
        assert _same(mod.ray_dot3_probe(a, b, es),
                     np.einsum("ij,ij->i", a, b))
        d = np.ascontiguousarray(b[0])
        dm = np.ascontiguousarray(np.broadcast_to(d, a.shape))
        if n > 1:
            assert _same(mod.ray_dot3_probe(a, dm, mm), a @ d)
        assert _same(mod.ray_dot3_probe(a[:1], dm[:1], mm1), a[:1] @ d)
        assert _same(np.sqrt(mod.ray_dot3_probe(a, a, sq)),
                     np.linalg.norm(a, axis=1))
        assert float(np.sqrt(mod.ray_dot3_probe(a[:1], a[:1], dd))[0]) \
            == float(np.linalg.norm(a[0]))


@needs_native
def test_moller_trumbore_row_by_row(modes):
    rng = np.random.default_rng(6)
    with np.errstate(all="ignore"):
        for o, d in _rays(rng):
            v0, e1, e2 = _tris(rng, 2500, o, d)
            o3, d3 = tuple(o.tolist()), tuple(d.tolist())
            for lo, hi in ((0, 0), (0, 1), (7, 8), (0, 2), (3, 6), (0, 64),
                           (100, 1100), (0, 2500)):
                a, b, c = (np.ascontiguousarray(x[lo:hi]) for x in (v0, e1, e2))
                tp, hp = vv._moller_trumbore_py(o, d, a, b, c)
                t, hit = mod.ray_tris(o3, d3, a, b, c, modes)
                assert _same(t, tp), (lo, hi)
                assert (hit == hp).all(), (lo, hi)
                # And the dispatcher hands the engine's answer.
                t2, h2 = vv._moller_trumbore(o, d, a, b, c)
                assert _same(t2, tp) and (h2 == hp).all()


@needs_native
def test_one_row_passes_on_the_edges(modes):
    """A pass of one row: NumPy's ``q @ d`` is then a BLAS dot, which may
    sum in another order than the gemv of many rows — and on a triangle
    whose edge the ray meets that last bit decides the hit."""
    rng = np.random.default_rng(26)
    seen = 0
    with np.errstate(all="ignore"):
        for o, d in _rays(rng)[:6]:
            v0, e1, e2 = _tris(rng, 1500, o, d)
            o3, d3 = tuple(o.tolist()), tuple(d.tolist())
            many_t, many_h = vv._moller_trumbore_py(o, d, v0, e1, e2)
            for r in range(len(v0)):
                a, b, c = v0[r:r + 1], e1[r:r + 1], e2[r:r + 1]
                tp, hp = vv._moller_trumbore_py(o, d, a, b, c)
                t, hit = mod.ray_tris(o3, d3, a, b, c, modes)
                assert _same(t, tp) and hit[0] == hp[0], r
                seen += int(hp[0] != many_h[r])
    # The sample does reach rows where one row and many part ways.
    assert seen > 0


@needs_native
def test_built_in_modes_are_the_run_time_ones():
    """The kernel builds the modes NumPy was seen to use into its code and
    reads any other at run time: both give the same bits, every mode."""
    rng = np.random.default_rng(36)
    o, d = rng.normal(size=3), rng.normal(size=3)
    with np.errstate(all="ignore"):
        v0, e1, e2 = _tris(rng, 400, o, d / np.linalg.norm(d))
    o3, d3 = tuple(o.tolist()), tuple((d / np.linalg.norm(d)).tolist())
    for es in range(48):
        for mm in range(48):
            for m in ((es, mm, 3, 3, 0), (es, 0, mm, 27, 24)):
                for rows in (slice(None), slice(5, 6)):
                    a, b, c = (np.ascontiguousarray(x[rows])
                               for x in (v0, e1, e2))
                    t1, h1 = mod.ray_tris(o3, d3, a, b, c, m)
                    t2, h2 = mod.ray_tris(o3, d3, a, b, c, m, dynamic=True)
                    assert _same(t1, t2) and (h1 == h2).all(), m


@needs_native
def test_per_entity_and_global_minima(modes):
    rng = np.random.default_rng(16)
    with np.errstate(all="ignore"):
        for o, d in _rays(rng):
            v0, e1, e2 = _tris(rng, 3000, o, d)
            te = np.sort(rng.integers(0, 700, len(v0))).astype(np.int64)
            off = 5
            mask = rng.random(705) < 0.8
            o3, d3 = tuple(o.tolist()), tuple(d.tolist())
            for rows in (None, np.sort(rng.choice(3000, 900, replace=False)),
                         np.array([17]), np.empty(0, np.int64)):
                sel = slice(None) if rows is None else rows
                t, hit = vv._moller_trumbore_py(o, d, v0[sel], e1[sel],
                                                e2[sel])
                ents = te[sel] + off
                hit &= mask[ents]
                want = np.full(len(mask), np.inf)
                hr = np.where(hit)[0]
                np.minimum.at(want, ents[hr], t[hr])
                got = np.full(len(mask), np.inf)
                r = (None if rows is None
                     else np.ascontiguousarray(rows, np.int64))
                mod.ray_face_min(o3, d3, v0, e1, e2, te, off, mask, modes,
                                 rows=r, face_t=got)
                assert _same(got, want)
                g = mod.ray_face_min(o3, d3, v0, e1, e2, te, off, mask, modes,
                                     rows=r, best=12.5)
                th = t[hit]
                wg = 12.5 if not len(th) else min(12.5, float(th.min()))
                assert g == wg
            # Ranges: the same rows as their concatenation, as ONE pass.
            rg = np.array([[0, 1], [40, 0], [100, 300], [2000, 999]],
                          np.int64)
            rows = np.concatenate([np.arange(s, s + n) for s, n in rg])
            t, hit = vv._moller_trumbore_py(o, d, v0[rows], e1[rows],
                                            e2[rows])
            hit &= mask[te[rows] + off]
            want = np.full(len(mask), np.inf)
            hr = np.where(hit)[0]
            np.minimum.at(want, te[rows][hr] + off, t[hr])
            got = np.full(len(mask), np.inf)
            mod.ray_face_min(o3, d3, v0, e1, e2, te, off, mask, modes,
                             ranges=rg, face_t=got)
            assert _same(got, want)


@needs_native
def test_out_of_range_rows_and_entities_are_refused():
    v0 = np.zeros((4, 3))
    te = np.arange(4, dtype=np.int64)
    m = (28, 35, 27, 3, 0)
    with pytest.raises(ValueError):
        mod.ray_face_min((0, 0, 1), (0, 0, -1), v0, v0, v0, te, 0,
                         np.ones(3, bool), m)          # entity 3 of 3
    with pytest.raises(ValueError):
        mod.ray_face_min((0, 0, 1), (0, 0, -1), v0, v0, v0, te, 0,
                         np.ones(4, bool), m, rows=np.array([4]))
    with pytest.raises(ValueError):
        mod.ray_face_min((0, 0, 1), (0, 0, -1), v0, v0, v0, te, -1,
                         np.ones(4, bool), m)          # entity -1
    with pytest.raises(ValueError):
        mod.ray_tris((0, 0, 1), (0, 0, -1), v0, v0, v0, (48, 0, 0, 0, 0))


def _stub_index(rng, n_span=90, per=40, n_own=3):
    """A bare pick index: ``n_span`` boxed spans (past 64: the vectorised
    box test) and lazy placements' own spans."""
    from types import SimpleNamespace
    o = np.array([0.5, -0.3, 30.0])
    d = np.array([0.01, 0.02, -1.0])
    d /= np.linalg.norm(d)
    n = n_span * per
    v0, e1, e2 = _tris(rng, n, o, d)
    te = (np.arange(n) // 2).astype(np.int64)
    spans = []
    for s in range(n_span):
        rows = slice(s * per, (s + 1) * per)
        pts = np.concatenate([v0[rows], v0[rows] + e1[rows],
                              v0[rows] + e2[rows]])
        with np.errstate(invalid="ignore"):
            lo, hi = np.nanmin(pts, axis=0), np.nanmax(pts, axis=0)
        bb = (tuple(lo.tolist()), tuple(hi.tolist()))
        spans.append((None if s % 9 == 0 else bb, s * per, per))
    n_ent = n // 2
    own = []
    for k in range(n_own):
        a, b, c = _tris(rng, 50, o, d)
        bb = None if k == 0 else ((-1e9, -1e9, -1e9), (1e9, 1e9, 1e9))
        if k == 2:
            # Small triangles met far along the ray, in a tight box: past
            # a short reach the box test leaves them out.
            a = np.ascontiguousarray(o + d * rng.uniform(60, 70, (50, 1))
                                     - 0.25 * (b + c) * 1e-3)
            b, c = b * 1e-3, c * 1e-3
            pts = np.concatenate([a, a + b, a + c])
            bb = (tuple(pts.min(axis=0).tolist()),
                  tuple(pts.max(axis=0).tolist()))
        own.append((bb, a, b, c,
                    (np.arange(50) // 5).astype(np.int64), n_ent + 10 * k))
    n_ent += 10 * n_own
    idx = SimpleNamespace(
        entities=[None] * n_ent, tri_v0=v0, tri_e1=e1, tri_e2=e2,
        tri_ent=te, tri_spans=spans, own_spans=own,
        ent_vis=rng.random(n_ent) < 0.85)
    return idx, o, d


@needs_native
def test_ray_hits_with_the_engine_and_without(modes, monkeypatch):
    rng = np.random.default_rng(1392)
    host = object()
    spy = _counted(monkeypatch)
    hits = 0
    for rep in range(3):
        idx, o, d = _stub_index(rng, n_span=90 if rep != 1 else 20)
        for k in range(12):
            oo = o + rng.normal(size=3) * (0.2 * k)
            dd = d + rng.normal(size=3) * 0.01 * k
            if k == 11:
                dd = np.array([0.0, 0.0, -1.0])
            org, dirn = V(*oo.tolist()), V(*dd.tolist())
            for own in (True, False):
                for reach in (None, 25.0):
                    for glob in (False, True):
                        with np.errstate(all="ignore"):
                            want = Viewport._ray_hits_np(
                                host, idx, org, dirn, idx.ent_vis, glob,
                                reach, own)
                            got = Viewport._ray_hits(
                                host, idx, org, dirn, idx.ent_vis, glob,
                                reach, own)
                        if glob:
                            assert got == want
                        else:
                            assert _same(got, want)
                            hits += int(np.isfinite(want).sum())
        assert vv._MT_NATIVE                      # never turned off
    assert spy.calls > 100 and hits > 100


@needs_native
def test_a_difference_on_a_live_ray_turns_the_engine_off(monkeypatch):
    """On trial NumPy answers; a pass that differs puts NumPy in for good."""
    monkeypatch.setattr(vv, "_MT_NATIVE", None)
    monkeypatch.setattr(vv, "_MT_SHADOW", [5])
    monkeypatch.setattr(vv, "_MT_NATIVE_ON", True)
    mods = vv._mt_native()[1]

    class Off:
        """The engine, one ulp out on every minimum."""
        def __getattr__(self, name):
            return getattr(mod, name)

        def ray_face_min(self, *a, **k):
            ft = k.get("face_t")
            r = mod.ray_face_min(*a, **k)
            if ft is not None:
                ft[np.isfinite(ft)] = np.nextafter(ft[np.isfinite(ft)], 0.0)
            return np.nextafter(r, 0.0)
    monkeypatch.setattr(vv, "_MT_NATIVE", (Off(), mods))
    rng = np.random.default_rng(3)
    idx, o, d = _stub_index(rng)
    org, dirn = V(*o.tolist()), V(*d.tolist())
    host = object()
    with np.errstate(all="ignore"):
        want = Viewport._ray_hits_np(host, idx, org, dirn, idx.ent_vis)
        got = Viewport._ray_hits(host, idx, org, dirn, idx.ent_vis)
    assert np.isfinite(want).any()
    assert _same(got, want)                     # NumPy answered
    assert vv._MT_NATIVE is False and vv._mt_native() is None


def _window():
    """Two groups, one in front of part of the other, over a loose floor,
    and a small face of 1 mm (the small-det reading)."""
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(700, 500)
    sc = vp.scene
    sc.clear()
    sc.mesh.add_face([V(-3, -3, 0), V(7, -3, 0), V(7, 4, 0), V(-3, 4, 0)])
    sc.mesh.add_face([V(0, 0, 0.5), V(1e-3, 0, 0.5), V(1e-3, 1e-3, 0.5),
                      V(0, 1e-3, 0.5)])
    groups = []
    for s, (x, y) in ((2.0, (0.0, 0.0)), (1.0, (1.5, -1.5))):
        m = Mesh()
        p = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
             V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                  (2, 3, 7, 6), (3, 0, 4, 7)):
            m.add_face([p[i] for i in q])
        g = Group(m, name="G")
        g.xform = QMatrix4x4()
        g.xform.translate(x, y, 0.01)
        groups.append(g)
    sc.groups += groups
    sc.version += 1
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(35.0), math.radians(35.0)
    cam.target = V(1.5, 0.5, 0.5)
    cam.distance = 12.0
    return win, vp, groups[0]


def _readings(vp):
    """Every face each ray of a pixel grid meets (t, order) and whether
    corners of the model are hidden, as the hover asks them."""
    out = []
    idx = vp._pick_index(near="skip")
    W, H = vp.width(), vp.height()
    for j in range(9):
        for i in range(13):
            x, y = W * (0.05 + 0.9 * i / 12), H * (0.05 + 0.9 * j / 8)
            o, d = vp._pixel_to_ray(x, y)
            vp._ray_union_memo = vp._ray_union_prev = None
            for which in ("sel", "infer", "vis"):
                h = Viewport._face_hits(vp, idx, o, d, which)
                out.append(None if h is None else
                           (h.t.tobytes(), [id(h.ent(k)[0])
                                            for k in range(len(h.t))]))
            out.append(Viewport._ray_hits(vp, idx, o, d, idx.ent_vis,
                                          reduce_global=True))
    for p in (V(0, 0, 0), V(2, 2, 2.01), V(1.5, -1.5, 1.01), V(7, 4, 0),
              V(0.5, 0.5, 2.01), V(-3, -3, 0), V(1e-3, 1e-3, 0.5)):
        out.append(vp._is_occluded(p))
    return out


@needs_native
def test_a_real_view_reads_the_same_with_the_engine(monkeypatch):
    win, vp, a = _window()
    try:
        for edit in (False, True):
            if edit:
                vp.begin_group_edit(a)
            monkeypatch.setattr(vv, "_MT_NATIVE_ON", False)
            monkeypatch.setattr(vv, "_MT_NATIVE", None)
            want = _readings(vp)
            monkeypatch.setattr(vv, "_MT_NATIVE_ON", True)
            monkeypatch.setattr(vv, "_MT_SHADOW", [0])
            assert vv._mt_native() is not None
            spy = _counted(monkeypatch)
            got = _readings(vp)
            assert spy.calls > 100
            assert got == want
            assert any(r is not None and len(r[1]) for r in want
                       if isinstance(r, tuple))
            assert vv._MT_NATIVE
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_python_alone_without_the_switch(monkeypatch):
    """With the switch off nothing asks the engine."""
    monkeypatch.setattr(vv, "_MT_NATIVE_ON", False)
    monkeypatch.setattr(vv, "_MT_NATIVE", None)
    assert vv._mt_native() is None
    rng = np.random.default_rng(4)
    o, d = np.zeros(3), np.array([0.0, 0.0, 1.0])
    v0, e1, e2 = _tris(rng, 200, o, d)
    with np.errstate(all="ignore"):
        t, hit = vv._moller_trumbore(o, d, v0, e1, e2)
        tp, hp = vv._moller_trumbore_py(o, d, v0, e1, e2)
    assert _same(t, tp) and (hit == hp).all()
