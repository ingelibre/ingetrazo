# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Real thin surfaces must retain separate depth at building viewing distances."""
from __future__ import annotations

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V, QVector4D

from core.camera import OrbitCamera

GAUGE = 0.0003048  # 12 mil, unchanged world geometry


def _camera(perspective=True):
    cam = OrbitCamera()
    cam.yaw, cam.pitch, cam.distance = -math.pi / 2, 0.0, 50.0
    cam.perspective = perspective
    cam.depth_bounds = lambda: (V(-12, -6, -3), V(12, 6, 3))
    return cam


def _depth_bin(cam, point):
    clip = (cam.projection_matrix() * cam.view_matrix()).map(
        QVector4D(point.x(), point.y(), point.z(), 1))
    return round((clip.z() / clip.w() * 0.5 + 0.5) * (2**24 - 1))


@pytest.mark.parametrize("perspective", [True, False])
def test_twelve_mil_surfaces_have_distinct_depth_at_fifty_metres(perspective):
    cam = _camera(perspective)
    # Includes the actual float32 Qt projection/view transform, not merely
    # ideal double-precision projection coefficients.
    front = _depth_bin(cam, V(0, 0, 0))
    rear = _depth_bin(cam, V(0, GAUGE, 0))
    assert rear - front >= 8
    assert cam.znear == 0.1 and cam.zfar == 10000.0


@pytest.mark.parametrize("perspective", [True, False])
@pytest.mark.parametrize("two_point", [True, False])
def test_fitting_keeps_every_corner_and_section_cap_depth(perspective, two_point):
    cam = _camera(perspective)
    cam.two_point = two_point
    cam.pitch = math.radians(30)
    matrix = cam.projection_matrix() * cam.view_matrix()
    # A section cap is inside this convex box too; fitting does not use the
    # cut plane to discard the severed half's depth or tighten through a cap.
    for x in (-12, 12):
        for y in (-6, 6):
            for z in (-3, 3):
                c = matrix.map(QVector4D(x, y, z, 1))
                assert -c.w() < c.z() < c.w()


def test_walkthrough_and_close_view_keep_the_close_near_plane():
    cam = _camera()
    cam.distance = 0.02
    cam.depth_bounds = lambda: (V(-1, -1, -1), V(1, 1, 1))
    near, _far = cam.depth_range()
    assert near == pytest.approx(0.0004)
    ahead = cam.eye() + cam.forward() * 0.002
    clip = (cam.projection_matrix() * cam.view_matrix()).map(
        QVector4D(ahead.x(), ahead.y(), ahead.z(), 1))
    assert -clip.w() < clip.z() < clip.w()


def test_user_clip_planes_are_never_expanded_by_bounds():
    cam = _camera()
    cam.znear, cam.zfar = 2.0, 60.0
    cam.distance = 10.0
    cam.depth_bounds = lambda: (V(-1, -100, -1), V(1, 100, 1))
    assert cam.depth_range() == (0.2, 60.0)


def test_parallel_keeps_geometry_behind_the_eye_when_in_bounds():
    cam = _camera(False)
    cam.depth_bounds = lambda: (V(-1, -80, -1), V(1, 10, 1))
    near, far = cam.depth_range()
    assert near < -30 and far > 60


@pytest.mark.parametrize("perspective", [True, False])
@pytest.mark.parametrize("two_point", [True, False])
def test_cursor_ray_keeps_unfitted_origin_and_off_center_direction(
        perspective, two_point):
    from views.viewport import Viewport

    cam = _camera(perspective)
    cam.distance, cam.pitch = 20.0, math.radians(25)
    cam.two_point = two_point
    cam.znear, cam.zfar = 0.25, 125.0
    cam.aspect = 1000 / 600
    cam.depth_bounds = lambda: (V(-0.1, -0.1, -0.1), V(0.1, 0.1, 0.1))
    vp = SimpleNamespace(camera=cam, width=lambda: 1000, height=lambda: 600)
    forward = cam._level_forward()
    if forward is None:
        forward = cam.forward()
    right = V.crossProduct(forward, cam.up_vector()).normalized()
    up = V.crossProduct(right, forward)
    point = cam.eye() + forward * 2 + right * 0.25 + up * 0.2
    pixel = Viewport._world_to_pixel(vp, point)
    assert pixel is not None
    fitted_origin, fitted_direction = Viewport._pixel_to_ray(vp, *pixel)
    assert fitted_origin is not None and fitted_direction is not None
    # A new drawing point can sit in front of the current model's tightened
    # near plane. Its intersection must still be forward along the ray.
    assert cam.depth_range()[0] > 2.0
    t = V.dotProduct(point - fitted_origin, fitted_direction)
    assert t > 0
    assert (fitted_origin + fitted_direction * t - point).length() < 0.002
    origin_depth = V.dotProduct(fitted_origin - cam.eye(), forward)
    expected = cam.near_plane() if perspective else -cam.far_plane()
    assert origin_depth == pytest.approx(expected, abs=2e-5)
    cam.depth_bounds = None
    original_origin, original_direction = Viewport._pixel_to_ray(vp, *pixel)
    assert (fitted_origin - original_origin).length() < 1e-6
    assert (fitted_direction - original_direction).length() < 1e-6


@pytest.mark.parametrize("fitted", [True, False])
def test_millimetre_cursor_ray_stays_finite_without_far_plane_unprojection(fitted):
    from views.viewport import Viewport

    cam = _camera()
    cam.distance = 0.005
    if fitted:
        cam.depth_bounds = lambda: (V(-0.005, 0, -0.005), V(0.005, 0, 0.005))
    else:
        cam.depth_bounds = None
    vp = SimpleNamespace(camera=cam, width=lambda: 1000, height=lambda: 600)
    for pixel in ((500, 300), (20, 30), (980, 570)):
        origin, direction = Viewport._pixel_to_ray(vp, *pixel)
        assert origin is not None and direction is not None
        assert all(math.isfinite(c) for v in (origin, direction)
                   for c in v.toTuple())
        assert direction.length() == pytest.approx(1.0)
        assert V.dotProduct(direction, cam.forward()) > 0


def _viewport_stub(scene):
    from views.viewport import Viewport
    vp = SimpleNamespace(
        scene=scene, active_tool=None, plano_style=None, style_override=None,
        _base_map_showing=lambda: False, _terrain_showing=lambda: False,
        _photo_showing=lambda: False, _rest_is_hidden=lambda: False,
    )
    vp._placements_epoch = lambda: Viewport._placements_epoch(vp)
    vp._visible_billboards = lambda: Viewport._visible_billboards(vp)
    vp._placements = lambda: Viewport._placements(vp)
    vp._expand_placements = lambda *args: Viewport._expand_placements(vp, *args)
    vp.bounds = lambda: Viewport._projection_bounds(vp)
    return vp


def test_default_select_tool_keeps_model_depth_fitting():
    from core.scene import Scene
    from tools.base import Tool
    from tools.select import SelectTool
    vp = _viewport_stub(Scene())
    vp.active_tool = SelectTool()
    bounds = V(-12, -6, -3), V(12, 6, 3)
    vp.scene.bounds = lambda: bounds
    assert vp.active_tool.preview_faces.__func__ is Tool.preview_faces
    assert vp.bounds() is bounds
    cam = _camera()
    cam.depth_bounds = vp.bounds
    assert _depth_bin(cam, V(0, GAUGE, 0)) - _depth_bin(cam, V(0, 0, 0)) >= 8


def test_hidden_far_reference_does_not_spend_model_depth_precision():
    from core.scene import Scene
    scene = Scene()
    scene.mesh.add_face([V(-1, 0, -1), V(1, 0, -1), V(1, 0, 1), V(-1, 0, 1)])
    # The image's geometry must not even be queried while it is hidden.
    from core.layers import Layer
    scene.layers.append(Layer("Far references", visible=False))
    image = SimpleNamespace(layer="Far references")
    scene.image_planes.append(image)
    vp = _viewport_stub(scene)
    lo, hi = vp.bounds()
    assert lo is not None and hi is not None
    scene.layers[-1].visible = True
    assert vp.bounds() == (None, None)


@pytest.mark.parametrize("perspective", [True, False])
@pytest.mark.parametrize("nested", [True, False])
def test_visible_billboard_outside_model_bounds_keeps_original_clipping(
        perspective, nested):
    from core.group import Group, make_billboard_group
    from core.scene import Scene

    scene = Scene()
    scene.mesh.add_face([V(-1, 0, -1), V(1, 0, -1), V(1, 0, 1)])
    figure = make_billboard_group("unused.png", 2, "Figure", 1, V(0, -10, 0))
    root = Group() if nested else figure
    if nested:
        root.children.append(figure)
    scene.groups.append(root)
    vp = _viewport_stub(scene)
    cam = _camera(perspective)
    cam.depth_bounds = vp.bounds

    near, far = cam.depth_range()
    assert near < 40 < far
    assert vp.bounds() == (None, None)
    # Hidden figures, including those hidden by their parent, do not disable
    # precision for the ordinary model that remains visible.
    root.hidden = True
    scene.version += 1
    assert cam.depth_range() == pytest.approx((49.9, 50.1))


def test_depth_tested_guides_outside_model_bounds_keep_original_clipping():
    from core.guide import Guide
    from core.scene import Scene

    scene = Scene()
    scene.mesh.add_face([V(-1, 0, -1), V(1, 0, -1), V(1, 0, 1)])
    scene.guides.append(Guide(V(0, -10, 0), direction=V(1, 0, 0)))
    vp = _viewport_stub(scene)
    cam = _camera()
    cam.depth_bounds = vp.bounds
    near, far = cam.depth_range()
    assert near < 40 < far
    # Styled sheet renders omit scaffolding and can retain model precision.
    vp.plano_style = "tecnico"
    assert cam.depth_range() == pytest.approx((49.9, 50.1))


@pytest.mark.parametrize("auxiliary", ["preview", "groups", "ghosts", "terrain", "edit"])
def test_unbounded_auxiliary_geometry_keeps_original_clipping(auxiliary):
    from core.scene import Scene
    vp = _viewport_stub(Scene())
    vp.scene.bounds = lambda: pytest.fail("incomplete bounds must not fit clipping")
    if auxiliary == "preview":
        vp.active_tool = SimpleNamespace(
            preview_faces=lambda: pytest.fail("fitting must not construct previews"))
    elif auxiliary == "groups":
        vp._preview_groups = [object()]
    elif auxiliary == "ghosts":
        vp.scene.show_hidden_objects = True
    elif auxiliary == "terrain":
        vp._terrain_showing = lambda: True
    else:
        vp._rest_is_hidden = lambda: True
    assert vp.bounds() == (None, None)


@pytest.mark.parametrize("perspective", [True, False])
@pytest.mark.parametrize("instanced", [True, False])
def test_rendered_tape_front_is_not_overpainted_by_its_rear(perspective, instanced):
    """Consumer-visible GL scenario; run under Xvfb/Mesa for a real depth FBO.

    INGETRAZO_RUST=0 and =1 exercise the Python/Rust draw submission modes.
    Both use the same camera and shaders. No running document or settings
    are changed: this creates only an isolated Viewport and a new mesh.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.mesh import Mesh
    from tools.select import SelectTool
    from views.viewport import Viewport

    app = QApplication.instance() or QApplication([])
    if app.platformName() in ("offscreen", "minimal"):
        pytest.skip("QOpenGLWidget is unsupported on this platform; "
                    "use Xvfb with QT_QPA_PLATFORM=xcb")
    vp = Viewport()
    vp.active_tool = SelectTool()
    try:
        mesh = Mesh() if instanced else vp.scene.mesh
        front = [V(-12, 0, -6), V(12, 0, -6), V(12, 0, 6), V(-12, 0, 6)]
        rear = [p + V(0, GAUGE, 0) for p in front]
        # Outward normals: -Y at the visible front, +Y at the rear.
        faces = [front, list(reversed(rear))]
        faces += [[front[i], rear[i], rear[(i + 1) % 4], front[(i + 1) % 4]]
                  for i in range(4)]
        for vertices in faces:
            mesh.add_face(vertices).attrs["color"] = (0.9, 0.05, 0.05)
        if instanced:
            group = Group(mesh, "12 mil tape")
            group.xform = QMatrix4x4()
            vp.scene.groups.append(group)
        vp.scene.version += 1
        style = vp.scene.display_style
        style.sky, style.edges, style.profiles = False, False, False
        style.face_mode = "shaded"
        # Isolate model depth: workspace axes lie on the tape's front plane.
        vp.style_override = style
        vp.camera.yaw, vp.camera.pitch = -math.pi / 2, 0.0
        vp.camera.distance = 50.0
        vp.camera.perspective = perspective
        vp.resize(640, 480)
        vp.show()
        for _ in range(10):
            app.processEvents()
        if vp._gl is None or not vp.isValid():
            pytest.skip("no rendering OpenGL context; use Xvfb with QT_QPA_PLATFORM=xcb")
        image = vp.grabFramebuffer()
        assert not image.isNull()
        samples = [image.pixelColor(image.width() // 2 + x,
                                    image.height() // 2 + y)
                   for x in (-40, -20, 0, 20, 40) for y in (-20, 0, 20)]
        assert all(c.red() > 2 * c.green() and c.red() > 2 * c.blue()
                   for c in samples), [c.getRgb() for c in samples]
    finally:
        vp.close()
        # Destroy this context before the next viewport starts rendering.
        # Delayed cyclic GC can otherwise tear it down inside initializeGL.
        vp.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
