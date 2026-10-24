# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DXF writer for view exports (composer C4, File ▸ Export ▸ Current view).

Writes a DXF R2000 with LINE entities through ezdxf: a real HEADER with
``$INSUNITS``, a LTYPE table and one LAYER per line class — what Illustrator,
LibreCAD, AutoCAD and IngeCAD all read as vectors (issue #428). The drawing
is the true-size orthographic view, not paper, in the document's length
unit.
"""
from __future__ import annotations

import re
from pathlib import Path

import ezdxf

from core.units import length_number

#: The DXF release written: R2000 is the oldest that carries a full header
#: and the newest that every CAD, Illustrator included, opens.
DXF_VERSION = "R2000"

#: ``$INSUNITS`` code of each document length unit. The fractional and
#: feet-and-inches forms follow the number a length field shows for them
#: (``core.units.length_number``): decimal feet, or decimal inches.
_INSUNITS = {"m": 6, "cm": 5, "mm": 4, "in": 1, "in-frac": 1,
             "ft": 2, "ft-in": 2, "ft-in-frac": 2}

#: Dash and gap of the DASHED linetype in metres at 1:1; the CAD's LTSCALE
#: adapts it to the plot scale.
_DASH_M, _GAP_M = 0.5, 0.25

_INVALID_LAYER_CHARS = re.compile(r'[<>/\\":;?*|=`\x00-\x1f]')


def _layer_name(name: str) -> str:
    clean = _INVALID_LAYER_CHARS.sub("_", (name or "VISTA").strip().upper())
    return clean.replace(" ", "_")[:255] or "VISTA"


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
    hidden lines (issue #81) — declared in the LTYPE table so any CAD draws
    that layer dashed on its own."""
    unit = units if units in _INSUNITS else "m"
    scale = length_number(1.0, unit)
    doc = ezdxf.new(DXF_VERSION, units=_INSUNITS[unit])
    doc.header["$MEASUREMENT"] = 0 if unit in ("in", "in-frac", "ft", "ft-in",
                                               "ft-in-frac") else 1
    doc.linetypes.add(
        "DASHED", [(_DASH_M + _GAP_M) * scale, _DASH_M * scale,
                   -_GAP_M * scale], description="Dashed __ __ __ __")
    msp = doc.modelspace()
    declared: set[str] = set()
    n = 0
    for group in groups:
        name = _layer_name(group[0])
        ltype = group[2] if len(group) > 2 and group[2] else "CONTINUOUS"
        if name not in declared:
            doc.layers.add(name, color=7, linetype=ltype)
            declared.add(name)
        for x0, y0, x1, y1 in group[1]:
            msp.add_line((x0 * scale, y0 * scale), (x1 * scale, y1 * scale),
                         dxfattribs={"layer": name})
            n += 1
    doc.saveas(str(path))
    return n
