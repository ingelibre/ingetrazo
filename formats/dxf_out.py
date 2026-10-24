# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DXF writer for view exports (composer C4, File ▸ Export ▸ Current view).

Writes a DXF R2000 with LINE entities through ezdxf: a real HEADER with
``$INSUNITS``, a LTYPE table and one LAYER per line class or model layer —
what Illustrator, LibreCAD, AutoCAD and IngeCAD all read as vectors (issue
#428). The drawing is the true-size orthographic view, not paper, in the
document's length unit.
"""
from __future__ import annotations

import re
from pathlib import Path

import ezdxf
from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb

from core.units import length_number

#: The DXF release written: R2000 is the oldest that carries a full header
#: and the newest that every CAD, Illustrator included, opens.
DXF_VERSION = "R2000"

#: ``$INSUNITS`` code of each document length unit. The fractional and
#: feet-and-inches forms follow the number a length field shows for them
#: (``core.units.length_number``): decimal feet, or decimal inches.
_INSUNITS = {"m": 6, "cm": 5, "mm": 4, "in": 1, "in-frac": 1,
             "ft": 2, "ft-in": 2, "ft-in-frac": 2}

#: The line types a view export may declare: description and pattern in
#: metres at 1:1 (dash > 0, gap < 0, dot 0); the CAD's LTSCALE adapts them
#: to the plot scale.
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

_INVALID_LAYER_CHARS = re.compile(r'[<>/\\":;?*|=`\x00-\x1f]')


def _layer_name(name: str) -> str:
    clean = _INVALID_LAYER_CHARS.sub("_", (name or "VISTA").strip().upper())
    return clean.replace(" ", "_")[:255] or "VISTA"


def _nearest_aci(rgb) -> int:
    """The standard palette colour (1–255, 7 excluded) closest to ``rgb``
    (0–1 floats)."""
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


def save_dxf_lines(path: str | Path, segments, layer: str = "VISTA",
                   units: str = "m") -> int:
    """Write ``segments`` — an iterable of (x0, y0, x1, y1) in metres —
    as LINE entities on ``layer``. Returns the number of lines written."""
    return save_dxf_layers(path, [(layer, segments)], units)


def save_dxf_layers(path: str | Path, groups, units: str = "m") -> int:
    """Write several ``(layer, segments)`` groups into one DXF — the
    composer's line classes (edges / profiles / section cut) each on its
    own layer, so the CAD's pen table gives them their weights. Empty
    groups still declare their layer. Returns the number of lines written.

    ``segments`` are in metres. They are written in ``units`` (a length
    code of ``core.units``, the document's), declared in ``$INSUNITS``.

    A group may carry a third element, its linetype: ``"DASHED"`` for the
    hidden lines (issue #81), ``"DASHDOT"`` or ``"DOT"`` for a model layer
    inked that way — declared in the LTYPE table so any CAD draws that
    layer so on its own. A fourth, an RGB colour (0–1), colours the layer
    with the nearest colour of the standard palette (R2000 has no true
    colour)."""
    unit = units if units in _INSUNITS else "m"
    scale = length_number(1.0, unit)
    doc = ezdxf.new(DXF_VERSION, units=_INSUNITS[unit])
    doc.header["$MEASUREMENT"] = 0 if unit in ("in", "in-frac", "ft", "ft-in",
                                               "ft-in-frac") else 1
    msp = doc.modelspace()
    n = 0
    for group in groups:
        name = _layer_name(group[0])
        ltype = group[2] if len(group) > 2 and group[2] else "CONTINUOUS"
        if ltype in _LTYPES and ltype not in doc.linetypes:
            desc, pattern = _LTYPES[ltype]
            scaled = [d * scale for d in pattern]
            doc.linetypes.add(ltype, [sum(abs(d) for d in scaled), *scaled],
                              description=desc)
        if name not in doc.layers:
            layer = doc.layers.add(name, color=7, linetype=ltype)
            if len(group) > 3 and group[3] is not None:
                layer.dxf.color = _nearest_aci(group[3])
        for x0, y0, x1, y1 in group[1]:
            msp.add_line((x0 * scale, y0 * scale), (x1 * scale, y1 * scale),
                         dxfattribs={"layer": name})
            n += 1
    doc.saveas(str(path))
    return n
