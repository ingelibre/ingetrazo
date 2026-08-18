# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Model Info plugin: the numbers must agree with the rest of the app.

Each test in the second half pins one of the wrong numbers the original
contribution (PR #2) reported: materials read from a key IngeTrazo never
writes (always empty), BIM counted per face instead of per object, totals
double-counted while a group was open for editing, and colour swatches
assumed 0–255 ints where IngeTrazo paints with floats 0–1.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core import bim                                              # noqa: E402
from core.group import Group                                      # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from plugins.model_info import (                                  # noqa: E402
    ModelInfoTool, _collect_stats, _stats_to_text)


def _quad(mesh, z=0.0, o=0.0, size=4.0):
    return mesh.add_face([
        QVector3D(o, o, z), QVector3D(o + size, o, z),
        QVector3D(o + size, o + size, z), QVector3D(o, o + size, z)])


# ---- Basic counts ---------------------------------------------------------

def test_empty_scene():
    stats = _collect_stats(Scene())
    assert stats["total_verts"] == 0
    assert stats["bbox"]["width"] == 0.0
    assert stats["colors"] == [] and stats["textures"] == []
    assert stats["bim_objects"] == []


def test_geometry_and_groups():
    scene = Scene()
    _quad(scene.mesh, size=1.0)
    g_mesh = Mesh()
    g_mesh.add_face([QVector3D(2, 0, 0), QVector3D(3, 0, 0),
                     QVector3D(2.5, 1, 0)])
    scene.groups.append(Group(g_mesh, name="TestGroup"))

    stats = _collect_stats(scene)
    assert stats["loose_verts"] == 4 and stats["loose_faces"] == 1
    assert stats["group_verts"] == 3 and stats["group_faces"] == 1
    assert stats["total_verts"] == 7 and stats["total_faces"] == 2
    assert stats["tri_count"] == 3          # quad -> 2, triangle -> 1
    assert abs(stats["bbox"]["width"] - 3.0) < 1e-6


def test_tool_metadata():
    tool = ModelInfoTool()
    assert tool.name == "Model Info"
    assert tool.shortcut is None and tool.uses_snap is False


# ---- The four numbers PR #2 got wrong -------------------------------------

def test_materials_read_the_attrs_ingetrazo_writes():
    """PR #2 read attrs["material"], which nothing in IngeTrazo writes:
    its Materials tab was empty no matter how painted the model was. The
    real keys are attrs["color"] (floats 0-1) and attrs["texture"]."""
    scene = Scene()
    f1 = _quad(scene.mesh)                       # 16 m2, painted red
    f1.attrs["color"] = (0.8, 0.1, 0.1)
    f2 = _quad(scene.mesh, z=1.0)                # 16 m2, same red
    f2.attrs["color"] = (0.8, 0.1, 0.1)
    f3 = _quad(scene.mesh, z=2.0, size=2.0)      # 4 m2, textured
    f3.attrs["texture"] = {"path": "/tex/ladrillo.png", "sw": 1.0}

    stats = _collect_stats(scene)
    assert len(stats["colors"]) == 1
    red = stats["colors"][0]
    assert red["faces"] == 2 and abs(red["area"] - 32.0) < 1e-6
    assert red["rgb"] == (0.8, 0.1, 0.1)         # floats kept, not int-cast
    assert len(stats["textures"]) == 1
    tex = stats["textures"][0]
    assert tex["name"] == "ladrillo"
    assert tex["faces"] == 1 and abs(tex["area"] - 4.0) < 1e-6


def test_bim_counts_objects_not_faces():
    """One wall spanning six tagged faces is ONE IfcWall — the same answer
    core.bim gives the BIM tray and the IFC export. PR #2 said six."""
    scene = Scene()
    faces = [_quad(scene.mesh, z=float(i)) for i in range(6)]
    bim.tag_faces(faces, "IfcWall", "Muro 1", obj_id=1)

    stats = _collect_stats(scene)
    assert len(stats["bim_objects"]) == 1
    assert stats["bim_by_class"] == {"IfcWall": 1}
    obj = stats["bim_objects"][0]
    assert obj["name"] == "Muro 1"
    assert abs(obj["area"] - 6 * 16.0) < 1e-6    # quantities come along


def test_totals_stable_while_a_group_is_open():
    """begin_group_edit swaps scene.mesh to the group's mesh; reading it
    double-counted (PR #2 reported 24 vertices for this 16-vertex model).
    scene.loose_mesh is the honest source either way."""
    scene = Scene()
    _quad(scene.mesh)
    g = Group(Mesh(), name="Caseta")
    for i in range(3):
        _quad(g.mesh, z=i * 10.0, o=20.0)
    scene.groups.append(g)

    closed = _collect_stats(scene)
    scene.begin_group_edit(g)
    opened = _collect_stats(scene)
    scene.end_group_edit()

    assert closed["total_verts"] == 16
    assert opened["total_verts"] == closed["total_verts"]
    assert opened["total_faces"] == closed["total_faces"]
    assert opened["loose_verts"] == closed["loose_verts"]


def test_showcase_key_ifc_class_is_not_bim():
    """attrs["ifc_class"] (what PR #3's showcase script wrote) is not the
    key IngeTrazo reads: it must NOT surface as a BIM object here, exactly
    as it does not surface in the BIM tray or the IFC export."""
    scene = Scene()
    f = _quad(scene.mesh)
    f.attrs["ifc_class"] = "IfcSlab"
    assert _collect_stats(scene)["bim_objects"] == []


# ---- Formatting -----------------------------------------------------------

def test_lengths_follow_the_dimension_style():
    scene = Scene()
    _quad(scene.mesh, size=2.5)
    scene.dimension_style["units"] = "cm"
    scene.dimension_style["decimals"] = 1
    text = _stats_to_text(_collect_stats(scene))
    assert "250.0 cm" in text                 # 2.5 m in the document's unit


def test_stats_to_text_mentions_the_essentials():
    scene = Scene()
    f = _quad(scene.mesh)
    f.attrs["color"] = (1.0, 0.0, 0.0)
    bim.tag_faces([f], "IfcSlab", "Losa", obj_id=1)
    text = _stats_to_text(_collect_stats(scene))
    assert "rgb(255,0,0)" in text
    assert "IfcSlab" in text and "Losa" in text
    assert "Layer 0" in text
