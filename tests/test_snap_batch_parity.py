# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The snap search's per-edge passes asked of the engine at once
(``core.snap_batch``, Bloque 6b) answer what walking every edge in Python
answers, bit for bit:

* each kernel keeps exactly the edges (or points) its Python twin keeps —
  ``qt_px_near`` gives ``QMatrix4x4.map``'s pixels to the last bit, and
  ``snap_on_segment``, ``snap_ext_maybe``, ``snap_line_hits`` and
  ``snap_feet_near`` repeat QVector3D's float32 arithmetic — over random
  cameras (perspective, orthographic, arbitrary), parallel, nearly
  parallel, zero-length, huge and NaN edges;
* ``compute_snap`` gives the same point, kind, colour, guide and context
  with the batch and without it, over random scenes of boxes, grids and
  guide-like long edges, cursors on corners, midpoints, edges and
  nowhere, draws along an axis, square to a wall, along an edge, and on a
  face;
* in a real viewport, a Line hover with the batch answers the hover
  without it.

Skipped where the engine is off or not built (``INGETRAZO_RUST=0``)."""
from __future__ import annotations

import math
import os
import random
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core import snap, snap_batch  # noqa: E402
from core.snap_batch import EdgeBatch, pixel_projector, widened  # noqa: E402

from core import _native  # noqa: E402

MOD = _native.native            # the engine on (INGETRAZO_RUST), not only built
BUILT = MOD is not None and hasattr(MOD, "snap_feet_near")
NAT = snap_batch.native()
needs_engine = pytest.mark.skipif(
    NAT[0] is None, reason="engine off, not built, or not Qt's arithmetic")
needs_hypot = pytest.mark.skipif(
    NAT[0] is None or NAT[2] is None,
    reason="no native QVector3D length formula")


@pytest.mark.skipif(not BUILT or _native.qt_hypot() is None,
                    reason="engine off or not built")
def test_the_engine_projects_as_this_qt():
    """Where the engine knows this Qt's QVector3D arithmetic, it also
    projects as its QMatrix4x4 does: the batch is on (were it refused, the
    search would quietly walk every edge in Python again)."""
    assert NAT[0] is not None
    assert NAT[2] == _native.qt_hypot()


def _bits(v):
    return None if v is None else np.float64(v).tobytes()


def _camera(rng, w=1100, h=700):
    proj = QMatrix4x4()
    kind = rng.random()
    if kind < 0.55:
        proj.perspective(rng.uniform(25, 80), w / h, rng.choice((0.01, 0.1)),
                         rng.choice((500.0, 5e4)))
    elif kind < 0.9:
        s = rng.uniform(3, 60)
        proj.ortho(-s, s, -s * h / w, s * h / w, -1e3, 1e3)
    else:
        proj = QMatrix4x4(*[rng.gauss(0, 1) for _ in range(16)])
        return proj, w, h
    view = QMatrix4x4()
    r = rng.uniform(8, 60)
    yaw, pitch = rng.uniform(0, 2 * math.pi), rng.uniform(-1.4, 1.4)
    if rng.random() < 0.15:
        pitch = math.pi / 2 - 1e-7                     # straight down
    if rng.random() < 0.1:
        yaw, pitch = 0.0, 0.0                          # square front view
    eye = V(r * math.cos(yaw) * math.cos(pitch) + 8,
            r * math.sin(yaw) * math.cos(pitch) + 8, r * math.sin(pitch))
    up = V(0, 0, 1) if abs(pitch) < 1.5 else V(0, 1, 0)
    view.lookAt(eye, V(8, 8, rng.uniform(0, 2)), up)
    return proj * view, w, h


class _E:
    """A snap edge: ``a``/``b`` and the flags the passes read."""

    def __init__(self, a, b, **flags):
        self.a, self.b = a, b
        for k, v in flags.items():
            setattr(self, k, v)


def _edges(rng):
    edges = []
    # Boxes on a grid: many parallel and collinear edges, shared corners.
    for _ in range(rng.randint(6, 20)):
        o = V(rng.randint(0, 12) * 1.25, rng.randint(0, 12) * 1.25, 0)
        sx, sy, sz = (rng.choice((1.0, 1.25, 0.6)), rng.choice((1.0, 0.75)),
                      rng.choice((1.0, 2.5, 3.0)))
        p = [o, o + V(sx, 0, 0), o + V(sx, sy, 0), o + V(0, sy, 0)]
        q = [c + V(0, 0, sz) for c in p]
        for k in range(4):
            edges.append(_E(p[k], p[(k + 1) % 4]))
            edges.append(_E(q[k], q[(k + 1) % 4]))
            edges.append(_E(p[k], q[k]))
    # Nearly parallel sticks, slanted ones, a few far and long.
    for _ in range(rng.randint(10, 40)):
        a = V(rng.uniform(-2, 18), rng.uniform(-2, 18), rng.uniform(0, 4))
        d = V(rng.gauss(0, 3), rng.gauss(0, 3), rng.gauss(0, 1))
        if rng.random() < 0.3:
            d = V(rng.uniform(1, 4), rng.gauss(0, 1e-4), rng.gauss(0, 1e-5))
        if rng.random() < 0.05:
            d = d * 1e4                                 # guide-like, km long
        edges.append(_E(a, a + d))
    # Degenerate ones and flagged ones.
    pick = list(edges)
    for _ in range(3):
        a = rng.choice(pick).a
        edges.append(_E(V(a), V(a)))                    # zero length
    edges.append(_E(V(5, 5, 1), V(5, 5, 1), center=True))
    edges.append(_E(V(0, 0, 0), V(0, 0, 0), component_origin=True))
    edges.append(_E(V(3, 4, 0), V(3, 4, 0), arc_midpoint=True))
    edges.append(_E(V(-40, 6, 0), V(60, 6, 0), guide=True))
    for e in rng.sample(edges, min(len(edges), 6)):
        setattr(e, rng.choice(("soft", "hidden", "figure")), True)
    for e in rng.sample(edges, 4):
        e.curve = 7
    for e in rng.sample(edges, 5):
        e.context = "group"
    if rng.random() < 0.04:
        edges.append(_E(V(math.nan, 1, 2), V(3, 4, 5)))
        edges.append(_E(V(1, 2, 3), V(math.inf, 4, 5)))
    rng.shuffle(edges)
    return edges


def _key(res):
    if res is None:
        return None

    def p(v):                       # bits: a NaN point equals itself
        return None if v is None else np.float32(v.toTuple()).tobytes()
    guide = None if res.guide is None else tuple(p(g) for g in res.guide)
    return (res.kind, p(res.point), res.color, res.axis, guide,
            getattr(res, "guide_color", None), getattr(res, "context", None),
            getattr(res, "lock_color", None), id(getattr(res, "edge", None)))


def _outcome(fn, **kw):
    """compute_snap's answer as a key, or the error it raises (a NaN edge
    still breaks the search's sort, with the batch or without it)."""
    try:
        return _key(fn(**kw))
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        return ("raised", type(exc).__name__)


def _ray_projector(mvp, w, h, cx, cy):
    """``project_onto_line``: the point of a line nearest the cursor ray
    (the viewport's own idea, enough for a deterministic stand-in)."""
    inv, _ok = mvp.inverted()
    nx, ny = cx / w * 2 - 1, 1 - cy / h * 2
    p0 = inv.map(V(nx, ny, -1.0))
    p1 = inv.map(V(nx, ny, 1.0))
    d = p1 - p0

    def onto(s, u):
        if u.length() < 1e-12 or d.length() < 1e-12:
            return V(s)
        a, b = u.normalized(), d.normalized()
        w0 = s - p0
        bb = V.dotProduct(a, b)
        den = 1.0 - bb * bb
        if abs(den) < 1e-12:
            return V(s)
        t = (bb * V.dotProduct(b, w0) - V.dotProduct(a, w0)) / den
        return s + a * t
    return onto


def _occluder(rng):
    hidden = set(rng.sample(range(53), rng.randint(0, 25)))

    def occluded(p):
        k = int(abs(p.x() * 7.1 + p.y() * 3.3 + p.z() * 11.7) * 10) % 53 \
            if all(map(math.isfinite, p.toTuple())) else 0
        return k in hidden

    def many(ps):
        if hasattr(ps, "tolist"):
            ps = [V(*r) for r in np.asarray(ps).tolist()]
        return [occluded(p) for p in ps]
    return occluded, many


def _cursor(rng, edges, fn, w, h):
    kind = rng.random()
    e = rng.choice(edges)
    if kind < 0.35:
        p = e.a if rng.random() < 0.5 else e.b
    elif kind < 0.55:
        p = (e.a + e.b) * 0.5
    elif kind < 0.8:
        p = e.a + (e.b - e.a) * rng.random()
    else:
        return rng.uniform(0, w), rng.uniform(0, h)
    pix = fn(p)
    if pix is None or not all(map(math.isfinite, pix)):
        return rng.uniform(0, w), rng.uniform(0, h)
    j = rng.choice((0.0, 0.0, 1.5, 6.0, 11.0))
    return pix[0] + rng.uniform(-j, j), pix[1] + rng.uniform(-j, j)


_AXES = (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1))


def _search(rng, edges, mvp, w, h):
    """compute_snap's keyword arguments for one random search, without
    ``world_to_pixel`` (the caller adds both kinds). The cursor and the
    point under it are set up for one rule at a time: a corner, a
    midpoint, an edge, a 'from point' foot along an axis, an edge's
    extension, a crossing, square off a wall, or anywhere."""
    fn = pixel_projector(mvp, w, h)
    occluded, many = _occluder(rng)
    start = None
    target = None
    mode = rng.choice(("cursor", "cursor", "foot", "extension", "cross",
                       "square", "free"))
    good = [e for e in edges if (e.b - e.a).length() > 1e-3
            and all(map(math.isfinite, e.a.toTuple() + e.b.toTuple()))]
    if mode == "foot":
        start = V(rng.choice(good).a)
        ax = rng.choice(_AXES)
        ref = rng.choice(good).b
        target = start + ax * V.dotProduct(ref - start, ax)
    elif mode == "extension":
        e = rng.choice(good)
        u = (e.b - e.a).normalized()
        start = V(e.b) if rng.random() < 0.7 else V(e.a)
        target = e.b + u * rng.uniform(0.2, 4)
    elif mode == "cross":
        e1, e2 = rng.sample(good, 2)
        target = e1.a + (e1.b - e1.a) * rng.random()
        # A stick through the point, for the green X.
        d = V(rng.gauss(0, 1), rng.gauss(0, 1), 0) * 2
        edges = edges + [_E(target - d, target + d)]
        start = V(e2.a) if rng.random() < 0.6 else None
    elif mode == "square":
        e = rng.choice(good)
        start = e.a + (e.b - e.a) * 0.37
        n = V.crossProduct(e.b - e.a, V(0, 0, 1))
        if n.length() < 1e-9:
            n = V(1, 0, 0)
        target = start + n.normalized() * rng.uniform(0.5, 5)
    elif mode == "cursor":
        e = rng.choice(good)
        start = V(rng.choice(good).a) if rng.random() < 0.6 else None
        target = rng.choice((e.a, e.b, (e.a + e.b) * 0.5,
                             e.a + (e.b - e.a) * rng.random()))
    if target is not None:
        pix = fn(target)
    else:
        pix = None
    if pix is None or not all(map(math.isfinite, pix)):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        target = None
    else:
        j = rng.choice((0.0, 0.0, 1.5, 4.0, 11.0))
        cx, cy = pix[0] + rng.uniform(-j, j), pix[1] + rng.uniform(-j, j)
    onto = _ray_projector(mvp, w, h, cx, cy)
    if target is not None:
        cand = target + V(rng.gauss(0, 1e-3), rng.gauss(0, 1e-3), 0)
    elif start is not None:
        cand = onto(start, V(rng.gauss(0, 1), rng.gauss(0, 1), 0))
    else:
        cand = onto(V(8, 8, 0), V(1, 0, 0))
    if start is None and rng.random() < 0.3:
        start = V(rng.choice(good).a)
    on_face = rng.random() < 0.3
    acquired = None
    if rng.random() < 0.4:
        acquired = V(rng.choice(good).b)
    return dict(
        candidate_world=cand, candidate_pixel=(cx, cy),
        scene=SimpleNamespace(edges=edges, circles=[]),
        threshold_px=rng.choice((9.0, 9.0, 15.0)),
        project_onto_line=lambda s, d: onto(s, d),
        start_point=start, chain_first_point=None,
        is_occluded=occluded, are_occluded=many if rng.random() < 0.7 else None,
        edge_threshold_px=rng.choice((None, 14.0)),
        face_under_cursor=on_face,
        work_plane_normal=(V(0, 0, 1) if not on_face or rng.random() < 0.6
                           else V(rng.gauss(0, 1), rng.gauss(0, 1),
                                  rng.gauss(0, 1)).normalized()),
        acquired_point=acquired,
        acquired_points=[acquired] if acquired is not None
        and rng.random() < 0.3 else [],
        magnetic_axis_deg=rng.choice((None, None, 3.0)),
        inference_angle_deg=5.0,
        disabled_kinds=(frozenset(rng.sample(
            ("endpoint", "midpoint", "on_edge", "intersection", "extension",
             "from_point"), 2)) if rng.random() < 0.15 else None),
    )


# ---- Kernels: the very decisions of their Python twins ----------------------

def _segments(rng, n):
    out = []
    for _ in range(n):
        a = V(rng.gauss(5, 6), rng.gauss(5, 6), rng.gauss(1, 2))
        kind = rng.random()
        if kind < 0.2:
            b = a + V(rng.choice((1.0, 2.5, 0.5)), 0, 0)
        elif kind < 0.3:
            b = V(a)
        elif kind < 0.4:
            b = a + V(1, rng.gauss(0, 1e-6), 0)
        elif kind < 0.45:
            b = a * 1e4
        else:
            b = a + V(rng.gauss(0, 3), rng.gauss(0, 3), rng.gauss(0, 3))
        out.append(_E(a, b))
    return out


@needs_engine
@pytest.mark.parametrize("seed", range(30))
def test_projection_is_qt_to_the_bit(seed):
    rng = random.Random(seed)
    mod, fma, _h = NAT
    for _ in range(4):
        mvp, w, h = _camera(rng)
        fn = pixel_projector(mvp, w, h)
        pts = [V(rng.gauss(8, 20), rng.gauss(8, 20), rng.gauss(0, 5))
               for _ in range(300)]
        pts += [V(0, 0, 0), V(math.nan, 0, 0), V(math.inf, 1, 1),
                V(1e38, -1e38, 1e30)]
        arr = np.array([p.toTuple() for p in pts], dtype=np.float32)
        want = [fn(p) for p in pts]
        ok_pix = [p for p in want if p is not None and math.isfinite(p[0])]
        cx, cy = (rng.choice(ok_pix) if ok_pix else (w / 2, h / 2))
        cx += rng.uniform(-5, 5)
        r = rng.choice((0.0, 9.0, 40.0, 1e9))
        px, py, ok, near = mod.qt_px_near(arr, list(mvp.data()), float(w),
                                          float(h), cx, cy, widened(r), fma)
        got = [(x, y) if f else None
               for x, y, f in zip(px.tolist(), py.tolist(), ok.tolist())]
        assert [_bits(g) for g in got] == [_bits(x) for x in want]
        near = set(near.tolist())
        within = {i for i, p in enumerate(want)
                  if p is not None and not math.hypot(p[0] - cx,
                                                      p[1] - cy) > r}
        assert within <= near
        # A hair more at most: the radius is widened by one part in 1e9.
        assert all(want[i] is not None and not math.hypot(
            want[i][0] - cx, want[i][1] - cy) > r * (1 + 1e-6)
            for i in near - within)


@needs_hypot
@pytest.mark.parametrize("seed", range(20))
def test_on_segment_is_point_on_segment_world(seed):
    rng = random.Random(seed)
    edges = _segments(rng, 300)
    batch = EdgeBatch(edges, NAT[0], NAT[1], NAT[2],
                      (QMatrix4x4(), 800, 600))
    for _ in range(8):
        e = rng.choice(edges)
        t = rng.choice((0.0, 1.0, 0.5, rng.random(), -1e-7, 1 + 1e-7))
        p = e.a + (e.b - e.a) * t + V(rng.choice((0.0, 0.0, 9e-4, 2e-3)), 0, 0)
        want = [snap._point_on_segment_world(p, x.a, x.b) for x in edges]
        assert batch.on_segment(p) == want


def _ext_reference(edges, draw, start, screen, cand, plane, fn, cx, cy, r):
    """The edges _extension_snap's walk reaches ``math.hypot`` with (or
    reads on screen), the way the kernel decides it."""
    out = []
    r2 = widened(r)
    for i, e in enumerate(edges):
        ab = e.b - e.a
        if ab.length() < 1e-9:
            continue
        u = ab.normalized()
        if abs(V.dotProduct(draw, u)) < 0.966:
            if not screen:
                continue
            off = start - e.a
            if (off - u * V.dotProduct(off, u)).length() > 1e-3:
                continue
            out.append(i)
            continue
        t = V.dotProduct(cand - e.a, u)
        if plane is not None:
            den = V.dotProduct(plane, u)
            if abs(den) > 1e-6:
                t = V.dotProduct(plane, cand - e.a) / den
        if -1e-6 <= t <= ab.length() + 1e-6:
            continue
        pp = fn(e.a + u * t)
        if pp is None:
            continue
        dx, dy = pp[0] - cx, pp[1] - cy
        if not dx * dx + dy * dy > r2:
            out.append(i)
    return out


def _line_reference(edges, start, u, draw, fn, cx, cy, r):
    out = []
    r2 = widened(r)
    for i, e in enumerate(edges):
        if draw is not None and snap._point_on_segment_world(start, e.a, e.b):
            continue
        hit = snap._line_segment_intersection(start, u, e.a, e.b)
        if hit is None:
            continue
        if draw is not None and V.dotProduct(hit - start, draw) <= 0:
            continue
        hp = fn(hit)
        if hp is None:
            continue
        dx, dy = hp[0] - cx, hp[1] - cy
        if not dx * dx + dy * dy > r2:
            out.append(i)
    return out


def _feet_reference(refs, start, adir, fn, cx, cy, r, both):
    out = []
    r2 = widened(r)

    def near(p):
        pp = fn(p)
        if pp is None:
            return False
        dx, dy = pp[0] - cx, pp[1] - cy
        return not dx * dx + dy * dy > r2
    for i, ref in enumerate(refs):
        s = V.dotProduct(ref - start, adir)
        if not both and s <= 1e-6:
            continue
        foot = start + adir * s
        if (foot - ref).length() < 1e-4:
            continue
        if near(foot) or (both and near(ref)):
            out.append(i)
    return out


@needs_hypot
@pytest.mark.parametrize("seed", range(25))
def test_line_kernels_are_their_python(seed):
    rng = random.Random(seed)
    edges = _edges(rng) + _segments(rng, 80)
    mod, fma, hy = NAT
    for _ in range(4):
        mvp, w, h = _camera(rng)
        fn = pixel_projector(mvp, w, h)
        batch = EdgeBatch(edges, mod, fma, hy, (mvp, w, h))
        start = V(rng.choice(edges).a)
        cx, cy = _cursor(rng, edges, fn, w, h)
        r = rng.choice((9.0, 14.0, 60.0))
        draws = [V(1, 0, 0), V(0, 1, 0), V(0, 0, 1),
                 (rng.choice(edges).b - rng.choice(edges).a).normalized(),
                 V(rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))
                 .normalized()]
        for draw in draws:
            for screen in (False, True):
                for plane in (None, V(0, 0, 1),
                              V(rng.gauss(0, 1), 1, rng.gauss(0, 1))
                              .normalized()):
                    cand = start + draw * rng.uniform(-8, 8)
                    got = batch.extension_maybe(draw, start, screen, cand,
                                                plane, cx, cy, r)
                    want = _ext_reference(edges, draw, start, screen, cand,
                                          plane, fn, cx, cy, r)
                    assert got == want
            for ahead in (None, draw):
                got = batch.line_hits(start, draw, ahead, cx, cy, r)
                want = _line_reference(edges, start, draw, ahead, fn, cx,
                                       cy, r)
                assert got == want
            for mids in (False, True):
                refs = batch.refs(mids)
                pts = [V(*p) for p in refs.tolist()]
                for both in (False, True):
                    got = batch.feet_near(refs, start, draw, cx, cy, r, both)
                    want = _feet_reference(pts, start, draw, fn, cx, cy, r,
                                           both)
                    assert got == want


@needs_engine
@pytest.mark.parametrize("seed", range(25))
def test_screen_passes_keep_every_edge_python_keeps(seed):
    rng = random.Random(seed)
    edges = _edges(rng) + _segments(rng, 60)
    mod, fma, hy = NAT
    for _ in range(5):
        mvp, w, h = _camera(rng)
        fn = pixel_projector(mvp, w, h)
        batch = EdgeBatch(edges, mod, fma, hy, (mvp, w, h))
        cx, cy = _cursor(rng, edges, fn, w, h)
        r = rng.choice((9.0, 14.0, 60.0))
        seg = set(batch.segments_near(cx, cy, r))
        mid = set(batch.mids_near(cx, cy, r))
        ends = set(batch.ends_near(cx, cy, r))
        for i, e in enumerate(edges):
            pa, pb = fn(e.a), fn(e.b)
            if pa is not None and pb is not None:
                d, _t = snap._closest_on_segment_2d((cx, cy), pa, pb)
                if not d > r:
                    assert i in seg, (i, d, r)
            elif i in seg:
                raise AssertionError("an end behind the eye was kept")
            pm = fn((e.a + e.b) * 0.5)
            if pm is not None and not math.hypot(pm[0] - cx, pm[1] - cy) > r:
                assert i in mid
            for k, p in ((2 * i, pa), (2 * i + 1, pb)):
                if p is not None and not math.hypot(p[0] - cx,
                                                    p[1] - cy) > r:
                    assert k in ends


# ---- The whole search -------------------------------------------------------

@needs_engine
@pytest.mark.parametrize("seed", range(100))
def test_compute_snap_is_the_same_with_the_batch(seed, monkeypatch):
    rng = random.Random(seed)
    edges = _edges(rng)
    assert len(edges) >= snap_batch._MIN_EDGES
    used = 0
    for _ in range(8):
        mvp, w, h = _camera(rng)
        kw = _search(rng, edges, mvp, w, h)
        fn = pixel_projector(mvp, w, h)
        plain = lambda p, fn=fn: fn(p)            # no qt_view: no batch
        want = _outcome(snap.compute_snap, world_to_pixel=plain, **kw)
        made = []
        real_of = EdgeBatch.of

        def spy(edges_, wtp):
            b = real_of(edges_, wtp)
            made.append(b)
            return b
        with monkeypatch.context() as mp:
            mp.setattr(EdgeBatch, "of", staticmethod(spy))
            got = _outcome(snap.compute_snap, world_to_pixel=fn, **kw)
        used += any(b is not None for b in made)
        assert got == want, (seed, kw["candidate_pixel"])
    assert used, "the batch never ran"


@needs_engine
def test_some_searches_reach_each_batched_pass():
    """The random searches above do reach the passes the batch serves."""
    reached = set()
    for seed in range(60):
        rng = random.Random(seed)
        edges = _edges(rng)
        for _ in range(6):
            mvp, w, h = _camera(rng)
            kw = _search(rng, edges, mvp, w, h)
            got = _outcome(snap.compute_snap,
                           world_to_pixel=pixel_projector(mvp, w, h), **kw)
            if got is not None:
                reached.add(got[0])
    assert {"endpoint", "midpoint", "on_edge", "extension", "from_point",
            "intersection", "reference"} <= reached


# ---- A real viewport --------------------------------------------------------

def _city_window():
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(1000, 700)
    vp.scene.guides.clear()
    rng = random.Random(3)
    m = vp.scene.mesh
    for i in range(7):
        for j in range(7):
            x0, y0 = i * 3.0, j * 3.0
            sx, sy, sz = rng.uniform(1, 2.5), rng.uniform(1, 2.5), rng.uniform(1, 6)
            p = [V(x0, y0, 0), V(x0 + sx, y0, 0), V(x0 + sx, y0 + sy, 0),
                 V(x0, y0 + sy, 0)]
            q = [c + V(0, 0, sz) for c in p]
            for idx in ((0, 3, 2, 1),):
                m.add_face([p[k] for k in idx])
            m.add_face(q)
            for k in range(4):
                m.add_face([p[k], p[(k + 1) % 4], q[(k + 1) % 4], q[k]])
    vp.scene.version += 1
    cam = vp.camera
    cam.perspective = True
    cam.fit_to(V(0, 0, 0), V(21, 21, 6))
    cam.yaw, cam.pitch = math.radians(35), math.radians(30)
    return win, vp


@needs_engine
def test_a_line_hover_is_the_same_with_the_batch(monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    win, vp = _city_window()
    try:
        win._activate_tool("line")
        tool = vp.active_tool
        rng = random.Random(11)
        W, H = vp.width(), vp.height()
        corners = [e.a for e in vp.scene.mesh.edges]
        targets = []
        for c in rng.sample(corners, 25):
            pix = vp._world_to_pixel(c)
            if pix is not None:
                targets.append((pix[0] + rng.uniform(-4, 4),
                                pix[1] + rng.uniform(-4, 4)))
        targets += [(rng.uniform(0, W), rng.uniform(0, H)) for _ in range(25)]
        assert len(vp.scene.mesh.edges) >= snap_batch._MIN_EDGES

        def run(start):
            tool.start_point = start
            vp.inference.clear_references()
            out = []
            for x, y in targets:
                vp._tick = getattr(vp, "_tick", 0) + 1
                s = vp.inference.snap(x, y, Qt.NoModifier)
                out.append(_key(s))
            return out
        for start in (None, V(corners[5]), V(corners[40])):
            got = run(start)
            monkeypatch.setattr(snap_batch, "_MIN_EDGES", 10 ** 9)
            want = run(start)
            monkeypatch.setattr(snap_batch, "_MIN_EDGES", 64)
            assert got == want
        del QPointF
    finally:
        win._saved_version = vp.scene.version
        win.close()
