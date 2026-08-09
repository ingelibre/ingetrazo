# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood and IngeTrazo contributors.
"""Unit tests for the Model Info plugin and plugin discovery system."""
import pytest
from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from plugins.model_info import ModelInfoTool, _collect_stats, _stats_to_text


def test_collect_stats_empty_scene():
    scene = Scene()
    stats = _collect_stats(scene)

    assert stats["loose_verts"] == 0
    assert stats["loose_edges"] == 0
    assert stats["loose_faces"] == 0
    assert stats["group_count"] == 0
    assert stats["total_verts"] == 0
    assert stats["bbox"]["width"] == 0.0


def test_collect_stats_geometry_and_groups():
    scene = Scene()
    pts = [QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]
    scene.mesh.add_face(pts)

    g_mesh = Mesh()
    g_pts = [QVector3D(2, 0, 0), QVector3D(3, 0, 0), QVector3D(2.5, 1, 0)]
    g_mesh.add_face(g_pts)
    g = Group(g_mesh, name="TestGroup")
    scene.groups.append(g)

    stats = _collect_stats(scene)

    assert stats["loose_verts"] == 4
    assert stats["loose_faces"] == 1
    assert stats["group_count"] == 1
    assert stats["group_verts"] == 3
    assert stats["group_faces"] == 1
    assert stats["total_verts"] == 7
    assert stats["total_faces"] == 2
    assert stats["tri_count"] == 3
    assert abs(stats["bbox"]["width"] - 3.0) < 1e-4
    assert abs(stats["bbox"]["depth"] - 1.0) < 1e-4


def test_model_info_tool_metadata():
    tool = ModelInfoTool()
    assert tool.name == "Model Info"
    assert tool.uses_snap is False
    assert tool.shortcut is None


def test_stats_to_text_format():
    scene = Scene()
    pts = [QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 0)]
    scene.mesh.add_face(pts)
    stats = _collect_stats(scene)
    text = _stats_to_text(stats)

    assert "Model Info" in text
    assert "Total vertices:" in text
    assert "Total faces:" in text
