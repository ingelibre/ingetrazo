# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Saved views ("Scenes"): capture/apply, importer conversion,
and .igz persistence."""
import math

import pytest

from core.camera import OrbitCamera
from core.layers import Layer
from core.saved_views import SavedView, from_lookat
from core.scene import Scene


def test_capture_apply_round_trips_camera_and_layers():
    scene = Scene()
    scene.layers.append(Layer("Muros"))
    scene.layers.append(Layer("Curvas", visible=False))
    cam = OrbitCamera()
    cam.target.setX(3.0); cam.target.setY(-2.0); cam.target.setZ(1.5)
    cam.distance = 42.0
    cam.yaw = 1.234
    cam.pitch = -0.4
    cam.fov_deg = 30.0
    cam.perspective = False

    view = SavedView.capture("Planta", scene, cam)
    assert view.hidden_layers == ["Curvas"]

    # Wreck the live state, then recall the view.
    cam2 = OrbitCamera()
    for ly in scene.layers:
        ly.visible = True
    view.apply(scene, cam2)
    assert (cam2.target.x(), cam2.target.y(), cam2.target.z()) == (3.0, -2.0, 1.5)
    assert cam2.distance == 42.0
    assert cam2.yaw == 1.234
    assert cam2.pitch == -0.4
    assert cam2.fov_deg == 30.0
    assert cam2.perspective is False
    assert scene.layer("Curvas").visible is False
    assert scene.layer("Muros").visible is True


def test_apply_shows_layers_created_after_the_view_was_saved():
    scene = Scene()
    cam = OrbitCamera()
    view = SavedView.capture("V", scene, cam)
    scene.layers.append(Layer("Nueva", visible=False))
    view.apply(scene, cam)
    # Not in the view's hidden list → shows, the usual convention.
    assert scene.layer("Nueva").visible is True


def test_scenes_preserve_color_by_layer_on_update_and_file_reopen(tmp_path):
    from formats import igz

    scene = Scene()
    cam = OrbitCamera()
    scene.display_style.color_by_layer = True
    colored = SavedView.capture("Layer colors", scene, cam)
    scene.display_style.color_by_layer = False
    normal = SavedView.capture("Materials", scene, cam)
    scene.saved_views = [colored, normal]

    # Updating one scene must not change the other scene's style snapshot.
    scene.display_style.color_by_layer = False
    colored.recapture(scene, cam)
    colored.apply(scene, cam)
    assert scene.display_style.color_by_layer is False
    scene.display_style.color_by_layer = True
    colored.recapture(scene, cam)

    path = tmp_path / "scene-colors.igz"
    igz.save_scene(scene, path)
    restored = Scene()
    igz.load_into(restored, path)

    # Recall both ways, including after another scene changed the live style.
    for index, expected in [(1, False), (0, True), (1, False)]:
        restored.saved_views[index].apply(restored, cam)
        assert restored.display_style.color_by_layer is expected


def test_from_lookat_oblique_view():
    view = from_lookat("V", eye=(10.0, 0.0, 10.0), target=(0.0, 0.0, 0.0),
                       up=(0.0, 0.0, 1.0), fov_deg=35.0)
    assert view.distance == pytest.approx(math.sqrt(200.0))
    assert math.degrees(view.pitch) == pytest.approx(45.0)
    assert math.degrees(view.yaw) == pytest.approx(0.0)


def test_from_lookat_plan_view_recovers_rotation_from_up():
    # Straight-down plan, "north up": the horizontal direction is degenerate —
    # the screen rotation must come from the stored up vector.
    view = from_lookat("Planta", eye=(5.0, 5.0, 100.0), target=(5.0, 5.0, 0.0),
                       up=(0.0, 1.0, 0.0))
    assert math.degrees(view.yaw) == pytest.approx(-90.0)
    assert math.degrees(view.pitch) == pytest.approx(89.0)


def test_from_lookat_parallel_frames_by_ortho_height():
    view = from_lookat("P", eye=(0.0, 0.0, 100.0), target=(0.0, 0.0, 0.0),
                       up=(0.0, 1.0, 0.0), fov_deg=35.0, perspective=False,
                       ortho_height=32.6)
    # The orbit camera shows distance·2·tan(fov/2) vertically in parallel —
    # the chosen distance must reproduce the stored visible height.
    shown = 2.0 * view.distance * math.tan(math.radians(view.fov_deg) / 2.0)
    assert shown == pytest.approx(32.6)
    assert view.perspective is False


def test_igz_round_trips_saved_views(tmp_path):
    from formats import igz
    scene = Scene()
    scene.saved_views.append(SavedView(
        "Planta", target=(1.0, 2.0, 3.0), distance=51.7, yaw=-1.0, pitch=1.55,
        fov_deg=35.0, perspective=False, hidden_layers=["Curvas"]))
    scene.saved_views.append(SavedView("Vista"))
    p = tmp_path / "doc.igz"
    igz.save_scene(scene, p)

    out = Scene()
    igz.load_into(out, p)
    assert [v.name for v in out.saved_views] == ["Planta", "Vista"]
    v = out.saved_views[0]
    assert v.target == (1.0, 2.0, 3.0)
    assert v.distance == 51.7
    assert v.perspective is False
    assert v.hidden_layers == ["Curvas"]
    assert out.saved_views[1].perspective is True


def test_scene_clear_drops_saved_views():
    scene = Scene()
    scene.saved_views.append(SavedView("V"))
    scene.clear()
    assert scene.saved_views == []


def test_scene_remembers_whether_the_base_map_is_shown(tmp_path):
    """A plan scene taken WITH the base map and a detail scene taken WITHOUT
    it must each come back as they were made — and a sheet frame bound to
    either renders that way (Marco, 2026-09-14). Views from documents older
    than the field (no "georef" entry) leave the map alone."""
    from types import SimpleNamespace
    from formats import igz
    from georef.datum import SceneDatum
    from georef.tiles import PRESETS, TileLayer

    scene = Scene()
    scene.georef = SceneDatum(lat=-16.4, lon=-71.5)
    scene.tile_layer = TileLayer(next(iter(PRESETS.values())))
    scene.terrain = SimpleNamespace(visible=True)
    cam = OrbitCamera()

    scene.tile_layer.visible = True
    planta = SavedView.capture("Planta", scene, cam)
    assert planta.georef == {"map": True, "terrain": True, "survey": False}

    scene.tile_layer.visible = False
    scene.terrain.visible = False
    detalle = SavedView.capture("Detalle", scene, cam)
    assert detalle.georef == {"map": False, "terrain": False, "survey": False}

    planta.apply(scene, cam)
    assert scene.tile_layer.visible is True and scene.terrain.visible is True
    detalle.apply(scene, cam)
    assert scene.tile_layer.visible is False and scene.terrain.visible is False

    # A view without the field (older document) is hands-off.
    scene.tile_layer.visible = True
    SavedView.from_dict({"name": "Vieja"}).apply(scene, cam)
    assert scene.tile_layer.visible is True

    # A scene captured before any map existed recalls with the map OFF.
    bare = Scene()
    sin_mapa = SavedView.capture("Sin mapa", bare, cam)
    assert sin_mapa.georef == {"map": False, "terrain": False, "survey": False}
    sin_mapa.apply(scene, cam)
    assert scene.tile_layer.visible is False

    # The flag survives the document round trip.
    scene.terrain = None                       # a stub the writer can't save
    scene.saved_views += [planta, detalle]
    p = tmp_path / "escenas.igz"
    igz.save_scene(scene, p)
    out = Scene()
    igz.load_into(out, p)
    assert [v.georef["map"] for v in out.saved_views] == [True, False]


def test_base_map_opacity_travels_in_the_document(tmp_path):
    """The map's opacity (a faded satellite under a plan sheet) is document
    state on the tile layer and survives the .igz round trip; older files
    without it open fully opaque."""
    from formats import igz
    from georef.datum import SceneDatum
    from georef.tiles import PRESETS, TileLayer

    scene = Scene()
    scene.georef = SceneDatum(lat=-16.4, lon=-71.5)
    scene.tile_layer = TileLayer(next(iter(PRESETS.values())))
    assert scene.tile_layer.opacity == 1.0
    scene.tile_layer.opacity = 0.4
    p = tmp_path / "mapa.igz"
    igz.save_scene(scene, p)
    out = Scene()
    igz.load_into(out, p)
    assert out.tile_layer.opacity == 0.4
    raw = scene.tile_layer.to_dict()
    del raw["opacity"]
    assert TileLayer.from_dict(raw).opacity == 1.0


def test_scene_remembers_its_shadow_settings(tmp_path):
    """A 3D captured with the sun on comes back (and renders its sheet
    frame) with shadows; one captured without, without (Marco,
    2026-09-14). Applied IN PLACE: the panel, the menu and the viewport
    hold the one ``scene.shadows`` object."""
    from formats import igz
    from core.sun import ShadowSettings

    scene = Scene()
    sh = scene.shadows
    cam = OrbitCamera()
    sh.enabled, sh.hour, sh.minute, sh.darkness = True, 15, 30, 0.7
    con = SavedView.capture("Con sol", scene, cam)
    assert con.shadows["enabled"] is True and con.shadows["hour"] == 15
    sh.enabled = False
    sin = SavedView.capture("Sin sol", scene, cam)
    assert sin.shadows["enabled"] is False

    sh.hour = 9
    con.apply(scene, cam)
    assert scene.shadows is sh                          # same object
    assert sh.enabled and (sh.hour, sh.minute) == (15, 30) and sh.darkness == 0.7
    sin.apply(scene, cam)
    assert not sh.enabled
    SavedView.from_dict({"name": "Vieja"}).apply(scene, cam)   # hands-off
    assert not sh.enabled

    scene.saved_views += [con, sin]
    p = tmp_path / "sol.igz"
    igz.save_scene(scene, p)
    out = Scene()
    igz.load_into(out, p)
    assert [v.shadows["enabled"] for v in out.saved_views] == [True, False]
    assert ShadowSettings.from_dict(out.saved_views[0].shadows).hour == 15
