# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The parity triangles are packed in one flat pass (night of 19-11): the
same arrays, bit for bit, as the rows built one by one."""
from __future__ import annotations

import random

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

from core.orient import _pack_lists


def _rows(triangle_lists, face_ids=None):
    rows_a, rows_b, rows_c, idx = [], [], [], []
    for li, tlist in enumerate(triangle_lists):
        fi = face_ids[li] if face_ids is not None else li
        for (ta, tb, tc) in tlist:
            rows_a.append((ta.x(), ta.y(), ta.z()))
            rows_b.append((tb.x(), tb.y(), tb.z()))
            rows_c.append((tc.x(), tc.y(), tc.z()))
            idx.append(fi)
    if not rows_a:
        return None
    a = np.asarray(rows_a, dtype=np.float64)
    b = np.asarray(rows_b, dtype=np.float64)
    c = np.asarray(rows_c, dtype=np.float64)
    return a, b - a, c - a, np.asarray(idx, dtype=np.int64)


def _lists(rng):
    pt = lambda: V(rng.uniform(-1e4, 1e4), rng.uniform(-1, 1),  # noqa: E731
                   rng.uniform(-1e-3, 1e-3))
    return [[(pt(), pt(), pt()) for _ in range(rng.choice([0, 0, 1, 2, 5]))]
            for _ in range(rng.randint(0, 12))]


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("ids", [False, True])
def test_the_same_arrays(seed, ids):
    rng = random.Random(seed)
    lists = _lists(rng)
    fids = [rng.randint(0, 99) for _ in lists] if ids else None
    want = _rows(lists, fids)
    got = _pack_lists(lists, fids)
    if want is None:
        assert got.a.shape == (0, 3) and got.face_idx.shape == (0,)
        return
    for x, y in zip((got.a, got.e1, got.e2, got.face_idx), want):
        assert x.dtype == y.dtype and np.array_equal(x, y)
    # From a generator too.
    g = _pack_lists(iter(lists), fids)
    assert np.array_equal(g.e2, want[2]) and np.array_equal(g.face_idx, want[3])
