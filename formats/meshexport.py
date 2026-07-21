# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Shared geometry collection for the mesh-interchange exporters (glTF, DAE).

Both formats need the same three things OBJ already does: every renderable face
in **world** coordinates, triangulated and grouped by its material (a solid
``Face.attrs["color"]`` or a textured ``attrs["texture"]``), plus the per-vertex
UVs from the same planar/affine projection the viewport and OBJ use — so a model
exported to any of these formats looks identical. Kept here so glTF and DAE stay
in lock-step and don't each re-derive the material grouping.
"""
from __future__ import annotations

from pathlib import Path

# Cream painted on faces with no material colour (mirrors the viewport default).
_DEFAULT_COLOR = (0.96, 0.95, 0.925)


def world_faces(scene):
    """Every renderable face in WORLD space: loose mesh + groups. Component
    instances share a prototype mesh in local coordinates, so their faces come
    from a transformed copy. Same rule as ``formats.stl`` / ``formats.obj``."""
    if hasattr(scene, "render_faces"):
        groups = getattr(scene, "groups", [])
        if not any(getattr(g, "xform", None) is not None for g in groups):
            yield from scene.render_faces()
            return
        from core.group import world_mesh
        for f in scene.loose_mesh.faces:
            if scene.entity_visible(f):
                yield f
        for g in groups:
            if not scene.entity_visible(g) or getattr(g, "billboard", False):
                continue
            yield from world_mesh(g).faces
    elif hasattr(scene, "mesh"):
        yield from scene.mesh.faces
    else:
        yield from scene.faces


def collect_geometry(scene):
    """Group the scene's triangles by material.

    Returns ``(materials, prims)`` where

    * ``materials[key]`` is ``{"color": (r,g,b), "map": basename|None,
      "src": Path}`` (``src`` present only for textured materials), and
    * ``prims[key]`` is a list of triangles, each ``(normal, verts)`` with
      ``verts`` a list of three ``(position: QVector3D, uv: (u, v) | None)``.

    ``key`` is ``("color", rgb)`` or ``("tex", basename)`` — identical to the
    OBJ exporter's material keys, so painted colours and textures survive.
    """
    from core.texture import affine_uv, planar_uv

    materials: dict[tuple, dict] = {}
    prims: dict[tuple, list] = {}
    for face in world_faces(scene):
        n = face.normal()
        tex = face.attrs.get("texture")
        if tex is not None and tex.get("path"):
            src = Path(tex["path"])
            key = ("tex", src.name)
            materials.setdefault(key, {"color": (1.0, 1.0, 1.0),
                                       "map": src.name, "src": src})
            sw = tex.get("sw", 1.0) or 1.0
            sh = tex.get("sh", 1.0) or 1.0
            rot = float(tex.get("rot", 0.0))
            uvw = tex.get("uvw")
            for tri in face.triangulate():
                pts = list(tri)
                uv = affine_uv(uvw, pts) if uvw else planar_uv(n, pts, sw, sh, rot)
                prims.setdefault(key, []).append(
                    (n, [(pts[k], (uv[k][0], uv[k][1])) for k in range(3)]))
        else:
            col = tuple(face.attrs.get("color") or _DEFAULT_COLOR)
            key = ("color", col)
            materials.setdefault(key, {"color": col, "map": None})
            for tri in face.triangulate():
                pts = list(tri)
                prims.setdefault(key, []).append(
                    (n, [(pts[k], None) for k in range(3)]))
    return materials, prims


def geolocation(scene):
    """The scene's geographic anchor as ``(lat, lon, alt)`` in degrees/metres,
    or ``None`` when the scene has no georef datum. This is what carries the
    model's location (for sun/shadow studies) across the export."""
    g = getattr(scene, "georef", None)
    if g is None:
        return None
    lat = getattr(g, "lat", None)
    lon = getattr(g, "lon", None)
    if lat is None or lon is None:
        return None
    return (float(lat), float(lon), float(getattr(g, "alt", 0.0)))
