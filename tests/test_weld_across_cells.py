# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The cross-cell pass of ``Mesh.weld_coincident`` goes on instead of
starting over after each weld, and looks only at the vertices with a held
cell beside them (night of 19-11): the same welds, in the same order, and
the same mesh as the scan that started over."""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QVector3D as V

from core import mesh as M
from core.mesh import Mesh


def _starting_over(mesh):
    """The pass before."""
    step = 10.0 ** -M._KEY_DECIMALS
    tol2 = step * step
    changed = False
    merged = True
    while merged:
        merged = False
        for v in list(mesh.vertices):
            k = M._key(v.position)
            if mesh._registry.get(k) is not v:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nk = (k[0] + dx, k[1] + dy, k[2] + dz)
                        if nk == k:
                            continue
                        w = mesh._registry.get(nk)
                        if (w is None or w is v or
                                (w.position - v.position)
                                .lengthSquared() >= tol2):
                            continue
                        kp, dp = (v, w) if k < nk else (w, v)
                        mesh._weld_into(kp, dp)
                        changed = True
                        merged = True
                        break
                    if merged:
                        break
                if merged:
                    break
            if merged:
                break
    return changed


def _build(seed):
    """Separate quads, then corners of some moved a hair from corners of
    others — across a cell border (half a cell, give or take a few
    millionths), some of them chained one beside the next."""
    rng = random.Random(seed)
    m = Mesh()
    h = 0.5e-4                       # a cell border, in metres
    quads = []
    for i in range(rng.randint(4, 12)):
        x, y = (i % 4) * 0.3, (i // 4) * 0.3
        quads.append(m.add_face([V(x, y, 0), V(x + 0.1, y, 0),
                                 V(x + 0.1, y + 0.1, 0), V(x, y + 0.1, 0)]))
    m.add_edge(V(2, 2, 0), V(2.05, 2.02, 0))
    corners = [v for f in quads for v in f.loop]
    for _ in range(rng.randint(1, 10)):
        a, b = rng.sample(corners, 2)
        if a is b:
            continue
        off = [rng.choice([0.0, h + 2e-6, -(h + 3e-6), h + 9e-6, 2e-6])
               for _ in range(3)]
        m.place_vertex(b, a.position + V(*off))
    rng.shuffle(m.vertices)
    return m


def _state(m):
    r = lambda p: (round(p.x(), 7), round(p.y(), 7), round(p.z(), 7))  # noqa: E731
    return ([r(v.position) for v in m.vertices],
            sorted(tuple(sorted((r(e.v0.position), r(e.v1.position))))
                   for e in m.edges),
            sorted(tuple(r(v.position) for v in f.loop) for f in m.faces),
            sorted((k, r(v.position)) for k, v in m._registry.items()))


@pytest.mark.parametrize("seed", range(60))
def test_the_welds_are_the_scans(seed, monkeypatch):
    runs = []
    for fn in (_starting_over, Mesh._weld_across_cells):
        m = _build(seed)
        order = []
        real = Mesh._weld_into

        def spy(self, keep, dup, _real=real, _order=order):
            _order.append((tuple(round(c, 7) for c in keep.position.toTuple()),
                           tuple(round(c, 7) for c in dup.position.toTuple())))
            return _real(self, keep, dup)

        with monkeypatch.context() as mp:
            mp.setattr(Mesh, "_weld_into", spy)
            got = fn(m)
        runs.append((got, order, _state(m)))
    assert runs[0] == runs[1]


def test_the_cases_weld(monkeypatch):
    welded = 0
    for seed in range(60):
        m = _build(seed)
        welded += bool(Mesh._weld_across_cells(m))
    assert welded > 20


def test_far_apart_cells_fall_back_to_every_vertex():
    keys = [(0, 0, 0), (10 ** 9, 10 ** 9, 10 ** 9)]
    reg = {k: object() for k in keys}
    offs = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)]
    assert M._cells_beside_held(keys, reg, offs) == [0, 1]
    assert M._cells_beside_held([(0, 0, 0), (5, 5, 5)],
                                {(0, 0, 0): 1, (5, 5, 5): 2}, offs) == []
    assert M._cells_beside_held([(0, 0, 0), (1, 1, 0)],
                                {(0, 0, 0): 1, (1, 1, 0): 2}, offs) == [0, 1]
