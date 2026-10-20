# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Curved surfaces export round: smooth normals across soft edges (#131).

A cylinder, a sphere or any curved sweep is one surface of faces joined by
soft edges. Every exported triangle used to carry its face's flat normal, so
GLB, DAE and OBJ showed every facet in the program that opened them (and
OBJ carried no normals at all). Each corner on a soft edge now carries the
normal of the surface there — the faces reached around that corner across
soft edges only — while a hard edge keeps its crease: a cylinder's cap stays
flat against its sides, and a box exports exactly as before."""
from __future__ import annotations

import json
import math
import os
import re
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from formats import dae as dae_format                             # noqa: E402
from formats import gltf as gltf_format                           # noqa: E402
from formats import obj as obj_format                             # noqa: E402
from formats.meshexport import collect_geometry, corner_normals   # noqa: E402

SIDES = 12            # faces at 15° + 30°·k, corners at 30°·k
RADIUS, HEIGHT = 1.0, 2.0


def V(x, y, z):
    return QVector3D(float(x), float(y), float(z))


def _cylinder(mesh, soft=True):
    """A closed 12-sided cylinder around the Z axis, outward normals; its
    side seams soft (one curved surface) or hard (twelve flat faces)."""
    ring0 = [V(RADIUS * math.cos(2 * math.pi * i / SIDES),
               RADIUS * math.sin(2 * math.pi * i / SIDES), 0)
             for i in range(SIDES)]
    ring1 = [V(p.x(), p.y(), HEIGHT) for p in ring0]
    sides = []
    for i in range(SIDES):
        j = (i + 1) % SIDES
        sides.append(mesh.add_face([ring0[i], ring0[j], ring1[j], ring1[i]]))
    mesh.add_face(list(reversed(ring0)))              # bottom, facing -Z
    mesh.add_face(ring1)                              # top, facing +Z
    if soft:
        for e in mesh.edges:
            if len(e.faces) == 2 and all(f in sides for f in e.faces):
                e.soft = True
    return sides


def _scene(soft=True):
    scene = Scene()
    _cylinder(scene.mesh, soft)
    return scene


def _corners(scene):
    """Every exported corner as ``(position, normal)``."""
    _materials, prims = collect_geometry(scene)
    return [(p, n) for tris in prims.values() for _flat, verts in tris
            for p, _uv, n in verts]


def _close(a, b, tol=1e-4):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _radial(p):
    return (p.x() / RADIUS, p.y() / RADIUS, 0.0)


# ---- The normals themselves -------------------------------------------------

def test_side_corners_take_the_surface_normal():
    """On the soft side, each corner's normal points straight out from the
    axis through that corner — the round cylinder's — not a facet's."""
    side = [(p, n) for p, n in _corners(_scene()) if abs(n.z()) < 0.5]
    assert len(side) == SIDES * 6                     # 2 triangles a side
    for p, n in side:
        assert _close((n.x(), n.y(), n.z()), _radial(p)), (p, n)


def test_caps_keep_their_crease():
    """A hard edge stops the smoothing: the caps stay flat."""
    caps = [(p, n) for p, n in _corners(_scene()) if abs(n.z()) >= 0.5]
    assert caps
    for p, n in caps:
        want = (0, 0, 1) if p.z() > HEIGHT / 2 else (0, 0, -1)
        assert _close((n.x(), n.y(), n.z()), want)


def test_hard_geometry_exports_flat_as_before():
    """No soft edge, no change: every corner carries its face's normal."""
    _materials, prims = collect_geometry(_scene(soft=False))
    for tris in prims.values():
        for flat, verts in tris:
            for _p, _uv, n in verts:
                assert n == flat


def test_a_flipped_neighbour_does_not_cancel_the_normal():
    """Two faces across a soft edge, the second wound the wrong way: the
    corner still gets a sound normal, between the two."""
    mesh = Mesh()
    a = mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    mesh.add_face([V(1, 0, 0), V(1, 1, 0), V(2, 1, 0.5), V(2, 0, 0.5)])
    for e in mesh.edges:
        if len(e.faces) == 2:
            e.soft = True
    n = corner_normals(a)[(1.0, 0.0, 0.0)]
    assert abs(n.length() - 1.0) < 1e-5
    assert n.z() > 0.9                                # still facing up


def test_component_copies_are_smooth_too():
    """Inside a component instance (a transformed copy of its prototype)
    the soft seams still smooth the surface."""
    scene = Scene()
    proto = Mesh()
    _cylinder(proto)
    g = Group(proto, name="Column")
    g.xform = QMatrix4x4()
    g.xform.translate(10, 0, 0)
    scene.groups.append(g)
    side = [(p, n) for p, n in _corners(scene) if abs(n.z()) < 0.5]
    for p, n in side:
        want = ((p.x() - 10) / RADIUS, p.y() / RADIUS, 0.0)
        assert _close((n.x(), n.y(), n.z()), want)


# ---- In the files -----------------------------------------------------------

def _has_radial_x(normals) -> bool:
    """(1, 0, 0) is the round normal at the corner on +X; with flat shading
    the side normals sit at 15° + 30°·k and never point straight along X."""
    return any(_close(n, (1.0, 0.0, 0.0)) for n in normals)


def _glb_normals(path):
    raw = path.read_bytes()
    jlen = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + jlen])
    bin_start = 20 + jlen + 8
    out = []
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            acc = doc["accessors"][prim["attributes"]["NORMAL"]]
            view = doc["bufferViews"][acc["bufferView"]]
            off = bin_start + view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            for i in range(acc["count"]):
                x, y, z = struct.unpack_from("<3f", raw, off + 12 * i)
                out.append((x, -z, y))                # glTF Y-up → Z-up
    return out


@pytest.mark.parametrize("soft", [True, False])
def test_glb_carries_the_smooth_normals(tmp_path, soft):
    path = tmp_path / "c.glb"
    gltf_format.save_glb(_scene(soft), path)
    assert _has_radial_x(_glb_normals(path)) is soft


@pytest.mark.parametrize("soft", [True, False])
def test_dae_carries_the_smooth_normals(tmp_path, soft):
    path = tmp_path / "c.dae"
    dae_format.save_dae(_scene(soft), path)
    xml = path.read_text(encoding="utf-8")
    arr = re.search(r'<float_array id="geom0-nrm-array"[^>]*>([^<]*)<', xml)
    vals = [float(t) for t in arr.group(1).split()]
    normals = [tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)]
    assert _has_radial_x(normals) is soft


@pytest.mark.parametrize("soft", [True, False])
def test_obj_carries_normals(tmp_path, soft):
    path = tmp_path / "c.obj"
    obj_format.save_obj(_scene(soft), path)
    text = path.read_text(encoding="utf-8")
    normals = [tuple(float(t) for t in line.split()[1:])
               for line in text.splitlines() if line.startswith("vn ")]
    assert normals                                    # OBJ had none before
    assert _has_radial_x(normals) is soft
    faces = [line for line in text.splitlines() if line.startswith("f ")]
    assert faces and all("//" in f for f in faces)    # v//vn on every corner


def test_obj_round_trips_through_the_importer(tmp_path):
    """IngeTrazo still reads its own OBJ back with the normals in it."""
    path = tmp_path / "c.obj"
    obj_format.save_obj(_scene(), path)
    again = Scene()
    obj_format.load_obj(again, path)
    assert len(again.mesh.faces) + sum(len(g.mesh.faces)
                                       for g in again.groups) > 0
