# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Stitch on big triangulated imports: a long edge run past by a chain of
vertices (a stair stringer beside its treads) is split at all of them in one
go, and a coplanar region that cannot merge is not rebuilt per face."""
from __future__ import annotations

import time

from PySide6.QtGui import QVector3D

from core.history import run_stitch
from core.mesh import Mesh
from core.topology import _key, sweep_tjunctions


def _comb(n, drift=0.0):
    """One long face (the stringer) under n small faces (the treads) whose
    bottom corners lie on its top edge. ``drift`` bends that chain by a
    fraction of the weld tolerance per step: each split then brings the next
    vertex within reach, the case that used to cost one round per vertex."""
    m = Mesh()
    L = float(n)
    m.add_face([QVector3D(0, 0, -1), QVector3D(L, 0, -1),
                QVector3D(L, 0, 0), QVector3D(0, 0, 0)])
    bump = lambda i: drift * min(i, n - i)   # noqa: E731
    for i in range(n):
        a, b = float(i), float(i + 1)
        m.add_face([QVector3D(a, 0, bump(i)), QVector3D(b, 0, bump(i + 1)),
                    QVector3D(b, 0, 1), QVector3D(a, 0, 1)])
    return m


def _stringer(m):
    return max(m.faces, key=lambda f: len(f.loop))


def test_a_chain_of_t_junctions_splits_in_one_sweep():
    m = _comb(400)
    t = time.perf_counter()
    sweep_tjunctions(m)
    assert time.perf_counter() - t < 5.0
    assert len(_stringer(m).loop) == 4 + 399     # every tread corner sewn in


def test_a_slightly_bent_chain_is_sewn_too():
    from core.mesh import _STITCH_TOL
    m = _comb(200, drift=_STITCH_TOL * 0.004)
    sweep_tjunctions(m)
    assert len(_stringer(m).loop) == 4 + 199


def test_stitching_the_comb_merges_the_treads_with_the_stringer():
    m = _comb(100)
    seed = {_key(v.position) for v in m.vertices}
    t = time.perf_counter()
    run_stitch(m, seed, set(m.faces), coplanar_merge=True)
    assert time.perf_counter() - t < 10.0
    assert len(m.faces) == 1                     # one flat plate again
