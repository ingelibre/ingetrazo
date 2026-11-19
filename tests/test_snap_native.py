# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The snap search's per-move work, engine or not, gives the same answer:

* ``_projector`` projects each point once a search and hands back the very
  pixels the viewport's projector gives (a test's stand-in as is);
* ``Viewport._nearby_loose_edges`` finds the same edges in the same order
  with the engine's distances as with NumPy's (ties, segments behind the
  eye, zero length, NaN, more than ``cap`` within the radius)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402

import core._native as _native  # noqa: E402
from core import inference  # noqa: E402
from views import viewport as vpmod  # noqa: E402

mod = _native.available()


class _Proj:
    def __init__(self):
        self.calls = 0

    def _pixel_projector(self):
        def fn(w):
            self.calls += 1
            if w.z() < 0:
                return None
            return (w.x() * 3.0 + 0.25, w.y() * -2.0 + w.z())
        return fn


def test_projector_asks_each_point_once_and_gives_its_pixels():
    vp = _Proj()
    pr = inference._projector(vp)
    plain = _Proj()._pixel_projector()
    pts = [V(1, 2, 3), V(1, 2, 3), V(0, 0, -1), V(0, 0, -1), V(-0.0, 0, 0),
           V(0, 0, 0), V(float("nan"), 0, 1), V(float("nan"), 0, 1)]
    got = [pr(p) for p in pts]
    want = [plain(p) for p in pts]
    assert got[:6] == want[:6]
    assert all(g[0] != g[0] and g[1] == w[1] for g, w in zip(got[6:],
                                                          want[6:]))
    assert got[2] is None and got[3] is None
    # 1,2,3 once; behind once; ±0 once; NaN keys never match: twice.
    assert vp.calls == 5
    # Another search projects again (the camera may have moved between).
    inference._projector(vp)(V(1, 2, 3))
    assert vp.calls == 6


def test_projector_leaves_a_stand_in_alone():
    vp = _Proj()
    seen = []
    vp._world_to_pixel = lambda w: seen.append(w) or (0.0, 0.0)
    vp._pixel_projector = lambda: vp._world_to_pixel
    pr = inference._projector(vp)
    pr(V(1, 1, 1))
    pr(V(1, 1, 1))
    assert len(seen) == 2
    bare = SimpleNamespace(_world_to_pixel=lambda w: (1.0, 2.0))
    assert inference._projector(bare) is bare._world_to_pixel


class _Loose:
    """What _nearby_loose_edges reads of a viewport."""

    def __init__(self, data, n):
        self.data = data
        self.idx = SimpleNamespace(edges=[("edge", i) for i in range(n)])

    def _ledge_screen(self):
        return self.data

    def _pick_index(self, near=None):
        return self.idx


def _segments(rng, n):
    a = rng.uniform(-50, 1100, (4, n))
    k = rng.integers(0, 4)
    if k == 1:
        a = np.round(a / 7.0) * 7.0               # on a lattice: ties
    elif k == 2:
        a[2:, : n // 3] = a[:2, : n // 3]          # zero length
    if rng.random() < 0.3 and n:
        j = rng.integers(0, n, max(1, n // 50))
        a[rng.integers(0, 4, len(j)), j] = rng.choice(
            [np.nan, np.inf, -np.inf], len(j))
    ok = rng.random(n) < 0.9
    return a, ok


@pytest.mark.skipif(mod is None or not hasattr(mod, "segment_distances"),
                    reason="native module not built")
@pytest.mark.parametrize("seed", range(12))
def test_nearby_loose_edges_same_edges_engine_or_not(seed, monkeypatch):
    rng = np.random.default_rng(seed)
    for _ in range(4):
        n = int(rng.choice([4096, 9000, 30000]))
        a, ok = _segments(rng, n)
        vp = _Loose((a[0], a[1], a[2], a[3], ok), n - int(rng.integers(0, 3)))
        for _k in range(4):
            px, py = (float(v) for v in rng.uniform(0, 1035, 2))
            radius = float(rng.choice([8.0, 64.0, 400.0]))
            cap = int(rng.choice([3, 400, 10 ** 6]))
            got = {}
            for on in (False, True):
                monkeypatch.setattr(_native, "native", mod if on else None)
                got[on] = vpmod.Viewport._nearby_loose_edges(
                    vp, px, py, radius_px=radius, cap=cap)
            assert got[True] == got[False]
    # The engine's pass is the one asked when it is on.
    calls = []

    class _Counting:
        def segment_distances(self, *a):
            calls.append(1)
            return mod.segment_distances(*a)
    monkeypatch.setattr(_native, "native", _Counting())
    vpmod.Viewport._nearby_loose_edges(vp, 10.0, 10.0)
    assert calls


def test_nearby_loose_edges_python_only(monkeypatch):
    """Without the engine: the NumPy pass, as before."""
    monkeypatch.setattr(_native, "native", None)
    rng = np.random.default_rng(5)
    a, ok = _segments(rng, 5000)
    vp = _Loose((a[0], a[1], a[2], a[3], ok), 5000)
    got = vpmod.Viewport._nearby_loose_edges(vp, 300.0, 300.0, 64.0, 400)
    dx, dy = a[2] - a[0], a[3] - a[1]
    with np.errstate(all="ignore"):
        l2 = dx * dx + dy * dy
        safe = np.where(l2 > 1e-12, l2, 1.0)
        t = np.clip(((300.0 - a[0]) * dx + (300.0 - a[1]) * dy) / safe,
                    0.0, 1.0)
        d = np.hypot(a[0] + t * dx - 300.0, a[1] + t * dy - 300.0)
    d = np.where(ok, d, np.inf)
    cand = np.where(d < 64.0)[0]
    if len(cand) > 400:
        cand = cand[np.argsort(d[cand])[:400]]
    assert got == [("edge", int(i)) for i in cand]


# ---- The intersection snap's pairs ------------------------------------------

from PySide6.QtGui import QVector3D  # noqa: E402

from core import snap as snapmod  # noqa: E402
from core.topology import _SPLIT_TOLERANCE, segment_intersection  # noqa: E402

needs_hits = pytest.mark.skipif(
    mod is None or not hasattr(mod, "segment_hits")
    or _native.qt_hypot() is None, reason="native module not built")


def _python_hits(ends, pairs):
    rows = ends.tolist()
    out = []
    for i, j in pairs.tolist():
        p = [QVector3D(*rows[i][0]), QVector3D(*rows[i][1]),
             QVector3D(*rows[j][0]), QVector3D(*rows[j][1])]
        try:
            out.append(segment_intersection(*p))
        except (OverflowError, ValueError):
            out.append("raises")
    return out


@needs_hits
@pytest.mark.parametrize("seed", range(25))
def test_segment_hits_is_segment_intersection_bit_for_bit(seed):
    ends, pairs = snapmod._hit_sample(seed=seed, n=2000)
    status, pts = mod.segment_hits(ends, np.ascontiguousarray(pairs[:, 0]),
                                   np.ascontiguousarray(pairs[:, 1]),
                                   _SPLIT_TOLERANCE, _native.qt_hypot())
    want = _python_hits(ends, pairs)
    hits = 0
    for k, w in enumerate(want):
        if status[k] == 2:
            continue                      # asked of Python
        assert w != "raises"
        if w is None:
            assert status[k] == 0, k
        else:
            hits += 1
            assert status[k] == 1, k
            assert tuple(pts[k].tolist()) == (w.x(), w.y(), w.z()), k
    assert hits > 100                     # the sample does cross


@needs_hits
def test_segment_hits_edges():
    h = _native.qt_hypot()
    e = np.zeros((0, 2, 3), np.float32)
    z = np.zeros(0, np.int64)
    st, pts = mod.segment_hits(e, z, z, _SPLIT_TOLERANCE, h)
    assert len(st) == 0 and pts.shape == (0, 3)
    one = np.zeros((1, 2, 3), np.float32)
    with pytest.raises(ValueError):
        mod.segment_hits(one, np.array([0], np.int64), np.array([1], np.int64),
                         _SPLIT_TOLERANCE, h)
    with pytest.raises(ValueError):
        mod.segment_hits(one, z, z, _SPLIT_TOLERANCE, "nope")
    # An X, a T on an end, parallels, a skew pair.
    ends = np.array([[[0, 0, 0], [2, 2, 0]], [[0, 2, 0], [2, 0, 0]],
                     [[1, 1, 0], [1, 5, 0]], [[0, 1, 0], [2, 3, 0]],
                     [[0, 2, 1], [2, 0, 1]]], np.float32)
    ii = np.array([0, 0, 0, 0], np.int64)
    jj = np.array([1, 2, 3, 4], np.int64)
    st, pts = mod.segment_hits(ends, ii, jj, _SPLIT_TOLERANCE, h)
    assert st.tolist() == [1, 1, 0, 0]
    assert pts[0].tolist() == [1.0, 1.0, 0.0]


class _E:
    def __init__(self, a, b):
        self.a, self.b = QVector3D(*a), QVector3D(*b)


def _meetings(edges):
    return [(id(a), id(b), (p.x(), p.y(), p.z()))
            for a, b, p in snapmod._pair_meetings(edges)]


@pytest.mark.parametrize("seed", range(10))
def test_pair_meetings_same_engine_or_not_on_trial_or_not(seed, monkeypatch):
    rng = np.random.default_rng(seed)
    pts = np.round(rng.uniform(0, 6, (60, 2, 3)) * 2) / 2
    pts[:, :, 2] = np.round(rng.uniform(0, 1, (60, 2)))   # two planes: crossings
    edges = [_E(*map(tuple, p.tolist())) for p in pts]
    monkeypatch.setattr(_native, "native", None)
    monkeypatch.setattr(snapmod, "_HITS_NATIVE", None)
    want = _meetings(edges)
    assert want
    if mod is None or not hasattr(mod, "segment_hits") \
            or _native.qt_hypot() is None:
        return
    monkeypatch.setattr(_native, "native", mod)
    for trial in (300, 0):
        monkeypatch.setattr(snapmod, "_HITS_NATIVE", None)
        monkeypatch.setattr(snapmod, "_HITS_SHADOW", [trial])
        assert _meetings(edges) == want
        assert snapmod._HITS_NATIVE[0] is mod
        if trial:
            assert snapmod._HITS_SHADOW[0] < trial


@needs_hits
def test_an_engine_that_differs_is_not_used(monkeypatch):
    class _Liar:
        def segment_hits(self, ends, ii, jj, tol, h):
            st, p = mod.segment_hits(ends, ii, jj, tol, h)
            p = p.copy()
            p[st == 1] += np.float32(1e-3)
            return st, p
    monkeypatch.setattr(_native, "native", _Liar())
    monkeypatch.setattr(snapmod, "_HITS_NATIVE", None)
    assert snapmod._native_hits() == (None, None)
    # And one that passes the sample but differs live is dropped on trial.

    class _LiveLiar:
        def __init__(self):
            self.n = 0

        def segment_hits(self, ends, ii, jj, tol, h):
            self.n += 1
            st, p = mod.segment_hits(ends, ii, jj, tol, h)
            if self.n > 1:
                st = np.zeros_like(st)
            return st, p
    pts = np.array([[[0, 0, 0], [2, 2, 0]], [[0, 2, 0], [2, 0, 0]]] * 5,
                   np.float64)
    edges = [_E(*map(tuple, p.tolist())) for p in pts]
    monkeypatch.setattr(_native, "native", _LiveLiar())
    monkeypatch.setattr(snapmod, "_HITS_NATIVE", None)
    monkeypatch.setattr(snapmod, "_HITS_SHADOW", [2000])
    monkeypatch.setattr(_native, "native", _native.native)
    first = _meetings(edges)
    assert first and snapmod._HITS_NATIVE == (None, None)
    monkeypatch.setattr(_native, "native", None)
    monkeypatch.setattr(snapmod, "_HITS_NATIVE", None)
    assert _meetings(edges) == first


@needs_hits
def test_segment_hits_at_the_gap_tolerance():
    """Skew pairs whose gap is right at segment_intersection's tolerance:
    the engine keeps exactly the ones Python keeps."""
    rng = np.random.default_rng(7)
    n = 3000
    c = rng.uniform(-20, 20, (n, 3))
    d1 = rng.normal(size=(n, 3))
    d2 = rng.normal(size=(n, 3))
    nrm = np.cross(d1, d2)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    gap = _SPLIT_TOLERANCE * rng.uniform(0.98, 1.02, (n, 1))
    ends = np.empty((2 * n, 2, 3))
    ends[:n, 0], ends[:n, 1] = c - d1, c + d1
    ends[n:, 0], ends[n:, 1] = c + nrm * gap - d2, c + nrm * gap + d2
    ends = ends.astype(np.float32)
    pairs = np.stack([np.arange(n), np.arange(n) + n], axis=1).astype(np.int64)
    status, pts = mod.segment_hits(ends, np.ascontiguousarray(pairs[:, 0]),
                                   np.ascontiguousarray(pairs[:, 1]),
                                   _SPLIT_TOLERANCE, _native.qt_hypot())
    want = _python_hits(ends, pairs)
    kept = sum(w is not None for w in want)
    assert 0 < kept < n                   # both sides of the line are here
    for k, w in enumerate(want):
        assert status[k] == (0 if w is None else 1)
        if w is not None:
            assert tuple(pts[k].tolist()) == (w.x(), w.y(), w.z())
