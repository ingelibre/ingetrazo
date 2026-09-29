# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed dimensions must create geometry without a second hover or click."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtTest import QTest

from tools.base import ToolContext
from tools.circle import CircleTool
from tools.rectangle import RectangleTool
from views.viewport import Viewport


@pytest.mark.parametrize("text,width,height", [
    ("2.5,1.25", 2.5, 1.25),
    ("100mm,50mm", .1, .05),
    ("2,5;1,25", 2.5, 1.25),
])
def test_rectangle_first_click_then_keyboard(text, width, height):
    vp = Viewport()
    tool = RectangleTool()
    vp.active_tool = tool
    tool.on_activate(vp)
    # No hover: for example a tablet tap, or typing as soon as clicked.
    tool.on_click(ToolContext(vp, QVector3D(), QPointF(), Qt.NoModifier, None))
    QTest.keyClicks(vp, text)
    assert vp._value_buffer == text
    QTest.keyClick(vp, Qt.Key_Return)
    assert len(vp.scene.faces) == 1
    points = vp.scene.faces[0].vertices
    assert max(p.x() for p in points) == pytest.approx(width)
    assert max(p.y() for p in points) == pytest.approx(height)
    assert tool.start_point is None
    assert vp._value_buffer == ""
    vp.history.undo()
    assert not vp.scene.faces


def test_circle_first_click_then_radius():
    vp = Viewport()
    tool = CircleTool()
    vp.active_tool = tool
    tool.on_activate(vp)
    center = QVector3D(1, 2, 0)
    tool.on_click(ToolContext(vp, center, QPointF(), Qt.NoModifier, None))
    QTest.keyClicks(vp, "25mm")
    QTest.keyClick(vp, Qt.Key_Enter)
    assert len(vp.scene.faces) == 1
    for point in vp.scene.faces[0].vertices:
        assert (point - center).length() == pytest.approx(.025, abs=1e-6)
    vp.history.undo()
    assert not vp.scene.faces


def test_invalid_dimensions_remain_editable():
    vp = Viewport()
    tool = RectangleTool()
    vp.active_tool = tool
    tool.on_click(ToolContext(vp, QVector3D(), QPointF(), Qt.NoModifier, None))
    QTest.keyClicks(vp, "2,0")
    QTest.keyClick(vp, Qt.Key_Return)
    assert not vp.scene.faces
    assert vp._value_buffer == "2,0"
    QTest.keyClick(vp, Qt.Key_Backspace)
    QTest.keyClicks(vp, "1")
    QTest.keyClick(vp, Qt.Key_Return)
    assert len(vp.scene.faces) == 1
