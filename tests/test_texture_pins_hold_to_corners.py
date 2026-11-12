# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Position Texture: a pin brought near a corner of the face, or the middle
of one of its edges, lands exactly there.

A YouTube review of 0.6.1 (#1308): «the texture map placement anchors don't
snap to vertices or corners». The pins followed the cursor on the face's
plane and nothing else, so lining a tile up with the face's corner was done
by eye. Now a pin dragged — or lifted and set down — within a few pixels
of a corner or an edge middle holds to it, the green one without its 15°
rounding (it goes where it is held); Ctrl lets go, as it frees the
rotation; and away from them the pins move as before."""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.edits import build_add_edges
from tools.base import ToolContext
from tools.texture_position import (PIN_MOVE, PIN_SCALE_ROTATE,
                                    PIN_SCALE_SHEAR, TexturePositionTool)


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _square(vp):
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    vp.history.redo_stack.clear()
    sq = [QVector3D(0, 0, 0), QVector3D(2, 0, 0),
          QVector3D(2, 2, 0), QVector3D(0, 2, 0)]
    vp.history.execute(build_add_edges(
        vp.scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)]))
    face = vp.scene.mesh.faces[0]
    if face.normal().z() < 0:
        face.loop.reverse()
    face.attrs["texture"] = {"path": "brick.png", "sw": 0.5, "sh": 0.5}
    vp.camera.target = QVector3D(1, 1, 0)
    vp.camera.distance = 6.0
    vp.camera.pitch = math.radians(-80.0)
    tool = TexturePositionTool()
    vp.set_active_tool(tool)
    assert tool.begin(vp, face, QVector3D(0.7, 0.3, 0))
    return tool


def _ctx(vp, world, modifiers=Qt.NoModifier):
    px = vp._world_to_pixel(QVector3D(world))
    return ToolContext(viewport=vp, world=QVector3D(world),
                       screen=QPointF(*px), modifiers=modifiers, snap=None)


def _metres(vp, px):
    """``px`` screen pixels, in metres, along X at the face."""
    a = vp._world_to_pixel(QVector3D(1, 1, 0))
    b = vp._world_to_pixel(QVector3D(2, 1, 0))
    return px / math.hypot(b[0] - a[0], b[1] - a[1])


def _drag_pin(vp, tool, pin, to, modifiers=Qt.NoModifier):
    tool.on_click(_ctx(vp, tool.pins()[pin]))
    tool.on_hover(_ctx(vp, to, modifiers))
    held = tool._held
    tool.on_release(vp)
    return held


def _at(p, q, tol=1e-6):
    return (p - q).length() <= tol


def test_the_red_pin_dragged_near_a_corner_lands_on_it(viewport):
    tool = _square(viewport)
    corner = QVector3D(0, 0, 0)
    near = corner + QVector3D(_metres(viewport, 4), _metres(viewport, 3), 0)
    held = _drag_pin(viewport, tool, PIN_MOVE, near)
    assert held is not None and held[1] == "corner"
    assert _at(tool.pins()[PIN_MOVE], corner), tool.pins()[PIN_MOVE]


def test_the_green_pin_lands_on_a_corner_unrounded(viewport):
    tool = _square(viewport)
    # Red at (0.5, 0): the corner (0, 2) is at 104° — no 15° step.
    corner = QVector3D(0, 2, 0)
    near = corner + QVector3D(_metres(viewport, -3), _metres(viewport, 4), 0)
    held = _drag_pin(viewport, tool, PIN_SCALE_ROTATE, near)
    assert held is not None and held[1] == "corner"
    assert _at(tool.pins()[PIN_SCALE_ROTATE], corner, 1e-5), \
        tool.pins()[PIN_SCALE_ROTATE]


def test_the_blue_pin_holds_to_an_edge_middle(viewport):
    tool = _square(viewport)
    middle = QVector3D(0, 1, 0)
    near = middle + QVector3D(_metres(viewport, 3), _metres(viewport, -4), 0)
    held = _drag_pin(viewport, tool, PIN_SCALE_SHEAR, near)
    assert held is not None and held[1] == "middle"
    assert _at(tool.pins()[PIN_SCALE_SHEAR], middle, 1e-5)


def test_a_lifted_pin_sets_down_on_the_corner_it_is_brought_to(viewport):
    tool = _square(viewport)
    before = tool.map.copy()
    tool.on_click(_ctx(viewport, tool.pins()[PIN_MOVE]))
    tool.on_release(viewport)                      # a click: lifted
    assert tool._lifted == PIN_MOVE
    corner = QVector3D(2, 2, 0)
    near = corner - QVector3D(_metres(viewport, 4), _metres(viewport, 4), 0)
    tool.on_hover(_ctx(viewport, near))
    assert tool._held is not None and _at(tool._lifted_pos, corner)
    tool.on_click(_ctx(viewport, near))            # set down
    assert tool._lifted is None
    assert _at(tool.pins()[PIN_MOVE], corner)
    # Setting a pin down moves no texture.
    assert _at(tool.map.R, before.R) and _at(tool.map.e_u, before.e_u)


def test_ctrl_lets_go_and_far_from_everything_nothing_holds(viewport):
    tool = _square(viewport)
    corner = QVector3D(0, 0, 0)
    near = corner + QVector3D(_metres(viewport, 4), _metres(viewport, 3), 0)
    held = _drag_pin(viewport, tool, PIN_MOVE, near,
                     modifiers=Qt.ControlModifier)
    assert held is None
    assert _at(tool.pins()[PIN_MOVE], near, 1e-5)
    tool = _square(viewport)
    free = QVector3D(1.3, 0.7, 0)
    assert _drag_pin(viewport, tool, PIN_MOVE, free) is None
    assert _at(tool.pins()[PIN_MOVE], free, 1e-5)
