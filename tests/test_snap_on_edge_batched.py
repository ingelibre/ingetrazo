# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«On edge» asks the occlusion of its candidates nearest first, in batches.

Hovering with Line over the SPR of #158 cast a ray per edge in reach — 14 000
rays in 60 pointer moves, seconds a move — to keep only the nearest visible
one. The answer must stay that one; only the asking changes."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector3D

from core.snap import compute_snap


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _w2p(p: QVector3D):
    return (p.x() * 100.0, p.y() * 100.0)


def _scene():
    # 13 long parallel edges, one pixel apart, under the cursor: no corner,
    # midpoint or crossing within reach, so the edge rule decides.
    return SimpleNamespace(edges=[
        SimpleNamespace(a=V(-50, 0.01 * i), b=V(50, 0.01 * i), center=False)
        for i in range(13)])


def _hidden(p):
    return p.y() < 0.045           # the five nearest lie behind a wall


def _snap(**kw):
    cand = V(0.3, 0.0)
    return compute_snap(cand, _w2p(cand), _scene(), _w2p, threshold_px=9.0,
                        edge_threshold_px=14.0, is_occluded=kw.pop("one"),
                        **kw)


def test_the_nearest_visible_edge_wins_with_one_ray_alone():
    singles, batches = [], []

    def one(p):
        singles.append(p)
        return _hidden(p)

    def many(ps):
        batches.append(len(ps))
        return [_hidden(p) for p in ps]

    r = _snap(one=one, are_occluded=many)
    assert r.kind == "on_edge"
    assert abs(r.point.y() - 0.05) < 1e-4 and abs(r.point.x() - 0.3) < 1e-4
    assert len(singles) == 1                 # the nearest, alone
    assert batches == [8]                    # the next eight together


def test_without_a_batch_query_the_answer_is_the_same():
    asked = []

    def one(p):
        asked.append(p)
        return _hidden(p)

    r = _snap(one=one)
    assert r.kind == "on_edge" and abs(r.point.y() - 0.05) < 1e-4
    assert len(asked) == 6                   # five hidden, then the answer


def test_all_hidden_gives_no_edge():
    r = _snap(one=lambda p: True, are_occluded=lambda ps: [True] * len(ps))
    assert r is None or r.kind != "on_edge"
