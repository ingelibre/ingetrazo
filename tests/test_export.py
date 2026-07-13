# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""STL + OBJ export: geometry round-trips (triangle count, vertices), normals
point outward, and per-face colour becomes OBJ materials."""
from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtGui import QVector3D

from core.history import History, SetFaceColorCommand
from core.group import Group
from core.orient import is_closed, orient_outward, signed_volume
from core.scene import Scene
from formats import obj as obj_format
from formats import stl as stl_format
import tests.test_fuzz_engine as F


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cube(scene, hist, size=4.0, height=3.0):
    loop = [V(0, 0), V(size, 0), V(size, size), V(0, size)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    f = scene.mesh.faces[0]
    F._push(scene, hist, f, height if f.normal().z() > 0 else -height)


def _expected_tri_count(scene) -> int:
    return sum(len(f.triangulate()) for f in scene.render_faces())


# ---- STL -----------------------------------------------------------------------

def _read_stl(path):
    with open(path, "rb") as fh:
        fh.read(80)
        (count,) = struct.unpack("<I", fh.read(4))
        tris = []
        for _ in range(count):
            data = struct.unpack("<12fH", fh.read(50))
            n = data[0:3]
            a, b, c = data[3:6], data[6:9], data[9:12]
            tris.append((n, a, b, c))
    return tris


def test_stl_triangle_count_matches(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.stl"
    stl_format.save_stl(scene, path)
    tris = _read_stl(path)
    assert len(tris) == _expected_tri_count(scene)
    assert len(tris) == 12          # a box = 6 quads = 12 triangles


def test_stl_normals_point_outward(tmp_path):
    # The engine keeps solids outward-consistent, so every STL facet normal
    # should point away from the solid's centroid.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    orient_outward(scene.mesh)
    centroid = QVector3D(2, 2, 1.5)
    path = tmp_path / "cube.stl"
    stl_format.save_stl(scene, path)
    for n, a, b, c in _read_stl(path):
        nv = QVector3D(*n)
        tri_centroid = QVector3D(*[(a[i] + b[i] + c[i]) / 3 for i in range(3)])
        outward = tri_centroid - centroid
        assert QVector3D.dotProduct(nv, outward) > 0


def test_stl_includes_groups(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    g = Group()
    p = [V(10, 0, 0), V(12, 0, 0), V(12, 2, 0), V(10, 2, 0)]
    q = [V(10, 0, 2), V(12, 0, 2), V(12, 2, 2), V(10, 2, 2)]
    g.mesh.add_face(p)
    g.mesh.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        g.mesh.add_face([p[i], p[j], q[j], q[i]])
    scene.groups.append(g)
    path = tmp_path / "with_group.stl"
    stl_format.save_stl(scene, path)
    assert len(_read_stl(path)) == _expected_tri_count(scene)


# ---- OBJ -----------------------------------------------------------------------

def _read_obj(path):
    verts, faces, usemtl = [], [], []
    cur = None
    for line in Path(path).read_text().splitlines():
        if line.startswith("v "):
            verts.append(tuple(float(x) for x in line.split()[1:]))
        elif line.startswith("usemtl "):
            cur = line.split()[1]
        elif line.startswith("f "):
            faces.append((cur, [int(t.split("/")[0]) for t in line.split()[1:]]))
    return verts, faces


def test_obj_vertices_deduped_and_indices_valid(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.obj"
    obj_format.save_obj(scene, path)
    verts, faces = _read_obj(path)
    assert len(verts) == 8                 # a box has 8 corners (deduped)
    assert len(faces) == 12                # 12 triangles
    for _mat, idxs in faces:
        assert all(1 <= i <= len(verts) for i in idxs)


def test_obj_colours_become_materials(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    top = next(f for f in scene.mesh.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    hist.execute(SetFaceColorCommand([top], (0.9, 0.1, 0.1)))
    path = tmp_path / "painted.obj"
    obj_format.save_obj(scene, path)

    mtl = (path.with_suffix(".mtl")).read_text()
    assert "Kd 0.9000 0.1000 0.1000" in mtl     # the painted colour
    assert "Kd 0.9600 0.9500 0.9250" in mtl     # the default paper white

    _verts, faces = _read_obj(path)
    used = {mat for mat, _ in faces}
    assert len(used) == 2                        # cream + red


# ---- OBJ import (round-trip) ---------------------------------------------------

def test_obj_round_trip_rebuilds_clean_solid(tmp_path):
    # Export a cube (triangulated) and import it back: the coplanar merge fuses
    # the triangles into 6 quads, the solid is watertight and outward-oriented.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.obj"
    obj_format.save_obj(scene, path)

    loaded = Scene()
    obj_format.load_obj(loaded, path)
    m = loaded.mesh
    assert len(m.faces) == 6 and len(m.vertices) == 8
    assert is_closed(m)
    assert abs(signed_volume(m) - 48.0) < 1e-6      # 4×4×3
    assert orient_outward(m) == []                  # already consistent


def test_obj_import_restores_colour(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    top = next(f for f in scene.mesh.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    hist.execute(SetFaceColorCommand([top], (0.9, 0.1, 0.1)))
    path = tmp_path / "painted.obj"
    obj_format.save_obj(scene, path)

    loaded = Scene()
    obj_format.load_obj(loaded, path)
    painted = [f for f in loaded.mesh.faces if f.attrs.get("color")]
    assert len(painted) == 1
    assert painted[0].attrs["color"] == [0.9, 0.1, 0.1]
    # Unpainted faces stay unpainted (cream Kd is not stored as a colour).
    assert sum(1 for f in loaded.mesh.faces if not f.attrs.get("color")) == 5


def _big_obj(tmp_path, n):
    lines = []
    for i in range(n):
        x = float(i * 2)
        lines += [f"v {x} 0 0", f"v {x + 1} 0 0", f"v {x} 1 0"]
    lines += [f"f {3 * i + 1} {3 * i + 2} {3 * i + 3}" for i in range(n)]
    p = tmp_path / "big.obj"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_big_import_lands_as_reference_group(tmp_path):
    # Library-scale meshes (3D Warehouse buildings) are reference geometry:
    # they skip the O(F²) fusion/orientation passes (minutes-to-hours at 17k
    # triangles — the app read as hung) AND land in their own Group, so the
    # drawing tools' loose-mesh scans (snap, edge splitting, auto-face) never
    # pay for them while the user draws beside the model. Small imports keep
    # the full editable pipeline (covered by the round-trip tests above).
    from formats.dae import _MAX_FUSE_LOOPS

    n = _MAX_FUSE_LOOPS + 50
    p = _big_obj(tmp_path, n)

    import time
    scene = Scene()
    t0 = time.perf_counter()
    obj_format.load_obj(scene, p)
    assert time.perf_counter() - t0 < 10.0        # no O(F²) pass ran
    assert len(scene.mesh.faces) == 0             # loose mesh untouched
    assert len(scene.groups) == 1
    assert len(scene.groups[0].mesh.faces) == n   # unfused, as-is


def test_big_import_undo_removes_the_group(tmp_path):
    from core.history import SnapshotImport
    from formats.dae import _MAX_FUSE_LOOPS

    p = _big_obj(tmp_path, _MAX_FUSE_LOOPS + 10)
    scene = Scene()
    hist = History(scene)
    hist.execute(SnapshotImport(lambda s: obj_format.load_obj(s, p)))
    assert hist.last_error is None
    assert len(scene.groups) == 1
    assert hist.undo() is True
    assert len(scene.groups) == 0                 # the group undoes too
    assert hist.redo() is True
    assert len(scene.groups) == 1
