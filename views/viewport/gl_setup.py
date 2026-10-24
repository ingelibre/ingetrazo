# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""GL context lifecycle: scene FBO, shader programs, buffers, textures and their release."""
from __future__ import annotations

from array import array
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QOpenGLFunctions, QPainter
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject,
                              QOpenGLFramebufferObjectFormat, QOpenGLShader, QOpenGLShaderProgram,
                              QOpenGLTexture, QOpenGLVertexArrayObject)
from views.viewport._support import (GL_FLOAT, GL_DEPTH_TEST, GL_BLEND, GL_SRC_ALPHA,
                                     GL_ONE_MINUS_SRC_ALPHA, GL_LEQUAL, SHADER_DIR)


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
        from core.glinfo import read_gl_info, write_gl_report
        self.gl_info = read_gl_info(self._gl)
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication
        self.gl_info["platform"] = QGuiApplication.platformName()
        _app = QCoreApplication.instance()
        if _app is not None:
            self.gl_info["fallback"] = _app.property("gl_fallback") or ""
        write_gl_report(self.gl_info)
        self.glReady.emit(self.gl_info)
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
        self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        self._program = self._compile_program()
        self._loc_mvp = self._program.uniformLocation("u_mvp")
        self._loc_color = self._program.uniformLocation("u_color")
        self._loc_back_color = self._program.uniformLocation("u_back_color")
        self._loc_fade = self._program.uniformLocation("u_fade")
        self._loc_fade_color = self._program.uniformLocation("u_fade_color")
        self._loc_pos = self._program.attributeLocation("a_pos")
        self._loc_uv = self._program.attributeLocation("a_uv")
        self._loc_use_tex = self._program.uniformLocation("u_use_texture")
        self._loc_tex = self._program.uniformLocation("u_tex")
        self._loc_vcolor = self._program.attributeLocation("a_color")
        self._loc_use_vcolor = self._program.uniformLocation("u_use_vcolor")
        self._loc_opacity = self._program.uniformLocation("u_opacity")
        self._loc_hard_cutout = self._program.uniformLocation("u_hard_cutout")
        self._loc_shade = self._program.uniformLocation("u_shade")
        # Instanced pass: re-shade the prototype's baked tones for the
        # rotation of each copy (#482), against the bake's own light.
        self._loc_reshade = self._program.uniformLocation("u_reshade")
        self._program.bind()
        self._program.setUniformValue(self._loc_reshade, 0)
        self._program.setUniformValue(
            self._program.uniformLocation("u_light_fixed"), self._LIGHT)
        self._program.release()
        # Per-instance model matrix columns (P2 instanced components).
        self._loc_inst = [self._program.attributeLocation(f"a_inst{i}")
                          for i in range(4)]
        self._loc_clip_plane = self._program.uniformLocation("u_clip_plane")
        self._loc_clip_enable = self._program.uniformLocation("u_clip_enable")
        # Sun shadows (core/sun.py): sampling uniforms on the main program,
        # plus the tiny depth-only program the shadow map renders with.
        self._loc_shadow_enable = self._program.uniformLocation(
            "u_shadow_enable")
        self._loc_shadow_map = self._program.uniformLocation("u_shadow_map")
        self._loc_light_vp = self._program.uniformLocation("u_light_vp")
        self._loc_shadow_dark = self._program.uniformLocation("u_shadow_dark")
        self._loc_shadow_bias = self._program.uniformLocation("u_shadow_bias")
        self._loc_sun_dir = self._program.uniformLocation("u_sun_dir")
        self._loc_shadow_overlay = self._program.uniformLocation(
            "u_shadow_overlay")
        self._loc_stipple = self._program.uniformLocation("u_stipple")
        self._loc_viewport_px = self._program.uniformLocation("u_viewport_px")
        self._loc_dash_px = self._program.uniformLocation("u_dash_px")
        self._depth_program = self._compile_depth_program()
        self._loc_d_mvp = self._depth_program.uniformLocation("u_mvp")
        self._loc_d_clip_plane = self._depth_program.uniformLocation(
            "u_clip_plane")
        self._loc_d_clip_enable = self._depth_program.uniformLocation(
            "u_clip_enable")
        self._loc_d_use_tex = self._depth_program.uniformLocation(
            "u_use_texture")
        self._loc_d_tex = self._depth_program.uniformLocation("u_tex")
        self._shadow_fbo = None
        self._shadow_key = None
        self._shadow_vp = None

        # Axes rebuilt per frame (dash spacing scales with zoom), so dynamic.
        self._axes_vao, self._axes_vbo = self._create_dynamic()
        self._guides_vao, self._guides_vbo = self._create_dynamic()
        self._guides_cache = None
        self._axes_spans: dict = {}

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
        self._terrain_vao, self._terrain_vbo = self._create_dynamic_uv()
        self._photo_vao, self._photo_vbo = self._create_dynamic_uv()

    def resizeGL(self, w: int, h: int) -> None:
        # Qt passes framebuffer-pixel sizes here (already scaled by DPR), so
        # this is the authoritative source for FBO and viewport dimensions.
        if self._gl is None:
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
                     annotations_only: bool = False) -> Optional["QImage"]:
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
        misplaced under a composer camera."""
        if self._gl is None or self._program is None:
            return None
        lw = max(self.width(), 1)
        lh = max(self.height(), 1)
        width_px = max(int(width_px), 64)
        if height_px is None:
            height_px = max(int(round(width_px * lh / lw)), 64)
        else:
            height_px = max(int(height_px), 64)

        prev_fbo = self._scene_fbo
        prev_size = self._fbo_size
        self.makeCurrent()
        try:
            self._export_size = (width_px, height_px)
            try:
                self.paintGL()
                image = self._scene_fbo.toImage()   # resolves MSAA itself
            finally:
                self._export_size = None
                # Drop the big export FBO (destroyed here, context current)
                # and put the on-screen one back.
                self._scene_fbo = prev_fbo
                self._fbo_size = prev_size
        finally:
            self.doneCurrent()

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
                self._draw_geo_surfaces(painter)
                self._draw_geo_paths(painter)
                self._draw_geo_points(painter)
            self._draw_dimensions(painter)
            self._draw_text_labels(painter)
            painter.end()
        self.update()                               # repaint the widget
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
        img = QImage(path)
        tex = None
        if not img.isNull():
            tex = QOpenGLTexture(img.mirrored())  # OBJ/.skp V is bottom-up
            tex.setWrapMode(QOpenGLTexture.Repeat)
            tex.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
            tex.setMagnificationFilter(QOpenGLTexture.Linear)
            # Foliage cutouts (low alpha coverage): mip-averaged alpha plus
            # atlas bleed erase or darken the leaves at distance, and the
            # Bayer dither turns the rest into ghost speckle. Tag them: the
            # textured passes sample the top level only and cut hard at 0.5
            # — crisp cutout vegetation at every zoom.
            if img.hasAlphaChannel():
                small = img.scaled(64, 64).convertToFormat(
                    QImage.Format_Alpha8)
                import numpy as _np
                al = _np.frombuffer(small.constBits(), _np.uint8,
                                    count=small.height()
                                    * small.bytesPerLine())
                cov = float((al > 128).mean()) if len(al) else 1.0
                if cov < 0.6:
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

    def reset_document_caches(self) -> None:
        """Forget the previous document's chunks at the document boundary.

        The chunk caches are keyed by ``id()`` of groups and meshes and were
        never emptied: every New / Open kept the old document's chunks — and,
        through their pick arrays, its Face objects and meshes — alive. The
        release check measured it on the Plaza Yanque (25-09-2026): five
        reopenings of the same document, 617 → 1277 MB, 887 → 3219 chunks,
        71 000 → 135 000 live faces for a 71 000-face model. Opening a
        document also slowed down reopen after reopen (the garbage collector
        walking the dead ones). And a CPython id() reused by a new group
        could meet an old entry — the composer's lesson with frames."""
        draws = getattr(self, "_proto_draw", None)
        if draws and self.context() is not None:
            self.makeCurrent()                # GPU objects need the context
            try:
                for entry in draws.values():
                    self._destroy_proto_draw_entry(entry)
            finally:
                self.doneCurrent()
        for name in self._DOCUMENT_CACHES:
            cache = getattr(self, name, None)
            if isinstance(cache, dict):
                cache.clear()
        self._edges_version = -1          # rebuild the VBOs from nothing
        self._frozen_cache_version = None
        self._sil_table = None            # holds the old document's bakes
        self._sil_groups = None
        self._billboard_groups = None
        self._placements_memo = None
        self._epoch_same = None
        self._pick_lazy_memo = None
        self._pick_near_memo = None
        self._proto_draw_fast = None

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
                "_ghost_edges_vao", "_ghost_edges_vbo", "_ghost_vcol_vao",
                "_ghost_vcol_vbo", "_ghost_tex_vao", "_ghost_tex_vbo",
                "_depth_fbo", "_scene_fbo", "_shadow_fbo", "_depth_snap")

    def _forget_context_objects(self) -> None:
        """Forget every lazily made GL object (see ``_LAZY_GL``) and the
        per-prototype draw entries (their VAOs and buffers): the next frame
        makes them again in the current context."""
        for name in self._LAZY_GL:
            if getattr(self, name, None) is not None:
                setattr(self, name, None)
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
        finally:
            self.doneCurrent()

    def _upload_vbo(self, vbo, slot: str, parts, empty: int = 24) -> int:
        """Put ``b"".join(parts)`` in ``vbo``, re-sending only the tail that
        actually changed. Returns the total byte length.

        Every scene-version bump re-uploaded each buffer whole, so an edit
        inside one group re-sent the entire model each drag frame — on
        piscina.igz that is ~25 MB of edges plus more of faces, and the
        telemetry read ``sync=197ms`` against ``faces=11ms edges=7ms``: the
        frame was the upload, not the drawing.

        Parts that compare equal form a prefix the GPU already holds. Chunk
        buffers are cached objects, so that comparison is an identity hit for
        every group that did not change; the freshly built loose block falls
        back to a bytes compare, which is memcmp and still an order of
        magnitude under the transfer it saves. The buffer is over-allocated so
        a growing tail usually fits without a reallocation (which would
        discard the prefix along with everything else)."""
        raw = b"".join(parts)
        total = len(raw)
        prev = self._vbo_parts.get(slot)
        keep = 0
        cap = prev[1] if prev is not None else 0
        if prev is not None and total <= cap:
            for a, b in zip(parts, prev[0]):
                if a is b or a == b:
                    keep += len(a)
                else:
                    break
            keep = min(keep, total)
        vbo.bind()
        if total > cap:
            cap = max(int(total * 1.25) + 4096, empty)
            vbo.allocate(cap)      # reserve; a realloc keeps no contents
            keep = 0
        if total > keep:
            vbo.write(keep, raw[keep:], total - keep)
        vbo.release()
        self._vbo_parts[slot] = (list(parts), cap)
        return total
