# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""COLLADA (.dae) import — open the models SketchUp exports natively.

COLLADA is Khronos' open XML interchange format; parsing with the stdlib
``xml.etree`` keeps the project dependency-free. Scope (matching what
SketchUp emits): ``library_geometries`` meshes (``triangles`` / ``polylist``
/ ``polygons``), the ``visual_scene`` node tree with baked transforms
(``matrix`` / ``translate`` / ``rotate`` / ``scale``), component instancing
via ``library_nodes`` / ``instance_node``, lambert/phong diffuse colours,
``up_axis`` (Y_UP → Z-up conversion) and the ``unit`` metre scale (SketchUp
exports inches). Textures are skipped (colour only).

Like the OBJ importer, triangles are fused back into clean editable polygons
(coplanar merge) and closed results get a consistent outward orientation.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtGui import QMatrix4x4, QVector3D

_NS = "{http://www.collada.org/2005/11/COLLADASchema}"


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _floats(text) -> list[float]:
    return [float(t) for t in (text or "").split()]


def _ints(text) -> list[int]:
    return [int(t) for t in (text or "").split()]


class _Dae:
    """One parsed document: id-indexed libraries + resolved world geometry."""

    def __init__(self, root) -> None:
        self.root = root
        self.by_id: dict = {}
        for el in root.iter():
            i = el.get("id")
            if i is not None:
                self.by_id[i] = el
        asset = root.find(f"{_NS}asset")
        self.scale = 1.0
        self.up = "Z_UP"
        if asset is not None:
            unit = asset.find(f"{_NS}unit")
            if unit is not None and unit.get("meter"):
                self.scale = float(unit.get("meter"))
            up = asset.find(f"{_NS}up_axis")
            if up is not None and up.text:
                self.up = up.text.strip()

    def ref(self, url: str):
        return self.by_id.get((url or "").lstrip("#"))

    def to_zup(self, p: QVector3D) -> QVector3D:
        s = self.scale
        if self.up == "Y_UP":
            return QVector3D(p.x() * s, -p.z() * s, p.y() * s)
        if self.up == "X_UP":
            return QVector3D(p.y() * s, p.x() * s, p.z() * s)
        return QVector3D(p.x() * s, p.y() * s, p.z() * s)


def _source_floats(dae: _Dae, source_el) -> tuple[list[float], int]:
    arr = source_el.find(f"{_NS}float_array")
    data = _floats(arr.text if arr is not None else "")
    stride = 3
    tc = source_el.find(f"{_NS}technique_common")
    if tc is not None:
        acc = tc.find(f"{_NS}accessor")
        if acc is not None and acc.get("stride"):
            stride = int(acc.get("stride"))
    return data, stride


def _positions(dae: _Dae, mesh_el) -> list[QVector3D]:
    verts = mesh_el.find(f"{_NS}vertices")
    if verts is None:
        return []
    for inp in verts.findall(f"{_NS}input"):
        if inp.get("semantic") == "POSITION":
            src = dae.ref(inp.get("source"))
            if src is None:
                return []
            data, stride = _source_floats(dae, src)
            return [QVector3D(data[i], data[i + 1], data[i + 2])
                    for i in range(0, len(data) - 2, stride)]
    return []


def _vertex_offset_and_stride(prim_el) -> tuple[int, int]:
    """The VERTEX input's offset within the interleaved ``<p>`` stream, and
    the stream stride (max offset + 1)."""
    v_off, max_off = 0, 0
    for inp in prim_el.findall(f"{_NS}input"):
        off = int(inp.get("offset", "0"))
        max_off = max(max_off, off)
        if inp.get("semantic") == "VERTEX":
            v_off = off
    return v_off, max_off + 1


def _prim_loops(prim_el, positions) -> list[list[int]]:
    """Vertex-index loops of one ``triangles``/``polylist``/``polygons``."""
    kind = _tag(prim_el)
    v_off, stride = _vertex_offset_and_stride(prim_el)
    loops: list[list[int]] = []
    if kind == "triangles":
        p = prim_el.find(f"{_NS}p")
        idx = _ints(p.text if p is not None else "")
        verts_per = 3 * stride
        for k in range(0, len(idx) - verts_per + 1, verts_per):
            loops.append([idx[k + j * stride + v_off] for j in range(3)])
    elif kind == "polylist":
        vc = prim_el.find(f"{_NS}vcount")
        p = prim_el.find(f"{_NS}p")
        counts = _ints(vc.text if vc is not None else "")
        idx = _ints(p.text if p is not None else "")
        pos = 0
        for c in counts:
            loops.append([idx[pos + j * stride + v_off] for j in range(c)])
            pos += c * stride
    elif kind == "polygons":
        for p in prim_el.findall(f"{_NS}p"):
            idx = _ints(p.text)
            n = len(idx) // stride
            loops.append([idx[j * stride + v_off] for j in range(n)])
    return [lp for lp in loops
            if len(lp) >= 3 and all(0 <= i < len(positions) for i in lp)]


def _effect_color(dae: _Dae, material_el):
    """Diffuse RGB of a material (lambert/phong), or ``None``."""
    ie = material_el.find(f"{_NS}instance_effect")
    effect = dae.ref(ie.get("url")) if ie is not None else None
    if effect is None:
        return None
    for shader in ("lambert", "phong", "blinn", "constant"):
        for el in effect.iter(f"{_NS}{shader}"):
            diffuse = el.find(f"{_NS}diffuse")
            if diffuse is None:
                continue
            col = diffuse.find(f"{_NS}color")
            if col is not None:
                vals = _floats(col.text)
                if len(vals) >= 3:
                    return vals[:3]
    return None


def _material_map(dae: _Dae, inst_geom_el) -> dict:
    """symbol → RGB for one ``instance_geometry``'s bound materials."""
    out: dict = {}
    for im in inst_geom_el.iter(f"{_NS}instance_material"):
        mat = dae.ref(im.get("target"))
        if mat is not None:
            color = _effect_color(dae, mat)
            if color is not None:
                out[im.get("symbol")] = color
    return out


def _node_matrix(node_el) -> QMatrix4x4:
    m = QMatrix4x4()
    for el in node_el:
        t = _tag(el)
        if t == "matrix":
            vals = _floats(el.text)
            if len(vals) == 16:
                mm = QMatrix4x4(*vals)     # COLLADA matrices are row-major
                m = m * mm
        elif t == "translate":
            v = _floats(el.text)
            if len(v) >= 3:
                m.translate(v[0], v[1], v[2])
        elif t == "rotate":
            v = _floats(el.text)
            if len(v) >= 4:
                m.rotate(v[3], v[0], v[1], v[2])
        elif t == "scale":
            v = _floats(el.text)
            if len(v) >= 3:
                m.scale(v[0], v[1], v[2])
    return m


def _collect(dae: _Dae, node_el, xform: QMatrix4x4, out: list,
             depth: int = 0) -> None:
    """Walk a node tree, baking transforms; instances recurse into
    ``library_nodes`` (SketchUp components)."""
    if depth > 32:
        return                                     # cyclic instance guard
    m = xform * _node_matrix(node_el)
    for el in node_el:
        t = _tag(el)
        if t == "node":
            _collect(dae, el, m, out, depth)
        elif t == "instance_node":
            target = dae.ref(el.get("url"))
            if target is not None:
                _collect(dae, target, m, out, depth + 1)
        elif t == "instance_geometry":
            geom = dae.ref(el.get("url"))
            if geom is None:
                continue
            colors = _material_map(dae, el)
            mesh_el = geom.find(f"{_NS}mesh")
            if mesh_el is None:
                continue
            positions = _positions(dae, mesh_el)
            world = [m.map(p) for p in positions]
            for prim in mesh_el:
                kind = _tag(prim)
                if kind not in ("triangles", "polylist", "polygons"):
                    continue
                color = colors.get(prim.get("material"))
                for lp in _prim_loops(prim, world):
                    out.append(([world[i] for i in lp], color))


def load_dae(scene, path) -> None:
    """Add the geometry of a COLLADA file at ``path`` to ``scene``'s mesh.
    Adds to the current scene; the caller wraps it for undo."""
    from core.history import run_stitch
    from core.orient import orient_outward
    from core.topology import _key

    root = ET.parse(Path(path)).getroot()
    dae = _Dae(root)
    pending: list = []
    for vs in root.iter(f"{_NS}visual_scene"):
        for node in vs.findall(f"{_NS}node"):
            _collect(dae, node, QMatrix4x4(), pending)
    if not pending:
        # No visual scene (bare geometry library): import it un-instanced.
        for geom in root.iter(f"{_NS}geometry"):
            mesh_el = geom.find(f"{_NS}mesh")
            if mesh_el is None:
                continue
            positions = _positions(dae, mesh_el)
            for prim in mesh_el:
                if _tag(prim) in ("triangles", "polylist", "polygons"):
                    for lp in _prim_loops(prim, positions):
                        pending.append(([positions[i] for i in lp], None))
    if not pending:
        raise ValueError("No geometry found in the COLLADA file")

    seed: set = set()
    new_faces = set()
    for loop, color in pending:
        pts = [dae.to_zup(p) for p in loop]
        try:
            face = scene.mesh.add_face(pts)
        except Exception:  # noqa: BLE001 — skip a degenerate polygon
            continue
        new_faces.add(face)
        if color is not None:
            face.attrs["color"] = [float(c) for c in color[:3]]
        for p in pts:
            seed.add(_key(p))

    # Fuse the exported triangles back into clean polygons and give a closed
    # result a consistent outward orientation — same pipeline as OBJ import.
    run_stitch(scene.mesh, seed, new_faces, coplanar_merge=True)
    orient_outward(scene.mesh)
    scene.version += 1
