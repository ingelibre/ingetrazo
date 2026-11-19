# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «point of the hovered edge» reference of _from_point_snap asks
«hidden?» only of the edges in reach, nearest first, and stops at the first
one seen (19-11: 87 rays, ~110 ms, on a Move frame in a group of the Plaza).
The answer is the one of the old scan in scene order: the nearest visible
edge, the first in scene order among equals."""
from __future__ import annotations

import inspect
import random
import textwrap
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D

import core.snap as snap

_OLD_SCAN = '''        best_edge = None
        for edge in scene.edges:
            pa, pb = world_to_pixel(edge.a), world_to_pixel(edge.b)
            if pa is None or pb is None:
                continue
            d, t = _closest_on_segment_2d((cx, cy), pa, pb)
            if d <= threshold_px and (best_edge is None or d < best_edge[0]):
                point = _on_edge_point(edge, t, project_onto_line)
                if is_occluded is not None and is_occluded(point):
                    continue
                best_edge = (d, point)
'''


def _old_function():
    src = textwrap.dedent(inspect.getsource(snap._from_point_snap))
    a = src.index("        near = []")
    b = src.index("            break\n", a) + len("            break\n")
    src = src[:a] + _OLD_SCAN + src[b:]
    ns = dict(vars(snap))
    exec(compile(src, "<old _from_point_snap>", "exec"), ns)
    return ns["_from_point_snap"]


def _key(r):
    if r is None:
        return None
    p = r.point
    return (r.kind, round(p.x(), 9), round(p.y(), 9), round(p.z(), 9))


def _case(seed):
    rnd = random.Random(seed)
    edges = []
    for _ in range(rnd.randint(0, 60)):
        a = QVector3D(rnd.randint(-8, 8) * 0.5, rnd.randint(-8, 8) * 0.5,
                      rnd.choice((0.0, 0.0, 1.0)))
        b = QVector3D(a.x() + rnd.choice((-4, -2, 0, 2, 4)),
                      a.y() + rnd.choice((-4, -2, 0, 2, 4)), a.z())
        edges.append(SimpleNamespace(a=a, b=b, center=False,
                                     figure=rnd.random() < 0.05))
    hidden_ratio = rnd.choice((0.0, 0.5, 0.9, 1.0))
    hidden = {}

    def is_occluded(p):
        k = (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))
        if k not in hidden:
            hidden[k] = rnd.random() < hidden_ratio
        return hidden[k]

    def w2p(p):
        if p.z() > 0.5 and p.x() > 3.5:
            return None                      # off screen / behind the eye
        return (p.x() * 40.0, p.y() * 40.0 + p.z() * 3.0)

    cursor = (rnd.uniform(-160, 160), rnd.uniform(-160, 160))
    return edges, is_occluded, hidden, w2p, cursor


def _call(fn, case, occl):
    edges, _o, _h, w2p, (cx, cy) = case
    scene = SimpleNamespace(edges=edges)
    return fn(scene, QVector3D(-20.0, -20.0, 0.0), QVector3D(1.0, 0.0, 0.0),
              cx, cy, w2p, 12.0, occl, hovered_refs=True,
              line_dir=QVector3D(0.0, 1.0, 0.0))


@pytest.mark.parametrize("seed", range(300))
def test_the_same_answer_as_the_scan_in_scene_order(seed):
    case = _case(seed)
    old = _old_function()
    want = _call(old, case, case[1])      # fills the hidden table first
    got = _call(snap._from_point_snap, case, case[1])
    assert _key(got) == _key(want)


def _two_edges_at(ya, yb):
    # 0..8 m wide, the cursor over x = 5: corners and midpoints are out of
    # reach, so the point of an edge is the answer.
    return [SimpleNamespace(a=QVector3D(0, y, 0), b=QVector3D(8, y, 0),
                            center=False) for y in (ya, yb)]


def _edge_answer(edges, threshold=12.0):
    w2p = lambda p: (p.x() * 10.0, p.y() * 10.0)       # noqa: E731
    r = snap._from_point_snap(
        SimpleNamespace(edges=edges), QVector3D(-50, 0, 0),
        QVector3D(1, 0, 0), 50.0, 0.0, w2p, threshold, None,
        hovered_refs=True, line_dir=QVector3D(0, 1, 0))
    return None if r is None else round(r.point.y(), 6)


def test_ties_go_to_the_first_edge_in_scene_order():
    for _ in range(20):          # whatever the objects' order in memory
        assert _edge_answer(_two_edges_at(1.0, -1.0)) == 1.0
        assert _edge_answer(_two_edges_at(-1.0, 1.0)) == -1.0


def test_an_edge_exactly_at_the_reach_counts():
    # 1.25 m is 12.5 px exactly (binary floats), the reach given here.
    assert _edge_answer(_two_edges_at(1.25, 3.0), 12.5) == 1.25
    assert _edge_answer(_two_edges_at(1.5, 3.0), 12.5) is None


def test_hidden_is_asked_of_the_nearest_first_and_stops_at_the_first_seen():
    # Edges 0..8 m wide, the cursor over x = 5: an edge's point is at
    # x = 5, its corners and midpoint (asked later, as references) are not.
    edges = [SimpleNamespace(a=QVector3D(0, y, 0), b=QVector3D(8, y, 0),
                             center=False) for y in (0.9, 0.5, 0.7, 0.2, 0.4)]
    asked = []

    def occl(p):
        if abs(p.x() - 5.0) < 1e-6:
            asked.append(round(p.y(), 3))
        return round(p.y(), 3) == 0.2        # the nearest is hidden

    w2p = lambda p: (p.x() * 10.0, p.y() * 10.0)       # noqa: E731
    r = snap._from_point_snap(
        SimpleNamespace(edges=edges), QVector3D(-50, 0, 0),
        QVector3D(1, 0, 0), 50.0, 0.0, w2p, 12.0, occl,
        hovered_refs=True, line_dir=QVector3D(0, 1, 0))
    assert asked == [0.2, 0.4]
    assert r is not None
