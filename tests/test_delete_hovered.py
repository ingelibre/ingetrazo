# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Delete what is under the cursor: hover an edge or a face (the blue
highlight) and press Delete — no click needed. A selection still wins;
the hover grows like a click would (a whole drawn curve, a whole smooth
surface), and it is one undoable step."""
from __future__ import annotations

from PySide6.QtCore import Qt

from core.history import History
from core.scene import Scene
from tests.test_fuzz_engine import V, _draw_rect
from tools.select import SelectTool, delete_selection_or_hover


class _StubViewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self._hover_entity = None

    def set_hover(self, entity):
        self._hover_entity = entity

    def update(self):
        pass


def _square():
    scene = Scene()
    vp = _StubViewport(scene)
    _draw_rect(scene, vp.history, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    return scene, vp


def test_delete_erases_the_hovered_face_without_a_click():
    scene, vp = _square()
    face = scene.mesh.faces[0]
    n_edges = len(scene.mesh.edges)
    vp._hover_entity = face
    assert SelectTool().on_key(vp, Qt.Key_Delete, Qt.NoModifier) is True
    assert face not in scene.mesh.faces
    assert len(scene.mesh.edges) == n_edges          # the face alone goes
    assert vp._hover_entity is None                  # no dangling highlight
    vp.history.undo()                                # one step
    assert len(scene.mesh.faces) == 1


def test_delete_erases_the_hovered_edge_and_its_face():
    scene, vp = _square()
    edge = scene.mesh.edges[0]
    vp._hover_entity = edge
    assert delete_selection_or_hover(vp) is True
    assert edge not in scene.mesh.edges
    assert scene.mesh.faces == []                    # SketchUp: face follows


def test_a_selection_wins_over_the_hover():
    scene, vp = _square()
    face = scene.mesh.faces[0]
    edge = scene.mesh.edges[0]
    scene.selection.add(face)
    vp._hover_entity = edge                          # cursor elsewhere
    assert delete_selection_or_hover(vp) is True
    assert face not in scene.mesh.faces
    assert edge in scene.mesh.edges                  # hover untouched


def test_nothing_hovered_nothing_selected_is_a_no_op():
    scene, vp = _square()
    assert delete_selection_or_hover(vp) is False
    assert len(scene.mesh.faces) == 1
    assert SelectTool().on_key(vp, Qt.Key_Delete, Qt.NoModifier) is True


def test_other_tools_wait_while_an_operation_holds_geometry():
    from views.viewport import Viewport

    class _Idle:
        pass

    class _Pushing:
        dragging = True

    class _Offsetting:
        base_face = object()

    assert Viewport._tool_busy_for_delete(_Idle()) is False
    assert Viewport._tool_busy_for_delete(_Pushing()) is True
    assert Viewport._tool_busy_for_delete(_Offsetting()) is True
