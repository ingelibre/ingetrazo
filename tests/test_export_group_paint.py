# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exports carry the materials the viewport shows (GLB, DAE, OBJ).

Two faults, both silent in the file:

* two registry materials that happen to share a colour (two whites under
  two names) were grouped by colour alone, so the second came out as the
  first — and the program opening the file could no longer tell them apart;
* the paint of a group or component instance never left the document: the
  faces inside wearing the default material exported cream, as an anonymous
  ``matN``, although the viewport draws them in the container's paint.

The rule is the viewport's (``core.materials.effective_attrs``): a face's
own paint wins; otherwise its piece's; otherwise the top-level object's."""
from __future__ import annotations

import json
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
from core.materials import Material                               # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from formats import dae as dae_format                             # noqa: E402
from formats import gltf as gltf_format                           # noqa: E402
from formats import obj as obj_format                             # noqa: E402
from formats.meshexport import collect_geometry, material_key     # noqa: E402

WHITE = (0.95, 0.95, 0.95)
PINK = (0.9, 0.3, 0.6)
BLUE = (0.1, 0.2, 0.9)
GREEN = (0.1, 0.7, 0.2)
CREAM = (0.96, 0.95, 0.925)


def _quad(mesh, x, y=0.0, attrs=None):
    f = mesh.add_face([QVector3D(x, y, 0), QVector3D(x + 1, y, 0),
                       QVector3D(x + 1, y + 1, 0), QVector3D(x, y + 1, 0)])
    if attrs:
        f.attrs.update(attrs)
    return f


def _at(x, y=0.0):
    m = QMatrix4x4()
    m.translate(QVector3D(x, y, 0))
    return m


def _paint(name, color):
    return Material(name, color=color).face_attrs()


def _glb(scene, tmp_path):
    path = tmp_path / "m.glb"
    gltf_format.save_glb(scene, path)
    raw = path.read_bytes()
    n = struct.unpack_from("<I", raw, 12)[0]
    return json.loads(raw[20:20 + n])


def _glb_node_materials(doc) -> dict:
    """Node name → set of material names its mesh draws with."""
    names = [m["name"] for m in doc["materials"]]
    out: dict = {}
    for node in doc.get("nodes", []):
        if "mesh" not in node:
            continue
        prims = doc["meshes"][node["mesh"]]["primitives"]
        out.setdefault(node.get("name"), set()).update(
            names[p["material"]] for p in prims)
    return out


def _exported_names(scene, tmp_path) -> dict:
    """Material names per format."""
    obj_path, dae_path = tmp_path / "m.obj", tmp_path / "m.dae"
    obj_format.save_obj(scene, obj_path)
    dae_format.save_dae(scene, dae_path)
    mtl = (tmp_path / "m.mtl").read_text(encoding="utf-8")
    xml = dae_path.read_text(encoding="utf-8")
    import re
    return {
        "glb": {m["name"] for m in _glb(scene, tmp_path)["materials"]},
        "obj": set(re.findall(r"^newmtl (.*)$", mtl, re.M)),
        "dae": set(re.findall(r'<material id="[^"]*" name="([^"]*)"', xml)),
    }


# ---- Two materials, one colour --------------------------------------------

def _twins():
    scene = Scene()
    for name in ("White_A", "White_B"):
        scene.materials[name] = Material(name, color=WHITE)
    _quad(scene.mesh, 0, attrs=scene.materials["White_A"].face_attrs())
    _quad(scene.mesh, 2, attrs=scene.materials["White_B"].face_attrs())
    return scene


def test_same_colour_different_names_stay_two_materials(tmp_path):
    for fmt, names in _exported_names(_twins(), tmp_path).items():
        assert {"White_A", "White_B"} <= names, fmt


def test_each_twin_keeps_its_own_faces():
    materials, prims = collect_geometry(_twins())
    by_name = {info["mat"]: len(prims[key]) for key, info in materials.items()}
    assert by_name == {"White_A": 2, "White_B": 2}       # two triangles each


def test_anonymous_paint_still_merges_by_colour():
    """Unnamed paint keeps the old grouping: same look, one material."""
    a = material_key({"color": WHITE})
    b = material_key({"color": WHITE})
    assert a == b == ("color", WHITE)
    assert material_key({}) == ("color", CREAM)
    assert material_key({"color": WHITE, "mat": "White_A"}) != a


# ---- Paint on a group ------------------------------------------------------

def _painted_group():
    """A classic group painted pink: one unpainted face, one blue of its own."""
    scene = Scene()
    g = Group(Mesh(), name="Box")
    _quad(g.mesh, 0)                                     # default material
    _quad(g.mesh, 2, attrs=_paint("Blue", BLUE))         # painted itself
    g.material = _paint("Pink", PINK)
    scene.groups.append(g)
    return scene, g


def test_group_paint_reaches_its_unpainted_faces(tmp_path):
    scene, _g = _painted_group()
    for fmt, names in _exported_names(scene, tmp_path).items():
        assert "Pink" in names, fmt                      # the group's paint
        assert "Blue" in names, fmt                      # the face's own wins
        assert not any(n.startswith("mat") for n in names), fmt


def test_group_paint_colours_the_right_faces():
    scene, _g = _painted_group()
    materials, prims = collect_geometry(scene)
    colours = {info.get("mat"): info["color"] for info in materials.values()}
    assert colours == {"Pink": PINK, "Blue": BLUE}
    assert all(len(prims[k]) == 2 for k in materials)


def test_exporting_leaves_the_document_untouched(tmp_path):
    scene, g = _painted_group()
    before = [dict(f.attrs) for f in g.mesh.faces]
    _exported_names(scene, tmp_path)
    assert [dict(f.attrs) for f in g.mesh.faces] == before


# ---- Copies of a component ---------------------------------------------------

def _two_copies():
    """Two copies of one component: one painted pink, one blue."""
    scene = Scene()
    proto = Mesh()
    _quad(proto, 0)
    for i, (name, colour) in enumerate((("Pink", PINK), ("Blue", BLUE))):
        g = Group(proto, name=f"Copy {name}")
        g.xform = _at(3 * i)
        g.material = _paint(name, colour)
        scene.groups.append(g)
    return scene


def test_component_copies_keep_their_own_paint_in_glb(tmp_path):
    doc = _glb(_two_copies(), tmp_path)
    by_node = _glb_node_materials(doc)
    assert by_node["Copy Pink"] == {"Pink"}
    assert by_node["Copy Blue"] == {"Blue"}


def test_unpainted_copies_still_share_one_mesh_in_glb(tmp_path):
    scene = _two_copies()
    for g in scene.groups:
        g.material = None
    doc = _glb(scene, tmp_path)
    meshes = {n["mesh"] for n in doc["nodes"] if "mesh" in n}
    assert len(meshes) == 1                              # sharing kept


def test_component_copies_paint_in_dae_and_obj(tmp_path):
    names = _exported_names(_two_copies(), tmp_path)
    assert {"Pink", "Blue"} <= names["dae"]
    assert {"Pink", "Blue"} <= names["obj"]


# ---- Pieces inside a component ---------------------------------------------

def _nested():
    """A pink component holding two pieces: one green of its own, one not."""
    scene = Scene()
    proto = Mesh()
    _quad(proto, 0)
    own = Group(proto, name="Green piece")
    own.xform = _at(0)
    own.material = _paint("Green", GREEN)
    plain = Group(proto, name="Plain piece")
    plain.xform = _at(2)
    top = Group(Mesh(), name="Top")
    top.xform = _at(0, 5)
    top.adopt([own, plain])
    top.material = _paint("Pink", PINK)
    scene.groups.append(top)
    return scene


def test_nested_piece_paint_wins_and_the_rest_takes_the_top(tmp_path):
    materials, prims = collect_geometry(_nested())
    counts = {info.get("mat"): len(prims[k]) for k, info in materials.items()}
    assert counts == {"Green": 2, "Pink": 2}
    by_node = _glb_node_materials(_glb(_nested(), tmp_path))
    assert by_node["Green piece"] == {"Green"}
    assert by_node["Plain piece"] == {"Pink"}
