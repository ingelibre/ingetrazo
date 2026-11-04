# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pixel checks for edge effects on an invisible native OpenGL surface.

These skip where Qt cannot create GL. They can also run without showing
windows using QT_QPA_PLATFORM=windows on a Windows development machine.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QObject
from PySide6.QtGui import (QImage, QMatrix4x4, QOffscreenSurface, QOpenGLContext,
                           QSurfaceFormat, QVector3D)
from PySide6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                              QOpenGLShaderProgram)

from core.camera import OrbitCamera
from core.group import Group
from core.layers import Layer
from core.scene import Scene
from core.style import Style
from views.edge_renderer import EdgeRenderer

V = QVector3D
WIDTH, HEIGHT = 600, 400


class _Viewport(QObject):
    def __init__(self, context):
        super().__init__()
        self._context = context
        self.scene = Scene()
        self.camera = OrbitCamera()
        self.camera.set_view("front")
        self.camera.perspective = False
        self.camera.aspect = WIDTH / HEIGHT
        self.camera.distance = 5
        self._gl = context.functions()
        self._gl.initializeOpenGLFunctions()
        self._program = QOpenGLShaderProgram(self)
        self._export_size = None
        self._export_edge_px = 1
        self._edit_rest_mode = "fade"
        self.edit_rest_fade = 0.65

    def context(self):
        return self._context

    def devicePixelRatioF(self):
        return 1.0

    def _placements_epoch(self):
        return self.scene.version

    def _placements(self):
        return self.scene.groups

    def _draws_in_edit_context(self, group):
        return False

    def _texture_avg_color(self, path):
        return (0.5, 0.5, 0.5)

    def _xray_face_depth(self):
        self._gl.glClearDepthf(0.0)
        self._gl.glClear(0x0100)


@pytest.fixture
def drawing():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        pytest.skip("no OpenGL context on this platform")
    vp = _Viewport(context)
    fbo_format = QOpenGLFramebufferObjectFormat()
    fbo_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
    fbo = QOpenGLFramebufferObject(WIDTH, HEIGHT, fbo_format)
    if not fbo.isValid():
        pytest.skip("no framebuffer on this platform")
    renderer = EdgeRenderer(vp)

    def render(style, depth=1.0):
        assert context.makeCurrent(surface)
        fbo.bind()
        gl = vp._gl
        gl.glViewport(0, 0, WIDTH, HEIGHT)
        gl.glClearColor(1.0, 1.0, 1.0, 1.0)
        gl.glClearDepthf(depth)
        gl.glClear(0x4000 | 0x0100)
        gl.glEnable(0x0B71)
        gl.glEnable(0x0BE2)
        gl.glBlendFunc(0x0302, 0x0303)
        mvp = vp.camera.projection_matrix() * vp.camera.view_matrix()
        renderer.draw(mvp, WIDTH, HEIGHT, style, style.face_mode)
        assert gl.glGetError() == 0
        image = fbo.toImage().convertToFormat(QImage.Format_RGBA8888)
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).copy()
        return pixels.reshape((HEIGHT, image.bytesPerLine() // 4, 4))[:, :WIDTH]

    yield vp, render, renderer
    context.makeCurrent(surface)
    renderer.clear()
    context.doneCurrent()


def _line(vp):
    vp.scene.mesh.add_edge(V(-1, 0, 0), V(1, 0, 0))
    vp.scene.version += 1


def _ink(image):
    return image[:, :, :3].min(axis=2) < 240


def _style(**kwargs):
    values = dict(profiles=False, sky=False, face_mode="hidden_line",
                  edge_color=(0, 0, 0), background=(1, 1, 1))
    values.update(kwargs)
    return Style(**values)


def test_profile_width_and_extensions_are_measured_in_pixels(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    plain = _ink(render(_style()))
    thick = _ink(render(_style(profiles=True, profile_width=5)))
    extended = _ink(render(_style(extensions=True, extension_length=12)))
    assert thick[:, WIDTH // 2].sum() >= plain[:, WIDTH // 2].sum() + 3
    plain_x = np.flatnonzero(plain.any(axis=0))
    extended_x = np.flatnonzero(extended.any(axis=0))
    assert extended_x[0] == pytest.approx(plain_x[0] - 12, abs=1)
    assert extended_x[-1] == pytest.approx(plain_x[-1] + 12, abs=1)


def test_endpoints_emphasize_only_the_ends_and_preserve_opaque_alpha(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    image = render(_style(endpoints=True, endpoint_length=10))
    mask = _ink(image)
    first = np.flatnonzero(mask.any(axis=0))[0]
    assert mask[:, first + 3].sum() > mask[:, WIDTH // 2].sum()
    assert np.all(image[:, :, 3] == 255)


def test_depth_cue_makes_foreground_strokes_thicker(drawing):
    vp, render, _renderer = drawing
    vp.scene.mesh.add_edge(V(-1, -2.5, 0.5), V(1, -2.5, 0.5))
    vp.scene.mesh.add_edge(V(-1, 2.5, -0.5), V(1, 2.5, -0.5))
    vp.scene.version += 1
    mask = _ink(render(_style(depth_cue=True, depth_cue_width=8)))
    upper = mask[:HEIGHT // 2, WIDTH // 2].sum()
    lower = mask[HEIGHT // 2:, WIDTH // 2].sum()
    assert upper > lower + 1


def test_dashes_follow_layers_and_switch_off_without_repainting_geometry(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    vp.scene.layers.append(Layer("Dashed", linetype="dashed"))
    vp.scene.mesh.edges[0].layer = "Dashed"
    vp.scene.version += 1
    solid = _ink(render(_style(dashes=False))).any(axis=0)
    dashed = _ink(render(_style(dashes=True))).any(axis=0)
    assert 0.4 < dashed.sum() / solid.sum() < 0.85
    assert vp.scene.mesh.edges[0].layer == "Dashed"


def test_colors_follow_material_and_world_axis_of_transformed_instances(drawing):
    vp, render, _renderer = drawing
    mesh = Scene().mesh
    mesh.add_edge(V(-1, 0, 0), V(1, 0, 0))
    group = Group(mesh)
    group.xform = QMatrix4x4()
    group.xform.rotate(90, 0, 1, 0)
    group.material = {"color": (0.9, 0.15, 0.1)}
    vp.scene.groups.append(group)
    vp.scene.version += 1
    material = render(_style(edge_color_mode="material", profiles=True, profile_width=3))
    axis = render(_style(edge_color_mode="axis", profiles=True, profile_width=3))
    same = render(_style(edge_color_mode="same", profiles=True, profile_width=3))
    assert (material[:, :, 0].astype(int) > material[:, :, 1].astype(int) + 60).sum() > 100
    assert (axis[:, :, 2].astype(int) > axis[:, :, 0].astype(int) + 60).sum() > 100
    assert not (same[:, :, 2].astype(int) > same[:, :, 0].astype(int) + 60).any()


def test_back_edges_remain_dashed_when_layer_dashes_are_disabled(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    hidden = _ink(render(_style(dashes=False), depth=0))
    back = _ink(render(_style(dashes=False, back_edges=True), depth=0))
    assert not hidden.any()
    assert 80 < back.sum() < 400


def test_frame_changes_reuse_geometry_and_document_reset_releases_it(drawing):
    vp, render, renderer = drawing
    _line(vp)
    render(_style(extensions=True))
    original = next(iter(renderer.geometry.values()))
    vp.camera.distance = 7
    render(_style(extensions=True))
    assert next(iter(renderer.geometry.values())) is original
    assert len(renderer.batches) == 1
    renderer.clear()
    assert renderer.geometry == {} and renderer.batches == []


def test_near_plane_and_section_clipping_leave_no_spurious_lines(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    from PySide6.QtGui import QVector4D
    vp._clip_vec = QVector4D(1, 0, 0, 0)
    image = render(_style(extensions=True, extension_length=20))
    mask = _ink(image)
    assert not mask[:, :WIDTH // 2 - 1].any()
    assert mask[:, WIDTH // 2:].any()


def test_soft_edges_only_reappear_at_silhouettes_when_profiles_are_enabled(drawing):
    vp, render, _renderer = drawing
    mesh = vp.scene.mesh
    a, b = V(0, 0, -1), V(0, 0, 1)
    mesh.add_face([a, b, V(1, 1, 1), V(1, 1, -1)])
    mesh.add_face([b, a, V(1, -1, -1), V(1, -1, 1)])
    shared = next(edge for edge in mesh.edges if len(edge.faces) == 2)
    shared.soft = True
    vp.scene.version += 1
    off = _ink(render(_style(profiles=False)))
    on = _ink(render(_style(profiles=True, profile_width=5)))
    assert not off[HEIGHT // 2, WIDTH // 2 - 1:WIDTH // 2 + 1].any()
    assert on[HEIGHT // 2, WIDTH // 2 - 1:WIDTH // 2 + 1].all()


def test_extension_lengths_are_independent_of_zoom(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    for distance in (3.0, 8.0):
        vp.camera.distance = distance
        plain = _ink(render(_style())).any(axis=0)
        extended = _ink(render(_style(extensions=True, extension_length=10))).any(axis=0)
        assert extended.sum() - plain.sum() == pytest.approx(20, abs=2)


def test_independent_material_stays_assigned_when_switching_edge_color_modes(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    edge = vp.scene.mesh.edges[0]
    edge.material = {"color": [0.1, 0.8, 0.2]}
    painted = render(_style(edge_color_mode="material", profiles=True, profile_width=3))
    uniform = render(_style(edge_color_mode="same", profiles=True, profile_width=3))
    axes = render(_style(edge_color_mode="axis", profiles=True, profile_width=3))
    assert (painted[:, :, 1].astype(int) > painted[:, :, 0].astype(int) + 60).sum() > 100
    assert not (uniform[:, :, 1].astype(int) > uniform[:, :, 0].astype(int) + 60).any()
    assert (axes[:, :, 0].astype(int) > axes[:, :, 1].astype(int) + 60).sum() > 100
    assert edge.material == {"color": [0.1, 0.8, 0.2]}


def test_export_profile_pen_remains_independent_of_the_regular_edge_pen(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    vp._export_size = (WIDTH, HEIGHT)
    vp._export_edge_px = 1
    vp._export_profile_px = 6
    image = render(_style(profiles=True, profile_width=1))
    assert _ink(image)[:, WIDTH // 2].sum() >= 6
