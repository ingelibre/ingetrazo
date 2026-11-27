# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Element status (new / existing / demolish) in the IFC export.

IFC4 keeps the status as ``Pset_<Class>Common.Status`` (PEnum_ElementStatus),
an enumerated property, not an entity attribute. A BIM tag carries it as
``"status"``; untagged status writes nothing, a bad value fails the export
before the file is written.
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.bim import tag_faces, tag_group
from core.group import Group
from core.scene import Scene
from formats import igz
from formats.ifc import ELEMENT_STATUSES, element_status, save_ifc


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _group(scene, cls, name, status=None, x=0.0):
    group = Group()
    group.mesh.add_face([V(x, 0), V(x + 2, 0), V(x + 2, 0, 3), V(x, 0, 3)])
    group.xform = QMatrix4x4()
    tag_group(group, cls, name)
    if status is not None:
        group.ifc["status"] = status
    scene.groups.append(group)
    return group


def _status_rows(text):
    """``{pset name: [status values]}`` read back from the STEP text."""
    props = dict(re.findall(
        r"#(\d+)=IFCPROPERTYENUMERATEDVALUE\('Status',\$,\(IFCLABEL\('(\w+)'\)\),\$\);",
        text))
    out = {}
    for name, refs in re.findall(r"IFCPROPERTYSET\('[^']+',\$,'(\w+)',\$,\(([^)]*)\)\);", text):
        for ref in refs.split(","):
            if ref.strip("#") in props:
                out.setdefault(name, []).append(props[ref.strip("#")])
    return out


def test_group_status_is_written_to_the_common_pset(tmp_path):
    scene = Scene()
    _group(scene, "IfcWall", "Existing wall", "EXISTING")
    _group(scene, "IfcWall", "Wall to remove", "DEMOLISH", x=3)
    _group(scene, "IfcMember", "New rafter", "new", x=6)
    path = tmp_path / "status.ifc"
    save_ifc(scene, path)
    rows = _status_rows(path.read_text())
    assert sorted(rows["Pset_WallCommon"]) == ["DEMOLISH", "EXISTING"]
    assert rows["Pset_MemberCommon"] == ["NEW"]          # case-folded


def test_loose_face_tag_carries_status(tmp_path):
    scene = Scene()
    face = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 0, 3), V(0, 0, 3)])
    tag_faces([face], "IfcWall", "Wall", 1)
    face.attrs["ifc"]["status"] = "EXISTING"
    path = tmp_path / "faces.ifc"
    save_ifc(scene, path)
    assert _status_rows(path.read_text()) == {"Pset_WallCommon": ["EXISTING"]}


def test_unknown_class_falls_back_to_proxy_pset(tmp_path):
    scene = Scene()
    _group(scene, "IfcSolarDevice", "PV module", "NEW")
    path = tmp_path / "proxy.ifc"
    save_ifc(scene, path)
    text = path.read_text()
    assert "IFCBUILDINGELEMENTPROXY(" in text
    assert _status_rows(text) == {"Pset_BuildingElementProxyCommon": ["NEW"]}


def test_no_status_writes_no_status_property(tmp_path):
    scene = Scene()
    _group(scene, "IfcWall", "Wall")
    path = tmp_path / "plain.ifc"
    save_ifc(scene, path)
    assert "IFCPROPERTYENUMERATEDVALUE('Status'" not in path.read_text()


def test_space_has_no_status_property(tmp_path):
    scene = Scene()
    _group(scene, "IfcSpace", "Room", "EXISTING")
    path = tmp_path / "space.ifc"
    save_ifc(scene, path)
    assert "'Status'" not in path.read_text()


def test_invalid_status_fails_without_overwriting(tmp_path):
    scene = Scene()
    _group(scene, "IfcWall", "Wall", "Bestand")
    path = tmp_path / "keep.ifc"
    path.write_text("keep me")
    with pytest.raises(ValueError, match="status 'Bestand'"):
        save_ifc(scene, path)
    assert path.read_text() == "keep me"


def test_element_status_values():
    scene = Scene()
    group = _group(scene, "IfcWall", "Wall", " temporary ")
    assert element_status({"group": group}) == "TEMPORARY"
    group.ifc["status"] = ""
    assert element_status({"group": group}) is None
    assert set(ELEMENT_STATUSES) >= {"NEW", "EXISTING", "DEMOLISH"}


def test_status_survives_save_and_load(tmp_path):
    scene = Scene()
    _group(scene, "IfcBeam", "Purlin", "EXISTING")
    path = tmp_path / "status.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    assert loaded.groups[0].ifc["status"] == "EXISTING"


def test_status_validates_with_ifcopenshell(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.util.element
    import ifcopenshell.validate
    scene = Scene()
    _group(scene, "IfcWall", "Wall", "DEMOLISH")
    path = tmp_path / "valid.ifc"
    save_ifc(scene, path)
    model = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger)
    assert not logger.statements
    wall = model.by_type("IfcWall")[0]
    psets = ifcopenshell.util.element.get_psets(wall)
    assert psets["Pset_WallCommon"]["Status"] == "DEMOLISH"
