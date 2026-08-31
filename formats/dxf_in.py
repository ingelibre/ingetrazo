# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DXF import (D1) — what SketchUp's CAD import does for a 2D plan, per its
official doc ("Importing and Exporting CAD Files"):

- LINE / LWPOLYLINE / POLYLINE / ARC / CIRCLE / ELLIPSE / SPLINE come in as
  edges; curved entities are flattened and share ONE curve id each, so a
  circle imported from CAD selects as one contour, exactly like a drawn one.
- Block INSERTs are expanded in place (components arrive in D2); text,
  dimensions and hatches are skipped, as SketchUp skips them.
- CAD layers become groups-with-tags — SketchUp's documented "Import Layers
  as Groups" behaviour, and the shape that works with our layer system: a
  group carries a tag and toggling the tag hides it; per-edge tags inside a
  group's mesh would be dead weight.
- Units come from ``$INSUNITS``; a header that does not say is asked about,
  never guessed in silence (the OBJ importer's rule).
- **UTM recentring**: municipal drawings sit at N≈8,200,000 m, where the
  engine's float32 quantisation (weld keys, GPU chunks) only resolves about
  half a metre — geometry would collapse. Anything that far out is shifted
  to the origin and the offset reported, SketchUp's "move close to the
  origin" advice applied automatically where it stops being advice and
  becomes arithmetic.

Parsed with ezdxf (MIT), the same library IngeCAD reads its DXF with — one
set of format scars shared across the family. DWG rides the LibreDWG
``dwg2dxf`` satellite in D3, IngeCAD's ``dwg_bridge`` pattern.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QVector3D

# Metres per drawing unit, by $INSUNITS code (DXF reference, group 70).
_INSUNITS_TO_M = {
    1: 0.0254,       # inches
    2: 0.3048,       # feet
    3: 1609.344,     # miles
    4: 0.001,        # millimetres
    5: 0.01,         # centimetres
    6: 1.0,          # metres
    7: 1000.0,       # kilometres
    10: 0.9144,      # yards
    14: 10.0,        # decametres... rarely seen, kept for completeness
}

#: Coordinates beyond this (metres, after unit scale) trigger recentring:
#: far enough that float32 precision starts eating survey drawings, well
#: past anything drawn around the origin on purpose.
RECENTER_BEYOND_M = 100_000.0

# How finely curves flatten: maximum sagitta in METRES (converted to drawing
# units per file). 1 cm reads as a smooth curve at plan scales without
# exploding a big circle into thousands of edges.
_SAGITTA_M = 0.01

_CURVED = {"CIRCLE", "ARC", "ELLIPSE", "SPLINE"}
_SKIP_SILENT = {"ATTDEF", "VIEWPORT", "XLINE", "RAY"}
_MAX_INSERT_DEPTH = 8


def read_unit_scale(path: Path):
    """``(metres_per_unit, code)`` from the header, or ``(None, 0)`` when the
    file does not say (unitless DXF — the caller must ask the user)."""
    import ezdxf

    try:
        doc = ezdxf.readfile(str(path))
    except Exception:
        return None, 0
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    return _INSUNITS_TO_M.get(code), code


def load_dxf(scene, path, progress=None, scale: float = 1.0) -> dict:
    """See :func:`_load_dxf_inner`. Wrapped with the generational GC off —
    the same mass-construction guard every importer here carries."""
    import gc
    was = gc.isenabled()
    gc.disable()
    try:
        return _load_dxf_inner(scene, path, progress=progress, scale=scale)
    finally:
        if was:
            gc.enable()


def _read_document(path: Path):
    """ezdxf's strict reader, falling back to its recover mode — real-world
    DXF (LibreDWG conversions included) is often structurally bruised."""
    import ezdxf
    from ezdxf import recover

    try:
        return ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(str(path))
        return doc


def _iter_entities(space, depth: int = 0):
    """Every drawable entity, with INSERTs expanded in place. A child on
    layer "0" inherits its INSERT's layer (the CAD convention). Yields
    ``(entity, layer_name)``."""
    for e in space:
        kind = e.dxftype()
        layer = getattr(e.dxf, "layer", "0") or "0"
        if kind in ("INSERT", "MINSERT") and depth < _MAX_INSERT_DEPTH:
            try:
                children = list(e.virtual_entities())
            except Exception:
                continue                    # a broken block loses only itself
            for child, sub in _iter_entities(children, depth + 1):
                yield child, (layer if sub == "0" else sub)
            continue
        yield e, layer


def _entity_segments(e, sagitta: float):
    """``(segments, curved)`` for one entity: a list of point runs (each run
    is a connected polyline of Vec3s) and whether it was a curve (one curve
    id for the whole run)."""
    kind = e.dxftype()
    if kind == "LINE":
        return [[e.dxf.start, e.dxf.end]], False
    if kind in ("LWPOLYLINE", "POLYLINE") or kind in _CURVED:
        from ezdxf import path as _path

        try:
            p = _path.make_path(e)
            pts = list(p.flattening(sagitta, segments=8))
        except Exception:
            return [], False
        if len(pts) < 2:
            return [], False
        curved = kind in _CURVED
        if not curved:
            # A polyline with arc bulges is a curve for selection purposes;
            # an all-straight one stays plain edges (SketchUp's feel).
            curved = bool(getattr(e, "has_arc", False))
            if kind == "POLYLINE":
                try:
                    curved = any(abs(v.dxf.bulge) > 1e-12
                                 for v in e.vertices)
                except Exception:
                    curved = False
        return [pts], curved
    return None, False                      # unsupported → caller counts it


def _load_dxf_inner(scene, path, progress=None, scale: float = 1.0) -> dict:
    from core.group import Group
    from core.layers import Layer
    from core.mesh import Mesh

    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    path = Path(path)
    tick(0.05, "Reading file…")
    doc = _read_document(path)
    msp = doc.modelspace()
    sagitta = max(_SAGITTA_M / scale, 1e-6)

    tick(0.2, "Collecting entities…")
    per_layer: dict[str, list] = {}         # layer → [(run_points, curved)]
    skipped: dict[str, int] = {}
    entity_count = 0
    for e, layer in _iter_entities(msp):
        kind = e.dxftype()
        segs, curved = _entity_segments(e, sagitta)
        if segs is None:
            if kind not in _SKIP_SILENT:
                skipped[kind] = skipped.get(kind, 0) + 1
            continue
        if not segs:
            continue
        entity_count += 1
        per_layer.setdefault(layer, []).extend(
            (run, curved) for run in segs)
    if not per_layer:
        raise ValueError("no importable geometry (lines, polylines, arcs, "
                         "circles, ellipses or splines) in the model space")

    # ---- Scale to metres, then measure for the UTM recentring ----
    tick(0.45, "Scaling…")
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for runs in per_layer.values():
        for run, _curved in runs:
            for p in run:
                for i, c in enumerate((p.x * scale, p.y * scale,
                                       p.z * scale)):
                    if c < lo[i]:
                        lo[i] = c
                    if c > hi[i]:
                        hi[i] = c
    offset = (0.0, 0.0, 0.0)
    if max(abs(c) for c in lo + hi) > RECENTER_BEYOND_M:
        # Whole metres, so the shift reads clean in a report and survey
        # coordinates stay recoverable by adding it back.
        offset = tuple(float(int(c)) for c in lo)

    # ---- Build one tagged group per CAD layer ----
    tick(0.6, "Building geometry…")
    import numpy as np

    groups_made = 0
    edges_made = 0
    layer_names = sorted(per_layer)
    for li, layer in enumerate(layer_names):
        runs = per_layer[layer]
        pts: list[tuple] = []
        ia: list[int] = []
        ib: list[int] = []
        flags: list[tuple] = []
        for run, curved in runs:
            curve_id = Mesh.next_curve_id() if curved and len(run) > 2 \
                else None
            base = len(pts)
            for p in run:
                pts.append((p.x * scale - offset[0],
                            p.y * scale - offset[1],
                            p.z * scale - offset[2]))
            for k in range(len(run) - 1):
                ia.append(base + k)
                ib.append(base + k + 1)
                flags.append((False, curve_id, None))
        mesh = Mesh()
        vobjs, ids = mesh.bulk_weld(np.array(pts, dtype=np.float64))
        made = mesh.add_edges_welded(
            vobjs, np.asarray(ids)[ia], np.asarray(ids)[ib], flags=flags)
        if not mesh.edges:
            continue
        edges_made += len(mesh.edges)
        group = Group(mesh, name=(layer if layer != "0" else path.stem))
        if layer != "0":
            group.layer = layer
            if scene.layer(layer) is None:
                scene.layers.append(Layer(layer))
        scene.groups.append(group)
        groups_made += 1
        tick(0.6 + 0.35 * (li + 1) / len(layer_names),
             f"Building geometry… {layer}")

    scene.version += 1
    tick(1.0, "Done")
    return {
        "entities": entity_count,
        "edges": edges_made,
        "groups": groups_made,
        "skipped": skipped,
        "offset": offset if offset != (0.0, 0.0, 0.0) else None,
    }
