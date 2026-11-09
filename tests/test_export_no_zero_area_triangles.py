# SPDX-License-Identifier: GPL-3.0-or-later
"""Exported meshes carry no zero-area triangles (#314, @ales-limon).

A face with collinear corners — a mitred member with points along its long
edges — triangulates into slivers of three collinear points. They draw
nothing, and another modeller refused a whole COLLADA door for 56 of them.
The exporters skip them; the surface is unchanged."""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

from PySide6.QtGui import QVector3D as V

from core.scene import Scene

# A 2 m mitred strip, 0.1 m deep, with points along both long edges.
STRIP = [V(0, 0, 0), V(0.5, 0, 0), V(1, 0, 0), V(1.5, 0, 0), V(2, 0, 0),
         V(1.9, 0.1, 0), V(1.5, 0.1, 0), V(1.0, 0.1, 0), V(0.5, 0.1, 0),
         V(0.1, 0.1, 0)]
AREA = 0.5 * (2.0 + 1.8) * 0.1


def _scene():
    sc = Scene()
    sc.mesh.add_face(STRIP)
    return sc


def _area(a, b, c):
    ab = [b[i] - a[i] for i in range(3)]
    ac = [c[i] - a[i] for i in range(3)]
    cr = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2],
          ab[0] * ac[1] - ab[1] * ac[0])
    return 0.5 * sum(x * x for x in cr) ** 0.5


def test_the_strip_does_triangulate_into_slivers():
    # The premise: without the filter the face does produce some.
    face = _scene().mesh.faces[0]
    tris = [tuple((p.x(), p.y(), p.z()) for p in t) for t in face.triangulate()]
    assert any(_area(*t) < 1e-9 for t in tris)


def test_dae_has_none_and_keeps_the_surface(tmp_path):
    from formats.dae import save_dae
    out = tmp_path / "strip.dae"
    save_dae(_scene(), out)
    ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
    root = ET.parse(out).getroot()
    floats = [float(x) for x in root.find(".//c:float_array", ns).text.split()]
    pos = [tuple(floats[i:i + 3]) for i in range(0, len(floats), 3)]
    total = 0.0
    for tris in root.iter("{%s}triangles" % ns["c"]):
        stride = len(tris.findall("c:input", ns))
        idx = [int(x) for x in tris.find("c:p", ns).text.split()]
        verts = [pos[idx[i]] for i in range(0, len(idx), stride)]
        for i in range(0, len(verts), 3):
            a = _area(*verts[i:i + 3])
            assert a >= 1e-9
            total += a
    assert abs(total - AREA) < 1e-6


def test_stl_has_none(tmp_path):
    from formats.stl import save_stl
    out = tmp_path / "strip.stl"
    save_stl(_scene(), out)
    data = out.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    total = 0.0
    for i in range(n):
        f = struct.unpack_from("<12f", data, 84 + 50 * i)
        a = _area(f[3:6], f[6:9], f[9:12])
        assert a >= 1e-9
        total += a
    assert abs(total - AREA) < 1e-5


def test_obj_has_none(tmp_path):
    from formats.obj import save_obj
    out = tmp_path / "strip.obj"
    save_obj(_scene(), out)
    vs, total = [], 0.0
    for line in out.read_text().splitlines():
        if line.startswith("v "):
            vs.append(tuple(float(x) for x in line.split()[1:4]))
        elif line.startswith("f "):
            ids = [int(t.split("/")[0]) - 1 for t in line.split()[1:]]
            a = _area(vs[ids[0]], vs[ids[1]], vs[ids[2]])
            assert a >= 1e-9
            total += a
    assert abs(total - AREA) < 1e-6
