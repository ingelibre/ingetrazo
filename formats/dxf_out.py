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


#: The line types a view export may declare: description and pattern in
#: drawing units (dash > 0, gap < 0, dot 0).
_LTYPES = {
    "DASHED": ("__ __ __ __", (0.5, -0.25)),
    "HIDDEN": ("_ _ _ _ _ _", (0.25, -0.125)),
    "DASHEDX2": ("____  ____  ____", (1.0, -0.5)),
    "DOT": (". . . . . .", (0.0, -0.25)),
    "DASHDOT": ("__ . __ . __", (0.5, -0.25, 0.0, -0.25)),
    "DIVIDE": ("__ . . __ . . __", (0.5, -0.25, 0.0, -0.25, 0.0, -0.25)),
    "CENTER": ("____ _ ____ _ ____", (1.25, -0.25, 0.25, -0.25)),
    "PHANTOM": ("____ _ _ ____ _ _", (1.25, -0.25, 0.25, -0.25, 0.25, -0.25)),
    "BORDER": ("__ __ . __ __ .", (0.5, -0.25, 0.5, -0.25, 0.0, -0.25)),
}


def _nearest_aci(rgb) -> int:
    """The standard palette colour (1–255, 7 excluded) closest to ``rgb``
    (0–1 floats)."""
    try:
        from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb
    except ImportError:                       # pragma: no cover
        return 7
    r, g, b = (float(c) * 255.0 for c in rgb[:3])
    best, best_d = 7, float("inf")
    for aci in range(1, 256):
        if aci == 7:
            continue
        cr, cg, cb = int2rgb(DXF_DEFAULT_COLORS[aci])
        d = (cr - r) ** 2 + (cg - g) ** 2 + (cb - b) ** 2
        if d < best_d:
            best, best_d = aci, d
    return best


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
    hidden lines (issue #81), ``"DASHDOT"`` or ``"DOT"`` for a model layer
    inked that way — declared in an LTYPE table so any CAD draws that layer
    so on its own. A fourth, an RGB colour (0–1), colours the layer with
    the nearest colour of the standard palette (R12 has no true colour)."""
    names: dict = {}
    colors: dict = {}
    for group in groups:
        name = _layer_name(group[0])
        ltype = group[2] if len(group) > 2 and group[2] else "CONTINUOUS"
        names.setdefault(name, ltype)
        if len(group) > 3 and group[3] is not None:
            colors.setdefault(name, _nearest_aci(group[3]))
    used = [lt for lt in _LTYPES if lt in names.values()]
    n = 0
    with open(path, "w", encoding="ascii", errors="replace") as f:
        w = f.write
        w("0\nSECTION\n2\nTABLES\n")
        if used:
            # In drawing units (metres at 1:1; the CAD's LTSCALE adapts
            # them to the plot scale).
            w(f"0\nTABLE\n2\nLTYPE\n70\n{len(used)}\n")
            for lt in used:
                desc, pattern = _LTYPES[lt]
                total = sum(abs(d) for d in pattern)
                w(f"0\nLTYPE\n2\n{lt}\n70\n0\n3\n{desc}\n72\n65\n"
                  f"73\n{len(pattern)}\n40\n{total:g}\n")
                for d in pattern:
                    w(f"49\n{d:g}\n")
            w("0\nENDTAB\n")
        w(f"0\nTABLE\n2\nLAYER\n70\n{len(names)}\n")
        for name, ltype in names.items():
            w(f"0\nLAYER\n2\n{name}\n70\n0\n62\n{colors.get(name, 7)}\n"
              f"6\n{ltype}\n")
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
