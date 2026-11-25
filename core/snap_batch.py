# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The snap search's per-edge passes, asked of the engine all at once.

:func:`core.snap.compute_snap` walks the scene's edges a dozen times per
pointer move — the endpoints, the extension of an edge, the green X, the
midpoints, the edge under the cursor, the perpendicular from a wall, the
'from point' feet — each edge through QVector3D arithmetic and a projection
to the screen. Over a loose model of a few thousand edges that was ~30 ms a
move of a Line (a city of 225 boxes, 21-11): every edge asked every time,
almost all of them to be turned down.

:class:`EdgeBatch` holds the edges of ONE search as float32 arrays, and the
engine (``ingetrazo_core``: ``qt_px_near``, ``snap_ext_maybe``,
``snap_on_segment``, ``snap_line_hits``, ``snap_feet_near``) repeats each
pass's tests — QVector3D's float32 operations, ``QMatrix4x4.map`` and the
Python float arithmetic after them, in their order — to tell which edges
the pass could keep. The pass then runs its own Python body on those
alone, so it answers exactly what it answered walking them all. Distances
on screen are compared in the engine on a radius widened a hair
(``math.hypot`` is CPython's own); the body asks ``math.hypot`` again.

Without the engine, below :data:`_MIN_EDGES` edges, or when the search's
projector is not the viewport's (a test's stand-in), there is no batch and
every pass walks the edges as before. ``INGETRAZO_RUST=0`` is that path."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D, QVector4D

#: From this many edges a search batches its passes.
_MIN_EDGES = 64
#: A radius on screen, widened for the engine's squared comparison: far
#: more than ``math.hypot`` and the squared sum can disagree by.
_WIDEN = 1.0 + 1e-9


def pixel_projector(mvp, w, h):
    """World point → widget pixel through the QMatrix4x4 ``mvp`` for a
    ``w`` × ``h`` widget, or None behind the eye: ``Viewport._world_to_pixel``
    with the camera fixed (``Viewport._pixel_projector``). The function
    carries its view (``qt_view``) so a search can project its edges at
    once with the same arithmetic (:class:`EdgeBatch`)."""
    vec4 = QVector4D

    def world_to_pixel(world):
        clip = mvp.map(vec4(world.x(), world.y(), world.z(), 1.0))
        if clip.w() <= 0:
            return None
        ndc_x = clip.x() / clip.w()
        ndc_y = clip.y() / clip.w()
        return ((ndc_x * 0.5 + 0.5) * w, (1.0 - (ndc_y * 0.5 + 0.5)) * h)
    world_to_pixel.qt_view = (mvp, w, h)
    return world_to_pixel


def widened(r):
    """``r`` squared, widened (:data:`_WIDEN`); NaN stays NaN (the engine
    then keeps everything, as ``d > NaN`` keeps everything in Python)."""
    r = float(r)
    if r != r:
        return r
    return (abs(r) * _WIDEN) ** 2


# ---- Is the engine Qt? ------------------------------------------------------

#: ``(module, fma, hypot)`` once the engine was found to project as
#: :func:`pixel_projector` does here (``hypot`` the QVector3D length
#: formula, or None: then only the projection passes batch), or
#: ``(None, None, None)``; unset until first asked.
_NATIVE = None


def _set_native(value):
    global _NATIVE
    _NATIVE = value


def native():
    """``(core._native module, fma, hypot)`` when the engine's
    ``qt_px_near`` projects as :func:`pixel_projector` (Qt's own
    ``QMatrix4x4.map``) on a fixed sample — perspective, orthographic and
    arbitrary matrices, points near and far, behind the eye, on the eye
    plane, NaN and infinity — trying Qt's sum as written and contracted;
    else ``(None, None, None)``: the search projects through Qt."""
    if _NATIVE is not None:
        return _NATIVE
    from core import _native
    mod = _native.native
    if mod is None or not hasattr(mod, "snap_feet_near"):
        return None, None, None           # not cached: the switch may change
    _set_native((None, None, None))
    try:
        sample = _px_sample()
        for fma in (False, True):
            if _px_match(mod, fma, sample):
                _set_native((mod, fma, _native.qt_hypot()))
                break
    except Exception:  # noqa: BLE001 — then Python
        pass
    return _NATIVE


def _px_sample(seed=6, views=16, n=60):
    """``[(mvp, w, h, pts)]`` for :func:`_px_match`."""
    import numpy as np
    from PySide6.QtGui import QMatrix4x4
    rng = np.random.default_rng(seed)
    out = []
    for k in range(views):
        proj = QMatrix4x4()
        if k % 3 == 2:
            s = float(10.0 ** rng.uniform(-1, 3))
            proj.ortho(-s, s, -s * 0.7, s * 0.7, -50 * s, 50 * s)
        else:
            proj.perspective(float(rng.uniform(15, 90)),
                             float(rng.uniform(0.5, 2.5)),
                             float(10.0 ** rng.uniform(-3, 0)),
                             float(10.0 ** rng.uniform(2, 5)))
        view = QMatrix4x4()
        scale = float(10.0 ** rng.uniform(-1, 4))
        eye = rng.normal(size=3) * scale
        view.lookAt(QVector3D(*eye),
                    QVector3D(*(rng.normal(size=3) * scale * 0.1)),
                    QVector3D(0, 0, 1))
        mvp = proj * view
        if k % 8 == 7:                    # an arbitrary matrix
            mvp = QMatrix4x4(*rng.normal(size=16).tolist())
        pts = rng.normal(size=(n, 3)) * scale * 10.0 ** rng.uniform(
            -3, 1, (n, 1))
        pts[:4] = eye                     # on the eye: w == 0
        pts[4:8] = np.round(pts[4:8])
        if k % 4 == 0:
            pts[8, 0], pts[9, 1], pts[10, 2] = np.nan, np.inf, -np.inf
            pts[11] = (3e38, -3e38, 1e-38)
        w, h = int(rng.integers(1, 3000)), int(rng.integers(1, 2000))
        out.append((mvp, w, h, pts.astype(np.float32)))
    return out


def _px_match(mod, fma, sample) -> bool:
    """Whether ``qt_px_near`` gives :func:`pixel_projector`'s very pixels
    on ``sample``, and the rows it calls near include every one within
    the radius."""
    import numpy as np
    for mvp, w, h, pts in sample:
        fn = pixel_projector(mvp, w, h)
        want = [fn(QVector3D(*p)) for p in pts.tolist()]
        hit = next((p for p in want if p is not None and p[0] == p[0]),
                   (w * 0.5, h * 0.5))
        cx, cy, r = hit[0] + 0.25, hit[1] - 0.5, 9.0
        px, py, ok, near = mod.qt_px_near(
            pts, list(mvp.data()), float(w), float(h), cx, cy, widened(r),
            fma)
        got = [(x, y) if f else None
               for x, y, f in zip(px.tolist(), py.tolist(), ok.tolist())]
        if ([None if p is None else np.float64(p).tobytes() for p in got]
                != [None if p is None else np.float64(p).tobytes()
                    for p in want]):
            return False
        near = set(near.tolist())
        for i, p in enumerate(want):
            if (p is not None and not math.hypot(p[0] - cx, p[1] - cy) > r
                    and i not in near):
                return False
    return True


# ---- One search's edges -------------------------------------------------------

def _f3(v):
    """A QVector3D's float32 components, as the engine reads them."""
    return v.toTuple()


class EdgeBatch:
    """The edges of one snap search, as the engine reads them: their ends
    (float32, made on first use) and the view the search projects through.
    Each method answers which edges a pass could keep, in edge order; the
    pass asks its own Python of those (see the module docstring)."""

    __slots__ = ("edges", "mod", "fma", "hypot", "mvp", "w", "h", "_ends")

    def __init__(self, edges, mod, fma, hypot, view):
        self.edges = edges
        self.mod, self.fma, self.hypot = mod, fma, hypot
        mvp, w, h = view
        self.mvp = list(mvp.data())
        self.w, self.h = float(w), float(h)
        self._ends = None

    @classmethod
    def of(cls, edges, world_to_pixel):
        """The batch of ``edges`` for a search projecting through
        ``world_to_pixel``, or None (no engine, few edges, a stand-in
        projector)."""
        view = getattr(world_to_pixel, "qt_view", None)
        if view is None:
            return None
        try:
            n = len(edges)
        except TypeError:
            return None
        if n < _MIN_EDGES:
            return None
        mod, fma, hypot = native()
        if mod is None:
            return None
        return cls(edges, mod, fma, hypot, view)

    def ends(self):
        """``(N, 2, 3)`` float32: each edge's ``a`` and ``b``."""
        if self._ends is None:
            import numpy as np
            self._ends = np.array(
                [e.a.toTuple() + e.b.toTuple() for e in self.edges],
                dtype=np.float32).reshape(-1, 2, 3)
        return self._ends

    def refs(self, midpoints):
        """``(N·k, 3)`` float32: each edge's ``a``, ``b`` and (with
        ``midpoints``) ``(a + b) * 0.5``, edge after edge — the references
        ``_from_point_snap`` lists, in its order."""
        import numpy as np
        e = self.ends()
        if not midpoints:
            return e.reshape(-1, 3)
        mids = (e[:, 0] + e[:, 1]) * np.float32(0.5)
        return np.ascontiguousarray(
            np.concatenate([e, mids[:, None, :]], axis=1).reshape(-1, 3))

    def _near(self, pts, cx, cy, r):
        _px, _py, _ok, near = self.mod.qt_px_near(
            pts, self.mvp, self.w, self.h, float(cx), float(cy), widened(r),
            self.fma)
        return near

    def ends_near(self, cx, cy, r):
        """The end indices ``2·edge + (0 for a, 1 for b)``, ascending, whose
        pixel may lie within ``r`` of ``(cx, cy)``."""
        return self._near(self.ends().reshape(-1, 3), cx, cy, r).tolist()

    def mids_near(self, cx, cy, r):
        """The edges whose midpoint ``(a + b) * 0.5`` (QVector3D's float32
        sum and product) may project within ``r`` of ``(cx, cy)``."""
        import numpy as np
        e = self.ends()
        mids = (e[:, 0] + e[:, 1]) * np.float32(0.5)
        return self._near(np.ascontiguousarray(mids), cx, cy, r).tolist()

    def segments_near(self, cx, cy, r):
        """The edges both of whose ends are in front of the eye and whose
        projected segment may pass within ``r`` of ``(cx, cy)``: what
        ``_closest_on_segment_2d`` does, in float64, the same operations
        (its ``math.hypot`` read as the squared sum, widened)."""
        import numpy as np
        e = self.ends()
        px, py, ok, _near = self.mod.qt_px_near(
            e.reshape(-1, 3), self.mvp, self.w, self.h, 0.0, 0.0, -1.0,
            self.fma)
        px, py, ok = px.reshape(-1, 2), py.reshape(-1, 2), ok.reshape(-1, 2)
        ax, bx, ay, by = px[:, 0], px[:, 1], py[:, 0], py[:, 1]
        cx, cy = float(cx), float(cy)
        with np.errstate(all="ignore"):
            dx = bx - ax
            dy = by - ay
            denom = dx * dx + dy * dy
            t = ((cx - ax) * dx + (cy - ay) * dy) / np.where(
                denom == 0.0, 1.0, denom)
            t = np.maximum(0.0, np.minimum(1.0, t))
            t = np.where(denom == 0.0, 0.0, t)
            qx = ax + t * dx
            qy = ay + t * dy
            d2 = (cx - qx) * (cx - qx) + (cy - qy) * (cy - qy)
        keep = ok[:, 0] & ok[:, 1] & ~(d2 > widened(r))
        return np.flatnonzero(keep).tolist()

    def on_segment(self, p):
        """Mask: the edges ``p`` lies on (``_point_on_segment_world``,
        tolerance 1 mm), or None without the QVector3D formula."""
        if self.hypot is None:
            return None
        return self.mod.snap_on_segment(self.ends(), _f3(p), 1e-3,
                                        self.hypot).tolist()

    def extension_maybe(self, draw, start, screen, cand, plane, cx, cy, r):
        """The edges rule 5 (``_extension_snap``) may extend (see
        ``snap_ext_maybe``), or None without the QVector3D formula."""
        if self.hypot is None:
            return None
        return self.mod.snap_ext_maybe(
            self.ends(), _f3(draw), _f3(start), bool(screen), _f3(cand),
            None if plane is None else _f3(plane), self.mvp, self.w, self.h,
            float(cx), float(cy), widened(r), self.fma, self.hypot).tolist()

    def line_hits(self, start, u, draw, cx, cy, r):
        """The edges the line from ``start`` along ``u`` may cross within
        ``r`` of the cursor (see ``snap_line_hits``): with ``draw``, rule
        4b's perpendicular (not the edges through ``start``, the crossing
        ahead along ``draw``); without, rule 5's extension. None without
        the QVector3D formula."""
        if self.hypot is None:
            return None
        return self.mod.snap_line_hits(
            self.ends(), _f3(start), _f3(u),
            None if draw is None else _f3(draw), draw is not None, self.mvp,
            self.w, self.h, float(cx), float(cy), widened(r), self.fma,
            self.hypot).tolist()

    def feet_near(self, refs, start, adir, cx, cy, r, both):
        """Of the points ``refs`` ((M, 3) float32), those whose foot on the
        line ``start`` + ``adir``·s — or, with ``both``, the point itself —
        may be within ``r`` of the cursor (see ``snap_feet_near``), or None
        without the QVector3D formula."""
        if self.hypot is None:
            return None
        return self.mod.snap_feet_near(
            refs, _f3(start), _f3(adir), self.mvp, self.w, self.h, float(cx),
            float(cy), widened(r), self.fma, bool(both), self.hypot).tolist()
