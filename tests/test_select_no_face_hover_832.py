# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Select does not mark the face under the cursor (#832, @GitHuhl).

As in SketchUp, the Select tool shows nothing over a face until it is
clicked; edges still light up (a thin line is hard to hit), and Delete
over a lit edge still erases it. With no face lit, Delete with nothing
selected never erases a face the user could not see. The other tools
that act on faces (Paint, Push/Pull, Offset...) keep their marking."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tests.test_fuzz_engine import V, _draw_rect
from tools.base import ToolContext
from tools.select import SelectTool, delete_selection_or_hover


class _StubViewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self._hover_entity = None

    def set_hover(self, entity, placement=None):
        self._hover_entity = entity

    def update(self):
        pass


def _hover_over(entity):
    scene = Scene()
    vp = _StubViewport(scene)
    _draw_rect(scene, vp.history, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    target = entity(scene)
    tool = SelectTool()
    tool._pick = lambda _vp, _x, _y: target
    tool.on_hover(ToolContext(viewport=vp, world=QVector3D(),
                              screen=QPointF(10, 10),
                              modifiers=Qt.NoModifier, snap=None))
    return scene, vp, target


def test_a_face_under_the_cursor_is_not_marked():
    scene, vp, face = _hover_over(lambda s: s.mesh.faces[0])
    assert vp._hover_entity is None
    assert delete_selection_or_hover(vp) is False      # nothing unseen goes
    assert face in scene.mesh.faces


def test_an_edge_under_the_cursor_still_lights_and_deletes():
    scene, vp, edge = _hover_over(lambda s: s.mesh.edges[0])
    assert vp._hover_entity is edge
    assert delete_selection_or_hover(vp) is True
    assert edge not in scene.mesh.edges
