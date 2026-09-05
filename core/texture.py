# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Image textures, mapped the SketchUp way for interchange compatibility.

A SketchUp material is a colour plus an optional texture image with a
**real-world tile size** (the model-unit width/height one repeat of the image
covers). The default mapping is a **planar projection**: a face's UVs come from
its world position projected onto the face plane, divided by the tile size. The
projection basis depends only on the face normal — SketchUp's own, see
:func:`projection_basis` — so coplanar faces share it and the texture tiles
**seamlessly** across a flat surface, and a face painted here shows the image
where SketchUp will draw it for the same file.

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
import re
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


_DIGEST_PREFIX = re.compile(r"^(?:[0-9a-f]{16}-)+")
NAME_LIMIT = 64     # characters kept of an image name inside the cache


def texture_file_name(name: str) -> str:
    """Filesystem-safe base name for an image called ``name``: characters
    outside the safe set dropped, any content-hash prefix the name already
    carried (from a cached file or an archive member) stripped, and the whole
    clipped to :data:`NAME_LIMIT`. Stripping is what keeps a document from
    stacking ``<hash>-<hash>-…-sumari.png`` one level deeper on every save —
    0.3.10 did exactly that until the cache path outgrew Windows' 260-character
    limit and the file refused to open; clipping keeps any name inside it."""
    safe = "".join(c for c in Path(name).name
                   if c.isalnum() or c in " ._-").strip(" .")
    safe = _DIGEST_PREFIX.sub("", safe).strip(" .")
    if len(safe) > NAME_LIMIT:
        stem, dot, ext = safe.rpartition(".")
        if dot and 0 < len(ext) <= 5 and ext.isalnum():
            safe = stem[:NAME_LIMIT - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            safe = safe[:NAME_LIMIT].rstrip(" .")
    return safe or "texture.png"


def cache_image(data: bytes, name: str, subdir: str) -> Path:
    """Store ``data`` in the texture cache under ``subdir`` and return its
    path. **Content-addressed**: the file name carries a hash of the bytes, so
    the same image shared by several documents is written (and uploaded to the
    GPU) once, and a rewrite of the same file is a no-op. ``name`` goes through
    :func:`texture_file_name`, so feeding a cached file's own name back in
    lands on the same file instead of a longer one."""
    import hashlib
    digest = hashlib.sha1(data).hexdigest()[:16]
    safe = texture_file_name(name)
    out = texture_cache_root() / subdir / f"{digest}-{safe}"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.stat().st_size != len(data):
            out.write_bytes(data)
        return out
    except OSError:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="ingetrazo-tex-")) / safe
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


#: |Z × n| below which SketchUp projects a face with the world axes (X, ±Y)
#: instead of the cross product — measured with the SDK, see
#: :func:`projection_basis`.
SKETCHUP_VERTICAL_TOLERANCE = 1e-3


def projection_basis(normal) -> tuple[tuple[float, float, float],
                                      tuple[float, float, float]]:
    """SketchUp's in-plane axes for a face normal ``(nx, ny, nz)`` — the
    basis its default texture projection AND its per-face texture matrices
    are expressed in: ``xr = normalize(Z × n)``, ``yr = n × xr``; for a
    vertical normal ``(X, Y)`` looking up and ``(−X, Y)`` looking down.
    Plain tuples: the ``.skp`` importer runs this per vertex over large
    models.

    THE one recipe for the whole app. The renderer, the OBJ/glTF writers and
    the paste preview used to project with ``core.triangulate.plane_axes``
    (world X projected onto the plane) while the ``.skp`` importer already
    used this one: on a wall facing +Y or −X the two differ by 180°, so a
    texture painted in IngeTrazo showed upside-down against what SketchUp
    draws for the very same file (measured through the SDK's own converter,
    2026-09-04). Calibrated against SketchUp ground truth for every
    orientation, not just the axis-aligned ones.

    ``Z × n`` is discontinuous at the vertical: for ``n = (ε, 0, 1)`` it
    points along +Y however small ε is, for ``(0, ε, 1)`` along −X. Real
    SketchUp resolves that with a tolerance, measured with the SDK on
    faces tilted by ε from 1e-10 to 1e-2 (2026-09-04): the world axes
    ``(X, ±Y)`` while ``|Z × n| < 1e-3`` (the sine of the tilt), the cross
    product from 1.0001e-3 up. The same tolerance here keeps a horizontal
    face whose normal carries float noise — up to 6e-4 on the small faces
    of Marco's pool — projected the way SketchUp projects the plane it
    reads back from the file; with the old 1e-9 every such face came out
    turned 90°."""
    nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
    ln = (nx * nx + ny * ny + nz * nz) ** 0.5
    if ln > 1e-30:
        nx, ny, nz = nx / ln, ny / ln, nz / ln
    xx, xy = -ny, nx                      # Z × n
    lx = (xx * xx + xy * xy) ** 0.5
    if lx < SKETCHUP_VERTICAL_TOLERANCE:
        # Measured, not derived: a face looking DOWN gets (−X, +Y), the
        # 180° turn of the upward (X, Y) — not the (X, −Y) mirror the
        # reader assumed. Every underside of the pool (slabs, benches,
        # countertops) came out upside-down until the SDK said so.
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) if nz > 0 \
            else ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    xx, xy = xx / lx, xy / lx
    return (xx, xy, 0.0), (-nz * xy, nz * xx, nx * xy - ny * xx)   # n × xr


def projection_axes(normal, rot: float = 0.0) -> tuple[QVector3D, QVector3D]:
    """:func:`projection_basis` as ``QVector3D`` axes, turned in-plane by
    ``rot`` degrees (SketchUp's texture rotation)."""
    n = QVector3D(normal)
    xr, yr = projection_basis((n.x(), n.y(), n.z()))
    u_axis, v_axis = QVector3D(*xr), QVector3D(*yr)
    if rot:
        import math
        a = math.radians(rot)
        cos_a, sin_a = math.cos(a), math.sin(a)
        u_axis, v_axis = (u_axis * cos_a + v_axis * sin_a,
                          v_axis * cos_a - u_axis * sin_a)
    return u_axis, v_axis


def planar_uv(normal: QVector3D, positions, sw: float, sh: float,
              rot: float = 0.0):
    """SketchUp-style planar-projected ``(u, v)`` for each world ``positions``
    point: project onto SketchUp's plane basis for ``normal`` (so coplanar
    faces tile seamlessly), scaled by the tile size. ``rot`` turns the texture
    in-plane by that many degrees (SketchUp's texture rotation). ``sw``/``sh``
    ≤ 0 fall back to 1 to avoid a divide-by-zero."""
    u_axis, v_axis = projection_axes(normal, rot)
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
    """Evaluate a fitted world→UV map (see :func:`fit_uv_affine`) at points
    — ``QVector3D`` or plain ``(x, y, z)`` sequences alike."""
    ux, uy, uz, uc = uvw[0], uvw[1], uvw[2], uvw[3]
    vx, vy, vz, vc = uvw[4], uvw[5], uvw[6], uvw[7]
    out = []
    for p in positions:
        if hasattr(p, "x"):
            x, y, z = p.x(), p.y(), p.z()
        else:
            x, y, z = p[0], p[1], p[2]
        out.append((ux * x + uy * y + uz * z + uc,
                    vx * x + vy * y + vz * z + vc))
    return out


def face_uv_axes(tex: dict, normal):
    """The affine world→UV map a textured face renders with, as
    ``(gu, cu, gv, cv)``: ``u = gu·p + cu`` and ``v = gv·p + cv`` at any
    world point ``p``.

    ONE definition of "where does the texture sit on this face", so the
    renderer and the ``.skp`` exporter cannot drift apart — the exporter had
    no UV recipe at all and wrote textured faces with no mapping, which is
    why a model saved from IngeTrazo opened in SketchUp with every texture
    gone and only its average colour left.

    Two sources, matching what the face carries: a fitted ``uvw`` (an import
    that brought its own texture coordinates) or, failing that, SketchUp's
    planar projection of world position (:func:`projection_axes`), so
    coplanar faces tile seamlessly and a ``planar`` face — which the .skp
    exporter writes with NO per-face record — lands in SketchUp exactly
    where the viewport drew it."""
    uvw = tex.get("uvw")
    if uvw:
        return (QVector3D(uvw[0], uvw[1], uvw[2]), float(uvw[3]),
                QVector3D(uvw[4], uvw[5], uvw[6]), float(uvw[7]))
    u_axis, v_axis = projection_axes(normal, float(tex.get("rot", 0.0) or 0.0))
    sw = tex.get("sw", 1.0) or 1.0
    sh = tex.get("sh", 1.0) or 1.0
    return (u_axis / sw, 0.0, v_axis / sh, 0.0)


def uv_reference_points(points, normal=None):
    """Three points on the face's plane, forming a well-conditioned triangle,
    for pinning an affine UV map. ``None`` when the face is degenerate.

    NOT face vertices: the map is affine, so it can be sampled anywhere on
    the plane, and picking real corners is what broke the first attempt. A
    long thin face gives three nearly collinear corners — one sampled face in
    piscina.igz had two of them 1.8 inches apart and the third 19 away — and
    fitting a map through that sliver amplifies float error enough to come
    back rotated. A right-angled triad on the face's own plane, sized to the
    face, is exact and always conditioned."""
    pts = [QVector3D(p) for p in points]
    if len(pts) < 3:
        return None
    centre = QVector3D()
    for p in pts:
        centre += p
    centre /= float(len(pts))
    n = QVector3D(normal) if normal is not None else None
    if n is None or n.lengthSquared() < 1e-18:
        # Newell over the ring: robust for any polygon, and the caller may
        # not have a normal to give.
        n = QVector3D()
        count = len(pts)
        for i in range(count):
            a, b = pts[i], pts[(i + 1) % count]
            n += QVector3D((a.y() - b.y()) * (a.z() + b.z()),
                           (a.z() - b.z()) * (a.x() + b.x()),
                           (a.x() - b.x()) * (a.y() + b.y()))
    if n.lengthSquared() < 1e-18:
        return None
    e1, e2 = plane_axes(n.normalized())
    span = max((p - centre).length() for p in pts)
    if span < 1e-9:
        return None
    return centre, centre + e1 * span, centre + e2 * span
