# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust parity rays (core.orient.ray_parity_outside, behind orientation
and the push/pull rebuild) must count exactly what the NumPy code counts:
ray by ray over random triangle soups — rays through vertices and along
edges of human-valued coordinates, masks, a skipped face, sets big enough
for the NumPy side's own index — and then whole orientation passes on
random solids. Skipped when the module is not built."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("INGETRAZO_RUST", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402

import core._native as _native  # noqa: E402
from core import orient  # noqa: E402

pytestmark = pytest.mark.skipif(_native.native is None,
                                reason="native module not built")


def _soup(rng, n, grid):
    """``n`` triangles; on ``grid`` their corners sit on a 0.5 lattice, so
    rays meet shared edges and vertices exactly."""
    a, b, c, idx = [], [], [], []
    for i in range(n):
        if grid:
            p = [QVector3D(*(rng.randrange(-8, 9) * 0.5 for _ in range(3)))
                 for _ in range(3)]
        else:
            o = [rng.uniform(-5, 5) for _ in range(3)]
            p = [QVector3D(*(o[k] + rng.uniform(-2, 2) for k in range(3)))
                 for _ in range(3)]
        a.append(p[0])
        b.append(p[1])
        c.append(p[2])
        idx.append(i // 2)
    lists = {}
    for i in range(n):
        lists.setdefault(idx[i], []).append((a[i], b[i], c[i]))
    return orient._pack_lists([lists[k] for k in sorted(lists)])


def _counts(monkeypatch, use_native, origin, direction, packed, mask, skip,
            seed):
    monkeypatch.setattr(_native, "native",
                        _native.available() if use_native else None)
    return orient.ray_parity_outside(origin, direction, None,
                                     random.Random(seed), packed=packed,
                                     mask=mask, skip=skip)


@pytest.mark.parametrize("seed", range(10))
def test_same_verdicts_as_numpy(monkeypatch, seed):
    rng = random.Random(seed)
    grid = seed % 2 == 0
    # Above orient._BVH_MIN_TRIS the NumPy side uses its own index: both.
    n = rng.choice([40, 300, 2600])
    packed = _soup(rng, n, grid)
    nf = int(packed.face_idx.max()) + 1
    for q in range(60):
        if grid:
            o = QVector3D(*(rng.randrange(-8, 9) * 0.5 for _ in range(3)))
            d = QVector3D(*(rng.choice([-1, 0, 0, 1]) for _ in range(3)))
            if d.length() == 0:
                d = QVector3D(0, 0, 1)
        else:
            o = QVector3D(*(rng.uniform(-6, 6) for _ in range(3)))
            d = QVector3D(*(rng.uniform(-1, 1) for _ in range(3)))
        mask = None if q % 3 else (np.array(
            [rng.random() < 0.7 for _ in range(len(packed.a))]))
        skip = rng.randrange(nf) if q % 2 else None
        want = _counts(monkeypatch, False, o, d, packed, mask, skip, q)
        got = _counts(monkeypatch, True, o, d, packed, mask, skip, q)
        assert got == want, (q, want, got)


def test_raw_counts_match(monkeypatch):
    """Below the vote: the crossing counts themselves, ray by ray."""
    rng = random.Random(7)
    packed = _soup(rng, 3000, True)
    nt = _native.available().ParityTris(packed.a, packed.e1, packed.e2,
                                        packed.face_idx)
    for _ in range(200):
        o = QVector3D(*(rng.randrange(-8, 9) * 0.5 for _ in range(3)))
        # Jittered around one axis-aligned or diagonal direction, as the
        # vote casts them (the NumPy index is built for that spread).
        n = QVector3D(*(rng.choice([-1, 0, 1]) for _ in range(3)))
        if n.length() == 0:
            continue
        n = n.normalized()
        u, v = orient._basis(n)
        rays = [n] + [(n + u * rng.uniform(-3e-4, 3e-4)
                       + v * rng.uniform(-3e-4, 3e-4)).normalized()
                      for _ in range(6)]
        want = orient._python_crossings(o, n, rays, packed, None, None)
        dirs = np.array([[r.x(), r.y(), r.z()] for r in rays])
        got = nt.crossings((o.x(), o.y(), o.z()), dirs)
        assert got == want


def _solid_mesh(rng):
    """A few boxes welded into one mesh, some touching, some turned over
    at random (the job orientation does)."""
    from core.mesh import Mesh
    m = Mesh()
    for _ in range(rng.randrange(1, 5)):
        x, y, z = (rng.randrange(-3, 3) for _ in range(3))
        w, d, h = (rng.randrange(1, 4) for _ in range(3))
        P = [QVector3D(x + i * w, y + j * d, z + k * h)
             for k in (0, 1) for j in (0, 1) for i in (0, 1)]
        for quad in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                     (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
            pts = [P[i] for i in quad]
            if rng.random() < 0.4:
                pts.reverse()
            try:
                m.add_face(pts)
            except ValueError:
                pass
    return m


@pytest.mark.parametrize("seed", range(12))
def test_orient_outward_same_result(monkeypatch, seed):
    results = []
    for use in (False, True):
        m = _solid_mesh(random.Random(seed))
        monkeypatch.setattr(_native, "native",
                            _native.available() if use else None)
        flipped = orient.orient_outward(m)
        results.append((sorted(m.faces.index(f) for f in flipped),
                        [f.interior for f in m.faces],
                        [[v.toTuple() for v in f.vertices] for f in m.faces]))
    assert results[0] == results[1]


def test_rays_starting_on_and_just_off_a_face(monkeypatch):
    """The probes of orientation sit ON a face and those of the rebuild
    1 mm off one: rays that start at, just behind or just past a triangle
    (t around the test's 1e-6 floor)."""
    rng = random.Random(11)
    packed = _soup(rng, 600, False)
    nt = _native.available().ParityTris(packed.a, packed.e1, packed.e2,
                                        packed.face_idx)
    checked = 0
    for _ in range(400):
        r = rng.randrange(len(packed.a))
        a, e1, e2 = packed.a[r], packed.e1[r], packed.e2[r]
        s, t = rng.random() * 0.5, rng.random() * 0.5
        on = a + e1 * s + e2 * t
        n = np.cross(e1, e2)
        if np.linalg.norm(n) < 1e-9:
            continue
        n = n / np.linalg.norm(n)
        back = rng.choice([0.0, 5e-7, 2e-6, 1e-4, 1e-3, -5e-7, -2e-6])
        o = on - n * back
        d = QVector3D(*n)
        rays = [d]
        want = orient._python_crossings(QVector3D(*o), d, rays, packed,
                                        None, None)
        got = nt.crossings(tuple(o), np.array([n]))
        assert got == want, (back, want, got)
        checked += 1
    assert checked > 300
