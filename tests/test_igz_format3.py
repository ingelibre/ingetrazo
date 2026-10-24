# SPDX-License-Identifier: GPL-3.0-or-later
"""Format 3: a large document keeps its big meshes as binary blocks.

Indexed geometry preserves the stored vertex identities and connectivity,
including edges below drawing weld tolerance. Unindexed legacy JSON still
reconstructs shared topology by position."""
from __future__ import annotations

import json
import zipfile

import pytest
import numpy as np
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


@pytest.mark.parametrize("gauge", [0.0003048, 0.000381],
                         ids=["12mil-tape", "15mil-flashing"])
@pytest.mark.parametrize("deferred", [False, True], ids=["eager", "deferred"])
def test_indexed_thin_film_roundtrip_preserves_drawn_volume(
        tmp_path, monkeypatch, gauge, deferred):
    from core import _native, lazy_mesh
    from core.mesh import DeferredMesh

    monkeypatch.setattr(_native, "wanted", lambda: deferred)
    scene = Scene()
    pos = np.array([(20, 12, 3), (21, 12, 3), (21, 12.00005, 3),
                    (20, 12, 3 + gauge), (21, 12, 3 + gauge),
                    (21, 12.00005, 3 + gauge)])
    triangles = np.array([(0, 2, 1), (3, 4, 5), (0, 1, 4), (0, 4, 3),
                          (1, 2, 5), (1, 5, 4), (2, 0, 3), (2, 3, 5)])
    scene.mesh.add_faces_indexed(pos, triangles.reshape(-1),
                                 [3] * 8, [1] * 8)
    expected = np.array([v.position.toTuple() for v in scene.mesh.vertices])
    reopened = _save_and_load(scene, tmp_path / "thin-film.igz")
    mesh = reopened.mesh
    if deferred:
        assert type(mesh) is DeferredMesh
        plan = lazy_mesh.plan_of(mesh)
        assert len(plan.pos) == 6 and len(plan.edges) == 12
        assert all(len(set(r)) == 3 for r in plan.corners.reshape(-1, 3))
        # The native buffer conversion consumes these same authoritative
        # indices; exercise its actual triangle stream when it is available.
        if _native.native is not None and _native.qt_hypot() is not None:
            from views.array_bake import _geometry
            indices = _geometry(mesh, plan)[3]
            native_drawn = plan.pos[indices].copy()
            assert len(native_drawn) == 8
            native_drawn -= expected[0]
            native_volume = np.einsum(
                "ij,ij->i", native_drawn[:, 0],
                np.cross(native_drawn[:, 1], native_drawn[:, 2])).sum() / 6
            assert native_volume == pytest.approx(
                np.prod(np.ptp(expected, axis=0)) / 2, rel=1e-6)
        assert type(mesh) is DeferredMesh, "planning must not build objects"

    assert len(mesh.vertices) == 6 and len(mesh.edges) == 12
    assert all(len(e.faces) == 2 and e.v0 is not e.v1 for e in mesh.edges)
    actual = np.array([v.position.toTuple() for v in mesh.vertices])
    assert sorted(map(tuple, actual)) == sorted(map(tuple, expected))
    assert np.ptp(actual[:, 2]) == pytest.approx(gauge, abs=2e-7)
    drawn = np.array([[p.toTuple() for p in tri] for f in mesh.faces
                      for tri in f.triangulate()])
    assert len(drawn) == 8
    drawn -= expected[0]
    volume = np.einsum("ij,ij->i", drawn[:, 0],
                       np.cross(drawn[:, 1], drawn[:, 2])).sum() / 6
    assert volume == pytest.approx(
        np.prod(np.ptp(expected, axis=0)) / 2, rel=1e-6)


@pytest.mark.parametrize("deferred", [False, True], ids=["eager", "deferred"])
def test_nonfinite_indexed_vertex_drops_only_affected_geometry(
        tmp_path, binary, monkeypatch, deferred):
    from core import _native, lazy_mesh

    monkeypatch.setattr(_native, "wanted", lambda: deferred)
    scene = Scene()
    for x in (0, 10):
        scene.mesh.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x, 1, 0)])
    path = tmp_path / "damaged-point.igz"
    igz.save_scene(scene, path)

    def damage(doc, members):
        meta = doc["scene"]["geom"]
        dtype, shape, offset = meta["arrays"]["pos"]
        blob = bytearray(members[meta["member"]])
        positions = np.ndarray(shape, dtype=dtype, buffer=blob, offset=offset)
        positions[0, 0] = np.nan
        members[meta["member"]] = bytes(blob)

    _tamper(path, damage)
    reopened = Scene()
    igz.load_into(reopened, path)
    if deferred:
        assert np.isfinite(lazy_mesh.plan_of(reopened.mesh).pos).all()
    assert reopened.load_repairs == 3       # one face and its two bad edges
    assert len(reopened.mesh.faces) == 1
    assert all(np.isfinite(v.position.toTuple()).all()
               for v in reopened.mesh.vertices)
    assert min(v.x() for v in reopened.mesh.faces[0].vertices) == 10


@pytest.mark.parametrize("deferred", [False, True], ids=["eager", "deferred"])
def test_small_touching_shells_stay_separate_after_resaving(
        tmp_path, monkeypatch, deferred):
    from core import _native
    from core.mesh import DeferredMesh

    monkeypatch.setattr(_native, "wanted", lambda: deferred)
    scene = Scene()
    pos = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
           (0, 0, 0), (-1, 0, 0), (0, -1, 0), (0, 0, -1)]
    triangles = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    triangles += [(a + 4, c + 4, b + 4) for a, b, c in triangles[:]]
    scene.mesh.add_faces_indexed(
        pos, np.asarray(triangles).reshape(-1), [3] * 8, [1] * 8)
    reopened = _save_and_load(scene, tmp_path / "touching-shells.igz")
    second = tmp_path / "resaved-shells.igz"
    igz.save_scene(reopened, second)
    if deferred:
        assert type(reopened.mesh) is DeferredMesh
    back = Scene()
    igz.load_into(back, second)
    mesh = back.mesh
    assert len(mesh.vertices) == 8 and len(mesh.edges) == 12
    origins = [v for v in mesh.vertices if v.position == V(0, 0, 0)]
    assert len(origins) == 2
    assert all(len(v.edges) == 3 for v in mesh.vertices)
    assert origins[0].faces().isdisjoint(origins[1].faces())
