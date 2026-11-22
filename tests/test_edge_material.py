# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Independent edge paint: picking, undo, geometry edits and file transfer."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.edge_style import edge_vertices
from core.group import Group, copy_group, transformed_mesh
from core.history import (History, MakeGroupCommand, ExplodeGroupCommand,
                           RestampMaterialCommand, SetEdgeMaterialCommand)
from core.materials import Material
from core.purge import used_materials
from core.scene import Scene
from tools.base import ToolContext
from tools.paint import PaintTool


def _scene():
    scene = Scene()
    face = scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)])
    face.attrs["color"] = (0.2, 0.4, 0.8)
    return scene, face, scene.mesh.edges[0]


def test_edge_paint_is_independent_and_undoable():
    scene, face, edge = _scene()
    history = History(scene)
    paint = {"color": [0.9, 0.1, 0.2], "mat": "Red"}
    before = copy.deepcopy(face.attrs)
    history.execute(SetEdgeMaterialCommand([edge], paint))
    assert edge.material == paint and face.attrs == before
    data = edge_vertices(scene.mesh, scene)
    assert np.allclose(data[:2, 3:6], paint["color"])
    assert np.allclose(data[2:, 3:6], face.attrs["color"])
    assert all(e.material is None for e in scene.mesh.edges[1:])  # Display never repaints edges.
    paint["color"][0] = 0.0
    assert edge.material["color"][0] == 0.9
    assert history.undo() and edge.material is None
    assert history.redo() and edge.material["color"][0] == 0.9


def test_unpainted_edges_blend_neighbor_colors_with_independent_paint_priority():
    scene = Scene()
    first = scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)])
    second = scene.mesh.add_face([V(2, 0, 0), V(0, 0, 0), V(0, 2, 0), V(2, 2, 0)])
    first.attrs["color"] = (1, 0, 0)
    second.attrs["color"] = (0, 0, 1)
    shared = next(e for e in scene.mesh.edges if len(e.faces) == 2)

    def color(edge, inherited=None):
        index = scene.mesh.edges.index(edge)
        return edge_vertices(scene.mesh, scene, paint=inherited)[index * 2, 3:6]

    assert np.allclose(color(shared), (0.5, 0, 0.5))
    assert shared.material is None
    shared.material = {"color": (0, 1, 0)}
    assert np.allclose(color(shared), (0, 1, 0))
    shared.material = None
    second.attrs.clear()
    assert np.allclose(color(shared), (1, 0, 0))
    assert np.allclose(color(shared, {"color": (0, 1, 0)}), (0.5, 0.5, 0))
    second.attrs["hidden"] = True
    assert np.allclose(color(shared), (1, 0, 0))
    first.attrs.clear()
    assert np.all(color(shared) == -1)


def test_unpainted_edges_use_texture_average_and_material_registry():
    scene, face, edge = _scene()
    face.attrs = {"texture": {"path": "brick.png"}, "color": (1, 1, 1)}
    assert np.allclose(edge_vertices(scene.mesh, scene, average=lambda _: (0.7, 0.3, 0.1))[:, 3:6],
                       (0.7, 0.3, 0.1))
    scene.materials["Blue"] = Material("Blue", color=(0, 0, 1))
    face.attrs = {"mat": "Blue"}
    assert np.allclose(edge_vertices(scene.mesh, scene)[:, 3:6], (0, 0, 1))
    edge.material = {"mat": "Blue"}
    face.attrs["color"] = (1, 0, 0)
    assert np.allclose(edge_vertices(scene.mesh, scene)[:2, 3:6], (0, 0, 1))


def test_paint_tool_targets_edges_in_by_material_and_samples_or_removes_them(monkeypatch):
    scene, face, edge = _scene()
    scene.display_style.edge_color_mode = "material"
    material = Material("Edge red", color=(0.9, 0.1, 0.2))
    monkeypatch.setattr(PaintTool, "current_is_default", False)
    monkeypatch.setattr(PaintTool, "current_texture", None)
    monkeypatch.setattr(PaintTool, "current_color", material.color)
    monkeypatch.setattr(PaintTool, "current_opacity", None)
    monkeypatch.setattr(PaintTool, "current_material", material)
    monkeypatch.setattr(PaintTool, "sample_armed", False)
    monkeypatch.setattr(PaintTool, "recent", [])

    class Viewport:
        def __init__(self):
            self.scene = scene
            self.history = History(scene)
            self.hover = None
        def pick_face_any(self, x, y):
            return face, None
        def pick_visible_edge(self, x, y):
            return edge
        def set_hover(self, entity):
            self.hover = entity
        def update(self):
            pass

    vp = Viewport()
    ctx = ToolContext(viewport=vp, world=V(), screen=QPointF(),
                      modifiers=Qt.NoModifier, snap=None)
    before = dict(face.attrs)
    tool = PaintTool()
    tool.on_hover(ctx)
    assert vp.hover is edge
    tool.on_click(ctx)
    assert edge.material["mat"] == "Edge red" and face.attrs == before
    assert scene.materials["Edge red"] is material
    assert vp.history.undo() and edge.material is None
    assert vp.history.redo() and edge.material["color"] == list(material.color)
    ctx.modifiers = Qt.AltModifier
    tool.on_click(ctx)
    assert PaintTool.current_material is material
    assert PaintTool.current_color == material.color
    ctx.modifiers = Qt.NoModifier
    PaintTool.current_is_default = True
    tool.on_click(ctx)
    assert edge.material is None and face.attrs == before
    ctx.modifiers = Qt.AltModifier
    tool.on_click(ctx)
    assert PaintTool.current_color == tuple(face.attrs["color"])
    assert PaintTool.current_material is None
    assert not PaintTool.current_is_default


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("lazy", [False, True])
def test_edge_material_roundtrips_json_binary_and_lazy_meshes(tmp_path, monkeypatch, binary, lazy):
    from core import _native
    from core.mesh import DeferredMesh
    from formats import igz

    monkeypatch.setattr(_native, "wanted", lambda: lazy)
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0 if binary else 10**9)
    monkeypatch.setattr(igz, "_BULK_MIN", 1 if binary else 10**9)
    scene, _face, edge = _scene()
    edge.material = {"color": [0.9, 0.1, 0.2], "mat": "Red"}
    group = Group()
    group.mesh.add_edge(V(0, 0, 0), V(1, 0, 0)).material = {"color": [0.1, 0.8, 0.2]}
    scene.groups.append(group)
    path = tmp_path / "edges.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    for mesh in (loaded.mesh, loaded.groups[0].mesh):
        if lazy:
            assert type(mesh) is DeferredMesh
            data = edge_vertices(mesh, loaded)
            assert type(mesh) is DeferredMesh
            assert (data[:, 3] >= 0).any()
    # Saving an unopened lazy mesh must keep its sparse edge material data.
    igz.save_scene(loaded, tmp_path / "resaved.igz")
    again = Scene()
    igz.load_into(again, tmp_path / "resaved.igz")
    assert again.mesh.edges[0].material == edge.material
    assert again.groups[0].mesh.edges[0].material == group.mesh.edges[0].material


def test_split_copy_group_and_explode_keep_edge_paint():
    scene, face, edge = _scene()
    edge.material = {"color": [0.9, 0.1, 0.2]}
    halves = scene.mesh.split_edge(edge, (edge.a + edge.b) * 0.5)
    assert all(half.material == edge.material for half in halves)
    assert halves[0].material is not halves[1].material
    history = History(scene)
    history.execute(MakeGroupCommand(list(scene.mesh.faces), list(scene.mesh.edges)))
    group = scene.groups[0]
    duplicate = copy_group(group, V(3, 0, 0))
    assert sum(bool(e.material) for e in duplicate.mesh.edges) == 2
    matrix = QMatrix4x4()
    matrix.translate(0, 4, 0)
    transformed = transformed_mesh(group.mesh, matrix)
    assert sum(bool(e.material) for e in transformed.edges) == 2
    history.execute(ExplodeGroupCommand(group))
    assert sum(bool(e.material) for e in scene.mesh.edges) == 2


def test_collinear_edges_with_different_paint_are_not_collapsed():
    scene = Scene()
    a = scene.mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    b = scene.mesh.add_edge(V(1, 0, 0), V(2, 0, 0))
    a.material = {"color": [1, 0, 0]}
    b.material = {"color": [0, 1, 0]}
    assert not scene.mesh.collapsible_vertex(a.v1)


def test_clipboard_transfer_and_paste_keep_independent_paint():
    from formats import clip
    from tools.paste import PasteTool

    paint = {"color": [0.8, 0.1, 0.2]}
    copied = {"faces": [], "groups": [], "edges": [(V(), V(2, 0, 0), False, None)],
              "edge_materials": [paint], "ref": V()}
    transferred = clip.decode(clip.encode(copied))
    assert transferred["edge_materials"] == [paint]
    scene = Scene()
    vp = SimpleNamespace(scene=scene, history=History(scene), clipboard=transferred,
                         update=lambda: None)
    assert PasteTool.in_place(vp)
    assert scene.mesh.edges[0].material == paint
    assert vp.history.undo() and not scene.mesh.edges
    assert vp.history.redo() and scene.mesh.edges[0].material == paint


def test_registry_edits_and_purge_recognize_materials_used_only_by_edges():
    scene, _face, edge = _scene()
    old = Material("Old", color=(0.9, 0.1, 0.2))
    scene.materials[old.name] = old
    edge.material = old.face_attrs()
    assert "Old" in used_materials(scene)
    history = History(scene)
    new = Material("New", color=(0.1, 0.8, 0.2))
    history.execute(RestampMaterialCommand("Old", new))
    assert edge.material == new.face_attrs()
    assert history.undo() and edge.material == old.face_attrs()


def test_edge_only_material_is_visible_in_the_materials_panel():
    from views.main_window import MainWindow
    from views.tray import MaterialsPanel

    window = MainWindow()
    try:
        scene = window.viewport.scene
        edge = scene.mesh.add_edge(V(), V(1, 0, 0))
        edge.material = {"color": [0.8, 0.1, 0.2], "mat": "Edge ink"}
        scene.version += 1
        panel = window.findChildren(MaterialsPanel)[0]
        panel.refresh_in_model()
        widgets = [panel._in_model_grid.itemAt(i).widget()
                   for i in range(panel._in_model_grid.count())]
        assert any("Edge ink" in widget.toolTip() for widget in widgets if widget is not None)
    finally:
        window._saved_version = window.viewport.scene.version
        window.close()
