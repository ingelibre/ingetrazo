# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The corners near the cursor that the frame hides are left out in the
native engine with ``points_near_px``'s ``seen`` (#158): the same indices,
in the same order and at the same distances, as NumPy's
``Viewport._depth_hidden`` leaves — over limits a point lies exactly at,
points off the patch, behind the eye and in a patch with no limit."""
from __future__ import annotations

import numpy as np
import pytest

import views.viewport as viewport_mod
from core import _native
from views.viewport import Viewport, _px_near

mod = _native.native
pytestmark = pytest.mark.skipif(mod is None, reason="native module not built")


def _case(rng, n):
    eye = rng.uniform(-50, 50, 3)
    pts = eye + rng.normal(0, 30, (n, 3))
    W, H, dpr = 900.0, 640.0, float(rng.choice([1.0, 1.25, 2.0]))
    px, py = rng.uniform(0, W), rng.uniform(0, H)
    # Clustered round the cursor, some off it, some on the very pixel.
    x = px + rng.normal(0, 14, n)
    y = py + rng.normal(0, 14, n)
    x[::7] = px
    y[::11] = py
    ok = rng.random(n) > 0.05
    thr = float(rng.choice([6.0, 10.0, 24.0]))
    hdev = int(H * dpr)
    x0 = int(np.floor((px - thr) * dpr)) - 1
    yb0 = hdev - 1 - (int(np.floor((py + thr) * dpr)) + 1)
    gw = int(2 * thr * dpr) + 4
    gh = gw
    dist = np.sqrt(((pts - eye) ** 2).sum(axis=1))
    lim = np.full((gh, gw), float(np.median(dist)))
    lim[rng.random((gh, gw)) < 0.2] = np.inf
    # A point lying exactly at its pixel's limit is not hidden.
    ix = np.floor(x * dpr).astype(np.int64) - x0
    iy = hdev - 1 - np.floor(y * dpr).astype(np.int64) - yb0
    on = np.flatnonzero((ix >= 0) & (iy >= 0) & (ix < gw) & (iy < gh))
    for k in on[::5]:
        lim[iy[k], ix[k]] = dist[k]
    seen = (eye.tolist(), np.ascontiguousarray(lim), x0, yb0, dpr, hdev)
    return x, y, ok, px, py, thr, pts, seen


@pytest.mark.parametrize("seed", range(8))
def test_the_native_depth_test_leaves_what_numpy_leaves(seed, monkeypatch):
    if "seen" not in (mod.points_near_px.__text_signature__ or ""):
        pytest.skip("older module")
    rng = np.random.default_rng(1600 + seed)
    hidden = kept = 0
    for _ in range(20):
        case = _case(rng, int(rng.choice([5000, 40_000])))
        x, y, ok, px, py, thr, pts, seen = case
        k, d = _px_near(*case)
        with monkeypatch.context() as m:
            m.setattr(viewport_mod, "_NEAR_SEEN_NATIVE", False)
            k1, d1 = _px_near(*case)
        with monkeypatch.context() as m:
            m.setattr(_native, "native", None)
            k0, d0 = _px_near(*case)
        assert np.array_equal(k, k0) and np.array_equal(k1, k0)
        assert np.array_equal(d, d0) and np.array_equal(d1, d0)
        all_k, _ = _px_near(x, y, ok, px, py, thr)
        hid = Viewport._depth_hidden(seen, pts[all_k], x[all_k], y[all_k])
        assert np.array_equal(k, all_k[~hid])
        hidden += int(hid.sum())
        kept += len(k)
    assert hidden > 100 and kept > 100
