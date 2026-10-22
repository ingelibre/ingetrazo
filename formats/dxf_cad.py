# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Layered 2D CAD views as DXF — plans, elevations and sections for CAD.

Where ``formats/dxf_out.py`` writes the least common denominator (R12,
LINE only, a layer per line class), this writes what a CAD office files:
an AutoCAD 2010 DXF through ezdxf with one layer per discipline and line
class (``core.cad_layers``), each layer carrying its colour, lineweight
and linetype, lines chained into polylines, and the section cut hatched.
Coordinates are MODEL metres (``$INSUNITS`` = 6): the true-size view, to
be plotted at any scale; ``scale_n`` only sizes the dashes and the hatch
so they read right on paper at 1:N.
"""
from __future__ import annotations

import math
from pathlib import Path

#: Paper size of one dash of a hidden line, and of the hatch spacing, mm.
DASH_MM = 3.0
HATCH_MM = 2.0
#: ezdxf's DASHED: a 0.5-unit dash; ANSI31: lines 3.175 units apart.
_DASHED_UNIT = 0.5
_ANSI31_UNIT = 3.175


def chain_segments(segments, tol: float = 1e-6) -> list:
    """Join segments that meet end to end into polylines: a list of point
    lists, a closed one ending on its first point. Order-independent and
    linear (endpoints hashed on a ``tol`` grid); a node where three or more
    segments meet ends the chains through it."""
    inv = 1.0 / tol

    def key(x, y):
        return (int(round(x * inv)), int(round(y * inv)))

    ends: dict = {}
    segs = [tuple(s) for s in segments]
    for i, (x0, y0, x1, y1) in enumerate(segs):
        ends.setdefault(key(x0, y0), []).append((i, 0))
        ends.setdefault(key(x1, y1), []).append((i, 1))
    used = [False] * len(segs)

    def pt(i, end):
        s = segs[i]
        return (s[0], s[1]) if end == 0 else (s[2], s[3])

    def walk(i, end):
        """From segment i's ``end`` onward: the points beyond it."""
        out = []
        while True:
            nxt = [(j, e) for j, e in ends.get(key(*pt(i, end)), ())
                   if not used[j]]
            if len(ends.get(key(*pt(i, end)), ())) != 2 or len(nxt) != 1:
                return out
            j, e = nxt[0]
            used[j] = True
            i, end = j, 1 - e
            out.append(pt(i, end))

    chains = []
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        fwd = walk(i, 1)
        back = walk(i, 0)
        pts = list(reversed(back)) + [pt(i, 0), pt(i, 1)] + fwd
        chains.append(pts)
    return chains


def save_cad_dxf(path: str | Path, layers: dict, scale_n: float = 100.0,
                 hatch: bool = True) -> int:
    """Write ``layers`` — ``{name: core.cad_layers.CadLayer}`` — as a
    layered DXF at ``path``. Returns the number of segments written (as
    lines, before chaining into polylines)."""
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)    # setup: DASHED & co. declared
    doc.header["$INSUNITS"] = 6             # metres
    doc.header["$MEASUREMENT"] = 1          # metric
    doc.header["$LWDISPLAY"] = 1
    doc.header["$LTSCALE"] = scale_n * DASH_MM / 1000.0 / _DASHED_UNIT
    msp = doc.modelspace()
    hatch_scale = scale_n * HATCH_MM / 1000.0 / _ANSI31_UNIT
    n = 0
    for name, lay in layers.items():
        doc.layers.add(name, color=lay.pen.color,
                       linetype=lay.pen.linetype,
                       lineweight=lay.pen.lineweight)
        attrs = {"layer": name}
        for pts in chain_segments(lay.segments):
            closed = len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-9
            if closed:
                pts = pts[:-1]
            if len(pts) == 2 and not closed:
                msp.add_line(pts[0], pts[1], dxfattribs=attrs)
            else:
                msp.add_lwpolyline(pts, close=closed, dxfattribs=attrs)
        n += len(lay.segments)
        if hatch and lay.fills:
            h = msp.add_hatch(dxfattribs=attrs)
            h.set_pattern_fill("ANSI31", scale=hatch_scale)
            for ring in lay.fills:
                h.paths.add_polyline_path(
                    [(float(x), float(y)) for x, y in ring], is_closed=True)
    doc.saveas(str(path))
    return n
