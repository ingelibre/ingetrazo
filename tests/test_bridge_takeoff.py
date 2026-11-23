# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``get_takeoff`` and ``select`` by GlobalId: the takeoff an agent or a
budget reads over the bridge is the IFC export's, element by element —
the same GlobalIds (copies, mirrors and nested objects included), the same
quantities, nothing made up for what cannot be measured."""
from __future__ import annotations

import json
import re

import pytest
from PySide6.QtGui import QMatrix4x4
from PySide6.QtGui import QVector3D as V

from core.bim import collect_objects, tag_faces, tag_group
from core.group import Group, copy_group
from core.history import History
from core.layers import Layer, assign_layer
from core.scene import Scene
from core.takeoff import find_objects, takeoff
from formats import igz
from formats.ifc import save_ifc
from tests.test_bim_grouped_tags import _box, _group, _nest
from tests.test_bridge_tools import _err, _mcp_call, _ok, env  # noqa: F401


def _mirrored(g, x):
    m = QMatrix4x4()
    m.translate(x, 0, 0)
    m.scale(-1, 1, 1)
    return m * g.xform


def _fill(scene):
    """Loose faces, a tagged group, components with tagged faces and as
    tagged groups — each copied and mirrored —, and a nested object."""
    h = History(scene)

    def box(x, size=(2.0, 1.0, 3.0), component=True):
        return _group(scene, h, _box(scene, x, size), component=component)

    column = box(0, (0.3, 0.3, 3.0))
    tag_group(column, "IfcColumn", "C1")
    plain = box(10, component=False)
    tag_group(plain, "IfcBeam", "Plain")
    wall = box(20)
    tag_faces(list(wall.mesh.faces), "IfcWall", "W1", 1)
    for g, x in ((column, 5.0), (wall, 60.0)):
        scene.groups.append(copy_group(g, V(x, 3, 0)))
        flipped = copy_group(g, V(0, 9, 0))
        flipped.xform = _mirrored(flipped, x)
        scene.groups.append(flipped)
    inner = box(80)
    tag_group(inner, "IfcFooting", "F1")
    nest = _nest(scene, h, [inner, box(90)])
    scene.groups.append(copy_group(nest, V(0, 30, 0)))
    # One open face: no volume.
    sheet = Group(name="Sheet")
    sheet.mesh.add_face([V(0, 50, 0), V(1, 50, 0), V(1, 50, 2), V(0, 50, 2)])
    tag_group(sheet, "IfcColumn", "Open")
    odd = Group(name="Odd")
    odd.mesh.add_face([V(0, 60, 0), V(1, 60, 0), V(1, 60, 2), V(0, 60, 2)])
    tag_group(odd, "IfcSomethingElse", "")
    empty = Group(name="Empty")
    tag_group(empty, "IfcWall", "Nothing drawn")
    scene.groups += [sheet, odd, empty]
    faces = _box(scene, 40)
    tag_faces(faces, "IfcSlab", "Loose", 1)
    scene.clear_selection()           # grouping leaves the group selected
    return scene


def _ifc(path):
    """``{GlobalId: (entity, name, {quantity: value})}`` of the products in
    the file — read from its text, with no help from the writer."""
    rows = dict(re.findall(r"^#(\d+)=(.*);$", path.read_text(), re.M))
    out, by_id = {}, {}
    for eid, row in rows.items():
        m = re.match(r"(IFC\w+)\('([0-3][\w$]{21})',#?[\w$]+,'(.*?)',\$,"
                     r"(?:\$|'.*?'),#\d+,#\d+,", row)
        if m and "IFCPRODUCTDEFINITIONSHAPE" in rows.get(
                re.findall(r"#\d+", row)[-1][1:], ""):
            by_id[eid] = out[m[2]] = (m[1], m[3], {})
    for row in rows.values():
        m = re.match(r"IFCRELDEFINESBYPROPERTIES\(.*\(#(\d+)\),#(\d+)\)", row)
        if not m or m[1] not in by_id:
            continue
        for q in re.findall(r"#(\d+)", rows[m[2]].rsplit("(", 1)[1]):
            kind, name, value = re.match(
                r"IFCQUANTITY(\w+)\('(\w+)',\$,\$,([-\d.]+),\$\)",
                rows[q]).groups()
            by_id[m[1]][2][name] = {"value": float(value), "unit": {
                "AREA": "m2", "VOLUME": "m3", "LENGTH": "m",
                "WEIGHT": "kg"}[kind]}
    return out


def _same(scene, path):
    save_ifc(scene, path)
    file = _ifc(path)
    data = takeoff(scene)
    assert {e["global_id"]: (e["ifc_class"].upper(), e["name"],
                             e["quantities"]) for e in data["elements"]} == file
    assert len(data["elements"]) == len(file)
    return data


def test_the_takeoff_is_the_ifc_export(tmp_path):
    scene = _fill(Scene())
    version = scene.version
    data = _same(scene, tmp_path / "a.ifc")
    assert scene.version == version                       # read-only
    # 3 columns + 1 beam + 3 walls + 2 footings + open + odd + slab; the
    # empty object is not exported.
    assert len(data["elements"]) == 12
    assert data["schema"] == "inge-takeoff" and data["version"] == 1
    assert data["source"] == {"app": "IngeTrazo", "document": "",
                              "namespace": scene.ifc_namespace}
    assert all(set(e) == {"global_id", "ifc_class", "name", "type", "storey",
                          "layer", "material", "quantities", "metrado"}
               for e in data["elements"])
    json.dumps(data, allow_nan=False)
    # Saved and opened again: the same.
    igz.save_scene(scene, tmp_path / "a.igz")
    again = Scene()
    igz.load_into(again, tmp_path / "a.igz")
    key = lambda d: {e["global_id"] for e in d["elements"]}  # noqa: E731
    assert key(_same(again, tmp_path / "b.ifc")) == key(data)


def test_a_mirrored_copy_measures_like_the_original(tmp_path):
    data = takeoff(_fill(Scene()))
    walls = [e for e in data["elements"] if e["name"] == "W1"]
    assert len(walls) == 3 and len({e["global_id"] for e in walls}) == 3
    for e in walls:
        assert e["quantities"]["GrossVolume"]["value"] == pytest.approx(6.0)
        assert e["metrado"] == {"value": pytest.approx(6.0), "unit": "m2"}


def test_what_cannot_be_measured_is_absent():
    data = takeoff(_fill(Scene()))
    sheet = next(e for e in data["elements"] if e["name"] == "Open")
    assert "GrossVolume" not in sheet["quantities"]
    assert "CrossSectionArea" not in sheet["quantities"]
    assert sheet["metrado"] is None
    for e in data["elements"]:
        for q in (*e["quantities"].values(), e["metrado"] or {"value": 1}):
            assert q["value"] > 0


def test_ifcopenshell_reads_the_same_elements(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from ifcopenshell.util.element import get_psets
    scene = _fill(Scene())
    path = tmp_path / "a.ifc"
    save_ifc(scene, path)
    model = ifcopenshell.open(str(path))
    elements = {e["global_id"]: e for e in takeoff(scene)["elements"]}
    products = [p for p in model.by_type("IfcElement")]
    assert {p.GlobalId for p in products} == set(elements)
    for p in products:
        e = elements[p.GlobalId]
        assert (p.is_a(), p.Name) == (e["ifc_class"], e["name"])
        read = {}
        for q in get_psets(p, qtos_only=True).values():
            read.update({k: v for k, v in q.items() if k != "id"})
        assert read == {k: v["value"] for k, v in e["quantities"].items()}


def test_ambiguous_identities_are_refused_as_the_export_does():
    scene = _fill(Scene())
    dup = copy_group(scene.groups[0], V(5, 70, 0))
    dup.uid = scene.groups[0].uid
    scene.groups.append(dup)
    with pytest.raises(ValueError, match="Duplicate BIM object identity"):
        takeoff(scene)


def test_class_filter_and_unknown_class():
    scene = _fill(Scene())
    names = [e["name"] for e in takeoff(
        scene, classes=["ifcwall", "IfcSlab"])["elements"]]
    assert sorted(names) == ["Loose", "W1", "W1", "W1"]
    proxies = takeoff(scene, classes=["IfcBuildingElementProxy"])["elements"]
    assert [e["name"] for e in proxies] == ["IfcBuildingElementProxy"]
    with pytest.raises(ValueError, match="unknown IFC class 'IfcWal'"):
        takeoff(scene, classes=["IfcWal"])


def test_selection_filter_reaches_nested_and_loose_objects():
    scene = _fill(Scene())
    assert takeoff(scene, selection_only=True)["elements"] == []
    nest = next(g for g in scene.groups if g.children)
    scene.selection = {nest}
    assert [e["name"] for e in takeoff(
        scene, selection_only=True)["elements"]] == ["F1"]
    scene.selection = {scene.mesh.faces[0]}
    assert [e["name"] for e in takeoff(
        scene, selection_only=True)["elements"]] == ["Loose"]


def test_layer_material_type_and_storey(tmp_path):
    scene = _fill(Scene())
    scene.layers.append(Layer("Muros"))
    plain = next(g for g in scene.groups
                 if (g.ifc or {}).get("name") == "Plain")
    assign_layer(plain, "Muros")
    plain.material = {"mat": "Ladrillo", "color": [1, 0, 0]}
    nest = next(g for g in scene.groups if g.children)
    assign_layer(nest, "Muros")
    scene.ifc_project["spatial"] = {"storeys": [{"id": "s1", "name": "P1"}]}
    sheet = next(g for g in scene.groups if g.name == "Sheet")
    sheet.ifc["delivery"] = {"object_type": "T-1", "storey_id": "s1",
                             "material": "Concreto"}
    data = takeoff(scene)["elements"]
    by_name = {e["name"]: e for e in data}
    assert by_name["Plain"]["layer"] == "Muros"
    assert by_name["Plain"]["material"] == "Ladrillo"
    assert (by_name["Plain"]["type"], by_name["Plain"]["storey"]) == ("", "")
    assert {"Muros", "Layer 0"} == {e["layer"] for e in data
                                    if e["name"] == "F1"}   # inherited
    assert (by_name["Open"]["type"], by_name["Open"]["storey"],
            by_name["Open"]["material"]) == ("T-1", "P1", "Concreto")
    # One face painted otherwise: no single material.
    plain.mesh.faces[0].attrs.update(mat="Yeso", color=[0, 1, 0])
    by_name = {e["name"]: e for e in takeoff(scene)["elements"]}
    assert by_name["Plain"]["material"] == ""


def test_find_objects_reports_the_missing():
    scene = _fill(Scene())
    gid = takeoff(scene, classes=["IfcSlab"])["elements"][0]["global_id"]
    objects, missing = find_objects(scene, [gid, "nope", gid])
    assert [o["name"] for o in objects] == ["Loose"] and missing == ["nope"]


# ---- Through the bridge ---------------------------------------------------------

@pytest.fixture
def model(env):  # noqa: F811
    win, vp, bridge = env
    _fill(vp.scene)
    vp.scene.version += 1
    vp.history.clear()
    win._saved_version = vp.scene.version
    return win, vp, bridge


def test_the_bridge_gives_what_export_file_writes(model, tmp_path):
    win, vp, bridge = model
    data = _ok(bridge, "get_takeoff")
    assert not win._is_dirty() and not vp.history.undo_stack
    assert data["source"]["document"]                     # «Untitled»
    path = tmp_path / "m.ifc"
    assert _ok(bridge, "export_file", {"path": str(path)})["elements"] == \
        len(data["elements"])
    assert {e["global_id"] for e in data["elements"]} == set(_ifc(path))
    out = _mcp_call(bridge, "get_takeoff", {"classes": ["IfcSlab"]})
    assert not out["isError"]
    assert [e["name"] for e in json.loads(
        out["content"][0]["text"])["elements"]] == ["Loose"]
    assert "unknown IFC class" in _err(bridge, "get_takeoff",
                                       {"classes": ["Wall"]})


def test_the_takeoff_follows_the_model(model):
    win, vp, bridge = model
    before = len(_ok(bridge, "get_takeoff")["elements"])
    _ok(bridge, "run_python", {"code": (
        "g = extrude([(0,90),(1,90),(1,91),(0,91)], 0, 1, name='New')\n"
        "g = next(x for x in scene.groups if x.name == 'New')\n"
        "bim.tag_group(g, 'IfcColumn', 'New')\n")})
    assert len(_ok(bridge, "get_takeoff")["elements"]) == before + 1
    _ok(bridge, "undo")
    assert len(_ok(bridge, "get_takeoff")["elements"]) == before


def test_select_by_global_id(model):
    win, vp, bridge = model
    scene = vp.scene
    gids = {}
    for e in _ok(bridge, "get_takeoff")["elements"]:
        gids.setdefault(e["name"], []).append(e["global_id"])

    out = _ok(bridge, "select", {"global_ids": gids["C1"] + ["gone"]})
    assert out["selected"] == 3 and out["found"] == 3
    assert out["not_found"] == ["gone"] and "by_group" not in out
    assert all(g.ifc["class"] == "IfcColumn" for g in scene.selection)
    assert {e["global_id"] for e in _ok(bridge, "get_takeoff", {
        "selection_only": True})["elements"]} == set(gids["C1"])

    # Tagged faces inside a closed group: the group stands for them.
    out = _ok(bridge, "select", {"global_ids": gids["W1"][:1]})
    assert len(out["by_group"]) == 1 and out["by_group"] == out["objects"]
    assert [e["global_id"] for e in _ok(bridge, "get_takeoff", {
        "selection_only": True})["elements"]] == gids["W1"][:1]

    # Loose faces; with names too; modes.
    assert _ok(bridge, "select", {"global_ids": gids["Loose"]})[
        "selected"] == 6
    out = _ok(bridge, "select", {"global_ids": gids["Loose"],
                                 "names": ["Caja"], "mode": "toggle"})
    assert [o["name"] for o in out["objects"]] == ["Caja"]
    assert out["selected"] == 1
    out = _ok(bridge, "select", {"global_ids": ["gone"]})
    assert out["selected"] == 0 and out["not_found"] == ["gone"]
    # Unknown names stay an error, the selection as it was.
    assert "found" not in _ok(bridge, "select", {"clear": True})
    assert "no object with name" in _err(bridge, "select", {
        "names": ["zzz"], "global_ids": gids["C1"]})
    assert not scene.selection
    assert not win._is_dirty() and not vp.history.undo_stack


def test_select_by_global_id_with_a_group_open(model):
    win, vp, bridge = model
    scene = vp.scene
    obj = next(o for o in collect_objects(scene) if o["name"] == "W1")
    before = {e["global_id"]: e for e in
              _ok(bridge, "get_takeoff")["elements"]}
    objects = find_objects(scene, before)[0]
    gid = next(g for g, o in zip(before, objects)
               if o.get("owner") is obj["owner"])
    vp.begin_group_edit(obj["owner"])
    assert scene.edit_group is obj["owner"]
    assert {e["global_id"] for e in
            _ok(bridge, "get_takeoff")["elements"]} == set(before)
    out = _ok(bridge, "select", {"global_ids": [gid]})
    assert out["selected"] == 6 and "by_group" not in out
    assert set(scene.selection) == set(scene.mesh.faces)
    assert [e["global_id"] for e in _ok(bridge, "get_takeoff", {
        "selection_only": True})["elements"]] == [gid]
    # Loose faces: the group closes first.
    loose = next(g for g, e in before.items() if e["name"] == "Loose")
    assert _ok(bridge, "select", {"global_ids": [loose]})["selected"] == 6
    assert scene.edit_group is None
