# SPDX-License-Identifier: GPL-3.0-or-later
"""Format 3: a large document keeps its big meshes as binary blocks.

The promise is that nothing changes but the speed: a model written in
binary reopens exactly as the same model written as JSON — same vertices,
edges, faces, holes, flags, attributes, in the same order."""
from __future__ import annotations

import json
import zipfile

import pytest
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


@pytest.fixture
def binary(monkeypatch):
    """Every document counts as large and every mesh goes binary."""
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)


def _scene(tmp_path) -> Scene:
    scene = Scene()
    m = scene.mesh
    png = tmp_path / "wood.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x8B5A2B)
    img.save(str(png))
    # A slab with two holes, one nested in the other (the nested one is
    # dropped on load, both ways).
    slab = m.add_face(
        [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)],
        [[V(2, 2, 0), V(8, 2, 0), V(8, 8, 0), V(2, 8, 0)],
         [V(3, 3, 0), V(4, 3, 0), V(4, 4, 0), V(3, 4, 0)]])
    slab.attrs.update({"color": [0.5, 0.4, 0.3], "layer": "Pisos",
                       "texture": {"path": str(png), "sw": 1.0, "sh": 1.0},
                       "mat": "Madera", "back": True})
    wall = m.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 0, 3), V(0, 0, 3)])
    wall.attrs.update({"opacity": 0.5, "ifc": {"class": "IfcWall"}})
    m.add_face([V(0, 10, 0), V(10, 10, 0), V(10, 10, 3)])    # no attrs
    e = m.add_edge(V(20, 0, 0), V(21, 0, 0))
    e.soft, e.curve, e.layer = True, 7, "Guias"
    m.add_edge(V(21, 0, 0), V(22, 1, 0)).hidden = True
    m.add_edge(V(22, 1, 0), V(23, 1, 0))
    # A component placed twice and a classic group.
    proto = Mesh()
    proto.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    for dx in (0, 5):
        g = Group(proto, name=f"Silla {dx}")
        x = QMatrix4x4()
        x.translate(dx, 20, 0)
        g.xform = x
        scene.groups.append(g)
    classic = Group(name="Mesa")
    classic.mesh.add_face([V(0, 30, 0), V(2, 30, 0), V(2, 31, 0)])
    scene.groups.append(classic)
    return scene


def _canonical(scene) -> str:
    """The scene as JSON mesh blocks — order included."""
    def mesh(m):
        block = igz._mesh_json(m)
        block["vertices"] = [v.position.toTuple() for v in m.vertices]
        return block
    out = {"loose": mesh(scene.mesh),
           "groups": [(g.name, g.xform.data() if g.xform is not None
                       else None, mesh(g.mesh)) for g in scene.groups]}
    for f in out["loose"]["faces"]:
        tex = f.get("texture")
        if tex:
            tex.pop("path", None)        # cached copy: a different file name
    return json.dumps(out, sort_keys=True, default=list)


def _save_and_load(scene, path) -> Scene:
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    return back


def test_binary_and_json_reopen_identical(tmp_path, monkeypatch):
    json_back = _save_and_load(_scene(tmp_path), tmp_path / "json.igz")
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    bin_path = tmp_path / "bin.igz"
    bin_back = _save_and_load(_scene(tmp_path), bin_path)
    with zipfile.ZipFile(bin_path) as zf:
        doc = json.loads(zf.read("document.json"))
        assert doc["igz_format"] == igz.GEOMETRY_FORMAT
        assert any(n.startswith("geom/") for n in zf.namelist())
    assert "faces" not in doc["scene"]           # the loose mesh went binary
    assert _canonical(bin_back) == _canonical(json_back)
    # The component is still ONE mesh placed twice.
    assert bin_back.groups[0].mesh is bin_back.groups[1].mesh


def test_the_texture_travels_with_a_binary_mesh(tmp_path, binary):
    back = _save_and_load(_scene(tmp_path), tmp_path / "t.igz")
    slab = next(f for f in back.mesh.faces if f.attrs.get("mat") == "Madera")
    assert slab.attrs["texture"]["path"].endswith("wood.png")
    assert len(slab.hole_loops) == 1             # the nested hole was dropped


def test_faces_sharing_attributes_do_not_share_the_dicts(tmp_path, binary):
    scene = Scene()
    for i in range(3):
        f = scene.mesh.add_face([V(i, 0, 0), V(i + 1, 0, 0), V(i, 1, 0)])
        f.attrs["texture"] = {"path": "/x.png", "sw": 1.0, "sh": 1.0}
    back = _save_and_load(scene, tmp_path / "s.igz")
    texs = [f.attrs["texture"] for f in back.mesh.faces]
    texs[0]["sw"] = 9.0                           # editing one face…
    assert texs[1]["sw"] == 1.0                   # …leaves the others alone


def test_two_saves_are_byte_identical(tmp_path, binary):
    scene = _scene(tmp_path)
    igz.save_scene(scene, tmp_path / "a.igz")
    igz.save_scene(scene, tmp_path / "b.igz")
    assert (tmp_path / "a.igz").read_bytes() == (tmp_path / "b.igz").read_bytes()


def test_a_small_document_is_not_binary(tmp_path):
    out = tmp_path / "small.igz"
    igz.save_scene(_scene(tmp_path), out)
    with zipfile.ZipFile(out) as zf:
        assert not any(n.startswith("geom/") for n in zf.namelist())
        assert json.loads(zf.read("document.json"))["igz_format"] == 2


def test_a_newer_format_is_refused_with_a_message(tmp_path):
    out = tmp_path / "future.igz"
    out.write_text(json.dumps({"igz_format": igz.CURRENT_FORMAT + 1,
                               "scene": {}}))
    with pytest.raises(ValueError, match="newer than this build"):
        igz.load_into(Scene(), out)


def _tamper(path, mutate):
    with zipfile.ZipFile(path) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    doc = json.loads(members["document.json"])
    mutate(doc, members)
    members["document.json"] = json.dumps(doc).encode()
    with zipfile.ZipFile(path, "w") as zf:
        for n, data in members.items():
            zf.writestr(n, data)


@pytest.mark.parametrize("mutate", [
    # an index past the last point
    lambda doc, m: m.__setitem__(
        doc["scene"]["geom"]["member"],
        m[doc["scene"]["geom"]["member"]][:-8]),
    # a dtype the reader must not build
    lambda doc, m: doc["scene"]["geom"]["arrays"]["pos"].__setitem__(0, "|O"),
    # an array said to be bigger than the blob
    lambda doc, m: doc["scene"]["geom"]["arrays"]["pos"].__setitem__(
        1, [10 ** 9, 3]),
    # the block itself missing
    lambda doc, m: m.pop(doc["scene"]["geom"]["member"]),
])
def test_a_damaged_block_fails_cleanly(tmp_path, binary, mutate):
    out = tmp_path / "d.igz"
    igz.save_scene(_scene(tmp_path), out)
    _tamper(out, mutate)
    with pytest.raises(ValueError):
        igz.load_into(Scene(), out)


def test_a_nan_point_is_refused_on_save(tmp_path, binary):
    scene = Scene()
    f = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])
    f.loop[0].position = V(float("nan"), 0, 0)
    out = tmp_path / "nan.igz"
    with pytest.raises(igz.NonFiniteDocumentError):
        igz.save_scene(scene, out)
    assert not out.exists()


def test_a_mesh_goes_binary_only_where_json_would_load_in_bulk():
    """The JSON reader rebuilds small meshes entity by entity and big ones
    in bulk, and the two number vertices differently: a mesh the JSON
    reader takes one by one must stay JSON, or it reopens in another
    order (23 meshes of the #158 model did)."""
    m = Mesh()
    for i in range(600):                 # 600 edges: 1200 ends, < 1024 rule
        m.add_edge(V(i, 0, 0), V(i, 1, 0))
    assert not igz._bulk_sized(len(m.edges), len(m.faces))
    assert "edges" in igz._mesh_json(m, {})
    for i in range(500):
        m.add_edge(V(i, 2, 0), V(i, 3, 0))
    assert "geom" in igz._mesh_json(m, {})
