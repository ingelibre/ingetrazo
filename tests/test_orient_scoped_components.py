# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``orient_outward(only=...)`` triangulates, packs and labels only the
components of the faces it is asked about (night of 19-11): every face
comes out wound, marked and flipped as when the whole mesh was packed and
labelled — boxes wound either way, touching boxes with partitions, an open
sheet beside them."""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QVector3D as V

import core.orient as orient
from core.mesh import Mesh


def _build(seed):
    rng = random.Random(seed)
    m = Mesh()
    for _ in range(rng.randint(1, 7)):
        x, y = rng.randint(0, 8), rng.randint(0, 8)
        w, d, h = rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 3)
        p = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + d, 0), V(x, y + d, 0)]
        q = [v + V(0, 0, h) for v in p]
        fs = [m.add_face(p[::-1]), m.add_face(q)]
        for i in range(4):
            j = (i + 1) % 4
            fs.append(m.add_face([p[i], p[j], q[j], q[i]]))
        for f in fs:
            if rng.random() < 0.3:
                f.loop.reverse()
    if rng.random() < 0.5:
        m.add_face([V(20, 0, 0), V(21, 0, 0), V(21, 1, 0), V(20, 1, 0)])
    return m


def _run(seed, monkeypatch, whole):
    m = _build(seed)
    rng = random.Random(seed + 7)
    faces = list(m.faces)
    only = rng.sample(faces, rng.randint(1, 3))
    with monkeypatch.context() as mp:
        if whole:
            # Every face labelled — and so triangulated and packed — as
            # before the pass was scoped.
            def everything(roots, live, lab, label, _m=m):
                lab.update(orient._face_components(_m))
                return label
            mp.setattr(orient, "_flood_components", everything)
        flipped = orient.orient_outward(m, seed=12345, only=only)
    at = {id(f): i for i, f in enumerate(faces)}
    return (sorted(at[id(f)] for f in flipped),
            [[(v.position.x(), v.position.y(), v.position.z())
              for v in f.loop] for f in m.faces],
            [f.interior for f in m.faces])


@pytest.mark.parametrize("seed", range(120))
def test_a_scoped_pass_is_the_whole_meshs(seed, monkeypatch):
    assert _run(seed, monkeypatch, False) == _run(seed, monkeypatch, True)


def test_the_cases_turn_and_mark_faces(monkeypatch):
    runs = [_run(s, monkeypatch, False) for s in range(120)]
    assert sum(bool(r[0]) for r in runs) > 60
    # Fewer cases mark a face interior since #1155: a wall of one box laid
    # against a box of another size (the two faces overlap but are not cut
    # to each other) is no longer read as a partition, because its edges
    # are seams of its own box (two faces each) and a seam's two faces are
    # on the same side. Thirteen of the 120 cases marked such walls before;
    # five still mark one, enough to compare both passes on.
    assert sum(any(r[2]) for r in runs) >= 5
