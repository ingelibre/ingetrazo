# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Drawing on a solid that already has many features asks the model once.

Measured on a slab with sixty 32-sided cylinders raised on it (2000 faces,
5800 edges): the next circle took 0.96 s. The stroke's 32 sides each laid
out the model's whole edge graph again; every face of the model had its
plane worked out to learn it was not the new face's; each of the cap's
sixty openings was tried edge against edge with a circle nowhere near it;
and the overlap heal ran four array passes over the model per face.

Counted or compared with the plain way of asking, not timed.
"""
from __future__ import annotations

import math
import random

import numpy as np
from PySide6.QtGui import QVector3D

from core import topology
from core.edits import build_add_edges
from core.geometry import Edge
from core.topology import CycleGraph, find_cycles_through
from tests.test_pushpull_large_solid_cost import _slab_with_cylinders


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _circle_segments(cx, cy, z=3.0, r=0.4, n=32):
    pts = [V(cx + r * math.cos(2 * math.pi * k / n),
             cy + r * math.sin(2 * math.pi * k / n), z) for k in range(n)]
    return [(pts[k], pts[(k + 1) % n]) for k in range(n)]


def test_a_stroke_lays_the_edge_graph_out_once(monkeypatch):
    scene, _hist = _slab_with_cylinders(3)
    built = []
    real_init = CycleGraph.__init__

    def init(self, edges, key=topology._key):
        built.append(len(edges))
        real_init(self, edges, key)

    monkeypatch.setattr(CycleGraph, "__init__", init)
    monkeypatch.setattr(
        topology, "_cycle_adjacency",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the graph was laid out again for one segment")))
    faces_before = len(scene.faces)
    build_add_edges(scene, _circle_segments(1.0 + 3 * 1.8, 1.0))
    assert len(built) == 1
    assert len(scene.faces) == faces_before     # a plan changes nothing


def _grid_edges(n: int, rng: random.Random) -> list:
    """An n × n grid of unit squares with some diagonals and some gaps."""
    edges = []
    for i in range(n + 1):
        for j in range(n + 1):
            if i < n and rng.random() > 0.1:
                edges.append(Edge(V(i, j), V(i + 1, j)))
            if j < n and rng.random() > 0.1:
                edges.append(Edge(V(i, j), V(i, j + 1)))
            if i < n and j < n and rng.random() < 0.2:
                edges.append(Edge(V(i, j), V(i + 1, j + 1)))
    rng.shuffle(edges)
    return edges


def _same(a, b) -> bool:
    key = topology._key
    return [[key(p) for p in c] for c in a] == [[key(p) for p in c] for c in b]


def test_the_kept_graph_finds_the_cycles_the_fresh_one_finds():
    rng = random.Random(20261110)
    for _round in range(6):
        edges = _grid_edges(6, rng)
        graph = CycleGraph(edges)
        for _step in range(60):
            what = rng.random()
            if what < 0.25 and edges:
                gone = rng.choice(edges)
                edges.remove(gone)
                assert graph.remove(gone)
            elif what < 0.5:
                i, j = rng.randrange(6), rng.randrange(6)
                new = Edge(V(i, j), V(i + rng.choice((0, 1)), j + 1))
                edges.append(new)
                graph.add(new)
            a = V(rng.randrange(7), rng.randrange(7))
            b = V(a.x() + rng.choice((-1, 0, 1)), a.y() + rng.choice((-1, 1)))
            assert _same(find_cycles_through(edges, a, b, graph=graph),
                         find_cycles_through(edges, a, b))


def test_the_heal_pairs_faces_as_it_did_one_by_one():
    rng = np.random.default_rng(20261110)
    dirs = np.array([[0, 0, 1.0], [0, 0, -1.0], [1.0, 0, 0], [0, 1.0, 0],
                     [0.6, 0.8, 0], [0.0, 0.03, 0.9995]])
    for n in (1, 7, 300, 700):
        N = dirs[rng.integers(0, len(dirs), size=n)]
        A = np.round(rng.uniform(0.0, 4.0, size=n), 1)
        LO = np.round(rng.uniform(0.0, 3.0, size=(n, 3)), 1)
        HI = LO + np.round(rng.uniform(0.0, 3.0, size=(n, 3)), 1)
        got = topology._heal_partners(N, A, LO, HI)
        pad = topology._BOX_PAD
        for i in range(n):
            want = np.flatnonzero((np.abs(N @ N[i]) > 0.999) & (A < A[i])
                                  & (LO >= LO[i] - pad).all(axis=1)
                                  & (HI <= HI[i] + pad).all(axis=1))
            assert list(got.get(i, ())) == list(want)


def _cross_plain(a, b) -> bool:
    """``_loops_cross_2d`` as it was: every edge against every edge."""
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    eps = 1e-12
    for i in range(len(a)):
        p1, p2 = a[i], a[(i + 1) % len(a)]
        for j in range(len(b)):
            q1, q2 = b[j], b[(j + 1) % len(b)]
            d1, d2 = side(q1, q2, p1), side(q1, q2, p2)
            d3, d4 = side(p1, p2, q1), side(p1, p2, q2)
            if (((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps))
                    and ((d3 > eps and d4 < -eps)
                         or (d3 < -eps and d4 > eps))):
                return True
    return False


def test_outlines_cross_as_they_did_edge_by_edge():
    rng = random.Random(20261110)

    def ngon(cx, cy, r, n):
        return [(cx + r * math.cos(2 * math.pi * k / n),
                 cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]

    crossed = apart = 0
    for _ in range(400):
        a = ngon(rng.uniform(0, 3), rng.uniform(0, 3), rng.uniform(0.2, 1), 8)
        b = ngon(rng.uniform(0, 3), rng.uniform(0, 3), rng.uniform(0.2, 1), 5)
        want = _cross_plain(a, b)
        assert topology._loops_cross_2d(a, b) == want
        crossed += want
        apart += not want
    assert crossed > 50 and apart > 50
    # Touching boxes, nothing crossing; and boxes a hair apart.
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for dx in (1.0, 1.0 + 1e-12, 1.0 - 1e-12, 2.0):
        other = [(x + dx, y) for x, y in sq]
        assert topology._loops_cross_2d(sq, other) == _cross_plain(sq, other)


def test_a_circle_drawn_on_the_solid_lands_as_before():
    """The circle is one new face in a new opening of the cap, the model
    still one closed solid with nothing turned or marked."""
    from core.orient import is_closed, signed_volume

    scene, hist = _slab_with_cylinders(3)
    faces_before = len(scene.faces)
    volume = signed_volume(scene.mesh)
    cap = max((f for f in scene.mesh.faces if f.hole_loops),
              key=lambda f: len(f.hole_loops))
    holes_before = len(cap.hole_loops)
    hist.execute(build_add_edges(scene,
                                 _circle_segments(1.0 + 3 * 1.8, 1.0)))
    assert len(scene.faces) == faces_before + 1
    cap = max((f for f in scene.mesh.faces if f.hole_loops),
              key=lambda f: len(f.hole_loops))
    assert len(cap.hole_loops) == holes_before + 1
    assert is_closed(scene.mesh)
    assert not any(f.interior for f in scene.mesh.faces)
    assert abs(signed_volume(scene.mesh) - volume) < 1e-6
