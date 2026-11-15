# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tools ▸ North: aim true north on screen with a compass, and the sun's
shadows turn with it — with or without a location, one undo step, saved in
the .igz. The model itself never moves."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core import sun
from core.history import History, SetNorthCommand
from core.render_blender import sun_toward
from core.scene import Scene
from formats import igz
from georef.datum import SceneDatum
from tools.base import ToolContext
from tools.north import (COMPASS_PX, NorthTool, compass_segments,
                         north_deg_towards)

YANQUE = (-15.459809, -72.947774)


class _Vp:
    """Stub viewport: world (x, y) → pixel (100x, 100y)."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashes = []
        self.tiles_reset = 0

    def update(self):
        pass

    def flash_status(self, text, *_a):
        self.flashes.append(text)

    def reset_tiles(self):
        self.tiles_reset += 1

    def _world_to_pixel(self, v):
        return (v.x() * 100.0, v.y() * 100.0)


def _ctx(vp, x, y, z=0.0, kind="none"):
    return ToolContext(viewport=vp, world=QVector3D(x, y, z),
                       screen=QPointF(x * 100.0, y * 100.0),
                       modifiers=Qt.NoModifier,
                       snap=SimpleNamespace(kind=kind))


def _shadows_on(scene):
    scene.shadows.enabled = True
    scene.shadows.month, scene.shadows.day = 6, 21
    scene.shadows.hour, scene.shadows.minute = 15, 0


# ---- The sun turns with the north ------------------------------------------

def test_sun_turns_with_the_north_without_a_location():
    """Fails without the tool: with no location the north was always the
    green axis and the sun could not be turned at all."""
    scene = Scene()
    _shadows_on(scene)
    before = sun_toward(scene)
    scene.north_deg = 90.0                      # north lies along +X
    after = sun_toward(scene)
    assert before is not None and after is not None
    # (east, north) on the site → (north, -east) in the model's frame.
    assert after[0] == pytest.approx(before[1], abs=1e-9)
    assert after[1] == pytest.approx(-before[0], abs=1e-9)
    assert after[2] == pytest.approx(before[2], abs=1e-12)


def test_with_a_location_the_datum_north_is_the_one_that_counts():
    scene = Scene()
    scene.georef = SceneDatum(*YANQUE, north=30.0)
    scene.north_deg = 75.0                      # stale, ignored
    assert sun.scene_north_deg(scene) == pytest.approx(30.0)
    x, y = sun.grid_to_model_xy(30.0, 0.0, 1.0)
    v = scene.georef.north_vector()
    assert (x, y) == pytest.approx((v.x(), v.y()), abs=1e-6)


def test_wrap_north():
    assert sun.wrap_north_deg(350.0) == pytest.approx(-10.0)
    assert sun.wrap_north_deg(-180.0) == pytest.approx(180.0)
    assert sun.wrap_north_deg(540.0) == pytest.approx(180.0)


# ---- One undo step -----------------------------------------------------------

def test_set_north_without_location_undo_redo():
    scene = Scene()
    hist = History(scene)
    hist.execute(SetNorthCommand(400.0))         # wraps to 40°
    assert scene.north_deg == pytest.approx(40.0)
    assert scene.georef is None
    hist.undo()
    assert scene.north_deg == 0.0
    hist.redo()
    assert scene.north_deg == pytest.approx(40.0)


def test_set_north_with_location_turns_the_datum_not_the_model():
    scene = Scene()
    scene.add_edge(QVector3D(0, 0, 0), QVector3D(3, 0, 0))
    old = SceneDatum(*YANQUE, alt=12.0)
    scene.georef = old
    scene.terrain = object()                     # display-only, rebuilt
    hist = History(scene)
    hist.execute(SetNorthCommand(-25.0))
    assert scene.georef is not old               # a new datum: map re-cached
    assert scene.georef.north == pytest.approx(-25.0)
    assert scene.georef.lat == old.lat and scene.georef.alt == 12.0
    assert scene.terrain is None
    ends = sorted((v.x(), v.y()) for e in scene.mesh.edges
                  for v in (e.v0.position, e.v1.position))
    assert ends == [(0.0, 0.0), (3.0, 0.0)]      # the model did not move
    hist.undo()
    assert scene.georef is old and scene.terrain is not None


# ---- Saved in the file -----------------------------------------------------

def test_north_without_location_round_trips_and_stays_terse(tmp_path):
    scene = Scene()
    scene.add_edge(QVector3D(0, 0, 0), QVector3D(1, 0, 0))
    plain = tmp_path / "plain.igz"
    igz.save_scene(scene, plain)
    scene.north_deg = 33.5
    path = tmp_path / "north.igz"
    igz.save_scene(scene, path)
    assert path.read_bytes() != plain.read_bytes()
    back = Scene()
    igz.load_into(back, path)
    assert back.north_deg == pytest.approx(33.5)
    back.north_deg = 99.0                        # never leaks into the next
    igz.load_into(back, plain)
    assert back.north_deg == 0.0


def test_new_document_forgets_the_north():
    scene = Scene()
    scene.north_deg = 12.0
    scene.clear()
    assert scene.north_deg == 0.0


# ---- The tool --------------------------------------------------------------

def test_angle_is_clockwise_from_the_green_axis():
    o = QVector3D(0, 0, 0)
    assert north_deg_towards(o, QVector3D(0, 5, 0)) == pytest.approx(0.0)
    assert north_deg_towards(o, QVector3D(5, 0, 0)) == pytest.approx(90.0)
    assert north_deg_towards(o, QVector3D(-5, 0, 0)) == pytest.approx(-90.0)
    assert north_deg_towards(o, QVector3D(0, -5, 0)) == pytest.approx(180.0)
    assert north_deg_towards(o, QVector3D(0, 0, 4)) is None


def test_two_clicks_set_the_north_far_out_at_a_tenth():
    scene = Scene()
    vp = _Vp(scene)
    t = NorthTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 1, 1))                   # centre
    assert t.work_plane is not None              # the arrow sweeps in plan
    # 5 m out = 500 px, far beyond the 70 px compass: free at 0.1°.
    x, y = 1 + 5 * math.sin(math.radians(33.47)), 1 + 5 * math.cos(math.radians(33.47))
    t.on_hover(_ctx(vp, x, y))
    t.on_click(_ctx(vp, x, y))
    assert scene.north_deg == pytest.approx(33.5)
    assert t.centre is None                      # ready for another go
    assert vp.flashes and "33" in vp.flashes[-1]
    vp.history.undo()
    assert scene.north_deg == 0.0


def test_near_the_compass_the_arrow_snaps_to_15_degrees():
    scene = Scene()
    vp = _Vp(scene)
    t = NorthTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))
    # 0.5 m = 50 px: inside the compass.
    r = 0.5
    x, y = r * math.sin(math.radians(40.0)), r * math.cos(math.radians(40.0))
    t.on_hover(_ctx(vp, x, y))
    assert t.pending_deg() == pytest.approx(45.0)
    t.on_click(_ctx(vp, x, y))
    assert scene.north_deg == pytest.approx(45.0)


def test_an_inference_is_aimed_at_exactly():
    scene = Scene()
    vp = _Vp(scene)
    t = NorthTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))
    t.on_hover(_ctx(vp, 3, 7, kind="endpoint"))
    t.on_click(_ctx(vp, 3, 7, kind="endpoint"))
    assert scene.north_deg == pytest.approx(math.degrees(math.atan2(3, 7)),
                                            abs=1e-9)


def test_typed_angle_sets_the_north_at_once():
    scene = Scene()
    vp = _Vp(scene)
    t = NorthTool()
    t.on_activate(vp)
    assert t.value_is_unitless()                 # «30» is 30°, in any unit
    assert t.on_value(vp, -120.0)
    assert scene.north_deg == pytest.approx(-120.0)


def test_with_a_location_the_map_is_redrawn():
    scene = Scene()
    scene.georef = SceneDatum(*YANQUE)
    vp = _Vp(scene)
    t = NorthTool()
    t.on_activate(vp)
    t.on_value(vp, 10.0)
    assert scene.georef.north == pytest.approx(10.0)
    assert vp.tiles_reset == 1


def test_compass_shows_the_current_north_and_follows_the_cursor():
    scene = Scene()
    scene.north_deg = 90.0
    vp = _Vp(scene)
    t = NorthTool()
    t.on_activate(vp)
    t.on_hover(_ctx(vp, 2, 2))
    # The compass keeps its screen size: 70 px = 0.7 m in the stub.
    assert t._radius == pytest.approx(COMPASS_PX / 100.0)
    segs = t.rubber_band_lines()
    far = max((p for s in segs for p in s),
              key=lambda p: (p - QVector3D(2, 2, 0)).length())
    # The farthest point is the N past the arrow tip: east, for north 90°.
    assert far.x() > 2.5 and abs(far.y() - 2.0) < 0.2


def test_compass_lies_flat_at_the_centre_height():
    segs = compass_segments(QVector3D(0, 0, 3.0), 1.0, 20.0)
    assert segs and all(p.z() == pytest.approx(3.0) for s in segs for p in s)


def test_recalling_a_scene_keeps_the_north():
    """North belongs to the site: a scene restores the shadow settings
    whole, and must not take the north back with them (docs/north.md)."""
    from core.saved_views import apply_shadow_state
    scene = Scene()
    snapshot = scene.shadows.to_dict()          # a scene saved before
    scene.north_deg = 30.0
    apply_shadow_state(scene, snapshot)
    assert scene.north_deg == pytest.approx(30.0)


def test_the_manual_shows_what_it_says():
    """docs/north.md: every picture it shows is in the repository."""
    import re
    from pathlib import Path
    docs = Path(__file__).resolve().parent.parent / "docs"
    text = (docs / "north.md").read_text(encoding="utf-8")
    pics = re.findall(r"\]\((images/north/[^)]+)\)", text)
    assert len(pics) == 5
    assert all((docs / p).is_file() for p in pics)
    assert "Shift+N" in text
