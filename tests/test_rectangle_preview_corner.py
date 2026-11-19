# SPDX-License-Identifier: GPL-3.0-or-later
"""The idle rectangle preview marks the next click as a corner."""
from types import SimpleNamespace
from PySide6.QtGui import QVector3D as V
from tools.rectangle import RectangleTool


def _preview(center=False):
    tool = RectangleTool()
    tool.hover_point = V(2, 3, 1)
    tool.hover_plane = (tool.hover_point, V(0,0,1))
    tool._viewport = SimpleNamespace(_world_to_pixel=lambda p:(p.x()*100,p.y()*100))
    tool._from_center = center
    return tool, tool._cursor_preview()


def test_first_click_is_a_preview_corner():
    tool, segments = _preview()
    assert len(segments) == 4
    corners = [a for a,_ in segments]
    assert any((p-tool.hover_point).length()<1e-6 for p in corners)
    assert all(abs(p.z()-1)<1e-6 for p in corners)


def test_center_mode_keeps_the_first_click_at_the_center():
    tool, segments = _preview(True)
    center = sum((a for a,_ in segments), V())*.25
    assert (center-tool.hover_point).length()<1e-6
    assert not any((a-tool.hover_point).length()<1e-6 for a,_ in segments)


def test_rectangle_cursor_uses_the_pencil_without_a_second_rectangle_badge():
    from views.icons import tool_cursor
    rectangle, pencil = tool_cursor('rectangle'), tool_cursor('line')
    assert rectangle.hotSpot() == pencil.hotSpot()
    assert rectangle.pixmap().toImage() == pencil.pixmap().toImage()
