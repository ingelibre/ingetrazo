# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Edge style persistence, UI edits and camera-independent render data."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

from core.edge_style import AXIS_COLORS, axis_color, edge_vertices, needs_edge_renderer
from core.layers import Layer
from core.scene import Scene
from core.style import Style

V = QVector3D


def test_edge_settings_survive_copy_library_scene_and_saved_view(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from core import style as library
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    style = Style(name="Ink", profile_width=5, depth_cue=True, depth_cue_width=6,
                  extensions=True, extension_length=8, endpoints=True,
                  endpoint_length=7, dashes=False, edge_color_mode="axis")
    library.save_user_style(style)
    assert library.style_by_name("Ink").to_dict() == style.to_dict()
    assert style.copy().to_dict() == style.to_dict()
    scene = Scene()
    scene.mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    scene.display_style = style
    view = SavedView.capture("Ink view", scene, OrbitCamera())
    igz.save_scene(scene, tmp_path / "ink.igz")
    loaded = Scene()
    igz.load_into(loaded, tmp_path / "ink.igz")
    assert loaded.display_style.to_dict() == style.to_dict()
    loaded.display_style = Style()
    view.apply(loaded, OrbitCamera())
    assert loaded.display_style.to_dict() == style.to_dict()


def test_old_documents_keep_defaults_and_malformed_sizes_are_bounded():
    old = Style.from_dict({"name": "Old"})
    assert old.profile_width == 1 and old.dashes and old.edge_color_mode == "same"
    assert not old.depth_cue and not old.extensions and not old.endpoints
    assert "profile_width" not in Style().to_dict()
    odd = Style.from_dict({"profile_width": -100, "depth_cue_width": 1000,
                           "extension_length": "NaN", "endpoint_length": [],
                           "edge_color_mode": "unknown"})
    assert odd.profile_width == 1 and odd.depth_cue_width == 20
    assert odd.extension_length == 3 and odd.endpoint_length == 3
    assert odd.edge_color_mode == "same"


def test_default_fast_path_and_layer_dash_switch():
    scene, style = Scene(), Style()
    assert not needs_edge_renderer(style, scene)
    scene.layers.append(Layer("Dashed", linetype="dashed"))
    assert needs_edge_renderer(style, scene)
    style.dashes = False
    assert not needs_edge_renderer(style, scene)
    style.profiles = True
    style.profile_width = 5
    assert needs_edge_renderer(style, scene)


def test_axis_colors_follow_rotated_drawing_axes_and_keep_diagonal_fallback():
    fallback = (0.1, 0.2, 0.3)
    assert axis_color((-4, 0, 0), fallback) == AXIS_COLORS[0]
    assert axis_color((0, 0, 2), fallback) == AXIS_COLORS[2]
    assert axis_color((1, 1, 0), fallback) == fallback
    assert axis_color((0, 0, 0), fallback) == fallback
    basis = ((0, 1, 0), (-1, 0, 0), (0, 0, 1))
    assert axis_color((0, 2, 0), fallback, basis) == AXIS_COLORS[0]


def test_render_data_keeps_materials_normals_and_inherited_tag_patterns():
    scene = Scene()
    face = scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)])
    face.attrs["color"] = (0.7, 0.2, 0.1)
    for edge in scene.mesh.edges:
        edge.material = {"color": (0.7, 0.2, 0.1)}
    scene.layers.append(Layer("Outline", linetype="dashdot"))
    data = edge_vertices(scene.mesh, scene, inherited_layer="Outline")
    assert len(data) == 8
    assert np.allclose(data[:, 3:6], (0.7, 0.2, 0.1))
    assert np.allclose(np.linalg.norm(data[:, 6:9], axis=1), 1)
    assert np.all(data[:, 13] == 1)  # A face boundary is a profile.
    assert np.all(data[:, 14] == 4)
    assert np.allclose(data[:, 15:19], (24, 6, 2, 6))
    assert all(edge.layer is None for edge in scene.mesh.edges)
    assert face.attrs["color"] == (0.7, 0.2, 0.1)  # Display never repaints geometry.


def test_hidden_and_degenerate_edges_are_not_displayed_and_unpainted_edges_fall_back():
    scene = Scene()
    scene.mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    hidden = scene.mesh.add_edge(V(0, 0, 1), V(1, 0, 1))
    hidden.hidden = True
    data = edge_vertices(scene.mesh, scene)
    assert len(data) == 2
    assert np.all(data[:, 3:6] == -1)
    inherited = edge_vertices(scene.mesh, scene, paint={"color": (0.1, 0.7, 0.2)})
    assert np.allclose(inherited[:, 3:6], (0.1, 0.7, 0.2))


def test_deferred_meshes_keep_lazy_topology_and_match_built_render_data(tmp_path, monkeypatch):
    from core import _native
    from core.group import Group
    from core.mesh import DeferredMesh
    from formats import igz

    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)
    scene = Scene()
    group = Group()
    face = group.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)])
    face.attrs["color"] = (0.7, 0.2, 0.1)
    group.mesh.edges[0].material = {"color": (0.8, 0.1, 0.2)}
    scene.groups.append(group)
    path = tmp_path / "lazy.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    mesh = loaded.groups[0].mesh
    assert type(mesh) is DeferredMesh
    lazy = edge_vertices(mesh, loaded)
    assert type(mesh) is DeferredMesh
    mesh.faces  # Materialize to compare the exact same mesh's eager path.
    assert np.allclose(lazy, edge_vertices(mesh, loaded))


def test_edge_controls_apply_live_and_disabled_values_survive_refresh(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from core import style as library
    from views.tray import StylesPanel

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))

    class Viewport:
        scene = Scene()
        def update(self):
            pass

    class Window:
        viewport = Viewport()
        def _sync_style_menu(self):
            panel.refresh()

    window = Window()
    panel = StylesPanel(window)
    style = window.viewport.scene.display_style
    assert not panel._depth_cue_width.isEnabled()
    assert not panel._extension_length.isEnabled()
    panel._profile_width.setValue(5)
    panel._depth_cue.setChecked(True)
    panel._depth_cue_width.setValue(7)
    panel._extensions.setChecked(True)
    panel._extension_length.setValue(12)
    panel._endpoints.setChecked(True)
    panel._endpoint_length.setValue(8)
    panel._dashes.setChecked(False)
    panel._edge_color_mode.setCurrentIndex(panel._edge_color_mode.findData("material"))
    assert style.profile_width == 5 and style.depth_cue_width == 7
    assert style.depth_cue and style.extensions and style.endpoints
    assert style.extension_length == 12 and style.endpoint_length == 8
    assert not style.dashes and style.edge_color_mode == "material"
    panel._extensions.setChecked(False)
    panel.refresh()
    assert style.extension_length == 12
    assert not panel._extension_length.isEnabled()
    panel._extensions.setChecked(True)
    assert panel._extension_length.value() == 12
    panel.close()
