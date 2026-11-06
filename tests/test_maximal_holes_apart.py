# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""_maximal_holes keeps its answer while asking _loop_inside_loop far less:
the boxes of two holes far apart settle it (#158)."""
import random

import pytest
from PySide6.QtGui import QVector3D as V

from core import topology
from core.topology import _HolesApart, _loop_inside_loop, _maximal_holes


def plain_answer(holes):
    """_maximal_holes as written before the boxes: every bigger hole asked."""
    def area(loop):
        a = 0.0
        n = len(loop)
        for i in range(n):
            a += loop[i].x() * loop[(i + 1) % n].y()
            a -= loop[(i + 1) % n].x() * loop[i].y()
        return abs(a) / 2.0
    areas = [area(h) for h in holes]
    keep = []
    for i, h in enumerate(holes):
        nrm = V.crossProduct(h[1] - h[0], h[2] - h[0])
        if nrm.length() < 1e-9:
            keep.append(h)
            continue
        nrm = nrm.normalized()
        if not any(j != i and areas[j] > areas[i] + 1e-6
                   and _loop_inside_loop(h, holes[j], nrm)
                   for j in range(len(holes))):
            keep.append(h)
    return keep


def ring(cx, cy, r, n=6, z=0.0, tilt=0.0, reverse=False, rng=None):
    import math
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        rr = r * (rng.uniform(0.4, 1.0) if rng else 1.0)
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        pts.append(V(x, y, z + tilt * x))
    return pts[::-1] if reverse else pts


def test_a_plate_of_holes_side_by_side_triangulates_nothing(monkeypatch):
    holes = [ring(float(x), float(y), 0.1 + 0.001 * (x + 7 * y))
             for x in range(8) for y in range(8)]
    calls = []
    real = _loop_inside_loop
    monkeypatch.setattr(topology, "_loop_inside_loop",
                        lambda *a: calls.append(1) or real(*a))
    assert len(_maximal_holes(holes)) == len(holes)
    assert not calls


def test_a_nested_hole_is_still_dropped():
    big = ring(0.0, 0.0, 1.0)
    small = ring(0.1, 0.1, 0.2)
    far = ring(5.0, 5.0, 0.3)
    assert _maximal_holes([small, far, big]) == [far, big]


def test_a_hole_touching_a_bigger_one_is_asked(monkeypatch):
    big = ring(0.0, 0.0, 1.0)
    near = ring(1.05, 0.0, 0.05)     # just outside: boxes within the margin?
    calls = []
    real = _loop_inside_loop
    monkeypatch.setattr(topology, "_loop_inside_loop",
                        lambda *a: calls.append(1) or real(*a))
    assert plain_answer([big, near]) == _maximal_holes([big, near])
    assert calls


def test_loops_off_the_plane_are_seen_along_the_normal():
    """A hole's plane and another's far apart in depth, one above the other
    along the normal: their boxes are apart, the test still says inside."""
    big = ring(0.0, 0.0, 1.0, z=5.0)
    small = ring(0.0, 0.0, 0.2, z=0.0)
    assert plain_answer([small, big]) == [big]
    assert _maximal_holes([small, big]) == [big]


@pytest.mark.parametrize("seed", range(40))
def test_same_answer_as_asking_every_hole(seed):
    rng = random.Random(seed)
    scale = rng.choice([0.01, 1.0, 50.0, 3000.0])
    tilt = rng.choice([0.0, 0.0, 0.3, 2.0])
    off = rng.choice([0.0, 0.0, 1e-4, 0.02])
    holes = []
    for _ in range(rng.randint(2, 25)):
        cx = rng.uniform(-3, 3) * scale
        cy = rng.uniform(-3, 3) * scale
        r = rng.choice([0.01, 0.1, 0.5, 2.0]) * scale
        holes.append(ring(cx, cy, r, n=rng.randint(3, 9),
                          z=rng.uniform(-off, off) * scale, tilt=tilt,
                          reverse=rng.random() < 0.5,
                          rng=rng if rng.random() < 0.5 else None))
    if seed % 5 == 0:                    # one exactly inside another's ring
        holes.append(list(holes[0]))
    if seed % 7 == 0:                    # degenerate: all points in a line
        holes.append([V(i, i, 0) for i in range(4)])
    want = plain_answer(holes)
    got = _maximal_holes(holes)
    assert [id(h) for h in got] == [id(h) for h in want]


def test_a_mix_of_sizes_is_not_tied_to_the_first_point():
    holes = [ring(0.0, 0.0, 0.2), ring(9.0, 0.0, 1.0)]
    apart = _HolesApart(holes)
    assert apart.maybe_around(0, V(0, 0, 1), [1]) == []
    assert apart.maybe_around(1, V(0, 0, 1), [0]) == []
    # Tilted so that seen along it the two are near: the bound widens.
    assert apart.maybe_around(0, V(1, 0, 0), [1]) == [1]


def test_an_empty_loop_fails_where_it_failed():
    holes = [ring(0.0, 0.0, 0.2), ring(0.0, 0.0, 1.0), []]
    assert _HolesApart(holes).maybe_around(0, V(0, 0, 1), [1, 2]) == [1, 2]
    with pytest.raises(IndexError):
        _maximal_holes(holes)
