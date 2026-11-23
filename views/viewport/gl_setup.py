# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""GL context lifecycle: scene FBO, shader programs, buffers, textures and their release."""
from __future__ import annotations

from array import array
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QOpenGLFunctions, QPainter, QVector3D
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject,
                              QOpenGLFramebufferObjectFormat, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLTexture,
                              QOpenGLVertexArrayObject)
from views.viewport._support import (GL_FLOAT, GL_DEPTH_TEST, _MAX_CUT_PLANES,
                                     GL_BLEND, GL_LEQUAL, SHADER_DIR,
                                     _SHARED_BAKES, _decoded_texture,
                                     _scene_blend)


class GLSetupMixin:
    """GL context lifecycle: scene FBO, shader programs, buffers, textures and their release."""

    # ---- GL lifecycle -------------------------------------------------------
    def initializeGL(self) -> None:
        # initializeGL re-runs when Qt recreates the context — the widget
        # moved to another window, which is what MultiView does to put the
        # viewport in its grid. Everything below is rebuilt; what the frame
        # makes lazily must be forgotten too, or it is bound in a context it
        # does not belong to (segfault in _draw_image_planes, 10-10).
        self._forget_context_objects()
        self._gl = QOpenGLFunctions(self.context())
        self._gl.initializeOpenGLFunctions()
        # Who is drawing: the GPU driver or a software rasteriser. Recorded
        # for Help ▸ About, written to the log folder, and announced to the
        # main window so a CPU-drawn viewport says so before anyone wonders
        # why orbiting crawls (a Windows box without a working driver).
        from core.glinfo import meets_gl_requirement, read_gl_info, write_gl_report
        self.gl_info = read_gl_info(self._gl)
        self.gl_info["supported"] = meets_gl_requirement(self.gl_info["version"])
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication
        self.gl_info["platform"] = QGuiApplication.platformName()
        _app = QCoreApplication.instance()
        if _app is not None:
            self.gl_info["fallback"] = _app.property("gl_fallback") or ""
        write_gl_report(self.gl_info)
        self.glReady.emit(self.gl_info)
        # Every pixel of the view is drawn (paintGL clears with an opaque
        # background, even below GL 3.3), so nothing under it needs painting.
        # Without this, any status text redrawn in the same frame as the view
        # merged into one dirty rectangle with it and the window painted its
        # whole background under the view again — ~765 px tall instead of
        # the bar's 34, in one frame of six of a Line in the Plaza (19-11).
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        if not self.gl_info["supported"]:
            # Below GL 3.3 the shaders cannot compile (issue #751). Make no
            # GL object on this context, so none is freed on it at exit
            # either; paintGL only clears, and the main window explains.
            self._program = None              # a previous context's, if any
            self._gl.glClearColor(0.93, 0.94, 0.96, 1.0)
            return
        # GL cleanup has exactly one legal moment: the context's own farewell.
        # (initializeGL re-runs if the context is ever recreated; each context
        # gets its own connection, which is precisely what we want.)
        self.context().aboutToBeDestroyed.connect(self.release_gl_textures)
        self._gl.glClearColor(0.93, 0.94, 0.96, 1.0)
        self._gl.glClearDepthf(1.0)
        self._gl.glEnable(GL_DEPTH_TEST)
        # LEQUAL (instead of the default LESS) lets a fragment win when its
        # depth equals the existing one — important for edges drawn on top of
        # coincident faces, which can rasterize to bit-identical depths.
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glEnable(GL_BLEND)
        _scene_blend(self._gl)

        self._program = self._compile_program()
        self._style_ground_program = None
        self._watermark_textures = {}
        self._loc_mvp = self._program.uniformLocation("u_mvp")
        self._loc_color = self._program.uniformLocation("u_color")
        self._loc_back_color = self._program.uniformLocation("u_back_color")
        self._loc_fade = self._program.uniformLocation("u_fade")
        self._loc_fade_color = self._program.uniformLocation("u_fade_color")
        self._loc_fog_enable = self._program.uniformLocation("u_fog_enable")
        self._loc_fog_eye = self._program.uniformLocation("u_fog_eye")
        self._loc_fog_forward = self._program.uniformLocation("u_fog_forward")
        self._loc_fog_color = self._program.uniformLocation("u_fog_color")
        self._loc_fog_start = self._program.uniformLocation("u_fog_start")
        self._loc_fog_end = self._program.uniformLocation("u_fog_end")
        self._loc_pos = self._program.attributeLocation("a_pos")
        self._loc_uv = self._program.attributeLocation("a_uv")
        self._loc_use_tex = self._program.uniformLocation("u_use_texture")
        self._loc_tex = self._program.uniformLocation("u_tex")
        self._loc_vcolor = self._program.attributeLocation("a_color")
        self._loc_use_vcolor = self._program.uniformLocation("u_use_vcolor")
        self._loc_opacity = self._program.uniformLocation("u_opacity")
        self._loc_material_opaque = self._program.uniformLocation("u_material_opaque")
        self._loc_xray_opacity = self._program.uniformLocation("u_xray_opacity")
        self._loc_hard_cutout = self._program.uniformLocation("u_hard_cutout")
        self._loc_shade = self._program.uniformLocation("u_shade")
        # Instanced pass: re-shade the prototype's baked tones for the
        # rotation of each copy (#482), against the bake's own light.
        self._loc_reshade = self._program.uniformLocation("u_reshade")
        self._loc_back_shade = self._program.uniformLocation("u_back_shade")
        self._program.bind()
        self._program.setUniformValue(self._loc_reshade, 0)
        self._program.setUniformValue(
            self._program.uniformLocation("u_light_fixed"), self._LIGHT)
        self._program.release()
        # Per-instance model matrix columns (P2 instanced components).
        self._loc_inst = [self._program.attributeLocation(f"a_inst{i}")
                          for i in range(4)]
        self._loc_clip_planes = [
            self._program.uniformLocation(f"u_clip_planes[{i}]")
            for i in range(_MAX_CUT_PLANES)]
        self._loc_clip_count = self._program.uniformLocation("u_clip_count")
        # Sun shadows (core/sun.py): sampling uniforms on the main program,
        # plus the tiny depth-only program the shadow map renders with.
        self._loc_shadow_enable = self._program.uniformLocation(
            "u_shadow_enable")
        self._loc_shadow_map = self._program.uniformLocation("u_shadow_map")
        self._loc_light_vp = self._program.uniformLocation("u_light_vp")
        self._loc_fig_shadow_map = self._program.uniformLocation(
            "u_fig_shadow_map")
        self._loc_fig_shadow_enable = self._program.uniformLocation(
            "u_fig_shadow_enable")
        self._loc_shadow_dark = self._program.uniformLocation("u_shadow_dark")
        self._loc_shadow_bias = self._program.uniformLocation("u_shadow_bias")
        self._loc_shadow_soft = self._program.uniformLocation("u_shadow_soft")
        self._loc_shadow_world = self._program.uniformLocation(
            "u_shadow_world")
        self._loc_sun_dir = self._program.uniformLocation("u_sun_dir")
        self._loc_shadow_overlay = self._program.uniformLocation(
            "u_shadow_overlay")
        self._loc_stipple = self._program.uniformLocation("u_stipple")
        self._loc_viewport_px = self._program.uniformLocation("u_viewport_px")
        self._loc_dash_px = self._program.uniformLocation("u_dash_px")
        self._depth_program = self._compile_depth_program()
        self._loc_d_mvp = self._depth_program.uniformLocation("u_mvp")
        self._loc_d_clip_planes = [
            self._depth_program.uniformLocation(f"u_clip_planes[{i}]")
            for i in range(_MAX_CUT_PLANES)]
        self._loc_d_clip_count = self._depth_program.uniformLocation(
            "u_clip_count")
        self._loc_d_use_tex = self._depth_program.uniformLocation(
            "u_use_texture")
        self._loc_d_tex = self._depth_program.uniformLocation("u_tex")
        self._loc_d_bias_const = self._depth_program.uniformLocation(
            "u_bias_const")
        self._loc_d_bias_slope_max = self._depth_program.uniformLocation(
            "u_bias_slope_max")
        self._shadow_fbo = None
        self._shadow_key = None
        self._shadow_vp = None
        self._fine_shadow_fbo = None
        self._fine_shadow_key = None
        self._fig_shadow_fbo = None
        self._fig_shadow_key = None
        self._shadow_fit = None

        # Axes rebuilt per frame (dash spacing scales with zoom), so dynamic.
        self._axes_vao, self._axes_vbo = self._create_dynamic()
        self._guides_vao, self._guides_vbo = self._create_dynamic()
        self._guides_cache = None
        self._axes_spans: dict = {}
        self._axes_key = None        # a new buffer holds no axes yet

        self._sky_vao, self._sky_vbo = self._create_dynamic()
        self._sky_grad_vao, self._sky_grad_vbo = self._create_dynamic_color()
        self._ground_vao, self._ground_vbo = self._create_dynamic()
        self._shadow_bb_vao, self._shadow_bb_vbo = self._create_dynamic_uv()
        self._edges_vao, self._edges_vbo = self._create_dynamic()
        self._dback_vao, self._dback_vbo = self._create_dynamic()
        self._selected_vao, self._selected_vbo = self._create_dynamic()
        self._sel_faces_vao, self._sel_faces_vbo = self._create_dynamic()
        self._faces_vao, self._faces_vbo = self._create_dynamic_vcol()
        self._tex_faces_vao, self._tex_faces_vbo = self._create_dynamic_uv()
        self._billboard_vao, self._billboard_vbo = self._create_dynamic_uv()
        self._bb_sel_vao, self._bb_sel_vbo = self._create_dynamic()
        self._hover_faces_vao, self._hover_faces_vbo = self._create_dynamic()
        self._hover_edges_vao, self._hover_edges_vbo = self._create_dynamic()
        self._silhouette_vao, self._silhouette_vbo = self._create_dynamic()
        self._rubber_vao, self._rubber_vbo = self._create_dynamic()
        self._preview_faces_vao, self._preview_faces_vbo = self._create_dynamic()
        self._preview_tex_vao, self._preview_tex_vbo = self._create_dynamic_uv()
        self._section_vao, self._section_vbo = self._create_dynamic()
        self._tile_quad_vao, self._tile_quad_vbo = self._create_dynamic_uv()
        self._watermark_vao, self._watermark_vbo = self._create_dynamic_uv()
        self._terrain_vao, self._terrain_vbo = self._create_dynamic_uv()
        self._photo_vao, self._photo_vbo = self._create_dynamic_uv()

    def resizeGL(self, w: int, h: int) -> None:
        # Qt passes framebuffer-pixel sizes here (already scaled by DPR), so
        # this is the authoritative source for FBO and viewport dimensions.
        if self._gl is None or self._program is None:
            return
        self._gl.glViewport(0, 0, w, h)
        self.camera.set_aspect(w, h)
        self._ensure_scene_fbo(w, h)

    def _fb_size(self) -> tuple[int, int]:
        """Framebuffer pixel size (logical size × device pixel ratio)."""
        dpr = self.devicePixelRatioF()
        return max(int(round(self.width() * dpr)), 1), max(int(round(self.height() * dpr)), 1)

    def _ensure_scene_fbo(self, w: int, h: int) -> None:
        """Create or resize the offscreen FBO used for depth-tested rendering."""
        size = (max(w, 1), max(h, 1))
        if self._scene_fbo is not None and self._fbo_size == size:
            return
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        # Real MSAA happens HERE, where the scene actually renders; the blit
        # to the widget's single-sample FBO is the resolve (MSAA read → plain
        # draw is the legal direction). The widget surface itself stays
        # single-sample — see __init__. Sample count from Preferences
        # (Graphics); changing it just voids _fbo_size.
        fmt.setSamples(getattr(self, "_msaa", 4))
        self._scene_fbo = QOpenGLFramebufferObject(size[0], size[1], fmt)
        if fmt.samples() and self._scene_fbo.format().samples() == 0:
            # Driver refused multisampling — retry single-sample but KEEP the
            # depth/stencil attachment (the Wayland depth workaround).
            fmt.setSamples(0)
            self._scene_fbo = QOpenGLFramebufferObject(size[0], size[1], fmt)
        self._fbo_size = size

    def render_image(self, width_px: int, height_px: Optional[int] = None,
                     overlays: bool = True,
                     annotations_only: bool = False,
                     sharp_shadows: bool = False,
                     transparent: bool = False,
                     crop_to_frame: bool = False,
                     defined_shadows: bool = False) -> Optional["QImage"]:
        """Render the current view at ``width_px`` wide (height follows the
        viewport's aspect) and return it as a ``QImage`` — the hi-res 2D
        export. Reuses the exact ``paintGL`` pipeline against a temporary
        FBO, then paints the presentation overlays (dimensions, geo paths,
        survey points, guides) on top with a scaled QPainter; interactive
        artifacts (snap marker, hover, rubber band) are naturally absent.

        The sheet composer passes an explicit ``height_px`` (its frames have
        their own aspect — the caller is responsible for pointing the camera
        and setting its aspect to match) and ``overlays=False``: the overlay
        painters are calibrated to the live widget's aspect and would land
        misplaced under a composer camera.

        ``sharp_shadows`` (Export image, sheets): the sun's map is drawn
        for this one picture at ``_SHADOW_EXPORT_SIZE`` instead of the view's
        2048 — a plaza of 100 m gets 1.2 cm per texel instead of 5 cm — and
        freed after it, so the view keeps its own map and its memory.

        ``transparent`` (Export image): no sky, no ground and no background
        colour — alpha 0 wherever the model is not, glass and the shadows on
        the ground as translucent as they are.

        ``crop_to_frame`` (Export image): with a camera frame set (Camera
        Settings ▸ Frame) the picture is what lies inside it, ``width_px``
        wide — the view is rendered that much wider and cut to the frame,
        so the export is exactly the shot framed on screen."""
        if self._gl is None or self._program is None:
            return None
        lw = max(self.width(), 1)
        lh = max(self.height(), 1)
        if crop_to_frame and height_px is None:
            from core.camera import frame_rect
            rect = frame_rect(lw, lh, getattr(self.camera, "frame_aspect",
                                               None))
            if rect is not None and (rect[2] < lw - 0.5
                                     or rect[3] < lh - 0.5):
                fx, fy, fw, fh = rect
                aspect = self.camera.frame_aspect
                out_w = max(int(width_px), 64)
                out_h = max(int(round(out_w / aspect)), 1)
                full = self.render_image(
                    max(int(round(out_w * lw / fw)), 64), None, overlays,
                    annotations_only, sharp_shadows, transparent, False,
                    defined_shadows=defined_shadows)
                if full is None:
                    return None
                sx = full.width() / lw
                sy = full.height() / lh
                x = int(round(fx * sx))
                y = int(round(fy * sy))
                w = min(int(round(fw * sx)), full.width() - x)
                h = min(int(round(fh * sy)), full.height() - y)
                image = full.copy(x, y, w, h)
                if (image.width(), image.height()) != (out_w, out_h):
                    image = image.scaled(out_w, out_h, Qt.IgnoreAspectRatio,
                                         Qt.SmoothTransformation)
                return image
        width_px = max(int(width_px), 64)
        if height_px is None:
            height_px = max(int(round(width_px * lh / lw)), 64)
        else:
            height_px = max(int(height_px), 64)

        prev_fbo = self._scene_fbo
        prev_size = self._fbo_size
        view_shadow = None
        self.makeCurrent()
        from PySide6.QtGui import QOpenGLContext
        if QOpenGLContext.currentContext() is None:
            # The widget's context is not up yet (asked for a picture before
            # its first frame): an FBO made with no context current crashes.
            return None
        try:
            self._export_size = (width_px, height_px)
            self._export_transparent = transparent
            self._export_defined_shadows = bool(defined_shadows)
            if sharp_shadows and self._sun_dir_now() is not None:
                view_shadow = (self._shadow_fbo, self._shadow_key)
                self._shadow_fbo = self._shadow_key = None
                self._shadow_size = self._export_shadow_size()
            try:
                self.paintGL()
                image = self._scene_fbo.toImage()   # resolves MSAA itself
            finally:
                if view_shadow is not None:
                    # Freed here, with the context current; the view's own
                    # map was never touched and is reused as it was.
                    self._shadow_fbo = None
                    self._shadow_fbo, self._shadow_key = view_shadow
                    self._shadow_size = self._SHADOW_MAP_SIZE
                self._export_size = None
                self._export_transparent = False
                self._export_defined_shadows = False
                # Drop the big export FBO (destroyed here, context current)
                # and put the on-screen one back.
                self._scene_fbo = prev_fbo
                self._fbo_size = prev_size
        finally:
            self.doneCurrent()

        if defined_shadows and not annotations_only:
            hard = self._hard_shadow_overlay(width_px, height_px)
            if hard is not None:
                painter = QPainter(image)
                painter.drawImage(0, 0, hard)
                painter.end()
        if overlays:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            # Overlay drawing works in logical widget pixels
            # (_world_to_pixel); the scale maps it onto the hi-res image,
            # thickening lines and text proportionally.
            painter.scale(width_px / lw, height_px / lh)
            if not annotations_only:
                # A sheet frame wants the model's annotations (the usual
                # convention for sheets: dimensions and texts) but never the guides or
                # the section-plane frames.
                self._draw_guides(painter)
                self._draw_section_planes(painter)
                self._draw_section_box(painter, handles=False)
                self._draw_geo_surfaces(painter)
                self._draw_geo_paths(painter)
                self._draw_geo_points(painter)
            self._draw_dimensions(painter)
            self._draw_text_labels(painter)
            painter.end()
        # Repaint the widget — when it shows: a sheet's frames render here
        # with the composer over the model window, and repainting that
        # covered window waits ~1 s on the compositor per frame (19-11).
        win = self.window()
        later = getattr(win, "update_viewport_when_seen", None)
        if later is not None and getattr(win, "viewport", None) is self:
            later()
        else:
            self.update()
        return image

    def _sync_axes(self) -> None:
        """Make the drawing axes the current context's (issue #44) — the
        world's at the top level, the open group's own inside it."""
        from core import axes as _axes
        _axes.sync(getattr(self.scene, "drawing_frame", None))

    def _sync_projection(self) -> None:
        """Tell the quick buttons when the projection changed. Scenes,
        saved views, the geo path and the composer all set the camera's
        fields directly, so the check runs on every paint: whatever set
        it, the next frame shows it and the buttons follow."""
        mode = self.camera.projection_mode()
        if mode != getattr(self, "_shown_projection", None):
            self._shown_projection = mode
            self.projectionChanged.emit(mode)

    def _sync_depth_reach(self) -> None:
        """Tell the camera what the view holds, for the depth range of a
        parallel view (``OrbitCamera.parallel_depth``, issue #874): the
        model's box, the reference images and figures, and the drawing
        axes' origin. ``None`` — the old ±far range — while a base map or
        a survey shows, whose extent the model's box does not know."""
        cam = self.camera
        if cam.perspective:
            return                       # perspective does not read it
        sc = self.scene
        layer = getattr(sc, "tile_layer", None)
        survey = getattr(sc, "photo_mesh", None)
        if (layer is not None and getattr(layer, "visible", False)) \
                or (survey is not None and getattr(survey, "visible", False)) \
                or any(getattr(c, "visible", False)
                       for c in getattr(sc, "point_clouds", None) or ()):
            cam.depth_reach = None
            return
        from core import axes as _axes
        lo, hi = sc.bounds()
        pts = [_axes.ORIGIN]
        if lo is not None:
            pts += [lo, hi]
        for im in getattr(sc, "image_planes", None) or ():
            if sc.entity_visible(im):
                pts.extend(im.corners())
        for g in sc.groups:
            if getattr(g, "billboard", False) and sc.entity_visible(g):
                xf = g.xform
                pts.append(QVector3D(xf.column(3).x(), xf.column(3).y(),
                                     xf.column(3).z())
                           if xf is not None else QVector3D())
                pts.append(pts[-1] + QVector3D(0.0, 0.0, 3.0))
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        zs = [p.z() for p in pts]
        a = QVector3D(min(xs), min(ys), min(zs))
        b = QVector3D(max(xs), max(ys), max(zs))
        cam.depth_reach = ((a + b) * 0.5, (b - a).length() * 0.5)

    #: This picture's background is alpha 0 (``render_image``'s ``transparent``).
    _export_transparent = False

    # ---- Setup helpers ------------------------------------------------------
    def _compile_program(self) -> QOpenGLShaderProgram:
        prog = QOpenGLShaderProgram(self)
        ok_v = prog.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(SHADER_DIR / "basic.vert")
        )
        ok_f = prog.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(SHADER_DIR / "basic.frag")
        )
        if not (ok_v and ok_f and prog.link()):
            raise RuntimeError("shader compile/link failed:\n" + prog.log())
        return prog

    def _compile_depth_program(self) -> QOpenGLShaderProgram:
        prog = QOpenGLShaderProgram(self)
        ok_v = prog.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(SHADER_DIR / "depth.vert")
        )
        ok_f = prog.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(SHADER_DIR / "depth.frag")
        )
        if not (ok_v and ok_f and prog.link()):
            raise RuntimeError(
                "depth shader compile/link failed:\n" + prog.log())
        return prog

    def _upload_static(self, data: array):
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.create()
        vbo.bind()
        raw = data.tobytes()
        vbo.allocate(raw, len(raw))
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo, len(data) // 3

    def _create_dynamic(self):
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(24)  # 2 vertices × 3 floats × 4 bytes
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _create_dynamic_color(self):
        """A dynamic VAO/VBO interleaving position (3f) + RGB (3f) per
        vertex — the sky-gradient backdrop (drawn with ``u_use_vcolor``)."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(48)  # 2 vertices × 6 floats × 4 bytes
        stride = 6 * 4
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(self._loc_vcolor)
        self._program.setAttributeBuffer(self._loc_vcolor, GL_FLOAT, 12, 3,
                                         stride)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _create_dynamic_uv(self):
        """A dynamic VAO/VBO interleaving position (3f) + UV (2f) per vertex —
        for textured faces."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(40)  # 2 vertices × 5 floats × 4 bytes
        stride = 5 * 4
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(self._loc_uv)
        self._program.setAttributeBuffer(self._loc_uv, GL_FLOAT, 3 * 4, 2, stride)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _create_dynamic_vcol(self):
        """A dynamic VAO/VBO interleaving position (3f) + RGB (3f) per vertex —
        the batched face pass (one draw call for every colour run)."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(48)  # 2 vertices × 6 floats × 4 bytes
        stride = 6 * 4
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(self._loc_vcolor)
        self._program.setAttributeBuffer(self._loc_vcolor, GL_FLOAT, 3 * 4, 3,
                                         stride)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _get_texture(self, path: str):
        """GL texture for an image ``path``, cached on the viewport. Returns the
        :class:`QOpenGLTexture` (Repeat wrap, linear+mipmap) or ``None`` if the
        image can't be loaded."""
        cache = getattr(self, "_tex_cache", None)
        if cache is None:
            cache = self._tex_cache = {}
        if path in cache:
            return cache[path]
        decoded = _decoded_texture(path)
        tex = None
        if decoded is not None:
            img, cutout = decoded
            tex = QOpenGLTexture(img)           # already mirrored
            tex.setWrapMode(QOpenGLTexture.Repeat)
            tex.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
            tex.setMagnificationFilter(QOpenGLTexture.Linear)
            if cutout:
                tex.setMinificationFilter(QOpenGLTexture.Linear)
                tex._cutout = True
        cache[path] = tex
        return tex

    def _texture_avg_color(self, path: str) -> tuple[float, float, float]:
        """Average colour of a texture image — the "Shaded" face style
        shows the material COLOUR instead of its texture. Cached per path."""
        cache = getattr(self, "_tex_avg_cache", None)
        if cache is None:
            cache = self._tex_avg_cache = {}
        c = cache.get(path)
        if c is None:
            img = QImage(path)
            if img.isNull():
                c = (0.78, 0.78, 0.78)
            else:
                small = img.scaled(4, 4, Qt.IgnoreAspectRatio,
                                   Qt.SmoothTransformation)
                rs = gs = bs = n = 0
                for yy in range(small.height()):
                    for xx in range(small.width()):
                        px = small.pixelColor(xx, yy)
                        rs += px.red()
                        gs += px.green()
                        bs += px.blue()
                        n += 1
                c = ((rs / (255.0 * n), gs / (255.0 * n), bs / (255.0 * n))
                     if n else (0.78, 0.78, 0.78))
            cache[path] = c
        return c

    def forget_uploads(self) -> None:
        """Free what this document has on the GPU, per prototype, for a
        context about to go; its bakes and pick index stay, in plain memory."""
        draws = getattr(self, "_proto_draw", None)
        if draws and self.context() is not None:
            self.makeCurrent()                # GPU objects need the context
            try:
                for entry in draws.values():
                    self._destroy_proto_draw_entry(entry)
            finally:
                self.doneCurrent()
        if draws:
            draws.clear()
        self._proto_draw_fast = None
        self._frozen_cache_version = None
        self._slot_layout = None

    def reset_document_caches(self, keep_bakes: bool = False) -> None:
        """Forget the previous document's chunks at the document boundary.

        ``keep_bakes``: only the GL side goes — a viewport moving to another
        parent gets a new context and must upload again, but its scene's
        shared bakes (:data:`_SHARED_BAKES`, CPU arrays) are as good as
        before, and the views that join it in the grid draw from them.

        The chunk caches are keyed by ``id()`` of groups and meshes and were
        never emptied: every New / Open kept the old document's chunks — and,
        through their pick arrays, its Face objects and meshes — alive. The
        release check measured it on the Plaza Yanque (25-09-2026): five
        reopenings of the same document, 617 → 1277 MB, 887 → 3219 chunks,
        71 000 → 135 000 live faces for a 71 000-face model. Opening a
        document also slowed down reopen after reopen (the garbage collector
        walking the dead ones). And a CPython id() reused by a new group
        could meet an old entry — the composer's lesson with frames."""
        self._pick_warm = None               # its threads end on their own
        self._inst_obb = None
        self._pick_warm_due = False
        edge_renderer = getattr(self, "_edge_renderer", None)
        if edge_renderer is not None and self.context() is not None:
            self.makeCurrent()
            try:
                edge_renderer.clear()
            finally:
                self.doneCurrent()
        draws = getattr(self, "_proto_draw", None)
        if draws and self.context() is not None:
            self.makeCurrent()                # GPU objects need the context
            try:
                for entry in draws.values():
                    self._destroy_proto_draw_entry(entry)
            finally:
                self.doneCurrent()
        for name in self._DOCUMENT_CACHES:
            if keep_bakes and name in _SHARED_BAKES:
                continue
            cache = getattr(self, name, None)
            if isinstance(cache, dict):
                cache.clear()
        self._edges_version = -1          # rebuild the VBOs from nothing
        self._face_transparency_runs = []
        self._transparency_order_key = None
        self._transparency_order = []
        self._frozen_cache_version = None
        self._sil_table = None            # holds the old document's bakes
        self._pick_cat_memo = None        # ...and its pick triangles
        self._fresh_edit_chunk = None     # ...and the open mesh's last bake
        self._verts_preview = None        # a vertex drag cannot outlive it
        self._sel_runs_memo = None        # ...and the selected faces
        self._pick_te_memo = None
        self._pick_loose_memo = None
        self._lazy_native_memo = None
        self._static_occl_memo = None
        self._sil_groups = None
        self._billboard_groups = None
        self._placements_memo = None
        self._epoch_same = None
        self._pick_lazy_memo = None
        self._pick_near_memo = self._edge_near_memo = None
        self._proto_draw_fast = None
        self._arc_mid_cache = None
        self._epoch_hist = None           # ids of the old document's objects
        self._kept_tops_memo = None
        self._kept_place_memo = None
        self._slot_layout = None          # holds its gone objects

    def reset_texture_cache(self) -> None:
        """Return the document's cached GL textures to the driver.

        ``_get_texture`` uploads lazily and remembers forever, which is right
        WITHIN a document — but nothing ever emptied it, so a long session of
        opening textured models only ever grew VRAM (the same class of leak
        CLAUDE.md measured at 0.42 GB for one survey's tile atlases).
        File ▸ New / Open call this at the document boundary: the old
        document's pictures go back to the driver, and whatever the new one
        actually shows re-uploads on demand at first paint."""
        self.reset_document_caches()
        cache = getattr(self, "_tex_cache", None)
        if not cache:
            return
        # Same contract as reset_tiles: destroying GL textures needs the
        # context current — this runs from menu handlers, not paintGL.
        self.makeCurrent()
        try:
            for tex in cache.values():
                if tex is not None:
                    tex.destroy()
        finally:
            self.doneCurrent()
        cache.clear()
        self.update()

    #: GL objects the frame creates on first use, outside initializeGL —
    #: dropped (not destroyed: their context is gone) when it re-runs.
    _LAZY_GL = ("_img_vao", "_img_vbo",
                "_pv_edges_vao", "_pv_edges_vbo", "_pv_vcol_vao",
                "_pv_vcol_vbo", "_pv_tex_vao", "_pv_tex_vbo",
                "_pv_bent_vao", "_pv_bent_vbo", "_pv_dots_vao",
                "_pv_dots_vbo", "_pv_sel_e_vao", "_pv_sel_e_vbo",
                "_pv_plain_e_vao", "_pv_plain_e_vbo",
                "_ghost_edges_vao", "_ghost_edges_vbo", "_ghost_vcol_vao",
                "_ghost_vcol_vbo", "_ghost_tex_vao", "_ghost_tex_vbo",
                "_depth_fbo", "_scene_fbo", "_shadow_fbo", "_depth_snap",
                "_fine_shadow_fbo", "_fig_shadow_fbo",
                "_frame_cache_fbo", "_frame_cache", "_edge_renderer",
                "_cloud_program", "_cloud_gpu")

    def _forget_context_objects(self) -> None:
        """Forget every lazily made GL object (see ``_LAZY_GL``) and the
        per-prototype draw entries (their VAOs and buffers): the next frame
        makes them again in the current context."""
        renderer = getattr(self, "_edge_renderer", None)
        forget = getattr(renderer, "forget_context", None)
        if callable(forget):
            forget()
        for name in self._LAZY_GL:
            if getattr(self, name, None) is not None:
                setattr(self, name, None)
        self._frame_cache_prev_mvp = None   # the kept picture is forgotten
        self._fbo_size = (0, 0)
        if getattr(self, "_proto_draw", None):
            self._proto_draw = {}
        self._forget_frame_records()

    def _forget_frame_records(self) -> None:
        """Drop the recorded instanced passes, the native replayer and the
        frame's batches. A tape holds the context's own function tables
        (``extraFunctions()``): kept past the context, PySide handed that
        stale wrapper back for a NEW object made at the same address — a
        later viewport's ``context()`` came back as a QOpenGLExtraFunctions
        and initializeGL failed (1 test run in ~10)."""
        for name in ("_lean_faces_rec", "_lean_edges_rec",
                     "_gl_replay_memo", "_inst_frame_memo",
                     "_frame_instanced"):
            if getattr(self, name, None) is not None:
                setattr(self, name, None)

    def release_gl_textures(self) -> None:
        """Free every GL texture while the context can still take them back.

        Connected to the context's ``aboutToBeDestroyed`` — the one moment
        Qt guarantees for GL cleanup. Without it every texture alive at exit
        leaked with a "Texture has not been destroyed" warning each (harmless
        at process exit, real if the context is ever torn down and recreated
        mid-session, e.g. on reparenting)."""
        self._forget_frame_records()
        self.makeCurrent()
        try:
            watermarks = getattr(self, "_watermark_textures", None)
            if watermarks:
                for _key, texture in watermarks.values():
                    texture.destroy()
                watermarks.clear()
            cache = getattr(self, "_tex_cache", None)
            if cache:
                for tex in cache.values():
                    if tex is not None:
                        tex.destroy()
                cache.clear()
            tiles = getattr(self, "_tile_textures", None)
            if tiles:
                for tex in tiles.values():
                    if tex is not None:
                        tex.destroy()
                tiles.clear()
            terrain = getattr(self, "_terrain_texture", None)
            if terrain is not None:
                terrain.destroy()
                self._terrain_texture = None
            self._release_photo_textures_unsafe()
            if getattr(self, "_ao", None) is not None:
                self._ao.release()
                self._ao = None
        finally:
            self.doneCurrent()

    def _upload_vbo(self, vbo, slot: str, parts, empty: int = 24) -> int:
        """Put ``b"".join(parts)`` in ``vbo``, re-sending only the parts
        that actually changed. Returns the total byte length.

        Every scene-version bump re-uploaded each buffer whole, so an edit
        inside one group re-sent the entire model each drag frame — on
        piscina.igz that is ~25 MB of edges plus more of faces, and the
        telemetry read ``sync=197ms`` against ``faces=11ms edges=7ms``: the
        frame was the upload, not the drawing.

        A part equal to the one the GPU holds at the same offset is not
        sent. Chunk buffers are cached objects, so that comparison is an
        identity hit for every group that did not change; the freshly built
        loose block falls back to a bytes compare, which is memcmp and still
        an order of magnitude under the transfer it saves. The buffer is
        over-allocated so a growing tail usually fits without a reallocation
        (which would discard everything the GPU held)."""
        sizes = [len(p) for p in parts]
        total = sum(sizes)
        prev = self._vbo_parts.get(slot)
        cap = prev[1] if prev is not None else 0
        vbo.bind()
        if prev is not None and total <= cap and len(prev) > 2:
            # Each part is sent unless the GPU holds it already, at the very
            # same offset: an object moved, deleted (its zeros) or pasted
            # into the room left for it sends its own part, not the tail
            # after it. Joining the whole buffer to send its tail was most
            # of putting an object down on the plant of #158 (~0.6 s).
            held = {}
            off = 0
            for b, n in zip(prev[0], prev[2]):
                if n:
                    held[off] = b
                off += n
            off = 0
            for a, n in zip(parts, sizes):
                if n:
                    b = held.get(off)
                    if not (b is not None and (a is b or (len(b) == n
                                                          and a == b))):
                        vbo.write(off, a, n)
                        self._gpu_epoch = getattr(self, "_gpu_epoch", 0) + 1
                off += n
        else:
            if total > cap:
                cap = max(int(total * 1.25) + 4096, empty)
                vbo.allocate(cap)      # reserve; a realloc keeps no contents
            if total:
                vbo.write(0, b"".join(parts), total)
            self._gpu_epoch = getattr(self, "_gpu_epoch", 0) + 1
        vbo.release()
        self._vbo_parts[slot] = (list(parts), cap, sizes)
        return total
