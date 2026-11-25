# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A screen-space grid over projected segments: which edges pass near a pixel.

The hover pass asks, on every mouse move, how far the cursor is from each
group hard edge — and only cares about the few within a few dozen pixels
(the edge pick's 8 px, the snap prefilter's 48 px). Measuring all of them
is one NumPy pass, but over 700 000 edges (a 330 k-face city) that pass is
~30 ms per move, a third of the whole inference cost. The projection only
changes when the camera or the scene does; while the user draws, the camera
is still, so the segments are binned ONCE into square cells and each move
reads the handful of cells around the cursor.

Exact by construction: a segment within ``reach`` of the cursor has its
bounding box within ``reach`` of it too, so it sits in one of the cells the
query reads — or in the short list of segments too long to bin (spanning
more than ``max_cells`` cells), which every query reads. NumPy, no Qt;
a long distance pass may go to the native engine, bit for bit.
"""
from __future__ import annotations

import os

import numpy as np

#: Cell side in pixels.
CELL_PX = 32.0
#: Segments whose box covers more cells than this are not binned: a few
#: long edges across the screen would otherwise fill hundreds of cells
#: each. They are read by every query instead.
MAX_CELLS = 16


class EdgeGrid:
    """Segments ``(ax, ay)–(bx, by)`` (pixels; ``ok`` False = not on screen,
    e.g. behind the camera) binned for a ``width × height`` view, for
    queries up to ``reach`` pixels from a cursor inside the view."""

    __slots__ = ("reach", "cell", "cx0", "cy0", "ncx", "ncy",
                 "keys", "ids", "long_ids", "width", "height", "n")

    def __init__(self, ax, ay, bx, by, ok, width: float, height: float,
                 reach: float, cell: float = CELL_PX,
                 max_cells: int = MAX_CELLS) -> None:
        self.reach = float(reach)
        self.cell = float(cell)
        self.width, self.height = float(width), float(height)
        if self._bin_native(ax, ay, bx, by, ok, max_cells):
            return
        with np.errstate(invalid="ignore"):
            lox = np.minimum(ax, bx)
            hix = np.maximum(ax, bx)
            loy = np.minimum(ay, by)
            hiy = np.maximum(ay, by)
            # Only what a cursor IN the view can come within reach of.
            live = (ok & np.isfinite(lox) & np.isfinite(hix)
                    & np.isfinite(loy) & np.isfinite(hiy)
                    & (hix >= -self.reach) & (lox <= self.width + self.reach)
                    & (hiy >= -self.reach) & (loy <= self.height + self.reach))
        # The grid spans the view plus the reach on every side; boxes are
        # clipped to it (a segment running off screen is binned where it
        # crosses the band a cursor can reach).
        self.cx0 = int(np.floor(-self.reach / cell))
        self.cy0 = int(np.floor(-self.reach / cell))
        cx1 = int(np.floor((self.width + self.reach) / cell))
        cy1 = int(np.floor((self.height + self.reach) / cell))
        self.ncx, self.ncy = cx1 - self.cx0 + 1, cy1 - self.cy0 + 1
        self.n = len(live)
        idx = np.flatnonzero(live)
        x0 = np.clip(np.floor(lox[idx] / cell), self.cx0, cx1).astype(np.int64)
        x1 = np.clip(np.floor(hix[idx] / cell), self.cx0, cx1).astype(np.int64)
        y0 = np.clip(np.floor(loy[idx] / cell), self.cy0, cy1).astype(np.int64)
        y1 = np.clip(np.floor(hiy[idx] / cell), self.cy0, cy1).astype(np.int64)
        nx, ny = x1 - x0 + 1, y1 - y0 + 1
        span = nx * ny
        small = span <= max_cells
        self.long_ids = idx[~small]
        ids, x0, y0, nx, span = (idx[small], x0[small], y0[small], nx[small],
                                 span[small])
        # Expand each binned segment into the cells its box covers.
        rep = np.repeat(np.arange(len(ids)), span)
        first = np.repeat(np.cumsum(span) - span, span)
        k = np.arange(len(rep)) - first
        nxr = nx[rep]
        cx = x0[rep] + k % nxr
        cy = y0[rep] + k // nxr
        keys = (cy - self.cy0) * self.ncx + (cx - self.cx0)
        # A view holds well under 65 536 cells: sorted as 16-bit keys, the
        # stable sort is a radix pass (same order, ~9× quicker — most of a
        # grid built on the hover of a push, night of 19-11).
        sk = (keys.astype(np.uint16) if self.ncx * self.ncy <= 0xFFFF
              else keys)
        order = np.argsort(sk, kind="stable")
        self.keys = keys[order]
        self.ids = ids[rep[order]]

    def _bin_native(self, ax, ay, bx, by, ok, max_cells) -> bool:
        """The binning below in the native engine, the same cells and the
        same order to the last index (the first hover with Line after a
        click binned the Plaza's group edges, ~10 ms of NumPy, 19-11):
        ``False`` where it cannot (no engine, a view it does not take)."""
        from core import _native
        mod = _native.native
        if mod is None or not hasattr(mod, "edge_grid_bins"):
            return False
        vals = (self.width, self.height, self.reach, self.cell)
        if not all(np.isfinite(vals)) or self.cell <= 0.0:
            return False
        f = np.ascontiguousarray
        (self.cx0, self.cy0, self.ncx, self.ncy, self.long_ids, self.keys,
         self.ids) = mod.edge_grid_bins(
            f(ax, np.float64), f(ay, np.float64), f(bx, np.float64),
            f(by, np.float64), f(ok, bool), self.width, self.height,
            self.reach, self.cell, int(max_cells))
        self.n = len(ax)
        return True

    def near(self, px: float, py: float, reach: float | None = None):
        """Indices of the segments that MAY lie within ``reach`` (at most
        the grid's own) of ``(px, py)`` — every one that does is among
        them — or ``None`` when the cursor is outside the view (the caller
        measures them all, as before the grid)."""
        if not (0.0 <= px <= self.width and 0.0 <= py <= self.height):
            return None
        r = self.reach if reach is None else min(float(reach), self.reach)
        c = self.cell
        x0 = int(np.floor((px - r) / c)) - self.cx0
        x1 = int(np.floor((px + r) / c)) - self.cx0
        y0 = int(np.floor((py - r) / c)) - self.cy0
        y1 = int(np.floor((py + r) / c)) - self.cy0
        x0, x1 = max(x0, 0), min(x1, self.ncx - 1)
        y0, y1 = max(y0, 0), min(y1, self.ncy - 1)
        got = self._near_native(x0, x1, y0, y1)
        if got is not None:
            return got
        parts = [self.long_ids]
        # Cells of one row are consecutive keys: one slice per row.
        for row in range(y0, y1 + 1):
            lo = np.searchsorted(self.keys, row * self.ncx + x0, "left")
            hi = np.searchsorted(self.keys, row * self.ncx + x1, "right")
            if hi > lo:
                parts.append(self.ids[lo:hi])
        cand = np.concatenate(parts)
        if len(cand) * 16 < self.n:
            return np.unique(cand)
        # Many candidates (a whole plant in view: thousands of edges a
        # cell): the same sorted, repeat-free indices through a mask, in
        # one linear pass instead of a sort (~180 ms a move on #158).
        mark = np.zeros(self.n, dtype=bool)
        mark[cand] = True
        return np.flatnonzero(mark)

    def _near_native(self, x0, x1, y0, y1):
        """:meth:`near`'s gather of the cells ``x0..x1`` × ``y0..y1`` in the
        native engine — the same sorted, repeat-free indices (``np.unique``
        of them was ~0.2 ms of each edge query of a hover over 1 400
        placements, 21-11) — or ``None`` without it."""
        if not _GRID_NATIVE:
            return None
        from core import _native
        mod = _native.native
        if mod is None or not hasattr(mod, "edge_grid_near"):
            return None
        f = np.ascontiguousarray
        try:
            return mod.edge_grid_near(
                f(self.keys, np.int64), f(self.ids, np.int64),
                f(self.long_ids, np.int64), int(self.ncx), int(x0), int(x1),
                int(y0), int(y1), int(self.n))
        except (TypeError, ValueError):
            return None


#: The grid's gather in the native engine (``EdgeGrid._near_native``);
#: INGETRAZO_PICK_NATIVE=0 keeps NumPy, for measuring and for the tests.
_GRID_NATIVE = os.environ.get("INGETRAZO_PICK_NATIVE", "1") != "0"


#: Below this many segments NumPy's pass is as quick as a native call: the
#: native pass was faster from 200 segments up (4x there, 3.6x at 10 000,
#: 21-11), so only a handful stay in NumPy.
NATIVE_MIN = 256

#: Whether the native pass gives NumPy's very bits here (None: not checked).
_NATIVE_SAME = None


def _native_pass():
    """core._native's ``segment_distances`` when it gives this NumPy's bits
    — checked once on segments of every kind (zero-length, off screen, not
    finite, the cursor on an end and past it): ``hypot`` is the C
    library's, and another one may round the last bit its own way."""
    global _NATIVE_SAME
    from core import _native
    mod = _native.native
    if mod is None or not hasattr(mod, "segment_distances"):
        return None
    if _NATIVE_SAME is None:
        rng = np.random.default_rng(158)
        n = 4096
        a = rng.normal(size=(4, n)) * 10.0 ** rng.uniform(-2, 4, (1, n))
        a[:, :64] = np.round(a[:, :64])               # whole pixels
        a[2:, 64:128] = a[:2, 64:128]                 # zero length
        a[0, 128:136] = (np.nan, np.inf, -np.inf, 1e308, -1e308, 0.0, -0.0,
                         5e-324)
        ok = rng.random(n) < 0.9
        _NATIVE_SAME = True
        for px, py in ((0.0, 0.0), (12.5, -3.25), (float(a[0, 7]),
                                                    float(a[1, 7]))):
            with np.errstate(all="ignore"):
                want = _numpy_distances(a[0], a[1], a[2], a[3], ok, px, py)
            got = np.asarray(mod.segment_distances(a[0], a[1], a[2], a[3],
                                                   ok, px, py))
            same = (got == want) | (np.isnan(got) & np.isnan(want))
            if not same.all():
                _NATIVE_SAME = False
    return mod if _NATIVE_SAME else None


def segment_distances(ax, ay, bx, by, ok, px: float, py: float, which=None):
    """Pixel distance from ``(px, py)`` to each segment (``inf`` where
    ``ok`` is False), for all of them or only the indices ``which``. Many
    of them go to the native engine, the same arithmetic in parallel
    (zoomed out over the plant of #158, 475 000 within 8 px of the cursor
    took ~11 ms of every pointer move)."""
    n = len(ax) if which is None else len(which)
    if n >= NATIVE_MIN:
        mod = _native_pass()
        if mod is not None:
            f = np.ascontiguousarray
            return np.asarray(mod.segment_distances(
                f(ax, np.float64), f(ay, np.float64), f(bx, np.float64),
                f(by, np.float64), f(ok, bool), float(px), float(py),
                None if which is None else f(which, np.int64)))
    return _numpy_distances(ax, ay, bx, by, ok, px, py, which)


def _numpy_distances(ax, ay, bx, by, ok, px, py, which=None):
    """``segment_distances`` in NumPy."""
    if which is not None:
        ax, ay, bx, by, ok = ax[which], ay[which], bx[which], by[which], ok[which]
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    safe = np.where(l2 > 1e-12, l2, 1.0)
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe, 0.0, 1.0)
    d = np.hypot(ax + t * dx - px, ay + t * dy - py)
    return np.where(ok, d, np.inf)
