# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The spatial index (core._native InstanceSet) only ever drops a
placement the pick index's exact tests would not see: for random
prototypes under random placement matrices (mirrors, scales, rotations),
every placement whose world-baked triangles a ray meets — by the very
Möller–Trumbore of the pick index — is kept by ray_filter, and every one
with a hard edge within reach of a pixel, or a triangle whose screen box
comes near it, by screen_filter. Skipped without the module."""
from __future__ import annotations

import numpy as np
import pytest

import core._native as _native

mod = _native.available()
pytestmark = pytest.mark.skipif(mod is None or not hasattr(mod, "InstanceSet"),
                                reason="native module not built")


def _proto(rng):
    n = int(rng.integers(1, 60))
    c = rng.uniform(-2, 2, size=(n, 1, 3))
    tri = c + rng.normal(scale=rng.choice([0.05, 0.5, 2.0]), size=(n, 3, 3))
    v0 = tri[:, 0]
    e1 = tri[:, 1] - v0
    e2 = tri[:, 2] - v0
    edges = tri[:, :2].reshape(-1, 6)[: int(rng.integers(0, n + 1))]
    return v0, e1, e2, edges


def _matrix(rng):
    from PySide6.QtGui import QMatrix4x4
    m = QMatrix4x4()
    m.translate(*rng.uniform(-30, 30, 3))
    m.rotate(float(rng.uniform(0, 360)), *rng.uniform(-1, 1, 3))
    s = rng.uniform(0.2, 3, 3)
    if rng.random() < 0.3:
        s[0] = -s[0]                                  # mirrored
    m.scale(*s)
    return np.array(m.data(), dtype=np.float64)


def _world(proto, m):
    """The placement baked the way the viewport bakes it (``a @ L.T + t``)."""
    v0, e1, e2, edges = proto
    M = m.reshape(4, 4).T                             # row-major
    L, t = M[:3, :3], M[:3, 3]
    return (v0 @ L.T + t, e1 @ L.T, e2 @ L.T,
            edges.reshape(-1, 3) @ L.T + t)


def _exact_ray(v0, e1, e2, o, d, reach=None):
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) >= 1e-6
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = o - v0
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * (q @ d)
    t = f * np.einsum("ij,ij->i", e2, q)
    hit = ok & (u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t >= 1e-6)
    if reach is not None:
        hit &= t <= reach
    return bool(hit.any())


@pytest.mark.parametrize("seed", range(6))
def test_ray_filter_never_drops_a_hit(seed):
    rng = np.random.default_rng(seed)
    protos = [_proto(rng) for _ in range(5)]
    natp = [mod.InstanceProto(*p) for p in protos]
    P = 200
    of = rng.integers(0, len(protos), P)
    mats = np.array([_matrix(rng) for _ in range(P)])
    iset = mod.InstanceSet(natp, of.astype(np.int64), mats)
    worlds = [_world(protos[of[i]], mats[i]) for i in range(P)]
    cand = np.arange(P, dtype=np.int64)
    kept_total = 0
    for _ in range(60):
        o = rng.uniform(-50, 50, 3)
        tgt = worlds[int(rng.integers(P))][0]
        tgt = tgt[int(rng.integers(len(tgt)))] if len(tgt) else rng.uniform(-30, 30, 3)
        d = tgt + rng.normal(scale=0.5, size=3) - o
        reach = None if rng.random() < 0.7 else float(rng.uniform(1, 80))
        kept = set(iset.ray_filter(cand, tuple(o), tuple(d), reach))
        kept_total += len(kept)
        for i in range(P):
            w = worlds[i]
            if _exact_ray(w[0], w[1], w[2], o, d, reach):
                assert i in kept, (i, reach)
    assert kept_total < 60 * P, "the filter should drop something"


@pytest.mark.parametrize("seed", range(4))
def test_screen_filter_never_drops_something_near(seed):
    from PySide6.QtGui import QMatrix4x4
    rng = np.random.default_rng(100 + seed)
    protos = [_proto(rng) for _ in range(5)]
    natp = [mod.InstanceProto(*p) for p in protos]
    P = 150
    of = rng.integers(0, len(protos), P)
    mats = np.array([_matrix(rng) for _ in range(P)])
    iset = mod.InstanceSet(natp, of.astype(np.int64), mats)
    W, H = 1200.0, 800.0
    proj = QMatrix4x4()
    proj.perspective(50.0, W / H, 0.5, 500.0)
    view = QMatrix4x4()
    view.lookAt(*(__import__("PySide6.QtGui", fromlist=["QVector3D"]).QVector3D(*v)
                  for v in ((60.0, -70.0, 50.0), (0, 0, 0), (0, 0, 1))))
    M = np.array((proj * view).data(), dtype=np.float64).reshape(4, 4).T

    def screen(p):
        c4 = np.c_[p, np.ones(len(p))] @ M.T
        w = c4[:, 3]
        return ((c4[:, 0] / w * 0.5 + 0.5) * W,
                (1.0 - (c4[:, 1] / w * 0.5 + 0.5)) * H, w > 1e-9)
    cand = np.arange(P, dtype=np.int64)
    ER, TR = 66.0, 34.0
    for _ in range(40):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        kept = set(iset.screen_filter(cand, M.T.ravel().tolist(), W, H, x, y,
                                      ER, TR))
        for i in range(P):
            v0, e1, e2, ed = _world(protos[of[i]], mats[i])
            near = False
            if len(ed):
                ax, ay, oa = screen(ed[0::2])
                bx, by, ob = screen(ed[1::2])
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                t = np.clip(((x - ax) * dx + (y - ay) * dy)
                            / np.where(l2 > 1e-12, l2, 1.0), 0, 1)
                dist = np.hypot(ax + t * dx - x, ay + t * dy - y)
                near |= bool(((dist < ER - 2) & oa & ob).any())
            sx = np.stack([screen(c)[0] for c in (v0, v0 + e1, v0 + e2)])
            sy = np.stack([screen(c)[1] for c in (v0, v0 + e1, v0 + e2)])
            front = np.stack([screen(c)[2] for c in (v0, v0 + e1, v0 + e2)])
            inside = ((sx.min(0) - (TR - 2) <= x) & (x <= sx.max(0) + TR - 2)
                      & (sy.min(0) - (TR - 2) <= y) & (y <= sy.max(0) + TR - 2)
                      & front.all(0))
            near |= bool(inside.any()) or bool((~front).any())
            if near:
                assert i in kept, i
