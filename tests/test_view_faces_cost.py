# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exporting a big model's view as SVG does not test every face against
every other.

Seen on a 1 035-object plaza: the SVG of the current view froze the
window six minutes. Each of its 90 000 faces was boxed against all the
others, every pair in front was clipped and joined in one union — 5 000
regions under the ground alone. Now a grid finds the overlapping boxes,
the faces a roof hides are dropped by the roof alone, and the covers are
taken away a batch at a time. Compared with the plain way, counted, not
timed."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("manifold3d")

from core import vista_caras as VC                      # noqa: E402
from core.vista_caras import FaceFill                   # noqa: E402


def _brute(lo, hi, opaque, i):
    m = (opaque & (lo[:, 0] < hi[i, 0]) & (hi[:, 0] > lo[i, 0])
         & (lo[:, 1] < hi[i, 1]) & (hi[:, 1] > lo[i, 1]))
    m[i] = False
    return np.flatnonzero(m)


def _boxes(rng, n):
    lo = rng.uniform(0, 10, size=(n, 2))
    size = rng.exponential(0.2, size=(n, 2))
    size[: n // 50] = rng.uniform(3, 9, size=(n // 50, 2))   # big ones
    # Boxes on a lattice: edges falling exactly on cell edges and on each
    # other, boxes that only touch, boxes of no width.
    lo[n // 3: n // 2] = np.round(lo[n // 3: n // 2] * 4) / 4
    size[n // 3: n // 2] = np.round(size[n // 3: n // 2] * 4) / 4
    return lo, lo + size


def test_the_grid_finds_the_overlapping_boxes_testing_all_of_them_does():
    rng = np.random.default_rng(20261111)
    lo, hi = _boxes(rng, 3000)
    opaque = rng.random(len(lo)) > 0.1
    grid = VC._OverlapGrid(lo, hi, opaque)
    assert len(grid.big) > 0 and grid.is_big.sum() < len(lo)
    found = 0
    for i in range(len(lo)):
        got = grid.overlapping(i)
        want = _brute(lo, hi, opaque, i)
        assert got.dtype.kind == "i" and np.array_equal(got, want), i
        found += len(want)
    assert found > 5000


def test_the_grid_does_not_test_every_face_against_every_other(monkeypatch):
    rng = np.random.default_rng(4)
    lo, hi = _boxes(rng, 4000)
    grid = VC._OverlapGrid(lo, hi, np.ones(len(lo), dtype=bool))
    tested = []
    real = VC._OverlapGrid._test

    def counted(self, i, cand):
        tested.append(len(cand))
        return real(self, i, cand)

    monkeypatch.setattr(VC._OverlapGrid, "_test", counted)
    for i in range(len(lo)):
        grid.overlapping(i)
    # Every face against every other: 4000 × 4000.
    assert sum(tested) < 0.1 * len(lo) ** 2


def _clip_plain(ring, dq):
    """``_clip_half`` as it was: corner by corner."""
    v = ring @ dq[:2] + dq[2]
    keep = v > 0.0
    if keep.all():
        return ring
    if not keep.any():
        return ring[:0]
    out = []
    n = len(ring)
    for k in range(n):
        m = (k + 1) % n
        if keep[k]:
            out.append(ring[k])
        if keep[k] != keep[m]:
            t = v[k] / (v[k] - v[m])
            out.append(ring[k] + (ring[m] - ring[k]) * t)
    return np.asarray(out)


def test_the_half_plane_clip_is_the_corner_by_corner_one_to_the_bit():
    rng = np.random.default_rng(9)
    cut = 0
    for _ in range(5000):
        ring = rng.normal(size=(int(rng.integers(3, 12)), 2))
        dq = rng.normal(size=3)
        if rng.random() < 0.3:                  # corners on the line
            ring, dq = np.round(ring), np.round(dq)
        got, want = VC._clip_half(ring, dq), _clip_plain(ring, dq)
        assert got.dtype == want.dtype and got.shape == want.shape
        assert np.array_equal(got, want)
        cut += 0 < len(want) and got is not ring
    assert cut > 1000


def _square(x, y, s):
    return np.array([[x, y], [x + s, y], [x + s, y + s], [x, y + s]],
                    dtype=np.float64)


def _scene(rng, n, roof=True):
    """Small tiles at random heights over a floor, under a roof covering
    half of them: the faces a view of a building is made of."""
    faces = []

    def face(ring, z, tilt=(0.0, 0.0)):
        faces.append(FaceFill(rings=[ring], rgb=(0.5, 0.5, 0.5),
                              layer="0", depth=-z,
                              extra={"near": (tilt[0], tilt[1], z)}))
    face(_square(0, 0, 10), 0.0)                              # the floor
    for _ in range(n):
        x, y = rng.uniform(0, 9.5, size=2)
        face(_square(x, y, rng.uniform(0.1, 0.5)),
             float(rng.uniform(0.1, 2.0)),
             tuple(rng.uniform(-0.05, 0.05, size=2)))
    if roof:
        face(_square(0, 0, 5), 3.0)
    return faces


def _canon(out):
    return [(round(f.depth, 9), [np.round(r, 9).tolist() for r in f.rings])
            for f in out]


def _area(out):
    return sum(abs(VC._area(r)) for f in out for r in f.rings)


def test_faces_the_roof_hides_are_dropped_as_the_full_union_drops_them(
        monkeypatch):
    rng = np.random.default_rng(12)
    base = _scene(rng, 300)
    unions = []
    real = VC._take_away

    def counted(visible, covers):
        unions.append(len(covers))
        return real(visible, covers)

    monkeypatch.setattr(VC, "_take_away", counted)
    fast = VC._visible_parts([FaceFill(**vars(f)) for f in base])
    shortcut = len(unions)
    unions.clear()
    monkeypatch.setattr(VC, "_hidden_by_the_biggest",
                        lambda *a, **k: False)
    plain = VC._visible_parts([FaceFill(**vars(f)) for f in base])
    assert _canon(fast) == _canon(plain)
    # About half the tiles are under the roof: they never reach the union.
    assert shortcut < 0.75 * len(unions)


def test_covers_taken_away_in_batches_leave_what_one_union_leaves(
        monkeypatch):
    from manifold3d import CrossSection, OpType
    rng = np.random.default_rng(21)
    covers = [VC._section([_square(*rng.uniform(0, 9.5, size=2),
                                   rng.uniform(0.1, 0.6))])
              for _ in range(700)]
    visible = VC._section([_square(0, 0, 10)])
    one = visible - CrossSection.batch_boolean(covers, OpType.Add)
    monkeypatch.setattr(VC, "_COVER_BATCH", 64)
    batched = VC._take_away(visible, covers)
    assert abs(one.area() - batched.area()) < 1e-6 * visible.area()
    assert (one - batched).area() + (batched - one).area() < 1e-3
    # Up to one batch: the single union, to the bit.
    few = covers[:64]
    a = visible - CrossSection.batch_boolean(few, OpType.Add)
    b = VC._take_away(visible, few)
    assert [p.tolist() for p in a.to_polygons()] == \
        [p.tolist() for p in b.to_polygons()]


def test_no_more_batches_once_nothing_is_left(monkeypatch):
    from manifold3d import CrossSection
    visible = VC._section([_square(0, 0, 1)])
    covers = [VC._section([_square(-1, -1, 3)])] + [
        VC._section([_square(0.1 * k, 0, 0.05)]) for k in range(9)]
    monkeypatch.setattr(VC, "_COVER_BATCH", 1)
    joined = []
    real = CrossSection.batch_boolean

    class Counting:
        @staticmethod
        def batch_boolean(parts, op):
            joined.append(len(parts))
            return real(parts, op)

    import manifold3d
    monkeypatch.setattr(manifold3d, "CrossSection", Counting)
    assert VC._take_away(visible, covers).is_empty()
    assert joined == [1]


def test_the_visible_parts_cover_what_they_covered(monkeypatch):
    """The whole pass against the plain one (every box tested, one union
    per face, no roof shortcut): the same faces, the same area."""
    rng = np.random.default_rng(33)
    base = _scene(rng, 400)
    fast = VC._visible_parts([FaceFill(**vars(f)) for f in base])

    class Everything(VC._OverlapGrid):
        def overlapping(self, i):
            return _brute(self.lo, self.hi, self.opaque, i)

    monkeypatch.setattr(VC, "_OverlapGrid", Everything)
    monkeypatch.setattr(VC, "_hidden_by_the_biggest",
                        lambda *a, **k: False)
    monkeypatch.setattr(VC, "_COVER_BATCH", 10 ** 9)
    plain = VC._visible_parts([FaceFill(**vars(f)) for f in base])
    assert [f.depth for f in fast] == [f.depth for f in plain]
    assert abs(_area(fast) - _area(plain)) < 1e-9
    assert len(fast) > 50
