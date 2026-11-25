# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Image attachment skips the placements whose subtree lies elsewhere: the
answer is the plain walk's, and a forest of cut-outs does not walk the whole
file once per image."""
from __future__ import annotations

import random
from types import SimpleNamespace as NS

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

from formats import skp_openskp as adapter
from tests.test_skp_image_bounds import panel, quad


def _ins(ref, m):
    m = np.asarray(m, dtype=float)
    # The file's own order: three rows of the rotation, then the offset.
    return NS(ref_idx=ref, matrix=[*m[:3, :3].T.ravel(), *m[:3, 3], 1.0])


def _random_matrix(r):
    a, b = r.uniform(0, 6.3), r.uniform(0, 6.3)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0],
                   [0, 0, 1.0]])
    rx = np.array([[1.0, 0, 0], [0, np.cos(b), -np.sin(b)],
                   [0, np.sin(b), np.cos(b)]])
    m = np.eye(4)
    m[:3, :3] = rz @ (rx if r.random() < .5 else np.eye(3)) @ np.diag(
        [r.choice((-1, 1)) * r.choice((.01, .5, 1, 3, 40)) for _ in "xyz"])
    if r.random() < .3:
        m[0, 1] += r.uniform(-2, 2)                     # sheared
    m[:3, 3] = [r.uniform(-300, 300) for _ in "xyz"]
    return m


def _plain(monkeypatch, *args):
    """The walk that enters every placement."""
    def everything(defn, by_id, cache, stack=frozenset()):
        kids = []
        for ins in defn.instances:
            kids.append((by_id[ins.ref_idx], np.array(
                adapter._matrix(ins.matrix).data(),
                dtype=float).reshape(4, 4, order="F")))
        n = len(kids)
        return kids, np.full((n, 3), -np.inf), np.full((n, 3), np.inf)
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "_placed_boxes", everything)
        return adapter._rests_on_a_face(*args)


def test_the_answer_is_the_plain_walks(monkeypatch):
    yes = 0
    for seed in range(300):
        r = random.Random(seed)
        defs = {i: panel(i, r.uniform(-30, 30)) for i in range(1, 7)}
        for i in range(1, 6):
            defs[i].instances = [
                _ins(r.randint(i + 1, 6), _random_matrix(r))
                for _ in range(r.randint(0, 3))]
        roots, cache = [defs[1]], {}
        # An image put on a face of the tree, or a little off it.
        for _ in range(6):
            d, m = defs[1], np.eye(4)
            while d.instances and r.random() < .8:
                ins = r.choice(d.instances)
                m = m @ np.array(adapter._matrix(ins.matrix).data(),
                                 dtype=float).reshape(4, 4, order="F")
                d = defs[ins.ref_idx]
            pos, _raw, _meta = adapter._defn_geom(d)
            c = pos.mean(axis=0)
            corners = np.array([c + (p - c) * .3 for p in pos])
            w = corners @ m[:3, :3].T + m[:3, 3]
            n = np.cross(w[1] - w[0], w[2] - w[0])
            n = n / (np.linalg.norm(n) or 1)
            w = w + n * r.choice((0, .004, .0099, .0101, .5))
            args = roots, defs, [V(*p) for p in w]
            got = adapter._rests_on_a_face(*args, cache)
            assert got == _plain(monkeypatch, *args), seed
            yes += got
    assert yes > 200


@pytest.mark.parametrize("x, hit", [(0.0, True), (700.0, False)])
def test_far_placements_are_not_entered(monkeypatch, x, hit):
    """500 placements side by side: an image reaches at most its own."""
    leaf = panel(2)
    root = NS(id=1, vertices={}, edges={}, faces={}, instances=[
        _ins(2, np.array([[1, 0, 0, k * 60], [0, 1, 0, 0], [0, 0, 1, 0],
                          [0, 0, 0, 1]])) for k in range(500)])
    seen = []
    inv = np.linalg.inv
    monkeypatch.setattr(np.linalg, "inv",
                        lambda m: (seen.append(1), inv(m))[1])
    cache = {}
    assert adapter._rests_on_a_face([root], {1: root, 2: leaf}, quad(x),
                                    cache) is hit
    assert len(seen) < 10


def test_a_cycle_ends():
    a, b = panel(1), panel(2)
    a.instances, b.instances = [_ins(2, np.eye(4))], [_ins(1, np.eye(4))]
    assert adapter._rests_on_a_face([a], {1: a, 2: b}, quad())
    assert not adapter._rests_on_a_face([a], {1: a, 2: b}, quad(100.))
