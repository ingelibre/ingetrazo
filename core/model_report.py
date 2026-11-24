# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model report: areas, volumes and counts of the WHOLE document,
by layer, by material and by component — tagged for BIM or not.

The BIM takeoff (:func:`core.bim.quantities_csv`) only sees what carries
an IFC class, and Model Info's materials table only paint. This report
reads every face and every placed group once and answers the three
questions a budget asks of a plain model: how much of each layer, of each
material, of each component.

Rules, so the numbers can be trusted:

- **World space.** A component's faces live in its definition's local
  coordinates; each placement's matrix puts them in the world. Areas go
  through the matrix's cofactor and volumes through its determinant, so an
  instance scaled ×2 counts four times the area and eight times the
  volume — and a mirrored one counts positive.
- **Net area.** A face's holes are not surface (:func:`core.bim.face_net_area`),
  the same measure the materials table and the BIM takeoff use.
- **The whole model.** Hidden objects and objects on hidden layers count:
  the report must not change with what happens to be switched on.
- **Volume only when closed.** A placement adds a volume when its own mesh
  is a solid (:func:`core.solids.solid_report`); an open shell adds none,
  never a zero that looks like a measurement. A row with no solid at all
  reports ``None``.
- **Layer of a face:** its own when it carries one, else the layer of the
  nearest group above it that carries one, else the default layer.
- **Material of a face:** its own paint, else the paint of the nearest
  group above it (the drawing rule, :func:`core.materials.effective_attrs`),
  else none. A solid's volume goes to a material only when every face of
  it wears that one material — a concrete column, not a painted box.
- **Components:** one row per definition (copies share their mesh); each
  instance counts its whole subtree, nested parts included, so a nested
  component is also inside its parent's row.

Pure data, no GUI: :func:`collect_report` returns rows, :func:`report_csv`
the spreadsheet (raw m² and m³, not the document's display units).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from core.bim import face_net_area

#: The ``grouping`` column of the CSV — machine-readable, never translated.
LAYER, MATERIAL, COMPONENT = "layer", "material", "component"
GROUPINGS = (LAYER, MATERIAL, COMPONENT)
#: The CSV's columns, the same for every row whatever its grouping.
CSV_HEADER = ["grouping", "name", "count", "faces", "area_m2", "volume_m3",
              "value"]


# ---- Matrix helpers ---------------------------------------------------------

def _linear(m):
    """The 3×3 linear part of a QMatrix4x4 as its three columns, or
    ``None`` for the identity (no matrix at all)."""
    if m is None:
        return None
    d = m.data()                                  # column-major, 16 floats
    return ((d[0], d[1], d[2]), (d[4], d[5], d[6]), (d[8], d[9], d[10]))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _cofactor(cols):
    """Columns of the cofactor matrix: what a unit normal × area maps
    through to give the world area vector (works for a flat scale too)."""
    a1, a2, a3 = cols
    return (_cross(a2, a3), _cross(a3, a1), _cross(a1, a2))


def _det(cols):
    a1, a2, a3 = cols
    c = _cross(a2, a3)
    return a1[0] * c[0] + a1[1] * c[1] + a1[2] * c[2]


def _world_area(face, cof) -> float:
    area = face_net_area(face)
    if cof is None or area <= 0.0:
        return area
    n = face.normal()
    nx, ny, nz = n.x(), n.y(), n.z()
    c1, c2, c3 = cof
    w = (nx * c1[0] + ny * c2[0] + nz * c3[0],
         nx * c1[1] + ny * c2[1] + nz * c3[1],
         nx * c1[2] + ny * c2[2] + nz * c3[2])
    return area * (w[0] * w[0] + w[1] * w[1] + w[2] * w[2]) ** 0.5


# ---- Materials ----------------------------------------------------------------

def _paint_of(attrs, container_paint):
    """The paint a face is measured with: its own, else its container's."""
    from core.materials import has_own_material
    if has_own_material(attrs):
        return attrs
    return container_paint


def _material_key(paint):
    """``(key, label, rgb)`` of a paint dict, or ``None`` for no paint."""
    if not paint:
        return None
    name = paint.get("mat")
    tex = paint.get("texture")
    col = paint.get("color")
    rgb = tuple(col[:3]) if col is not None else None
    if name:
        return ("mat", name), name, rgb
    if tex and tex.get("path"):
        return ("tex", tex["path"]), Path(tex["path"]).stem, None
    if col is not None:
        r, g, b = (int(round(c * 255)) for c in rgb)
        return ("rgb", (r, g, b)), f"rgb({r},{g},{b})", rgb
    return None


# ---- Collection -----------------------------------------------------------------

def _row(name: str) -> dict:
    return {"name": name, "count": 0, "faces": 0, "area": 0.0,
            "volume": None}


def _add_volume(row: dict, vol: float) -> None:
    row["volume"] = (row["volume"] or 0.0) + vol


def _walk(groups, base, parent_layer, parent_paint):
    """``(group, world matrix, layer, paint)`` for every placed group,
    depth first — the layer and paint inherited from the nearest
    container that carries one. Hidden placements are NOT skipped."""
    from core.layers import DEFAULT_LAYER
    for g in groups or ():
        m = getattr(g, "xform", None)
        if base is not None:
            m = base if m is None else base * m
        own = getattr(g, "layer", None)
        layer = own if own and own != DEFAULT_LAYER else parent_layer
        paint = getattr(g, "material", None) or parent_paint
        yield g, m, layer, paint
        kids = getattr(g, "children", None)
        if kids:
            yield from _walk(kids, m, layer, paint)


def collect_report(scene) -> dict:
    """The report of ``scene`` as ``{"layer": [...], "material": [...],
    "component": [...]}``; each row is ``{"name", "count", "faces",
    "area" (m²), "volume" (m³ or ``None``)}``, plus ``"visible"`` on a
    layer row and ``"rgb"`` on a material row.

    ``count`` is, per grouping: the groups and component instances drawn
    on that layer (nested ones too); the groups and instances that wear the
    material on at least one face; the component's instances."""
    from core.layers import DEFAULT_LAYER
    from core.solids import solid_report

    layers: dict[str, dict] = {}
    for ly in getattr(scene, "layers", None) or ():
        row = layers.setdefault(ly.name, _row(ly.name))
        row["visible"] = bool(ly.visible)

    def layer_row(name):
        row = layers.get(name)
        if row is None:
            row = layers[name] = _row(name)
            row["visible"] = True
        return row

    materials: dict = {}
    no_paint = _row("")
    no_paint["rgb"] = None

    def material_row(key_label_rgb):
        if key_label_rgb is None:
            return no_paint
        key, label, rgb = key_label_rgb
        row = materials.get(key)
        if row is None:
            row = materials[key] = _row(label)
            row["rgb"] = rgb
        return row

    solid_cache: dict = {}

    def local_volume(mesh):
        vol = solid_cache.get(id(mesh), False)
        if vol is False:
            ok, v = solid_report(mesh)
            vol = solid_cache[id(mesh)] = v if ok else None
        return vol

    def measure(mesh, m, layer, paint):
        """Faces of one placement → (faces, area, {material row: area},
        volume or None, the one material row if uniform)."""
        cols = _linear(m)
        cof = _cofactor(cols) if cols is not None else None
        n = 0
        total = 0.0
        mats: dict = {}
        for f in mesh.faces:
            if getattr(f, "interior", False):
                continue
            area = _world_area(f, cof)
            n += 1
            total += area
            attrs = f.attrs
            lrow = layer_row(attrs.get("layer") or layer)
            lrow["faces"] += 1
            lrow["area"] += area
            mrow = material_row(_material_key(_paint_of(attrs, paint)))
            mrow["faces"] += 1
            mrow["area"] += area
            mats[id(mrow)] = mrow
        vol = local_volume(mesh) if n else None
        if vol is not None and cols is not None:
            vol *= abs(_det(cols))
        return n, total, mats, vol

    # Loose geometry: no object of its own, so no count and no volume.
    measure(scene.loose_mesh, None, DEFAULT_LAYER, None)

    # Every placement, once, with what it measures.
    placed = []
    for g, m, layer, paint in _walk(scene.groups, None, None, None):
        layer = layer or DEFAULT_LAYER
        n, area, mats, vol = measure(g.mesh, m, layer, paint)
        lrow = layer_row(layer)
        lrow["count"] += 1
        if vol is not None:
            _add_volume(lrow, vol)
        for mrow in mats.values():
            mrow["count"] += 1
        if vol is not None and len(mats) == 1:
            _add_volume(next(iter(mats.values())), vol)
        placed.append((g, n, area, vol))

    # Components: each instance sums its own subtree.
    by_group = {id(g): (n, area, vol) for g, n, area, vol in placed}
    components: dict[int, dict] = {}
    for g, _n, _a, _v in placed:
        if not g.is_component():
            continue
        row = components.get(id(g.mesh))
        if row is None:
            row = components[id(g.mesh)] = _row(g.name)
        row["count"] += 1
        stack = [g]
        faces_here = 0
        while stack:
            node = stack.pop()
            n, area, vol = by_group.get(id(node), (0, 0.0, None))
            faces_here += n
            row["area"] += area
            if vol is not None:
                _add_volume(row, vol)
            stack.extend(getattr(node, "children", None) or ())
        # Faces of ONE instance: the definition's size, not the sum.
        row["faces"] = max(row["faces"], faces_here)

    layer_rows = list(layers.values())
    material_rows = sorted(materials.values(),
                           key=lambda r: (-r["area"], r["name"].casefold()))
    if no_paint["faces"]:
        material_rows.append(no_paint)
    component_rows = sorted(components.values(),
                            key=lambda r: r["name"].casefold())
    return {LAYER: layer_rows, MATERIAL: material_rows,
            COMPONENT: component_rows}


# ---- CSV -------------------------------------------------------------------------

def report_csv(report: dict, no_material_label: str = "(no material)",
               groupings=GROUPINGS, extra=()) -> str:
    """The report as one long CSV — a ``grouping`` column (``layer``,
    ``material``, ``component``…) a spreadsheet filters or pivots on.
    Areas in m² and volumes in m³ as raw numbers; an empty volume cell
    means nothing closed was measured there (not zero). Names go through
    the csv module, so ``Paint, white`` stays one cell.

    ``groupings`` picks which tables go in (all three by default: «Export
    all»; one of them: «Export shown»). ``extra`` appends ready rows of
    the same seven columns — Model Info adds its summary, BIM objects and
    location that way; ``value`` is the column for what is neither a
    count nor an area or volume (a length in m, a class, a coordinate)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for grouping in groupings:
        for row in report.get(grouping, ()):
            vol = row["volume"]
            writer.writerow([
                grouping, row["name"] or no_material_label, row["count"],
                row["faces"], f"{row['area']:.4f}",
                "" if vol is None else f"{vol:.4f}", ""])
    for row in extra:
        writer.writerow(row)
    return out.getvalue()
