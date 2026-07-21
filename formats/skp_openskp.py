# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Adapter: an OpenSKP parse → an IngeTrazo geometry payload.

Kept in its own module so ``import openskp`` happens lazily (only when this
backend actually runs) — ``formats/skp.py`` must stay importable without the
optional parser installed.

OpenSKP 0.8-era data model (v0.2.0), discovered by introspection:

* ``SkpFile.open(path).parse()`` → ``SkpModel`` with ``definitions`` (dict:
  id → ``Definition``), ``materials``, ``layers``, ``version``.
* ``Definition``: ``id``, ``name``, ``vertices`` (dict id → ``Vertex(x,y,z)``),
  ``edges`` (dict id → ``Edge(v1_id, v2_id)``), ``faces`` (dict id → ``Face``),
  ``instances`` (list of ``Instance``).
* ``Face``: ``loops`` — a list of loops, each ``[(edge_id, sense), …]``; the
  first loop is the outer boundary, the rest are holes. ``sense`` 1 walks the
  edge ``v1→v2``, 0 walks ``v2→v1``. Plus ``normal`` and ``material_id``.
* ``Instance``: ``matrix`` (a 3×3 rotation/scale row-major + a translation, 13
  floats), ``ref_idx`` (→ the placed definition's id), ``children``.

SketchUp stores lengths in **inches** and is **Z-up** — same up axis as
IngeTrazo, so we only scale (inches → metres); no axis swap. The instance tree
is flattened to world-space polygons (reference geometry, like the big-DAE
import path). Per-face colours resolve through ``SkpModel.materials_by_id``
(added by our upstream PR iamahsanmehmood/openskp#3; absent on PyPI 0.2.0, in
which case faces import uncoloured). Textures are not extracted by the parser
yet — the remaining upstream gap.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QMatrix4x4, QVector3D

_INCH = 0.0254          # SketchUp internal unit → metres
_MAX_DEPTH = 32         # guard against pathological instance nesting


def _ring(defn, loop):
    """Resolve one ``[(edge_id, sense), …]`` loop to a list of local-space
    ``QVector3D`` (metres). Returns ``None`` on any dangling reference."""
    pts = []
    for eid, sense in loop:
        edge = defn.edges.get(eid)
        if edge is None:
            return None
        vid = edge.v1_id if sense else edge.v2_id
        v = defn.vertices.get(vid)
        if v is None:
            return None
        pts.append(QVector3D(v.x * _INCH, v.y * _INCH, v.z * _INCH))
    return pts


def _matrix(m) -> QMatrix4x4:
    """An OpenSKP instance ``matrix`` (row-major 3×3 + translation, in inches)
    as a ``QMatrix4x4`` whose translation is already in metres."""
    return QMatrix4x4(
        m[0], m[1], m[2], m[9] * _INCH,
        m[3], m[4], m[5], m[10] * _INCH,
        m[6], m[7], m[8], m[11] * _INCH,
        0.0, 0.0, 0.0, 1.0)


def _face_attrs(face, mat_by_id):
    """IngeTrazo ``Face.attrs`` for an OpenSKP face — its material colour
    (RGB 0..1) resolved through ``SkpModel.materials_by_id``, or ``None``."""
    mid = getattr(face, "material_id", None)
    if mid is None:
        return None
    mat = mat_by_id.get(mid)
    color = getattr(mat, "color", None) if mat is not None else None
    if not color or len(color) < 3:
        return None
    return {"color": [color[0] / 255.0, color[1] / 255.0, color[2] / 255.0]}


def _collect(defn, xform, by_id, mat_by_id, out, depth, stack) -> None:
    """Append ``(outer, holes, attrs)`` world-space faces for ``defn`` and,
    recursively, for every definition its instances place."""
    if depth > _MAX_DEPTH or id(defn) in stack:
        return
    stack = stack | {id(defn)}
    for face in defn.faces.values():
        loops = getattr(face, "loops", None)
        if not loops:
            continue
        outer = _ring(defn, loops[0])
        if not outer or len(outer) < 3:
            continue
        outer = [xform.map(p) for p in outer]
        holes = []
        for lp in loops[1:]:
            h = _ring(defn, lp)
            if h and len(h) >= 3:
                holes.append([xform.map(p) for p in h])
        out.append((outer, holes, _face_attrs(face, mat_by_id)))
    for ins in getattr(defn, "instances", []):
        child = by_id.get(getattr(ins, "ref_idx", None))
        if child is None:
            continue
        _collect(child, xform * _matrix(ins.matrix), by_id, mat_by_id,
                 out, depth + 1, stack)


def _adapt(model, name: str):
    """An ``SkpModel`` → a payload ``{"backend", "groups"}`` or ``None`` when it
    yields no geometry (so the seam can fall back to skp2dae)."""
    defs = getattr(model, "definitions", {}) or {}
    # Face.material_id -> Material join. Present since our upstream PR
    # (iamahsanmehmood/openskp#3); guarded so PyPI 0.2.0 (no join) still
    # imports — faces then come in uncoloured, like before.
    mat_by_id = getattr(model, "materials_by_id", None) or {}
    by_id = {}
    root = None
    for d in defs.values():
        by_id[getattr(d, "id", None)] = d
        if getattr(d, "name", None) == "ROOT_MODEL":
            root = d
    roots = [root] if root is not None else list(defs.values())
    faces: list = []
    for r in roots:
        _collect(r, QMatrix4x4(), by_id, mat_by_id, faces, 0, set())
    if not faces:
        return None
    return {"backend": "openskp",
            "groups": [{"name": name, "faces": faces}]}


def parse(path, progress=None):
    """Parse ``path`` with OpenSKP and adapt it to a payload, or ``None`` when
    no geometry comes out. Raises whatever OpenSKP raises on a file it cannot
    read (the caller treats that as "fall back to the converter")."""
    import openskp
    if progress is not None:
        progress(0.1, "Parsing .skp (OpenSKP)…")
    model = openskp.SkpFile.open(str(path)).parse()
    if progress is not None:
        progress(0.6, "Building geometry…")
    return _adapt(model, Path(path).stem)
