# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""GeoPath tool over a ground surface (Track G, G6): the automatic plan view and
the live elevation readout. Headless — the tool is driven with a stub viewport,
so none of this needs GL."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QGuiApplication, QVector3D

from tools.geopath import GeoPathTool

_app = QGuiApplication.instance() or QGuiApplication([])


class StubCamera:
    """Just the state the tool saves and restores."""

    _VIEWS = {"top": (math.radians(-90.0), math.radians(89.0)),
              "iso": (math.radians(-45.0), math.radians(30.0))}

    def __init__(self) -> None:
        self.perspective = True
        self.yaw, self.pitch = self._VIEWS["iso"]

    def set_view(self, name: str) -> None:
        self.yaw, self.pitch = self._VIEWS[name]


class StubViewport:
    """A ground surface that slopes 10% in +X, and nothing else."""

    def __init__(self, ground=True) -> None:
        self.camera = StubCamera()
        self._ground = ground
        self.datum_alt = 0.0        # scene Z=0 is at sea level unless set
        self.messages = []
        self.scene = type("S", (), {"geo_paths": [], "version": 0})()
        self._hover_geo_node = None

    def has_ground_surface(self) -> bool:
        return self._ground

    def ground_height(self, x, y):
        return 0.1 * x if self._ground else None

    def ground_elevation(self, x, y):
        """Local height plus the datum altitude — what the user is shown."""
        z = self.ground_height(x, y)
        return None if z is None else z + self.datum_alt

    def flash_status(self, text, msec=2500) -> None:
        self.messages.append(text)

    def update(self) -> None:
        pass

    def _world_to_pixel(self, p):
        return None


class Ctx:
    def __init__(self, viewport, x, y):
        self.viewport = viewport
        self.world = QVector3D(x, y, 0.0)


# ---- the automatic plan view -----------------------------------------------

def test_activating_over_ground_switches_to_top_parallel():
    """Only top + parallel has zero parallax, so the click lands under the
    cursor instead of metres away wherever the relief is high."""
    vp = StubViewport()
    tool = GeoPathTool()
    tool.on_activate(vp)
    assert vp.camera.perspective is False
    assert vp.camera.pitch == pytest.approx(math.radians(89.0))
    assert vp.messages, "the user must be told why the view moved"


def test_leaving_the_tool_puts_the_view_back():
    vp = StubViewport()
    before = (vp.camera.perspective, vp.camera.yaw, vp.camera.pitch)
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_deactivate(vp)
    assert (vp.camera.perspective, vp.camera.yaw, vp.camera.pitch) == before


def test_no_ground_surface_leaves_the_camera_alone():
    """Nothing to trace over: taking the user's view would be pure rudeness."""
    vp = StubViewport(ground=False)
    before = (vp.camera.perspective, vp.camera.yaw, vp.camera.pitch)
    tool = GeoPathTool()
    tool.on_activate(vp)
    assert (vp.camera.perspective, vp.camera.yaw, vp.camera.pitch) == before
    assert vp.messages == []


def test_restore_is_not_repeated_after_a_second_deactivate():
    vp = StubViewport()
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_deactivate(vp)
    vp.camera.perspective = False           # user changed it afterwards
    tool.on_deactivate(vp)
    assert vp.camera.perspective is False    # not clobbered by a stale restore


# ---- the live readout ------------------------------------------------------

def test_spot_elevation_shows_before_any_click():
    vp = StubViewport()
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_hover(Ctx(vp, 50.0, 10.0))
    text, _ = tool.value_label()
    assert text == "5.00 m"


def test_readout_shows_real_altitude_not_a_local_offset():
    """A cota of "5.00 m" when the site is at 1705 m is worse than no number:
    it reads as a valid elevation and isn't one."""
    vp = StubViewport()
    vp.datum_alt = 1700.0
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_hover(Ctx(vp, 50.0, 10.0))
    text, _ = tool.value_label()
    assert text == "1705.00 m"


def test_no_readout_off_the_surveyed_area():
    vp = StubViewport(ground=False)
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_hover(Ctx(vp, 50.0, 10.0))
    assert tool.value_label() is None


def test_tracing_reports_length_elevation_drop_and_grade():
    """The three numbers an alignment is judged on, without leaving the tool."""
    vp = StubViewport()
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_click(Ctx(vp, 0.0, 0.0))            # ground here is 0.00 m
    tool.on_hover(Ctx(vp, 100.0, 0.0))          # ground there is 10.00 m
    text, _ = tool.value_label()
    assert "100.00 m" in text                   # run
    assert "10.00 m" in text                    # elevation at the cursor
    assert "+10.00 m" in text                   # rise
    assert "+10.0%" in text                     # grade


def test_grade_is_negative_going_downhill():
    vp = StubViewport()
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_click(Ctx(vp, 100.0, 0.0))
    tool.on_hover(Ctx(vp, 0.0, 0.0))
    text, _ = tool.value_label()
    assert "-10.00 m" in text
    assert "-10.0%" in text


def test_length_only_when_the_ground_is_unknown():
    vp = StubViewport(ground=False)
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_click(Ctx(vp, 0.0, 0.0))
    tool.on_hover(Ctx(vp, 30.0, 40.0))
    text, _ = tool.value_label()
    assert text == "50.00 m"                    # 3-4-5, and no invented cota


def test_readout_clears_when_the_tool_is_dropped():
    vp = StubViewport()
    tool = GeoPathTool()
    tool.on_activate(vp)
    tool.on_hover(Ctx(vp, 50.0, 10.0))
    tool.on_deactivate(vp)
    assert tool.hover_elevation is None
    assert tool.value_label() is None
