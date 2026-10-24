# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Drawing on an exploded DWG plan froze IngeTrazo and then lost the line
(#491).

A flat drawing with curves rebuilds its faces on every stroke. On a plan of
16 848 loose edges that rebuild tested every pair of segments (70 s), then
re-stamped curve flags against every flagged edge (218 s), then the overlap
heal tested every pair of faces (95 s) -- and when it finally got there, an
edge a hair shorter than the weld raised and rolled the stroke back. Each
filter here must give the answer the full scan gave, so every test compares
against it."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.arrangement as ar  # noqa: E402
from core.arrangement import planar_rebuild  # noqa: E402
from core.history import RebuildPlanarFacesCommand, _segment_grid  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.topology import _box_grid, _point_on_seg_incl  # noqa: E402

# A square cut by two verticals whose feet land 0.02 mm apart, astride a
# 0.1 mm line of the arrangement's grid: two keys, one welded vertex.
_HAIR = (((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 1), (0, 1)),
         ((0, 1), (0, 0)), ((0.50014, -0.5), (0.50014, 0.0)),
         ((0.50016, 0.5), (0.50016, -0.3)))


def _hair_scene():
    scene = Scene()
    for a, b in _HAIR:
        scene.mesh.add_edge(V(a[0], a[1], 0), V(b[0], b[1], 0))
    return scene


def test_the_drawing_really_rebuilds_an_edge_the_mesh_welds():
    scene = _hair_scene()
    edges, _faces = planar_rebuild(
        [(e.v0.position, e.v1.position) for e in scene.mesh.edges],
        V(0, 0, 0), V(0, 0, 1))
    probe = Mesh()
    assert any(probe.vertex(a) is probe.vertex(b) for a, b in edges)


def test_a_hair_short_edge_is_dropped_instead_of_undoing_the_stroke():
    scene = _hair_scene()
    before = scene.mesh.capture_state()
    cmd = RebuildPlanarFacesCommand()
    cmd.do(scene)                                 # raised ValueError
    assert cmd.rebuilt == 1
    assert all(e.v0 is not e.v1 for e in scene.mesh.edges)
    for f in scene.mesh.faces:
        loop = f.vertices
        assert all(loop[i] != loop[(i + 1) % len(loop)]
                   for i in range(len(loop)))
    cmd.undo(scene)
    assert scene.mesh.capture_state().keys() == before.keys()
    assert len(scene.mesh.edges) == len(_HAIR)


def _full_scan_graph(segments_2d):
    n = len(segments_2d)
    split_pts = [list(seg) for seg in segments_2d]
    for i in range(n):
        a, b = segments_2d[i]
        for j in range(n):
            if i != j:
                c, d = segments_2d[j]
                for p in ar._intersections(a, b, c, d):
                    if ar._on_seg(p, a, b) is not None:
                        split_pts[i].append(p)
    coords: dict = {}
    adj: dict = {}
    for i in range(n):
        a, b = segments_2d[i]
        pts = split_pts[i]
        pts.sort(key=lambda p: ar._on_seg(p, a, b) or 0.0)
        keys = []
        for p in pts:
            k = ar._key(p[0], p[1])
            if k not in coords:
                coords[k] = (p[0], p[1])
                adj[k] = set()
            keys.append(k)
        for ka, kb in zip(keys, keys[1:]):
            if ka != kb:
                adj[ka].add(kb)
                adj[kb].add(ka)
    return coords, adj


def test_the_box_filter_builds_the_graph_the_full_scan_built():
    rng = random.Random(491)
    for _ in range(150):
        scale = rng.choice([1e-3, 0.05, 1.0, 30.0, 2000.0])
        segs = []
        for _ in range(rng.randint(2, 40)):
            a = (rng.uniform(0, scale), rng.uniform(0, scale))
            kind = rng.random()
            if kind < 0.2:
                b = (a[0] + rng.uniform(-scale, scale), a[1])
            elif kind < 0.3:
                b = (a[0], a[1] + rng.choice([1e-5, 1e-4, 2e-4]))
            elif kind < 0.45 and segs:
                c, d = rng.choice(segs)
                t, u = rng.uniform(-0.5, 1.5), rng.uniform(-0.5, 1.5)
                a = (c[0] + t * (d[0] - c[0]), c[1] + t * (d[1] - c[1]))
                b = (c[0] + u * (d[0] - c[0]), c[1] + u * (d[1] - c[1]))
            else:
                b = (rng.uniform(0, scale), rng.uniform(0, scale))
            if a != b:
                segs.append((a, b))
        coords, adj = ar._build_graph(segs)
        ref_coords, ref_adj = _full_scan_graph(segs)
        assert list(coords.items()) == list(ref_coords.items())
        assert adj == ref_adj


def test_the_flag_grid_never_misses_an_edge_the_point_lies_on():
    rng = random.Random(7)
    for _ in range(60):
        scale = rng.choice([1e-3, 0.1, 1.0, 50.0, 3000.0])
        n = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        n = n / n.length()
        u = V.crossProduct(n, V(0.3, 0.5, 0.8))
        u = u / u.length()
        w = V.crossProduct(n, u)
        o = V(rng.uniform(-scale, scale), rng.uniform(-scale, scale), 0.0)
        segs = []
        for _ in range(rng.randint(1, 40)):
            x, y = rng.uniform(0, scale), rng.uniform(0, scale)
            length = scale * rng.choice([1e-5, 1e-4, 0.01, 0.3, 1.0])
            dx, dy = rng.uniform(-1, 1), rng.uniform(-1, 1)
            segs.append((o + u * x + w * y,
                         o + u * (x + length * dx) + w * (y + length * dy)))
        near = _segment_grid(segs)
        for a, b in segs:
            for t in (-2e-4, 0.0, rng.random(), 1.0, 1.0 + 2e-4):
                p = a + (b - a) * t + n * rng.uniform(-1e-4, 1e-4)
                found = list(near(p))
                assert found == sorted(found)
                for i, (fa, fb) in enumerate(segs):
                    if _point_on_seg_incl(p, fa, fb):
                        assert i in found


def test_the_box_grid_meets_exactly_the_boxes_the_full_scan_meets():
    rng = np.random.default_rng(3)
    for trial in range(80):
        n = int(rng.integers(1, 200))
        scale = float(rng.choice([1e-3, 1.0, 100.0, 5000.0]))
        lo = rng.uniform(0, scale, (n, 3))
        if trial % 3 == 0:
            lo[:, 2] = 0.0
        size = rng.choice([0, 1e-5, 0.01, 0.3, 1.0], size=(n, 1)) * scale
        hi = lo + size * rng.uniform(0, 1, (n, 3))
        if trial % 2:
            hi[rng.random(n) < 0.05] *= 3.0          # a few long walls
        meeting = _box_grid(lo, hi)
        for i in range(n):
            full = np.flatnonzero((hi >= lo[i]).all(axis=1)
                                  & (lo <= hi[i]).all(axis=1)).tolist()
            assert meeting(i) == full
