# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The engine's kernels a big document opens with let go of the interpreter,
or the meshes baked side by side would run one after another (#1092), and
their (N,3) rows stay what they were. Skipped without the engine."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

import core._native as _native

nat = _native.native
pytestmark = pytest.mark.skipif(
    nat is None or _native.qt_hypot() is None,
    reason="engine off or not built")


def _spins_during(call):
    """How many turns this thread gets while another runs ``call``."""
    box = []
    t = threading.Thread(target=lambda: box.append(call()))
    start = time.perf_counter()
    t.start()
    spins = 0
    while t.is_alive():
        spins += 1
        time.sleep(0.0005)
    assert time.perf_counter() - start > 0.01, "too short to tell"
    return spins, box[0]


def _spheres(n):
    rng = np.random.default_rng(3)
    return rng.normal(size=(n, 3)).astype(np.float32)


def test_the_kernels_let_the_interpreter_go():
    rows = _spheres(3_000_000)
    spins, out = _spins_during(
        lambda: nat.qt_vector_probe(rows, _native.qt_hypot()))
    assert spins > 5 and out[1].shape == rows.shape
    spins, out = _spins_during(
        lambda: nat.weld_points(rows, 1e4, 1e-8))
    assert spins > 5 and out[0].shape[1] == 3
    n = 1_000_000
    corners = np.arange(3 * n, dtype=np.int64)
    spins, out = _spins_during(lambda: nat.face_geometry(
        rows[:3 * n], corners, np.full(n, 3, dtype=np.int64),
        np.ones(n, dtype=np.int64), _native.qt_hypot(), True))
    assert spins > 5 and out[0].shape == (n, 3) and out[3].shape == (n, 3)


def test_the_kernels_rows_are_in_order():
    """(N,3) as the row-by-row conversion made them, whatever the N."""
    h = _native.qt_hypot()
    for n in (0, 1, 5):
        rows = _spheres(n)
        ln, unit, u, v = nat.qt_vector_probe(rows, h)
        assert unit.shape == u.shape == v.shape == (n, 3) and ln.shape == (n,)
        assert unit.dtype == np.float32
        for i in range(n):
            one = nat.qt_vector_probe(rows[i:i + 1], h)
            assert one[1][0].tobytes() == unit[i].tobytes()
            assert one[2][0].tobytes() == u[i].tobytes()
    pts = np.array([[0, 0, 0], [1, 2, 3], [0, 0, 0], [4, 5, 6]], np.float32)
    vpos, ids, origin = nat.weld_points(pts, 1e4, 1e-8)
    assert vpos.tolist() == [[0, 0, 0], [1, 2, 3], [4, 5, 6]]
    assert ids.tolist() == [0, 1, 0, 2] and origin.tolist() == [0, 1, 3]
    empty = nat.weld_points(np.zeros((0, 3), np.float32), 1e4, 1e-8)
    assert empty[0].shape == (0, 3)
    sq = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32)
    g = nat.face_geometry(sq, np.arange(4, dtype=np.int64),
                          np.array([4], np.int64), np.array([1], np.int64),
                          h, True)
    assert g[0].tolist() == [[0, 0, 1]] and g[0].dtype == np.float32
    assert g[3].shape == (2, 3) and g[3].dtype == np.uint32
    assert g[4].tolist() == [0, 0] and g[6].shape == (2, 3)
