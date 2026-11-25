# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Face components are labelled with NumPy instead of a Python union-find,
and a rebuild narrowed to the operation's solids floods only their
components (night of 19-11): the same partition of the faces, the same
rebuild scope — faces and edges, in order — and the same parity set as
with the union-find's labels."""
from __future__ import annotations

import random

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

from core.cap_rebuild import RebuildCache
from core.mesh import Mesh
from core.orient import _face_components


def _union_find(mesh) -> dict:
    """The labelling before."""
    idx = {f: i for i, f in enumerate(mesh.faces)}
    parent = list(range(len(mesh.faces)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in mesh.edges:
        it = iter(e.faces)
        first = next((idx[f] for f in it if f in idx), None)
        if first is None:
            continue
        for f in it:
            j = idx.get(f)
            if j is not None:
                ra, rb = find(first), find(j)
                if ra != rb:
                    parent[ra] = rb
    return {f: find(i) for f, i in idx.items()}


def _build(seed):
    rng = random.Random(seed)
    m = Mesh()
    for _ in range(rng.randint(1, 6)):          # boxes, some touching
        x, y = rng.randint(0, 6), rng.randint(0, 6)
        w, d, h = rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 3)
        p = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + d, 0), V(x, y + d, 0)]
        q = [v + V(0, 0, h) for v in p]
        m.add_face(p[::-1])
        m.add_face(q)
        for i in range(4):
            j = (i + 1) % 4
            m.add_face([p[i], p[j], q[j], q[i]])
    for _ in range(rng.randint(0, 30)):         # loose quads, a strip
        x, y = rng.randint(0, 12), rng.randint(20, 24)
        m.add_face([V(x, y, 0), V(x + 1, y, 0), V(x + 1, y + 1, 0),
                    V(x, y + 1, 0)])
    # A fin on a box edge: an edge with three faces.
    m.add_face([V(0, 0, 0), V(0, 1, 0), V(-1, 1, 0), V(-1, 0, 0)])
    for _ in range(rng.randint(0, 5)):          # faceless edges
        a = V(rng.randint(30, 40), 0, 0)
        m.add_edge(a, a + V(1, 1, 0))
    faces = list(m.faces)
    rng.shuffle(faces)
    for f in faces[:rng.randint(0, 3)]:         # dead faces still listed
        m.faces.remove(f)
    return m


def _partition(comp, faces):
    groups: dict = {}
    for f in faces:
        groups.setdefault(comp[f], []).append(id(f))
    return sorted(tuple(g) for g in groups.values())


@pytest.mark.parametrize("seed", range(40))
def test_the_same_components(seed):
    m = _build(seed)
    new, old = _face_components(m), _union_find(m)
    assert new.keys() == old.keys()
    assert _partition(new, m.faces) == _partition(old, m.faces)
    # The label names the component's first face.
    order = {f: i for i, f in enumerate(m.faces)}
    for f, c in new.items():
        assert c <= order[f]


@pytest.mark.parametrize("seed", range(40))
def test_the_same_scope(seed):
    m = _build(seed)
    rng = random.Random(seed + 1000)
    faces = list(m.faces)
    cache = RebuildCache()
    cache.seed_faces = set(rng.sample(faces, rng.randint(1, 3)))
    got = cache.scope(m)
    comp = _union_find(m)
    live = {comp[f] for f in cache.seed_faces if f in comp}
    want_f = [f for f in m.faces if comp.get(f) in live]
    fset = set(want_f)
    want_e = [e for e in m.edges
              if not e.faces or any(f in fset for f in e.faces)]
    assert got is not None
    assert [id(f) for f in got[0]] == [id(f) for f in want_f]
    assert [id(e) for e in got[1]] == [id(e) for e in want_e]


@pytest.mark.parametrize("seed", range(40))
def test_the_components_of_some_faces_are_the_union_finds(seed):
    """Flooded from some faces, the labels cover exactly those faces'
    components, split as the union-find splits them; asking again after
    more roots only adds components."""
    m = _build(seed)
    rng = random.Random(seed + 2000)
    faces = list(m.faces)
    old = _union_find(m)
    cache = RebuildCache()
    first = rng.sample(faces, rng.randint(1, 3))
    lab = dict(cache.components_of(m, first))
    want = {old[f] for f in first}
    assert set(lab) == {f for f in m.faces if old[f] in want}
    assert _partition(lab, lab) == _partition(old, lab)
    more = rng.sample(faces, rng.randint(1, 4))
    lab2 = cache.components_of(m, more)
    assert all(lab2[f] == c for f, c in lab.items())
    want |= {old[f] for f in more}
    assert set(lab2) == {f for f in m.faces if old[f] in want}
    assert _partition(lab2, lab2) == _partition(old, lab2)
    # A dead face is no root; a new token starts over.
    cache.token += 1
    gone = [f for f in faces if f not in set(m.faces)]
    assert all(f not in cache.components_of(m, gone) for f in gone)


@pytest.mark.parametrize("seed", range(20))
def test_the_packed_parity_set_is_the_same_by_either_labelling(seed):
    m = _build(seed)
    rng = random.Random(seed + 3000)
    faces = list(m.faces)
    roots = rng.sample(faces, rng.randint(1, 3))
    a, b = RebuildCache(), RebuildCache()
    full = a.components(m)
    part = b.components_of(m, roots)
    pa = a.packed(m, set(), {full[f] for f in roots})
    pb = b.packed(m, set(), {part[f] for f in roots}, part)
    for name in ("a", "e1", "e2"):
        assert np.array_equal(getattr(pa, name), getattr(pb, name))
