# SPDX-License-Identifier: GPL-3.0-or-later
"""Ungrouping a placed copy must keep its textures where they showed (#1278).

Copying a classic group snapshots it as an identity instance and every
paste is a placed sibling of that prototype, so the group a user ungroups
usually carries a placement. Explode mapped the faces' vertices through
the placement but copied their attrs verbatim, leaving each texture's
world→UV map anchored to the prototype's local frame — the texture
stayed behind at the local origin and read as lost.
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group
from core.history import ExplodeGroupCommand, History
from core.mesh import Mesh
from core.scene import Scene

UVW = [0.5, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0]


def _textured_group():
    m = Mesh()
    f = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    f.attrs["texture"] = {"path": "wood.png", "sw": 2.0, "sh": 2.0,
                          "uvw": list(UVW)}
    return Group(m, "caja")


def _explode(group):
    sc = Scene()
    sc.groups.append(group)
    History(sc).execute(ExplodeGroupCommand(group))
    return sc


def test_explode_of_a_translated_instance_refits_the_texture_map():
    g = _textured_group()
    g.xform = QMatrix4x4()
    g.xform.translate(V(3, 0, 0))
    g.component = True
    sc = _explode(g)
    face = sc.mesh.faces[0]
    assert face.vertices[0].x() == 3.0
    # U = 0.5 * (x - 3): the map's constant follows the placement.
    assert face.attrs["texture"]["uvw"] == [0.5, 0.0, 0.0, -1.5,
                                             0.0, 0.5, 0.0, 0.0]


def test_explode_of_a_pasted_copy_keeps_the_texture_and_the_prototype():
    template = copy_group(_textured_group())
    template.xform = QMatrix4x4()          # the clipboard snapshot
    template.component = False
    pasted = copy_group(template, V(3, 0, 0))
    sc = _explode(pasted)
    face = sc.mesh.faces[0]
    assert face.attrs["texture"]["path"] == "wood.png"
    assert face.attrs["texture"]["uvw"][3] == -1.5
    # The shared prototype keeps its local map: siblings still to paste
    # must not inherit the exploded copy's re-fit.
    assert template.mesh.faces[0].attrs["texture"]["uvw"] == UVW


def test_explode_of_a_classic_group_leaves_the_texture_map_alone():
    sc = _explode(_textured_group())
    assert sc.mesh.faces[0].attrs["texture"]["uvw"] == UVW
