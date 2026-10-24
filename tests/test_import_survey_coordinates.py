# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Files in survey coordinates import near the origin, precise (#798).

The engine keeps positions in single precision: at a UTM northing of
8,500,000 m it only tells whole metres apart, so a 0.5 m box read in there
comes out 0 m or 1 m deep. The DXF importer already moved such drawings
near the origin; OBJ, STL, glTF/GLB and COLLADA now do the same, measuring
the file in double precision and subtracting one whole-metre offset before
the first vertex turns single precision (formats/recenter.py)."""
from __future__ import annotations

import os
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
from formats import glb as glb_format                             # noqa: E402
from formats import gltf as gltf_format                           # noqa: E402
from formats import obj as obj_format                             # noqa: E402
from formats import stl as stl_format                             # noqa: E402
from formats.recenter import RECENTER_BEYOND_M, survey_offset     # noqa: E402

E, N = 500000.3, 8500000.5          # a UTM easting / northing, off-metre
SIDE = 0.5
BOX = [(x, y, z) for z in (0, SIDE) for y in (0, SIDE) for x in (0, SIDE)]
QUADS = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
         (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)]


def _points(scene):
    pts = [v.position for v in scene.mesh.vertices]
    for g in scene.groups:
        from core.group import world_mesh
        pts += [v.position for v in world_mesh(g).vertices]
    return pts


def _extent(scene, axis):
    vals = [p.toTuple()[axis] for p in _points(scene)]
    return max(vals) - min(vals)


def _assert_precise_near_origin(scene, offset):
    assert offset is not None
    assert all(c == int(c) for c in offset)            # whole metres
    for axis in range(3):
        assert _extent(scene, axis) == pytest.approx(SIDE, abs=1e-4)
    assert max(abs(c) for p in _points(scene) for c in p.toTuple()) < 10.0


# ---- The rule ---------------------------------------------------------------

def test_survey_offset_rule():
    assert survey_offset((0, 0, 0), (50, 40, 10)) is None
    assert survey_offset((-RECENTER_BEYOND_M, 0, 0), (0, 1, 1)) is None
    assert survey_offset((E, N, 3800.7), (E + 9, N + 9, 3810)) == \
        (500000.0, 8500000.0, 3800.0)


# ---- OBJ ----------------------------------------------------------------------

def _obj(path, dx, dy):
    lines = [f"v {x + dx!r} {y + dy!r} {z!r}" for x, y, z in BOX]
    lines += ["f " + " ".join(str(i + 1) for i in q) for q in QUADS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_obj_in_survey_coordinates_arrives_precise(tmp_path):
    scene = Scene()
    offset = obj_format.load_obj(scene, _obj(tmp_path / "far.obj", E, N))
    _assert_precise_near_origin(scene, offset)
    assert offset[:2] == (500000.0, 8500000.0)


def test_obj_near_the_origin_is_read_as_it_is(tmp_path):
    scene = Scene()
    assert obj_format.load_obj(scene, _obj(tmp_path / "near.obj", 3, 4)) \
        is None
    xs = sorted({round(p.x(), 4) for p in _points(scene)})
    assert xs == [3.0, 3.5]


# ---- STL ----------------------------------------------------------------------

def _triangles(dx, dy):
    tris = []
    for q in QUADS:
        a, b, c, d = (BOX[i] for i in q)
        tris += [(a, b, c), (a, c, d)]
    return [tuple((x + dx, y + dy, z) for x, y, z in t) for t in tris]


def test_ascii_stl_in_survey_coordinates_arrives_precise(tmp_path):
    path = tmp_path / "far.stl"
    out = ["solid box"]
    for t in _triangles(E, N):
        out += ["facet normal 0 0 0", "outer loop"]
        out += [f"vertex {x!r} {y!r} {z!r}" for x, y, z in t]
        out += ["endloop", "endfacet"]
    path.write_text("\n".join(out + ["endsolid box"]) + "\n")
    scene = Scene()
    offset = stl_format.load_stl(scene, path)
    _assert_precise_near_origin(scene, offset)


def test_binary_stl_moves_near_the_origin_without_more_loss(tmp_path):
    """A binary STL is single precision already: nothing to win back, but
    it lands near the origin and keeps exactly the file's own values."""
    dx, dy = 500000.25, 8500000.0                    # float32-exact
    path = tmp_path / "far.stl"
    tris = _triangles(dx, dy)
    data = bytearray(80) + struct.pack("<I", len(tris))
    for t in tris:
        data += struct.pack("<12fH", 0, 0, 0, *[c for p in t for c in p], 0)
    path.write_bytes(bytes(data))
    scene = Scene()
    offset = stl_format.load_stl(scene, path)
    assert offset == (500000.0, 8500000.0, 0.0)
    xs = sorted({round(p.x(), 4) for p in _points(scene)})
    assert xs == [0.25, 0.75]


# ---- glTF / GLB ---------------------------------------------------------------

def test_glb_placed_in_survey_coordinates_arrives_precise(tmp_path):
    """glTF keeps vertices single precision but node placements double: a
    georeferenced file carries its position there, and it survives."""
    src = Scene()
    proto = Mesh()
    for q in QUADS:
        proto.add_face([QVector3D(*BOX[i]) + QVector3D(0.3, 0.5, 0)
                        for i in q])
    g = Group(proto, name="Box")
    g.xform = QMatrix4x4()
    g.xform.translate(500000.0, 8500000.0, 0.0)
    src.groups.append(g)
    path = tmp_path / "far.glb"
    gltf_format.save_glb(src, path)
    scene = Scene()
    offset = glb_format.load_glb(scene, path)
    _assert_precise_near_origin(scene, offset)


# ---- COLLADA -------------------------------------------------------------------

def _dae(path, verts, nodes, library=""):
    pos = " ".join(repr(float(c)) for v in verts for c in v)
    p = " ".join(str(i) for q in QUADS for i in q)
    path.write_text(f'''<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit meter="1"/><up_axis>Z_UP</up_axis></asset>
<library_geometries><geometry id="g"><mesh>
<source id="g-pos"><float_array id="g-pos-a" count="{len(verts) * 3}">{pos}</float_array>
<technique_common><accessor source="#g-pos-a" count="{len(verts)}" stride="3"/>
</technique_common></source>
<vertices id="g-v"><input semantic="POSITION" source="#g-pos"/></vertices>
<polylist count="6"><input semantic="VERTEX" source="#g-v" offset="0"/>
<vcount>4 4 4 4 4 4</vcount><p>{p}</p></polylist>
</mesh></geometry></library_geometries>{library}
<library_visual_scenes><visual_scene id="s">{nodes}</visual_scene>
</library_visual_scenes><scene><instance_visual_scene url="#s"/></scene>
</COLLADA>''', encoding="utf-8")
    return path


def test_dae_with_far_vertices_arrives_precise(tmp_path):
    path = _dae(tmp_path / "v.dae", [(x + E, y + N, z) for x, y, z in BOX],
                '<node id="n"><instance_geometry url="#g"/></node>')
    scene = Scene()
    _assert_precise_near_origin(scene, dae_format.load_dae(scene, path))


def test_dae_placed_far_by_its_node_arrives_precise(tmp_path):
    path = _dae(tmp_path / "n.dae", BOX,
                f'<node id="n"><translate>{E!r} {N!r} 0</translate>'
                '<instance_geometry url="#g"/></node>')
    scene = Scene()
    _assert_precise_near_origin(scene, dae_format.load_dae(scene, path))


def test_dae_far_out_and_rotated_by_its_node(tmp_path):
    """A placement that also turns the model: the offset still comes off
    the node's translation, in the right frame."""
    path = _dae(tmp_path / "r.dae", BOX,
                f'<node id="n"><translate>{E!r} {N!r} 0</translate>'
                '<rotate>0 0 1 90</rotate><instance_geometry url="#g"/>'
                '</node>')
    scene = Scene()
    _assert_precise_near_origin(scene, dae_format.load_dae(scene, path))


def test_dae_one_far_geometry_placed_twice(tmp_path):
    """Two nodes place the same far-out geometry, one 3 m further east:
    both copies arrive precise, 3 m apart — the geometry is shifted once."""
    path = _dae(tmp_path / "t.dae", [(x + E, y + N, z) for x, y, z in BOX],
                '<node id="a"><instance_geometry url="#g"/></node>'
                '<node id="b"><translate>3 0 0</translate>'
                '<instance_geometry url="#g"/></node>')
    scene = Scene()
    offset = dae_format.load_dae(scene, path)
    assert offset is not None
    xs = sorted({round(p.x(), 4) for p in _points(scene)})
    assert xs == [0.3, 0.8, 3.3, 3.8]


def test_dae_component_placed_far_twice(tmp_path):
    """A library node (component) placed by two far-out nodes."""
    library = ('<library_nodes><node id="comp">'
               '<instance_geometry url="#g"/></node></library_nodes>')
    path = _dae(tmp_path / "c.dae", BOX,
                f'<node id="a"><translate>{E!r} {N!r} 0</translate>'
                '<instance_node url="#comp"/></node>'
                f'<node id="b"><translate>{E + 3!r} {N!r} 0</translate>'
                '<instance_node url="#comp"/></node>', library)
    scene = Scene()
    assert dae_format.load_dae(scene, path) is not None
    xs = sorted({round(p.x(), 4) for p in _points(scene)})
    assert xs == [0.3, 0.8, 3.3, 3.8]


def test_dae_near_the_origin_is_read_as_it_is(tmp_path):
    path = _dae(tmp_path / "near.dae", BOX,
                '<node id="n"><translate>3 4 0</translate>'
                '<instance_geometry url="#g"/></node>')
    scene = Scene()
    assert dae_format.load_dae(scene, path) is None
    xs = sorted({round(p.x(), 4) for p in _points(scene)})
    assert xs == [3.0, 3.5]
