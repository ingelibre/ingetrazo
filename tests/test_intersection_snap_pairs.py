# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The green X where two edges cross (``core.snap._intersection_snap``)
asks ``segment_intersection`` only for pairs whose boxes come close
(``_pairs_that_may_meet``) and occlusion only nearest first, until a
crossing in sight. Same answer as asking every pair and every crossing:
the nearest visible one, the first of equals — over grids, guides of
10 km, skew pairs, touching ends and hidden points. A point many pairs
meet at is asked once, and with ``are_occluded`` in batches."""
from __future__ import annotations

import math
import random
from types import SimpleNamespace

from PySide6.QtGui import QVector3D as V

from core import snap
from core.topology import segment_intersection


def _reference(cx, cy, scene, world_to_pixel, et, is_occluded):
    """The rule as it was: every pair, every crossing asked."""
    near = []
    for edge in scene.edges:
        if getattr(edge, "center", False):
            continue
        ab = edge.b - edge.a
        if V.dotProduct(ab, ab) < 1e-12:
            continue
        pa, pb = world_to_pixel(edge.a), world_to_pixel(edge.b)
        if pa is None or pb is None:
            continue
        d, _t = snap._closest_on_segment_2d((cx, cy), pa, pb)
        if d <= et:
            near.append(edge)
    if len(near) < 2:
        return None
    best = None
    for i in range(len(near)):
        for j in range(i + 1, len(near)):
            e1, e2 = near[i], near[j]
            hit = segment_intersection(e1.a, e1.b, e2.a, e2.b)
            if hit is None:
                continue
            hp = world_to_pixel(hit)
            if hp is None:
                continue
            dh = math.hypot(hp[0] - cx, hp[1] - cy)
            if dh > et:
                continue
            if is_occluded is not None and is_occluded(hit):
                continue
            if best is None or dh < best[0]:
                best = (dh, hit, e1, e2)
    if best is None:
        return None
    hit = best[1]
    corners = (best[2].a, best[2].b, best[3].a, best[3].b)
    kind = ("endpoint" if any((hit - c).lengthSquared() < 1e-12
                              for c in corners) else "intersection")
    return hit, kind


def _edge(a, b):
    return SimpleNamespace(a=a, b=b)


def _scene(rng):
    edges = []
    # A grid on the floor sharing its corners, like a tiled slab.
    n, step = rng.randint(3, 8), rng.choice((0.5, 1.0, 1.7))
    for k in range(n + 1):
        edges.append(_edge(V(0, k * step, 0), V(n * step, k * step, 0)))
        edges.append(_edge(V(k * step, 0, 0), V(k * step, n * step, 0)))
    # Long guides through the middle, both crossing and skew.
    for _ in range(rng.randint(1, 4)):
        p = V(rng.uniform(0, n * step), rng.uniform(0, n * step),
              rng.choice((0.0, 0.0, rng.uniform(0.1, 2))))
        ang = rng.uniform(0, math.pi)
        d = V(math.cos(ang), math.sin(ang), 0) * 1e4
        edges.append(_edge(p - d, p + d))
    # Loose sticks, some through the grid, some above it.
    for _ in range(rng.randint(5, 25)):
        a = V(rng.uniform(-1, n * step + 1), rng.uniform(-1, n * step + 1),
              rng.choice((0.0, rng.uniform(-1, 2))))
        b = a + V(rng.uniform(-3, 3), rng.uniform(-3, 3),
                  rng.choice((0.0, rng.uniform(-1, 1))))
        edges.append(_edge(a, b))
    # One that ends exactly on a grid line.
    edges.append(_edge(V(step, step, 0), V(step, step, 2)))
    rng.shuffle(edges)
    return SimpleNamespace(edges=edges), n * step


def _view(rng, size):
    """An oblique parallel view: x, y and a little z onto the screen."""
    s = 600 / max(size, 1e-6) * rng.uniform(0.3, 1.5)
    kz = rng.uniform(-0.5, 0.5)

    def to_px(p):
        return (100 + s * (p.x() + 0.3 * p.y()),
                700 - s * (p.y() * 0.8 + kz * p.z()))
    return to_px


def test_the_nearest_visible_crossing_is_the_one_every_pair_gave():
    rng = random.Random(158)
    asked = [0, 0, 0]
    calls = [0]
    seen = 0
    for trial in range(400):
        scene, size = _scene(rng)
        to_px = _view(rng, size)
        hidden = set(rng.sample(range(97), rng.randint(0, 60)))

        def occl(p, k):
            asked[k] += 1
            key = (round(p.x(), 3) * 7 + round(p.y(), 3) * 13) % 97
            return round(key) in hidden

        for _ in range(6):
            tx = rng.uniform(-0.5, size + 0.5)
            ty = rng.uniform(-0.5, size + 0.5)
            cx, cy = to_px(V(tx, ty, 0))
            cx += rng.uniform(-6, 6)
            cy += rng.uniform(-6, 6)
            et = rng.choice((6.0, 12.0, 30.0))
            want = _reference(cx, cy, scene, to_px, et,
                              lambda p: occl(p, 0))
            got = snap._intersection_snap(cx, cy, scene, to_px, et,
                                          lambda p: occl(p, 1))

            def batch(ps):
                calls[0] += 1
                return [occl(p, 2) for p in ps]

            def one(p):
                calls[0] += 1
                return occl(p, 2)

            got_b = snap._intersection_snap(cx, cy, scene, to_px, et,
                                            one, batch)
            assert (got is None) == (got_b is None), trial
            if got is not None:
                assert got_b.point == got.point and got_b.kind == got.kind
            if want is None:
                assert got is None, trial
                continue
            seen += 1
            assert got is not None, trial
            assert (got.point.x(), got.point.y(), got.point.z()) == \
                (want[0].x(), want[0].y(), want[0].z()), trial
            assert got.kind == want[1], trial
            got_free = snap._intersection_snap(cx, cy, scene, to_px, et,
                                               None)
            want_free = _reference(cx, cy, scene, to_px, et, None)
            assert got_free.point == want_free[0]
    assert seen > 300
    assert asked[1] < asked[0]              # fewer rays
    assert asked[2] >= asked[1]             # a batch asks past the first
    assert calls[0] < asked[2]              # in fewer calls


def test_only_pairs_far_apart_are_left_out():
    rng = random.Random(7)
    for _ in range(200):
        scene, _size = _scene(rng)
        edges = scene.edges
        kept = set(snap._pairs_that_may_meet(edges))
        order = list(snap._pairs_that_may_meet(edges))
        assert order == sorted(order)       # the pair loop's order
        for i in range(len(edges)):
            for j in range(i + 1, len(edges)):
                if segment_intersection(edges[i].a, edges[i].b,
                                        edges[j].a, edges[j].b) is not None:
                    assert (i, j) in kept
