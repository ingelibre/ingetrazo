# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Frame rendering: the paintGL passes, shading, previews, hidden ghosts, hover and silhouettes."""
from __future__ import annotations

import math
import time as _time_mod
from array import array
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import (QImage, QMatrix4x4, QPainter, QVector2D, QVector3D,
                           QVector4D)
from PySide6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLTexture)
from core.group import Group
from core.mesh import Edge, Face
from core.style import (DEFAULT_BACK_COLOR, MONOCHROME_GLASS_RGB,
                        effective_back_color, base_face_mode, xray_enabled)
from core.materials import material_sig as _material_sig
from views.viewport._support import (_PERF, _NO_BACK_TINT, _plog, GL_LINES,
                                     GL_CLIP_DISTANCE0,
                                     _shifted_mvp, GL_TRIANGLES,
                                     GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
                                     GL_DEPTH_TEST, _MAX_CUT_PLANES,
                                     GL_STENCIL_TEST, GL_STENCIL_BUFFER_BIT,
                                     GL_ALWAYS, GL_EQUAL, GL_KEEP, GL_REPLACE,
                                     AO_FOLIAGE_BIT, GL_BLEND, GL_SRC_ALPHA,
                                     GL_ONE_MINUS_SRC_ALPHA,
                                     GL_POLYGON_OFFSET_FILL, GL_CULL_FACE,
                                     GL_FRONT, GL_BACK, GL_LESS, GL_LEQUAL,
                                     GL_GREATER, GL_FALSE, GL_TRUE,
                                     GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
                                     GL_DRAW_FRAMEBUFFER, GL_NEAREST,
                                     GL_TEXTURE_2D, GL_TEXTURE0, GL_TEXTURE1,
                                     SHADER_DIR, _chunk_uid, _FRAME_CACHE,
                                     _array_bake, _proto_wrapper, _scene_blend,
                                     _paint_of, _ghost_edge_points, _cache_ver,
                                     _content_ver, _batch_instances,
                                     _mt_native, edit_fade_color,
                                     fog_depth_range, effective_fog_color,
                                     fog_backdrop_strength, fog_backdrop,
                                     fog_sky_colors, XRAY_HIDDEN_EDGE_FADE,
                                     selection_dot_color, _box_edges,
                                     _axes_vertices, _axes_vertices_key,
                                     _box_edge_vertices,
                                     shown_guides, _guide_vertices,
                                     _baked_bytes, _NO_PAINT)

#: The Viewport class, set by views/viewport/__init__.py once it exists: a
#: method here that names ``Viewport.X`` reads (and writes) the class itself.
Viewport = None


def _segment_bytes(segments) -> bytes:
    """``[(a, b), …]`` world segments as the float32 ``a.xyz, b.xyz`` bytes
    a line VBO takes."""
    data = array("f")
    for a, b in segments:
        data.extend([a.x(), a.y(), a.z(), b.x(), b.y(), b.z()])
    return data.tobytes()


def _sweep_lines_match(nat, sweeps) -> bool:
    """Whether the engine's wireframe of ``sweeps`` (``(rings, off, …)``
    each, see tools.pushpull._sweep_spec) is the very bytes Python draws,
    at the push's own curve threshold and at others."""
    from tools.pushpull import _sweep_arrays, sweep_segments
    import core._native as _native
    for cos in (0.85, -1.0, 0.99999):
        pairs = [(list(r), [p + off for p in r])
                 for rings, off, _c, _w in sweeps for r in rings]
        want = _segment_bytes(sweep_segments(pairs, cos))
        pos, sizes, counts, off3, _c, _w, _k = _sweep_arrays(sweeps, cos)
        got = nat.preview_sweep_lines(pos, sizes, counts, off3, cos,
                                      _native.qt_hypot())
        if got != want:
            return False
    return True


class RenderMixin:
    """Frame rendering: the paintGL passes, shading, previews, hidden ghosts, hover and silhouettes."""

    #: Off in a view of several (views/multi_view.py) other than the one being
    #: worked in: the model shows there, without the tool in hand's preview.
    tool_preview = True

    #: How many viewports are inside ``paintGL`` right now (a view of
    #: several paints the others from its own). What a paint announces must
    #: not show or hide a widget beside the view: that resizes it in the
    #: middle of its frame, and macOS crashed on the flush after (#1316).
    painting = 0

    def paintGL(self) -> None:
        if Viewport._preview_native_state is None:
            self._schedule_preview_check()
        if getattr(self, "_pick_warm_due", False):
            # After this first frame of a new document, not beside it.
            self._pick_warm_due = False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self, self.start_pick_warmup)
        Viewport.painting += 1
        try:
            if getattr(self, "tool_preview", True):
                Viewport._paint_frame(self)
                return
            tool, self.active_tool = self.active_tool, None
            try:
                Viewport._paint_frame(self)
            finally:
                self.active_tool = tool
        finally:
            Viewport.painting -= 1

    def _paint_frame(self) -> None:
        self._tick = getattr(self, "_tick", 0) + 1     # a new epoch memo
        self._note_camera()
        self._depth_clean = None          # see the read-back at the end
        self._sync_axes()
        # Camera from Photo: a stand-in viewport (tests, a context below
        # GL 3.3) may not have it.
        check_photo = getattr(self, "_check_photo", None)
        if check_photo is not None:
            check_photo()
        self._sync_projection()
        if self._program is None:
            if self._gl is not None:          # a context below GL 3.3
                self._gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            return
        self._sync_depth_reach()
        _pt0 = _time_mod.perf_counter() if _PERF else 0.0

        # Render the 3D scene into our own FBO (which has a real depth buffer)
        # then blit the colour to the widget's default framebuffer. Sizes are
        # in framebuffer pixels — using logical (self.width/height) here would
        # blit into a fraction of the widget on HiDPI displays and shift the
        # rendered scene away from the mouse cursor.
        w, h = self._export_size or self._fb_size()
        self._ensure_scene_fbo(w, h)
        default_fbo = self.defaultFramebufferObject()
        self._scene_fbo.bind()
        self._gl.glViewport(0, 0, w, h)

        # Re-establish GL state every frame. QPainter (used for the 2D overlay)
        # leaves GL state in an undefined shape — in particular it tends to
        # disable depth test — so we can't trust state to persist across
        # paintGL calls.
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glDepthMask(GL_TRUE)
        self._gl.glEnable(GL_BLEND)
        _scene_blend(self._gl)
        self._gl.glDisable(GL_CULL_FACE)

        # Effective display style (Styles): the composer's
        # plano_style override maps onto the same face modes; otherwise the
        # scene's active style drives faces, edges and background.
        style = self._effective_style()
        mode = base_face_mode(style)
        self._frame_style = style

        # Section cut: the active plane and the section box's faces
        # (core.section.cut_planes), world-space; the kept side of each is
        # where dot(n, p - origin) <= 0. Applies to model geometry only —
        # sky, axes, terrain, previews and overlays stay uncut.
        from core.section import cut_planes
        self._clip_planes = cut_planes(self.scene)[:_MAX_CUT_PLANES]
        self._clip_vecs = [
            QVector4D(-sp.normal.x(), -sp.normal.y(), -sp.normal.z(),
                      QVector3D.dotProduct(sp.normal, sp.point))
            for sp in self._clip_planes]

        self._gl.glClearDepthf(1.0)
        # The environment follows the far-depth fog, except the transparent
        # export's empty pixels, which must remain premultiplied transparent.
        bg, draw_sky = fog_backdrop(style)
        if self._export_transparent:
            self._gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            self._gl.glClearColor(bg[0], bg[1], bg[2], 1.0)
        self._gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT
                         | GL_STENCIL_BUFFER_BIT)
        # Foliage marking for the ambient occlusion: every opaque fragment
        # that wins the depth test leaves its bit — set by a cutout, cleared
        # by anything else (``_set_cutout``) — so the bit ends up saying
        # whether the surface SEEN there is a leaf. The test always passes:
        # colour and depth come out as ever. Off again at the occlusion.
        self._gl.glEnable(GL_STENCIL_TEST)
        self._gl.glStencilFunc(GL_ALWAYS, 0, 0xFF)
        self._gl.glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE)
        self._gl.glStencilMask(AO_FOLIAGE_BIT)

        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        # Frustum planes for chunk culling — also consumed by the
        # silhouette pass (skip whole chunks that are off screen).
        self._frame_planes = self._frustum_planes(mvp)
        # P0 frame telemetry: coarse per-section CPU times, logged with the
        # cull counters when the frame is slow (INGETRAZO_PERF=1).
        _fseg: dict = {}
        _fprev = _pt0

        def _fmark(name: str) -> None:
            nonlocal _fprev
            if _PERF:
                now = _time_mod.perf_counter()
                _fseg[name] = _fseg.get(name, 0.0) + (now - _fprev) * 1000.0
                _fprev = now

        self._program.bind()
        self._program.setUniformValue(self._loc_mvp, mvp)
        # Instanced-matrix attributes default to IDENTITY for every
        # non-instanced draw (the GL default (0,0,0,1) collapses geometry,
        # and QPainter may clobber generic attribute state — reset per frame).
        li = getattr(self, "_loc_inst", None)
        if li and li[0] >= 0:
            self._gl.glVertexAttrib4f(li[0], 1.0, 0.0, 0.0, 0.0)
            self._gl.glVertexAttrib4f(li[1], 0.0, 1.0, 0.0, 0.0)
            self._gl.glVertexAttrib4f(li[2], 0.0, 0.0, 1.0, 0.0)
            self._gl.glVertexAttrib4f(li[3], 0.0, 0.0, 0.0, 1.0)
        # Solid-colour by default; the textured-face pass flips this on.
        self._program.setUniformValue(self._loc_use_tex, 0)
        self._program.setUniformValue(self._loc_stipple, 0)
        self._program.setUniformValue(self._loc_tex, 0)  # sampler → unit 0
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._program.setUniformValue(self._loc_material_opaque, 0)
        self._program.setUniformValue1f(self._loc_xray_opacity, 1.0)
        self._program.setUniformValue1f(self._loc_shade, 1.0)
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._program.setUniformValue1f(self._loc_fade, 0.0)
        # The backdrop is at infinity and has no world-space depth.  Fog is
        # armed only after it has drawn, for the actual 3D scene below.
        self._program.setUniformValue(self._loc_fog_enable, 0)

        # Sky / ground backdrop with a horizon anchored to the camera pitch —
        # premium modeller feel. Fixed on zoom (it's the point at infinity),
        # moves only on orbit. Skipped over the base map / terrain (which supply
        # their own ground). Fog is armed for geometry afterward (#1139).
        if (self.plano_style is None and (style.sky or style.ground is not None)
                and not self._export_transparent
                and not self._base_map_showing()
                and not self._terrain_showing()
                and not self._photo_showing()
                and getattr(self, "photo_view", None) is None):
            self._draw_sky(mvp)
            self._program.setUniformValue(self._loc_mvp, mvp)
        # Camera from Photo: the photo is the backdrop.
        if (getattr(self, "photo_view", None) is not None
                and not self._export_transparent):
            self._draw_photo_backdrop(mvp)
        self._apply_fog_uniforms(style)

        # Base-map tiles (Track G) — the ground image, drawn before the grid so
        # the grid lines read on top of the imagery. Depth-write OFF: it's a
        # backdrop, geometry always draws over it.
        self._draw_style_watermarks(style, "background", w, h)
        self._render_tiles()

        # 3D draped terrain (Track G, G2 full) — real depth-tested relief that
        # replaces the flat map when enabled.
        self._render_terrain()

        # Photogrammetric survey (Track G, G6) — the user's own flight, drawn
        # after the DEM terrain so the real capture wins where both exist.
        self._render_photo_mesh()

        # Imported reference images (a scanned plan, a facade photo). Last of
        # the reference layers and before any model geometry: they are what
        # the user draws ON TOP of.
        if self.scene.edit_group is not None:
            # One colour for every faded pass (images, loose, grouped,
            # instanced, face-me figures); set before the first of them.
            self._program.setUniformValue(
                self._loc_fade_color, QVector3D(*edit_fade_color(
                    style.background)))
        if not self._style_ground_visible(style):
            self._draw_image_planes()
        _fmark("ground")

        # No grid — the infinite axes are the spatial reference.

        # Persistent edges + faces
        self._sync_edges()
        _fmark("sync")

        # Sun shadow map — AFTER the sync, so the consolidated VBOs hold
        # THIS frame's geometry; cached across frames by geometry+sun (it is
        # camera-independent: orbit and zoom reuse it). The pass borrows the
        # FBO/program bindings; this block restores them and binds the map
        # on texture unit 1 for the geometry passes to sample.
        self._frame_shadow = (self._ensure_shadow_map(mvp)
                              if mode in ("textures", "shaded",
                                          "hidden_line", "monochrome")
                              else None)
        if self._frame_shadow is not None:
            self._scene_fbo.bind()
            self._gl.glViewport(0, 0, w, h)
            self._program.bind()
            self._gl.glActiveTexture(GL_TEXTURE1)
            self._gl.glBindTexture(GL_TEXTURE_2D,
                                   self._frame_shadow.texture())
            self._gl.glActiveTexture(GL_TEXTURE0)
            self._program.setUniformValue(self._loc_shadow_map, 1)
            self._program.setUniformValue(self._loc_light_vp,
                                          self._shadow_vp)
            sh = getattr(self.scene, "shadows", None)
            self._program.setUniformValue1f(
                self._loc_shadow_dark,
                float(getattr(sh, "darkness", 0.55)))
            # Small constant margin on the receiver; the heavy lifting is
            # the slope-scaled bias the CASTER writes (depth.frag) — a
            # constant big enough to silence grazing faces peeled every
            # shadow off its base instead.
            self._program.setUniformValue1f(
                self._loc_shadow_bias, self._shadow_biases(self._shadow_vp)[2])
            self._set_soft_shadow_uniforms()
            sun = getattr(self, "_frame_sun", None) or (0.0, 0.0, 1.0)
            self._program.setUniformValue(
                self._loc_sun_dir, QVector3D(sun[0], sun[1], sun[2]))
        self._program.setUniformValue(self._loc_shadow_enable, 0)
        self._program.setUniformValue(self._loc_shadow_overlay, 0)
        _fmark("shadowmap")

        fc = self._frame_cache_key(mvp, w, h, style, mode)
        settled = self._frame_cache_track(
            fc[0] if fc is not None else tuple(mvp.data()))
        # A drag's previews (the solid a tool previews, the movers of a
        # Move) change on every pointer move while the model does not:
        # with a frame kept they go over it, after the static passes,
        # instead of the whole model being drawn again on each move.
        # Drawn so on every frame, kept or not, so the two come out the
        # same pixel for pixel (tests/test_frame_cache.py).
        self._previews_after = True
        if fc is None:
            self._paint_static(mvp, w, h, style, mode, _fmark,
                               self._hover_entity)
            self._draw_previews_after(mvp)
        else:
            # The model as the last frame left it, when nothing it shows
            # changed (a pointer move): see _frame_cache_key.
            if not self._frame_cache_restore(fc, w, h):
                self._paint_static(mvp, w, h, style, mode, _fmark, None)
                # Keep the picture only once the view has settled: while
                # the camera moves, every frame's key is new, so the copy
                # (~0.8 ms of an orbit frame, issue #944) was stored and
                # never restored. The frame after the last camera move
                # stores instead; a change that is not the camera (a
                # selection, an edit) keeps the same MVP and stores at
                # once, as before.
                if settled:
                    self._frame_cache_store(fc, w, h)
            self._draw_previews_after(mvp)
            self._paint_hover(mvp, w, h)
        # A preview drawn over the kept model writes depth of its own.
        tool = self.active_tool
        provider = getattr(tool, "preview_faces", None) if tool else None
        previews_on = (bool(getattr(self, "_preview_groups", None))
                       or getattr(self, "_verts_preview", None) is not None
                       or (callable(provider) and bool(provider())))
        # The view at rest: measure what it shows for the fitted sun map
        # (#958) — read from the depth the model just left, before the
        # rubber band and the overlay draw over it.
        self._settle_shadow_fit(mvp, w, h)

        # Rubber band preview. Loose drawing tools float it on top (depth test
        # off, so it never z-fights with coincident axes). Push/Pull's solid
        # preview keeps depth testing on, so the forming box's back edges are
        # hidden behind its faces — classic hidden-line removal.
        depth_wire = (
            getattr(self.active_tool, "wireframe_depth_tested", False)
            if self.active_tool is not None
            else False
        )
        if not depth_wire:
            self._gl.glDisable(GL_DEPTH_TEST)
        self._draw_rubber_band()
        if not depth_wire:
            self._gl.glEnable(GL_DEPTH_TEST)

        self._draw_style_watermarks(style, "foreground", w, h)
        self._program.release()

        if self._export_size is not None:
            # Hi-res export: the scene stays in the FBO for render_image to
            # read back; the widget blit and its QPainter overlay don't apply.
            self._scene_fbo.release()
            return

        # The depth this frame just drew, read ONCE for the overlay's
        # annotations (dimensions, leader texts), which ask «is this point
        # hidden?» for every sample of every line — see _occluded_on_screen.
        # A pointer move over the kept model (_frame_cache_key) leaves the
        # depth as it was when nothing over it writes depth — the face's
        # dots do not, the rubber band floats with no depth test, the axes
        # redrawn over the dots fail GL_LESS where they are — and the
        # read-back already made of it is kept: over the plant of #158 it
        # was ~5 ms of every pointer move, reading the same depth again.
        clean = (fc is not None and not depth_wire and not previews_on
                 and not isinstance(getattr(self, "_hover_entity", None),
                                    Edge))
        kept = (clean and getattr(self, "_depth_snap", None) is not None
                and getattr(self, "_depth_snap_of", None) == fc)
        self._depth_clean = fc if clean else None
        if not kept:
            self._depth_snap = None
            if self._annotations_need_depth():
                self._capture_depth(w, h)
        # What the scene FBO now holds: the depth under the cursor can be
        # read from it while the camera stays here (``_depth_world_at``).
        self._painted_view = (tuple(mvp.data()), w, h)

        # Blit colour from our scene FBO to the widget's default framebuffer.
        # We can't use QOpenGLFramebufferObject.blitFramebuffer(None, src) here
        # because in QOpenGLWidget the "default" framebuffer the widget shows
        # is its own internal FBO (returned by defaultFramebufferObject()),
        # NOT the system framebuffer 0. So we bind the read/draw targets by id
        # and call glBlitFramebuffer directly via the GL3+ extra functions.
        extra = self.context().extraFunctions()
        self._gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, self._scene_fbo.handle())
        self._gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, default_fbo)
        extra.glBlitFramebuffer(
            0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT, GL_NEAREST
        )
        self._gl.glBindFramebuffer(GL_FRAMEBUFFER, default_fbo)
        if _PERF:
            _plog("paintGL.gl+blit",
                  (_time_mod.perf_counter() - _pt0) * 1000.0, floor=30.0)
            _ov0 = _time_mod.perf_counter()

        # 2D overlays on top of the OpenGL framebuffer.
        self._draw_overlay()

        if _PERF:
            _plog("paintGL.overlay",
                  (_time_mod.perf_counter() - _ov0) * 1000.0, floor=30.0)
            _dt = (_time_mod.perf_counter() - _pt0) * 1000.0
            _plog("paintGL", _dt)
            # P0 breakdown: per-section CPU ms + cull counters + the
            # input→paint latency of the gesture that triggered this frame.
            if _dt >= 25.0:
                cf, tf, ce = getattr(self, "_cull_stats", (0, 0, 0))
                it = getattr(self, "_input_t", None)
                lat = (f" lat={( _time_mod.monotonic() - it) * 1000.0:.0f}ms"
                       if it is not None else "")
                segs = " ".join(f"{k}={v:.0f}ms" for k, v in _fseg.items())
                _plog("frame", _dt,
                      extra=f"{segs} cull={cf//1000}k/{tf//1000}k"
                            f" tris +{ce//1000}k edges{lat}", floor=0.0)
            self._input_t = None
            st = getattr(self, "_perf_stat", None) or \
                [_time_mod.perf_counter(), 0, 0.0]
            st[1] += 1
            st[2] += _dt
            now = _time_mod.perf_counter()
            if now - st[0] >= 1.0:
                _plog("frames/s", st[2] / max(st[1], 1),
                      extra=f"{st[1]} paints en {now-st[0]:.1f}s (avg ms)",
                      floor=0.0)
                st = [now, 0, 0.0]
            self._perf_stat = st

    def _paint_static(self, mvp, w, h, style, mode, _fmark, hover) -> None:
        """Composite far geometry, the display ground, then near geometry.

        Splitting at Z=0 keeps translucent faces on either side correctly
        layered with the ground, including triangles that cross the plane.
        Unchanged styles retain the original single pass.
        """
        if not self._style_ground_visible(style):
            self._paint_static_half(mvp, w, h, style, mode, _fmark, hover)
            return
        side = 1.0 if self.camera.eye().z() >= 0 else -1.0
        location = self._program.uniformLocation("u_style_ground_clip")

        def clip(z, offset):
            self._style_ground_clip = QVector4D(0, 0, z, offset)
            self._program.setUniformValue(location, self._style_ground_clip)
            self._set_ground_clip_hw(z != 0)

        try:
            if style.ground_transparency > 0:
                clip(-side, -1e-6)
                self._draw_image_planes()
                self._paint_static_half(mvp, w, h, style, mode, _fmark, hover)
            clip(0, 0)
            self._draw_style_ground(mvp, style)
            if self._frame_shadow is not None:
                self._draw_shadow_ground(style)
            clip(side, 1e-6)
            self._draw_image_planes()
            self._paint_static_half(mvp, w, h, style, mode, _fmark, hover)
        finally:
            clip(0, 0)

    def _set_ground_clip_hw(self, on: bool) -> None:
        """Turn the display ground's clip plane (``gl_ClipDistance[7]`` of
        basic.vert) on or off. Only the main program writes that slot: the
        passes of other programs inside a half (ambient occlusion, styled
        edges, which clip the ground themselves) run with it off, as GL
        leaves an enabled distance a shader does not write undefined."""
        on = bool(on)
        if bool(getattr(self, "_ground_clip_hw", False)) == on:
            return
        (self._gl.glEnable if on else self._gl.glDisable)(GL_CLIP_DISTANCE0 + 7)
        self._ground_clip_hw = on

    def _without_ground_clip_hw(self, fn, *args, **kwargs):
        """``fn(...)`` with the ground's clip plane off, then back as it was."""
        was = bool(getattr(self, "_ground_clip_hw", False))
        if was:
            self._set_ground_clip_hw(False)
        try:
            return fn(*args, **kwargs)
        finally:
            if was:
                self._set_ground_clip_hw(True)

    def _paint_static_half(self, mvp, w, h, style, mode, _fmark, hover) -> None:
        """paintGL's passes of the model and what sits in it — faces,
        edges, selection, axes, guides — up to the section cut's edges;
        ``hover`` is the entity under the cursor they highlight (None:
        none, for the frame cache, which draws it after)."""
        # Frustum culling (P1): the consolidated VBOs carry per-chunk draw
        # spans; only spans whose chunk AABB touches the frustum are
        # submitted. Conservative — a missing bbox always draws.
        xray = xray_enabled(style) and mode != "wireframe"
        planes = self._frame_planes
        # Inside a group with the context faded, the buffers hold the
        # surroundings first and the edited group last; the split keeps the
        # two apart so each is drawn with its own opacity.
        # Both splits or neither: a frame that faded the context's edges but
        # not its faces would read as a glitch rather than a mode.
        fading = (self.scene.edit_group is not None
                  and self._edit_rest_mode == "fade"
                  and getattr(self, "_edit_split_e", None) is not None
                  and getattr(self, "_edit_split_f", None) is not None)
        split_f = self._edit_split_f if fading else None
        split_e = self._edit_split_e if fading else None
        spans = getattr(self, "_face_spans", None)
        if spans:
            face_spans, culled_fv = self._visible_spans(spans, planes, split_f)
        else:
            face_spans, culled_fv = [(0, self._faces_count)], 0
        espans = getattr(self, "_edge_spans", None)
        if espans:
            edge_spans, culled_ev = self._visible_spans(espans, planes, split_e)
        else:
            edge_spans, culled_ev = [(0, self._edges_count)], 0
        self._frame_edge_spans = edge_spans
        self._cull_stats = (culled_fv // 3, self._faces_count // 3,
                            culled_ev // 2)

        # Faces — drawn before edges, with polygon offset so coincident
        # boundary edges sit cleanly on top instead of z-fighting.
        self._set_section_clip(True)
        if getattr(self, "_frame_shadow", None) is not None:
            if not self._style_ground_visible(style):
                self._draw_shadow_ground(style)
            self._program.setUniformValue(self._loc_shadow_enable, 1)
        self._program.setUniformValue(self._loc_material_opaque, int(not style.material_transparency))
        self._program.setUniformValue1f(self._loc_xray_opacity, style.xray_opacity / 100.0 if xray else 1.0)
        self._gl.glDepthMask(GL_FALSE if xray else GL_TRUE)
        self._gl.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
        if self._faces_count > 0 and mode != "wireframe":
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            if mode == "hidden_line":
                # Plan style: every face flat in the style's front colour, no
                # rebatch needed — per-vertex colours simply not consulted.
                self._program.setUniformValue(self._loc_use_vcolor, 0)
                fr = style.front_color
                self._set_color(fr[0], fr[1], fr[2], 1.0)
                self._program.setUniformValue(
                    self._loc_back_color, QVector4D(fr[0], fr[1], fr[2], 1.0))
            elif mode == "monochrome":
                # Flat default front colour + the back tint — the classic
                # reversed-face checker (Monochrome style).
                self._program.setUniformValue(self._loc_use_vcolor, 0)
                fr = style.front_color
                self._set_color(fr[0], fr[1], fr[2], 1.0)
                self._set_back_face_color()
            else:
                # Every colour run in ONE draw call: the shaded material
                # colour rides per vertex (a_color). An imported model with
                # hundreds of colour×shade runs paid ~2000 uniform/draw
                # calls per frame.
                self._program.setUniformValue(self._loc_use_vcolor, 1)
                self._set_back_face_color()
            if xray:
                # X-ray: translucent faces that do not occlude — edges stay
                # fully visible because nothing writes depth.
                self._gl.glDepthMask(GL_FALSE)
            self._faces_vao.bind()
            if split_f is None:
                for _vs, _vc in face_spans:
                    self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            else:
                # Context first, washed toward the background but fully
                # opaque and still writing depth (the faded rest of
                # model reads as haze, not as glass); then the group itself
                # at full strength.
                self._program.setUniformValue1f(self._loc_fade,
                                                self.edit_rest_fade)
                for _vs, _vc in face_spans:
                    if _vs < split_f:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
                self._program.setUniformValue1f(self._loc_fade, 0.0)
                for _vs, _vc in face_spans:
                    if _vs >= split_f:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            fstart, fcount = self._fvcol_run
            if fcount:
                # opaque front copies of glass-backed faces: visible only
                # from the front (the translucent back pass owns the rear)
                self._gl.glEnable(GL_CULL_FACE)
                self._gl.glCullFace(GL_BACK)
                self._gl.glDrawArrays(GL_TRIANGLES, fstart, fcount)
                self._gl.glDisable(GL_CULL_FACE)
            self._faces_vao.release()
            if xray:
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_FALSE)
            self._program.setUniformValue(self._loc_use_vcolor, 0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        # Textured faces — same depth/offset treatment, sampling each face's
        # image. One draw per texture (its GL texture bound to unit 0).
        if self._tex_faces_count > 0 and mode in ("hidden_line", "monochrome"):
            # Plan styles: textured faces draw flat like the rest.
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            fr = style.front_color
            self._set_color(fr[0], fr[1], fr[2], 1.0)
            self._tex_faces_vao.bind()
            if mode == "monochrome" and style.material_transparency:
                # Not its translucent runs: they draw with the glass below,
                # or a textured pane came out as a white wall.
                self._gl.glDrawArrays(GL_TRIANGLES, 0, self._tex_opaque_count)
                for _key, start, count in self._back_tex_runs:
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
            else:
                self._gl.glDrawArrays(GL_TRIANGLES, 0, self._tex_faces_count)
            self._tex_faces_vao.release()
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        elif self._tex_faces_count > 0 and mode == "shaded":
            # "Shaded" style: textured faces draw in their texture's
            # AVERAGE colour (the material colour), keeping the run shading.
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._tex_faces_vao.bind()
            run_parts = getattr(self, "_tex_run_parts", None)
            for ri, ((path, shade), start, count) in enumerate(self._tex_runs):
                if not run_parts:
                    vis, subj = [(start, count)], []
                else:
                    vis, subj = self._tex_run_spans(run_parts[ri], planes,
                                                    fading)
                if not vis and not subj:
                    continue
                r, g, b = self._texture_avg_color(path)
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                self._set_color(r, g, b, 1.0)
                for fade, spans in ((self.edit_rest_fade, vis),
                                    (0.0, subj)) \
                        if fading else ((0.0, vis),):
                    if not spans:
                        continue
                    self._program.setUniformValue1f(self._loc_fade, fade)
                    for _vs, _vc in spans:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            self._program.setUniformValue1f(self._loc_fade, 0.0)
            self._tex_faces_vao.release()
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        elif self._tex_faces_count > 0 and mode in ("textures", "xray"):
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._program.setUniformValue(self._loc_use_tex, 1)
            if xray:
                self._gl.glDepthMask(GL_FALSE)
            self._tex_faces_vao.bind()
            run_parts = getattr(self, "_tex_run_parts", None)
            for ri, ((path, shade), start, count) in enumerate(self._tex_runs):
                if not run_parts:
                    vis, subj = [(start, count)], []
                else:
                    vis, subj = self._tex_run_spans(run_parts[ri], planes,
                                                    fading)
                if not vis and not subj:
                    continue
                tex = self._get_texture(path)
                if tex is None:
                    continue
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                self._set_cutout(getattr(tex, "_cutout", False))
                tex.bind(0)
                for fade, spans in ((self.edit_rest_fade, vis),
                                    (0.0, subj)) \
                        if fading else ((0.0, vis),):
                    if not spans:
                        continue
                    self._program.setUniformValue1f(self._loc_fade, fade)
                    for _vs, _vc in spans:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
                tex.release(0)
            self._program.setUniformValue1f(self._loc_fade, 0.0)
            self._set_cutout(False)
            self._tex_faces_vao.release()
            if xray:
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_FALSE)
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._program.setUniformValue(self._loc_use_tex, 0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        # The default back: a painted face shows its material on
        # the side you painted and the style's blue-grey on the other, so
        # the reverse of a wall reads as the reverse. Every face whose back
        # is unpainted — and whose front is opaque; glass, water and a mesh
        # read the same from both sides — is drawn once more here with
        # FRONT culling in the back colour: only its rear fragments arrive,
        # at the depth the face pass already wrote, and LEQUAL lets this
        # later draw win. Plan styles have their own rule (monochrome tints
        # every back, hidden-line none), X-ray keeps the blend clean.
        if (self._dback_count > 0 and mode in ("textures", "shaded")
                and not _NO_BACK_TINT and not xray):
            db_spans = getattr(self, "_dback_spans", None)
            split_db = (getattr(self, "_edit_split_db", None)
                        if fading else None)
            if db_spans:
                db_draw, _c = self._visible_spans(db_spans, planes, split_db)
            else:
                db_draw = [(0, self._dback_count)]
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._gl.glEnable(GL_CULL_FACE)
            self._gl.glCullFace(GL_FRONT)
            self._program.setUniformValue(self._loc_use_vcolor, 0)
            self._program.setUniformValue(self._loc_use_tex, 0)
            self._set_back_face_color()
            self._program.setUniformValue(self._loc_back_shade, 1)
            self._dback_vao.bind()
            if split_db is None:
                for _vs, _vc in db_draw:
                    self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            else:
                self._program.setUniformValue1f(self._loc_fade,
                                                self.edit_rest_fade)
                for _vs, _vc in db_draw:
                    if _vs < split_db:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
                self._program.setUniformValue1f(self._loc_fade, 0.0)
                for _vs, _vc in db_draw:
                    if _vs >= split_db:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            self._dback_vao.release()
            self._gl.glDisable(GL_CULL_FACE)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        # Instanced components (P2): eligible instances draw from their
        # prototype's local VBOs with per-instance matrices — the
        # consolidated passes above excluded them in _sync_edges.
        # The instanced default backs shade the same way (the flag only
        # speaks to back-facing fragments in the back colour; set for the
        # whole call, which the recorded native replay sees too).
        if mode in ("textures", "shaded") and not _NO_BACK_TINT:
            self._program.setUniformValue(self._loc_back_shade, 1)
        self._draw_instanced_faces(mode, style)
        self._program.setUniformValue(self._loc_back_shade, 0)
        # Shadows stop at the face passes: edges, overlays, previews and
        # billboards stay unlit (v1 scope).
        if getattr(self, "_frame_shadow", None) is not None:
            self._program.setUniformValue(self._loc_shadow_enable, 0)

        # Back-side material overrides (faces painted DIFFERENTLY per side,
        # two-sided paint from .skp): drawn with front-face culling so they
        # only show from behind, without the face passes' polygon offset so
        # they win the depth test over the front copy there.
        if (self._back_vcol_run[1] > 0 or self._back_tex_runs) \
                and mode in ("textures", "shaded", "xray"):
            if xray:
                self._gl.glDepthMask(GL_FALSE)
            self._gl.glEnable(GL_CULL_FACE)
            self._gl.glCullFace(GL_FRONT)
            bstart, bcount = self._back_vcol_run
            if bcount:
                self._program.setUniformValue(self._loc_use_vcolor, 1)
                self._faces_vao.bind()
                self._gl.glDrawArrays(GL_TRIANGLES, bstart, bcount)
                self._faces_vao.release()
                self._program.setUniformValue(self._loc_use_vcolor, 0)
            if self._back_tex_runs:
                self._program.setUniformValue(self._loc_use_tex, 1)
                self._tex_faces_vao.bind()
                for (path, shade), start, count in self._back_tex_runs:
                    tex = self._get_texture(path)
                    if tex is None:
                        continue
                    self._program.setUniformValue1f(self._loc_shade, float(shade))
                    self._set_cutout(getattr(tex, "_cutout", False))
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                self._set_cutout(False)
                self._tex_faces_vao.release()
                self._program.setUniformValue1f(self._loc_shade, 1.0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            self._gl.glDisable(GL_CULL_FACE)
            if xray:
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_FALSE)

        if not style.material_transparency or mode == "hidden_line":
            self._draw_face_material_runs(mode, style)
        self._draw_section_fill(mode, style)
        # Ambient occlusion (#954): onto the opaque faces only — the glass
        # below, the billboards, highlights and every edge come after it.
        if (not self._style_ground_visible(style)
                or self._style_ground_clip.w() >= 0):
            self._without_ground_clip_hw(self._apply_ambient_occlusion,
                                         w, h, mode, style)

        # Translucent material runs (.skp trans with useTrans): drawn
        # after everything opaque, blended, depth-tested but not depth-
        # written, so glass/mesh screens show what's behind them.
        if (style.material_transparency and (style.transparency_quality == "nicer" or mode == "shaded")
                and mode in ("textures", "shaded", "xray")):
            self._draw_face_material_runs(mode, style,
                                          sorted_triangles=style.transparency_quality == "nicer")
        elif (self._tcol_runs or self._ttex_runs
                or self._back_tcol_runs or self._back_ttex_runs) \
                and style.material_transparency and mode in ("textures", "shaded", "xray", "monochrome"):
            self._gl.glDepthMask(GL_FALSE)
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            # Monochrome: one flat tone on both sides at each run's opacity,
            # instead of the run's own colour or texture.
            flat = MONOCHROME_GLASS_RGB if mode == "monochrome" else None

            def run_opacity(a):
                self._program.setUniformValue1f(self._loc_opacity, float(a))
                if flat is not None:
                    self._set_color(*flat, float(a))

            if self._tcol_runs or self._back_tcol_runs:
                self._program.setUniformValue(self._loc_use_vcolor,
                                              0 if flat is not None else 1)
                self._faces_vao.bind()
                for a, fc, start, count in self._tcol_runs:
                    run_opacity(a)
                    if fc:
                        # glass-backed front copy: front side only
                        self._gl.glEnable(GL_CULL_FACE)
                        self._gl.glCullFace(GL_BACK)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    if fc:
                        self._gl.glDisable(GL_CULL_FACE)
                if self._back_tcol_runs:
                    # translucent BACK overrides: back side only
                    self._gl.glEnable(GL_CULL_FACE)
                    self._gl.glCullFace(GL_FRONT)
                    for a, start, count in self._back_tcol_runs:
                        run_opacity(a)
                        self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    self._gl.glDisable(GL_CULL_FACE)
                self._faces_vao.release()
                self._program.setUniformValue(self._loc_use_vcolor, 0)
            if self._ttex_runs or self._back_ttex_runs:
                self._program.setUniformValue(self._loc_use_tex,
                                              0 if flat is not None else 1)
                self._tex_faces_vao.bind()
                for (path, shade), a, fc, start, count in self._ttex_runs:
                    tex = None if flat is not None else self._get_texture(path)
                    if tex is None and flat is None:
                        continue
                    run_opacity(a)
                    self._program.setUniformValue1f(
                        self._loc_shade, 1.0 if flat is not None else float(shade))
                    if fc:
                        self._gl.glEnable(GL_CULL_FACE)
                        self._gl.glCullFace(GL_BACK)
                    if tex is not None:
                        tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    if tex is not None:
                        tex.release(0)
                    if fc:
                        self._gl.glDisable(GL_CULL_FACE)
                if self._back_ttex_runs:
                    self._gl.glEnable(GL_CULL_FACE)
                    self._gl.glCullFace(GL_FRONT)
                    for (path, shade), a, start, count in self._back_ttex_runs:
                        tex = (None if flat is not None
                               else self._get_texture(path))
                        if tex is None and flat is None:
                            continue
                        run_opacity(a)
                        self._program.setUniformValue1f(
                            self._loc_shade,
                            1.0 if flat is not None else float(shade))
                        if tex is not None:
                            tex.bind(0)
                        self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                        if tex is not None:
                            tex.release(0)
                    self._gl.glDisable(GL_CULL_FACE)
                self._tex_faces_vao.release()
                self._program.setUniformValue1f(self._loc_shade, 1.0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            self._program.setUniformValue1f(self._loc_opacity, 1.0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
            self._gl.glDepthMask(GL_FALSE if xray else GL_TRUE)

        self._program.setUniformValue(self._loc_material_opaque, 0)
        self._program.setUniformValue1f(self._loc_xray_opacity, 1.0)
        self._gl.glDepthMask(GL_TRUE)
        _scene_blend(self._gl)
        # Face-me billboards (2D people): per-frame textured cutout
        # — skipped on plan sheets and line styles: a coloured cutout person
        # on a technical drawing gives the raster away; scale figures belong
        # to the shaded looks only.
        if self.plano_style is None and mode in ("textures", "shaded", "xray"):
            self._draw_billboards()
            if self._export_size is None:
                # Selection cues never reach an export: the orange box
                # around a selected Sumari came out on the printed sheet
                # (Marco, 2026-09-07).
                self._draw_billboard_outlines()

        # Face highlights (selection + hover) — translucent overlays drawn on
        # top of the cream faces. Same polygon offset as the faces so they sit
        # at matching depth (LEQUAL lets this later draw win); depth-write OFF
        # so the overlay tints without blocking the edges drawn afterwards.
        if (self._sel_faces_count > 0 or hover is not None) \
                and self._export_size is None:      # no selection cues in exports
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._gl.glDepthMask(GL_FALSE)
            if self._sel_faces_count > 0:
                # Selected faces: an opaque DOT pattern, not a tint — the
                # old 35% orange wash over a back face read as just another
                # back face. Each run carries the dot colour for its front
                # and for its back side, picked against that side's paint.
                self._program.setUniformValue(self._loc_stipple, 3)
                self._sel_faces_vao.bind()
                for front, back, start, count in self._sel_faces_spans:
                    self._set_color(*front, 1.0)
                    self._program.setUniformValue(
                        self._loc_back_color, QVector4D(*back, 1.0))
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                self._sel_faces_vao.release()
                self._program.setUniformValue(self._loc_stipple, 0)
            hovered = hover
            if isinstance(hovered, Face) and hovered not in self.scene.selection:
                # The face under the cursor (Select, Push/Pull, Paint,
                # Offset, Follow Me...) wears the same dots as a selected
                # one, so every tool points at a face the same way. An
                # already selected face is skipped: it shows its dots.
                hover_count = self._upload_hover_face(
                    hovered, self._hover_placement)
                if hover_count > 0:
                    front, back = self._selection_dot_colors(hovered)
                    self._set_color(*front, 1.0)
                    self._program.setUniformValue(
                        self._loc_back_color, QVector4D(*back, 1.0))
                    self._program.setUniformValue(self._loc_stipple, 3)
                    self._hover_faces_vao.bind()
                    self._gl.glDrawArrays(GL_TRIANGLES, 0, hover_count)
                    self._hover_faces_vao.release()
                    self._program.setUniformValue(self._loc_stipple, 0)
            self._gl.glDepthMask(GL_TRUE)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        _fmark("faces")
        # Shaded solid preview (Push/Pull box forming as you drag). Drawn after
        # the persistent faces, depth-tested so it occludes geometry behind it
        # and reads as a real solid; its wireframe goes on top via the rubber
        # band below.
        self._set_section_clip(False)
        if not getattr(self, "_previews_after", False):
            self._draw_preview_faces()
            self._draw_groups_preview(mvp)
        self._draw_hidden_ghosts(mvp)

        self._draw_scaffold(mvp, w, h)

        self._set_section_clip(True)
        from core.edge_style import needs_edge_renderer
        styled_edges = needs_edge_renderer(style, self.scene)
        show_edges = (style.edges or mode == "wireframe") and not styled_edges
        ec = style.edge_color
        # Line weight for sheet renders: a GL line is one pixel whatever
        # the DPI (core-profile Mesa clamps glLineWidth), and one pixel at
        # 300 dpi is a 0.085 mm hairline that vanishes on paper and on the
        # composer's scaled preview (Marco, 2026-09-14: «casi no se ven»).
        # The frame asks for a pen in pixels and the pass is redrawn at
        # sub-pixel offsets to reach it — exports only, never the screen.
        _jit_e = self._line_jitter(self._export_edge_px, w, h)
        _jit_p = self._line_jitter(self._export_profile_px, w, h)
        # X-ray draws every edge, but the ones BEHIND a face come out washed
        # toward the background: the faces' depth (never written by their
        # translucent pass) is laid down here, the edges beyond it drawn
        # first in the faded colour, then the ones in front at full strength.
        # From above, an open box keeps every edge dark and a lidded one
        # greys the edges under the lid — you see whether a face is there.
        xray_edges = xray and show_edges
        if xray_edges:
            self._xray_face_depth()
            bg = style.background
            k = XRAY_HIDDEN_EDGE_FADE
            _edge_passes = ((tuple(ec[i] + (bg[i] - ec[i]) * k
                                   for i in range(3)), True),
                            (tuple(ec[:3]), False))
        else:
            _edge_passes = ((tuple(ec[:3]), False),)
        if (show_edges and not xray_edges
                and getattr(style, "model_linetypes", True)):
            self._mask_model_linetype_gaps()
        for (_ecol, _hidden), (_dx, _dy) in (
                (_p, _j) for _p in _edge_passes for _j in _jit_e):
            if xray_edges:
                self._gl.glDepthFunc(GL_GREATER if _hidden else GL_LEQUAL)
                self._gl.glDepthMask(GL_FALSE if _hidden else GL_TRUE)
            if len(_jit_e) > 1:
                self._program.setUniformValue(self._loc_mvp,
                                              _shifted_mvp(mvp, _dx, _dy))
            if self._edges_count > 0 and show_edges:
                self._set_color(*_ecol, 1.0)
                self._edges_vao.bind()
                _espans = getattr(self, "_frame_edge_spans",
                                  ((0, self._edges_count),))
                if split_e is None:
                    for _vs, _vc in _espans:
                        self._gl.glDrawArrays(GL_LINES, _vs, _vc)
                else:
                    # Same two-tier draw as the faces: washed-out
                    # surroundings, then the edited group's own edges at
                    # full strength.
                    self._program.setUniformValue1f(self._loc_fade,
                                                    self.edit_rest_fade)
                    for _vs, _vc in _espans:
                        if _vs < split_e:
                            self._gl.glDrawArrays(GL_LINES, _vs, _vc)
                    self._program.setUniformValue1f(self._loc_fade, 0.0)
                    for _vs, _vc in _espans:
                        if _vs >= split_e:
                            self._gl.glDrawArrays(GL_LINES, _vs, _vc)
                self._edges_vao.release()
            if show_edges:
                self._set_color(*_ecol, 1.0)
                self._draw_instanced_edges()
        if show_edges and getattr(style, "model_linetypes", True):
            self._draw_model_linetype_dashes()
        if xray_edges:
            # Back to X-ray's depth: the faces never occlude, so selected
            # and hovered edges behind them still show.
            self._gl.glDepthFunc(GL_LEQUAL)
            self._gl.glDepthMask(GL_TRUE)
            self._gl.glClear(GL_DEPTH_BUFFER_BIT)
        elif (show_edges and getattr(style, "back_edges", False)
                and mode != "wireframe"):
            self._draw_back_edges(tuple(ec[:3]), w, h)
        if len(_jit_e) > 1:
            self._program.setUniformValue(self._loc_mvp, mvp)

        # Profile (silhouette) edges: soft seams of a curved surface are hidden,
        # except where the surface turns away from the viewer — the cylinder's
        # outline. View-dependent, so rebuilt every frame. An independent
        # style option, not part of Edges: with Edges off and Profiles on a
        # curved surface still shows its outline (#1253).
        if style.profiles:
            sil_count = self._upload_silhouette_edges()
            if sil_count > 0:
                self._set_color(ec[0], ec[1], ec[2], 1.0)
                self._silhouette_vao.bind()
                for _dx, _dy in _jit_p:
                    if _dx or _dy:
                        self._program.setUniformValue(
                            self._loc_mvp, _shifted_mvp(mvp, _dx, _dy))
                    self._gl.glDrawArrays(GL_LINES, 0, sil_count)
                self._silhouette_vao.release()
                if len(_jit_p) > 1:
                    self._program.setUniformValue(self._loc_mvp, mvp)
        if styled_edges:
            from views.edge_renderer import EdgeRenderer
            renderer = getattr(self, "_edge_renderer", None)
            if renderer is None:
                renderer = self._edge_renderer = EdgeRenderer(self)
            self._without_ground_clip_hw(
                renderer.draw, mvp, w, h, style, mode,
                fade_color=edit_fade_color(style.background))
        _fmark("edges")

        # Selected edges (drawn on top, highlighted) — never in an export
        if self._selected_count > 0 and self._export_size is None:
            self._set_color(*self._modeling_color("selected"), 1.0)
            self._selected_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, self._selected_count)
            self._selected_vao.release()
        if self._export_size is None:
            self._draw_locked_selection()

        # Hovered edge — light blue, on top of everything else so it reads as
        # the pick candidate even when it overlaps a selected (orange) edge.
        # A curve segment highlights its whole contour (what a click selects).
        if isinstance(hover, Edge):
            hover_count = self._upload_hover_edge(hover)
            self._set_color(0.30, 0.55, 0.95, 1.0)
            self._hover_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, hover_count)
            self._hover_edges_vao.release()
        self._set_section_clip(False)
        self._draw_section_cut_edges()   # ON the planes — each by the others

    def _draw_scaffold(self, mvp, w, h) -> None:
        """The axes, the guides and the dashed box of the group being
        edited: drawn without writing depth, over the faces."""
        # Axes — long solid positive + evenly-dashed negative per axis.
        # Dash spacing scales with the camera distance so the on-screen density
        # stays stable across zoom. Depth-write OFF so the ground axes don't cull
        # geometry sitting on z=0; drawn BEFORE user edges so an edge along an
        # axis wins the LEQUAL depth test. Rubber-band stays on top (drawn last).
        from core import axes as _axes
        if (self.plano_style is None and self.style_override is None
                and (getattr(self.scene, "show_axes", True)
                     or not _axes.is_world())):
            # No axes on a plan sheet / styled composer frame, nor the
            # world's once Camera ▸ Axes is off (an open group keeps its own).
            spacing = max(self.camera.distance * 0.008, 1e-4)
            # Built and uploaded again only when the spacing or the drawing
            # axes changed: an orbit or a pan keeps the distance, and the
            # same vertices went up on every frame (~1 ms on the plaza).
            akey = _axes_vertices_key(spacing)
            if getattr(self, "_axes_key", None) != akey:
                axes_coords, self._axes_spans = _axes_vertices(spacing)
                data = axes_coords.tobytes()
                self._axes_vbo.bind()
                self._axes_vbo.allocate(data, len(data))
                self._axes_vbo.release()
                self._axes_key = akey
            self._axes_vao.bind()
            self._gl.glDepthMask(GL_FALSE)
            for name, rgb in (("x", (0.86, 0.22, 0.27)),   # red
                              ("y", (0.16, 0.62, 0.36)),   # green
                              ("z", (0.20, 0.40, 0.78))):  # blue
                start, count = self._axes_spans[name]
                self._set_color(*rgb, 1.0)
                self._gl.glDrawArrays(GL_LINES, start, count)
            self._gl.glDepthMask(GL_TRUE)
            self._axes_vao.release()

        # Guides — dashed, DEPTH-TESTED, so geometry in front hides them
        # (issue #23). They used to be painted in the QPainter overlay,
        # which runs after the render and has no depth at all, so a guide
        # behind a wall still showed through. Same rules as the axes:
        # depth-write off (scaffolding must not cull anything), and none on
        # a plan sheet or a styled composer frame — a printed lámina does
        # not carry the scaffolding, and that is also how it behaved before.
        on_screen = (shown_guides(self.scene)
                     if self.plano_style is None
                     and self.style_override is None else [])
        if on_screen:
            dist = max(float(self.camera.distance), 1e-3)
            eye = self.camera.eye() if self.camera.perspective else None
            # The dashes only change with the camera, the guides or the
            # selection; a hover repaint reuses them and their upload (#816).
            v3 = lambda v: (None if v is None
                            else (v.x(), v.y(), v.z()))  # noqa: E731
            key = (dist, v3(self.camera.target), v3(eye),
                   tuple((id(g), v3(g.point), v3(getattr(g, "direction",
                                                         None)),
                          v3(getattr(g, "origin", None)))
                         for g in on_screen),
                   tuple(g in self.scene.selection
                         for g in on_screen))
            cached = getattr(self, "_guides_cache", None)
            if cached is not None and cached[0] == key:
                g_spans = cached[1]
            else:
                g_coords, g_spans = _guide_vertices(
                    on_screen, dist * 0.03, self.scene.selection,
                    centre=self.camera.target, reach=dist * 15.0,
                    # Parallel: one scale at every depth, nothing to adjust.
                    eye=eye)
                self._guides_cache = (key, g_spans)
                if g_spans:
                    data = g_coords.tobytes()
                    self._guides_vbo.bind()
                    self._guides_vbo.allocate(data, len(data))
                    self._guides_vbo.release()
            if g_spans:
                # A guide LINE runs through any box: the section box cuts
                # it as it cuts the model (the plane leaves guides whole).
                box_cuts = (self.scene.active_section_box() is not None
                            and getattr(self.scene, "show_section_cuts",
                                        True))
                if box_cuts:
                    self._set_section_clip(
                        True, skip=0 if self.scene.active_section() else None)
                self._guides_vao.bind()
                self._gl.glDepthMask(GL_FALSE)
                for start, count, selected in g_spans:
                    if selected:
                        self._set_color(*self._modeling_color("selected"), 1.0)
                    else:
                        self._set_color(*self._modeling_color("guides", (0.27, 0.35, 0.47)), 1.0)
                    self._gl.glDrawArrays(GL_LINES, start, count)
                self._gl.glDepthMask(GL_TRUE)
                self._guides_vao.release()
                if box_cuts:
                    self._set_section_clip(False)

        # The dashed box of the group being edited, depth-tested like the
        # guides (it shares their buffer): the part behind the geometry is
        # hidden instead of showing through it. The dashes live in the
        # shader (u_stipple 4): twelve solid edges at any zoom, not a
        # per-frame tessellation whose count scaled with 1/distance.
        box = (self._edit_group_box_corners()
               if self.plano_style is None and self.style_override is None
               else None)
        if box is not None:
            data = _box_edge_vertices(box).tobytes()
            if data:
                self._guides_cache = None   # the guides' dashes are gone
                self._guides_vbo.bind()
                self._guides_vbo.allocate(data, len(data))
                self._guides_vbo.release()
                self._guides_vao.bind()
                # Dash size in framebuffer pixels for visual parity with
                # the old world-space dashes: their 0.006·distance length
                # spanned 0.003/tan(fov/2) of the viewport height — a
                # screen fraction, independent of zoom (perspective frames
                # the target at 2·distance·tan(fov/2); parallel sizes its
                # height from the same product). w/h are framebuffer
                # pixels, which is what gl_FragCoord measures.
                fov = math.radians(float(self.camera.fov_deg))
                dash = min(20.0, max(3.0, 0.003 * h / math.tan(fov / 2.0)))
                self._program.setUniformValue(self._loc_viewport_px,
                                              QVector2D(float(w), float(h)))
                self._program.setUniformValue1f(self._loc_dash_px, dash)
                self._program.setUniformValue(self._loc_stipple, 4)
                self._gl.glDepthMask(GL_FALSE)
                self._set_color(90 / 255, 110 / 255, 140 / 255, 1.0)
                self._gl.glDrawArrays(GL_LINES, 0, len(data) // 12)
                self._program.setUniformValue(self._loc_stipple, 0)
                self._gl.glDepthMask(GL_TRUE)
                self._guides_vao.release()

    def _draw_previews_after(self, mvp) -> None:
        """The drag's previews over the model's static passes (see
        ``_previews_after``)."""
        self._previews_after = False
        self._set_section_clip(False)
        self._draw_preview_faces()
        self._draw_groups_preview(mvp)
        self._set_section_clip(True)

    def _frame_cache_key(self, mvp, w, h, style, mode):
        """What the model this frame draws depends on, when a pointer move
        may reuse the last frame's (``_frame_cache_restore``) — or None:
        the switch off, an export, or a frame whose passes the cursor's
        cues cannot simply go over (X-ray and back edges draw edges through
        the faces, a section cut its own edges, a tool's preview, the hidden
        ghosts, the base map, terrain and survey layers). The model over
        the plant of #158 took the GPU 40 ms a frame, every pointer move.

        Everything the static passes read is in it: the view, the scene's
        versions (a selection bumps it), every buffer sent to the GPU since
        (``_gpu_epoch``), the style, the open group, the guides, the
        textures loaded, the shadow map."""
        if not _FRAME_CACHE or self._export_size is not None:
            return None
        sc = self.scene
        if (xray_enabled(style) or getattr(style, "back_edges", False)
                or self.plano_style is not None
                or getattr(self, "_clip_vecs", None)
                or getattr(sc, "show_hidden_objects", False)
                or getattr(sc, "show_hidden_geometry", False)
                or self._base_map_showing() or self._terrain_showing()
                or self._photo_showing()):
            return None
        v3 = lambda v: (None if v is None  # noqa: E731
                        else (v.x(), v.y(), v.z()))
        try:
            look = repr(sorted(vars(style).items()))
        except TypeError:
            look = repr(style)
        return (tuple(mvp.data()), w, h, getattr(self, "_msaa", 4), mode,
                look, id(self.style_override), id(sc), sc.version,
                _content_ver(self), _cache_ver(self),
                getattr(self, "_gpu_epoch", 0),
                id(sc.edit_group), self._edit_rest_mode,
                self.edit_rest_fade,
                getattr(sc, "show_axes", True),
                tuple((id(g), v3(g.point), v3(getattr(g, "direction", None)),
                       v3(getattr(g, "origin", None)), g in sc.selection)
                      for g in (getattr(sc, "guides", None) or ())),
                len(getattr(self, "_tex_cache", None) or ()),
                id(getattr(self, "_frame_shadow", None)),
                getattr(self, "_shadow_key", None),
                # Soft shadows (#1281): set from Preferences, a still view
                # kept the old level until the camera moved (Windows round
                # 0.6.2).
                getattr(self, "_soft_shadows", 0),
                self._faces_count, self._edges_count, self._sel_faces_count,
                self._selected_count, self.camera.fov_deg,
                self.camera.perspective)

    def _frame_cache_track(self, mvp_key) -> bool:
        """Note this frame's view (``mvp_key``: the frame cache key's MVP
        element, or the MVP itself when there is no key) and answer
        whether it is the same as the last frame's — the view has
        settled, so a picture kept now can be restored by the frames
        after it. While the camera moves every frame's differs."""
        prev = getattr(self, "_frame_cache_prev_mvp", None)
        self._frame_cache_prev_mvp = mvp_key
        return prev == mvp_key

    def _frame_cache_store(self, key, w, h) -> None:
        """Keep the scene FBO's colour and depth as the static passes left
        them, for the pointer moves after (``_frame_cache_restore``)."""
        fbo = getattr(self, "_frame_cache_fbo", None)
        if fbo is None or not fbo.isValid() \
                or (fbo.width(), fbo.height()) != (w, h) \
                or fbo.format().samples() != self._scene_fbo.format().samples():
            fbo = self._frame_cache_fbo = QOpenGLFramebufferObject(
                w, h, self._scene_fbo.format())
        self._frame_cache_copy(self._scene_fbo, fbo, w, h)
        self._frame_cache = key

    def _frame_cache_restore(self, key, w, h) -> bool:
        """The kept model back into the scene FBO when ``key`` is still
        what this frame would draw; then only the cursor's cues are drawn
        (``_paint_hover``)."""
        fbo = getattr(self, "_frame_cache_fbo", None)
        # A context made again (the widget moved to another window) takes
        # its FBOs with it; read from one, the blit took the window's own.
        if (fbo is None or getattr(self, "_frame_cache", None) != key
                or not fbo.isValid() or (fbo.width(), fbo.height()) != (w, h)):
            return False
        self._frame_cache_copy(fbo, self._scene_fbo, w, h)
        return True

    def _frame_cache_copy(self, src, dst, w, h) -> None:
        extra = self.context().extraFunctions()
        self._gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, src.handle())
        self._gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst.handle())
        extra.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h,
                                GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT,
                                GL_NEAREST)
        self._scene_fbo.bind()
        self._gl.glViewport(0, 0, w, h)

    def _paint_hover(self, mvp, w, h) -> None:
        """The cursor's cues over the kept model: the dots of the face under
        it, then — on those dots only — the axes, guides and group box the
        full frame draws after them, so they read as before; the edge
        under it on top. Where an edge lies at the same depth as an axis
        the edge keeps it (``GL_LESS``), as when it was drawn later."""
        hovered = self._hover_entity
        if isinstance(hovered, Face) and hovered not in self.scene.selection:
            hover_count = self._upload_hover_face(hovered,
                                                  self._hover_placement)
            if hover_count > 0:
                self._set_section_clip(True)
                self._gl.glClearStencil(0)
                self._gl.glClear(GL_STENCIL_BUFFER_BIT)
                self._gl.glEnable(GL_STENCIL_TEST)
                self._gl.glStencilMask(0xFF)
                self._gl.glStencilFunc(GL_ALWAYS, 1, 0xFF)
                self._gl.glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE)
                self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
                self._gl.glPolygonOffset(1.0, 1.0)
                self._gl.glDepthMask(GL_FALSE)
                front, back = self._selection_dot_colors(hovered)
                self._set_color(*front, 1.0)
                self._program.setUniformValue(
                    self._loc_back_color, QVector4D(*back, 1.0))
                self._program.setUniformValue(self._loc_stipple, 3)
                self._hover_faces_vao.bind()
                self._gl.glDrawArrays(GL_TRIANGLES, 0, hover_count)
                self._hover_faces_vao.release()
                self._program.setUniformValue(self._loc_stipple, 0)
                self._gl.glDepthMask(GL_TRUE)
                self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
                self._set_section_clip(False)
                self._gl.glStencilFunc(GL_EQUAL, 1, 0xFF)
                self._gl.glStencilMask(0x00)
                self._gl.glDepthFunc(GL_LESS)
                self._draw_scaffold(mvp, w, h)
                self._program.setUniformValue(self._loc_mvp, mvp)
                self._gl.glDepthFunc(GL_LEQUAL)
                self._gl.glStencilMask(0xFF)
                self._gl.glDisable(GL_STENCIL_TEST)
        if isinstance(hovered, Edge):
            self._set_section_clip(True)
            hover_count = self._upload_hover_edge(hovered)
            self._set_color(0.30, 0.55, 0.95, 1.0)
            self._hover_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, hover_count)
            self._hover_edges_vao.release()
            self._set_section_clip(False)

    def _set_cutout(self, on) -> None:
        """The foliage cutout switch of the face shader, and with it the
        stencil mark the ambient occlusion skips (#954): the frame arms the
        stencil (test always passing, ``AO_FOLIAGE_BIT`` writable) and only
        the value a fragment leaves changes here."""
        self._program.setUniformValue(self._loc_hard_cutout, 1 if on else 0)
        self._gl.glStencilFunc(GL_ALWAYS, AO_FOLIAGE_BIT if on else 0, 0xFF)

    def _apply_ambient_occlusion(self, w, h, mode, style=None) -> None:
        """The ambient occlusion pass (#954, the style's switch)
        over the faces the scene FBO holds. Wireframe and X-ray have no
        opaque faces to darken."""
        # The foliage marking ends with the opaque faces, AO or not.
        self._gl.glDisable(GL_STENCIL_TEST)
        self._gl.glStencilMask(0xFF)
        from views import ambient_occlusion as _ao
        settings = _ao.settings_for(style)
        if settings is None or mode in ("wireframe", "xray") or xray_enabled(style):
            return
        if getattr(self, "_ao", None) is None:
            self._ao = _ao.AmbientOcclusion(self, SHADER_DIR)
        if not self._ao.apply(self._gl, self.context().extraFunctions(),
                              self._scene_fbo, w, h,
                              self.camera.projection_matrix(), settings):
            if self._ao.broken and not getattr(self, "_ao_warned", False):
                self._ao_warned = True
                print(f"[ambient occlusion] off: {self._ao.broken}")
        self._program.bind()

    def _apply_fog_uniforms(self, style) -> None:
        """Arm distance fog for subsequent world-space draws in this frame."""
        if not bool(getattr(style, "fog_enabled", False)):
            self._program.setUniformValue(self._loc_fog_enable, 0)
            return

        start, end = fog_depth_range(
            getattr(style, "fog_distance", 10.0),
            getattr(style, "fog_thickness", 10.0))
        color = effective_fog_color(style)

        self._program.setUniformValue(self._loc_fog_eye, self.camera.eye())
        self._program.setUniformValue(self._loc_fog_forward,
                                      self.camera.forward())
        self._program.setUniformValue(self._loc_fog_color,
                                      QVector3D(*color))
        self._program.setUniformValue1f(self._loc_fog_start, float(start))
        self._program.setUniformValue1f(self._loc_fog_end, float(end))
        self._program.setUniformValue(self._loc_fog_enable, 1)

    #: Default back-face colour, the classic blue-grey: a visible back face
    #: means "you are looking at the inside" (or at a genuinely inverted
    #: face) — honest feedback the winding-proof shading used to hide. The
    #: active style's Back color overrides it (core/style.py).
    BACK_FACE_COLOR = DEFAULT_BACK_COLOR

    def _set_color(self, r: float, g: float, b: float, a: float) -> None:
        self._program.setUniformValue(self._loc_color, QVector4D(r, g, b, a))
        # Keep the back colour in sync by default so lines and highlights
        # (where gl_FrontFacing is meaningless) render one colour; the face
        # passes override it just before their draws.
        self._program.setUniformValue(self._loc_back_color,
                                      QVector4D(r, g, b, a))

    def _modeling_color(self, key, default=None) -> tuple:
        from core.modeling_style import modeling_color
        style = getattr(self, "_frame_style", None) or self.scene.display_style
        return modeling_color(style, key, default)

    def _draw_locked_selection(self) -> None:
        parts = []
        for group in self.scene.selection:
            if (isinstance(group, Group) and getattr(group, "locked", False)
                    and self.scene.entity_visible(group)):
                if getattr(group, "billboard", False):
                    quad = self._billboard_quad(group)
                    if quad is not None:
                        corners = quad[0]
                        data = array("f")
                        for i in range(4):
                            for point in (corners[i], corners[(i + 1) % 4]):
                                data.extend(point.toTuple())
                        parts.append(data.tobytes())
                else:
                    parts.append(_box_edges(*self._group_obb(group)))
        if not parts:
            return
        raw = b"".join(parts)
        self._bb_sel_vbo.bind()
        self._bb_sel_vbo.allocate(raw, len(raw))
        self._bb_sel_vbo.release()
        self._set_color(*self._modeling_color("locked"), 1.0)
        self._bb_sel_vao.bind()
        self._gl.glDrawArrays(GL_LINES, 0, len(raw) // 12)
        self._bb_sel_vao.release()

    def _selection_dot_colors(self, face, paint=_NO_PAINT,
                              back_default=None, dots=None) -> tuple:
        """``(front_dot, back_dot)``: the selection dot colour for each side
        of ``face``, each picked against the paint that side shows — its
        material colour (or the open group's paint), the two-sided back
        paint, or the style's back-face tint.

        ``paint`` (the open group's), ``back_default`` (the style's back
        tint) and ``dots`` (a dict remembering each colour's dot) let a
        caller asking for thousands of faces find those once."""
        from core.materials import effective_attrs
        style = self._view_style()
        if "selected" in getattr(style, "modeling_colors", {}):
            color = self._modeling_color("selected")
            return color, color
        if paint is _NO_PAINT:
            paint = _paint_of(self, self.scene.edit_group)
        attrs = effective_attrs(face.attrs, paint)
        tex = attrs.get("texture")
        if tex is not None and tex.get("path"):
            front = None                      # a texture: colour unknown
        else:
            front = tuple(attrs.get("color") or self.DEFAULT_FACE_COLOR)
        back_attr = attrs.get("back")
        if back_attr is True:
            back = front                      # both sides wear the front
        elif isinstance(back_attr, dict):
            col = back_attr.get("color")
            back = tuple(col) if col is not None else None
        else:
            back = (back_default if back_default is not None
                    else effective_back_color(self._view_style(), self.scene))
        if dots is None:
            return selection_dot_color(front), selection_dot_color(back)
        out = dots.get((front, back))
        if out is None:
            out = dots[(front, back)] = (selection_dot_color(front),
                                         selection_dot_color(back))
        return out

    def _set_back_face_color(self) -> None:
        # The style's Back color wins; else the scene's adopted tint (from
        # an imported .skp's style, so unpainted faces read like they did
        # for the author); else the default blue-grey.
        r, g, b = effective_back_color(
            self._view_style(), self.scene)
        self._program.setUniformValue(self._loc_back_color,
                                      QVector4D(r, g, b, 1.0))

    def _shade_factor(self, normal) -> float:
        """Diffuse factor (0.62..1.0) of a face normal against the fixed
        world light — quantised to 1/32 so it can key texture draw runs
        without exploding the run count on curved surfaces."""
        if normal.length() < 1e-9:
            return 0.84375
        # abs(): shading depends on the face's plane, not its winding — a
        # flat plan whose faces happen to wind downward still reads bright,
        # while a solid keeps its top-bright / sides-toned maquette look.
        # The 0.62..1.0 range matches the classic default-style contrast
        # (measured on user models: its shaded walls sit near 0.65 of the
        # lit tone) — the previous 0.80..1.0 read as "unshaded"/wrong
        # colour next to a reference render of the same building.
        d = abs(QVector3D.dotProduct(normal.normalized(), self._LIGHT))
        return round((0.62 + 0.38 * d) * 32.0) / 32.0

    def _shaded_color(self, base, normal):
        """Multiply ``base`` RGB by a subtle diffuse term from the face normal vs
        the fixed world light — the matte-model shading. Returns a clamped RGB
        tuple used as the render key (identical normals/colours group together)."""
        # Through the class: test stand-ins borrow _shaded_color alone.
        return Viewport._shade_rgb(base, self._shade_factor(normal))

    @staticmethod
    def _shade_rgb(base, shade):
        """:meth:`_shaded_color` for a known ``shade`` factor."""
        # Quantise to 1/64 steps: the tuple is the DRAW-RUN key, and a model
        # with thousands of distinct normals (imported trees, curved detail)
        # otherwise explodes into one draw call per unique shade — 63k draw
        # calls per frame on a real 100k-face project. 1/64 banding is
        # invisible; the run count collapses to a few hundred.
        return (round(min(1.0, base[0] * shade) * 64.0) / 64.0,
                round(min(1.0, base[1] * shade) * 64.0) / 64.0,
                round(min(1.0, base[2] * shade) * 64.0) / 64.0)

    # ---- Line weight for exports --------------------------------------------
    def _line_jitter(self, px: int, w: int, h: int) -> list:
        """NDC offsets that thicken a 1-px GL line to about ``px`` pixels by
        redrawing it shifted — a disc of sub-pixel samples (2 px = the four
        half-pixel corners, 3 px = a cross, …). Only export renders ask for
        more than one; on screen the list is the single origin."""
        if px <= 1 or self._export_size is None:
            return [(0.0, 0.0)]
        px = min(int(px), 8)
        r = (px - 1) / 2.0
        offs = [-r + i for i in range(px)]
        return [(dx * 2.0 / max(w, 1), dy * 2.0 / max(h, 1))
                for dx in offs for dy in offs
                if dx * dx + dy * dy <= r * r + 0.51]

    def _draw_style_watermarks(self, style, layer, width, height) -> None:
        if (not style.watermarks_visible or not any(
                mark.visible and mark.opacity > 0 and mark.layer == layer
                for mark in style.watermarks)):
            return
        from views.watermarks import paint_watermarks
        from PySide6.QtGui import QTransform
        marks = tuple(mark for mark in style.watermarks if mark.layer == layer)
        key = (marks, width, height, tuple(style.background[:3]))
        cached = self._watermark_textures.get(layer)
        if cached is None or cached[0] != key:
            image = QImage(width, height, QImage.Format_RGBA8888)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            try:
                paint_watermarks(painter, style, QSize(width, height), layer)
            finally:
                painter.end()
            if cached is not None:
                cached[1].destroy()
            texture = QOpenGLTexture(image.transformed(QTransform.fromScale(1, -1)))
            texture.setMinificationFilter(QOpenGLTexture.Linear)
            texture.setMagnificationFilter(QOpenGLTexture.Linear)
            self._watermark_textures[layer] = (key, texture)
        else:
            texture = cached[1]
        self._program.bind()
        quad = array("f", [-1, -1, 0, 0, 0, 1, -1, 0, 1, 0, 1, 1, 0, 1, 1,
                           -1, -1, 0, 0, 0, 1, 1, 0, 1, 1, -1, 1, 0, 0, 1])
        self._watermark_vbo.bind()
        self._watermark_vbo.allocate(quad.tobytes(), len(quad) * 4)
        self._watermark_vbo.release()
        self._program.setUniformValue(self._loc_mvp, QMatrix4x4())
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._program.setUniformValue(self._loc_use_tex, 1)
        self._program.setUniformValue1f(self._loc_shade, 1.0)
        self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._program.setUniformValue1f(self._loc_xray_opacity, 1.0)
        self._program.setUniformValue(self._program.uniformLocation("u_screen_image"), 1)
        self._set_color(1.0, 1.0, 1.0, 1.0)
        self._gl.glDisable(GL_DEPTH_TEST)
        self._gl.glDisable(GL_CULL_FACE)
        self._gl.glEnable(GL_BLEND)
        self._gl.glDepthMask(GL_FALSE)
        self._gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                                     1, GL_ONE_MINUS_SRC_ALPHA)
        texture.bind(0)
        self._watermark_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
        self._watermark_vao.release()
        texture.release(0)
        self._program.setUniformValue(self._program.uniformLocation("u_screen_image"), 0)
        self._program.setUniformValue(self._loc_use_tex, 0)
        self._program.setUniformValue(self._loc_mvp,
                                      self.camera.projection_matrix() * self.camera.view_matrix())
        self._gl.glDepthMask(GL_TRUE)
        self._gl.glEnable(GL_DEPTH_TEST)
        _scene_blend(self._gl)

    def _draw_style_ground(self, mvp, style) -> None:
        """Composite the optional Z=0 plane over geometry below ground.

        This display surface never enters the model or snapping. Drawing after
        geometry with depth writes off permits transparent ground, while model
        surfaces above it retain their own colors and depth.
        """
        if not self._style_ground_visible(style):
            return
        inverse, valid = mvp.inverted()
        if not valid:
            return
        program = self._style_ground_program
        if program is None:
            program = QOpenGLShaderProgram(self)
            vertex = program.addShaderFromSourceFile(
                QOpenGLShader.Vertex, str(SHADER_DIR / "style_ground.vert"))
            fragment = program.addShaderFromSourceFile(
                QOpenGLShader.Fragment, str(SHADER_DIR / "style_ground.frag"))
            if not (vertex and fragment and program.link()):
                raise RuntimeError("ground shader compile/link failed:\n" + program.log())
            self._style_ground_program = program
        program.bind()
        program.setUniformValue("u_mvp", mvp)
        program.setUniformValue("u_inverse_mvp", inverse)
        program.setUniformValue("u_color", QVector4D(
            *style.ground_color[:3], 1.0 - style.ground_transparency / 100.0))
        quad = array("f", [-1, -1, 0, 1, -1, 0, 1, 1, 0,
                           -1, -1, 0, 1, 1, 0, -1, 1, 0])
        self._ground_vbo.bind()
        self._ground_vbo.allocate(quad.tobytes(), len(quad) * 4)
        self._ground_vbo.release()
        self._ground_vao.bind()
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthMask(GL_FALSE)
        # Preserve destination alpha, including exported QImage conversion.
        self._gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                                     1, GL_ONE_MINUS_SRC_ALPHA)
        self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
        _scene_blend(self._gl)
        self._gl.glDepthMask(GL_TRUE)
        self._ground_vao.release()
        program.release()
        self._program.bind()

    def begin_groups_preview(self, groups=(), external: bool = False) -> None:
        """Enter a groups-only transform preview: the per-version caches
        freeze, the moving groups leave the consolidated VBOs (one resync)
        and their chunk arrays upload ONCE to scratch VBOs that paintGL
        draws with a translated MVP — a drag frame touches no arrays at
        all. Smooth group dragging on a 230k-face group.

        ``external=True`` previews OFF-scene template groups (Paste's
        clipboard): same scratch upload, but nothing leaves the consolidated
        VBOs and the caches stay live — no freeze, no resyncs."""
        # A component keeps placements inside itself, and THOSE hold the
        # geometry: previewing only the top-level group uploaded an empty
        # scratch copy while the children kept drawing, frozen, at the old
        # spot — the hedge stood still through the whole drag and teleported
        # on release (Marco: "cuando roto o muevo tiene laj bastante").
        movers: list = []
        # Inside an open group the movers sit in its paint: without it a
        # plain piece turned unpainted for the drag and came back on release
        # (#1101).
        open_paint = self.scene.open_group_paint()
        self._placements()                     # the proxies _preview_chunk bakes
        for g in groups:
            self._expand_placements(g, movers, above=open_paint)
        groups = movers
        self._preview_external = external
        if not external:
            self._frozen_cache_version = self.scene.version
            self._edges_version = -1      # one resync WITHOUT the movers
        self._preview_groups = set(map(id, groups))
        self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        if not self._preview_groups or self._program is None:
            return
        self.makeCurrent()
        try:
            if getattr(self, "_pv_edges_vao", None) is None:
                self._pv_edges_vao, self._pv_edges_vbo = self._create_dynamic()
                self._pv_vcol_vao, self._pv_vcol_vbo = \
                    self._create_dynamic_vcol()
                self._pv_tex_vao, self._pv_tex_vbo = self._create_dynamic_uv()
            chunks = []
            for g in groups:
                if getattr(g, "billboard", False):
                    # Face-me figures preview through their OWN pass (the
                    # anchor rides the preview transform): their raw mesh
                    # quad in the scratch VBOs showed a swimming texture.
                    continue
                chunks.append(self._preview_chunk(g))
            self._upload_preview_chunks(chunks)
        finally:
            self.doneCurrent()

    def _upload_preview_chunks(self, chunks) -> None:
        """Upload the arrays of ``chunks`` to the scratch VBOs the groups
        preview draws at its offset (GL context current)."""
        edge_parts: list = []
        vcol_parts: list = []
        tex_parts: dict = {}
        for ch in chunks:
            if ch["edges"]:
                edge_parts.append(ch["edges"])
            if ch["vcol"]:
                vcol_parts.append(ch["vcol"])
            for path, raw in ch["by_texture"].items():
                tex_parts.setdefault(path, []).append(raw)
        raw = b"".join(edge_parts)
        self._pv_edges_vbo.bind()
        self._pv_edges_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
        self._pv_edges_vbo.release()
        self._pv_edges_count = len(raw) // 12
        raw = b"".join(vcol_parts)
        self._pv_vcol_vbo.bind()
        self._pv_vcol_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
        self._pv_vcol_vbo.release()
        self._pv_vcol_count = len(raw) // 24
        runs: list = []
        blobs: list = []
        off = 0
        for path, parts in tex_parts.items():
            blob = b"".join(parts)
            runs.append((path, off // 20, len(blob) // 20))
            blobs.append(blob)
            off += len(blob)
        raw = b"".join(blobs)
        self._pv_tex_vbo.bind()
        self._pv_tex_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
        self._pv_tex_vbo.release()
        self._pv_tex_runs = runs

    def _preview_chunk(self, g):
        """The arrays of a mover's scratch copy. A nested piece handed in as
        itself bakes through its placement proxy, which knows the paint above
        it; the piece alone only knows its own (#1101)."""
        proxies = getattr(self, "_placement_proxies", None) or {}
        return self._group_chunk(proxies.get(id(g), g))

    def end_groups_preview(self) -> None:
        if getattr(self, "_verts_preview", None) is not None:
            self.end_verts_preview()
            return
        if not getattr(self, "_preview_external", False):
            self._frozen_cache_version = None
            self._edges_version = -1      # resync with the movers back in
        else:
            # Off-scene templates never left the consolidated VBOs (nothing
            # to resync) and their scratch chunks are one-shot — drop them
            # so a big clipboard doesn't pin megabytes of arrays.
            scene_ids = {id(g) for g in self._placements()}
            for cache_name in ("_group_chunks", "_inst_chunks"):
                cache = getattr(self, cache_name, None)
                if cache:
                    for gid in self._preview_groups - scene_ids:
                        cache.pop(gid, None)
        self._preview_external = False
        self._preview_groups = set()
        self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_matrix = None
        self._pv_edges_count = 0
        self._pv_vcol_count = 0
        self._pv_tex_runs = []

    #: Most faces a vertex drag may bend (a corner moving, another not)
    #: for the drag to preview from frozen arrays; past it the old live
    #: rebuild stays — the bent faces are drawn again on every frame.
    VERTS_PREVIEW_BENT_MAX = 1500

    def begin_verts_preview(self, verts, groups=()):
        """Preview a drag of ``verts`` (the open mesh's own vertices) the
        way a group drag is previewed: nothing is mutated until the
        commit. The open mesh is baked ONCE in two parts — what stays,
        drawn in place of the open group's chunk, and the faces and
        edges every corner of which rides the drag, uploaded to the
        scratch VBOs and drawn at the preview offset. Each frame of a
        Move of the 15 799-face flag re-baked the whole open group,
        ~0.4 s (night of 18-11).

        Returns ``(bent faces, bent edges, the open group's paint)`` — the
        ones with corners on both sides: the tool draws the faces itself,
        moved, each frame, the viewport the edges — or
        None when the preview does not apply (a small mesh, copies
        sharing it, too many bent faces; for the loose model with no group
        open, a soft edge riding or bending, or hidden geometry shown), and
        the tool keeps the live rebuild.

        ``groups``: a MIXED drag — objects grabbed with the vertices. They
        ride the same transform, so they join the groups preview's state
        (left out of the consolidated buffers, their arrays uploaded with
        what rides to the same scratch VBOs) and nothing at all is mutated
        until the commit. Each frame of a mixed Move re-walked the whole
        loose model and re-placed the objects before (21-11). None when
        either part does not apply: the tool then keeps the live drag for
        the whole selection, never half of it."""
        sc = self.scene
        E = sc.edit_group
        mesh = sc.mesh
        if (not verts or self._program is None
                or getattr(self, "_verts_preview", None) is not None
                or getattr(self, "_preview_groups", None)):
            return None
        # No group open: the model's own loose geometry. It is not a
        # chunk — _sync_edges walks it face by face on every sync — so
        # nothing stands in for it: the sync that starts the drag leaves
        # out what rides and what bends (``hide``), and no frame after it
        # syncs again. Each frame of a Move of a block of a 6 400-face
        # loose floor re-walked the whole floor, ~0.33 s (21-11).
        loose = E is None
        if loose and (mesh is not sc.loose_mesh
                      or getattr(sc, "show_hidden_geometry", False)):
            return None
        array_bake = _array_bake()
        if not array_bake.can_bake_built(mesh):
            return None
        if not loose:
            # A mesh drawn twice (a component's copies, an instance) would
            # show the hole the static part leaves.
            holders = [g for g in self._placements()
                       if getattr(g, "mesh", None) is mesh]
            if (len(holders) != 1
                    or getattr(holders[0], "xform", None) is not None):
                return None
            if sc.loose_mesh is mesh:
                return None
        moving = {id(v) for v in verts}
        touched: dict = {}
        for v in verts:
            for e in getattr(v, "edges", ()):
                for f in e.faces:
                    touched[id(f)] = f
        ride, bent = set(), []
        for f in touched.values():
            corners = [v for loop in (f.loop, *f.hole_loops) for v in loop]
            if all(id(v) in moving for v in corners):
                ride.add(id(f))
            else:
                bent.append(f)
        if len(bent) > self.VERTS_PREVIEW_BENT_MAX:
            return None
        bent_ids = {id(f) for f in bent}
        stay_f, ride_f = [], []
        for f in mesh.faces:
            if id(f) in ride:
                ride_f.append(f)
            elif id(f) not in bent_ids:
                stay_f.append(f)
        stay_e, ride_e, bent_e = [], [], []
        for e in mesh.edges:
            a, b = id(e.v0) in moving, id(e.v1) in moving
            if a and b:
                ride_e.append(e)
            elif a or b:
                bent_e.append(e)
            else:
                stay_e.append(e)
        if loose and any(getattr(e, "soft", False)
                         for e in (*ride_e, *bent_e)):
            # The loose soft edges and the smooth shading around them are
            # kept per content version (frozen here): the curve would stay
            # behind where it was. The live drag stays.
            return None
        paint = _paint_of(self, None if loose else holders[0])
        msig = _material_sig(paint)
        stay = (None if loose else
                array_bake.bake_built(self, mesh, paint, msig, None,
                                      stay_f, stay_e))
        rider = array_bake.bake_built(self, mesh, paint, msig, None,
                                      ride_f, ride_e)
        if (stay is None and not loose) or rider is None:
            return None
        movers: list = []
        if groups:
            # The objects of a mixed drag, as begin_groups_preview takes
            # them: a component's placements inside it, in the open
            # group's paint (#1101).
            open_paint = sc.open_group_paint()
            self._placements()             # the proxies _preview_chunk bakes
            for g in groups:
                self._expand_placements(g, movers, above=open_paint)
            if not movers:
                return None
            self._preview_external = False
            self._preview_groups = set(map(id, movers))
            self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        # The pick index answers for the drag from the frozen version:
        # made now, from the whole open group's chunk — made later, the
        # chunk would be the static part, and the walk is ~1 s. (Made
        # once the movers are known, as a groups preview makes its own.)
        try:
            self._pick_index()
        except Exception:  # noqa: BLE001 — a pick index made later is slower, not wrong
            pass
        if stay is not None:
            stay["vkey"] = (sc.version, id(mesh))
            stay["uid"] = next(_chunk_uid)
            stay["mesh"] = mesh
        hide = ride | bent_ids
        hide_e = {id(e) for e in ride_e} | {id(e) for e in bent_e}
        import numpy as np
        if bent_e:
            ends = np.array([(p.x(), p.y(), p.z()) for e in bent_e
                             for p in (e.v0.position, e.v1.position)],
                            dtype=np.float32)
            rides = np.array([id(v) in moving for e in bent_e
                              for v in (e.v0, e.v1)], dtype=np.float32)
            drawn = np.array([not getattr(e, "soft", False)
                              and not getattr(e, "hidden", False)
                              and sc.entity_visible(e)
                              for e in bent_e for _ in (0, 1)], dtype=bool)
            ends, rides = ends[drawn], rides[drawn]
        else:
            ends = rides = None
        # What rides keeps the look the live drag gives it: the selected
        # faces their dots, the selected edges the selection colour, the
        # others the edge colour. The scratch copy drew every riding edge
        # orange and no dot at all. Made once, here, while nothing moved.
        sel = sc.selection
        sel_ids = {id(x) for x in sel}
        dot_faces = [f for f in sel if isinstance(f, Face) and id(f) in ride]
        dots = self._selected_face_runs(dot_faces) if dot_faces else {}
        dot_spans, dot_parts, at = [], [], 0
        for (front, back), buf in dots.items():
            n = len(buf) // 3
            dot_spans.append((front, back, at, n))
            dot_parts.append(buf.tobytes())
            at += n

        def points(edges):
            return array("f", (c for e in edges
                               for p in (e.v0.position, e.v1.position)
                               for c in (p.x(), p.y(), p.z()))).tobytes()

        # The selection buffer draws every selected edge; the edge pass
        # only the hard, visible ones.
        sel_e = [e for e in ride_e if id(e) in sel_ids]
        plain_e = [e for e in ride_e if id(e) not in sel_ids
                   and not getattr(e, "soft", False)
                   and not getattr(e, "hidden", False)
                   and sc.entity_visible(e)]
        self._verts_preview = {"mesh": mesh, "stay": stay, "hide": hide,
                               "hide_e": hide_e, "bent_ends": ends,
                               "bent_rides": rides, "loose": loose,
                               "dot_spans": dot_spans,
                               "dots": b"".join(dot_parts),
                               "sel_edges": points(sel_e),
                               "plain_edges": points(plain_e),
                               "token": object()}
        self._frozen_cache_version = sc.version
        self._edges_version = -1          # one resync with the static part
        # The index made above answers under the frozen version too: the
        # geometry it holds is the geometry the drag starts from.
        pc = getattr(self, "_pick_index_cache", None)
        if pc is not None:
            self._pick_index_cache = (
                (_content_ver(self),) + tuple(pc[0][1:]),) + tuple(pc[1:])
        # The scratch copy draws through the groups preview's pass. No
        # placement changes: the pick index keeps what it has.
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_matrix = None
        self.makeCurrent()
        try:
            if getattr(self, "_pv_edges_vao", None) is None:
                self._pv_edges_vao, self._pv_edges_vbo = self._create_dynamic()
                self._pv_vcol_vao, self._pv_vcol_vbo = \
                    self._create_dynamic_vcol()
                self._pv_tex_vao, self._pv_tex_vbo = self._create_dynamic_uv()
            # Face-me figures preview through their own pass (see
            # begin_groups_preview).
            self._upload_preview_chunks(
                [dict(rider, edges=b"")]
                + [self._preview_chunk(g) for g in movers
                   if not getattr(g, "billboard", False)])
            self._upload_rider_looks(self._verts_preview)
            if getattr(self, "_pv_bent_vao", None) is None:
                # Made here, not in paintGL: making a buffer releases the
                # shader program, and the rest of that first drag frame
                # drew nothing — the stretched edges among it.
                self._pv_bent_vao, self._pv_bent_vbo = self._create_dynamic()
        finally:
            self.doneCurrent()
        self.update()
        return bent, bent_e, paint

    def _upload_rider_looks(self, vpv) -> None:
        """Upload the riding part's selection dots and its two kinds of
        edges (``begin_verts_preview``) to their scratch VBOs (GL context
        current)."""
        for name, key in (("_pv_dots", "dots"), ("_pv_sel_e", "sel_edges"),
                          ("_pv_plain_e", "plain_edges")):
            raw = vpv[key]
            if not raw:
                continue
            if getattr(self, name + "_vao", None) is None:
                vao, vbo = self._create_dynamic()
                setattr(self, name + "_vao", vao)
                setattr(self, name + "_vbo", vbo)
            vbo = getattr(self, name + "_vbo")
            vbo.bind()
            vbo.allocate(raw, len(raw))
            vbo.release()

    def _draw_rider_looks(self, vpv) -> None:
        """The riding part's dots and edges, through the transform the
        scratch copy is drawn with (the MVP set by the caller), as the
        static passes draw them at rest. (A context made again mid-drag
        dropped their buffers: then they are not drawn.)"""
        dots_vao = getattr(self, "_pv_dots_vao", None)
        plain_vao = getattr(self, "_pv_plain_e_vao", None)
        sel_vao = getattr(self, "_pv_sel_e_vao", None)
        if self._export_size is None and vpv["dots"] and dots_vao:
            # As the face highlights pass: at the depth of the faces under
            # them (the scratch copy draws its faces with no offset, the
            # static passes offset both), no depth written, the dot
            # pattern.
            self._gl.glDepthMask(GL_FALSE)
            self._program.setUniformValue(self._loc_stipple, 3)
            dots_vao.bind()
            for front, back, start, count in vpv["dot_spans"]:
                self._set_color(*front, 1.0)
                self._program.setUniformValue(
                    self._loc_back_color, QVector4D(*back, 1.0))
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
            dots_vao.release()
            self._program.setUniformValue(self._loc_stipple, 0)
            self._gl.glDepthMask(GL_TRUE)
            self._set_back_face_color()
        if vpv["plain_edges"] and plain_vao:
            ec = self._effective_style().edge_color
            self._set_color(ec[0], ec[1], ec[2], 1.0)
            plain_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, len(vpv["plain_edges"]) // 12)
            plain_vao.release()
        if self._export_size is None and vpv["sel_edges"] and sel_vao:
            self._set_color(*self._modeling_color("selected"), 1.0)
            sel_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, len(vpv["sel_edges"]) // 12)
            sel_vao.release()

    def _chunk_without(self, group, hidden):
        """The open group's chunk without the faces in ``hidden`` (a
        push/pull preview hides the face being pushed), baked from arrays —
        or ``None``, and the faces are bucketed one by one as before.

        Only for the open mesh drawn in place, and not beside a soft edge;
        the part keeps every edge, each listing the faces drawn (as the
        mesh with ``hidden`` deleted would:
        tests/test_push_preview_chunk_without.py). Kept until the model or
        the hidden set changes."""
        mesh = getattr(group, "mesh", None)
        if (mesh is None or mesh is not self.scene.mesh
                or getattr(group, "xform", None) is not None):
            return None
        array_bake = _array_bake()
        if not array_bake.can_bake_built(mesh):
            return None
        # Beside a curved surface the walk shades the faces around the
        # hidden one as it always has; the part would round them as if the
        # hidden face were gone.
        if any(getattr(e, "soft", False)
               for f in hidden for lp in (f.loop, *f.hole_loops)
               for v in lp for e in v.edges):
            return None
        paint = _paint_of(self, group)
        msig = _material_sig(paint)
        key = (_cache_ver(self), id(mesh), getattr(mesh, "_mut_serial", None),
               msig, frozenset(id(f) for f in hidden))
        memo = getattr(self, "_chunk_without_memo", None)
        if memo is not None and memo[0] == key and memo[1]["mesh"] is mesh:
            return memo[1]
        faces = [f for f in mesh.faces if f not in hidden]
        try:
            entry = array_bake.bake_built(self, mesh, paint, msig, None,
                                          faces, list(mesh.edges))
        except Exception:  # noqa: BLE001 — the face-by-face path still draws it
            entry = None
        if entry is None:
            return None
        entry["uid"] = next(_chunk_uid)
        entry["mesh"] = mesh
        self._chunk_without_memo = (key, entry)
        return entry

    def end_verts_preview(self) -> None:
        if getattr(self, "_verts_preview", None) is None:
            return
        self._verts_preview = None
        if getattr(self, "_preview_groups", None):
            # A mixed drag's objects come back into the buffers too.
            self._preview_groups = set()
            self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        self._frozen_cache_version = None
        self._edges_version = -1
        self._sel_runs_memo = None
        self._moved_pack_memo = None      # the drag's faces, let go
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_matrix = None
        self._pv_edges_count = 0
        self._pv_vcol_count = 0
        self._pv_tex_runs = []
        self.update()

    def set_groups_preview_offset(self, delta: QVector3D) -> None:
        self._preview_offset = QVector3D(delta)
        self._preview_matrix = None
        self.update()

    def set_groups_preview_matrix(self, m) -> None:
        """Full-matrix variant (Rotate/Scale previews): the scratch copies
        draw through ``m`` — same zero-churn frame as the translation."""
        self._preview_matrix = QMatrix4x4(m)
        self.update()

    def _groups_preview_transform(self) -> QMatrix4x4:
        """The world transform the groups preview draws its movers through:
        the full matrix (Rotate/Scale) or the translation (Move)."""
        m = getattr(self, "_preview_matrix", None)
        if m is not None:
            return QMatrix4x4(m)
        m = QMatrix4x4()
        off = getattr(self, "_preview_offset", None)
        if off is not None:
            m.translate(off)
        return m

    def _draw_groups_preview(self, mvp) -> None:
        """Draw the frozen scratch copies of the moving groups at the
        current preview offset: one translated MVP, zero array churn."""
        if (not getattr(self, "_preview_groups", None)
                and getattr(self, "_verts_preview", None) is None):
            return
        m = self._groups_preview_transform()
        self._program.setUniformValue(self._loc_mvp, mvp * m)
        n = getattr(self, "_pv_vcol_count", 0)
        if n:
            self._program.setUniformValue(self._loc_use_vcolor, 1)
            self._pv_vcol_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, n)
            self._pv_vcol_vao.release()
            self._program.setUniformValue(self._loc_use_vcolor, 0)
        runs = getattr(self, "_pv_tex_runs", None)
        if runs:
            self._program.setUniformValue(self._loc_use_tex, 1)
            self._pv_tex_vao.bind()
            for key, start, count in runs:
                # Chunk texture runs key by (path, shade) tuples (bare path
                # when unshaded) — passing the tuple to QImage raised inside
                # paintGL and KILLED the whole preview frame ("moving shows
                # nothing until release", flatpak report).
                path, shade = key if isinstance(key, tuple) else (key, 1.0)
                tex = self._get_texture(path)
                if tex is None:
                    continue
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                self._set_cutout(getattr(tex, "_cutout", False))
                tex.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                tex.release(0)
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._set_cutout(False)
            self._pv_tex_vao.release()
            self._program.setUniformValue(self._loc_use_tex, 0)
        n = getattr(self, "_pv_edges_count", 0)
        if n:
            self._set_color(1.0, 0.45, 0.0, 1.0)   # selection orange: moving
            self._pv_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, n)
            self._pv_edges_vao.release()
        vpv = getattr(self, "_verts_preview", None)
        if vpv is not None and "dots" in vpv:
            self._draw_rider_looks(vpv)
        self._program.setUniformValue(self._loc_mvp, mvp)
        if vpv is not None and vpv.get("bent_ends") is not None \
                and len(vpv["bent_ends"]):
            # The edges a vertex drag stretches: one end rides, one stays.
            import numpy as np
            pm = getattr(self, "_preview_matrix", None)
            if pm is not None:
                # A Rotate's vertex drag: the riding ends turned.
                a = np.array(pm.data(), dtype=np.float64).reshape(4, 4)
                ends = vpv["bent_ends"]
                turned = (ends.astype(np.float64) @ a[:3, :3]
                          + a[3, :3]).astype(np.float32)
                pts = np.where(vpv["bent_rides"][:, None] > 0, turned, ends)
            else:
                off = getattr(self, "_preview_offset", None) or QVector3D()
                d = np.array([off.x(), off.y(), off.z()], dtype=np.float32)
                pts = vpv["bent_ends"] + vpv["bent_rides"][:, None] * d
            raw = pts.astype(np.float32).tobytes()
            if getattr(self, "_pv_bent_vao", None) is None:
                self._pv_bent_vao, self._pv_bent_vbo = self._create_dynamic()
            self._pv_bent_vbo.bind()
            self._pv_bent_vbo.allocate(raw, len(raw))
            self._pv_bent_vbo.release()
            ec = self._effective_style().edge_color
            self._set_color(ec[0], ec[1], ec[2], 1.0)
            self._pv_bent_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, len(pts))
            self._pv_bent_vao.release()

    # ---- Hidden things shown (View ▸ Hidden Objects / Geometry) ------------
    def _sync_hidden_ghosts(self) -> bool:
        """Scratch VBOs of the hidden things the view shows — the hidden
        OBJECTS' chunk arrays and the hidden FACES / EDGES of the mesh being
        edited, its soft edges among them — rebuilt only when the
        placements or the mesh change.
        Returns False when there is nothing to draw."""
        sc = self.scene
        objects = bool(getattr(sc, "show_hidden_objects", False))
        geometry = bool(getattr(sc, "show_hidden_geometry", False))
        if not objects and not geometry:
            self._ghost_key = None
            return False
        key = (self._placements_epoch(), _cache_ver(self), id(sc.mesh),
               objects, geometry)
        if getattr(self, "_ghost_key", None) == key:
            return bool(self._ghost_counts[0] or self._ghost_counts[1]
                        or self._ghost_tex_runs)
        if getattr(self, "_ghost_edges_vao", None) is None:
            self._ghost_edges_vao, self._ghost_edges_vbo = self._create_dynamic()
            self._ghost_vcol_vao, self._ghost_vcol_vbo = \
                self._create_dynamic_vcol()
            self._ghost_tex_vao, self._ghost_tex_vbo = self._create_dynamic_uv()
        edge_parts: list = []
        vcol_parts: list = []
        tex_parts: dict = {}
        if objects:
            for g in self._placements():
                if not getattr(g, "hidden", False) \
                        or getattr(g, "billboard", False):
                    continue
                if not sc._layer_state(g)[0]:
                    continue                  # a hidden LAYER stays hidden
                ch = self._group_chunk(g)
                if ch["edges"]:
                    edge_parts.append(ch["edges"])
                if ch["vcol"]:
                    vcol_parts.append(ch["vcol"])
                for path, raw in ch["by_texture"].items():
                    tex_parts.setdefault(path, []).append(raw)
        if geometry:
            data = array("f")
            for f in sc.mesh.faces:
                if not f.attrs.get("hidden") or not sc._layer_state(f)[0]:
                    continue
                color = f.attrs.get("color") or self.DEFAULT_FACE_COLOR
                r, gg, b = self._shaded_color(tuple(color[:3]),
                                              self._normal_of(f))
                for t0, t1, t2 in self._tris_of(f):
                    data.extend([t0.x(), t0.y(), t0.z(), r, gg, b,
                                 t1.x(), t1.y(), t1.z(), r, gg, b,
                                 t2.x(), t2.y(), t2.z(), r, gg, b])
            if data:
                vcol_parts.append(data.tobytes())
            edata = _ghost_edge_points(sc)
            if edata:
                edge_parts.append(edata.tobytes())
        raw = b"".join(edge_parts)
        self._ghost_edges_vbo.bind()
        self._ghost_edges_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
        self._ghost_edges_vbo.release()
        n_edges = len(raw) // 12
        raw = b"".join(vcol_parts)
        self._ghost_vcol_vbo.bind()
        self._ghost_vcol_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
        self._ghost_vcol_vbo.release()
        n_vcol = len(raw) // 24
        runs: list = []
        blobs: list = []
        off = 0
        for path, parts in tex_parts.items():
            blob = b"".join(parts)
            runs.append((path, off // 20, len(blob) // 20))
            blobs.append(blob)
            off += len(blob)
        raw = b"".join(blobs)
        self._ghost_tex_vbo.bind()
        self._ghost_tex_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
        self._ghost_tex_vbo.release()
        self._ghost_tex_runs = runs
        self._ghost_counts = (n_vcol, n_edges)
        self._ghost_key = key
        return bool(n_vcol or n_edges or runs)

    def _draw_hidden_ghosts(self, mvp) -> None:
        """View ▸ Hidden Objects / Hidden Geometry: what Hide put
        away is drawn as a see-through grid (faces) and dotted lines
        (edges) — its own pass over scratch VBOs, so the normal passes and
        their caches never learn about it. Depth-tested, so it sits where
        it is in the model and still lets everything show through the
        weave; and selectable through the pick index, which is the road
        back to Unhide ▸ Selected."""
        if not self._sync_hidden_ghosts():
            return
        n_vcol, n_edges = self._ghost_counts
        self._program.setUniformValue(self._loc_mvp, mvp)
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        self._program.setUniformValue(self._loc_stipple, 1)
        if n_vcol:
            self._program.setUniformValue(self._loc_use_vcolor, 1)
            self._ghost_vcol_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, n_vcol)
            self._ghost_vcol_vao.release()
            self._program.setUniformValue(self._loc_use_vcolor, 0)
        if self._ghost_tex_runs:
            # A textured face reads as a plain grey weave: the grid is the
            # message, not the picture.
            self._set_color(0.62, 0.62, 0.62, 1.0)
            self._program.setUniformValue(self._loc_back_color,
                                          QVector4D(0.62, 0.62, 0.62, 1.0))
            self._ghost_tex_vao.bind()
            for _path, start, count in self._ghost_tex_runs:
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
            self._ghost_tex_vao.release()
            self._set_back_face_color()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        if n_edges:
            self._program.setUniformValue(self._loc_stipple, 2)
            ec = self._effective_style().edge_color
            self._set_color(ec[0], ec[1], ec[2], 1.0)
            self._ghost_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, n_edges)
            self._ghost_edges_vao.release()
        self._program.setUniformValue(self._loc_stipple, 0)

    @staticmethod
    def _hover_face_data(face: Face, placement=None) -> array:
        """The hover marking's triangles, in WORLD coordinates.

        A face inside a component is stored in its part's OWN coordinates;
        ``placement`` (from :meth:`pick_face_placement`) carries the matrix
        that puts it where it is drawn. Without it the marking sat at the
        part's unplaced, assembled position: metres away from a component
        that had been placed and exploded."""
        m = getattr(placement, "xform", None)
        data = array("f")
        for tri in face.triangulate():
            if m is not None:
                tri = [m.map(p) for p in tri]
            for p in tri:
                data.extend([p.x(), p.y(), p.z()])
        return data

    def _upload_hover_face(self, face: Face, placement=None) -> int:
        """Triangulate ``face`` into the hover-faces VBO. Returns vertex count."""
        data = self._hover_face_data(face, placement)
        self._hover_faces_vbo.bind()
        if data:
            raw = data.tobytes()
            self._hover_faces_vbo.allocate(raw, len(raw))
        else:
            self._hover_faces_vbo.allocate(24)
        self._hover_faces_vbo.release()
        return len(data) // 3

    def _sil_inputs(self, key, cam) -> tuple:
        """Everything the outline pass reads: the scene (``key``), the
        camera, the placements, the groups previewed and the edit context."""
        sc = self.scene
        return (key, cam, self._placements_epoch(),
                getattr(self, "_preview_epoch", 0),
                id(sc.edit_group), getattr(self, "_edit_rest_mode", None))

    def _upload_silhouette_edges(self) -> int:
        """Upload the *profile* edges into the silhouette VBO and return the
        vertex count. A soft (hidden) edge is drawn when it lies on the
        silhouette — its two faces straddle the view, one turned toward the
        camera and one away — so a curved surface shows its outline. A soft
        edge with a single face is always a profile (a boundary). View-dependent,
        called each frame."""
        # Throttle: the silhouette is view-dependent but re-deriving it at
        # most ~12×/s is visually indistinguishable, and at 100k soft edges
        # the NumPy pass still costs ~4 ms a frame during orbits.
        #
        # On a heavy model (outlines costing over 30 ms) they are kept while
        # the camera moves and re-derived once it stops, by a booked
        # repaint (issue #158). They are world-space segments: meanwhile
        # they stay on the geometry, only WHICH edges outline lags.
        import time as _time
        now = _time.monotonic()
        key = (_content_ver(self), id(self.scene.mesh))
        last = getattr(self, "_sil_last", None)
        wait = 0.08
        # While the camera is moving (it moved since the last frame) and
        # the outlines are expensive, keep them: re-deriving them mid-orbit
        # made a 300–440 ms hitch every second or so on the model of #158.
        # The booked repaint below redraws them once the camera stops.
        cam = self.camera.projection_matrix() * self.camera.view_matrix()
        cam = tuple(cam.data())
        moving = getattr(self, "_sil_cam", None) not in (None, cam)
        self._sil_cam = cam
        if moving:
            self._sil_cam_t = now
        # Nothing an outline depends on moved since the VBO was filled —
        # the scene (version), the camera, the groups being previewed — so
        # the VBO holds this very outline: no need to wait out the throttle
        # and derive it again. A drag beside a plant of 21 406 placements
        # re-derived them (~340 ms) on every move of the pointer (#158).
        same_view = self._sil_inputs(key, cam)
        if last is not None and len(last) > 3 and last[3] == same_view:
            return last[2]
        # «Stopped» means 600 ms without a camera change: a run of wheel
        # notches is a string of short pauses, and re-deriving after each
        # one blocked the next notch (live profile, #158).
        still = now - getattr(self, "_sil_cam_t", 0.0)
        if getattr(self, "_sil_cost", 0.0) > 0.03 and still < 0.6:
            wait = (now - last[1] if last else 0.0) + (0.6 - still)
        if last is not None and last[0] == key and now - last[1] < wait:
            if getattr(self, "_sil_refresh_booked", False) is False:
                from PySide6.QtCore import QTimer
                self._sil_refresh_booked = True

                def _refresh():
                    self._sil_refresh_booked = False
                    self.update()
                QTimer.singleShot(int((wait - (now - last[1])) * 1000) + 20,
                                  self, _refresh)
            return last[2]        # VBO still holds the last upload

        # Loose soft edges run the SAME vectorised view test as group
        # chunks: per-edge Python here froze orbits after an explode dumped
        # a group's curved surfaces into the loose mesh (38k soft edges =
        # ~600 ms EVERY frame, piscina.igz user report). The cache bakes
        # endpoints + face normals/centroids once per edit; each frame is
        # one einsum.
        import numpy as np
        cached = getattr(self, "_soft_edges_cache", None)
        if cached is None or cached[0] != key:
            softs = [e for e in self.scene.loose_mesh.edges
                     if getattr(e, "soft", False)
                     and not getattr(e, "hidden", False)
                     and self.scene.entity_visible(e) and e.faces]
            if softs:
                pts = np.empty((len(softs), 6))
                single = np.empty(len(softs), dtype=bool)
                # Face planes via one vectorized cross product instead of
                # per-face Python normal()/centroid() (_newell dominated the
                # edit frame at 25k+ faces). For the view-side sign test any
                # point ON the plane works, so the first loop vertex serves
                # as the anchor; the plane normal comes from the first two
                # loop edges (faces are planar).
                tri0 = np.empty((len(softs), 3, 3))
                tri1 = np.empty((len(softs), 3, 3))
                from core.profile_edges import edge_normal_sign
                windings = {}
                normal_signs = np.empty(len(softs))
                for i, e in enumerate(softs):
                    normal_signs[i] = edge_normal_sign(e, windings)
                    pts[i] = (e.a.x(), e.a.y(), e.a.z(),
                              e.b.x(), e.b.y(), e.b.z())
                    v = e.faces[0].vertices
                    tri0[i] = ((v[0].x(), v[0].y(), v[0].z()),
                               (v[1].x(), v[1].y(), v[1].z()),
                               (v[2].x(), v[2].y(), v[2].z()))
                    # A 1-face soft edge is an open-surface boundary (always
                    # a profile); a 2-face one straddles the view or hides.
                    single[i] = len(e.faces) != 2
                    v = (e.faces[1] if len(e.faces) == 2 else e.faces[0]).vertices
                    tri1[i] = ((v[0].x(), v[0].y(), v[0].z()),
                               (v[1].x(), v[1].y(), v[1].z()),
                               (v[2].x(), v[2].y(), v[2].z()))
                n0 = np.cross(tri0[:, 1] - tri0[:, 0], tri0[:, 2] - tri0[:, 0])
                n1 = np.cross(tri1[:, 1] - tri1[:, 0], tri1[:, 2] - tri1[:, 0])
                n1 *= normal_signs[:, None]
                c0 = tri0[:, 0]
                c1 = tri1[:, 0]
                arrays = (pts.astype(np.float32), n0, c0, n1, c1, single)
            else:
                arrays = None
            cached = (key, arrays)
            self._soft_edges_cache = cached
        eye = self.camera.eye()
        chunks: list = []
        if cached[1] is not None:
            pts, n0, c0, n1, c1, single = cached[1]
            e_np = np.array([eye.x(), eye.y(), eye.z()])
            s0 = np.einsum("ij,ij->i", n0, c0 - e_np)
            s1 = np.einsum("ij,ij->i", n1, c1 - e_np)
            mask = single | ((s0 < 0) != (s1 < 0))
            chunks.append(pts[mask].tobytes())
        else:
            chunks.append(b"")
        pv_sil = getattr(self, "_preview_groups", None) or ()
        # Silhouettes are a full-strength black outline; drawing them over a
        # faded (or hidden) context would put the heaviest line in the frame
        # on exactly the geometry meant to recede. Only the subject profiles.
        skip_context = (self.scene.edit_group is not None
                        and self._edit_rest_mode in ("fade", "hide"))
        # Which placements get an outline changes with the placements, not
        # with the camera: the visibility test of every one of them ran on
        # every frame (~100 ms on 21 406 placements, issue #158).
        # The groups being previewed are left out when drawn, not here: the
        # list (and the per-prototype table made from it) then lasts while
        # a Move picks an object up — rebuilt, it was ~1 s on the plant.
        # Matrices alone (a Move picking up or putting down) change none of
        # the three tests: the list is kept, re-stamped (~0.1 s each way).
        gkey = (self._placements_epoch(), skip_context)
        gmemo = getattr(self, "_sil_groups", None)
        if gmemo is not None and gmemo[0] != gkey and \
                gmemo[0][1] == skip_context and \
                gmemo[2] is self.scene.mesh and \
                self._epoch_only_matrices(gmemo[0][0], gkey[0]):
            self._placements()        # nested proxies: composed matrices
            gmemo = self._sil_groups = (gkey,) + gmemo[1:]
        if gmemo is not None and gmemo[0] == gkey:
            groups = gmemo[1]
        else:
            def outlined(g):
                return (self.scene.entity_visible(g)
                        and not getattr(g, "billboard", False)
                        and not (skip_context
                                 and self._draws_in_edit_context(g)))
            groups = None
            if (gmemo is not None and gmemo[0][1] == skip_context
                    and gmemo[2] is self.scene.mesh):
                groups = self._refilter(gmemo[0][0], gmemo[1],
                                        self._placements(), outlined)
            if groups is None:
                groups = [g for g in self._placements() if outlined(g)]
            self._sil_groups = (gkey, groups, self.scene.mesh)
        if groups:
            import numpy as np
            e_np = np.array([eye.x(), eye.y(), eye.z()])
            planes = getattr(self, "_frame_planes", None)
            got, groups = self._instanced_silhouettes(groups, eye, planes,
                                                      skip=pv_sil)
            if pv_sil:
                groups = [g for g in groups if id(g) not in pv_sil]
            if got:
                chunks.append(got)
            # Each loose group's chunk, kept while the scene's version is
            # the one _group_chunk keys its entries by: a refresh asked all
            # ~880 groups of the Plaza for theirs (their paint, their
            # checks) every ~80 ms of an orbit, ~12 ms each time (19-11).
            vpv = getattr(self, "_verts_preview", None)
            skey = (self.scene.version, id(self.scene.mesh),
                    None if vpv is None else id(vpv))
            smemo = getattr(self, "_sil_chunk_memo", None)
            if smemo is None or smemo[0] != skey:
                smemo = self._sil_chunk_memo = (skey, {})
            known = smemo[1]
            for g in groups:
                if getattr(g, "xform", None) is not None:
                    got = self._instance_silhouette(g, eye, planes)
                    if got is not None:
                        if got:
                            chunks.append(got)
                        continue
                hit = known.get(id(g))
                if hit is not None and hit[0] is g and hit[1] is g.mesh:
                    ch = hit[2]
                else:
                    ch = self._group_chunk(g)
                    known[id(g)] = (g, g.mesh, ch)
                if ch["soft_pts"] is None:
                    continue
                bb = ch.get("bbox")
                if (planes is not None and bb is not None
                        and not self._aabb_visible(planes, bb[0], bb[1])):
                    continue        # whole chunk off screen: skip the einsum
                s0 = np.einsum("ij,ij->i", ch["soft_n0"],
                               ch["soft_c0"] - e_np)
                s1 = np.einsum("ij,ij->i", ch["soft_n1"],
                               ch["soft_c1"] - e_np)
                mask = ch["soft_single"] | ((s0 < 0) != (s1 < 0))
                if mask.any():
                    chunks.append(ch["soft_pts"][mask].tobytes())
        raw = b"".join(chunks)
        self._silhouette_vbo.bind()
        if raw:
            self._silhouette_vbo.allocate(raw, len(raw))
        else:
            self._silhouette_vbo.allocate(24)
        self._silhouette_vbo.release()
        count = len(raw) // 12
        self._sil_last = (key, now, count, self._sil_inputs(key, cam))
        self._sil_cost = _time.monotonic() - now
        return count

    def _silhouette_table(self, groups):
        """Per prototype, the arrays the silhouette pass reads for all its
        placements at once — built when the placements change, not per
        frame. ``(table, rest)``: ``rest`` are the placements it does not
        take (loose groups, face-me, a singular matrix)."""
        import numpy as np
        ids = tuple(map(id, groups))
        key = (self._placements_epoch(), ids)
        memo = getattr(self, "_sil_table", None)
        if memo is not None and memo[0] == key:
            return memo[1], memo[2]
        if (memo is not None and memo[0][1] == ids
                and self._epoch_only_matrices(memo[0][0], key[0])
                and self._sil_table_moved(memo[1], memo[2])):
            # Only matrices moved (a Move put an object down): the rows of
            # the placements that moved, not the whole table (~1 s).
            self._sil_table = (key, memo[1], memo[2])
            return memo[1], memo[2]
        # An object or two added or taken away (a Delete, a Paste, their
        # undo): the rows of every unchanged object come from the old
        # table, and a prototype none of whose rows changed keeps its
        # entry — and with it the outline last worked out for this view.
        kept = (self._epoch_kept_tops(memo[0][0], key[0], ctx=True)
                if memo is not None else None)
        old_rows: dict = {}
        old_rest: set = set()
        if kept:
            for t in memo[1]:
                for j, g in enumerate(t["groups"]):
                    old_rows[id(g)] = (t, j)
            old_rest = {id(g) for g in memo[2]}
        top_of = self._placement_top
        inf = float("inf")
        by_proto: dict = {}          # uid → [old entry, base, rows]
        rest: list = []
        for g in groups:
            if kept and top_of(g) in kept:
                hit = old_rows.get(id(g))
                if hit is None:
                    if id(g) in old_rest:
                        rest.append(g)
                    continue
                t, j = hit
                ent = by_proto.get(t["uid"])
                if ent is None:
                    ent = by_proto[t["uid"]] = [t, None, []]
                elif ent[0] is None:
                    ent[0] = t
                ent[2].append((g, t, j))
                continue
            if getattr(g, "xform", None) is None \
                    or getattr(g, "billboard", False):
                rest.append(g)
                continue
            base = self._proto_base_chunk(g.mesh, _paint_of(self, g))
            if base["soft_pts"] is None:
                continue                      # nothing curved to outline
            box, inv = self._placement_frame(g)
            if inv is None:
                rest.append(g)
                continue
            ent = by_proto.get(base["uid"])
            if ent is None:
                ent = by_proto[base["uid"]] = [None, base, []]
            elif ent[1] is None:
                ent[1] = base
            ent[2].append((g, None, (
                np.array(g.xform.data(), np.float64)
                .reshape(4, 4, order="F")[:3],
                np.array(inv.data(), np.float64).reshape(4, 4, order="F")[:3],
                box[0] if box else (-inf, -inf, -inf),
                box[1] if box else (inf, inf, inf))))
        table = []
        for uid, (t, base, rows) in by_proto.items():
            if (t is not None and len(rows) == len(t["groups"])
                    and all(src is t and j == k
                            for k, (_g, src, j) in enumerate(rows))):
                table.append(t)               # as it was, outline and all
                continue
            gl = [r[0] for r in rows]
            fwds, invs, los, his = [], [], [], []
            for g, src, j in rows:
                if src is None:
                    fwd, inv, lo, hi = j
                else:
                    fwd, inv = src["fwd"][j], src["inv"][j]
                    lo, hi = src["lo"][j], src["hi"][j]
                fwds.append(fwd)
                invs.append(inv)
                los.append(lo)
                his.append(hi)
            if base is not None:
                n0 = np.asarray(base["soft_n0"], np.float64)
                n1 = np.asarray(base["soft_n1"], np.float64)
                arrays = {
                    "seg": np.asarray(base["soft_pts"], np.float64).reshape(-1, 2, 3),
                    "n0": n0, "n1": n1,
                    "d0": np.einsum("ij,ij->i", n0, np.asarray(base["soft_c0"], np.float64)),
                    "d1": np.einsum("ij,ij->i", n1, np.asarray(base["soft_c1"], np.float64)),
                    "single": np.asarray(base["soft_single"], bool)}
            else:
                arrays = {k: t[k] for k in ("seg", "n0", "n1", "d0", "d1",
                                            "single")}
            table.append({
                **arrays,
                "fwd": np.stack(fwds), "inv": np.stack(invs),
                "lo": np.asarray(los, np.float64), "hi": np.asarray(his, np.float64),
                "groups": gl, "xf": [tuple(g.xform.data()) for g in gl],
                "ids": frozenset(map(id, gl)), "rev": 0, "uid": uid,
            })
        self._sil_table = (key, table, rest)
        return table, rest

    def _sil_table_moved(self, table, rest) -> bool:
        """Bring the rows of the silhouette table whose placement's matrix
        changed up to date, in place; ``False`` (nothing touched that
        matters) when one cannot be — the table is then made again."""
        import numpy as np
        for g in rest:
            if getattr(g, "xform", None) is not None:
                return False      # a singular matrix may not be one now
        todo = []
        for t in table:
            xf = t["xf"]
            for j, g in enumerate(t["groups"]):
                d = tuple(g.xform.data())
                if d != xf[j]:
                    box, inv = self._placement_frame(g)
                    if inv is None:
                        return False
                    todo.append((t, j, d, box, inv))
        inf = float("inf")
        for t, j, d, box, inv in todo:
            t["fwd"][j] = np.array(d, np.float64).reshape(4, 4, order="F")[:3]
            t["inv"][j] = (np.array(inv.data(), np.float64)
                           .reshape(4, 4, order="F")[:3])
            t["lo"][j] = box[0] if box else (-inf, -inf, -inf)
            t["hi"][j] = box[1] if box else (inf, inf, inf)
            t["xf"][j] = d
            t["rev"] += 1
        return True

    def _instanced_silhouettes(self, groups, eye, planes, skip=()):
        """Silhouette bytes of every component placement in ``groups``,
        prototype by prototype: the frustum cull and the «faces straddle
        the view» test run as one NumPy pass over all the placements of a
        prototype, with the eye in each one's local coordinates (see
        ``_instance_silhouette``, the one-placement version they must
        agree with). A per-placement Python loop cost 1.7 s a frame on a
        model of 21 406 placements (issue #158). Returns ``(bytes, rest)``
        with the placements left to the per-group path. ``skip``: ids of
        placements left out (the ones a preview draws)."""
        import numpy as np
        table, rest = self._silhouette_table(groups)
        if not table:
            return b"", rest
        e = np.array([eye.x(), eye.y(), eye.z()])
        pl = np.asarray(planes, np.float64) if planes is not None else None
        out = []
        # Per prototype, the last answer for this very view: when a Move
        # puts an object down only its prototype's rows moved, and the
        # others need not be worked out again (~0.3 s on the plant).
        view = (tuple(e.tolist()),
                tuple(map(tuple, planes)) if planes is not None else None)
        for t in table:
            # Only the left-out placements that are this prototype's.
            mine = (frozenset(k for k in skip if k in t["ids"])
                    if skip else frozenset())
            memo = t.get("memo")
            if (memo is not None and memo[0] == view and memo[1] == t["rev"]
                    and memo[3] == mine):
                if memo[2]:
                    out.append(memo[2])
                continue
            t_out = []
            self._instanced_silhouette_rows(t, e, pl, mine, t_out)
            raw = b"".join(t_out)
            t["memo"] = (view, t["rev"], raw, mine)
            if raw:
                out.append(raw)
        return b"".join(out), rest

    def _instanced_silhouette_rows(self, t, e, pl, skip, out) -> None:
        """One prototype's part of :meth:`_instanced_silhouettes`."""
        import numpy as np
        if pl is not None:
            n = pl[:, :3]
            pick = np.where(n[:, None, :] >= 0.0, t["hi"][None], t["lo"][None])
            keep = ((pick * n[:, None, :]).sum(axis=2)
                    + pl[:, 3][:, None] >= 0.0).all(axis=0)
        else:
            keep = np.ones(len(t["fwd"]), bool)
        if skip:
            keep &= np.fromiter((id(g) not in skip for g in t["groups"]),
                                bool, count=len(t["groups"]))
        rows = np.flatnonzero(keep)
        if not len(rows):
            return
        ne = len(t["d0"])
        step = max(1, int(4_000_000 // max(ne, 1)))
        for a in range(0, len(rows), step):
            rr = rows[a:a + step]
            inv = t["inv"][rr]
            eye_l = inv[:, :, :3] @ e + inv[:, :, 3]          # (K, 3)
            s0 = t["d0"][None, :] - eye_l @ t["n0"].T
            s1 = t["d1"][None, :] - eye_l @ t["n1"].T
            mask = t["single"][None, :] | ((s0 < 0) != (s1 < 0))
            r, c = np.nonzero(mask)
            if not len(r):
                continue
            m = t["fwd"][rr][r]                               # (N, 3, 4)
            seg = t["seg"][c]                                 # (N, 2, 3)
            pts = np.einsum("nij,nkj->nki", m[:, :, :3], seg) \
                + m[:, None, :, 3]
            out.append(pts.astype(np.float32).tobytes())

    def _instance_silhouette(self, g, eye, planes):
        """Silhouette bytes of a component placement, worked out on the
        PROTOTYPE's shared arrays — ``None`` when it cannot be (a singular
        matrix), and the caller bakes as before.

        Which side of a plane the eye is on does not change under the
        placement's affine map, and a mirror flips BOTH faces of a soft
        edge at once, so «its faces straddle the view» reads the same with
        the eye taken into local coordinates. Only the edges that pass are
        carried to the world. Baking every placement to world coordinates
        for this test was the last per-placement bake of a frame: with
        profiles on, the 21 000 placements of issue #158 baked 14 million
        faces the instanced draw never needed."""
        import numpy as np
        base = self._proto_base_chunk(g.mesh, _paint_of(self, g))
        if base["soft_pts"] is None:
            return b""
        bb, inv = self._placement_frame(g)
        if planes is not None and bb is not None \
                and not self._aabb_visible(planes, bb[0], bb[1]):
            return b""
        if inv is None:
            return None
        le = inv.map(eye)
        e_np = np.array([le.x(), le.y(), le.z()])
        s0 = np.einsum("ij,ij->i", base["soft_n0"], base["soft_c0"] - e_np)
        s1 = np.einsum("ij,ij->i", base["soft_n1"], base["soft_c1"] - e_np)
        mask = base["soft_single"] | ((s0 < 0) != (s1 < 0))
        if not mask.any():
            return b""
        m = np.array(g.xform.data(), dtype=np.float64).reshape(4, 4, order="F")
        seg = base["soft_pts"].reshape(-1, 6)[mask].astype(np.float64)
        pts = seg.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        return pts.astype(np.float32).tobytes()

    def _upload_hover_edge(self, edge: Edge) -> int:
        """Upload the hovered edge — or, for a curve segment, its whole contour
        (what a click would select) — into the hover-edges VBO. Returns the
        vertex count to draw."""
        edges = (self.scene.mesh.curve_edges(edge)
                 if getattr(edge, "curve", None) is not None else [edge])
        if edge not in edges:      # e.g. a group's edge — not in the main mesh
            edges = [edge]
        data = array("f")
        for e in edges:
            data.extend([e.a.x(), e.a.y(), e.a.z(),
                         e.b.x(), e.b.y(), e.b.z()])
        self._hover_edges_vbo.bind()
        raw = data.tobytes()
        self._hover_edges_vbo.allocate(raw, len(raw))
        self._hover_edges_vbo.release()
        return len(data) // 3

    def _draw_preview_faces(self) -> None:
        """Triangulate and draw the active tool's solid preview faces (if any).
        A face carrying attrs shows its REAL look — painted colour, or its
        texture (the tool re-anchors the uvw map to the drag) — so a paste
        drags the actual model; bare faces keep the warm cream of the
        push/pull preview. Depth-tested with a polygon offset so the
        wireframe sits cleanly on top."""
        tool = self.active_tool
        provider = getattr(tool, "preview_faces", None) if tool is not None else None
        if not callable(provider):
            return
        faces = provider()
        if not faces:
            return
        data, runs, by_texture = self._bake_preview_faces(faces, tool)
        if not data and not by_texture:
            return
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        if data:
            self._preview_faces_vbo.bind()
            raw = data.tobytes()
            self._preview_faces_vbo.allocate(raw, len(raw))
            self._preview_faces_vbo.release()
            self._preview_faces_vao.bind()
            last = None
            draw = self._gl.glDrawArrays
            for rgb, start, count in runs:
                if rgb != last:
                    # A preview has no back: it is an overlay, not a solid
                    # with an inside. Its walls are wound however the sweep
                    # produced them and nothing surrounds them to hide the
                    # ones turned away, so the real back-face tint painted
                    # the pocket of a push-in blue over the shape being
                    # formed (Marco, 2026-08-27). Both sides take the face's
                    # own colour — _set_color sets both. A run of the colour
                    # just set draws on it (a vertex drag stretching a
                    # thousand faces set the colour a thousand times).
                    self._set_color(rgb[0], rgb[1], rgb[2], 1.0)
                    last = rgb
                draw(GL_TRIANGLES, start, count)
            self._preview_faces_vao.release()
            self._set_back_face_color()          # leave the real tint behind
        if by_texture:
            # A tool may want its textured preview translucent (Position
            # Texture shows the image through).
            opacity = float(getattr(tool, "preview_opacity", 1.0) or 1.0)
            if opacity < 1.0:
                self._program.setUniformValue1f(self._loc_opacity, opacity)
            self._program.setUniformValue(self._loc_use_tex, 1)
            self._preview_tex_vao.bind()
            for key, buf in by_texture.items():
                path, shade = key if isinstance(key, tuple) else (key, 1.0)
                tex_obj = self._get_texture(path)
                if tex_obj is None:
                    continue
                raw = buf.tobytes()
                self._preview_tex_vbo.bind()
                self._preview_tex_vbo.allocate(raw, len(raw))
                self._preview_tex_vbo.release()
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                tex_obj.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, 0, len(buf) // 5)
                tex_obj.release(0)
            self._preview_tex_vao.release()
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._program.setUniformValue(self._loc_use_tex, 0)
            if opacity < 1.0:
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    def _bake_preview_faces(self, faces, tool=None):
        """``(data, runs, by_texture)`` for :meth:`_draw_preview_faces`:
        the Rust engine's bake when it has one and it passed its check
        (:meth:`_preview_native_ok`), else :meth:`_bake_preview_faces_py`.
        A push's overlay on a 100-sided textured pillar is 101 fresh faces a
        frame: ~8 ms of earcut, Newell and UV walks in Python, well under
        1 ms in Rust (19-11)."""
        out = None
        if self._preview_native_ok():
            arrays = getattr(tool, "preview_sweep_arrays", None)
            spec = arrays() if callable(arrays) else None
            moved = getattr(faces, "moved_parts", None)
            if spec is not None and spec[0] is faces:
                out = self._bake_preview_sweep_arrays_native(spec[1])
            elif (moved is not None
                  and len(faces) >= self.MOVED_NATIVE_MIN_FACES):
                out = self._bake_preview_moved_native(moved)
            else:
                sweeps = getattr(tool, "preview_sweeps", None)
                spec = sweeps() if callable(sweeps) else None
                if spec is not None and spec[0] is faces:
                    out = self._bake_preview_sweeps_native(spec[1])
                else:
                    out = self._bake_preview_faces_native(faces)
        if out is None:
            out = self._bake_preview_faces_py(faces)
        return out

    def _bake_preview_faces_py(self, faces):
        """The preview faces triangulated as the preview VBOs take them:
        ``data`` the colour faces' positions, ``runs`` one ``(shaded_rgb,
        start_vertex, count)`` per colour face, ``by_texture`` ``(path,
        shade)`` → interleaved pos+uv (see _append_textured_face)."""
        data = array("f")
        runs = []                        # (shaded_rgb, start_vertex, count)
        by_texture: dict = {}            # (path, shade) -> interleaved pos+uv
        for face in faces:
            attrs = getattr(face, "attrs", None) or {}
            tex = attrs.get("texture")
            if tex and tex.get("path"):
                self._append_textured_face(by_texture, face, tex)
                continue
            color = attrs.get("color") or self.DEFAULT_FACE_COLOR
            start = len(data) // 3
            for t0, t1, t2 in self._tris_of(face):
                data.extend([
                    t0.x(), t0.y(), t0.z(),
                    t1.x(), t1.y(), t1.z(),
                    t2.x(), t2.y(), t2.z(),
                ])
            runs.append((self._shaded_color(tuple(color[:3]), self._normal_of(face)),
                         start, len(data) // 3 - start))
        return data, runs, by_texture

    def _preview_mat(self, attrs, table) -> int:
        """The row of ``table`` (``(rows, colours, paths, memo, groups)``,
        see :meth:`_bake_preview_faces_native`) for a preview face's
        ``attrs``: a colour, or a texture with what ``face_uv_axes`` reads
        of it."""
        rows, colors, paths, memo, groups = table
        tex = attrs.get("texture") if attrs else None
        if tex and tex.get("path"):
            key = ("t", id(tex))
            k = memo.get(key)
            if k is None:
                path = tex["path"]
                g = groups.get(path)
                if g is None:
                    g = groups[path] = len(paths)
                    paths.append(path)
                uvw = tex.get("uvw")
                if uvw:
                    m = [float(uvw[i]) for i in range(8)]
                    row = [1.0, float(g), 1.0, *m, 0.0, 1.0, 1.0]
                else:
                    rot = float(tex.get("rot", 0.0) or 0.0)
                    sw = float(tex.get("sw", 1.0) or 1.0)
                    sh = float(tex.get("sh", 1.0) or 1.0)
                    row = [1.0, float(g), 0.0] + [0.0] * 8 + [rot, sw, sh]
                k = memo[key] = len(rows)
                rows.append(row)
                colors.append(None)
            return k
        color = (attrs.get("color") if attrs else None) or self.DEFAULT_FACE_COLOR
        rgb = tuple(color[:3])
        key = ("c", rgb)
        k = memo.get(key)
        if k is None:
            k = memo[key] = len(rows)
            rows.append([0.0] * 14)
            colors.append(rgb)
        return k

    def _preview_native_out(self, out, table):
        """The engine's bake as ``_bake_preview_faces_py`` returns it."""
        if out is None:
            return None
        col, nruns, tex = out
        _rows, colors, paths, _memo, _groups = table
        data = array("f")
        data.frombytes(col)
        shade_rgb = Viewport._shade_rgb
        runs = [(shade_rgb(colors[m], shade), start, count)
                for m, start, count, shade in nruns]
        by_texture: dict = {}
        for g, shade, raw in tex:
            buf = by_texture[(paths[g], shade)] = array("f")
            buf.frombytes(raw)
        return data, runs, by_texture

    def _bake_preview_faces_native(self, faces):
        """:meth:`_bake_preview_faces_py` in the Rust engine
        (``preview_faces_bake``), or ``None``: no engine, a mesh face among
        them, or anything Python would make another way (it then runs and
        does what it always did)."""
        import numpy as np
        import core._native as _native
        nat = _native.native
        try:
            xyz = array("f")
            sizes, counts, fmat = [], [], []
            table = ([], [], [], {}, {})
            for face in faces:
                if hasattr(face, "loop"):
                    return None
                fmat.append(self._preview_mat(
                    getattr(face, "attrs", None) or {}, table))
                rings = [face.vertices, *face.holes]
                counts.append(len(rings))
                for ring in rings:
                    sizes.append(len(ring))
                    for p in ring:
                        xyz.extend((p.x(), p.y(), p.z()))
            pos = np.frombuffer(xyz, dtype=np.float32).reshape(-1, 3)
            mats = np.array(table[0], dtype=np.float64).reshape(-1, 14)
            lt = self._LIGHT
            out = nat.preview_faces_bake(pos, sizes, counts, fmat, mats,
                                         (lt.x(), lt.y(), lt.z()),
                                         _native.qt_hypot())
            return self._preview_native_out(out, table)
        except Exception:  # noqa: BLE001 — Python bakes it (and says why)
            return None

    #: Fewest faces a Move's vertex drag stretches for the engine to bake
    #: them from the arrays packed at the grab (``MovePreview``); below
    #: it the faces are walked as any preview's — a few faces take as long
    #: either way, and the packing is a frame's walk.
    MOVED_NATIVE_MIN_FACES = 24

    def _bake_preview_moved_native(self, moved):
        """The bake of a Move's stretched faces (``tools.move._MovedFaces``
        ``moved_parts``: ``(shown, moving, paint, d)``) made by the
        engine's ``MovePreview`` — packed once per drag, from the faces'
        rings and which corners ride — at the offset ``d``: the bytes
        :meth:`_bake_preview_faces_py` makes of the moved faces, its runs
        of neighbouring faces of one colour and shade joined (the same
        triangles drawn the same). ``None``: Python bakes the frame."""
        import core._native as _native
        nat = _native.native
        if nat is None or not hasattr(nat, "MovePreview"):
            return None
        if (len(moved) > 4 and moved[4] is not None
                and not hasattr(nat.MovePreview, "bake_placed")):
            return None
        shown, moving, paint, d = moved[:4]
        m = moved[4] if len(moved) > 4 else None
        try:
            import numpy as np
            memo = getattr(self, "_moved_pack_memo", None)
            key = (self.scene.version, id(moving), id(paint))
            if memo is None or memo[0] != key or memo[1] is not shown:
                memo = self._moved_pack_memo = (
                    key, shown, self._pack_moved(nat, shown, moving, paint))
            pack, table, rverts, rinv = memo[2]
            lt = self._LIGHT
            light = (lt.x(), lt.y(), lt.z())
            if m is None:
                out = pack.bake((d.x(), d.y(), d.z()), light,
                                _native.qt_hypot())
            else:
                # A Rotate: each riding vertex placed once, by Qt's map —
                # the very floats the tool's faces hold.
                xyz = array("f")
                for v in rverts:
                    xyz.extend(m.map(v.position).toTuple())
                at = np.frombuffer(xyz, dtype=np.float32).reshape(-1, 3)
                out = pack.bake_placed(np.ascontiguousarray(at[rinv]),
                                       light, _native.qt_hypot())
            return self._preview_native_out(out, table)
        except Exception:  # noqa: BLE001 — Python bakes it
            return None

    def _pack_moved(self, nat, shown, moving, paint):
        """``(MovePreview, material table, riding vertices, each riding
        corner's index into them)`` of the faces ``shown`` (mesh faces)
        with the corners in ``moving`` riding: their rings as
        ``preview_faces`` builds them, their look ``effective_attrs`` of
        their own under ``paint``."""
        import numpy as np
        from core.materials import effective_attrs
        xyz = array("f")
        ride = []
        sizes, counts, fmat = [], [], []
        table = ([], [], [], {}, {})
        rverts: list = []                 # the riding vertices, once each
        rat: dict = {}
        rinv: list = []                   # each riding corner's of them
        for f in shown:
            fmat.append(self._preview_mat(
                effective_attrs(f.attrs, paint) or {}, table))
            rings = [f.loop, *f.hole_loops]
            counts.append(len(rings))
            for ring in rings:
                sizes.append(len(ring))
                for v in ring:
                    p = v.position
                    xyz.extend((p.x(), p.y(), p.z()))
                    on = id(v) in moving
                    ride.append(on)
                    if on:
                        k = rat.get(id(v))
                        if k is None:
                            k = rat[id(v)] = len(rverts)
                            rverts.append(v)
                        rinv.append(k)
        pos = np.frombuffer(xyz, dtype=np.float32).reshape(-1, 3)
        mats = np.array(table[0], dtype=np.float64).reshape(-1, 14)
        pack = nat.MovePreview(pos, np.array(ride, dtype=bool),
                               np.array(sizes, dtype=np.int64),
                               np.array(counts, dtype=np.int64),
                               np.array(fmat, dtype=np.int64), mats)
        return pack, table, rverts, np.array(rinv, dtype=np.int64)

    def _bake_preview_sweeps_native(self, sweeps):
        """The bake of a push's overlay (``tools.pushpull._build_light_faces``)
        made in the engine from ``sweeps`` — ``(rings, off, cap_attrs,
        wall_attrs)`` per swept face, ``rings`` its base rings outer first —
        without walking the faces at all (``preview_sweep_bake``)."""
        import numpy as np
        import core._native as _native
        nat = _native.native
        try:
            xyz = array("f")
            sizes, counts, offs, caps, walls = [], [], array("f"), [], []
            table = ([], [], [], {}, {})
            for rings, off, cap_attrs, wall_attrs in sweeps:
                caps.append(self._preview_mat(cap_attrs or {}, table))
                walls.append(self._preview_mat(wall_attrs or {}, table))
                offs.extend((off.x(), off.y(), off.z()))
                counts.append(len(rings))
                for ring in rings:
                    sizes.append(len(ring))
                    for p in ring:
                        xyz.extend((p.x(), p.y(), p.z()))
            pos = np.frombuffer(xyz, dtype=np.float32).reshape(-1, 3)
            off3 = np.frombuffer(offs, dtype=np.float32).reshape(-1, 3)
            mats = np.array(table[0], dtype=np.float64).reshape(-1, 14)
            lt = self._LIGHT
            out = nat.preview_sweep_bake(pos, sizes, counts, off3, caps, walls,
                                         mats, (lt.x(), lt.y(), lt.z()),
                                         _native.qt_hypot())
            return self._preview_native_out(out, table)
        except Exception:  # noqa: BLE001 — Python bakes it
            return None

    def _bake_preview_sweep_arrays_native(self, arrays):
        """:meth:`_bake_preview_sweeps_native` from the arrays a tool
        already holds (``preview_sweep_arrays``: the sweep read once a
        frame, for this bake and the wireframe alike; Bloque 6c)."""
        import core._native as _native
        nat = _native.native
        try:
            pos, sizes, counts, off3, caps, walls, _cos = arrays
            table = ([], [], [], {}, {})
            cap_m = [self._preview_mat(a or {}, table) for a in caps]
            wall_m = [self._preview_mat(a or {}, table) for a in walls]
            import numpy as np
            mats = np.array(table[0], dtype=np.float64).reshape(-1, 14)
            lt = self._LIGHT
            out = nat.preview_sweep_bake(pos, sizes, counts, off3, cap_m,
                                         wall_m, mats,
                                         (lt.x(), lt.y(), lt.z()),
                                         _native.qt_hypot())
            return self._preview_native_out(out, table)
        except Exception:  # noqa: BLE001 — Python bakes it
            return None

    def _preview_lines_native(self, tool):
        """The float32 bytes :meth:`_draw_rubber_band` uploads for a tool
        whose wireframe is a sweep's (``preview_sweep_arrays``), made by the
        engine (``preview_sweep_lines``) once its preview bake passed its
        check — else ``None`` (the tool's ``rubber_band_lines``)."""
        arrays = getattr(tool, "preview_sweep_arrays", None)
        if not callable(arrays) or not self._preview_native_ok():
            return None
        spec = arrays()
        if spec is None:
            return None
        import core._native as _native
        nat = _native.native
        if not hasattr(nat, "preview_sweep_lines"):
            return None
        try:
            pos, sizes, counts, off3, _caps, _walls, cos = spec[1]
            return nat.preview_sweep_lines(pos, sizes, counts, off3, cos,
                                           _native.qt_hypot())
        except Exception:  # noqa: BLE001 — Python draws it
            return None

    #: Whether the engine's preview bake matched the Python one on the
    #: fixed sample (None: not tried yet). Once per session.
    _preview_native_state = None

    def _schedule_preview_check(self, delay_ms: int = 1500) -> None:
        """Run :meth:`_check_preview_native` once, soon after the view is
        on screen and not inside a paint: the check bakes its sample in
        Python too (~15 ms, 19-11), which a drag's first frame must not
        wait for."""
        if getattr(self, "_preview_check_due", False):
            return
        self._preview_check_due = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(delay_ms, self, self._check_preview_native)

    def _preview_native_ok(self) -> bool:
        """Whether the engine bakes preview faces: only once it has baked a
        fixed sample — every kind of face, map and turn — to the very bytes
        the Python bake makes on this machine (``pow``, ``cos``, ``sin``
        and Qt's ``hypot`` come from C libraries that may round otherwise).
        Not checked yet: Python bakes this frame and the check is queued."""
        state = Viewport._preview_native_state
        if state is None:
            self._schedule_preview_check(0)
            return False
        return state

    def _check_preview_native(self) -> bool:
        """The check :meth:`_preview_native_ok` reads (see there)."""
        self._preview_check_due = False
        state = Viewport._preview_native_state
        if state is not None:
            return state
        # Not while the hand is working in the view: the check bakes its
        # sample in Python too (~45 ms on the first start), and a drag that
        # began within its first seconds took it as one frame. It waits for
        # a pause (20 s at most; Python bakes meanwhile).
        busy = getattr(self, "view_busy", None)
        waited = getattr(self, "_preview_check_waits", 0)
        try:
            if busy is not None and busy() and waited < 66:
                self._preview_check_waits = waited + 1
                self._schedule_preview_check(300)
                return False
        except RuntimeError:
            pass
        import core._native as _native
        # The ray pass's probe too (~15 ms, 19-11), off the first hover.
        _mt_native()
        nat = _native.native
        if (nat is None or _native.qt_hypot() is None
                or not hasattr(nat, "preview_faces_bake")
                or not hasattr(nat, "preview_sweep_bake")):
            return False                 # (the engine may still load later)
        ok = False
        try:
            from core.preview_probe import probe_faces, probe_sweeps
            faces = probe_faces()
            ok = (_baked_bytes(self._bake_preview_faces_native(faces))
                  == _baked_bytes(self._bake_preview_faces_py(faces)))
            if ok:
                built, sweeps = probe_sweeps()
                ok = (_baked_bytes(self._bake_preview_sweeps_native(sweeps))
                      == _baked_bytes(self._bake_preview_faces_py(built)))
            if ok and hasattr(nat, "preview_sweep_lines"):
                ok = _sweep_lines_match(nat, sweeps)
            if ok and hasattr(nat, "textured_faces_bake"):
                ok = self._textured_seed_matches(faces)
        except Exception as exc:  # noqa: BLE001 — then Python
            import logging
            logging.getLogger(__name__).warning(
                "Native preview bake check failed: %s", exc)
            ok = False
        if not ok:
            import logging
            logging.getLogger(__name__).info(
                "Native preview bake differs here: Python bakes previews")
        Viewport._preview_native_state = ok
        return ok

    def _draw_rubber_band(self) -> None:
        self._overlay_rubber = None
        tool = self.active_tool
        if tool is None:
            return
        raw = (self._preview_lines_native(tool)
               if getattr(tool, "wireframe_depth_tested", False) else None)
        if raw is not None:
            if not raw:
                return
            segments = None
        else:
            segments = tool.rubber_band_lines()
            if not segments:
                return

        # A tool can force its preview-line colour (Push/Pull uses the normal
        # edge colour so its forming box reads like real geometry, not a loose
        # orange rubber band).
        forced = getattr(tool, "wireframe_color", None)
        snap = self.last_snap
        # Axis / reference / extension cues read as "projection lines": draw them
        # a touch thicker so the alignment is easy to spot while drawing.
        inference = (
            forced is None
            and snap is not None
            and snap.kind in ("axis", "axis_inference", "reference", "extension",
                              "through_point", "perp_face")
        )
        lock = getattr(snap, "lock_color", None) if snap is not None else None
        if forced is not None:
            color = forced
        elif lock is not None:
            # A point found ON a lock line keeps the lock's colour (#711).
            color = (lock[0], lock[1], lock[2], 1.0)
        elif snap is not None and snap.kind == "axis":
            r, g, b = snap.color
            color = (r, g, b, 1.0)
        elif snap is not None and snap.kind == "axis_inference":
            r, g, b = snap.color
            color = (r, g, b, 0.50)
        elif snap is not None and snap.kind in ("reference", "through_point", "perp_face"):
            r, g, b = snap.color
            color = (r, g, b, 1.0)
        elif snap is not None and snap.kind == "close":
            color = (0.20, 0.40, 0.78, 0.95)
        else:
            color = (0.95, 0.45, 0.16, 0.85)

        # Depth-tested previews (Push/Pull, Offset, Paste) read like real
        # geometry and need GL hidden-line removal — draw them via GL. The
        # "always on top" previews (Line/Rectangle/Move) are stashed for the
        # QPainter overlay instead, where a thick pen is reliable (Core-profile
        # glLineWidth often clamps to 1px on Mesa, so GL can't thicken them).
        if getattr(tool, "wireframe_depth_tested", False):
            if raw is None:
                raw = _segment_bytes(segments)
            self._rubber_vbo.bind()
            self._rubber_vbo.allocate(raw, len(raw))
            self._rubber_vbo.release()

            self._set_color(*color)
            self._rubber_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, len(raw) // 12)
            self._rubber_vao.release()
        else:
            self._overlay_rubber = (segments, color, 2.5 if inference else 2.0)

    def _model_linetype_edges(self) -> list:
        """``[(rgb or None, dashes, gaps)]``: the edges of the layers drawn
        with their line type in the model (core.layers.model_line_styles),
        cut into their dashes and gaps (world space, as a sheet at 1:50
        dashes them) — rebuilt when the model or the line types change."""
        import numpy as np
        from core.layers import dash_segments, model_line_styles
        scene = self.scene
        styles = model_line_styles(scene)
        if not styles:
            return []
        # The document's version, not the view's: picking something moves
        # ``scene.version`` too, and every click on a model with dashed
        # layers walked all its edges and cut them into dashes again (a
        # second per click with 24 000 of them).
        key = (id(scene), scene.content_version,
               tuple(sorted(styles.items())))
        memo = getattr(self, "_model_lines_cache", None)
        if memo is not None and memo[0] == key:
            return memo[1]
        # From the viewport's arrays with their layers, not a walk of the
        # model: every change of the model walked 85 000 faces of a plaza.
        _t, hard, _s, _n, _tt, hard_tags, _st = self.hlr_geometry(tags=True)
        by_layer: dict = {}
        for seg, tag in zip(hard, hard_tags):
            if tag in styles:
                by_layer.setdefault(tag, []).append(seg)
        from core.layers import linetype_text
        names = {ly.name: ly.linetype for ly in scene.layers}
        out = []
        for tag, segs in by_layer.items():
            rgb, pattern = styles[tag]
            dashes, gaps = dash_segments(np.asarray(segs), pattern)
            words = self._model_line_words(
                np.asarray(segs), linetype_text(names.get(tag), scene))
            out.append((rgb, dashes, gaps, words))
        self._model_lines_cache = (key, out)
        return out

    @staticmethod
    def _model_line_words(segs, spec):
        """A line type's words (GAS…) on the model's edges, in the gaps the
        pattern leaves for them, as a sheet at 1:50 places them: their
        letters' outlines as world segments, lying in the plane of the
        edge and the horizontal across it, reading upright from above (a
        rising edge: from its side)."""
        import numpy as np
        from core.layers import MODEL_DASH_SCALE, text_marks
        empty = np.zeros((0, 2, 3), dtype=np.float32)
        if spec is None or not len(segs):
            return empty
        from views.hatch_paint import line_text_strokes
        strokes = line_text_strokes(spec[0], spec[1])
        if not strokes:
            return empty
        unit = MODEL_DASH_SCALE
        up_z = np.array([0.0, 0.0, 1.0])
        out: list = []
        for a, b in np.asarray(segs, dtype=np.float64).reshape(-1, 2, 3):
            d = b - a
            total = float(np.linalg.norm(d))
            if total <= 1e-9:
                continue
            u = d / total
            if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
                u = -u                  # read left to right
                a, b = b, a
            side = np.cross(up_z, u)
            if np.linalg.norm(side) < 1e-6:
                side = np.array([0.0, 1.0, 0.0])
            side /= np.linalg.norm(side)
            marks = text_marks((0.0, 0.0), (total / unit, 0.0), spec)
            if len(marks) * len(strokes) > 4000:
                continue
            for x, _y, _deg in marks:
                centre = a + u * (x * unit)
                for poly in strokes:
                    pts = [centre + u * (px * unit) + side * (py * unit)
                           for px, py in poly]
                    out += [(p0, p1) for p0, p1 in zip(pts, pts[1:])]
        if not out:
            return empty
        return np.asarray(out, dtype=np.float32)

    def _mask_model_linetype_gaps(self) -> None:
        """Before the model's edges: the gaps of the dashed layers' edges
        laid in the depth buffer only, a hair toward the eye along each
        point's own sight line (so on the same pixels) — the edges drawn
        next fail the depth test there, and break into dashes."""
        try:
            groups = self._model_linetype_edges()
        except Exception:                    # never cost the frame
            return
        gaps = [g for _rgb, _d, g, _w in groups if len(g)]
        if not gaps:
            return
        import numpy as np
        eye = self.camera.eye()
        e = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float32)
        pts = np.concatenate(gaps).reshape(-1, 3)
        pts = pts + (e - pts) * 0.003
        self._gl.glColorMask(False, False, False, False)
        self._draw_section_arrays(pts.reshape(-1, 2, 3), (0.0, 0.0, 0.0),
                                  GL_LINES)
        self._gl.glColorMask(True, True, True, True)

    def _draw_model_linetype_dashes(self) -> None:
        """After the model's edges: the dashes of a layer whose line type
        has a colour of its own drawn again in that colour — the same
        lines, so the depth test lets them through where the edges show."""
        try:
            groups = self._model_linetype_edges()
        except Exception:
            return
        ink = tuple(self._frame_style.edge_color[:3])
        for rgb, dashes, _gaps, words in groups:
            if rgb is not None and len(dashes):
                self._draw_section_arrays(dashes, rgb, GL_LINES)
            if len(words):
                # A hair toward the eye: on a floor, over its face.
                import numpy as np
                eye = self.camera.eye()
                e = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float32)
                pts = words.reshape(-1, 3)
                pts = pts + (e - pts) * 0.002
                self._draw_section_arrays(pts.reshape(-1, 2, 3),
                                          rgb or ink, GL_LINES)

    def hlr_geometry(self, tags: bool = False):
        """World-space geometry for the hidden-line pass (core.hlr) as
        arrays, straight from the caches the viewport already keeps: the
        pick index's triangles, every placement chunk's hard edges and soft
        edges with their two face normals, plus the loose mesh's edges.
        ``collect_geometry``'s per-face Python walk took 5 s on the fountain
        (106k triangles) — and the composer paid it on every "Update view"
        and on every frame added; this is tens of milliseconds.

        Returns ``(tris (T,3,3), hard (E,2,3), soft (S,2,3), soft_n
        (S,2,3))``; ``soft_n[:, 1]`` is NaN where a soft edge bounds an
        open surface (no second face).

        ``tags``: also the layer each triangle, hard edge and soft edge is
        inked with on a sheet — its own, else its object's, as
        ``collect_geometry(layers=True)`` tags them — three more object
        arrays ``(…, tri_tags, hard_tags, soft_tags)``. Read from the pick
        index and the chunks (a lazy placement's from the document), never
        from the faces: the walk was 12.8 s of the 16 s of the plaza's
        line drawing by layer."""
        import numpy as np
        from core.layers import DEFAULT_LAYER, layer_of
        scene = self.scene
        idx = self._pick_flat(self._pick_index(near="all"))
        ttags = htags = stags = None
        if getattr(idx, "tri_v0", None) is not None and len(idx.tri_v0):
            keep = idx.ent_vis[idx.tri_ent]
            v0 = idx.tri_v0[keep]
            tris = np.stack([v0, v0 + idx.tri_e1[keep],
                             v0 + idx.tri_e2[keep]], axis=1)
            tris = tris.astype(np.float64)
            if tags:
                # One lookup per entity, not per triangle.
                ents, back = np.unique(idx.tri_ent[keep],
                                       return_inverse=True)
                ttags = Viewport._cut_layer_tags(idx, ents)[back]
        else:
            tris = np.empty((0, 3, 3))
            if tags:
                ttags = np.empty(0, dtype=object)
        hard_parts: list = []
        htag_parts: list = []
        if getattr(idx, "gedge_a", None) is not None and len(idx.gedge_a):
            gvis = np.array([scene.entity_visible(g)
                             and not getattr(g, "billboard", False)
                             for g in idx.gedge_groups], dtype=bool)
            m = (gvis[idx.gedge_gi] if len(gvis)
                 else np.zeros(len(idx.gedge_a), dtype=bool))
            hard_parts.append(np.stack([idx.gedge_a[m], idx.gedge_b[m]],
                                       axis=1).astype(np.float64))
            if tags:
                # Its object's layer, unless the edge carries one of its own.
                owners = np.array([layer_of(g) for g in idx.gedge_groups]
                                  + [DEFAULT_LAYER], dtype=object)
                t = owners[idx.gedge_gi[m]]
                own = getattr(idx, "gedge_layer", None)
                if own is not None:
                    own = own[m]
                    has = np.array([o is not None for o in own], dtype=bool)
                    t[has] = own[has]
                htag_parts.append(t)
        soft_parts: list = []
        n_parts: list = []
        stag_parts: list = []
        nan3 = (float("nan"),) * 3
        lh: list = []
        lht: list = []
        ls: list = []
        ln: list = []
        lst: list = []
        # The second face's normal aligned to the first's winding (#1218):
        # a silhouette must not move when a face is flipped.
        from core.profile_edges import edge_normal_sign
        windings = {}
        for e in scene.loose_mesh.edges:
            if getattr(e, "hidden", False) or not scene.entity_visible(e):
                continue
            p0 = (e.v0.position.x(), e.v0.position.y(), e.v0.position.z())
            p1 = (e.v1.position.x(), e.v1.position.y(), e.v1.position.z())
            if getattr(e, "soft", False):
                fs = [f for f in e.faces if scene.entity_visible(f)]
                if not fs:
                    continue
                na = fs[0].normal()
                nb = fs[1].normal() if len(fs) > 1 else None
                if nb is not None and len(fs) == len(e.faces):
                    nb *= edge_normal_sign(e, windings)
                ls.append((p0, p1))
                ln.append(((na.x(), na.y(), na.z()),
                           nan3 if nb is None else (nb.x(), nb.y(), nb.z())))
                lst.append(layer_of(e))
            else:
                lh.append((p0, p1))
                lht.append(layer_of(e))
        if lh:
            hard_parts.append(np.asarray(lh, dtype=np.float64))
            htag_parts.append(np.asarray(lht, dtype=object))
        if ls:
            soft_parts.append(np.asarray(ls, dtype=np.float64))
            n_parts.append(np.asarray(ln, dtype=np.float64))
            stag_parts.append(np.asarray(lst, dtype=object))
        for g in self._placements():
            if (getattr(g, "billboard", False)
                    or not scene.entity_visible(g)):
                continue
            ch = self._group_chunk(g)
            sp = ch.get("soft_pts")
            if sp is None or not len(sp):
                continue
            soft_parts.append(
                np.asarray(sp, dtype=np.float64).reshape(-1, 2, 3))
            n1 = np.where(np.asarray(ch["soft_single"])[:, None], np.nan,
                          np.asarray(ch["soft_n1"], dtype=np.float64))
            n_parts.append(np.stack(
                [np.asarray(ch["soft_n0"], dtype=np.float64), n1], axis=1))
            if tags:
                owner = layer_of(g)
                own = ch.get("soft_layer")
                n = len(soft_parts[-1])
                if own is not None and len(own) == n:
                    stag_parts.append(np.array(
                        [o or owner for o in own], dtype=object))
                else:
                    stag_parts.append(np.array([owner] * n, dtype=object))
        hard = (np.concatenate(hard_parts) if hard_parts
                else np.empty((0, 2, 3)))
        soft = (np.concatenate(soft_parts) if soft_parts
                else np.empty((0, 2, 3)))
        soft_n = (np.concatenate(n_parts) if n_parts
                  else np.empty((0, 2, 3)))
        if not tags:
            return tris, hard, soft, soft_n
        htags = (np.concatenate(htag_parts) if htag_parts
                 else np.empty(0, dtype=object))
        stags = (np.concatenate(stag_parts) if stag_parts
                 else np.empty(0, dtype=object))
        return tris, hard, soft, soft_n, ttags, htags, stags

    def hlr_geometry_now(self):
        """:meth:`hlr_geometry` (without tags) with the layers as they are
        switched NOW, for a sheet frame whose scene shows other layers than
        the live model. The pick index behind ``hlr_geometry`` leaves out
        the groups hidden when it was built, so a frame showing them found
        no walls (#1249); the fallback, ``collect_geometry``'s per-face
        walk, took ~20 s on Marco's Queñuamarca plaza (2026-11-12) before
        the first dimension could snap. Here each visible placement's
        cached chunk lends its arrays — a group hidden from the live view
        is baked once, the first time a frame asks for it."""
        import numpy as np
        scene = self.scene
        tris_of = getattr(self, "_tris_of", None) or \
            (lambda f: f.triangulate())
        nan3 = (float("nan"),) * 3
        tri_parts: list = []
        hard_parts: list = []
        soft_parts: list = []
        n_parts: list = []
        lt: list = []
        for f in scene.faces:
            if not scene.entity_visible(f):
                continue
            for t0, t1, t2 in tris_of(f):
                lt.append(((t0.x(), t0.y(), t0.z()), (t1.x(), t1.y(), t1.z()),
                           (t2.x(), t2.y(), t2.z())))
        if lt:
            tri_parts.append(np.asarray(lt, dtype=np.float64))
        lh: list = []
        ls: list = []
        ln: list = []
        from core.profile_edges import edge_normal_sign
        windings = {}
        for e in scene.loose_mesh.edges:
            if getattr(e, "hidden", False) or not scene.entity_visible(e):
                continue
            p0 = (e.v0.position.x(), e.v0.position.y(), e.v0.position.z())
            p1 = (e.v1.position.x(), e.v1.position.y(), e.v1.position.z())
            if getattr(e, "soft", False):
                fs = [f for f in e.faces if scene.entity_visible(f)]
                if not fs:
                    continue
                na = fs[0].normal()
                nb = fs[1].normal() if len(fs) > 1 else None
                if nb is not None:
                    nb *= edge_normal_sign(e, windings)
                ls.append((p0, p1))
                ln.append(((na.x(), na.y(), na.z()),
                           nan3 if nb is None else (nb.x(), nb.y(), nb.z())))
            else:
                lh.append((p0, p1))
        if lh:
            hard_parts.append(np.asarray(lh, dtype=np.float64))
        if ls:
            soft_parts.append(np.asarray(ls, dtype=np.float64))
            n_parts.append(np.asarray(ln, dtype=np.float64))
        # Component copies not baked yet go in one batch per prototype:
        # baking them one by one (``_instance_chunk``) cost 1.2 s for the
        # 3 400 placements of Marco's plaza on opening its sheet. Same
        # maps, term by term, so the arrays are the ones a bake makes.
        batches: dict = {}
        inst_cache = getattr(self, "_inst_chunks", None) or {}
        for g in self._placements():
            if (getattr(g, "billboard", False)
                    or not scene.entity_visible(g)):
                continue
            xf = getattr(g, "xform", None)
            if xf is not None and getattr(g, "mesh", None) is not None:
                base = self._group_chunk(
                    _proto_wrapper(self, g.mesh, _paint_of(self, g)))
                cur = inst_cache.get(id(g))
                if cur is None or cur["ikey"] != (
                        base["uid"], tuple(xf.data()), base.get("rev")):
                    batches.setdefault(id(base), (base, []))[1].append(xf)
                    continue
            ch = self._group_chunk(g)
            v0 = ch.get("v0")
            if v0 is not None and len(v0):
                v0 = np.asarray(v0, dtype=np.float64)
                tri_parts.append(np.stack(
                    [v0, v0 + np.asarray(ch["e1"], dtype=np.float64),
                     v0 + np.asarray(ch["e2"], dtype=np.float64)], axis=1))
            if ch.get("edges"):
                hard_parts.append(
                    np.frombuffer(ch["edges"], dtype=np.float32)
                    .reshape(-1, 2, 3).astype(np.float64))
            sp = ch.get("soft_pts")
            if sp is not None and len(sp):
                soft_parts.append(
                    np.asarray(sp, dtype=np.float64).reshape(-1, 2, 3))
                n1 = np.where(np.asarray(ch["soft_single"])[:, None],
                              np.nan,
                              np.asarray(ch["soft_n1"], dtype=np.float64))
                n_parts.append(np.stack(
                    [np.asarray(ch["soft_n0"], dtype=np.float64), n1],
                    axis=1))

        for base, xfs in batches.values():
            _batch_instances(base, xfs, tri_parts, hard_parts, soft_parts,
                             n_parts)

        def cat(parts, shape):
            return np.concatenate(parts) if parts else np.empty(shape)
        return (cat(tri_parts, (0, 3, 3)), cat(hard_parts, (0, 2, 3)),
                cat(soft_parts, (0, 2, 3)), cat(n_parts, (0, 2, 3)))

    def _effective_style(self):
        """The display style this frame draws with (Styles): the
        composer's ``plano_style`` override maps onto the same face modes,
        then a ``style_override``, else the scene's active style. Shared by
        the paint pass and the snap engine so what the eye sees and what
        the cursor may grab never disagree."""
        from core.style import Style
        if self.plano_style == "tecnico":
            return Style(name="tecnico", face_mode="hidden_line", sky=False,
                         background=(1.0, 1.0, 1.0))
        if self.plano_style == "lineas":
            return Style(name="lineas", face_mode="wireframe", sky=False,
                         background=(1.0, 1.0, 1.0))
        if self.style_override is not None:
            return self.style_override
        return self._view_style() or Style()

    def _view_style(self):
        """The style this view shows outside the composer: its own when it
        has one (one of several views, restyled there), else the scene's."""
        return (getattr(self, "view_style", None)
                or getattr(self.scene, "display_style", None))
