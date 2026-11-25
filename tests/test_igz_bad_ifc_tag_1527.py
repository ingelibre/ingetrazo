# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A BIM tag that is not a dict does not block the save (#1527)."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.scene import Scene
from formats import igz


def _square(mesh):
    return mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])


def _saved_and_opened(scene, tmp_path, fmt):
    path = tmp_path / "doc.igz"
    igz.save_scene(scene, path, **({"fmt": fmt} if fmt else {}))
    back = Scene()
    igz.load_into(back, path)
    return back


@pytest.mark.parametrize("fmt", [None, "json"])
@pytest.mark.parametrize("tag, expected", [
    ("IfcPipeSegment", {"class": "IfcPipeSegment", "name": "Test"}),
    ({"class": "IfcWall", "name": "W", "extra": [1]},
     {"class": "IfcWall", "name": "W", "extra": [1]}),
    (7, None),
    (["IfcWall"], None),
    (" ", None),
])
def test_a_group_tag_is_repaired_or_left_out(tmp_path, tag, expected, fmt):
    scene = Scene()
    classic = Group(name="Test")
    placed = Group(name="Test")
    placed.xform = QMatrix4x4()
    for g in (classic, placed):
        _square(g.mesh)
        g.ifc = tag
        scene.groups.append(g)
    back = _saved_and_opened(scene, tmp_path, fmt)
    assert [g.ifc for g in back.groups] == [expected, expected]
    assert len(back.groups[0].mesh.faces) == 1


@pytest.mark.parametrize("fmt", [None, "json"])
@pytest.mark.parametrize("tag, expected", [
    ("IfcSlab", {"class": "IfcSlab", "name": ""}),
    (7, None),
])
def test_a_face_tag_is_repaired_or_left_out(tmp_path, tag, expected, fmt):
    scene = Scene()
    _square(scene.mesh).attrs["ifc"] = tag
    back = _saved_and_opened(scene, tmp_path, fmt)
    assert back.mesh.faces[0].attrs.get("ifc") == expected


@pytest.mark.parametrize("place", [False, True])
@pytest.mark.parametrize("tag, expected", [
    ("IfcPipeSegment", {"class": "IfcPipeSegment", "name": "Test"}),
    ({"class": "IfcWall", "name": "W"}, {"class": "IfcWall", "name": "W"}),
    (7, None),
    (None, None),
])
def test_a_group_with_such_a_tag_can_be_copied(tag, expected, place):
    from core.group import copy_group
    g = Group(name="Test")
    _square(g.mesh)
    if place:
        g.xform = QMatrix4x4()
    g.ifc = tag
    copied = copy_group(g).ifc
    assert copied == expected and (copied is None or copied is not tag)
