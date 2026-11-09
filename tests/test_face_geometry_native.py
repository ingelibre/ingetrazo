# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust face geometry (lazy meshes' drawing) is views.viewport.
_face_geometry bit for bit: QVector3D's own float32 arithmetic (length,
normalized, the plane axes), the Newell normal, the area, the centroid and
the very triangles of the earcut port — on convex, concave, holed,
collinear, sliver and degenerate faces. Skipped when the module is not
built or this Qt's hypot is not one the module knows."""
from __future__ import annotations

import math
import random
import sys

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

import core._native as _native
from core.mesh import Mesh
from core.triangulate import plane_axes, triangulate

nat = _native.available()
HYPOT = _native.qt_hypot() if nat is not None else None
pytestmark = pytest.mark.skipif(HYPOT is None,
                                reason="native module or hypot unknown")


def _f32(v):
    return [float(np.float32(c)) for c in v]


def test_qt_vector_arithmetic():
    rng = np.random.default_rng(3)
    rows = np.concatenate([
        rng.normal(size=(4000, 3)),
        rng.normal(size=(2000, 3)) * rng.choice(
            [1e-7, 1e-5, 1e-3, 1, 1e4], size=(2000, 1)),
        np.round(rng.normal(size=(2000, 3)) * 3) / 2,
        rng.normal(size=(1000, 3)) * [1, 0, 0] + [0, 1e-6, 0],
        [[1, 0, 0], [0, 0, 1], [1, 1, 0], [0, 0, 0], [1e-6, 0, 0],
         [0.70710677, 0.70710677, 0]],
    ]).astype(np.float32)
    ln, nz, pu, pv = nat.qt_vector_probe(rows, HYPOT)
    for i, r in enumerate(rows.tolist()):
        q = V(*r)
        assert float(ln[i]) == q.length(), r
        assert nz[i].tolist() == list(q.normalized().toTuple()), r
        if q.length() > 0:
            u, v = plane_axes(q)
            assert pu[i].tolist() == list(u.toTuple()), r
            assert pv[i].tolist() == list(v.toTuple()), r


def _polygon(rng):
    """A planar loop in a random plane: convex, star-shaped (concave) or
    with collinear points, sometimes with holes."""
    kind = rng.random()
    n = rng.randrange(3, 14)
    pts2 = []
    for k in range(n):
        a = 2 * math.pi * k / n
        r = 1.0 if kind < 0.3 else rng.choice([0.4, 1.0, 1.3])
        pts2.append((r * math.cos(a), r * math.sin(a)))
    if kind > 0.85:                      # a point on an edge's line
        x0, y0 = pts2[0]
        x1, y1 = pts2[1]
        pts2.insert(1, ((x0 + x1) / 2, (y0 + y1) / 2))
    holes2 = []
    if rng.random() < 0.35:
        for c in rng.sample([(0, 0), (0.25, 0.1), (-0.2, -0.2)],
                            rng.randrange(1, 3)):
            s = 0.08
            holes2.append([(c[0] - s, c[1] - s), (c[0] + s, c[1] - s),
                           (c[0] + s, c[1] + s), (c[0] - s, c[1] + s)])
    if rng.random() < 0.5:               # axis planes, as buildings are
        frame = rng.choice([((1, 0, 0), (0, 1, 0)), ((1, 0, 0), (0, 0, 1)),
                            ((0, 1, 0), (0, 0, 1)),
                            ((0.70710677, 0.70710677, 0), (0, 0, 1))])
    else:
        a = V(rng.random(), rng.random(), rng.random()).normalized()
        b = V.crossProduct(a, V(0.3, 0.2, 0.9)).normalized()
        frame = (a.toTuple(), b.toTuple())
    o = [rng.uniform(-500, 500) for _ in range(3)]
    s = rng.choice([0.01, 1.0, 37.0])

    def lift(p):
        return V(*(o[k] + s * (p[0] * frame[0][k] + p[1] * frame[1][k])
                   for k in range(3)))
    return [lift(p) for p in pts2], [[lift(p) for p in h] for h in holes2]


def _geometry_python(face):
    from views.viewport import _face_geometry
    return _face_geometry(face, None, triangulate)


@pytest.mark.parametrize("seed", range(6))
def test_face_geometry_is_the_python_one(seed):
    rng = random.Random(seed)
    m = Mesh()
    faces = []
    for _ in range(400):
        outer, holes = _polygon(rng)
        try:
            faces.append(m.add_face(outer, holes or None))
        except ValueError:
            continue
    # Dents a hair deep: the convexity test's 1e-9 decides fan or earcut.
    for k, dent in enumerate((1e-7, 4e-7, 2e-6, -3e-7)):
        x = 50.0 + 3 * k
        loop = [V(x, 0, 0), V(x + 0.25, dent, 0), V(x + 0.5, 0, 0),
                V(x + 0.5, 0.5, 0), V(x + 0.25, 0.5 - dent, 0),
                V(x, 0.5, 0)]
        for pts in (loop, [p + V(0, 2, 0) for p in reversed(loop)]):
            try:                         # both windings: both signs
                faces.append(m.add_face(pts))
            except ValueError:
                pass
    # Newell length within Qt's 1e-5 of 1 (area 0.5): normalized() keeps
    # the raw vector there, so the unit normal is not the divided one.
    for k, extra in enumerate((3e-6, -4e-6, 0.0, 2e-5)):
        a = V(0.6, 0.0, 0.8)
        b = V(0.0, 1.0, 0.0)
        o = V(80.0 + 3 * k, 0.0, 0.0)
        w = 0.5 * (1 + extra)
        try:
            faces.append(m.add_face([o, o + a, o + a + b * w, o + b * w]))
        except ValueError:
            pass
    # Round faces of many corners far from the origin: where Python's
    # compensated sum() (the centroid) parts from a plain one.
    for k in range(12):
        n = 24 + 8 * k
        c = V(731.3 + 7 * k, -418.9, 12.37)
        r = 0.37 + 0.11 * k
        try:
            faces.append(m.add_face([c + V(r * math.cos(2 * math.pi * j / n),
                                           r * math.sin(2 * math.pi * j / n),
                                           0.0) for j in range(n)]))
        except ValueError:
            pass
    # Corners whose coordinates cancel to ~0 (a part centred on the
    # origin, as in a real plant): the compensated sum leaves another last
    # bit than a plain one, and it survives the float32 centroid.
    for k, tiny in enumerate((-6.9e-18, 3.1e-17, -2.2e-16, 5e-19)):
        z = 0.5 * k
        try:                    # x: 0.25 + tiny - 0.25, plainly 0
            faces.append(m.add_face([V(0.25, 0.0, z), V(tiny, 1.0, z),
                                     V(-0.25, 0.5, z)]))
        except ValueError:
            pass
    # Slivers and a collapsed face, built straight from vertices.
    from core.mesh import Face
    a, b, c = (m.vertex(V(0, 0, 0)), m.vertex(V(1, 0, 0)),
               m.vertex(V(2, 1e-7, 0)))
    faces += [Face([a, b, c]), Face([a, b]), Face([a, b, a, b])]
    vid = {id(v): i for i, v in enumerate(m.vertices)}
    pos = np.array([v.position.toTuple() for v in m.vertices],
                   dtype=np.float32)
    corners, sizes, counts = [], [], []
    for f in faces:
        rings = [f.loop] + f.hole_loops
        counts.append(len(rings))
        for r in rings:
            sizes.append(len(r))
            corners.extend(vid[id(v)] for v in r)
    normal, ln, cen, tris, tri_face, unit, tris_u, tri_face_u = \
        nat.face_geometry(
        pos, np.array(corners, dtype=np.int64),
        np.array(sizes, dtype=np.int64), np.array(counts, dtype=np.int64),
        HYPOT, sys.version_info >= (3, 12))
    def per_face(tt, tf):
        out = [[] for _ in faces]
        for t, fi in zip(tt.tolist(), tf.tolist()):
            out[fi].append(tuple(tuple(m.vertices[i].position.toTuple())
                                 for i in t))
        return out
    by_face = per_face(tris, tri_face)
    differ = 0
    by_face_u = per_face(tris_u, tri_face_u)
    for i, f in enumerate(faces):
        g = _geometry_python(f)
        assert normal[i].tolist() == list(g[1].toTuple()), i
        assert 0.5 * float(ln[i]) == g[2], i
        if g[4] is None:
            assert np.isnan(cen[i]).all()
        else:
            assert cen[i].tolist() == list(g[4].toTuple()), i
        assert by_face[i] == [tuple(t) for t in g[3]], i
        # The viewport's _normal_of / _tris_of (textures, back sides).
        if len(f.loop) < 3:
            want_u = V(0.0, 0.0, 1.0)
        else:
            n = f._newell()
            want_u = n.normalized() if n.length() > 1e-9 else V(0, 0, 1)
        assert unit[i].tolist() == list(want_u.toTuple()), i
        differ += unit[i].tolist() != normal[i].tolist()
        want_t = f.triangulate(want_u) if len(f.loop) >= 3 else []
        assert by_face_u[i] == [tuple(tuple(p.toTuple()) for p in t)
                                for t in want_t], i
    assert differ, "some face where the two normals differ"
