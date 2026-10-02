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
more than ``max_cells`` cells), which every query reads. Pure NumPy, no Qt.
"""
from __future__ import annotations

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
                 "keys", "ids", "long_ids", "width", "height")

    def __init__(self, ax, ay, bx, by, ok, width: float, height: float,
                 reach: float, cell: float = CELL_PX,
                 max_cells: int = MAX_CELLS) -> None:
        self.reach = float(reach)
        self.cell = float(cell)
        self.width, self.height = float(width), float(height)
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
        order = np.argsort(keys, kind="stable")
        self.keys = keys[order]
        self.ids = ids[rep[order]]

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
        parts = [self.long_ids]
        # Cells of one row are consecutive keys: one slice per row.
        for row in range(y0, y1 + 1):
            lo = np.searchsorted(self.keys, row * self.ncx + x0, "left")
            hi = np.searchsorted(self.keys, row * self.ncx + x1, "right")
            if hi > lo:
                parts.append(self.ids[lo:hi])
        return np.unique(np.concatenate(parts))


def segment_distances(ax, ay, bx, by, ok, px: float, py: float, which=None):
    """Pixel distance from ``(px, py)`` to each segment (``inf`` where
    ``ok`` is False), for all of them or only the indices ``which``."""
    if which is not None:
        ax, ay, bx, by, ok = ax[which], ay[which], bx[which], by[which], ok[which]
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    safe = np.where(l2 > 1e-12, l2, 1.0)
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe, 0.0, 1.0)
    d = np.hypot(ax + t * dx - px, ay + t * dy - py)
    return np.where(ok, d, np.inf)
