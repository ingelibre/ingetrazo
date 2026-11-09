# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Survey coordinates on import: move a far-out file near the origin.

The engine keeps every position in single precision (``QVector3D``), which
holds about seven digits: at a UTM northing of 8,500,000 m it can only tell
whole metres apart, so a model read in at those coordinates is already
distorted before anything else happens. A drone survey, a terrain or a
municipal drawing routinely arrives that way.

Every importer therefore measures the file in double precision first and,
when it reaches beyond :data:`RECENTER_BEYOND_M`, subtracts one offset —
whole metres, from the low corner of the file's box — before the first
coordinate becomes a ``QVector3D``. The importer then reports the offset, so
the real position is never lost. The DXF importer did this first; the rule
lives here so every format moves a file the same way."""
from __future__ import annotations

import math

#: Coordinates beyond this (metres, after unit scale) trigger recentring:
#: far enough that float32 precision starts eating survey drawings, well
#: past anything drawn around the origin on purpose.
RECENTER_BEYOND_M = 100_000.0


class Bounds:
    """A box grown point by point, in double precision."""

    __slots__ = ("lo", "hi")

    def __init__(self) -> None:
        self.lo = [math.inf] * 3
        self.hi = [-math.inf] * 3

    def add(self, x: float, y: float, z: float) -> None:
        lo, hi = self.lo, self.hi
        if x < lo[0]:
            lo[0] = x
        if x > hi[0]:
            hi[0] = x
        if y < lo[1]:
            lo[1] = y
        if y > hi[1]:
            hi[1] = y
        if z < lo[2]:
            lo[2] = z
        if z > hi[2]:
            hi[2] = z

    def add_array(self, pts) -> None:
        """Grow by an ``(n, 3)`` NumPy array (or nested sequence)."""
        import numpy as np
        a = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        if not len(a):
            return
        mn, mx = a.min(axis=0), a.max(axis=0)
        self.add(float(mn[0]), float(mn[1]), float(mn[2]))
        self.add(float(mx[0]), float(mx[1]), float(mx[2]))

    def offset(self):
        """:func:`survey_offset` of this box."""
        return survey_offset(self.lo, self.hi)


def survey_offset(lo, hi):
    """The ``(x, y, z)`` to subtract from a file whose box is ``lo``..``hi``
    (metres, Z-up), or ``None`` when it sits near enough the origin to be
    read as it is. Whole metres, from the low corner — a value the user can
    read back off the status bar and add to any coordinate."""
    if not all(math.isfinite(c) for c in (*lo, *hi)) or lo[0] > hi[0]:
        return None
    if max(abs(c) for c in (*lo, *hi)) <= RECENTER_BEYOND_M:
        return None
    return tuple(float(int(c)) for c in lo)
