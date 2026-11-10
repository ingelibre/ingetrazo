# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Make Faces over thousands of separate outlines asks each one little.

Measured: 8000 separate squares (the columns of a plan, text exploded to
lines) took 85 s, the window frozen. The arrangement tried every opening
against every face in turn, measuring the opening again each time. And
the splitting step looked for the corners inside an edge's box along the
axis where the box is thinnest — for an edge running askew on a flat
plan that is the height, where every corner of the plan is "inside".

Compared with the plain way of asking, and counted; not timed.
"""
from __future__ import annotations

import random

from PySide6.QtGui import QVector3D

from core import arrangement, make_faces
from core.arrangement import (_area_floor, _interior_point,
                              _point_in_polygon, _signed_area)
from core.mesh import Mesh


def _classify_plain(loops, coords) -> list:
    """``arrangement._classify`` as it was: every hole against every face."""
    faces, holes = [], []
    for loop in loops:
        xy = [coords[k] for k in loop]
        area = _signed_area(xy)
        floor = _area_floor(xy)
        if area > floor:
            faces.append((xy, area))
        elif area < -floor:
            holes.append((xy, -area))
    if not faces:
        return []
    if holes:
        holes.sort(key=lambda h: h[1], reverse=True)
        holes = holes[1:]
    faces.sort(key=lambda f: f[1])
    face_holes = [[] for _ in faces]
    for hxy, harea in holes:
        hp = _interior_point(hxy)
        for fi, (fxy, farea) in enumerate(faces):
            if (farea > harea + _area_floor(hxy)
                    and _point_in_polygon(hp, fxy)):
                face_holes[fi].append(hxy)
                break
    return [(fxy, hls) for (fxy, _a), hls in zip(faces, face_holes)]


def _rect(x0, y0, x1, y1, ccw=True):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return pts if ccw else pts[::-1]


def _nested_scene(rng: random.Random):
    """Rooms on a grid, some with rooms inside rooms inside rooms: each
    boundary once as a face (anticlockwise) and once as the opening it
    leaves in what surrounds it (clockwise), as the tracer hands them
    over, plus the one clockwise loop round everything."""
    coords: dict = {}
    loops: list = []

    def add(pts):
        keys = []
        for p in pts:
            coords[len(coords)] = p
            keys.append(len(coords) - 1)
        loops.append(keys)

    add(_rect(-5, -5, 500, 500, ccw=False))         # the unbounded outside
    add(_rect(-1, -1, 400, 400))                    # the sheet they stand on
    for i in range(12):
        for j in range(12):
            if rng.random() < 0.2:
                continue
            x, y = i * 30.0 + rng.uniform(0, 3), j * 30.0 + rng.uniform(0, 3)
            size = rng.uniform(8, 24)
            depth = rng.choice((1, 1, 2, 3))
            for d in range(depth):
                inset = d * size / (2 * depth + 1)
                r = (x + inset, y + inset, x + size - inset, y + size - inset)
                add(_rect(*r))
                add(_rect(*r, ccw=False))
    order = list(range(len(loops)))
    rng.shuffle(order)
    return [loops[k] for k in order], coords


def test_openings_land_in_the_faces_they_always_landed_in():
    rng = random.Random(20261110)
    nested = 0
    for _ in range(8):
        loops, coords = _nested_scene(rng)
        got = arrangement._classify(loops, coords)
        want = _classify_plain(loops, coords)
        assert got == want
        nested += sum(1 for _xy, holes in got if holes)
    assert nested > 100          # the comparison did see openings placed


def test_an_opening_is_measured_once_not_once_per_face(monkeypatch):
    coords: dict = {}
    loops: list = []
    for pts in ([_rect(-5, -5, 2000, 20, ccw=False), _rect(-1, -1, 1990, 12)]
                + [r for i in range(300)
                   for r in (_rect(i * 6, 0, i * 6 + 4, 4),
                             _rect(i * 6, 0, i * 6 + 4, 4, ccw=False))]):
        keys = []
        for p in pts:
            coords[len(coords)] = p
            keys.append(len(coords) - 1)
        loops.append(keys)
    asked = []
    real = arrangement._area_floor
    monkeypatch.setattr(arrangement, "_area_floor",
                        lambda xy: asked.append(1) or real(xy))
    out = arrangement._classify(loops, coords)
    assert sum(len(holes) for _xy, holes in out) == 300
    # Each loop's floor once to sort it, each opening's once to place it:
    # it was worked out again for every face the opening was tried against,
    # 300 x 300 times here.
    assert len(asked) <= 2 * len(loops)


def test_corners_inside_a_box_are_the_ones_a_plain_walk_finds():
    rng = random.Random(20261110)
    pts = [QVector3D(rng.randrange(40), rng.randrange(40),
                     rng.choice((0.0, 0.0, 0.0, 3.0)))
           for _ in range(1500)]
    index = make_faces._Sorted(pts)
    weld = make_faces._WELD
    for _ in range(200):
        a, b = rng.choice(pts), rng.choice(pts)
        lo = (min(a.x(), b.x()), min(a.y(), b.y()), min(a.z(), b.z()))
        hi = (max(a.x(), b.x()), max(a.y(), b.y()), max(a.z(), b.z()))
        want = {id(p) for p in pts
                if all(lo[k] - weld <= (p.x(), p.y(), p.z())[k] <= hi[k] + weld
                       for k in range(3))}
        assert {id(p) for p in index.inside(lo, hi)} == want


def test_a_flat_plan_does_not_walk_every_corner_for_each_edge(monkeypatch):
    """On a plan every corner has the edge's height, and for an edge that
    runs askew the height is where its box is thinnest: the search goes
    along the edge instead."""
    mesh = Mesh()
    for i in range(20):
        for j in range(20):
            x, y = i * 3.0, j * 3.0
            c = [QVector3D(x + 1, y, 0), QVector3D(x + 2, y + 1, 0),
                 QVector3D(x + 1, y + 2, 0), QVector3D(x, y + 1, 0)]
            for a, b in zip(c, c[1:] + c[:1]):
                mesh.add_edge(a, b)
    looked = []

    class Counted(list):
        def __getitem__(self, key):
            got = list.__getitem__(self, key)
            if isinstance(key, slice):
                looked.append(len(got))
            return got

    real = make_faces._Sorted.__init__

    def init(self, points):
        real(self, points)
        self._by = [(keys, Counted(ordered)) for keys, ordered in self._by]

    monkeypatch.setattr(make_faces._Sorted, "__init__", init)
    assert make_faces.faces_from_linework(mesh) == 400
    edges, corners = 1600, 1600
    # Each edge looks at the corners of its own row or column of diamonds;
    # walking them all was edges x corners.
    assert 0 < sum(looked) < 0.1 * edges * corners
