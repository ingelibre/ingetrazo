# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The fixed group edges nearest the cursor picked in the native engine
(``views.viewport._nearest_within``, #158): past ``cap`` the first ``cap``
by distance and then index — at the distances NumPy's argpartition picks,
which among equals at the cut takes any — and under it the same ones,
whose order a stable sort by distance keeps; over ties, distances at the
radius, infinities and sizes round the native chunks."""
from __future__ import annotations

import numpy as np
import pytest

import views.viewport as viewport_mod
from core import _native
from views.viewport import _nearest_within

mod = _native.native
pytestmark = pytest.mark.skipif(
    mod is None or not hasattr(mod, "nearest_within"),
    reason="native module not built")


def _numpy(d, radius, cap, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(viewport_mod, "_NEAREST_NATIVE", False)
        return _nearest_within(d, radius, cap)


@pytest.mark.parametrize("seed", range(6))
def test_the_native_pick_is_numpys(seed, monkeypatch):
    rng = np.random.default_rng(4800 + seed)
    past = under = 0
    for _ in range(40):
        n = int(rng.choice([5000, 65_536, 65_537, 300_000]))
        radius = float(rng.choice([8.0, 48.0]))
        # Rounded to few values: many edges at the very same distance.
        d = np.round(rng.uniform(0, 3 * radius, n), int(rng.integers(0, 3)))
        d[rng.random(n) < 0.1] = np.inf
        d[rng.random(n) < 0.01] = radius        # at the radius: left out
        if rng.random() < 0.3:
            d[rng.random(n) < 0.9] = np.inf     # few under the radius
        cap = int(rng.choice([1, 48, 400, 10 ** 6]))
        got = _nearest_within(d, radius, cap)
        want = _numpy(d, radius, cap, monkeypatch)
        if len(want) >= cap:
            cand = np.flatnonzero(d < radius)
            full = cand[np.lexsort((cand, d[cand]))][:cap]
            assert np.array_equal(got, full)
            assert np.array_equal(np.sort(d[got]), np.sort(d[want]))
            past += 1
        else:
            assert np.array_equal(got, want[np.argsort(d[want],
                                                       kind="stable")])
            under += 1
        assert not (d[got] >= radius).any()
    assert past > 15 and under > 4
