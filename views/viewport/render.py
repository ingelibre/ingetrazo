# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Frame rendering: the paintGL passes, shading, previews, hidden ghosts, hover and silhouettes."""
from __future__ import annotations

import math
import time as _time_mod
from array import array
from PySide6.QtCore import QTimer
from PySide6.QtGui import QMatrix4x4, QVector2D, QVector3D, QVector4D
from core.mesh import Edge, Face
from core.style import DEFAULT_BACK_COLOR, effective_back_color
from views.viewport._support import (_PERF, _NO_BACK_TINT, _plog, GL_LINES, _shifted_mvp,
                                     GL_TRIANGLES, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
                                     GL_DEPTH_TEST, GL_BLEND, GL_SRC_ALPHA,
                                     GL_ONE_MINUS_SRC_ALPHA, GL_POLYGON_OFFSET_FILL, GL_CULL_FACE,
                                     GL_FRONT, GL_BACK, GL_LEQUAL, GL_GREATER, GL_FALSE, GL_TRUE,
                                     GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER,
                                     GL_NEAREST, GL_TEXTURE_2D, GL_TEXTURE0, GL_TEXTURE1,
                                     _cache_ver, EDIT_REST_FADE, edit_fade_color,
                                     XRAY_FACE_OPACITY, XRAY_HIDDEN_EDGE_FADE,
                                     selection_dot_color, _axes_vertices, _box_edge_vertices,
                                     _guide_vertices)


class RenderMixin:
    """Frame rendering: the paintGL passes, shading, previews, hidden ghosts, hover and silhouettes."""

    def paintGL(self) -> None:
        self._tick = getattr(self, "_tick", 0) + 1     # a new epoch memo
        self._sync_axes()
        self._sync_projection()
        if self._gl is None or self._program is None:
            return
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
        self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self._gl.glDisable(GL_CULL_FACE)

        # Effective display style (Styles): the composer's
        # plano_style override maps onto the same face modes; otherwise the
        # scene's active style drives faces, edges and background.
        style = self._effective_style()
        mode = style.face_mode
        self._frame_style = style

        # Active section cut: ONE world-space plane; the kept
        # side is where dot(n, p - origin) <= 0. Applies to model geometry
        # only — sky, axes, terrain, previews and overlays stay uncut.
        self._clip_vec = None
        sp = (self.scene.active_section()
              if getattr(self.scene, "show_section_cuts", True) else None)
        if sp is not None:
            n, o = sp.normal, sp.point
            self._clip_vec = QVector4D(
                -n.x(), -n.y(), -n.z(), QVector3D.dotProduct(n, o))

        self._gl.glClearDepthf(1.0)
        bg = style.background
        self._gl.glClearColor(bg[0], bg[1], bg[2], 1.0)
        self._gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

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
        self._program.setUniformValue1f(self._loc_shade, 1.0)
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._program.setUniformValue1f(self._loc_fade, 0.0)

        # Sky / ground backdrop with a horizon anchored to the camera pitch —
        # premium modeller feel. Fixed on zoom (it's the point at infinity),
        # moves only on orbit. Skipped over the base map / terrain (which supply
        # their own ground).
        if (self.plano_style is None and style.sky
                and not self._base_map_showing()
                and not self._terrain_showing()
                and not self._photo_showing()):
            self._draw_sky(mvp)
            self._program.setUniformValue(self._loc_mvp, mvp)

        # Base-map tiles (Track G) — the ground image, drawn before the grid so
        # the grid lines read on top of the imagery. Depth-write OFF: it's a
        # backdrop, geometry always draws over it.
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
        self._frame_shadow = (self._ensure_shadow_map()
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
            self._program.setUniformValue1f(self._loc_shadow_bias, 0.0006)
            sun = getattr(self, "_frame_sun", None) or (0.0, 0.0, 1.0)
            self._program.setUniformValue(
                self._loc_sun_dir, QVector3D(sun[0], sun[1], sun[2]))
        self._program.setUniformValue(self._loc_shadow_enable, 0)
        self._program.setUniformValue(self._loc_shadow_overlay, 0)
        _fmark("shadowmap")

        # Frustum culling (P1): the consolidated VBOs carry per-chunk draw
        # spans; only spans whose chunk AABB touches the frustum are
        # submitted. Conservative — a missing bbox always draws.
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
        if self.scene.edit_group is not None:
            # One colour for every faded pass (loose, grouped, instanced).
            self._program.setUniformValue(
                self._loc_fade_color, QVector3D(*edit_fade_color(
                    style.background)))
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
            self._draw_shadow_ground(style)
            self._program.setUniformValue(self._loc_shadow_enable, 1)
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
            if mode == "xray":
                # X-ray: translucent faces that do not occlude — edges stay
                # fully visible because nothing writes depth.
                self._program.setUniformValue1f(self._loc_opacity,
                                                XRAY_FACE_OPACITY)
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
                                                EDIT_REST_FADE)
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
            if mode == "xray":
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_TRUE)
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
                for fade, spans in ((EDIT_REST_FADE, vis), (0.0, subj)) \
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
            if mode == "xray":
                self._program.setUniformValue1f(self._loc_opacity,
                                                XRAY_FACE_OPACITY)
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
                self._program.setUniformValue(
                    self._loc_hard_cutout,
                    1 if getattr(tex, "_cutout", False) else 0)
                tex.bind(0)
                for fade, spans in ((EDIT_REST_FADE, vis), (0.0, subj)) \
                        if fading else ((0.0, vis),):
                    if not spans:
                        continue
                    self._program.setUniformValue1f(self._loc_fade, fade)
                    for _vs, _vc in spans:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
                tex.release(0)
            self._program.setUniformValue1f(self._loc_fade, 0.0)
            self._program.setUniformValue(self._loc_hard_cutout, 0)
            self._tex_faces_vao.release()
            if mode == "xray":
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_TRUE)
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
                and not _NO_BACK_TINT):
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
            self._dback_vao.bind()
            if split_db is None:
                for _vs, _vc in db_draw:
                    self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            else:
                self._program.setUniformValue1f(self._loc_fade,
                                                EDIT_REST_FADE)
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
        self._draw_instanced_faces(mode, style)
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
                    self._program.setUniformValue(
                        self._loc_hard_cutout,
                        1 if getattr(tex, "_cutout", False) else 0)
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                self._program.setUniformValue(self._loc_hard_cutout, 0)
                self._tex_faces_vao.release()
                self._program.setUniformValue1f(self._loc_shade, 1.0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            self._gl.glDisable(GL_CULL_FACE)

        self._draw_section_fill(mode, style)

        # Translucent material runs (.skp trans with useTrans): drawn
        # after everything opaque, blended, depth-tested but not depth-
        # written, so glass/mesh screens show what's behind them.
        if (self._tcol_runs or self._ttex_runs
                or self._back_tcol_runs or self._back_ttex_runs) \
                and mode in ("textures", "shaded", "xray"):
            self._gl.glDepthMask(GL_FALSE)
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            if self._tcol_runs or self._back_tcol_runs:
                self._program.setUniformValue(self._loc_use_vcolor, 1)
                self._faces_vao.bind()
                for a, fc, start, count in self._tcol_runs:
                    self._program.setUniformValue1f(self._loc_opacity, float(a))
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
                        self._program.setUniformValue1f(self._loc_opacity, float(a))
                        self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    self._gl.glDisable(GL_CULL_FACE)
                self._faces_vao.release()
                self._program.setUniformValue(self._loc_use_vcolor, 0)
            if self._ttex_runs or self._back_ttex_runs:
                self._program.setUniformValue(self._loc_use_tex, 1)
                self._tex_faces_vao.bind()
                for (path, shade), a, fc, start, count in self._ttex_runs:
                    tex = self._get_texture(path)
                    if tex is None:
                        continue
                    self._program.setUniformValue1f(self._loc_opacity, float(a))
                    self._program.setUniformValue1f(self._loc_shade, float(shade))
                    if fc:
                        self._gl.glEnable(GL_CULL_FACE)
                        self._gl.glCullFace(GL_BACK)
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                    if fc:
                        self._gl.glDisable(GL_CULL_FACE)
                if self._back_ttex_runs:
                    self._gl.glEnable(GL_CULL_FACE)
                    self._gl.glCullFace(GL_FRONT)
                    for (path, shade), a, start, count in self._back_ttex_runs:
                        tex = self._get_texture(path)
                        if tex is None:
                            continue
                        self._program.setUniformValue1f(self._loc_opacity, float(a))
                        self._program.setUniformValue1f(self._loc_shade, float(shade))
                        tex.bind(0)
                        self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                        tex.release(0)
                    self._gl.glDisable(GL_CULL_FACE)
                self._tex_faces_vao.release()
                self._program.setUniformValue1f(self._loc_shade, 1.0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            self._program.setUniformValue1f(self._loc_opacity, 1.0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
            self._gl.glDepthMask(GL_TRUE)

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
        if (self._sel_faces_count > 0 or self._hover_entity is not None) \
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
            hovered = self._hover_entity
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
        self._draw_preview_faces()
        self._draw_groups_preview(mvp)
        self._draw_hidden_ghosts(mvp)

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
            axes_coords, self._axes_spans = _axes_vertices(spacing)
            data = axes_coords.tobytes()
            self._axes_vbo.bind()
            self._axes_vbo.allocate(data, len(data))
            self._axes_vbo.release()
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
        if (self.plano_style is None and self.style_override is None
                and getattr(self.scene, "guides", None)):
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
                         for g in self.scene.guides),
                   tuple(g in self.scene.selection
                         for g in self.scene.guides))
            cached = getattr(self, "_guides_cache", None)
            if cached is not None and cached[0] == key:
                g_spans = cached[1]
            else:
                g_coords, g_spans = _guide_vertices(
                    self.scene.guides, dist * 0.03, self.scene.selection,
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
                self._guides_vao.bind()
                self._gl.glDepthMask(GL_FALSE)
                for start, count, selected in g_spans:
                    if selected:
                        self._set_color(0.95, 0.45, 0.16, 1.0)   # selection
                    else:
                        self._set_color(0.27, 0.35, 0.47, 1.0)
                    self._gl.glDrawArrays(GL_LINES, start, count)
                self._gl.glDepthMask(GL_TRUE)
                self._guides_vao.release()

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

        self._set_section_clip(True)
        show_edges = style.edges or mode == "wireframe"
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
        xray_edges = mode == "xray" and show_edges
        if xray_edges:
            self._xray_face_depth()
            bg = style.background
            k = XRAY_HIDDEN_EDGE_FADE
            _edge_passes = ((tuple(ec[i] + (bg[i] - ec[i]) * k
                                   for i in range(3)), True),
                            (tuple(ec[:3]), False))
        else:
            _edge_passes = ((tuple(ec[:3]), False),)
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
                                                    EDIT_REST_FADE)
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
        # outline. View-dependent, so rebuilt every frame.
        if show_edges and style.profiles:
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
        _fmark("edges")

        # Selected edges (drawn on top, highlighted) — never in an export
        if self._selected_count > 0 and self._export_size is None:
            self._set_color(0.95, 0.45, 0.16, 1.0)
            self._selected_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, self._selected_count)
            self._selected_vao.release()

        # Hovered edge — light blue, on top of everything else so it reads as
        # the pick candidate even when it overlaps a selected (orange) edge.
        # A curve segment highlights its whole contour (what a click selects).
        if isinstance(self._hover_entity, Edge):
            hover_count = self._upload_hover_edge(self._hover_entity)
            self._set_color(0.30, 0.55, 0.95, 1.0)
            self._hover_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, hover_count)
            self._hover_edges_vao.release()
        self._set_section_clip(False)
        self._draw_section_cut_edges()   # ON the plane — drawn unclipped

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

        self._program.release()

        if self._export_size is not None:
            # Hi-res export: the scene stays in the FBO for render_image to
            # read back; the widget blit and its QPainter overlay don't apply.
            self._scene_fbo.release()
            return

        # The depth this frame just drew, read ONCE for the overlay's
        # annotations (dimensions, leader texts), which ask «is this point
        # hidden?» for every sample of every line — see _occluded_on_screen.
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

    def _selection_dot_colors(self, face) -> tuple:
        """``(front_dot, back_dot)``: the selection dot colour for each side
        of ``face``, each picked against the paint that side shows — its
        material colour (or the open group's paint), the two-sided back
        paint, or the style's back-face tint."""
        from core.group import effective_material
        from core.materials import effective_attrs
        attrs = effective_attrs(face.attrs,
                                effective_material(self.scene.edit_group))
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
            back = effective_back_color(
                getattr(self.scene, "display_style", None), self.scene)
        return selection_dot_color(front), selection_dot_color(back)

    def _set_back_face_color(self) -> None:
        # The style's Back color wins; else the scene's adopted tint (from
        # an imported .skp's style, so unpainted faces read like they did
        # for the author); else the default blue-grey.
        r, g, b = effective_back_color(
            getattr(self.scene, "display_style", None), self.scene)
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
        shade = self._shade_factor(normal)
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
        for g in groups:
            self._expand_placements(g, movers)
        groups = movers
        self._preview_external = external
        if not external:
            self._frozen_cache_version = self.scene.version
            self._edges_version = -1      # one resync WITHOUT the movers
        self._preview_groups = set(map(id, groups))
        self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        if not self._preview_groups:
            return
        self.makeCurrent()
        try:
            if getattr(self, "_pv_edges_vao", None) is None:
                self._pv_edges_vao, self._pv_edges_vbo = self._create_dynamic()
                self._pv_vcol_vao, self._pv_vcol_vbo = \
                    self._create_dynamic_vcol()
                self._pv_tex_vao, self._pv_tex_vbo = self._create_dynamic_uv()
            edge_parts: list = []
            vcol_parts: list = []
            tex_parts: dict = {}
            for g in groups:
                if getattr(g, "billboard", False):
                    # Face-me figures preview through their OWN pass (the
                    # anchor rides the preview transform): their raw mesh
                    # quad in the scratch VBOs showed a swimming texture.
                    continue
                ch = self._group_chunk(g)
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
        finally:
            self.doneCurrent()

    def end_groups_preview(self) -> None:
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
        if not getattr(self, "_preview_groups", None):
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
                self._program.setUniformValue(
                    self._loc_hard_cutout,
                    1 if getattr(tex, "_cutout", False) else 0)
                tex.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                tex.release(0)
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._program.setUniformValue(self._loc_hard_cutout, 0)
            self._pv_tex_vao.release()
            self._program.setUniformValue(self._loc_use_tex, 0)
        n = getattr(self, "_pv_edges_count", 0)
        if n:
            self._set_color(1.0, 0.45, 0.0, 1.0)   # selection orange: moving
            self._pv_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, n)
            self._pv_edges_vao.release()
        self._program.setUniformValue(self._loc_mvp, mvp)

    # ---- Hidden things shown (View ▸ Hidden Objects / Geometry) ------------
    def _sync_hidden_ghosts(self) -> bool:
        """Scratch VBOs of the hidden things the view shows — the hidden
        OBJECTS' chunk arrays and the hidden FACES / EDGES of the mesh being
        edited — rebuilt only when the placements or the mesh change.
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
            edata = array("f")
            for e in sc.mesh.edges:
                if getattr(e, "hidden", False) and sc._layer_state(e)[0]:
                    edata.extend([e.a.x(), e.a.y(), e.a.z(),
                                  e.b.x(), e.b.y(), e.b.z()])
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
        key = (_cache_ver(self), id(self.scene.mesh))
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
                for i, e in enumerate(softs):
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
        gkey = (self._placements_epoch(), len(pv_sil), skip_context)
        gmemo = getattr(self, "_sil_groups", None)
        if gmemo is not None and gmemo[0] == gkey and not pv_sil:
            groups = gmemo[1]
        else:
            groups = [g for g in self._placements()
                      if self.scene.entity_visible(g)
                      and id(g) not in pv_sil
                      and not getattr(g, "billboard", False)
                      and not (skip_context and self._draws_in_edit_context(g))]
            self._sil_groups = (gkey, groups)
        if groups:
            import numpy as np
            e_np = np.array([eye.x(), eye.y(), eye.z()])
            planes = getattr(self, "_frame_planes", None)
            got, groups = self._instanced_silhouettes(groups, eye, planes)
            if got:
                chunks.append(got)
            for g in groups:
                if getattr(g, "xform", None) is not None:
                    got = self._instance_silhouette(g, eye, planes)
                    if got is not None:
                        if got:
                            chunks.append(got)
                        continue
                ch = self._group_chunk(g)
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
        from core.group import effective_material
        key = (self._placements_epoch(), tuple(map(id, groups)))
        memo = getattr(self, "_sil_table", None)
        if memo is not None and memo[0] == key:
            return memo[1], memo[2]
        by_proto: dict = {}
        rest: list = []
        for g in groups:
            if getattr(g, "xform", None) is None \
                    or getattr(g, "billboard", False):
                rest.append(g)
                continue
            base = self._proto_base_chunk(g.mesh, effective_material(g))
            if base["soft_pts"] is None:
                continue                      # nothing curved to outline
            box, inv = self._placement_frame(g)
            if inv is None:
                rest.append(g)
                continue
            ent = by_proto.get(base["uid"])
            if ent is None:
                ent = by_proto[base["uid"]] = (base, [], [], [], [])
            _b, fwds, invs, los, his = ent
            fwds.append(np.array(g.xform.data(), np.float64)
                        .reshape(4, 4, order="F")[:3])
            invs.append(np.array(inv.data(), np.float64)
                        .reshape(4, 4, order="F")[:3])
            inf = float("inf")
            los.append(box[0] if box else (-inf, -inf, -inf))
            his.append(box[1] if box else (inf, inf, inf))
        table = []
        for base, fwds, invs, los, his in by_proto.values():
            n0 = np.asarray(base["soft_n0"], np.float64)
            n1 = np.asarray(base["soft_n1"], np.float64)
            table.append({
                "seg": np.asarray(base["soft_pts"], np.float64).reshape(-1, 2, 3),
                "n0": n0, "n1": n1,
                "d0": np.einsum("ij,ij->i", n0, np.asarray(base["soft_c0"], np.float64)),
                "d1": np.einsum("ij,ij->i", n1, np.asarray(base["soft_c1"], np.float64)),
                "single": np.asarray(base["soft_single"], bool),
                "fwd": np.stack(fwds), "inv": np.stack(invs),
                "lo": np.asarray(los, np.float64), "hi": np.asarray(his, np.float64),
            })
        self._sil_table = (key, table, rest)
        return table, rest

    def _instanced_silhouettes(self, groups, eye, planes):
        """Silhouette bytes of every component placement in ``groups``,
        prototype by prototype: the frustum cull and the «faces straddle
        the view» test run as one NumPy pass over all the placements of a
        prototype, with the eye in each one's local coordinates (see
        ``_instance_silhouette``, the one-placement version they must
        agree with). A per-placement Python loop cost 1.7 s a frame on a
        model of 21 406 placements (issue #158). Returns ``(bytes, rest)``
        with the placements left to the per-group path."""
        import numpy as np
        table, rest = self._silhouette_table(groups)
        if not table:
            return b"", rest
        e = np.array([eye.x(), eye.y(), eye.z()])
        pl = np.asarray(planes, np.float64) if planes is not None else None
        out = []
        for t in table:
            if pl is not None:
                n = pl[:, :3]
                pick = np.where(n[:, None, :] >= 0.0, t["hi"][None], t["lo"][None])
                keep = ((pick * n[:, None, :]).sum(axis=2)
                        + pl[:, 3][:, None] >= 0.0).all(axis=0)
                rows = np.flatnonzero(keep)
                if not len(rows):
                    continue
            else:
                rows = np.arange(len(t["fwd"]))
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
        return b"".join(out), rest

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
        from core.group import effective_material
        base = self._proto_base_chunk(g.mesh, effective_material(g))
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
            for (r, g, b), start, count in runs:
                self._set_color(r, g, b, 1.0)
                # A preview has no back: it is an overlay, not a solid with an
                # inside. Its walls are wound however the sweep produced them
                # and nothing surrounds them to hide the ones turned away, so
                # the real back-face tint painted the pocket of a push-in blue
                # over the shape being formed (Marco, 2026-08-27). Both sides
                # take the face's own colour.
                self._program.setUniformValue(self._loc_back_color,
                                              QVector4D(r, g, b, 1.0))
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
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

    def _draw_rubber_band(self) -> None:
        self._overlay_rubber = None
        tool = self.active_tool
        if tool is None:
            return
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
            data = array("f")
            for a, b in segments:
                data.extend([a.x(), a.y(), a.z(), b.x(), b.y(), b.z()])
            raw = data.tobytes()
            self._rubber_vbo.bind()
            self._rubber_vbo.allocate(raw, len(raw))
            self._rubber_vbo.release()

            self._set_color(*color)
            self._rubber_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, len(data) // 3)
            self._rubber_vao.release()
        else:
            self._overlay_rubber = (segments, color, 2.5 if inference else 2.0)

    def hlr_geometry(self):
        """World-space geometry for the hidden-line pass (core.hlr) as
        arrays, straight from the caches the viewport already keeps: the
        pick index's triangles, every placement chunk's hard edges and soft
        edges with their two face normals, plus the loose mesh's edges.
        ``collect_geometry``'s per-face Python walk took 5 s on the fountain
        (106k triangles) — and the composer paid it on every "Update view"
        and on every frame added; this is tens of milliseconds.

        Returns ``(tris (T,3,3), hard (E,2,3), soft (S,2,3), soft_n
        (S,2,3))``; ``soft_n[:, 1]`` is NaN where a soft edge bounds an
        open surface (no second face)."""
        import numpy as np
        scene = self.scene
        idx = self._pick_flat(self._pick_index(near="all"))
        if getattr(idx, "tri_v0", None) is not None and len(idx.tri_v0):
            keep = idx.ent_vis[idx.tri_ent]
            v0 = idx.tri_v0[keep]
            tris = np.stack([v0, v0 + idx.tri_e1[keep],
                             v0 + idx.tri_e2[keep]], axis=1)
            tris = tris.astype(np.float64)
        else:
            tris = np.empty((0, 3, 3))
        hard_parts: list = []
        if getattr(idx, "gedge_a", None) is not None and len(idx.gedge_a):
            gvis = np.array([scene.entity_visible(g)
                             and not getattr(g, "billboard", False)
                             for g in idx.gedge_groups], dtype=bool)
            m = (gvis[idx.gedge_gi] if len(gvis)
                 else np.zeros(len(idx.gedge_a), dtype=bool))
            hard_parts.append(np.stack([idx.gedge_a[m], idx.gedge_b[m]],
                                       axis=1).astype(np.float64))
        soft_parts: list = []
        n_parts: list = []
        nan3 = (float("nan"),) * 3
        lh: list = []
        ls: list = []
        ln: list = []
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
        hard = (np.concatenate(hard_parts) if hard_parts
                else np.empty((0, 2, 3)))
        soft = (np.concatenate(soft_parts) if soft_parts
                else np.empty((0, 2, 3)))
        soft_n = (np.concatenate(n_parts) if n_parts
                  else np.empty((0, 2, 3)))
        return tris, hard, soft, soft_n

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
        return getattr(self.scene, "display_style", None) or Style()
