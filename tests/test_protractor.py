# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Protractor tool (H): angled guide lines."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.base import ToolContext
from tools.protractor import ProtractorTool


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass


def _click(vp, tool, x, y, z=0.0):
    tool.on_click(ToolContext(viewport=vp, world=QVector3D(x, y, z),
                              screen=QPointF(0, 0),
                              modifiers=Qt.NoModifier, snap=None))


def _hover(vp, tool, x, y, z=0.0):
    tool.on_hover(ToolContext(viewport=vp, world=QVector3D(x, y, z),
                              screen=QPointF(0, 0),
                              modifiers=Qt.NoModifier, snap=None))


def test_click_angle_creates_guide_line():
    scene = Scene()
    vp = _Vp(scene)
    t = ProtractorTool()
    t.on_activate(vp)
    _click(vp, t, 2, 1)                            # centre
    _click(vp, t, 5, 1)                            # base arm = +X
    _hover(vp, t, 2, 4)
    _click(vp, t, 2, 4)                            # 90°: guide along +Y
    assert len(scene.guides) == 1
    g = scene.guides[0]
    assert g.is_line
    assert (g.point - QVector3D(2, 1, 0)).length() < 1e-9
    assert abs(abs(g.direction.y()) - 1.0) < 1e-9  # vertical in plan

    # The protractor stays placed: a second angle from the same centre.
    _hover(vp, t, 5, 4)
    _click(vp, t, 5, 4)                            # +45°
    assert len(scene.guides) == 2
    d = scene.guides[1].direction
    assert abs(abs(d.x()) - math.sqrt(0.5)) < 1e-6


def test_typed_angle_via_vcb_and_undo():
    scene = Scene()
    vp = _Vp(scene)
    t = ProtractorTool()
    t.on_activate(vp)
    _click(vp, t, 0, 0)
    _click(vp, t, 1, 0)
    _hover(vp, t, 1, 1)                            # counter-clockwise side
    assert t.on_value(vp, 30.0) is True            # exact 30° (a roof pitch)
    assert len(scene.guides) == 1
    d = scene.guides[0].direction
    assert abs(d.x() - math.cos(math.radians(30))) < 1e-6
    assert abs(d.y() - math.sin(math.radians(30))) < 1e-6
    assert vp.history.undo()
    assert len(scene.guides) == 0


def test_guide_on_a_slanted_work_plane():
    scene = Scene()
    vp = _Vp(scene)
    t = ProtractorTool()
    t.on_activate(vp)
    t.work_plane = (QVector3D(0, 0, 0), QVector3D(0, 1, 0))  # a wall (XZ)
    _click(vp, t, 0, 0, 0)
    _click(vp, t, 1, 0, 0)                          # base along +X on the wall
    _hover(vp, t, 0, 0, 1)
    _click(vp, t, 0, 0, 1)                          # 90° up the wall
    g = scene.guides[0]
    assert abs(abs(g.direction.z()) - 1.0) < 1e-6   # guide runs vertically
