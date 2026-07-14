# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Image textures, mapped the SketchUp way for interchange compatibility.

A SketchUp material is a colour plus an optional texture image with a
**real-world tile size** (the model-unit width/height one repeat of the image
covers). The default mapping is a **planar projection**: a face's UVs come from
its world position projected onto the face plane, divided by the tile size. The
projection basis depends only on the face normal, so coplanar faces share it and
the texture tiles **seamlessly** across a flat surface — exactly SketchUp's
behaviour, and what makes an exported ``.obj``/``.mtl`` line up the same way in
SketchUp or Blender.

A textured face carries ``attrs["texture"] = {"path", "sw", "sh"}``. Colour and
texture are independent (a face can have either or both).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QVector3D

from core.triangulate import plane_axes


@dataclass
class Texture:
    path: str          # image file
    sw: float = 1.0    # real-world width of one tile (metres)
    sh: float = 1.0    # real-world height of one tile (metres)

    def as_dict(self) -> dict:
        return {"path": self.path, "sw": self.sw, "sh": self.sh}

    @staticmethod
    def from_dict(d: dict) -> "Texture":
        return Texture(d["path"], float(d.get("sw", 1.0)), float(d.get("sh", 1.0)))


def planar_uv(normal: QVector3D, positions, sw: float, sh: float,
              rot: float = 0.0):
    """SketchUp-style planar-projected ``(u, v)`` for each world ``positions``
    point: project onto the plane basis derived from ``normal`` (so coplanar
    faces tile seamlessly), scaled by the tile size. ``rot`` turns the texture
    in-plane by that many degrees (SketchUp's texture rotation). ``sw``/``sh``
    ≤ 0 fall back to 1 to avoid a divide-by-zero."""
    import math

    u_axis, v_axis = plane_axes(normal.normalized())
    if rot:
        a = math.radians(rot)
        cos_a, sin_a = math.cos(a), math.sin(a)
        u_axis, v_axis = (u_axis * cos_a + v_axis * sin_a,
                          v_axis * cos_a - u_axis * sin_a)
    sw = sw if abs(sw) > 1e-9 else 1.0
    sh = sh if abs(sh) > 1e-9 else 1.0
    return [(QVector3D.dotProduct(p, u_axis) / sw,
             QVector3D.dotProduct(p, v_axis) / sh) for p in positions]


def face_uvs(face, tex: dict):
    """Planar UVs for ``face``'s outer-loop vertices from a texture attrs dict."""
    return planar_uv(face.normal(), list(face.vertices),
                     float(tex.get("sw", 1.0)), float(tex.get("sh", 1.0)),
                     float(tex.get("rot", 0.0)))


def fit_uv_affine(points, uvs):
    """World→UV affine map ``[gu.xyz, u0, gv.xyz, v0]`` fitted from a polygon's
    vertices and their explicit UVs (a COLLADA/OBJ import). Any UV assignment
    on a planar polygon is affine over its plane, so evaluating the map at a
    vertex reproduces its UV exactly — which lets coplanar triangles of the
    same original face merge and still texture correctly. Returns ``None``
    when the polygon is degenerate."""
    if len(points) < 3 or len(uvs) < len(points):
        return None
    p0 = points[0]
    # The edge pair with the largest cross product gives the stablest fit.
    best = None
    best_len = 1e-12
    for i in range(1, len(points)):
        for j in range(i + 1, len(points)):
            cl = QVector3D.crossProduct(points[i] - p0,
                                        points[j] - p0).length()
            if cl > best_len:
                best_len = cl
                best = (i, j)
    if best is None:
        return None
    i, j = best
    e1 = points[i] - p0
    e2 = points[j] - p0
    g11 = QVector3D.dotProduct(e1, e1)
    g12 = QVector3D.dotProduct(e1, e2)
    g22 = QVector3D.dotProduct(e2, e2)
    det = g11 * g22 - g12 * g12
    if abs(det) < 1e-18:
        return None
    out = []
    for k in (0, 1):                       # u, then v
        d1 = uvs[i][k] - uvs[0][k]
        d2 = uvs[j][k] - uvs[0][k]
        a = (d1 * g22 - d2 * g12) / det
        b = (d2 * g11 - d1 * g12) / det
        g = e1 * a + e2 * b
        c = uvs[0][k] - QVector3D.dotProduct(g, p0)
        out.extend([g.x(), g.y(), g.z(), c])
    return out


def affine_uv(uvw, positions):
    """Evaluate a fitted world→UV map (see :func:`fit_uv_affine`) at points."""
    gu = QVector3D(uvw[0], uvw[1], uvw[2])
    gv = QVector3D(uvw[4], uvw[5], uvw[6])
    return [(QVector3D.dotProduct(gu, p) + uvw[3],
             QVector3D.dotProduct(gv, p) + uvw[7]) for p in positions]
