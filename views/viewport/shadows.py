# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sun shadows: the light frustum, the shadow map and the shadow ground."""
from __future__ import annotations

import os
from array import array
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from views.viewport._support import (GL_TRIANGLES, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
                                     GL_DEPTH_TEST, GL_CLIP_DISTANCE0, GL_BLEND, GL_LEQUAL,
                                     GL_FALSE, GL_TRUE)


class ShadowMixin:
    """Sun shadows: the light frustum, the shadow map and the shadow ground."""

    # ---- Sun shadows (core/sun.py) ------------------------------------------
    _SHADOW_MAP_SIZE = 2048
    #: The .skp translucency rule: materials under 70 % opacity cast no
    #: shadow — the sun passes through glass.
    _SHADOW_OPACITY_MIN = 0.7

    def _sun_dir_now(self):
        """Unit vector toward the sun for the scene's shadow settings —
        ``None`` when there is nothing to cast (shadows off, kill switch
        ``INGETRAZO_NO_SHADOWS``, a sheet plan style, night, or a date that
        does not exist in a hand-edited file)."""
        import os
        if os.environ.get("INGETRAZO_NO_SHADOWS"):
            return None
        if self.plano_style is not None:
            return None
        sh = getattr(self.scene, "shadows", None)
        if sh is None or not getattr(sh, "enabled", False):
            return None
        import datetime as _dt
        from core import sun
        datum = getattr(self.scene, "georef", None)
        lat = getattr(datum, "lat", None)
        lon = getattr(datum, "lon", None)
        if lat is None or lon is None:
            lat, lon = sun.DEFAULT_LAT, sun.DEFAULT_LON
        try:
            when = sh.when_utc(lon, year=_dt.date.today().year)
        except ValueError:
            return None
        d = sun.sun_direction(lat, lon, when)
        if d is None or datum is None or not getattr(datum, "north", 0.0):
            return d
        # The sun comes in grid axes (east, north); the model's frame may be
        # turned by the datum's north angle — a shadow must fall the same way
        # on the site whichever way the axes were drawn.
        x, y = datum.grid_to_local_xy(d[0], d[1])
        return (x, y, d[2])

    @staticmethod
    def _light_vp(d, lo, hi):
        """The sun's orthographic view-projection fitted around the model —
        and around the z=0 ground patch that receives. Ortho keeps the
        packed depth linear."""
        cx = (lo.x() + hi.x()) / 2.0
        cy = (lo.y() + hi.y()) / 2.0
        loz = min(lo.z(), 0.0)
        cz = (loz + hi.z()) / 2.0
        # Half-diagonal of the dominant extent (≤ 0.87×max side), with
        # margin so rims never clip against the map's edge.
        r = max(hi.x() - lo.x(), hi.y() - lo.y(), hi.z() - loz, 2.0) * 0.87
        r *= 1.25
        center = QVector3D(cx, cy, cz)
        eye = center + QVector3D(d[0], d[1], d[2]) * (r * 2.0)
        up = (QVector3D(0.0, 0.0, 1.0) if abs(d[2]) < 0.95
              else QVector3D(0.0, 1.0, 0.0))
        view = QMatrix4x4()
        view.lookAt(eye, center, up)
        proj = QMatrix4x4()
        # Eye sits 2r from center; everything lives within r of it.
        proj.ortho(-r, r, -r, r, r * 0.5, r * 3.5)
        return proj * view

    def _ensure_shadow_map(self):
        """Build or reuse the packed-depth shadow map. Camera-independent:
        keyed by geometry version + sun + cut + bounds, so orbit and zoom
        REUSE it — only an edit, the clock or the section rebuilds."""
        d = self._sun_dir_now()
        self._frame_sun = d
        if d is None:
            self._shadow_vp = None
            return None
        lo, hi = self.scene.bounds()
        if lo is None:
            self._shadow_vp = None
            return None
        clip = getattr(self, "_clip_vec", None)
        key = (self.scene.version, id(self.scene.mesh),
               getattr(self, "_preview_epoch", 0),
               tuple(round(v, 4) for v in d),
               None if clip is None else (round(clip.x(), 4),
                                          round(clip.y(), 4),
                                          round(clip.z(), 4),
                                          round(clip.w(), 4)),
               round(lo.x(), 2), round(lo.y(), 2), round(lo.z(), 2),
               round(hi.x(), 2), round(hi.y(), 2), round(hi.z(), 2))
        # The light matrix is a pure function of the sun and the bounds —
        # all of them in the key — so deriving it every frame costs two
        # matrix builds and keeps it in step with the map. It must NOT hang
        # off the cache-hit branch: a pass with the sun OFF in between
        # clears it while leaving the map and its key intact (a sheet
        # exports plans without shadows beside a 3D with them, and the live
        # viewport does the same on any Shadows off→on with no edit between)
        # — the next hit then pushed None into the uniform and the render
        # died with «setUniformValue(15, None)». Marco, 2026-09-17,
        # exporting the sheets of Plaza Yanque to PDF.
        vp = self._light_vp(d, lo, hi)
        if self._shadow_fbo is not None and self._shadow_key == key:
            self._shadow_vp = vp
            return self._shadow_fbo
        if self._shadow_fbo is None:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            self._shadow_fbo = QOpenGLFramebufferObject(
                self._SHADOW_MAP_SIZE, self._SHADOW_MAP_SIZE, fmt)
        self._render_shadow_map(vp)
        self._shadow_key = key
        self._shadow_vp = vp
        return self._shadow_fbo

    def _render_shadow_map(self, light_vp) -> None:
        """Depth-from-the-sun pass: every caster — the consolidated face
        VBOs plus ALL instanced components (no camera culling here: an
        off-screen tree still throws its shadow into the frame) — drawn
        with the depth program into the packed-depth FBO. The active
        section cut applies, so severed geometry does not cast. The caller
        restores the scene FBO/program bindings this pass borrows."""
        size = self._SHADOW_MAP_SIZE
        fbo = self._shadow_fbo
        fbo.bind()
        self._gl.glViewport(0, 0, size, size)
        self._gl.glClearColor(1.0, 1.0, 1.0, 1.0)
        self._gl.glClearDepthf(1.0)
        self._gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glDepthMask(GL_TRUE)
        self._gl.glDisable(GL_BLEND)
        prog = self._depth_program
        prog.bind()
        prog.setUniformValue(self._loc_d_mvp, light_vp)
        prog.setUniformValue(self._loc_d_use_tex, 0)
        clip = getattr(self, "_clip_vec", None)
        if clip is not None:
            prog.setUniformValue(self._loc_d_clip_plane, clip)
            prog.setUniformValue(self._loc_d_clip_enable, 1)
            self._gl.glEnable(GL_CLIP_DISTANCE0)
        else:
            prog.setUniformValue(self._loc_d_clip_enable, 0)
        # Identity on the instanced-matrix generic attributes for the
        # non-instanced draws (same reset the main pass does per frame).
        for i, row in enumerate(((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0),
                                 (0.0, 0.0, 1.0, 0.0),
                                 (0.0, 0.0, 0.0, 1.0))):
            self._gl.glVertexAttrib4f(3 + i, *row)
        if self._faces_count > 0 or self._tcol_runs:
            self._faces_vao.bind()
            if self._faces_count > 0:
                self._gl.glDrawArrays(GL_TRIANGLES, 0, self._faces_count)
            # The .skp translucency rule: under 70 % opacity a material
            # casts NO shadow (glass lets the sun through); at or above it,
            # it casts like a solid.
            for a, _fc, start, count in self._tcol_runs:
                if a >= self._SHADOW_OPACITY_MIN:
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
            self._faces_vao.release()
        if self._tex_runs or self._ttex_runs:
            # Textured faces cast with their ALPHA CUTOUT: a chain-link
            # fence throws its weave, a leaf card its silhouette (texture
            # unavailable = solid fallback). Translucent runs follow the
            # 70 % rule above.
            self._tex_faces_vao.bind()
            prog.setUniformValue(self._loc_d_tex, 0)

            def _cast_run(path, start, count):
                tex = self._get_texture(path)
                if tex is not None:
                    prog.setUniformValue(self._loc_d_use_tex, 1)
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                else:
                    prog.setUniformValue(self._loc_d_use_tex, 0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)

            for (path, _shade), start, count in self._tex_runs:
                _cast_run(path, start, count)
            for (path, _shade), a, _fc, start, count in self._ttex_runs:
                if a >= self._SHADOW_OPACITY_MIN:
                    _cast_run(path, start, count)
            prog.setUniformValue(self._loc_d_use_tex, 0)
            self._tex_faces_vao.release()
        saved = getattr(self, "_frame_planes", None)
        self._frame_planes = None      # gather WITHOUT camera culling
        try:
            by_proto = self._gather_instanced()
        finally:
            self._frame_planes = saved
        extra = self.context().extraFunctions()
        for mesh, paint, groups, mirrored in by_proto.values():
            entry = self._proto_view(self._ensure_proto_draw(mesh, paint),
                                     mirrored)
            n = self._update_inst_matrices(entry, groups)
            prog.bind()                # entry building binds the main program
            if entry["vcol_count"]:
                entry["vcol_vao"].bind()
                extra.glDrawArraysInstanced(
                    GL_TRIANGLES, 0, entry["vcol_count"], n)
                entry["vcol_vao"].release()
            if entry["tex_runs"]:
                # Alpha-cutout casting for instances too — the hedge's
                # leaves dapple instead of throwing solid slabs.
                entry["tex_vao"].bind()
                prog.setUniformValue(self._loc_d_tex, 0)
                for (path, _shade), s0, cnt in entry["tex_runs"]:
                    tex = self._get_texture(path)
                    if tex is not None:
                        prog.setUniformValue(self._loc_d_use_tex, 1)
                        tex.bind(0)
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                        tex.release(0)
                    else:
                        prog.setUniformValue(self._loc_d_use_tex, 0)
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                prog.setUniformValue(self._loc_d_use_tex, 0)
                entry["tex_vao"].release()
        # Billboard people cast their SILHOUETTE, as a quad turned toward
        # the sun — a camera-facing caster would swing its shadow while the
        # camera orbits (face-me "shadows face sun"). Vector-art
        # and mesh face-me stay non-casting (documented deferral).
        sun = getattr(self, "_frame_sun", None)
        bbs = [g for g in self._placements()
               if getattr(g, "billboard", False) is True
               and self.scene.entity_visible(g)]
        if sun is not None and bbs:
            face = QVector3D(sun[0], sun[1], 0.0)
            data = array("f")
            draws = []
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for g in bbs:
                quad = self._billboard_quad(g, face_dir=face)
                if quad is None or not quad[1]:
                    continue
                corners, path = quad
                start = len(data) // 5
                for idx in (0, 1, 2, 0, 2, 3):
                    c = corners[idx]
                    u, v = uvs[idx]
                    data.extend([c.x(), c.y(), c.z(), u, v])
                draws.append((path, start))
            if draws:
                raw = data.tobytes()
                self._shadow_bb_vbo.bind()
                self._shadow_bb_vbo.allocate(raw, len(raw))
                self._shadow_bb_vbo.release()
                prog.bind()
                prog.setUniformValue(self._loc_d_use_tex, 1)
                prog.setUniformValue(self._loc_d_tex, 0)
                self._shadow_bb_vao.bind()
                for path, start in draws:
                    tex = self._get_texture(path)
                    if tex is None:
                        continue
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, 6)
                    tex.release(0)
                self._shadow_bb_vao.release()
                prog.setUniformValue(self._loc_d_use_tex, 0)
        if clip is not None:
            self._gl.glDisable(GL_CLIP_DISTANCE0)
        prog.release()
        fbo.release()
        self._gl.glEnable(GL_BLEND)

    def _draw_shadow_ground(self, style) -> None:
        """The on-ground shadow catcher: a world plane just under z=0 that
        draws ONLY the shadow — translucent black where the sun is blocked,
        fully transparent where it is not, so the plane itself has no
        visible colour or edges (on-ground shadows). Skipped
        over the map, terrain and photo mesh, which bring their own ground;
        depth writes OFF so below-ground geometry still draws over it and a
        real floor AT z=0 never z-fights."""
        if (self._base_map_showing() or self._terrain_showing()
                or self._photo_showing()):
            return
        lo, hi = self.scene.bounds()
        if lo is None:
            return
        cx = (lo.x() + hi.x()) / 2.0
        cy = (lo.y() + hi.y()) / 2.0
        r = max(hi.x() - lo.x(), hi.y() - lo.y(), 20.0) * 1.5
        z = -0.005
        x0, x1, y0, y1 = cx - r, cx + r, cy - r, cy + r
        data = array("f", [x0, y0, z, x1, y0, z, x1, y1, z,
                           x0, y0, z, x1, y1, z, x0, y1, z])
        self._ground_vbo.bind()
        self._ground_vbo.allocate(data.tobytes(), len(data) * 4)
        self._ground_vbo.release()
        self._program.setUniformValue(self._loc_shadow_enable, 1)
        self._program.setUniformValue(self._loc_shadow_overlay, 1)
        self._gl.glDepthMask(GL_FALSE)
        self._ground_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
        self._ground_vao.release()
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_shadow_overlay, 0)
