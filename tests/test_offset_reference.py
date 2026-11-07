# SPDX-License-Identifier: GPL-3.0-or-later
"""Offset shows its source edge and clicked distance anchor before committing."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QVector3D as V

from core.history import History
from core.scene import Scene
from tools.base import ToolContext
from tools.offset import OffsetTool


class Viewport:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self.face = self.scene.mesh.add_face(
            [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)])
        self.hidden = False
        self.parallel = False

    def update(self):
        pass

    def set_hover(self, entity):
        pass

    def flash_status(self, *args, **kwargs):
        pass

    def pick_face(self, sx, sy):
        return self.face if 40 <= sx <= 440 and 40 <= sy <= 440 else None

    def pick_edge(self, sx, sy):
        return None

    def _pixel_to_ray(self, sx, sy):
        direction = V(1, 0, 0) if self.parallel else V(0, 0, -1)
        return V((sx - 40) / 100, (440 - sy) / 100, 10), direction

    def _world_to_pixel(self, point):
        return 40 + point.x() * 100, 440 - point.y() * 100

    def _segment_to_pixels(self, a, b):
        return self._world_to_pixel(a), self._world_to_pixel(b)

    def _occluded_on_screen(self, point):
        return self.hidden


@pytest.fixture
def offset():
    return Viewport(), OffsetTool()


def context(vp, x, y):
    point = V(x, y, 0)
    return ToolContext(vp, point, QPointF(*vp._world_to_pixel(point)), Qt.NoModifier, None)


def begin(vp, tool):
    ctx = context(vp, 2, .1)
    tool.on_hover(ctx)
    tool.on_click(ctx)


def render(vp, tool):
    image = QImage(480, 480, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        overlay = getattr(tool, "draw_overlay", None)
        if overlay is not None:
            overlay(vp, painter)
    finally:
        painter.end()
    return image


def test_source_square_is_visible_before_the_first_click(offset):
    vp, tool = offset
    tool.on_hover(context(vp, 2, .1))
    image = render(vp, tool)
    marker = image.pixelColor(240, 440)
    assert marker.red() > 140 and marker.green() < 80 and marker.blue() < 100
    edge = image.pixelColor(140, 440)
    assert edge.blue() > 150 and edge.red() < 80


def test_idle_reference_follows_the_nearest_boundary(offset):
    vp, tool = offset
    tool.on_hover(context(vp, 2, .1))
    assert tool._offset_reference[2] == V(2, 0, 0)
    tool.on_hover(context(vp, .1, 2))
    assert tool._offset_reference[2] == V(0, 2, 0)


def test_first_click_fixes_the_visible_start_and_preserves_distance_math(offset):
    vp, tool = offset
    begin(vp, tool)
    assert tool._ref_point == V(0, 0, 0)
    for x, y in [(2, .25), (3, .5), (1, -.5)]:
        tool.on_hover(context(vp, x, y))
        assert tool._offset_reference[2] == V(2, 0, 0)
        assert tool.distance == pytest.approx(y)


def test_distance_label_is_beside_the_clicked_reference(offset):
    vp, tool = offset
    begin(vp, tool)
    tool.on_hover(context(vp, 3, .5))
    assert tool.value_label()[1] == V(2, .25, 0)
    points = {tuple(p.toTuple()) for line in tool.rubber_band_lines() for p in line}
    assert points == {(.5, .5, 0), (3.5, .5, 0), (3.5, 3.5, 0), (.5, 3.5, 0)}


def test_drag_adds_a_distance_guide_without_moving_the_source_square(offset):
    vp, tool = offset
    begin(vp, tool)
    tool.on_hover(context(vp, 3, .5))
    image = render(vp, tool)
    marker = image.pixelColor(240, 440)
    assert marker.red() > 140 and marker.green() < 80
    assert any(image.pixelColor(240, y).alpha() for y in range(395, 425))
    # Cursor moved sideways: the guide still measures from the first click.
    assert all(image.pixelColor(340, y).alpha() == 0 for y in range(395, 425))


@pytest.mark.parametrize("action", ["cancel", "deactivate", "empty"])
def test_transient_reference_clears_without_editing_geometry(offset, action):
    vp, tool = offset
    tool.on_hover(context(vp, 2, .1))
    if action == "cancel":
        tool.on_click(context(vp, 2, .1))
        tool.on_cancel(vp)
    elif action == "deactivate":
        tool.on_deactivate(vp)
    else:
        tool.on_hover(context(vp, 10, 10))
    assert tool._offset_reference is None
    assert len(vp.scene.mesh.faces) == 1 and not vp.history.undo_stack
    assert render(vp, tool).pixelColor(240, 440).alpha() == 0


def test_hidden_source_does_not_paint_a_marker(offset):
    vp, tool = offset
    tool.on_hover(context(vp, 2, .1))
    vp.hidden = True
    image = render(vp, tool)
    assert image.pixelColor(240, 440).alpha() == 0
    assert image.pixelColor(140, 440).alpha() == 0


def test_parallel_cursor_ray_clears_the_idle_marker(offset):
    vp, tool = offset
    tool.on_hover(context(vp, 2, .1))
    vp.parallel = True
    tool.on_hover(context(vp, 2, .1))
    assert tool._offset_reference is None


def test_typed_commit_and_retype_remain_one_undo_step(offset):
    vp, tool = offset
    begin(vp, tool)
    assert tool.on_value(vp, 1.0)
    assert tool._offset_reference is None
    assert len(vp.history.undo_stack) == 1
    assert next(f for f in vp.scene.mesh.faces if not f.holes).area() == pytest.approx(4)
    assert vp.history.undo() and len(vp.scene.mesh.faces) == 1
    assert vp.history.redo()
    assert tool.on_value(vp, .5)
    assert len(vp.history.undo_stack) == 1
    assert next(f for f in vp.scene.mesh.faces if not f.holes).area() == pytest.approx(9)
    assert tool._offset_reference is None


def test_preselected_connected_edges_share_the_same_reference(offset):
    vp, tool = offset
    vp.scene.selection = set(vp.scene.mesh.edges[:2])
    tool.on_activate(vp)
    tool.on_hover(context(vp, 2, .1))
    assert tool._armed and tool._offset_reference[2] == V(2, 0, 0)
    tool.on_click(context(vp, 2, .1))
    assert tool.dragging and tool._chain
    tool.on_cancel(vp)
    assert tool._offset_reference is None
