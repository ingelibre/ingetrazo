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


@pytest.mark.parametrize("width", [1, 4, 8, 20])
def test_depth_cue_foreground_matches_the_same_profile_width(drawing, width):
    vp, render, _renderer = drawing
    _line(vp)
    profiles = render(_style(profiles=True, profile_width=width))
    depth = render(_style(depth_cue=True, depth_cue_width=width))
    assert np.array_equal(profiles, depth)


def test_negative_extensions_retract_both_ends_without_reversing_short_lines(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    plain = np.flatnonzero(_ink(render(_style())).any(axis=0))
    short = np.flatnonzero(_ink(render(_style(extensions=True, extension_length=-12))).any(axis=0))
    assert short[0] == pytest.approx(plain[0] + 12, abs=1)
    assert short[-1] == pytest.approx(plain[-1] - 12, abs=1)
    vp.camera.distance = 100
    assert not _ink(render(_style(extensions=True, extension_length=-50))).any()


@pytest.mark.parametrize("width", [1, 4, 6, 8, 12, 20])
def test_profile_caps_use_square_inset_and_full_round_overhang(drawing, width):
    vp, render, _renderer = drawing
    _line(vp)
    masks = {cap: _ink(render(_style(profiles=True, profile_width=width, profile_cap=cap)))
             for cap in ("butt", "round", "square", "round_extended")}
    bounds = {cap: np.flatnonzero(mask.any(axis=0)) for cap, mask in masks.items()}
    for cap in ("butt", "round"):
        assert bounds[cap][0] == pytest.approx(bounds["butt"][0], abs=1)
        assert bounds[cap][-1] == pytest.approx(bounds["butt"][-1], abs=1)
    for cap in ("square", "round_extended"):
        overhang = max(0, width / 2 - (2 if cap == "square" else 0))
        assert bounds[cap][0] == pytest.approx(bounds["butt"][0] - overhang, abs=1)
        assert bounds[cap][-1] == pytest.approx(bounds["butt"][-1] + overhang, abs=1)
    if width <= 4:
        assert np.array_equal(masks["square"], masks["butt"])
    if width >= 8:
        assert masks["round"].sum() < masks["butt"].sum() - 10
        assert (masks["round_extended"][:, bounds["round_extended"][0]].sum()
                < masks["round_extended"][:, WIDTH // 2].sum() - 1)


@pytest.mark.parametrize("cap,inset", [("square", 2), ("round_extended", 0)])
def test_profile_cap_overhang_scales_with_export_resolution(drawing, cap, inset):
    vp, render, _renderer = drawing
    _line(vp)
    vp._export_size = (WIDTH, HEIGHT)
    vp._export_edge_px = 2
    plain = np.flatnonzero(_ink(render(_style(profiles=True, profile_width=12))).any(axis=0))
    cap = np.flatnonzero(_ink(render(_style(profiles=True, profile_width=12,
                                           profile_cap=cap))).any(axis=0))
    assert cap[0] == pytest.approx(plain[0] - (12 / 2 - inset) * 2, abs=1)
    assert cap[-1] == pytest.approx(plain[-1] + (12 / 2 - inset) * 2, abs=1)


@pytest.fixture
def cube_viewport():
    """A real, invisible viewport with solid faces, depth, MSAA and picking."""
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QApplication
    from views.viewport import Viewport

    if QApplication.platformName() == "offscreen":
        pytest.skip("no native OpenGL widget on this platform")
    vp = Viewport()
    vp.setAttribute(Qt.WA_DontShowOnScreen)
    vp.resize(900, 750)
    vp.show()
    try:
        for _ in range(3):
            QApplication.processEvents()
        if not vp.isValid() or getattr(vp, "_gl", None) is None:
            pytest.skip("no native OpenGL viewport")
        scene = vp.scene
        scene.show_axes = False
        points = [V(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
        for face in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                     (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)):
            scene.mesh.add_face([points[i] for i in face])
        vp.camera.set_view("iso")
        vp.camera.fit_to(V(-1.25, -1.25, -1.25), V(1.25, 1.25, 1.25))
        scene.version += 1
        yield vp
    finally:
        vp.close()
        vp.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize("perspective", [False, True])
@pytest.mark.parametrize("cap", ["square", "round_extended"])
@pytest.mark.parametrize("width", [8, 20])
def test_thick_profiles_stay_opaque_over_faces_near_their_ends(cube_viewport, perspective, cap, width):
    """Expanded strokes must keep their depth slope against real faces."""
    vp = cube_viewport
    scene = vp.scene
    scene.display_style = _style(profiles=True, profile_width=width, profile_cap=cap)
    vp.camera.perspective = perspective
    image = vp.render_image(900, 750, overlays=False).convertToFormat(QImage.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape((750, image.bytesPerLine() // 4, 4))
    mvp = vp.camera.projection_matrix() * vp.camera.view_matrix()

    def project(point):
        p = mvp.map(point)
        return np.array([(p.x() + 1) * 450, (1 - p.y()) * 375])

    samples = 0
    for edge in scene.mesh.edges:
        toward = (vp.camera.eye() - (edge.a + edge.b) * 0.5
                  if perspective else -vp.camera.forward())
        if len(edge.faces) != 2 or (V.dotProduct(edge.faces[0].normal(), toward)
                                   * V.dotProduct(edge.faces[1].normal(), toward) >= 0):
            continue
        a, b = project(edge.a), project(edge.b)
        tangent = (b - a) / np.linalg.norm(b - a)
        normal = np.array([-tangent[1], tangent[0]])
        for origin, direction in ((a, tangent), (b, -tangent)):
            for along in (width, width * 2, width * 3):
                for side in (-width / 4, width / 4):
                    x, y = np.rint(origin + direction * along + normal * side).astype(int)
                    assert pixels[y, x, :3].max() <= 3, (cap, width, perspective, x, y, pixels[y, x])
                    assert pixels[y, x, 3] == 255
                    samples += 1
    assert samples >= 48


def test_painting_a_solid_edge_updates_3d_material_color_and_undo(cube_viewport, monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    from core.materials import Material
    from tools.base import ToolContext
    from tools.paint import PaintTool

    vp = cube_viewport
    scene = vp.scene
    scene.display_style = _style(profiles=True, profile_width=6, edge_color_mode="material")
    scene.mesh.faces[1].attrs["color"] = (0.9, 0.35, 0.1)
    scene.version += 1
    vp.render_image(900, 750, overlays=False)
    target = next(edge for edge in scene.mesh.edges
                  if not vp._is_occluded((edge.a + edge.b) * 0.5))
    midpoint = (target.a + target.b) * 0.5
    x, y = vp._world_to_pixel(midpoint)
    assert vp.pick_visible_edge(x, y) is target
    original_faces = [dict(face.attrs) for face in scene.mesh.faces]
    paint = Material("Green edge", color=(0.1, 0.85, 0.2))
    for attr, value in {"current_material": paint, "current_color": paint.color,
                        "current_texture": None, "current_opacity": None,
                        "current_is_default": False, "sample_armed": False, "recent": []}.items():
        monkeypatch.setattr(PaintTool, attr, value)
    tool = PaintTool()
    tool.on_click(ToolContext(viewport=vp, world=midpoint, screen=QPointF(x, y),
                              modifiers=Qt.NoModifier, snap=None))
    assert target.material["mat"] == paint.name
    assert [face.attrs for face in scene.mesh.faces] == original_faces

    def is_green():
        color = vp.render_image(900, 750, overlays=False).pixelColor(round(x), round(y))
        return color.green() > color.red() + 80 and color.green() > color.blue() + 80

    assert is_green()
    scene.display_style.edge_color_mode = "same"
    assert not is_green()
    scene.display_style.edge_color_mode = "material"
    assert is_green()
    assert vp.history.undo() and target.material is None
    assert not is_green()
    assert vp.history.redo() and is_green()


def test_endpoint_shapes_have_different_silhouettes_and_keep_size_on_zoom(drawing):
    vp, render, _renderer = drawing
    _line(vp)
    masks = {kind: _ink(render(_style(endpoints=True, endpoint_type=kind, endpoint_size=14)))
             for kind in ("default", "round", "square", "triangle")}
    for left in masks:
        for right in masks:
            if left != right:
                assert not np.array_equal(masks[left], masks[right])
    assert masks["square"].sum() > masks["round"].sum() > masks["triangle"].sum()
    for distance in (3, 8):
        vp.camera.distance = distance
        image = render(_style(endpoints=True, endpoint_type="square", endpoint_size=14))
        mask = _ink(image)
        assert np.flatnonzero(mask.any(axis=1)).size == 14
        assert np.all(image[:, :, 3] == 255)


def test_clipped_ends_get_neither_markers_nor_extended_profile_caps(drawing):
    from PySide6.QtGui import QVector4D
    vp, render, _renderer = drawing
    _line(vp)
    vp._clip_vec = QVector4D(1, 0, 0, 0)
    mask = _ink(render(_style(profiles=True, profile_width=4, profile_cap="round_extended",
                              endpoints=True, endpoint_type="square", endpoint_size=20)))
    assert not mask[:, :WIDTH // 2 - 1].any()
    assert mask[:, WIDTH // 2 + 2].sum() <= 5
    assert mask.sum(axis=0).max() >= 20


@pytest.mark.parametrize("kind", ["round", "square", "triangle"])
def test_junction_has_one_screen_aligned_marker_for_all_branches(drawing, kind):
    vp, render, renderer = drawing
    for end in (V(-1, 0, 0), V(0.7, 0, 0.7), V(0.4, 0, -0.8)):
        vp.scene.mesh.add_edge(V(0, 0, 0), end)
    vp.scene.version += 1
    plain = _ink(render(_style()))
    marked = _ink(render(_style(endpoints=True, endpoint_type=kind, endpoint_size=20)))
    # Three branches, four vertices: only four marker quads, not six.
    assert sum(batch["count"] // 2 for batch in renderer.marker_batches) == 4
    ys, xs = np.mgrid[-14:14, -14:14] + 0.5
    added = (marked & ~plain)[HEIGHT // 2 - 14:HEIGHT // 2 + 14,
                              WIDTH // 2 - 14:WIDTH // 2 + 14]
    if kind == "round":
        allowed = np.hypot(xs, ys) <= 10.6
    elif kind == "square":
        allowed = np.maximum(abs(xs), abs(ys)) <= 10.6
    else:
        allowed = (ys <= 10.6) & (ys + 10 - 2 * abs(xs) >= -1.3)
    assert added.any()
    assert not (added & ~allowed).any()


def test_markers_deduplicate_touching_instances_and_rebuild_only_when_needed(drawing):
    vp, render, renderer = drawing
    _line(vp)
    group = Group()
    group.mesh.add_edge(V(1, 0, 0), V(1, 0, 1))
    vp.scene.groups.append(group)
    vp.scene.version += 1
    style = _style(endpoints=True, endpoint_type="square")
    render(style)
    assert sum(batch["count"] // 2 for batch in renderer.marker_batches) == 3
    batch = renderer.marker_batches[0]
    render(style)
    assert renderer.marker_batches[0] is batch
    style.endpoint_type = "triangle"
    render(style)
    assert renderer.marker_batches[0] is batch
    vp.camera.set_view("iso")
    render(style)
    assert renderer.marker_batches[0] is not batch
    renderer.clear()
    assert renderer.marker_batches == []


def test_hidden_or_unrendered_soft_edges_do_not_steal_a_junction_marker(drawing):
    vp, render, renderer = drawing
    mesh = vp.scene.mesh
    hidden = mesh.add_edge(V(0, 0, 0), V(-1, 0, 0))
    hidden.hidden = True
    soft = mesh.add_edge(V(0, 0, 0), V(0, 0, 1))
    soft.soft = True
    mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    vp.scene.version += 1
    render(_style(endpoints=True, endpoint_type="square"))
    assert sum(batch["count"] // 2 for batch in renderer.marker_batches) == 2


def test_profiles_only_filters_marker_owners_at_soft_silhouettes(drawing):
    vp, render, renderer = drawing
    mesh = vp.scene.mesh
    a, b = V(0, 0, -1), V(0, 0, 1)
    mesh.add_face([a, b, V(1, 1, 1), V(1, 1, -1)])
    mesh.add_face([b, a, V(1, -1, -1), V(1, -1, 1)])
    for edge in mesh.edges:
        edge.soft = True
    vp.scene.version += 1
    style = _style(edges=False, profiles=True, endpoints=True, endpoint_type="square")
    render(style)
    assert renderer.marker_batches
    style.profiles = False
    assert not _ink(render(style)).any()
    assert renderer.marker_batches == []


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
