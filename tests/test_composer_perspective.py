# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A sheet frame in PERSPECTIVE, with its own sun (Marco, 2026-09-17:
«debería haber otra vista 3d con opción de sombras o algo así que se vea
como un 3d de verdad como si viera en campo … la vista 3d como
perspectiva»).

Until this existed ``apply_frame_camera`` forced ``camera.perspective =
False`` on every frame, so a sheet could only ever hold parallel drawings —
an axonometric was the closest thing to a 3D, and a scene saved in
perspective rendered flat anyway. These fix the three things that makes
true: the camera, the page projection that follows from it, and the fact
that such a frame has no scale to print."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.camera import OrbitCamera
from core.composition import (Composicion, MarcoVista, apply_frame_camera,
                              fit_distance_for_scene, frame_page_projector,
                              model_height_for_frame)
from core.saved_views import SavedView
from core.scene import Scene
from tests.test_composer_canvas import _FakeViewport
from views.composer import (ComposerWindow, apply_frame_shadows,
                            frame_title_text, view_title_texts)

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _scene_with_a_box() -> Scene:
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    return scene


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    # the GL render the raster path asks for, GL-free
    host.viewport.render_image = lambda w, h, overlays=True, sharp_shadows=False: None
    composer = ComposerWindow(host)
    return composer, host


def _frame_item(composer, frame):
    from views.composer import FrameItem
    return next(i for i in composer.canvas.items()
                if isinstance(i, FrameItem) and i.model is frame)


# ── The camera ──────────────────────────────────────────────────────────────

def test_a_parallel_frame_still_frames_by_its_exact_scale():
    """The contract every existing sheet rests on, unchanged."""
    cam, scene = OrbitCamera(), _scene_with_a_box()
    frame = MarcoVista(w_mm=100.0, h_mm=80.0, scale_n=50.0)
    apply_frame_camera(cam, frame, None, scene)
    assert cam.perspective is False
    shown = 2.0 * cam.distance * math.tan(math.radians(cam.fov_deg) / 2.0)
    assert shown == pytest.approx(model_height_for_frame(80.0, 50.0))


def test_a_perspective_frame_gets_a_vanishing_point_and_its_own_eye():
    cam, scene = OrbitCamera(), _scene_with_a_box()
    frame = MarcoVista(w_mm=100.0, h_mm=80.0, perspective=True,
                       cam_distance=12.5, cam_fov=35.0)
    apply_frame_camera(cam, frame, None, scene)
    assert cam.perspective is True
    assert cam.distance == pytest.approx(12.5)
    assert cam.fov_deg == pytest.approx(35.0)


def test_a_perspective_frame_bound_to_a_scene_stands_where_the_scene_did():
    """The scene is the natural source of the eye: the user already walked
    there in the model."""
    cam, scene = OrbitCamera(), _scene_with_a_box()
    view = SavedView("De campo", target=(3.0, 0.0, 1.6), distance=22.0,
                     fov_deg=60.0, perspective=True)
    scene.saved_views.append(view)
    frame = MarcoVista(view_key="scene:De campo", perspective=True)
    apply_frame_camera(cam, frame, view, scene)
    assert cam.perspective is True
    assert cam.distance == pytest.approx(22.0)
    assert cam.fov_deg == pytest.approx(60.0)


def test_a_perspective_frame_with_no_eye_at_all_fits_the_model():
    """std:iso turned perspective has no distance anywhere — it must not
    open standing inside a wall."""
    cam, scene = OrbitCamera(), _scene_with_a_box()
    frame = MarcoVista(view_key="std:iso", perspective=True)
    apply_frame_camera(cam, frame, None, scene)
    assert cam.perspective is True
    assert cam.distance == pytest.approx(
        fit_distance_for_scene(scene, cam.fov_deg))
    assert cam.distance > 3.0             # outside the 6×3 m box


def test_the_frames_own_turn_still_applies_in_perspective():
    cam, scene = OrbitCamera(), _scene_with_a_box()
    frame = MarcoVista(perspective=True, cam_distance=10.0,
                       cam_yaw=0.25, cam_pitch=0.1)
    apply_frame_camera(cam, frame, None, scene)
    assert cam.yaw == pytest.approx(0.25)
    assert cam.pitch == pytest.approx(0.1)


# ── The page projection ─────────────────────────────────────────────────────

def test_the_parallel_projector_is_the_scale_arithmetic_it_replaced():
    frame = MarcoVista(w_mm=100.0, h_mm=80.0, scale_n=50.0)
    to_page = frame_page_projector(frame, OrbitCamera())
    model_h = model_height_for_frame(80.0, 50.0)
    k = 80.0 / model_h
    half_h, half_w = model_h / 2.0, (model_h / 2.0) * (100.0 / 80.0)
    px, py = to_page(1.25, -0.5, 30.0)          # the depth is ignored
    assert px == pytest.approx((1.25 + half_w) * k)
    assert py == pytest.approx((half_h + 0.5) * k)


def test_the_perspective_projector_divides_by_depth():
    """The whole difference between an axonometric and standing there: the
    same object, twice as far, draws half the size."""
    frame = MarcoVista(w_mm=100.0, h_mm=80.0, perspective=True)
    cam = OrbitCamera()
    cam.fov_deg = 45.0
    to_page = frame_page_projector(frame, cam)
    near_x, near_y = to_page(1.0, 1.0, 10.0)
    far_x, far_y = to_page(1.0, 1.0, 20.0)
    centre_x, centre_y = to_page(0.0, 0.0, 10.0)
    assert (centre_x, centre_y) == pytest.approx((50.0, 40.0))  # dead centre
    assert near_x - centre_x == pytest.approx(2.0 * (far_x - centre_x))
    assert centre_y - near_y == pytest.approx(2.0 * (centre_y - far_y))


def test_a_point_behind_the_eye_leaves_the_page_by_a_bounded_amount():
    """It has no projection at all; a polyline crossing the eye plane must
    still head off the frame rather than to the next galaxy."""
    frame = MarcoVista(w_mm=100.0, h_mm=80.0, perspective=True)
    px, py = frame_page_projector(frame, OrbitCamera())(1.0, 1.0, -5.0)
    assert not (0.0 <= px <= 100.0 and 0.0 <= py <= 80.0)
    assert abs(px) < 1e4 and abs(py) < 1e4


def test_the_projector_takes_arrays_whole():
    import numpy as np
    frame = MarcoVista(w_mm=100.0, h_mm=80.0, perspective=True)
    to_page = frame_page_projector(frame, OrbitCamera())
    px, py = to_page(np.array([0.0, 1.0]), np.array([0.0, 1.0]),
                     np.array([10.0, 10.0]))
    assert px.shape == (2,) and py.shape == (2,)
    assert (px[0], py[0]) == pytest.approx((50.0, 40.0))


# ── No scale on paper ───────────────────────────────────────────────────────

def test_a_perspective_frame_prints_no_scale():
    frame = MarcoVista(view_key="std:iso", scale_n=125.0, perspective=True)
    assert "1:125" not in frame_title_text(frame)
    assert view_title_texts(frame)["scale"] == "NO SCALE"
    assert frame.scale_label() == "NO SCALE"


def test_a_parallel_frame_keeps_saying_its_scale():
    frame = MarcoVista(view_key="std:iso", scale_n=125.0)
    assert frame_title_text(frame).endswith("1:125")
    assert view_title_texts(frame)["scale"] == "ESC. 1:125"
    assert frame.scale_label() == "ESC. 1:125"


def test_the_escala_field_reads_no_scale_too():
    frame = MarcoVista(scale_n=50.0, perspective=True,
                       title_text="Vista — {escala}")
    # inline in a sentence it reads as words, not as a stamp
    assert view_title_texts(frame)["title"] == "Vista — no scale"


# ── The frame's own sun ─────────────────────────────────────────────────────

def test_the_frame_can_turn_the_sun_on_without_moving_the_models():
    scene = _scene_with_a_box()
    scene.shadows.enabled = False
    apply_frame_shadows(MarcoVista(shadows=True), scene)
    assert scene.shadows.enabled is True


def test_the_frame_can_turn_the_sun_off_for_itself():
    scene = _scene_with_a_box()
    scene.shadows.enabled = True
    apply_frame_shadows(MarcoVista(shadows=False), scene)
    assert scene.shadows.enabled is False


def test_no_opinion_means_the_frame_does_not_touch_the_shadows():
    scene = _scene_with_a_box()
    scene.shadows.enabled = True
    scene.shadows.hour = 9
    apply_frame_shadows(MarcoVista(), scene)
    assert scene.shadows.enabled is True and scene.shadows.hour == 9


def test_the_frame_can_pick_its_own_hour_of_the_day():
    scene = _scene_with_a_box()
    apply_frame_shadows(MarcoVista(shadows=True, sun_hour=15.5), scene)
    assert (scene.shadows.hour, scene.shadows.minute) == (15, 30)


def test_the_live_model_gets_its_own_sun_back_after_the_frame_renders():
    """The composer never disturbs the viewport — the rule the whole
    ``_with_frame_camera`` dance exists for."""
    composer, _host = _composer()
    scene = composer._scene()
    scene.shadows.enabled = False
    scene.shadows.hour = 8
    frame = composer.comp.frames[0]
    frame.shadows = True
    frame.sun_hour = 16.0
    seen = {}
    composer._with_frame_camera(
        frame, lambda: seen.update(on=scene.shadows.enabled,
                                   hour=scene.shadows.hour))
    assert seen == {"on": True, "hour": 16}
    assert scene.shadows.enabled is False and scene.shadows.hour == 8


# ── The composer around it ──────────────────────────────────────────────────

def test_a_perspective_frame_never_takes_the_hidden_line_pass():
    """``hlr_view`` projects in parallel by construction: a vector frame in
    perspective would come back blank."""
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.style = "vectorial"
    frame.perspective = True
    frame.cam_distance = 20.0
    composer._forget_frame(frame)
    composer.render_frame(frame)
    assert id(frame) not in composer.hlr_cache


def test_the_perspective_switch_survives_a_save_and_a_load():
    comp = Composicion(name="Lámina 4")
    comp.frames = [MarcoVista(perspective=True, cam_distance=18.0,
                              cam_fov=35.0, shadows=True, sun_hour=10.0)]
    back = Composicion.from_dict(comp.to_dict()).frames[0]
    assert back.perspective is True
    assert back.cam_distance == pytest.approx(18.0)
    assert back.cam_fov == pytest.approx(35.0)
    assert back.shadows is True
    assert back.sun_hour == pytest.approx(10.0)


def test_an_old_sheet_opens_parallel_even_pointing_at_a_perspective_scene():
    """No silent inheritance: a document made before this existed must draw
    exactly what it drew (half the scenes of a model are saved in
    perspective from modelling)."""
    frame = Composicion.from_dict(
        {"frames": [{"view_key": "scene:Escena 9", "scale_n": 417.7}]}
    ).frames[0]
    assert frame.perspective is False
    cam, scene = OrbitCamera(), _scene_with_a_box()
    view = SavedView("Escena 9", distance=40.0, perspective=True)
    scene.saved_views.append(view)
    apply_frame_camera(cam, frame, view, scene)
    assert cam.perspective is False


def test_zoom_in_a_perspective_frame_walks_the_eye_instead_of_rescaling():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.perspective = True
    frame.cam_distance = 20.0
    before_n = frame.scale_n
    composer.zoom_view(_frame_item(composer, frame), 2.0)
    assert frame.cam_distance == pytest.approx(10.0)
    assert frame.scale_n == before_n      # the scale means nothing here
