# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A BIM tag a script left as a bare class name, or with ids of two kinds,
does not stop the object list nor the IFC export (#1527)."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.bim import collect_objects, tag_faces
from core.group import Group
from core.scene import Scene
from formats.ifc import save_ifc


def _square(mesh, z=0.0):
    return mesh.add_face([V(0, 0, z), V(1, 0, z), V(1, 1, z), V(0, 1, z)])


@pytest.mark.parametrize("tag, classes", [
    ("IfcWall", ["IfcWall"]), (["IfcWall"], []), (7, [])])
@pytest.mark.parametrize("where", ["group", "loose face", "face of a group"])
def test_a_tag_that_is_not_a_dict(tmp_path, where, tag, classes):
    scene = Scene()
    g = Group(name="Pipe")
    scene.groups.append(g)
    face = _square(scene.mesh if where == "loose face" else g.mesh)
    if where == "group":
        g.ifc = tag
    else:
        face.attrs["ifc"] = tag
    assert [o["class"] for o in collect_objects(scene, {})] == classes
    if classes:
        save_ifc(scene, tmp_path / "a.ifc")


def test_tag_ids_of_two_kinds():
    scene = Scene()
    for z, oid in enumerate((2, "two", 1)):
        tag_faces([_square(scene.mesh, z)], "IfcSlab", str(oid), oid)
    assert [o["name"] for o in collect_objects(scene)] == [
        "1", "2", "two"]
