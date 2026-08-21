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

``path`` is always a real file on disk (the renderer, and every exporter, load
the image from there). Images that came in *inside* something — extracted from
an imported ``.skp``, unpacked from an ``.igz`` container — live in the app's
own **texture cache** (:func:`texture_cache_root`), never next to the user's
files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QVector3D

from core.triangulate import plane_axes


def texture_cache_root() -> Path:
    """Root of the app's texture cache: ``<user data>/IngeTrazo/textures``
    (``~/.local/share/…`` on Linux, ``%LOCALAPPDATA%\\…`` on Windows). Built
    from ``GenericDataLocation`` rather than ``AppDataLocation`` so the path
    does not depend on ``QCoreApplication``'s org/app names being set (scripts
    and tests would otherwise land in a different folder).
    ``$INGETRAZO_TEXTURE_CACHE`` overrides it (tests, and users who want the
    images somewhere else).

    Two subfolders, one per source: ``skp/`` (images extracted from an imported
    ``.skp``) and ``embedded/`` (images unpacked from an ``.igz`` container)."""
    import os
    override = os.environ.get("INGETRAZO_TEXTURE_CACHE")
    if override:
        return Path(override)
    base = ""
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.GenericDataLocation)
    except Exception:  # noqa: BLE001 — no Qt paths (headless odd env): use $HOME
        base = ""
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "IngeTrazo" / "textures"


def texture_cache_stats() -> tuple[int, int]:
    """``(file count, total bytes)`` currently held in the texture cache."""
    root = texture_cache_root()
    count = total = 0
    if root.is_dir():
        for f in root.rglob("*"):
            try:
                if f.is_file():
                    count += 1
                    total += f.stat().st_size
            except OSError:
                continue
    return count, total


def clear_texture_cache() -> int:
    """Delete the whole texture cache. Returns the number of files removed.
    Documents saved as ``.igz`` containers re-extract their images the next
    time they are opened; faces whose image came from a ``.skp`` import lose
    their texture until the ``.skp`` is imported again — the caller is expected
    to confirm first."""
    import shutil
    root = texture_cache_root()
    count = texture_cache_stats()[0]
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    return count


def cache_image(data: bytes, name: str, subdir: str) -> Path:
    """Store ``data`` in the texture cache under ``subdir`` and return its
    path. **Content-addressed**: the file name carries a hash of the bytes, so
    the same image shared by several documents is written (and uploaded to the
    GPU) once, and a rewrite of the same file is a no-op."""
    import hashlib
    digest = hashlib.sha1(data).hexdigest()[:16]
    safe = "".join(c for c in Path(name).name
                   if c.isalnum() or c in " ._-").strip(" .")
    out = texture_cache_root() / subdir / f"{digest}-{safe or 'texture.png'}"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.stat().st_size != len(data):
            out.write_bytes(data)
        return out
    except OSError:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="ingetrazo-tex-")) / (safe or "t.png")
        tmp.write_bytes(data)
        return tmp


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
    n = len(points)
    if n < 3 or len(uvs) < n:
        return None
    if hasattr(points[0], "x"):
        pts = [p.toTuple() for p in points]
    else:
        pts = points
    # The edge pair with the largest cross product gives the stablest fit.
    # The search is O(n²); |a×b|² = |a|²|b|² − (a·b)² keeps it cheap. Small
    # polygons (the bulk) run pure Python; big ones (imported faces can carry
    # hundreds of vertices) go through one NumPy Gram matmul — a per-pair
    # Python loop over those dominated .skp import.
    x0, y0, z0 = pts[0]
    d = [(x - x0, y - y0, z - z0) for x, y, z in pts[1:]]
    m = n - 1
    if m <= 12:
        best = 1e-24
        bi = bj = -1
        for i in range(m):
            ax, ay, az = d[i]
            for j in range(i + 1, m):
                bx, by, bz = d[j]
                cx = ay * bz - az * by
                cy = az * bx - ax * bz
                cz = ax * by - ay * bx
                c2 = cx * cx + cy * cy + cz * cz
                if c2 > best:
                    best = c2
                    bi, bj = i, j
        if bi < 0:
            return None
    else:
        import numpy as np
        dn = np.asarray(d, dtype=np.float64)
        gram = dn @ dn.T
        n2 = np.einsum("ij,ij->i", dn, dn)
        cl2 = np.multiply.outer(n2, n2) - gram * gram
        flat = int(np.argmax(cl2))
        bi, bj = flat // m, flat % m
        if cl2[bi, bj] <= 1e-24:
            return None
    e1x, e1y, e1z = d[bi]
    e2x, e2y, e2z = d[bj]
    g11 = e1x * e1x + e1y * e1y + e1z * e1z
    g12 = e1x * e2x + e1y * e2y + e1z * e2z
    g22 = e2x * e2x + e2y * e2y + e2z * e2z
    det = g11 * g22 - g12 * g12
    if abs(det) < 1e-18:
        return None
    i = bi + 1
    j = bj + 1
    out = []
    for k in (0, 1):                       # u, then v
        d1 = uvs[i][k] - uvs[0][k]
        d2 = uvs[j][k] - uvs[0][k]
        a = (d1 * g22 - d2 * g12) / det
        b = (d2 * g11 - d1 * g12) / det
        gx = e1x * a + e2x * b
        gy = e1y * a + e2y * b
        gz = e1z * a + e2z * b
        c = uvs[0][k] - (gx * x0 + gy * y0 + gz * z0)
        out.extend([gx, gy, gz, c])
    return out


def affine_uv(uvw, positions):
    """Evaluate a fitted world→UV map (see :func:`fit_uv_affine`) at points."""
    gu = QVector3D(uvw[0], uvw[1], uvw[2])
    gv = QVector3D(uvw[4], uvw[5], uvw[6])
    return [(QVector3D.dotProduct(gu, p) + uvw[3],
             QVector3D.dotProduct(gv, p) + uvw[7]) for p in positions]
