# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""STL import/export — triangle soup for 3D printing and mesh interchange.

Binary STL: every face (the loose mesh plus every group) is triangulated and
written with its outward geometric normal. The engine keeps solids
outward-consistent (``orient_outward``), so the normals come out right for
slicers. STL carries no colour or units, so the file is written in the unit
the caller picks: ``save_stl`` defaults to the model's own metres, and the
export menu asks — millimetres first, which is what slicers assume (#513).
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

from PySide6.QtGui import QVector3D

STL_UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}
_BINARY_HEADER_SIZE = 84
_BINARY_TRIANGLE_SIZE = 50
_MAX_FLOAT32 = 3.4028234663852886e38
_BATCH_SIZE = 4096


def _faces(scene):
    """Every renderable face in WORLD space: loose mesh + groups. Component
    instances share a prototype mesh in local coordinates, so their faces
    come from a transformed copy."""
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


def iter_triangles(scene):
    """Yield ``(a, b, c)`` world-space triangles for the whole scene."""
    from .meshexport import export_triangles
    for face in _faces(scene):
        yield from export_triangles(face)


def _normal(a: QVector3D, b: QVector3D, c: QVector3D) -> QVector3D:
    n = QVector3D.crossProduct(b - a, c - a)
    length = n.length()
    return n / length if length > 1e-12 else QVector3D(0.0, 0.0, 0.0)


def _tick(progress, fraction: float, message: str) -> None:
    if progress is not None:
        progress(fraction, message)


def _scaled_point(values, scale: float) -> tuple[float, float, float]:
    point = tuple(value * scale for value in values)
    if not all(math.isfinite(value) and abs(value) <= _MAX_FLOAT32
               for value in point):
        raise ValueError("STL contains a coordinate outside the supported range")
    return point


def _non_degenerate(triangle) -> bool:
    a, b, c = triangle
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (ab[1] * ac[2] - ab[2] * ac[1],
             ab[2] * ac[0] - ab[0] * ac[2],
             ab[0] * ac[1] - ab[1] * ac[0])
    return math.hypot(*cross) > 1e-12


def _ascii_stl(path: Path, scale: float, progress, file_size: int):
    state = "outside"
    vertices = []
    line_number = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        while True:
            line = source.readline()
            if not line:
                break
            line_number += 1
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            keyword = parts[0].lower()
            if state == "outside":
                if keyword == "facet":
                    if (len(parts) != 5 or parts[1].lower() != "normal"):
                        raise ValueError(
                            f"Invalid STL facet normal on line {line_number}")
                    try:
                        normal = tuple(float(value) for value in parts[2:])
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid STL facet normal on line {line_number}") from exc
                    if not all(math.isfinite(value) for value in normal):
                        raise ValueError(
                            f"Non-finite STL facet normal on line {line_number}")
                    vertices = []
                    state = "outer"
                elif keyword not in ("solid", "endsolid"):
                    continue
            elif state == "outer":
                if len(parts) != 2 or keyword != "outer" or \
                        parts[1].lower() != "loop":
                    raise ValueError(
                        f"Expected 'outer loop' on STL line {line_number}")
                state = "vertices"
            elif state == "vertices":
                if keyword != "vertex" or len(parts) != 4:
                    raise ValueError(
                        f"Expected an STL vertex on line {line_number}")
                try:
                    point = _scaled_point(
                        (float(value) for value in parts[1:]), scale)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid STL vertex on line {line_number}: {exc}") from exc
                vertices.append(point)
                if len(vertices) == 3:
                    state = "endloop"
            elif state == "endloop":
                if keyword != "endloop" or len(parts) != 1:
                    raise ValueError(
                        f"Expected 'endloop' on STL line {line_number}")
                state = "endfacet"
            elif state == "endfacet":
                if keyword != "endfacet" or len(parts) != 1:
                    raise ValueError(
                        f"Expected 'endfacet' on STL line {line_number}")
                yield tuple(vertices)
                state = "outside"
            if line_number % 4096 == 0:
                fraction = min(source.tell() / max(file_size, 1), 1.0)
                _tick(progress, 0.05 + 0.65 * fraction, "Reading file…")
    if state != "outside":
        raise ValueError("STL ASCII facet is incomplete")


def load_stl(scene, path, progress=None, scale: float = 1.0,
             simplify_mode: str = "none") -> None:
    """Add binary or ASCII STL geometry to ``scene``.

    STL has no unit declaration, so callers supply the metres-per-unit scale.
    ``simplify_mode`` is ``"none"``, ``"principal"`` (XY/XZ/YZ planes), or
    ``"all"`` (coplanar surfaces in any orientation); curved facets stay split.
    Small imports are merged into the editable loose mesh; larger imports are
    kept as a named reference group to avoid costly topology cleanup.
    """
    target = parse_stl(path, progress=progress, scale=scale,
                       simplify_mode=simplify_mode)
    add_stl_mesh(scene, path, target)


def parse_stl(path, progress=None, scale: float = 1.0,
              simplify_mode: str = "none"):
    """Parse and prepare STL geometry without touching a scene.

    Safe to call from a worker thread; returned mesh insertion belongs on the
    UI thread via :func:`add_stl_mesh`.
    """
    import gc

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        return _parse_stl_inner(Path(path), progress=progress, scale=scale,
                                simplify_mode=simplify_mode)
    finally:
        if was_enabled:
            gc.enable()


def _parse_stl_inner(path: Path, progress=None, scale: float = 1.0,
                     simplify_mode: str = "none"):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("STL unit scale must be a positive finite number")
    if simplify_mode not in ("none", "principal", "all"):
        raise ValueError("STL simplification mode must be none, principal, or all")
    _tick(progress, 0.02, "Reading file…")

    size = path.stat().st_size
    binary = False
    with path.open("rb") as source:
        header = source.read(_BINARY_HEADER_SIZE)
        if len(header) == _BINARY_HEADER_SIZE:
            (count,) = struct.unpack_from("<I", header, 80)
            expected_size = (_BINARY_HEADER_SIZE
                             + count * _BINARY_TRIANGLE_SIZE)
            binary = (size >= expected_size
                      and (size == expected_size
                           or header[:5].lower() != b"solid"))

    from core.mesh import Mesh
    target = Mesh()
    batch = []
    np = None

    def flush_batch():
        nonlocal np
        if not batch:
            return
        if np is None:
            import numpy as np_module
            np = np_module
        count = len(batch)
        positions = np.asarray(batch, dtype=np.float64).reshape(-1, 3)
        target.add_faces_bulk(
            positions,
            np.full(count, 3, dtype=np.int64),
            np.ones(count, dtype=np.int64))
        batch.clear()

    if binary:
        with path.open("rb") as source:
            source.seek(_BINARY_HEADER_SIZE)
            for index in range(count):
                record = source.read(_BINARY_TRIANGLE_SIZE)
                if len(record) != _BINARY_TRIANGLE_SIZE:
                    raise ValueError("STL binary facet data is truncated")
                data = struct.unpack("<12fH", record)
                triangle = tuple(
                    _scaled_point(data[i:i + 3], scale) for i in (3, 6, 9))
                if _non_degenerate(triangle):
                    batch.append(triangle)
                    if len(batch) >= _BATCH_SIZE:
                        flush_batch()
                if index % max(count // 100, 1) == 0:
                    _tick(progress, 0.05 + 0.65 * (index + 1) /
                          max(count, 1), "Reading file…")
    else:
        for triangle in _ascii_stl(path, scale, progress, size):
            if _non_degenerate(triangle):
                batch.append(triangle)
                if len(batch) >= _BATCH_SIZE:
                    flush_batch()
    flush_batch()

    if not target.faces:
        raise ValueError("STL file contains no usable triangles")

    from formats.dae import _MAX_FUSE_LOOPS
    if simplify_mode != "none":
        from formats.fuse import simplify_mesh

        _tick(progress, 0.75, "Merging flat surfaces…")
        simplify_mesh(
            target, principal_planes=simplify_mode == "principal")

    if len(target.faces) > _MAX_FUSE_LOOPS:
        _tick(progress, 1.0, "Done")
        return target

    from core.history import run_stitch
    from core.orient import orient_outward
    from core.topology import _key

    seed = {_key(point) for face in target.faces for point in face.vertices}
    new_faces = set(target.faces)
    _tick(progress, 0.85, "Joining triangles…")
    if simplify_mode != "none":
        orient_outward(target)
    else:
        run_stitch(target, seed, new_faces, coplanar_merge=True)
        orient_outward(target, only=new_faces)
    _tick(progress, 1.0, "Done")
    return target


def add_stl_mesh(scene, path, target) -> None:
    """Insert a prepared STL mesh into a scene (must run on the UI thread)."""
    from formats.dae import _MAX_FUSE_LOOPS

    if len(target.faces) > _MAX_FUSE_LOOPS:
        from core.group import Group
        scene.groups.append(Group(target, name=Path(path).stem))
    else:
        for face in target.faces:
            scene.mesh.add_face(face.vertices, face.holes)
    scene.version += 1


def save_stl(scene, path, unit: str = "m") -> None:
    """Write the scene as a binary STL to ``path``, its coordinates in
    ``unit`` (a key of ``STL_UNITS``). The model is in metres; a slicer reads
    an STL as millimetres, so a metre file came in 1000x too small (#513)."""
    scale = 1.0 / STL_UNITS[unit]
    tris = list(iter_triangles(scene))
    with open(Path(path), "wb") as f:
        f.write(b"IngeTrazo STL export".ljust(80, b"\x00"))  # 80-byte header
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = _normal(a, b, c)    # unit length: the scale leaves it alone
            f.write(struct.pack(
                "<12fH",
                n.x(), n.y(), n.z(),
                *_scaled_point((a.x(), a.y(), a.z()), scale),
                *_scaled_point((b.x(), b.y(), b.z()), scale),
                *_scaled_point((c.x(), c.y(), c.z()), scale),
                0,  # attribute byte count
            ))
