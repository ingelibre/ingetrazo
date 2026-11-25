# SPDX-License-Identifier: GPL-3.0-or-later
"""Dimension tagged curves from segment interiors through the ordinary tool."""
import math

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMenu

from core.history import History
from core.scene import Scene
from core.snap import SnapResult
from formats.igz import load_into, save_scene
from tools.base import ToolContext
from tools.dimension import DimensionTool
from views.main_window import MainWindow


class ViewportStub:
    def __init__(self, scene, edge):
        self.scene = scene
        self.history = History(scene)
        self.edge = edge

    def pick_visible_edge(self, *_):
        return self.edge

    def _ray_hit_plane(self, _, plane):
        center, _ = plane
        return center + QVector3D(0, 3, 0)

    def update(self):
        pass


@pytest.mark.parametrize("closed", [True, False])
def test_segment_hover_place_toggle_and_save(tmp_path, monkeypatch, closed):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    scene = Scene()
    mesh = scene.mesh
    # A circle or semicircle in the YZ plane, with a true radius of two.
    angles = [math.pi * index / 4 for index in range(8 if closed else 5)]
    center = QVector3D(7, 4, 3)
    points = [center + QVector3D(0, 2 * math.cos(a), 2 * math.sin(a))
              for a in angles]
    pairs = list(zip(points, points[1:] + (points[:1] if closed else [])))
    edges = [mesh.add_edge(a, b) for a, b in pairs]
    mesh.tag_curve(points, closed)
    vp = ViewportStub(scene, edges[0])
    tool = DimensionTool()
    highlight = getattr(tool, "curve_highlight_lines", tuple)
    interior = (edges[0].a + edges[0].b) * 0.5
    hover = ToolContext(vp, interior, QPointF(50, 50), Qt.NoModifier,
                        SnapResult(interior, "midpoint", (0, 0, 0)))

    endpoint = ToolContext(vp, edges[0].a, QPointF(50, 50), Qt.NoModifier,
                           SnapResult(edges[0].a, "endpoint", (0, 0, 0)))
    tool.on_hover(endpoint)
    assert not highlight()
    tool.on_hover(hover)
    assert len(highlight()) == len(edges)
    tool.on_click(hover)
    assert not scene.dimensions and tool.value_label()[0].startswith("⌀")
    tool.on_click(hover)
    assert not highlight()
    dim, = scene.dimensions
    assert dim.kind == "diameter" and dim.value() == pytest.approx(4)
    assert (dim.midpoint() - center).length() < 1e-5

    window = MainWindow(defer_extensions=True)
    window.viewport.scene = scene
    # The menu callback uses the real window's history.
    window.viewport.history = vp.history
    scene.selection.add(dim)

    def choose_radius_and_outside(menu, _):
        dimension_type = next(action.menu() for action in menu.actions()
                              if action.text() == "Dimension type")
        diameter, radius = dimension_type.actions()
        assert diameter.isChecked() and not radius.isChecked()
        positions = next(action.menu() for action in menu.actions()
                         if action.text() == "Text position")
        centered, outside = positions.actions()
        assert centered.isChecked() and not outside.isChecked()
        assert not dim.label_outside and dim.label_point() == dim.midpoint()
        outside.trigger()
        assert dim.kind == "diameter" and dim.label_outside
        radius.trigger()

    class TestMenu(QMenu):
        def exec(self, pos):
            choose_radius_and_outside(self, pos)

    monkeypatch.setattr("views.main_window.QMenu", TestMenu)
    window.show_viewport_context_menu(QPoint())
    assert dim.kind == "radius" and dim.value() == pytest.approx(2)
    assert dim.display_text("2 m") == "R2 m"
    label = dim.label_point()
    assert dim.label_outside and (label - center).length() == pytest.approx(2.5)
    assert dim.extension_segments(*dim.line_points()) == ((dim.b, label),)
    assert vp.history.undo() and dim.kind == "diameter" and dim.label_outside
    assert vp.history.undo() and not dim.label_outside
    assert dim.label_point() == dim.midpoint()
    assert vp.history.redo() and dim.label_outside
    assert vp.history.redo() and dim.kind == "radius"

    target = tmp_path / "circular.igz"
    save_scene(scene, target)
    restored = Scene()
    load_into(restored, target)
    saved, = restored.dimensions
    assert saved.kind == "radius" and saved.value() == pytest.approx(2)
    assert saved.line_points()[0] == dim.line_points()[0]
    assert saved.label_outside and saved.label_point() == label
