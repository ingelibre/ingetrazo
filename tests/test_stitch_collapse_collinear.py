# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The stitch's collinear-vertex collapse goes on from where it was instead
of restarting after each collapse (night of 19-11): it collapses the very
same vertices in the very same order as the restarting loop, and leaves the
same mesh."""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QVector3D as V

from core.history import collapse_collinear
from core.mesh import Mesh


def _restarting(mesh):
    """The loop the stitch ran before."""
    while True:
        collapsed = False
        for v in list(mesh.vertices):
            if mesh.collapsible_vertex(v):
                mesh.collapse_vertex(v)
                collapsed = True
                break
        if not collapsed:
            break


def _build(seed):
    rng = random.Random(seed)
    m = Mesh()
    n = rng.randint(2, 5)
    for i in range(n):
        for j in range(n):
            loop = []
            # Each side of the cell gets 0-3 points along it.
            corners = [V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                       V(i, j + 1, 0)]
            for k in range(4):
                a, b = corners[k], corners[(k + 1) % 4]
                loop.append(a)
                for t in sorted(rng.sample([.25, .5, .75], rng.randint(0, 3))):
                    loop.append(a + (b - a) * t)
            m.add_face(loop)
    # Standing walls along some rows, sharing the floor's subdivided edges.
    for i in range(n):
        if rng.random() < .5:
            m.add_face([V(i, 0, 0), V(i + .5, 0, 0), V(i + 1, 0, 0),
                        V(i + 1, 0, 1), V(i, 0, 1)])
    # Loose chains: a straight one (collapses) and a bent one (does not).
    m.add_edge(V(0, -3, 0), V(1, -3, 0))
    m.add_edge(V(1, -3, 0), V(2, -3, 0))
    m.add_edge(V(0, -4, 0), V(1, -4, 0))
    m.add_edge(V(1, -4, 0), V(1, -5, 0))
    # A triangle with a point on one side: it collapses to three corners.
    m.add_face([V(10, 0, 0), V(10.5, 0, 0), V(11, 0, 0), V(10.5, 1, 0)])
    rng.shuffle(m.vertices)
    return m


def _key(p):
    return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))


def _state(m):
    verts = [_key(v.position) for v in m.vertices]
    edges = sorted(tuple(sorted((_key(e.v0.position), _key(e.v1.position))))
                   for e in m.edges)
    faces = sorted(tuple(_key(v.position) for v in f.loop) for f in m.faces)
    return verts, edges, faces


@pytest.mark.parametrize("seed", range(40))
def test_the_collapse_is_the_restarting_loop(seed, monkeypatch):
    runs = []
    for fn in (_restarting, collapse_collinear):
        m = _build(seed)
        order = []
        real = Mesh.collapse_vertex

        def spy(self, v, _real=real, _order=order):
            _order.append(_key(v.position))
            return _real(self, v)

        with monkeypatch.context() as mp:
            mp.setattr(Mesh, "collapse_vertex", spy)
            fn(m)
        runs.append((order, _state(m)))
    assert runs[0][0], "the case collapses nothing"
    assert runs[0] == runs[1]
