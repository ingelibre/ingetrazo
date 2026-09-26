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


def _layer_name(name: str) -> str:
    return (name or "VISTA").strip().upper().replace(" ", "_") or "VISTA"


def save_dxf_lines(path: str | Path, segments, layer: str = "VISTA") -> int:
    """Write ``segments`` — an iterable of (x0, y0, x1, y1) in metres —
    as LINE entities on ``layer``. Returns the number of lines written."""
    return save_dxf_layers(path, [(layer, segments)])


def save_dxf_layers(path: str | Path, groups) -> int:
    """Write several ``(layer, segments)`` groups into one DXF — the
    composer's line classes (edges / profiles / section cut) each on its
    own layer, so the CAD's pen table gives them their weights. Empty
    groups still declare their layer. Returns the number of lines written.

    R12 ASCII needs no HEADER section; readers default sensibly, and
    omitting it sidesteps every version-variable there is.

    A group may carry a third element, its linetype: ``"DASHED"`` for the
    hidden lines (issue #81) — declared in an LTYPE table so any CAD draws
    that layer dashed on its own."""
    names: dict = {}
    for group in groups:
        name = _layer_name(group[0])
        ltype = group[2] if len(group) > 2 and group[2] else "CONTINUOUS"
        names.setdefault(name, ltype)
    dashed = "DASHED" in names.values()
    n = 0
    with open(path, "w", encoding="ascii", errors="replace") as f:
        w = f.write
        w("0\nSECTION\n2\nTABLES\n")
        if dashed:
            # 0.5 drawing units of dash, 0.25 of gap (metres at 1:1; the
            # CAD's LTSCALE adapts it to the plot scale).
            w("0\nTABLE\n2\nLTYPE\n70\n1\n"
              "0\nLTYPE\n2\nDASHED\n70\n0\n3\n__ __ __ __\n72\n65\n"
              "73\n2\n40\n0.75\n49\n0.5\n49\n-0.25\n0\nENDTAB\n")
        w(f"0\nTABLE\n2\nLAYER\n70\n{len(names)}\n")
        for name, ltype in names.items():
            w(f"0\nLAYER\n2\n{name}\n70\n0\n62\n7\n6\n{ltype}\n")
        w("0\nENDTAB\n0\nENDSEC\n")
        w("0\nSECTION\n2\nENTITIES\n")
        for group in groups:
            layer, segments = group[0], group[1]
            name = _layer_name(layer)
            for x0, y0, x1, y1 in segments:
                w(f"0\nLINE\n8\n{name}\n"
                  f"10\n{x0:.9g}\n20\n{y0:.9g}\n30\n0\n"
                  f"11\n{x1:.9g}\n21\n{y1:.9g}\n31\n0\n")
                n += 1
        w("0\nENDSEC\n0\nEOF\n")
    return n
