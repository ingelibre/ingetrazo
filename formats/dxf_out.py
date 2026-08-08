# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Minimal DXF writer for composer view exports (C4).

Writes an ASCII DXF R12 with LINE entities — the least common denominator
every CAD opens, IngeCAD included (the bridge the ecosystem plan calls
for: IngeTrazo produces the 2D view, IngeCAD signs and prints it).
Coordinates go out in MODEL units (metres): the drawing is the true-size
orthographic view, not paper.
"""
from __future__ import annotations

from pathlib import Path


def save_dxf_lines(path: str | Path, segments, layer: str = "VISTA") -> int:
    """Write ``segments`` — an iterable of (x0, y0, x1, y1) in metres —
    as LINE entities on ``layer``. Returns the number of lines written.

    R12 ASCII needs no HEADER section; readers default sensibly, and
    omitting it sidesteps every version-variable there is."""
    layer = (layer or "VISTA").strip().upper().replace(" ", "_") or "VISTA"
    n = 0
    with open(path, "w", encoding="ascii", errors="replace") as f:
        w = f.write
        w("0\nSECTION\n2\nTABLES\n")
        w("0\nTABLE\n2\nLAYER\n70\n1\n")
        w(f"0\nLAYER\n2\n{layer}\n70\n0\n62\n7\n6\nCONTINUOUS\n")
        w("0\nENDTAB\n0\nENDSEC\n")
        w("0\nSECTION\n2\nENTITIES\n")
        for x0, y0, x1, y1 in segments:
            w(f"0\nLINE\n8\n{layer}\n"
              f"10\n{x0:.9g}\n20\n{y0:.9g}\n30\n0\n"
              f"11\n{x1:.9g}\n21\n{y1:.9g}\n31\n0\n")
            n += 1
        w("0\nENDSEC\n0\nEOF\n")
    return n
