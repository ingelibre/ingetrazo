# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The engine's reader of a JSON document's mesh blocks (#158): the arrays it
gives are those _json_arrays makes of the parsed tree, the rest of the tree
is json.loads's, and anything out of the ordinary goes to the plain parser."""
import copy
import json
import zipfile

import numpy as np
import pytest

from core import _native
from core.mesh import DeferredMesh, Mesh, face_count
from core.scene import Scene
from formats import igz

mod = _native.available()
pytestmark = pytest.mark.skipif(
    not (mod and hasattr(mod, "json_mesh_blocks")),
    reason="no engine with json_mesh_blocks")


def square(x=0.0, z=0.0, side=1.0):
    return [[x, 0.0, z], [x + side, 0.0, z], [x + side, side, z], [x, side, z]]


def big_block(n=400, **face_attrs):
    """A block past _BULK_MIN, its faces and edges of every spelling."""
    faces = [dict(vertices=square(float(i)), **face_attrs) for i in range(n)]
    edges = [dict(a=[float(i), 0.0, 0.0], b=[float(i), 1.0, 0.0])
             for i in range(n)]
    return dict(edges=edges, faces=faces)


def document():
    b = big_block()
    b["edges"][3].update(soft=True)
    b["edges"][4].update(hidden=True, soft=False)
    b["edges"][5].update(curve=7, layer="Capa ñ \"x\"")
    b["edges"][6].update(curve=None, layer=None)
    b["edges"][7].update(layer="")           # kept by the bulk reader
    b["faces"][1].update(color=[1.0, 0.5, 0.25], mat="m1")
    b["faces"][2].update(mat="m1", color=[1.0, 0.5, 0.25])  # the same, reordered
    b["faces"][3].update(back=True, layer="L", opacity=0.5)
    b["faces"][4].update(hidden=False)       # says nothing: no table entry
    b["faces"][5].update(ifc={"edges": [1, 2], "faces": {"vertices": 3}})
    # One hole, and two: one of them nested in the other, in an order of keys
    # that puts the holes first.
    b["faces"][6]["holes"] = [square(6.25, 0.0, 0.5)]
    b["faces"][7] = {
        "holes": [square(7.1, 0.0, 0.8), square(7.3, 0.0, 0.1)],
        "color": [0.1, 0.2, 0.3],
        "vertices": square(7.0, 0.0, 1.0)}
    b["faces"][8]["holes"] = [square(8.1, 0.0, 0.2), square(8.6, 0.0, 0.2)]
    b["faces"][9]["holes"] = []
    small = {"edges": [{"a": [0, 0, 0], "b": [1, 2, 3], "layer": ""},
                       {"a": [1e0, 2.5e-1, -0.0], "b": [1, -0, 3], "layer": "A"}],
             "faces": [{"vertices": square(0.5), "texture": {"embed": "x.png"}}]}
    return {
        "igz_format": 2,
        "scene": {
            "edges": [], "faces": [],
            "name_with_faces": {"faces": [{"vertices": "not a mesh"}]},
            "plugin_data": {"p": {"edges": [{"a": 1}], "faces": 5}},
            "protos": [b, small, {"edges": [], "faces": []}],
            "groups": [
                dict(copy.deepcopy(small), name="uno", children=[
                    dict(copy.deepcopy(small), name="hijo", children=[
                        dict(big_block(300), name="nieto")]),
                    {"proto": 0, "xform": [1.0] * 16, "name": "copia"},
                ]),
                {"name": "vacío", "edges": [], "faces": []},
            ],
            "kept_components": [dict(small, name="guardado")],
            "ext_edges": {"edges": [{"odd": True}]},
        },
    }


def blocks_of(tree):
    """Every mesh block of a parsed tree, walked as jsondoc.rs walks it."""
    scene = tree["scene"]
    out = [scene] + list(scene["protos"])

    def walk(raw):
        out.append(raw)
        for c in raw.get("children", []):
            walk(c)
    for raw in scene["groups"] + scene["kept_components"]:
        walk(raw)
    return out


def assert_same_arrays(a, b):
    assert (a is None) == (b is None)
    if a is None:
        return
    assert set(a) == set(b)
    assert a["meta"] == b["meta"]
    assert a["sequential"] == b["sequential"]
    for key in ("pos", "edges", "flags", "curves", "layers", "rings", "sizes",
                "counts", "face_attr"):
        x, y = a[key], b[key]
        assert (x is None) == (y is None), key
        if x is not None:
            assert x.dtype == y.dtype and x.shape == y.shape, key
            assert x.tobytes() == y.tobytes(), key


@pytest.fixture
def any_size(monkeypatch):
    monkeypatch.setattr(igz, "_NATIVE_JSON_MIN", 0)
    monkeypatch.setenv("INGETRAZO_RUST", "1")
    monkeypatch.setattr(_native, "native", mod, raising=False)


@pytest.mark.parametrize("indent", [None, 2])
def test_the_arrays_are_those_of_the_parsed_tree(any_size, indent):
    raw = json.dumps(document(), indent=indent).encode()
    plain = json.loads(raw)
    tree = igz._parse_native(raw)
    assert tree is not None
    got = blocks_of(tree)
    want = blocks_of(plain)
    assert len(got) == len(want)
    taken = 0
    for g, w in zip(got, want):
        src = g.get("_arrays")
        if src is not None:
            taken += 1
            igz._merge_native_attrs(src)
        assert_same_arrays(src, igz._json_arrays(w))
    assert taken == 6


def test_the_rest_of_the_tree_is_json_loads(any_size):
    doc = document()
    tree = igz._parse_native(json.dumps(doc).encode())

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "_arrays"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    def empty_blocks(t):
        for b in blocks_of(t):
            if "edges" in b:
                b["edges"] = []
                b["faces"] = []
        return t
    assert strip(tree) == empty_blocks(json.loads(json.dumps(doc)))
    # Not a mesh block: left as written, whatever its keys are called.
    assert tree["scene"]["plugin_data"] == doc["scene"]["plugin_data"]
    assert tree["scene"]["ext_edges"] == doc["scene"]["ext_edges"]


@pytest.mark.parametrize("change", [
    lambda b: b["edges"][0].update(curve="named"),
    lambda b: b["edges"][0].update(curve=-1),
    lambda b: b["edges"][0].update(curve=1.0),
    lambda b: b["edges"][0].update(soft=1),
    lambda b: b["edges"][0].update(extra=1),
    lambda b: b["edges"][0].update(layer=3),
    lambda b: b["edges"][0].pop("a"),
    lambda b: b["edges"][0].update(a=[1.0, 2.0]),
    lambda b: b["edges"][0].update(a=[1.0, 2.0, 3.0, 4.0]),
    lambda b: b["edges"][0].update(a=[1.0, 2.0, "3"]),
    lambda b: b["edges"][0].update(a=[1.0, 2.0, 12345678901234567890]),
    lambda b: b["edges"].append(5),
    lambda b: b["faces"][0].pop("vertices"),
    lambda b: b["faces"][0].update(vertices=[]),
    lambda b: b["faces"][0].update(holes=None),
    lambda b: b["faces"][0].update(holes=[[]]),
    lambda b: b["faces"].append([]),
    lambda b: b.update(edges=None),
    lambda b: b.update(faces={}),
    lambda b: b.update(_njb=1),
], ids=range(20))
def test_anything_unusual_goes_to_the_plain_parser(any_size, change):
    doc = document()
    change(doc["scene"]["protos"][0])
    assert igz._parse_native(json.dumps(doc).encode()) is None


@pytest.mark.parametrize("text", [
    b"", b"[]", b"{", b'{"scene": {"edges": [', b'{"a": 1} x', b'{"a": }',
    b'{"scene": {"edges": [{"a": [01, 0, 0], "b": [0, 0, 0]}]}}',
    b'{"scene": {"edges": [{"a": [1., 0, 0], "b": [0, 0, 0]}]}}',
    b'{"scene": {"edges": [{"a": [1e999, 0, 0], "b": [0, 0, 0]}]}}',
    b'{"scene": {"edges": [{"a": [NaN, 0, 0], "b": [0, 0, 0]}]}}',
    b'{"scene": {"faces": [{"vertices": [[0, 0, 0]]}], "faces": []}}',
    b'{"scene": {"\\u0065dges": []}}',
])
def test_a_malformed_text_is_not_taken(any_size, text):
    assert igz._parse_native(text) is None


def test_a_nan_outside_the_meshes_leaves_it_to_the_plain_parser(any_size):
    igz._saw_nonfinite[0] = False
    assert igz._parse_native(
        b'{"scene": {"opacity": NaN, "faces": [{"vertices": [[0, 0, 0]]}]}}'
    ) is None
    igz._saw_nonfinite[0] = False


def test_a_small_document_keeps_the_plain_parser(monkeypatch):
    monkeypatch.setenv("INGETRAZO_RUST", "1")
    monkeypatch.setattr(_native, "native", mod, raising=False)
    assert len(json.dumps(document())) < igz._NATIVE_JSON_MIN
    assert igz._parse_native(json.dumps(document()).encode()) is None


def write(tmp_path, doc, name="d.igz"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("document.json", json.dumps(doc))
        z.writestr("textures/x.png", b"not really a png")
    return p


def shape(scene):
    def one(mesh):
        return (len(mesh.vertices), len(mesh.edges), [
            (tuple((v.x(), v.y(), v.z()) for v in f.vertices),
             tuple(tuple((v.x(), v.y(), v.z()) for v in h) for h in f.holes),
             json.dumps(f.attrs, sort_keys=True, default=str))
            for f in mesh.faces],
            [(e.soft, e.hidden, e.curve is not None, e.layer)
             for e in mesh.edges])

    def group(g):
        return (g.name, one(g.mesh), [group(c) for c in g.children])
    return (one(scene.mesh), [group(g) for g in scene.groups],
            [group(g) for g in scene.kept_components])


def test_a_document_opens_the_same_through_either_reader(
        any_size, tmp_path, monkeypatch):
    p = write(tmp_path, document())
    a = Scene()
    calls = []
    real = igz._parse_native
    monkeypatch.setattr(igz, "_parse_native",
                        lambda raw: calls.append(1) or real(raw))
    igz.load_into(a, p)
    assert calls
    assert a.groups[0].children[0].children[0].mesh.__class__ is DeferredMesh
    assert face_count(a.groups[0].children[0].children[0].mesh) == 300
    monkeypatch.setattr(igz, "_parse_native", lambda raw: None)
    b = Scene()
    igz.load_into(b, p)
    assert shape(a) == shape(b)


def test_equal_attributes_are_one_entry_once_textures_are_unpacked(
        any_size, tmp_path, monkeypatch):
    """Two spellings of an image land on one cached file: the table the mesh
    keeps is the one the plain reader makes, not the document's text."""
    doc = document()
    block = big_block(300)
    block["faces"][0]["texture"] = {"embed": "textures/x.png"}
    block["faces"][1]["texture"] = {"embed": "textures/y-x.png"}
    block["faces"][2]["hidden"] = False
    doc["scene"]["groups"] = [dict(block, name="g")]
    p = tmp_path / "t.igz"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("document.json", json.dumps(doc))
        z.writestr("textures/x.png", b"a")
        z.writestr("textures/y-x.png", b"a")
    monkeypatch.setattr("core.texture.cache_image",
                        lambda data, name, kind: tmp_path / "cached.png")
    a = Scene()
    igz.load_into(a, p)
    monkeypatch.setattr(igz, "_parse_native", lambda raw: None)
    b = Scene()
    igz.load_into(b, p)
    sa = a.groups[0].mesh.__dict__["_deferred_source"]
    sb = b.groups[0].mesh.__dict__["_deferred_source"]
    assert_same_arrays(sa, sb)
    assert len(sa["meta"]["face_attrs"]) == 1


def test_with_the_engine_off_the_plain_parser_reads(monkeypatch):
    monkeypatch.setattr(igz, "_NATIVE_JSON_MIN", 0)
    monkeypatch.setattr(_native, "native", None, raising=False)
    assert igz._parse_native(json.dumps(document()).encode()) is None


def test_a_texture_in_a_block_read_by_the_engine_is_unpacked(
        any_size, tmp_path, monkeypatch):
    doc = document()
    doc["scene"]["groups"] = [dict(big_block(
        300, texture={"embed": "textures/x.png"}), name="g")]
    p = write(tmp_path, doc)
    monkeypatch.setattr("core.texture.cache_image",
                        lambda data, name, kind: tmp_path / "cached.png")
    s = Scene()
    igz.load_into(s, p)
    mesh = s.groups[0].mesh
    table = mesh.__dict__["_deferred_source"]["meta"]["face_attrs"]
    assert table[0]["texture"].get("path") == str(tmp_path / "cached.png")
    assert "embed" not in table[0]["texture"]
    assert mesh.faces[0].attrs["texture"]["path"] == str(tmp_path / "cached.png")


def test_the_engine_lets_the_window_answer(any_size, tmp_path):
    p = write(tmp_path, document())
    pumped = []
    tree, archive = igz._read_document(p, pump=lambda: pumped.append(1))
    archive.close()
    assert "_arrays" in tree["scene"]["protos"][0]


def test_a_plain_file_too(any_size, tmp_path):
    p = tmp_path / "plain.igz"
    p.write_text(json.dumps(document()))
    tree, archive = igz._read_document(p)
    assert archive is None
    assert "_arrays" in tree["scene"]["protos"][0]
    assert isinstance(tree["scene"]["protos"][0]["_arrays"]["pos"], np.ndarray)


def test_a_block_that_is_not_empty_when_read_builds_at_once(any_size):
    """defer() refuses a mesh that already holds something: the arrays still
    make the mesh the plain reader would."""
    tree = igz._parse_native(json.dumps(document()).encode())
    block = tree["scene"]["protos"][1]
    m = Mesh()
    m.vertex(__import__("PySide6.QtGui", fromlist=["QVector3D"]).QVector3D(9, 9, 9))
    igz._load_mesh(m, block)
    assert type(m) is Mesh
    assert len(m.faces) == 1


def test_a_long_member_is_read_whole_and_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(igz, "_NATIVE_JSON_MIN", 10)
    payload = bytes(range(256)) * 200_000      # past one piece of the reader
    p = tmp_path / "m.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("m", payload)
    with zipfile.ZipFile(p) as z:
        assert bytes(igz._read_member_flat(z, "m")) == payload
    # A damaged member fails as it does read in one go.
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("m", payload)
    data = bytearray(bad.read_bytes())
    data[len(payload) // 2] ^= 0xFF
    bad.write_bytes(data)
    with zipfile.ZipFile(bad) as z:
        with pytest.raises(zipfile.BadZipFile):
            igz._read_member_flat(z, "m")
