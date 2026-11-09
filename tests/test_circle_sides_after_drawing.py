# SPDX-License-Identifier: GPL-3.0-or-later
"""«Ns» right after a circle or polygon rebuilds it in place (#305).

The Arc already did; the Circle only set the sides of the NEXT circle, so a
24-sided circle that should have been 48 had to be erased and drawn again.
The shape keeps its centre, radius and the vertex toward the cursor, in one
undo step, and the count stays for the next ones."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from tools.base import ToolContext
from tools.circle import CircleTool, PolygonTool


@pytest.fixture(scope="module")
def viewport():
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _ctx(world):
    return ToolContext(viewport=None, world=world, screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _draw(vp, tool, center, rim):
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    vp.history.redo_stack.clear()
    tool.on_activate(vp)
    for p in (center, rim):
        c = _ctx(p)
        c.viewport = vp
        tool.on_click(c)


def _ring(mesh):
    return sorted(len(f.vertices) for f in mesh.faces)


@pytest.mark.parametrize("cls,before", [(CircleTool, 24), (PolygonTool, 6)])
def test_ns_right_after_rebuilds_the_shape(viewport, cls, before):
    tool = cls()
    _draw(viewport, tool, V(1, 1, 0), V(3, 1, 0))
    mesh = viewport.scene.mesh
    assert _ring(mesh) == [before]
    steps = len(viewport.history.undo_stack)
    assert tool.on_segments_value(viewport, 12)
    assert _ring(mesh) == [12]
    assert len(viewport.history.undo_stack) == steps      # one step, replaced
    radii = {round((v.position - V(1, 1, 0)).length(), 6) for v in mesh.vertices}
    assert radii == {2.0}
    assert mesh.vertex_at(V(3, 1, 0)) is not None         # same first vertex
    assert tool.sides == 12                               # kept for the next
    viewport.history.undo()
    assert mesh.faces == []


def test_ns_after_something_else_only_sets_the_next(viewport):
    tool = CircleTool()
    _draw(viewport, tool, V(1, 1, 0), V(3, 1, 0))
    viewport.history.undo()                     # the circle is gone
    assert tool.on_segments_value(viewport, 12)
    assert viewport.scene.mesh.faces == []      # nothing came back
