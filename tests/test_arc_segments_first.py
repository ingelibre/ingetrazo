# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every arc takes its segment count BEFORE it is drawn, like the circle
takes its sides: before the first click a plain number is the count (the
VCB reads «Segments»), and «Ns» sets it at any moment."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.arc import ArcTool, CenterArcTool, PieTool, ThreePointArcTool
from tools.base import ToolContext


class _Vp:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self.messages = []

    def update(self):
        pass

    def set_hover(self, *_):
        pass

    def flash_status(self, text, msec=2500):
        self.messages.append(text)

    def pick_group(self, x, y):
        return None

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None


def _ctx(vp, x, y):
    return ToolContext(viewport=vp, world=QVector3D(x, y, 0.0),
                       screen=QPointF(0, 0), modifiers=Qt.NoModifier,
                       snap=None)


def _arc_edges(vp):
    return len(vp.scene.mesh.edges)


def test_a_number_before_the_first_click_is_the_segment_count():
    for cls in (ArcTool, ThreePointArcTool, CenterArcTool):
        tool = cls()
        vp = _Vp()
        caption = getattr(tool, "vcb_caption", None)
        assert (caption() if caption else tool.vcb_label) == "Segments"
        assert tool.value_is_unitless()
        assert tool.on_value(vp, 40)
        assert tool.segments == 40
        assert tool.on_value(vp, 1) is False        # too few to be an arc
        assert tool.segments == 40


def test_ns_sets_the_count_while_the_arc_is_drawn():
    tool = ThreePointArcTool()
    vp = _Vp()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 1, 1))
    assert tool.on_segments_value(vp, 7)
    tool.on_hover(_ctx(vp, 2, 0))
    assert len(tool.rubber_band_lines()) == 7


def test_the_2point_arc_is_drawn_with_the_count_typed_first():
    tool = ArcTool()
    vp = _Vp()
    tool.on_activate(vp)
    assert tool.on_value(vp, 32)
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 2, 0))
    tool.on_hover(_ctx(vp, 1, 0.5))
    assert len(tool.rubber_band_lines()) == 32
    assert tool.vcb_caption() == "Bulge"
    assert not tool.value_is_unitless()


def test_the_3point_arc_commits_that_many_edges():
    tool = ThreePointArcTool()
    vp = _Vp()
    assert tool.on_value(vp, 24)
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 1, 1))
    tool.on_click(_ctx(vp, 2, 0))
    assert _arc_edges(vp) == 24


def test_the_centre_arc_keeps_its_pitch_until_a_count_is_typed():
    tool = CenterArcTool()
    vp = _Vp()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 1, 0))
    tool.on_hover(_ctx(vp, 0, 1))                 # 90° → six 15° spans
    assert len(tool.rubber_band_lines()) == 2 + 6
    assert tool.on_segments_value(vp, 20)
    assert len(tool.rubber_band_lines()) == 2 + 20


def test_the_pie_takes_the_count_too():
    tool = PieTool()
    vp = _Vp()
    assert tool.on_value(vp, 10)
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 1, 0))
    assert tool.on_value(vp, 90)
    assert _arc_edges(vp) == 10 + 2               # the arc + two radii
