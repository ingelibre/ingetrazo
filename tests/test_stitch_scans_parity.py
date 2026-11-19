# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two scans of a push's cleanup do less work for the same answer (night
of 19-11): ``Mesh.dedupe_faces`` builds the edge cycle only of the faces
that share their lowest and highest corner with another, and
``orphaned_edges_at`` keys each corner once, read in place. Same faces
dropped (and kept, with their paint), same edges found, in order."""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QVector3D as V

from core import topology as T
from core.mesh import Mesh


def _dedupe_before(mesh):
    seen: dict = {}
    removed = 0
    for f in list(mesh.faces):
        sig = frozenset(
            frozenset((id(f.loop[i]), id(f.loop[(i + 1) % len(f.loop)])))
            for i in range(len(f.loop)))
        other = seen.get(sig)
        if other is None:
            seen[sig] = f
            continue
        drop, keep = ((other, f) if len(f.hole_loops) > len(other.hole_loops)
                      else (f, other))
        if drop.attrs and not keep.attrs:
            keep.attrs = dict(drop.attrs)
        mesh.remove_face(drop)
        seen[sig] = keep
        removed += 1
    return removed


def _orphans_before(edges, faces, vertices):
    vkeys = {T._key(v) for v in vertices}
    key = T.KeyMemo()
    face_edges: set = set()
    for f in faces:
        loops = [[key(p) for p in lp] for lp in (f.vertices, *f.holes)]
        if not any(k in vkeys for lk in loops for k in lk):
            continue
        for lk in loops:
            n = len(lk)
            face_edges.update(frozenset((lk[i], lk[(i + 1) % n]))
                              for i in range(n))
    out = []
    for e in edges:
        ka, kb = key(e.a), key(e.b)
        if (ka in vkeys or kb in vkeys) and frozenset((ka, kb)) not in face_edges:
            out.append(e)
    return out


def _build(seed):
    rng = random.Random(seed)
    m = Mesh()
    cells = []
    for i in range(rng.randint(3, 9)):
        x, y = (i % 3) * 2, (i // 3) * 2
        loop = [V(x, y, 0), V(x + 1, y, 0), V(x + 1, y + 1, 0), V(x, y + 1, 0)]
        f = m.add_face(loop)
        if rng.random() < .3:
            f.attrs["color"] = [rng.random(), .2, .3]
        cells.append(loop)
    # The same cycles again: plain, holed, wound the other way, painted.
    for loop in rng.sample(cells, rng.randint(1, len(cells))):
        x, y = loop[0].x(), loop[0].y()
        holes = ([[V(x + .3, y + .3, 0), V(x + .6, y + .3, 0),
                   V(x + .6, y + .6, 0), V(x + .3, y + .6, 0)]]
                 if rng.random() < .4 else None)
        g = m.add_face(loop[::-1] if rng.random() < .5 else loop, holes)
        if rng.random() < .4:
            g.attrs["color"] = [.1, .9, .1]
    # Loose edges, some touching the cells' corners.
    for _ in range(rng.randint(0, 6)):
        a = rng.choice(rng.choice(cells))
        b = a + V(rng.choice([-.5, .5]), 0, rng.choice([0, 1]))
        m.add_edge(*((a, b) if rng.random() < .5 else (b, a)))
    faces = list(m.faces)
    rng.shuffle(faces)
    m.faces[:] = faces
    return m, cells, rng


def _r(p):
    return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))


@pytest.mark.parametrize("seed", range(40))
def test_dedupe_drops_what_it_dropped(seed):
    runs = []
    for fn in (_dedupe_before, Mesh.dedupe_faces):
        m, _cells, _rng = _build(seed)
        n = fn(m)
        runs.append((n, [(tuple(_r(v.position) for v in f.loop),
                          len(f.hole_loops),
                          tuple(f.attrs.get("color") or ()))
                         for f in m.faces]))
    assert runs[0] == runs[1]


def test_the_dedupe_cases_drop_faces():
    assert sum(Mesh.dedupe_faces(_build(s)[0]) > 0 for s in range(40)) > 30


@pytest.mark.parametrize("seed", range(40))
def test_the_orphans_are_the_same(seed):
    m, cells, rng = _build(seed)
    for f in list(m.faces)[::3]:
        m.remove_face(f)                 # edges that now bound no face
    picks = [p for loop in rng.sample(cells, rng.randint(1, len(cells)))
             for p in loop]
    got = T.orphaned_edges_at(m.edges, m.faces, picks)
    want = _orphans_before(m.edges, m.faces, picks)
    assert [id(e) for e in got] == [id(e) for e in want]


def test_the_orphan_cases_find_edges():
    found = 0
    for seed in range(40):
        m, cells, rng = _build(seed)
        for f in list(m.faces)[::3]:
            m.remove_face(f)
        picks = [p for loop in cells for p in loop]
        found += bool(T.orphaned_edges_at(m.edges, m.faces, picks))
    assert found > 20
