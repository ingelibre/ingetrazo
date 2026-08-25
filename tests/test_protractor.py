# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Protractor tool (H): angled guide lines, SketchUp semantics — reset after
each guide with a hot retype window, 15° tick snapping near the disc,
rise:run slope input, plane lock by arrow keys."""
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


class _VpScreen(_Vp):
    """Stub with a screen projection: world (x, y) → pixel (100x, 100y)."""

    def _world_to_pixel(self, v):
        return (v.x() * 100.0, v.y() * 100.0)


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=QVector3D(x, y, z),
                       screen=QPointF(x * 100.0, y * 100.0),
                       modifiers=Qt.NoModifier, snap=None)


def _click(vp, tool, x, y, z=0.0):
    tool.on_click(_ctx(vp, x, y, z))


def _hover(vp, tool, x, y, z=0.0):
    tool.on_hover(_ctx(vp, x, y, z))


def test_click_angle_creates_guide_and_resets():
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

    # SketchUp: after the guide the tool RESETS for the next measurement.
    assert t.start_point is None and t.ref_point is None
    _click(vp, t, 10, 0)
    _click(vp, t, 11, 0)
    _hover(vp, t, 11, 1)
    _click(vp, t, 11, 1)                           # +45° from the new centre
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


def test_hot_retype_reaims_last_guide():
    # SketchUp: after the guide is created the Measurements box stays hot —
    # typing a new angle re-aims THAT guide instead of adding another.
    scene = Scene()
    vp = _Vp(scene)
    t = ProtractorTool()
    t.on_activate(vp)
    _click(vp, t, 0, 0)
    _click(vp, t, 1, 0)
    _hover(vp, t, 1, 1)
    _click(vp, t, 1, 1)                            # 45° guide, tool resets
    assert len(scene.guides) == 1
    g = scene.guides[0]

    assert t.on_value(vp, 30.0) is True            # retype: same guide moves
    assert len(scene.guides) == 1
    assert abs(g.direction.y() - math.sin(math.radians(30))) < 1e-6
    assert t.on_value(vp, 60.0) is True            # still hot
    assert abs(g.direction.y() - math.sin(math.radians(60))) < 1e-6
    assert t.on_value(vp, -60.0) is True           # negative flips the side
    assert abs(g.direction.y() + math.sin(math.radians(60))) < 1e-6

    assert vp.history.undo()                       # undo the last re-aim only
    assert abs(g.direction.y() - math.sin(math.radians(60))) < 1e-6

    _click(vp, t, 5, 5)                            # a click closes the window
    t.on_cancel(vp)
    assert t.on_value(vp, 10.0) is False


def test_tick_snapping_near_disc_free_far():
    # SketchUp: near the protractor the cursor snaps to the 15° ticks; farther
    # from the centre it measures free (0.1° precision).
    scene = Scene()
    vp = _VpScreen(scene)
    t = ProtractorTool()
    t.on_activate(vp)
    _click(vp, t, 0, 0)
    _click(vp, t, 1, 0)
    _hover(vp, t, 0.4, 0.3)                        # 36.87° at 50 px: snaps
    _click(vp, t, 0.4, 0.3)
    assert len(scene.guides) == 1
    d = scene.guides[0].direction
    assert abs(math.degrees(math.atan2(d.y(), d.x())) - 30.0) < 1e-6

    _click(vp, t, 0, 0)
    _click(vp, t, 1, 0)
    _hover(vp, t, 4, 3)                            # same angle at 500 px: free
    _click(vp, t, 4, 3)
    d = scene.guides[1].direction
    assert abs(math.degrees(math.atan2(d.y(), d.x())) - 36.9) < 0.05


def test_arrow_keys_lock_the_plane():
    scene = Scene()
    vp = _Vp(scene)
    t = ProtractorTool()
    t.on_activate(vp)
    assert t.wireframe_color[:3] != (0, 0, 0)      # ground plan: blue (Z axis)
    assert t.on_key(vp, Qt.Key_Right, Qt.NoModifier) is True
    _hover(vp, t, 0, 0)
    assert t._axis().x() == 1.0                    # locked to red
    _click(vp, t, 0, 0)
    _click(vp, t, 0, 1, 0)                         # base +Y on the YZ plane
    _hover(vp, t, 0, 0, 1)
    _click(vp, t, 0, 0, 1)                         # 90° → guide along Z
    assert abs(abs(scene.guides[0].direction.z()) - 1.0) < 1e-6
    assert t.on_key(vp, Qt.Key_Right, Qt.NoModifier) is True  # toggle off
    assert t._axis_pick is None
    assert t.on_key(vp, Qt.Key_Down, Qt.NoModifier) is False  # not consumed


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


def test_vcb_parses_slope_ratio():
    from views.viewport import Viewport
    parse = Viewport._parse_value_buffer
    kind, deg = parse("3:12")
    assert kind == "ratio"
    assert abs(deg - math.degrees(math.atan2(3, 12))) < 1e-9
    kind, deg = parse("1:6")
    assert abs(deg - math.degrees(math.atan2(1, 6))) < 1e-9
    kind, deg = parse("-1:1")
    assert abs(deg + 45.0) < 1e-9                  # negative rise: other side
    assert parse("3:0") is None                    # zero run is no slope
    assert parse("1:2:3") is None
    assert parse("2.5") == 2.5                     # plain numbers unaffected
