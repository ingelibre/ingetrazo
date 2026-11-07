# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rotate + Ctrl, then "3x" / "/3": a POLAR array (issue #24, @pacaeiro).

Move got arrays with issue #20 and Rotate did not, so after a rotate-copy
the typed number fell through to ``on_value`` and was read as the ANGLE —
his words: «the multiply or divide that we can apply after, are affecting
the rotate+copy angle, instead of quantity». The tool did not even declare
``accepts_array``, so the viewport dropped the "x" and only the digit
reached it.

The classic behaviour, and the one these pin: after a rotate-copy, ``3x``
lays three copies at multiples of the angle (30° → 30/60/90) and ``/3``
three copies dividing it (90° → 30/60/90). Retyping re-lays the array and
the whole thing is ONE undo step.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.base import ToolContext
from tools.rotate import RotateTool


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashed: list = []

    def update(self):
        pass

    def set_hover(self, *_a):
        pass

    def flash_status(self, text, *a, **k):
        self.flashed.append(text)

    def pick_group(self, x, y):
        return None

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None


def _ctx(vp, x, y, z=0.0, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=QVector3D(float(x), float(y),
                                                    float(z)),
                       screen=QPointF(0, 0), modifiers=mods, snap=None)


def _marker(scene, x=2.0, y=0.0):
    """A little square CENTRED on the +X arm at (2, 0): its centroid sits
    exactly on the arm, so the centroid's angle about the origin IS the
    rotation applied to it."""
    V, h = QVector3D, 0.1
    return scene.mesh.add_face([V(x - h, y - h, 0), V(x + h, y - h, 0),
                                V(x + h, y + h, 0), V(x - h, y + h, 0)])


def _angles(scene):
    """Angle (degrees, 0–360) of each face's centroid about the origin."""
    out = []
    for f in scene.mesh.faces:
        n = len(f.vertices)
        cx = sum(v.x() for v in f.vertices) / n
        cy = sum(v.y() for v in f.vertices) / n
        out.append(round(math.degrees(math.atan2(cy, cx)) % 360.0, 3))
    return sorted(out)


def _rotate_copy(vp, tool, deg: float):
    """Centre at the origin, reference on +X, Ctrl, then drop the copy at
    *deg* — the gesture the array window opens after."""
    tool.on_click(_ctx(vp, 0, 0))                     # centre
    tool.on_click(_ctx(vp, 2, 0))                     # reference arm
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)    # Ctrl: copy
    r = 2.0
    tool.on_click(_ctx(vp, r * math.cos(math.radians(deg)),
                       r * math.sin(math.radians(deg))))


def test_the_tool_declares_arrays_so_the_value_box_keeps_the_x():
    """The viewport only buffers the "x" of «3x» for tools that declare
    ``accepts_array`` (views/viewport.py). Without it the digit reached
    ``on_value`` alone and became an angle — the whole of #24."""
    assert getattr(RotateTool, "accepts_array", False) is True
    assert callable(getattr(RotateTool, "on_array_value", None))


def test_external_array_lays_copies_at_multiples_of_the_angle():
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, 30.0)
    assert _angles(scene) == [0.0, 30.0]

    assert tool.on_array_value(vp, 3, "x")            # «3x»
    assert _angles(scene) == [0.0, 30.0, 60.0, 90.0]


def test_internal_array_divides_the_angle():
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, 90.0)
    assert _angles(scene) == [0.0, 90.0]

    assert tool.on_array_value(vp, 3, "/")            # «/3»
    assert _angles(scene) == [0.0, 30.0, 60.0, 90.0]


def test_retyping_re_lays_the_array_and_it_is_one_undo_step():
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, 30.0)
    tool.on_array_value(vp, 3, "x")
    assert len(_angles(scene)) == 4

    tool.on_array_value(vp, 5, "x")                   # retype: 5 copies
    assert _angles(scene) == [0.0, 30.0, 60.0, 90.0, 120.0, 150.0]

    vp.history.undo()                                 # ONE step, back to bare
    assert _angles(scene) == [0.0]


def test_the_angle_keeps_its_side():
    """A copy laid clockwise arrays clockwise."""
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, -30.0)
    assert tool.on_array_value(vp, 2, "x")
    assert _angles(scene) == [0.0, 300.0, 330.0]      # −60 and −30


def test_a_plain_rotation_offers_no_array():
    """Without Ctrl nothing was copied, so there is nothing to repeat —
    the same rule Move follows."""
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 2, 0))
    tool.on_click(_ctx(vp, 0, 2))                     # a plain 90° turn
    assert _angles(scene) == [90.0]
    assert tool.on_array_value(vp, 3, "x") is False
    assert _angles(scene) == [90.0]


def test_the_array_window_closes_when_something_else_is_undone():
    """The window only stands while the copy is still the top of the undo
    stack — Move's rule, and what keeps a stale array from re-firing."""
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, 30.0)
    vp.history.undo()
    assert tool.on_array_value(vp, 3, "x") is False


def test_array_pending_says_when_x5_would_fan_the_copy():
    """«x5» (#542): the viewport lets a bare X open the value box only while
    ``array_pending`` is true — after a rotate-COPY, never after a plain
    turn, and no longer once the copy is not the top of the undo stack."""
    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    _rotate_copy(vp, tool, 30.0)
    assert tool.array_pending(vp) is True
    vp.history.undo()
    assert tool.array_pending(vp) is False

    scene = Scene()
    scene.selection = [_marker(scene)]
    vp = _Vp(scene)
    tool = RotateTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 2, 0))
    tool.on_click(_ctx(vp, 0, 2))                     # a plain 90° turn
    assert tool.array_pending(vp) is False
