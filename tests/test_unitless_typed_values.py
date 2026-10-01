# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #176 (Esteban Penzo, by email): with imperial units the Protractor
did not give the angle typed. Every bare number was read as a LENGTH in
the document's unit, so in a millimetre model «45» reached Rotate as
0.045°, Scale's «2» as a factor of 0.002 and the Polygon's «24» sides as
0. A tool whose value is not a length says so (``value_is_unitless``) and
the number reaches it as typed; lengths keep the document's unit."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core import units  # noqa: E402
from core.scene import Scene  # noqa: E402
from views.viewport import Viewport  # noqa: E402


@pytest.fixture
def bound():
    scene = Scene()
    units.bind_scene(scene)
    yield scene
    units.bind_scene(None)


class _Ev:
    def __init__(self, text, key=0):
        self._t, self._k = text, key

    def text(self):
        return self._t

    def key(self):
        return self._k


class _Recorder:
    """A tool that only records what the VCB hands it."""

    def __init__(self, unitless):
        self._unitless = unitless
        self.got = []

    def value_is_unitless(self):
        return self._unitless

    def on_value(self, viewport, value):
        self.got.append(value)
        return True


def _enter(tool, typed):
    vp = Viewport.__new__(Viewport)
    vp.active_tool = tool
    vp._value_buffer = typed
    vp.valueBufferChanged = type("S", (), {"emit": lambda self, t: None})()
    vp.update = lambda: None
    vp._release_axis_lock_after_operation = lambda *a, **k: None
    vp.flash_status = lambda *a, **k: None
    assert vp._handle_value_key(_Ev("", Qt.Key_Return)) is True
    return tool.got[-1]


@pytest.mark.parametrize("unit", ["m", "mm", "cm", "in", "ft-in"])
def test_an_angle_or_a_count_arrives_as_typed_in_every_unit(bound, unit):
    bound.units = {"length": unit, "precision": 2}
    assert _enter(_Recorder(True), "45") == pytest.approx(45.0, abs=1e-12)
    assert _enter(_Recorder(True), "2;3") == pytest.approx((2.0, 3.0))
    assert _enter(_Recorder(True), "-90") == pytest.approx(-90.0)


def test_a_length_still_takes_the_documents_unit(bound):
    bound.units = {"length": "mm", "precision": 0}
    assert _enter(_Recorder(False), "45") == pytest.approx(0.045)
    bound.units = {"length": "in", "precision": 0}
    assert _enter(_Recorder(False), "2") == pytest.approx(2 * 0.0254)


def test_a_unit_typed_on_purpose_still_converts(bound):
    # Scale's «2m» is the new absolute size, not a factor.
    bound.units = {"length": "mm", "precision": 0}
    assert _enter(_Recorder(True), "2m") == pytest.approx(2.0)


def test_the_unitless_reading_ends_with_the_entry(bound):
    bound.units = {"length": "mm", "precision": 0}
    _enter(_Recorder(True), "45")
    assert units.bare_number_scale() == pytest.approx(0.001)


def test_which_tools_take_a_number_that_is_not_a_length():
    from tools.arc import (ArcTool, CenterArcTool, PieTool,
                           ThreePointArcTool)
    from tools.circle import CircleTool, PolygonTool
    from tools.move import MoveTool
    from tools.protractor import ProtractorTool
    from tools.rotate import RotateTool
    from tools.scale import ScaleTool
    assert RotateTool().value_is_unitless()          # the angle
    assert ProtractorTool().value_is_unitless()      # the angle
    assert ScaleTool().value_is_unitless()           # the factor
    for cls in (CircleTool, PolygonTool):
        t = cls()
        assert t.value_is_unitless()                 # sides, before the centre
        t.start_point = QVector3D(0, 0, 0)
        assert not t.value_is_unitless()             # the radius after it
    for cls in (ThreePointArcTool, CenterArcTool, PieTool):
        assert cls().value_is_unitless()             # segments, then a sweep
    a = ArcTool()
    assert a.value_is_unitless()                     # the segment count first
    a.start_point = QVector3D(0, 0, 0)
    a.end_point = QVector3D(2, 0, 0)
    assert not a.value_is_unitless()                 # the bulge is a length
    assert not MoveTool().value_is_unitless()        # a distance


@pytest.mark.parametrize("unit", ["mm", "in"])
def test_polygon_sides_survive_a_millimetre_or_inch_model(bound, unit):
    """End to end through the real tool: «8» + Enter before the centre is
    eight sides — in mm it used to round 0.008 to 0 and be refused."""
    from tools.circle import PolygonTool
    bound.units = {"length": unit, "precision": 0}
    tool = PolygonTool()
    vp = Viewport.__new__(Viewport)
    vp.active_tool = tool
    vp._value_buffer = "8"
    vp.valueBufferChanged = type("S", (), {"emit": lambda self, t: None})()
    vp.update = lambda: None
    vp._release_axis_lock_after_operation = lambda *a, **k: None
    vp.flash_status = lambda *a, **k: None
    vp._handle_value_key(_Ev("", Qt.Key_Return))
    assert tool.sides == 8
