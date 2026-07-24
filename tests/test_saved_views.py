# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Saved views (SketchUp's "Scenes"): capture/apply, importer conversion,
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
    # Not in the view's hidden list → shows, like SketchUp.
    assert scene.layer("Nueva").visible is True


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
