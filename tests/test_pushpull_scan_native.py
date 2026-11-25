# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull's corner scan (tools.pushpull ``_infer_reference_distance``):

* the native ``px_near_sorted`` gives, bit for bit, the rows, distances and
  screen box that ``Viewport._project_px`` and the NumPy filter and stable
  sort give — random cameras, float64 and float32 rows, points behind the
  eye, NaN and infinity, ties, empty meshes;
* the scan answers the same corner with the engine and without it, and
  asking all meshes' candidates as one list answers what mesh by mesh,
  each under the best so far, answered (ties across meshes included)."""
from __future__ import annotations

import os
import random
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

import core._native as _native  # noqa: E402
from core.topology import _key  # noqa: E402
from tools.pushpull import PushPullTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402

mod = _native.available()
needs_native = pytest.mark.skipif(
    mod is None or not hasattr(mod, "px_near_sorted"),
    reason="native module not built")

W, H = 1035, 699


def _camera(rng):
    proj = QMatrix4x4()
    if rng.random() < 0.6:
        proj.perspective(float(rng.uniform(20, 80)), W / H, 0.1, 900.0)
    else:
        proj.ortho(-60, 60, -40, 40, -500, 500)
    view = QMatrix4x4()
    view.lookAt(V(*rng.uniform(-60, 60, 3)), V(*rng.uniform(-5, 5, 3)),
                V(0, 0, 1))
    m = proj * view
    return np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")


class _Eye:
    """What Viewport._project_px reads of a viewport."""

    def __init__(self, m):
        self.m = m

    def _np_mvp(self):
        return self.m

    def width(self):
        return W

    def height(self):
        return H


def _python(eye, pts, sx, sy, thr2):
    """The Python path of the scan, as _infer_reference_distance runs it."""
    px, py, ok = Viewport._project_px(eye, pts)
    box = ((px[ok].min(), px[ok].max(), py[ok].min(), py[ok].max())
           if ok.any() else None)
    d2 = (px - sx) ** 2 + (py - sy) ** 2
    near = np.flatnonzero(ok & (d2 <= thr2))
    cand = near[np.argsort(d2[near], kind="stable")]
    return cand, d2[cand], box


def _same_bits(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return a.shape == b.shape and (a.view(np.int64) == b.view(np.int64)).all()


def _pts(rng, n):
    kind = rng.integers(0, 4)
    if kind == 0:                                 # spread
        p = rng.uniform(-80, 80, (n, 3))
    elif kind == 1:                               # on a grid: many ties
        p = rng.integers(-6, 7, (n, 3)).astype(np.float64)
    elif kind == 2:                               # duplicates
        base = rng.uniform(-10, 10, (max(1, n // 7), 3))
        p = base[rng.integers(0, len(base), n)]
    else:                                         # tiny and huge
        p = rng.uniform(-1, 1, (n, 3)) * 10.0 ** rng.uniform(-6, 7, (n, 1))
    if n and rng.random() < 0.3:                  # NaN and infinity
        k = rng.integers(0, n, max(1, n // 20))
        p[k, rng.integers(0, 3, len(k))] = rng.choice(
            [np.nan, np.inf, -np.inf], len(k))
    return p


@needs_native
@pytest.mark.parametrize("seed", range(40))
def test_kernel_is_the_numpy_scan_bit_for_bit(seed):
    rng = np.random.default_rng(seed)
    for _ in range(6):
        eye = _Eye(_camera(rng))
        n = int(rng.choice([0, 1, 2, 7, 300, 5000]))
        pts = _pts(rng, n)
        if rng.random() < 0.3:
            pts = pts.astype(np.float32)
        for _k in range(5):
            px, py, ok = Viewport._project_px(eye, pts.reshape(-1, 3))
            if ok.any() and rng.random() < 0.7:
                j = int(rng.choice(np.flatnonzero(ok)))
                sx, sy = float(px[j]), float(py[j])    # right on a corner
                if rng.random() < 0.5:
                    sx += float(rng.uniform(-3, 3))
            else:
                sx, sy = float(rng.uniform(0, W)), float(rng.uniform(0, H))
            thr = float(rng.choice([0.0, 9.0, 40.0, 1e9]))
            thr2 = thr * thr
            want = _python(eye, pts.reshape(-1, 3), sx, sy, thr2)
            got = mod.px_near_sorted(pts.reshape(-1, 3), eye.m, float(W),
                                     float(H), sx, sy, thr2)
            assert got[0].dtype == np.int64
            assert (got[0] == want[0]).all() and len(got[0]) == len(want[0])
            assert _same_bits(got[1], want[1])
            if want[2] is None:
                assert got[2] is None
            else:
                # The box only feeds comparisons: any NaN is the same NaN.
                g = np.array(got[2], dtype=np.float64)
                w = np.array([float(v) for v in want[2]])
                assert (np.isnan(g) == np.isnan(w)).all()
                k = ~np.isnan(w)
                assert _same_bits(g[k], w[k])


@needs_native
def test_kernel_edges():
    eye = _Eye(np.eye(4))
    e = np.empty((0, 3))
    c, d, b = mod.px_near_sorted(e, eye.m, float(W), float(H), 1.0, 1.0, 81.0)
    assert len(c) == 0 and len(d) == 0 and b is None
    # All behind the eye: nothing, and no box.
    m = np.eye(4)
    m[3, 3] = -1.0
    c, d, b = mod.px_near_sorted(np.zeros((5, 3)), m, float(W), float(H),
                                 0.0, 0.0, 1e18)
    assert len(c) == 0 and b is None
    with pytest.raises(ValueError):
        mod.px_near_sorted(np.zeros((3, 2)), eye.m, 1.0, 1.0, 0, 0, 1.0)
    with pytest.raises(ValueError):
        mod.px_near_sorted(np.zeros((3, 3)), np.eye(3), 1.0, 1.0, 0, 0, 1.0)


# ---- The whole scan ---------------------------------------------------------

class _Rows:
    def __init__(self, pts):
        self.pts = pts

    def __len__(self):
        return len(self.pts)

    def __getitem__(self, i):
        x, y, z = self.pts[int(i)]
        return SimpleNamespace(position=V(float(x), float(y), float(z)))


class _Vp(_Eye):
    """A viewport whose projection is the real one; occlusion by a set."""

    snap_threshold_px = 9.0
    scene = SimpleNamespace(mesh=SimpleNamespace(vertices=[]), groups=[],
                            guides=[])
    _hover_edge = None
    _project_px = Viewport._project_px

    def __init__(self, m, hidden=(), batched=True):
        super().__init__(m)
        self.hidden = set(hidden)
        if batched:
            self._occluded_many = self._many
        if batched == "first":
            self._first_clear = self._first

    def _world_to_pixel(self, p):
        px, py, ok = self._project_px(np.array([[p.x(), p.y(), p.z()]]))
        return (float(px[0]), float(py[0])) if ok[0] else None

    def pick_face_any(self, *a, **k):
        return None, None

    def _is_occluded(self, world):
        return _key(world) in self.hidden

    def _first(self, pts):
        for j, p in enumerate(pts):
            if _key(V(*map(float, p))) not in self.hidden:
                return j
        return -1

    def _many(self, pts):
        return [_key(V(*map(float, p))) in self.hidden for p in pts]


def _tool(cache, cap=()):
    t = PushPullTool()
    t._infer_cache = cache
    t._anchor = V(0, 0, 0)
    t._normal = V(0, 0, 1)
    t._cap_positions = list(cap)
    t._infer_edge_midpoint = lambda *a: None
    t._infer_guide_line = lambda *a: None
    return t


def _answer(tool, vp, sx, sy):
    tool._inference_point = None
    tool._inference_kind = None
    tool._infer_boxes = None
    d = tool._infer_reference_distance(
        SimpleNamespace(viewport=vp, screen=QPointF(sx, sy), hit=None,
                        ctrl=False))
    p = tool._inference_point
    return (d, tool._inference_kind,
            None if p is None else (p.x(), p.y(), p.z()))


@pytest.mark.parametrize("seed", range(30))
def test_scan_same_answer_every_way(seed, monkeypatch):
    rng = np.random.default_rng(seed)
    rnd = random.Random(seed)
    m = _camera(rng)
    eye = _Eye(m)
    # A few meshes around one spot on screen, some sharing corners (ties
    # across meshes), some float32.
    centre = rng.uniform(-5, 5, 3)
    shared = centre + rng.normal(scale=0.5, size=(20, 3))
    cache = []
    for k in range(int(rng.integers(1, 6))):
        n = int(rng.integers(0, 400))
        p = centre + rng.normal(scale=float(rng.choice([0.3, 1.0, 4.0])),
                                size=(n, 3))
        p = np.concatenate([p, shared[rng.integers(0, 20, 10)]])
        if rng.random() < 0.3:
            p = p.astype(np.float32)
        cache.append((_Rows(p), p))
    every = np.concatenate([np.asarray(a, np.float64) for _r, a in cache])
    hidden = {_key(V(*map(float, q))) for q in every if rnd.random() < 0.5}
    cap = [V(*map(float, every[j])) for j in rng.integers(0, len(every), 4)]
    spots = []
    px, py, ok = Viewport._project_px(eye, every)
    for _ in range(8):
        if ok.any() and rnd.random() < 0.8:
            j = int(rng.choice(np.flatnonzero(ok)))
            spots.append((float(px[j]) + rnd.uniform(-4, 4),
                          float(py[j]) + rnd.uniform(-4, 4)))
        else:
            spots.append((rnd.uniform(0, W), rnd.uniform(0, H)))
    answers = []
    calls = []

    class _Counting:
        def px_near_sorted(self, *a):
            calls.append(1)
            return mod.px_near_sorted(*a)
    for native_on in (False, True):
        if native_on and (mod is None or not hasattr(mod, "px_near_sorted")):
            continue
        monkeypatch.setattr(_native, "native",
                            _Counting() if native_on else None)
        for merge in (PushPullTool._MERGE_MAX, 0):
            monkeypatch.setattr(PushPullTool, "_MERGE_MAX", merge)
            for batched in ("first", True, False):
                vp = _Vp(m, hidden, batched)
                t = _tool(cache, cap)
                answers.append([_answer(t, vp, sx, sy) for sx, sy in spots])
    for a in answers[1:]:
        assert a == answers[0]
    if mod is not None and hasattr(mod, "px_near_sorted"):
        assert calls                      # the engine's pass was the one asked
    # And the brute force: every candidate read.
    exclude = {_key(c) for c in cap}
    for (sx, sy), got in zip(spots, answers[0]):
        best = None
        for _rows, arr in cache:
            qx, qy, qok = Viewport._project_px(eye, arr)
            d2 = (qx - sx) ** 2 + (qy - sy) ** 2
            for i in np.flatnonzero(qok & (d2 <= 81.0)):
                p = V(*map(float, arr[i]))
                if _key(p) in exclude or _key(p) in hidden:
                    continue
                if best is None or float(d2[i]) < best[0]:
                    best = (float(d2[i]), p)
        o = Viewport._project_px(eye, np.zeros((1, 3)))
        if o[2][0]:
            od = (o[0][0] - sx) ** 2 + (o[1][0] - sy) ** 2
            if od <= 81.0 and (best is None or od < best[0]):
                assert got[1] == "origin"
                continue
        if best is None:
            assert got[1] != "vertex"
        else:
            assert got[1] == "vertex"
            assert got[2] == (best[1].x(), best[1].y(), best[1].z())


@pytest.mark.parametrize("native_on", [False, True])
@pytest.mark.parametrize("merge", [True, False])
def test_ties_go_to_the_first_mesh_then_the_first_row(native_on, merge,
                                                      monkeypatch):
    if native_on and (mod is None or not hasattr(mod, "px_near_sorted")):
        pytest.skip("native module not built")
    monkeypatch.setattr(_native, "native", mod if native_on else None)
    if not merge:
        monkeypatch.setattr(PushPullTool, "_MERGE_MAX", 0)
    # A pixel per unit (powers of two: exact), four corners at the same
    # distance from the cursor, spread over three meshes.
    m = np.zeros((4, 4))
    m[0, 3], m[1, 3], m[3, 3] = -1.0, 1.0, 1.0

    class _Square(_Vp):
        def width(self):
            return 1024

        def height(self):
            return 1024
    m[0, 0], m[1, 1] = 2.0 / 1024, -2.0 / 1024
    meshes = [np.array([[300.0, 300.0, 0.0], [101.0, 101.0, 1.0]]),
              np.array([[100.0, 100.0, 2.0], [101.0, 100.0, 3.0]]),
              np.array([[100.0, 101.0, 4.0]])]
    cache = [(_Rows(a), a) for a in meshes]
    for hidden, want in (((), 1.0),
                         ({_key(V(101, 101, 1))}, 2.0),
                         ({_key(V(101, 101, 1)), _key(V(100, 100, 2))}, 3.0)):
        vp = _Square(m, hidden)
        t = _tool(cache)
        d, kind, p = _answer(t, vp, 100.5, 100.5)
        assert kind == "vertex" and p[2] == want and d == want
