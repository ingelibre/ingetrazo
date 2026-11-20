# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Model Info ▸ Location: the model's geographic location (``scene.georef``),
shown and set or cleared in one undo step — SketchUp's Model Info ▸
Geo-location, on the datum the sun, the base map and the terrain read."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.history import History, SetLocationCommand          # noqa: E402
from core.scene import Scene                                  # noqa: E402
from core.sun import scene_north_deg                          # noqa: E402
from georef.datum import SceneDatum                           # noqa: E402
from plugins import model_info                                # noqa: E402
from plugins.model_info import (                              # noqa: E402
    ModelInfoDialog, _collect_stats, _location_anchored, _stats_to_text)

AREQUIPA = (-16.398866, -71.536961)
QUITO = (-0.180653, -78.467838)


class _Vp:
    """Stub viewport: a scene, its history, a window for the dialog."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.tiles_reset = 0

    def update(self):
        pass

    def reset_tiles(self):
        self.tiles_reset += 1

    def window(self):
        return None


# ---- The numbers ------------------------------------------------------------

def test_no_location():
    stats = _collect_stats(Scene())
    assert stats["location"] is None
    assert "This model has no location yet." in _stats_to_text(stats)


def test_a_location_is_reported_with_its_utm_and_north():
    scene = Scene()
    scene.georef = SceneDatum(*AREQUIPA, north=12.5)
    loc = _collect_stats(scene)["location"]
    assert loc["lat"] == pytest.approx(AREQUIPA[0])
    assert loc["lon"] == pytest.approx(AREQUIPA[1])
    assert loc["zone"] == 19 and loc["northern"] is False
    assert loc["north_deg"] == pytest.approx(12.5)
    text = _stats_to_text(_collect_stats(scene))
    assert "-16.398866°" in text and "-71.536961°" in text
    assert "19S" in text and "12.5°" in text


# ---- One undo step ------------------------------------------------------------

def test_setting_a_location_keeps_the_north_set_before():
    scene = Scene()
    scene.north_deg = 30.0                     # Tools ▸ North, no location yet
    hist = History(scene)
    hist.execute(SetLocationCommand(*AREQUIPA))
    assert scene.georef.lat == pytest.approx(AREQUIPA[0])
    assert scene_north_deg(scene) == pytest.approx(30.0)
    hist.undo()
    assert scene.georef is None and scene.north_deg == pytest.approx(30.0)


def test_moving_keeps_altitude_and_north_and_drops_the_terrain():
    scene = Scene()
    scene.georef = SceneDatum(*AREQUIPA, alt=2335.0, north=-8.0)
    old = scene.georef
    scene.tile_layer, scene.terrain = object(), object()
    tiles, terrain = scene.tile_layer, scene.terrain
    hist = History(scene)
    hist.execute(SetLocationCommand(*QUITO))
    assert scene.georef.lat == pytest.approx(QUITO[0])
    assert scene.georef.alt == pytest.approx(2335.0)
    assert scene_north_deg(scene) == pytest.approx(-8.0)
    assert scene.tile_layer is tiles           # redrawn for the new place
    assert scene.terrain is None               # rebuilt by the window
    hist.undo()
    assert scene.georef is old
    assert scene.tile_layer is tiles and scene.terrain is terrain


def test_clearing_keeps_the_north_for_the_sun_and_undo_brings_it_back():
    scene = Scene()
    scene.georef = SceneDatum(*AREQUIPA, north=20.0)
    old = scene.georef
    scene.tile_layer, scene.terrain = object(), object()
    tiles = scene.tile_layer
    hist = History(scene)
    hist.execute(SetLocationCommand(None, None))
    assert scene.georef is None
    assert scene.tile_layer is None and scene.terrain is None
    assert scene_north_deg(scene) == pytest.approx(20.0)
    hist.undo()
    assert scene.georef is old and scene.tile_layer is tiles


# ---- The tab --------------------------------------------------------------------

def test_the_tab_sets_and_clears_the_location(monkeypatch):
    scene = Scene()
    vp = _Vp(scene)
    dlg = ModelInfoDialog(vp)
    assert dlg._loc_table.isHidden() and not dlg._no_loc_label.isHidden()
    assert dlg._clear_loc_btn.isHidden()
    monkeypatch.setattr("views.location_dialog.pick_location",
                        lambda *_a, **_k: (QUITO[0], QUITO[1], None, None))
    dlg._set_location()
    assert scene.georef.lat == pytest.approx(QUITO[0])
    assert not dlg._loc_table.isHidden() and dlg._loc_table.rowCount() == 6
    assert not dlg._clear_loc_btn.isHidden() and vp.tiles_reset == 1
    dlg._clear_location()
    assert scene.georef is None
    vp.history.undo()
    assert scene.georef.lat == pytest.approx(QUITO[0])
    dlg.close()


def test_a_cancelled_locator_changes_nothing(monkeypatch):
    scene = Scene()
    vp = _Vp(scene)
    dlg = ModelInfoDialog(vp)
    monkeypatch.setattr("views.location_dialog.pick_location",
                        lambda *_a, **_k: None)
    dlg._set_location()
    assert scene.georef is None and not vp.history.undo_stack
    dlg.close()


def test_things_placed_by_the_location_keep_it_out_of_reach():
    """Survey points are placed by the location: moving it here would
    leave them behind, so the Terrain panel does it."""
    scene = Scene()
    scene.georef = SceneDatum(*AREQUIPA)
    assert not _location_anchored(scene)
    scene.geo_points.append(object())
    assert _location_anchored(scene)
    dlg = ModelInfoDialog(_Vp(scene))
    assert not dlg._set_loc_btn.isEnabled()
    assert not dlg._clear_loc_btn.isEnabled()
    assert "Terrain" in dlg._set_loc_btn.toolTip()
    dlg.close()


def test_the_module_keeps_its_tool():
    assert model_info.ModelInfoTool.name == "Model Info"
