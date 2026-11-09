# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A GLB carries one material per face. A face painted only on its back goes
out in that paint instead of the default colour (a face turned inside out and
painted on the side you see rendered white); a face whose front shows anything,
its own paint or a container's, keeps the front. Every assertion reads a real
GLB back: the triangles under each material, by colour and by picture."""
from __future__ import annotations

import json
import struct

from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats.gltf import save_glb

RED = (0.8, 0.1, 0.1)
BLUE = (0.1, 0.2, 0.9)
GREEN = (0.1, 0.7, 0.2)
CREAM = (0.96, 0.95, 0.925)


def _quad(mesh, x=0.0, **attrs):
    f = mesh.add_face([QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
                       QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)])
    f.attrs.update(attrs)
    return f


def _read(path):
    raw = path.read_bytes()
    n = struct.unpack_from("<I", raw, 12)[0]
    return json.loads(raw[20:20 + n])


def _triangles_by_look(doc) -> dict:
    """Triangles per material as the file says it looks: its picture's name,
    or its base colour rounded."""
    looks = []
    for m in doc["materials"]:
        pbr = m["pbrMetallicRoughness"]
        tex = pbr.get("baseColorTexture")
        if tex is not None:
            image = doc["textures"][tex["index"]]["source"]
            looks.append(doc["images"][image]["name"])
        else:
            looks.append(tuple(round(c, 3)
                               for c in pbr["baseColorFactor"][:3]))
    out: dict = {}
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            count = doc["accessors"][prim["indices"]]["count"] // 3
            look = looks[prim["material"]]
            out[look] = out.get(look, 0) + count
    return out


def _glb(scene, tmp_path, camera=False):
    path = tmp_path / "m.glb"
    # With a camera it is the render's own export (core.render_blender).
    save_glb(scene, path,
             face_me=(lambda a: QVector3D(0, -1, 0)) if camera else None)
    return _triangles_by_look(_read(path))


def _both(scene, tmp_path) -> dict:
    """The look per material, the same with and without a camera."""
    plain = _glb(scene, tmp_path)
    assert _glb(scene, tmp_path, camera=True) == plain
    return plain


def _at(x):
    m = QMatrix4x4()
    m.translate(QVector3D(x, 0, 0))
    return m


def _png(path):
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(QColor(10, 200, 30))
    img.save(str(path))
    return path


def test_only_the_back_painted_goes_out_in_the_backs_colour(tmp_path):
    scene = Scene()
    _quad(scene.mesh, back={"color": BLUE})
    assert _both(scene, tmp_path) == {BLUE: 2}


def test_only_the_back_textured_goes_out_with_the_picture(tmp_path):
    src = _png(tmp_path / "brick.png")
    scene = Scene()
    _quad(scene.mesh, back={"texture": {"path": str(src), "sw": 1.0,
                                        "sh": 1.0}})
    path = tmp_path / "m.glb"
    save_glb(scene, path)
    doc = _read(path)
    assert _triangles_by_look(doc) == {"brick.png": 2}
    # The picture is wired for real: its triangles carry UVs.
    prim = doc["meshes"][0]["primitives"][0]
    assert "TEXCOORD_0" in prim["attributes"]


def test_the_backs_named_material_keeps_its_name(tmp_path):
    scene = Scene()
    _quad(scene.mesh, back={"color": BLUE, "mat": "Azul"})
    path = tmp_path / "m.glb"
    save_glb(scene, path)
    assert [m["name"] for m in _read(path)["materials"]] == ["Azul"]


def test_front_and_back_painted_the_front_goes_out(tmp_path):
    scene = Scene()
    _quad(scene.mesh, color=RED, back={"color": BLUE})
    assert _both(scene, tmp_path) == {RED: 2}


def test_a_face_with_nothing_on_the_back_is_as_before(tmp_path):
    scene = Scene()
    _quad(scene.mesh)                            # default
    _quad(scene.mesh, 2.0, back=True)            # "the back mirrors the front"
    _quad(scene.mesh, 4.0, back={"opacity": 0.5})  # no paint to speak of
    assert _both(scene, tmp_path) == {CREAM: 6}


def test_inside_groups_nested_and_copied_the_back_still_goes_out(tmp_path):
    def scene():
        s = Scene()
        proto = Mesh()
        _quad(proto, back={"color": BLUE})
        copies = [Group(proto, name=f"Copy {i}") for i in range(2)]
        for i, c in enumerate(copies):
            c.xform = _at(3.0 * i)
        outer = Group(Mesh(), name="Outer")
        outer.adopt(copies)
        s.groups.append(outer)
        return s
    assert _glb(scene(), tmp_path, camera=True) == {BLUE: 4}
    # A file keeps one mesh for both copies: two triangles, two nodes.
    assert _glb(scene(), tmp_path) == {BLUE: 2}


def test_a_painted_groups_paint_wins_over_an_unpainted_fronts_back(tmp_path):
    """The viewport draws the group's paint on that front, so the face does
    show something there (views.viewport._paint_of, effective_attrs), and a
    painted group keeps the look it has always rendered with."""
    s = Scene()
    g = Group(Mesh(), name="G")
    _quad(g.mesh, back={"color": BLUE})
    g.material = {"color": GREEN}
    s.groups.append(g)
    assert _both(s, tmp_path) == {GREEN: 2}


def test_a_nested_piece_takes_the_paint_from_above_over_its_back(tmp_path):
    s = Scene()
    leaf = Group(Mesh(), name="Leaf")
    _quad(leaf.mesh, back={"color": BLUE})
    top = Group(Mesh(), name="Top")
    top.adopt([leaf])
    top.material = {"color": GREEN}
    s.groups.append(top)
    assert _both(s, tmp_path) == {GREEN: 2}


def test_a_faces_own_front_still_beats_the_group_and_the_back(tmp_path):
    s = Scene()
    g = Group(Mesh(), name="G")
    _quad(g.mesh, color=RED, back={"color": BLUE})
    _quad(g.mesh, 2.0, back={"color": BLUE})
    g.material = {"color": GREEN}
    s.groups.append(g)
    assert _both(s, tmp_path) == {RED: 2, GREEN: 2}


def test_exporting_leaves_the_faces_attrs_alone(tmp_path):
    scene = Scene()
    f = _quad(scene.mesh, back={"color": BLUE})
    before = {"back": {"color": BLUE}}
    _both(scene, tmp_path)
    assert f.attrs == before
