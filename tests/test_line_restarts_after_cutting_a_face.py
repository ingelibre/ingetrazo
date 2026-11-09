# SPDX-License-Identifier: GPL-3.0-or-later
"""The Line tool starts fresh once a segment makes a face (#496).

Closing a loop already ended the chain. A segment that cuts an existing face
in two makes a face too, yet the next click still left from its end point.
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.scene import Scene
from tools.line import LineTool


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass


def _scene_with_square():
    scene = Scene()
    vp = _Vp(scene)
    corners = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)]
    vp.history.execute(build_add_edges(
        scene, [(corners[i], corners[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(corners)]))
    return vp


def _click(tool, vp, point, kind="on_edge"):
    tool.on_click(SimpleNamespace(
        viewport=vp, world=V(*point), snap=SimpleNamespace(kind=kind)))


def test_a_click_that_cuts_a_face_ends_the_chain():
    vp = _scene_with_square()
    tool = LineTool()
    _click(tool, vp, (2, 0, 0))
    _click(tool, vp, (2, 4, 0))
    assert len(vp.scene.faces) == 2
    assert tool.start_point is None
    assert tool.chain_vertices == []


def test_a_typed_segment_that_cuts_a_face_ends_the_chain():
    vp = _scene_with_square()
    tool = LineTool()
    _click(tool, vp, (2, 0, 0))
    tool.hover_point = V(2, 4, 0)
    assert tool.on_value(vp, (0.0, 4.0, 0.0)) is True
    assert len(vp.scene.faces) == 2
    assert tool.start_point is None


def test_a_segment_that_makes_no_face_keeps_the_chain():
    vp = _scene_with_square()
    tool = LineTool()
    _click(tool, vp, (2, 0, 0))
    _click(tool, vp, (2, 2, 0))                 # ends inside the face
    assert len(vp.scene.faces) == 1
    assert (tool.start_point - V(2, 2, 0)).length() < 1e-9
    assert len(tool.chain_vertices) == 2
