# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DXF import — SketchUp's CAD import behaviour (official doc: "Importing
and Exporting CAD Files"), on our machinery. D1 + D2:

- LINE / LWPOLYLINE / POLYLINE / ARC / CIRCLE / ELLIPSE / SPLINE come in as
  edges; curved entities are flattened and share ONE curve id each, so a
  circle imported from CAD selects as one contour, exactly like a drawn one.
- **Blocks become components** (D2): each used block definition builds ONE
  prototype mesh in local metres, and every INSERT is an O(1) placement
  (``Group.xform``) — 500 trees are one proto and 500 matrices, the sharing
  SketchUp gives nested blocks (piscina's hedge lesson). INSERTs *inside* a
  block explode into its prototype for now (nested sharing deferred);
  MINSERT arrays explode in place.
- **3DFACE / SOLID / TRACE become faces** (D2), then each mesh that gained
  faces runs the stitch + coplanar merge every importer here uses — a
  triangulated CAD terrain comes back as clean polygons, SketchUp's "Merge
  coplanar faces" option always on.
- Text, dimensions, hatches and points are skipped, as SketchUp skips them.
- CAD layers become groups-with-tags — SketchUp's documented "Import Layers
  as Groups" behaviour, the shape that works with our layer system. Block
  instances carry their INSERT's layer the same way.
- Units: the header's ``$INSUNITS`` is only a *claim* — offices copy
  templates and never look ("Detalles Plaza Yanque" declares millimetres
  while drawn in metres). :func:`suggest_unit_scale` measures the drawing
  itself (median entity size) and vetoes a header that produces doors a
  millimetre wide; the dialog preselects the verdict, the user confirms.
- **UTM recentring**: municipal drawings sit at N≈8,200,000 m, where the
  engine's float32 quantisation (weld keys, GPU chunks) only resolves about
  half a metre — geometry would collapse. Anything that far out is shifted
  to the origin and the offset reported.

Parsed with ezdxf (MIT), the same library IngeCAD reads its DXF with — one
set of format scars shared across the family. DWG rides the LibreDWG
``dwg2dxf`` satellite in D3, IngeCAD's ``dwg_bridge`` pattern.

DEFERRED, documented: nested block sharing (children placements), the
"import linework flattened to Z=0" option, HATCH boundaries as edges.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QMatrix4x4, QVector3D

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
}

#: Coordinates beyond this (metres, after unit scale) trigger recentring:
#: far enough that float32 precision starts eating survey drawings, well
#: past anything drawn around the origin on purpose.
RECENTER_BEYOND_M = 100_000.0

# How finely curves flatten: maximum sagitta in METRES (converted to drawing
# units per file). 1 cm reads as a smooth curve at plan scales without
# exploding a big circle into thousands of edges.
_SAGITTA_M = 0.01

# A drawing whose MEDIAN entity size (metres) falls in this range is built
# at human scale — walls, kerbs, pipes. Outside it, the unit is lying.
_SANE_MEDIAN_M = (0.05, 80.0)

_CURVED = {"CIRCLE", "ARC", "ELLIPSE", "SPLINE"}
_FACES = {"3DFACE", "SOLID", "TRACE"}
_SKIP_SILENT = {"ATTDEF", "VIEWPORT", "XLINE", "RAY"}
_MAX_INSERT_DEPTH = 8


# ---- Reading ---------------------------------------------------------------
def open_document(path: Path):
    """ezdxf's strict reader, falling back to its recover mode — real-world
    DXF (LibreDWG conversions included) is often structurally bruised."""
    import ezdxf
    from ezdxf import recover

    try:
        return ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(str(path))
        return doc


def read_unit_scale(path):
    """``(metres_per_unit, code)`` from the header, or ``(None, 0)`` when the
    file does not say (unitless DXF)."""
    doc = path if hasattr(path, "header") else None
    if doc is None:
        try:
            doc = open_document(Path(path))
        except Exception:
            return None, 0
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    return _INSUNITS_TO_M.get(code), code


def suggest_unit_scale(doc) -> tuple:
    """``(scale_or_None, header_code)`` — the header's declared unit unless
    the drawing's own content rules it out (the OBJ importer's
    ``suggest_unit`` doctrine, adapted to CAD's lying headers).

    The evidence is the MEDIAN entity size over a sample: line lengths,
    circle diameters, polyline segment spans, in raw drawing units. The
    header wins while its reading lands the median at human scale; when it
    does not, the candidate unit that does is suggested instead."""
    header_scale, code = read_unit_scale(doc)
    sizes: list[float] = []
    try:
        msp = doc.modelspace()
    except Exception:
        return header_scale, code
    for e in msp:
        if len(sizes) >= 4000:
            break
        kind = e.dxftype()
        try:
            if kind == "LINE":
                sizes.append((e.dxf.end - e.dxf.start).magnitude)
            elif kind == "CIRCLE":
                sizes.append(2.0 * float(e.dxf.radius))
            elif kind == "ARC":
                sizes.append(2.0 * float(e.dxf.radius))
            elif kind == "LWPOLYLINE":
                pts = e.get_points("xy")
                for k in range(len(pts) - 1):
                    dx = pts[k + 1][0] - pts[k][0]
                    dy = pts[k + 1][1] - pts[k][1]
                    sizes.append((dx * dx + dy * dy) ** 0.5)
        except Exception:
            continue
    sizes = [s for s in sizes if s > 1e-9]
    if not sizes:
        return header_scale, code
    sizes.sort()
    median = sizes[len(sizes) // 2]

    def sane(scale: float) -> bool:
        return _SANE_MEDIAN_M[0] <= median * scale <= _SANE_MEDIAN_M[1]

    if header_scale is not None and sane(header_scale):
        return header_scale, code
    # Metres first: the 1-unit-=-1-metre habit is the region's default.
    for candidate in (1.0, 0.01, 0.001, 0.0254, 0.3048):
        if sane(candidate):
            return candidate, code
    return header_scale, code


# ---- Entity translation ----------------------------------------------------
def _iter_flat(space, depth: int = 0):
    """Entities with INSERTs expanded in place — used for MINSERT arrays and
    for the *contents of a block* while nested sharing stays deferred. A
    child on layer "0" inherits its INSERT's layer (the CAD convention).
    Yields ``(entity, layer_name)``."""
    for e in space:
        kind = e.dxftype()
        layer = getattr(e.dxf, "layer", "0") or "0"
        if kind in ("INSERT", "MINSERT") and depth < _MAX_INSERT_DEPTH:
            try:
                children = list(e.virtual_entities())
            except Exception:
                continue                    # a broken block loses only itself
            for child, sub in _iter_flat(children, depth + 1):
                yield child, (layer if sub == "0" else sub)
            continue
        yield e, layer


def _entity_segments(e, sagitta: float):
    """``(runs, curved)``: connected point runs for a linework entity, or
    ``(None, False)`` for kinds this function does not translate."""
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
    return None, False


def _entity_face(e):
    """The corner loop of a face entity, or ``None``. SOLID/TRACE store their
    quad in Z order — corners 2 and 3 swap to walk the perimeter."""
    kind = e.dxftype()
    if kind not in _FACES:
        return None
    d = e.dxf
    if kind == "3DFACE":
        pts = [d.vtx0, d.vtx1, d.vtx2]
        if d.vtx3 is not None and (d.vtx3 - d.vtx2).magnitude > 1e-12:
            pts.append(d.vtx3)
    else:                                   # SOLID / TRACE
        pts = [d.vtx0, d.vtx1, d.vtx3, d.vtx2]
        if (pts[2] - pts[3]).magnitude < 1e-12:
            pts = pts[:3]                   # degenerate quad = triangle
    seen: list = []
    for p in pts:
        if not seen or (p - seen[-1]).magnitude > 1e-12:
            seen.append(p)
    return seen if len(seen) >= 3 else None


class _Bucket:
    """Linework + faces collected for one destination mesh."""

    __slots__ = ("runs", "faces")

    def __init__(self) -> None:
        self.runs: list = []                # (point_run, curved)
        self.faces: list = []               # point loops


def _scan(space, sagitta, skipped, counter, per_layer, depth=0):
    """Sort a container's entities into per-layer buckets; return the
    top-level INSERT placements ``(block_name, matrix44, layer)`` found."""
    placements = []
    for e in space:
        kind = e.dxftype()
        layer = getattr(e.dxf, "layer", "0") or "0"
        if kind == "INSERT":
            try:
                m = e.matrix44()
                placements.append((e.dxf.name, m, layer))
                counter[0] += 1
                continue
            except Exception:
                pass                        # fall through to exploding it
        if kind in ("INSERT", "MINSERT"):
            for child, sub in _iter_flat([e], depth):
                _bucket_one(child, sub, sagitta, skipped, counter, per_layer)
            continue
        _bucket_one(e, layer, sagitta, skipped, counter, per_layer)
    return placements


def _bucket_one(e, layer, sagitta, skipped, counter, per_layer) -> None:
    kind = e.dxftype()
    loop = _entity_face(e)
    if loop is not None:
        counter[0] += 1
        per_layer.setdefault(layer, _Bucket()).faces.append(loop)
        return
    runs, curved = _entity_segments(e, sagitta)
    if runs is None:
        if kind not in _SKIP_SILENT:
            skipped[kind] = skipped.get(kind, 0) + 1
        return
    if not runs:
        return
    counter[0] += 1
    bucket = per_layer.setdefault(layer, _Bucket())
    bucket.runs.extend((run, curved) for run in runs)


def _build_mesh(bucket: _Bucket, scale: float, offset) -> "Mesh":
    """One welded Mesh from a bucket, in metres, recentred by ``offset``.
    Faces stitch + coplanar-merge afterwards, the OBJ importer's closing
    move, so triangulated CAD comes back as clean polygons."""
    import numpy as np

    from core.mesh import Mesh

    mesh = Mesh()
    pts: list[tuple] = []
    ia: list[int] = []
    ib: list[int] = []
    flags: list[tuple] = []
    for run, curved in bucket.runs:
        curve_id = Mesh.next_curve_id() if curved and len(run) > 2 else None
        base = len(pts)
        for p in run:
            pts.append((p.x * scale - offset[0],
                        p.y * scale - offset[1],
                        p.z * scale - offset[2]))
        for k in range(len(run) - 1):
            ia.append(base + k)
            ib.append(base + k + 1)
            flags.append((False, curve_id, None))
    if pts:
        vobjs, ids = mesh.bulk_weld(np.array(pts, dtype=np.float64))
        mesh.add_edges_welded(vobjs, np.asarray(ids)[ia],
                              np.asarray(ids)[ib], flags=flags)
    if bucket.faces:
        from core.history import run_stitch
        from core.topology import _key

        added = []
        seed = set()
        for loop in bucket.faces:
            corners = [QVector3D(p.x * scale - offset[0],
                                 p.y * scale - offset[1],
                                 p.z * scale - offset[2]) for p in loop]
            try:
                f = mesh.add_face(corners)
            except Exception:
                continue                    # degenerate sliver: only itself
            if f is not None:
                added.append(f)
                seed.update(_key(c) for c in corners)
        if added:
            try:
                run_stitch(mesh, seed, set(added), coplanar_merge=True)
            except Exception:
                pass                        # merge is a nicety, never fatal
    return mesh


def _fold_xform(m44, scale: float, offset) -> QMatrix4x4:
    """ezdxf's row-vector Matrix44 (translation in row 3) as the QMatrix4x4
    of a prototype in METRES: the linear part is scale-conjugation-invariant,
    the translation scales to metres and takes the recentring."""
    r = [m44.get_row(i) for i in range(4)]
    return QMatrix4x4(
        r[0][0], r[1][0], r[2][0], r[3][0] * scale - offset[0],
        r[0][1], r[1][1], r[2][1], r[3][1] * scale - offset[1],
        r[0][2], r[1][2], r[2][2], r[3][2] * scale - offset[2],
        0.0, 0.0, 0.0, 1.0)


# ---- The loader ------------------------------------------------------------
def load_dxf(scene, path, progress=None, scale: float = 1.0,
             doc=None, name: str | None = None) -> dict:
    """See :func:`_load_dxf_inner`. Wrapped with the generational GC off —
    the same mass-construction guard every importer here carries."""
    import gc
    was = gc.isenabled()
    gc.disable()
    try:
        return _load_dxf_inner(scene, path, progress=progress, scale=scale,
                               doc=doc, name=name)
    finally:
        if was:
            gc.enable()


def _load_dxf_inner(scene, path, progress=None, scale: float = 1.0,
                    doc=None, name: str | None = None) -> dict:
    from core.group import Group
    from core.layers import Layer

    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    path = Path(path)
    tick(0.05, "Reading file…")
    if doc is None:
        doc = open_document(path)
    msp = doc.modelspace()
    sagitta = max(_SAGITTA_M / scale, 1e-6)

    # ---- Pass 1: sort model space into buckets + component placements ----
    tick(0.2, "Collecting entities…")
    per_layer: dict[str, _Bucket] = {}
    skipped: dict[str, int] = {}
    counter = [0]
    placements = _scan(msp, sagitta, skipped, counter, per_layer)

    # ---- Block prototypes (one mesh per used definition, local metres) ----
    proto_buckets: dict[str, dict] = {}
    for block_name, _m, _layer in placements:
        if block_name in proto_buckets:
            continue
        try:
            block = doc.blocks[block_name]
        except Exception:
            continue
        # One bucket regardless of the inner layers: the INSTANCE carries
        # the tag; per-layer splits inside a component are deferred.
        bucket = _Bucket()
        for child, _sub in _iter_flat(block):
            _bucket_one(child, "0", sagitta, skipped, [0], {"0": bucket})
        proto_buckets[block_name] = {"0": bucket}

    if not per_layer and not any(
            b["0"].runs or b["0"].faces for b in proto_buckets.values()):
        raise ValueError("no importable geometry (lines, polylines, arcs, "
                         "circles, ellipses, splines or faces) in the "
                         "model space")

    # ---- Measure for the UTM recentring (placements count too) ----
    tick(0.45, "Scaling…")
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3

    def absorb(x, y, z):
        for i, c in enumerate((x, y, z)):
            if c < lo[i]:
                lo[i] = c
            if c > hi[i]:
                hi[i] = c

    for bucket in per_layer.values():
        for run, _c in bucket.runs:
            for p in run:
                absorb(p.x * scale, p.y * scale, p.z * scale)
        for loop in bucket.faces:
            for p in loop:
                absorb(p.x * scale, p.y * scale, p.z * scale)
    for _bname, m, _layer in placements:
        t = m.get_row(3)
        absorb(t[0] * scale, t[1] * scale, t[2] * scale)
    offset = (0.0, 0.0, 0.0)
    if lo[0] < hi[0] and max(abs(c) for c in lo + hi) > RECENTER_BEYOND_M:
        offset = tuple(float(int(c)) for c in lo)

    # ---- Build: one tagged group per layer, one proto per block ----
    tick(0.6, "Building geometry…")
    groups_made = 0
    edges_made = 0
    faces_made = 0

    def ensure_tag(layer_name: str) -> None:
        if layer_name != "0" and scene.layer(layer_name) is None:
            scene.layers.append(Layer(layer_name))

    for layer in sorted(per_layer):
        mesh = _build_mesh(per_layer[layer], scale, offset)
        if not mesh.edges and not mesh.faces:
            continue
        edges_made += len(mesh.edges)
        faces_made += len(mesh.faces)
        group = Group(mesh, name=(layer if layer != "0"
                                  else (name or path.stem)))
        if layer != "0":
            group.layer = layer
            ensure_tag(layer)
        scene.groups.append(group)
        groups_made += 1

    tick(0.75, "Placing components…")
    protos: dict[str, object] = {}
    components: dict[str, int] = {}
    for block_name, buckets in proto_buckets.items():
        mesh = _build_mesh(buckets["0"], scale, (0.0, 0.0, 0.0))
        if mesh.edges or mesh.faces:
            protos[block_name] = mesh
    for block_name, m44, layer in placements:
        proto = protos.get(block_name)
        if proto is None:
            continue                        # annotation-only block
        inst = Group(proto, name=block_name)
        inst.xform = _fold_xform(m44, scale, offset)
        if layer != "0":
            inst.layer = layer
            ensure_tag(layer)
        scene.groups.append(inst)
        groups_made += 1
        components[block_name] = components.get(block_name, 0) + 1
        edges_made += (len(proto.edges)
                       if components[block_name] == 1 else 0)

    if groups_made == 0:
        raise ValueError("no importable geometry (lines, polylines, arcs, "
                         "circles, ellipses, splines or faces) in the "
                         "model space")

    scene.version += 1
    tick(1.0, "Done")
    return {
        "entities": counter[0],
        "edges": edges_made,
        "faces": faces_made,
        "groups": groups_made,
        "components": components,
        "skipped": skipped,
        "offset": offset if offset != (0.0, 0.0, 0.0) else None,
    }
