# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sun shadows: the light frustum, the shadow map and the shadow ground."""
from __future__ import annotations

from array import array
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QMatrix4x4, QVector2D, QVector3D
from PySide6.QtOpenGL import (QOpenGLFramebufferObject,
                              QOpenGLFramebufferObjectFormat)
from core.style import sees_through_faces
from views.viewport._support import (GL_TRIANGLES, GL_COLOR_BUFFER_BIT,
                                     GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
                                     GL_CLIP_DISTANCE0, GL_BLEND, GL_LEQUAL,
                                     GL_FALSE, GL_TRUE, GL_MAX_TEXTURE_SIZE,
                                     SOFT_SHADOW_SPREAD,
                                     _build_hard_shadow_image)

#: The shadow catcher's height: a hair under the ground, so a real floor
#: at z=0 never z-fights with it.
SHADOW_GROUND_Z = -0.005

#: The Viewport class, set by views/viewport/__init__.py once it exists: a
#: method here that names ``Viewport.X`` reads (and writes) the class itself.
Viewport = None


class ShadowMixin:
    """Sun shadows: the light frustum, the shadow map and the shadow ground."""

    # ---- Sun shadows (core/sun.py) ------------------------------------------
    _SHADOW_MAP_SIZE = 2048
    #: The map an exported picture draws with (``render_image``'s
    #: ``sharp_shadows``): drawn once per picture, so its cost does not
    #: matter the way the view's does. Capped by the driver's texture size.
    _SHADOW_EXPORT_SIZE = 8192
    _shadow_size = _SHADOW_MAP_SIZE

    def _export_shadow_size(self) -> int:
        try:
            v = self._gl.glGetIntegerv(GL_MAX_TEXTURE_SIZE)
            cap = int(v[0] if hasattr(v, "__len__") else v)
        except (TypeError, ValueError, IndexError):
            cap = self._SHADOW_MAP_SIZE
        return max(self._SHADOW_MAP_SIZE, min(self._SHADOW_EXPORT_SIZE, cap))
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
        from core.sun import scene_sun_direction
        return scene_sun_direction(self.scene)

    def _set_soft_shadow_uniforms(self) -> None:
        """Soft sun shadows (#1281) for the map this frame samples: the
        level's spread, and the map's footprint in the world read off the
        light matrix — its sides across, its depth range along the sun —
        so a detail map (#958) or an export's bigger one softens the same.
        Level 0 leaves the crisp map as it was."""
        spread = SOFT_SHADOW_SPREAD.get(
            getattr(self, "_soft_shadows", 0), 0.0)
        self._program.setUniformValue1f(self._loc_shadow_soft, spread)
        if spread:
            across, along = self._shadow_footprint(self._shadow_vp)
            self._program.setUniformValue(self._loc_shadow_world,
                                          QVector2D(across, along))

    #: The shadow margins as they were tuned (depth units of the map: the
    #: caster's constant, the most its slope term adds, the receiver's
    #: constant) and the most each may be in the WORLD, metres along the
    #: sun. A model a few tens of metres deep keeps the tuned values; a map
    #: as deep as a plaza with its orthophoto (~1 300 m) turned them into
    #: 0.5 + 13 + 0.8 m, and the arch's shadow began 1.5 m from its
    #: columns, the figure's away from its feet (Marco, 16-11, sheet L-08).
    _SHADOW_BIAS_TUNED = (0.0004, 0.01, 0.0006)
    _SHADOW_BIAS_MAX_M = (0.015, 0.50, 0.02)

    @classmethod
    def _shadow_biases(cls, light_vp) -> tuple[float, float, float]:
        """``(caster constant, caster slope cap, receiver constant)`` in the
        map's depth units for ``light_vp``: the tuned values, capped at
        :attr:`_SHADOW_BIAS_MAX_M` metres of its depth range."""
        tuned = cls._SHADOW_BIAS_TUNED
        if light_vp is None:
            return tuned
        depth = cls._shadow_footprint(light_vp)[1]
        if not depth > 0.0:
            return tuned
        return tuple(min(t, m / depth)
                     for t, m in zip(tuned, cls._SHADOW_BIAS_MAX_M))

    @staticmethod
    def _shadow_footprint(light_vp) -> tuple[float, float]:
        """Metres across one side of the map and along its depth range.
        The light's view is a rigid motion, so each row of the orthographic
        projection keeps its scale: 2 / width and 2 / depth."""
        def span(row: int) -> float:
            n = light_vp.row(row).toVector3D().length()
            return 2.0 / n if n > 1e-12 else 1.0
        return span(0), span(2)

    @staticmethod
    def _light_vp(d, lo, hi, fit=None):
        """The sun's orthographic view-projection fitted around the model —
        and around the z=0 ground patch that receives. Ortho keeps the
        packed depth linear.

        ``fit`` = ``(cx, cy, half)`` in the sun's view plane narrows the map
        to that square (#958: what the settled view shows, see
        ``_settle_shadow_fit``); along the sun it still spans the whole
        model, so a caster off screen still throws its shadow in."""
        view, r = Viewport._light_view(d, lo, hi)
        proj = QMatrix4x4()
        # Eye sits 2r from center; everything lives within r of it.
        if fit is None:
            proj.ortho(-r, r, -r, r, r * 0.5, r * 3.5)
        else:
            cx, cy, half = fit
            proj.ortho(cx - half, cx + half, cy - half, cy + half,
                       r * 0.5, r * 3.5)
        return proj * view

    @staticmethod
    def _light_view(d, lo, hi):
        """The sun's view matrix round the model, and the radius ``r`` of
        the sphere the model and its ground patch fit in."""
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
        return view, r

    def _shadow_bounds(self):
        """The box the sun's map is fitted round: the model's, widened to
        the figures that cast (``_figure_shadow_box``). ``(None, None)``
        when there is nothing at all."""
        lo, hi = self.scene.bounds()
        box = self._figure_shadow_box()
        if box is None:
            return lo, hi
        flo, fhi = box
        if lo is None:
            return QVector3D(*flo), QVector3D(*fhi)
        return (QVector3D(min(lo.x(), flo[0]), min(lo.y(), flo[1]),
                          min(lo.z(), flo[2])),
                QVector3D(max(hi.x(), fhi[0]), max(hi.y(), fhi[1]),
                          max(hi.z(), fhi[2])))

    def _model_preview_epoch(self):
        """The drag preview's epoch as the model's map sees it: a preview
        that starts or ends with only face-me figures riding it leaves
        the model's buffers — so its map — as they were (the figures are
        in a map of their own), and keeps the epoch the map was keyed on.
        Dragging the engineer across the plaza redrew the whole model's map
        as the drag began and again as it ended (Marco, 22-11)."""
        ep = getattr(self, "_preview_epoch", 0)
        moving = frozenset(getattr(self, "_preview_groups", None) or ())
        seen = getattr(self, "_shadow_preview_seen", None)
        if seen is not None and seen[0] == ep:
            return seen[1]
        figures = {id(g) for g in self._faceme_figures()}
        if (seen is not None and moving <= figures
                and seen[2] <= figures):
            kept = seen[1]
        else:
            kept = ep
        self._shadow_preview_seen = (ep, kept, moving)
        return kept

    def _ensure_shadow_map(self, mvp=None):
        """Build or reuse the packed-depth shadow map. Camera-independent:
        keyed by geometry version + sun + cut + bounds, so orbit and zoom
        REUSE it — only an edit, the clock or the section rebuilds.

        Once the view has settled (``mvp`` the same as when
        ``_settle_shadow_fit`` measured what it shows), a second map of the
        same size spread over only that returns instead (#958): a plaza of
        100 m seen from a bench goes from 5 cm to millimetres per texel.
        The moment the camera moves the whole-model map is back."""
        d = self._sun_dir_now()
        self._frame_sun = d
        if d is None:
            self._shadow_vp = None
            return None
        if (getattr(self, "_export_defined_shadows", False)
                and self._export_size is not None):
            # Export-defined shadows come from the model's projected
            # polygons; the live viewport keeps its normal shadow preview.
            self._shadow_vp = None
            return None
        lo, hi = self._shadow_bounds()
        if lo is None:
            self._shadow_vp = None
            return None
        clips = getattr(self, "_clip_vecs", None) or ()
        key = (self.scene.version, id(self.scene.mesh),
               self._model_preview_epoch(),
               tuple(round(v, 4) for v in d),
               tuple((round(c.x(), 4), round(c.y(), 4), round(c.z(), 4),
                      round(c.w(), 4)) for c in clips),
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
        fine = self._fine_shadow_map(d, lo, hi, key, mvp)
        if fine is not None:
            return fine
        if self._shadow_fbo is not None and self._shadow_key == key:
            self._shadow_vp = vp
            return self._shadow_fbo
        if self._shadow_fbo is None:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            size = self._shadow_size
            self._shadow_fbo = QOpenGLFramebufferObject(size, size, fmt)
            while not self._shadow_fbo.isValid() and size > self._SHADOW_MAP_SIZE:
                size //= 2                   # a driver short of memory
                self._shadow_fbo = QOpenGLFramebufferObject(size, size, fmt)
        self._render_shadow_map(vp)
        self._shadow_key = key
        self._shadow_vp = vp
        return self._shadow_fbo

    #: How long the view must stay put before the fitted map is drawn (#958).
    SHADOW_SETTLE_MS = 200

    def _fine_shadow_map(self, d, lo, hi, key, mvp):
        """The fitted map for this frame (#958), built on first use; None
        while the view moves, in an export, or with nothing measured yet."""
        fit = getattr(self, "_shadow_fit", None)
        if (fit is None or mvp is None or self._export_size is not None
                or fit[0] != (tuple(mvp.data()), key)):
            return None
        fkey = (key, fit[1])
        vp = self._light_vp(d, lo, hi, fit[1])
        fbo = getattr(self, "_fine_shadow_fbo", None)
        if fbo is not None and getattr(self, "_fine_shadow_key", None) == fkey:
            self._shadow_vp = vp
            return fbo
        if fbo is None:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fbo = self._fine_shadow_fbo = QOpenGLFramebufferObject(
                self._SHADOW_MAP_SIZE, self._SHADOW_MAP_SIZE, fmt)
            if not fbo.isValid():
                self._fine_shadow_fbo = None
                return None
        self._render_shadow_map(vp, fbo)
        self._fine_shadow_key = fkey
        self._shadow_vp = vp
        return fbo

    def _settle_shadow_fit(self, mvp, w, h) -> None:
        """After a frame drawn with the whole-model map: once the view has
        stayed put ``SHADOW_SETTLE_MS`` (no button held), read which
        surfaces it shows from its depth and remember the square they span
        in the sun's view plane; the next frame draws the fitted map over
        it (#958). Any camera move, edit or clock change starts over."""
        if self._export_size is not None or self._frame_shadow is None:
            return
        d = getattr(self, "_frame_sun", None)
        lo, hi = self._shadow_bounds()
        if d is None or lo is None:
            return
        state = (tuple(mvp.data()), self._shadow_key)
        fit = getattr(self, "_shadow_fit", None)
        if fit is not None and fit[0] == state:
            return                                  # already fitted
        if getattr(self, "_shadow_settle_state", None) != state:
            self._shadow_settle_state = state
            self._shadow_settle_due = False
            timer = getattr(self, "_shadow_settle_timer", None)
            if timer is None:
                timer = self._shadow_settle_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._shadow_settled)
            timer.start(self.SHADOW_SETTLE_MS)
            return
        from PySide6.QtWidgets import QApplication
        if (not getattr(self, "_shadow_settle_due", False)
                or QApplication.mouseButtons() != Qt.NoButton):
            return
        self._shadow_settle_due = False
        rect = self._visible_light_square(mvp, w, h, d, lo, hi)
        self._scene_fbo.bind()
        self._gl.glViewport(0, 0, w, h)
        if rect is not None:
            self._shadow_fit = (state, rect)
            self.update()

    def _shadow_settled(self) -> None:
        self._shadow_settle_due = True
        self.update()

    def _visible_light_square(self, mvp, w, h, d, lo, hi):
        """The square, in the sun's view plane, that the surfaces this frame
        shows span — from its depth, every 8th pixel — with a margin; None
        when the sky fills the view or it would not be smaller than the
        whole-model map."""
        import numpy as np
        depth = self._read_scene_depth(w, h)
        if depth is None:
            return None
        step = 8
        z = depth[::step, ::step]
        iy, ix = np.nonzero(z < 1.0)
        if ix.size == 0:
            return None
        zz = z[iy, ix].astype(np.float64)
        nx = (ix * step + 0.5) / w * 2.0 - 1.0
        ny = (iy * step + 0.5) / h * 2.0 - 1.0
        inv, ok = mvp.inverted()
        if not ok:
            return None
        view, r = self._light_view(d, lo, hi)
        m = np.array((view * inv).data(), dtype=np.float64).reshape(4, 4).T
        clip = np.stack([nx, ny, zz * 2.0 - 1.0, np.ones_like(nx)])
        p = m @ clip
        px, py = p[0] / p[3], p[1] / p[3]
        x0, x1, y0, y1 = px.min(), px.max(), py.min(), py.max()
        # A figure's shadow on the bare ground is not in the depth (the
        # ground catcher writes none): the square must also hold the shadow
        # of every figure the view shows, or that shadow came out cut — a
        # different cut at each camera (Marco, 21-11).
        for fx, fy in self._figure_shadows_in_view(mvp, d, view):
            x0, x1 = min(x0, fx), max(x1, fx)
            y0, y1 = min(y0, fy), max(y1, fy)
        # Margin: the gaps between sampled pixels, and the PCF kernel.
        half = max(x1 - x0, y1 - y0) * 0.5 * 1.08 + 0.05
        if half >= r * 0.9:
            return None                 # the whole model: nothing to gain
        return (round(float(x0 + x1) * 0.5, 4), round(float(y0 + y1) * 0.5, 4),
                round(float(half), 4))

    def _figure_shadows_in_view(self, mvp, d, view):
        """The corners, in the sun's view plane, of the shadow of each
        casting figure that the camera ``mvp`` may see: its quad as drawn,
        facing the camera (in that plane the quad and its shadow are one
        and the same footprint, sun ``d``). A figure counts when the screen
        box of that quad and of its shadow's far end on its own ground
        overlaps the view — the figure itself may be out of it. Runs once
        per settled view."""
        from PySide6.QtGui import QVector4D
        out = []
        for g in self._faceme_figures():
            if getattr(g, "billboard", False) is not True:
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            corners = quad[0]
            pts = list(corners)
            if d[2] > 1e-6:
                z0 = corners[0].z()
                for c in corners[2:]:          # the top edge's shadow
                    t = (c.z() - z0) / d[2]
                    pts.append(QVector3D(c.x() - d[0] * t,
                                         c.y() - d[1] * t, z0))
            xs, ys, behind = [], [], False
            for q in pts:
                c = mvp.map(QVector4D(q.x(), q.y(), q.z(), 1.0))
                if c.w() <= 1e-9:
                    behind = True
                    continue
                xs.append(c.x() / c.w())
                ys.append(c.y() / c.w())
            if not xs:
                continue
            if not behind and (max(xs) < -1.0 or min(xs) > 1.0
                               or max(ys) < -1.0 or min(ys) > 1.0):
                continue
            for c in corners:
                v = view.map(c)
                out.append((v.x(), v.y()))
        return out

    def _render_shadow_map(self, light_vp, fbo=None) -> None:
        """Depth-from-the-sun pass: every caster — the consolidated face
        VBOs plus ALL instanced components (no camera culling here: an
        off-screen tree still throws its shadow into the frame) — drawn
        with the depth program into the packed-depth FBO. The active
        section cut applies, so severed geometry does not cast. The caller
        restores the scene FBO/program bindings this pass borrows."""
        fbo = self._shadow_fbo if fbo is None else fbo
        size = fbo.width()
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
        const, slope_max, _recv = self._shadow_biases(light_vp)
        prog.setUniformValue1f(self._loc_d_bias_const, const)
        prog.setUniformValue1f(self._loc_d_bias_slope_max, slope_max)
        clips = getattr(self, "_clip_vecs", None) or []
        for i, c in enumerate(clips):
            prog.setUniformValue(self._loc_d_clip_planes[i], c)
            self._gl.glEnable(GL_CLIP_DISTANCE0 + i)
        prog.setUniformValue(self._loc_d_clip_count, len(clips))
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
        # The face-me figures are not in this map: their shadow follows
        # the camera they face, and this map is kept while it orbits.
        # They have a map of their own (_ensure_figure_shadow_map).
        for i in range(len(clips)):
            self._gl.glDisable(GL_CLIP_DISTANCE0 + i)
        prog.release()
        fbo.release()
        self._gl.glEnable(GL_BLEND)

    #: Side of the figures' map: the model's map's, at most this (an
    #: export's 8 192 would hold 256 MB for a few quads).
    _FIG_SHADOW_MAX = 4096

    def _figure_caster_data(self, light_vp, size):
        """``(vertex data, [(texture, first vertex)])`` of the face-me
        figures as they cast: each quad AS DRAWN — facing the camera, turned
        round its feet — so both feet of the shadow meet both shoes at any
        orbit, the shadow stretching from the soles away from the sun
        (Marco, 21-11, against the expected behaviour frame by frame). Two
        quads a figure: the cutout, and a skirt under the feet.

        Built every frame while the camera moves: the quads come from
        ``_billboard_quad`` (the very corners drawn), the rest in numpy —
        ~0.4 ms for 20 figures (22-11)."""
        import numpy as np
        sun = getattr(self, "_frame_sun", None)
        draws = []
        if sun is None:
            return array("f"), draws
        corners = []
        feet_v = []
        for g in self._faceme_figures():
            if getattr(g, "billboard", False) is not True:
                continue           # mesh face-me figures cast no shadow
            quad = self._billboard_quad(g)
            if quad is None or not quad[1]:
                continue
            c, path = quad
            corners.append([p.toTuple() for p in c])
            feet_v.append(self._figure_feet(path)[1])
            draws.append((path, len(draws) * 12))
        if not draws:
            return array("f"), draws
        c = np.asarray(corners, dtype=np.float64)          # (n, 4, 3)
        fv = np.asarray(feet_v, dtype=np.float64)
        z0 = c[:, 0, 2].copy()
        h = np.linalg.norm(c[:, 3] - c[:, 0], axis=1)
        # The whole caster slides TOWARD THE SUN: in the map's plane nothing
        # moves (the slide is along the sun's rays), only its depth, which
        # now clears the margins the ground keeps against acne — they
        # peeled the shadow off the soles, 2 cm at 17 h on a small model
        # and more on a deep map. A figure receives no shadow, so its own
        # margins are zero (the caller sets them).
        lift = self._figure_caster_lift(light_vp, sun, size)
        c = c + (np.minimum(lift, h)[:, None, None]
                 * np.asarray(sun, dtype=np.float64)[None, None, :])
        # A skirt under the feet down to the shadow catcher, which lies a
        # hair under the ground: from the lowest opaque row of the picture
        # to that plane, painted with that row, so the shadow reaches the
        # soles on the catcher too.
        drop = np.where(np.abs(z0) < 1e-3, -SHADOW_GROUND_Z, 0.0)
        skirt = np.empty_like(c)
        skirt[:, 0] = c[:, 0]
        skirt[:, 1] = c[:, 1]
        skirt[:, 0, 2] -= drop
        skirt[:, 1, 2] -= drop
        skirt[:, 2] = c[:, 1]
        skirt[:, 3] = c[:, 0]
        skirt[:, 2, 2] += fv * h
        skirt[:, 3, 2] += fv * h
        tri = [0, 1, 2, 0, 2, 3]
        n = len(draws)
        out = np.empty((n, 12, 5), dtype=np.float32)
        out[:, :6, :3] = c[:, tri]
        out[:, 6:, :3] = skirt[:, tri]
        uv = np.array([(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)],
                      dtype=np.float32)
        out[:, :6, 3:] = uv
        out[:, 6:, 3] = uv[:, 0]
        out[:, 6:, 4] = fv[:, None]
        return array("f", out.tobytes()), draws

    def _ensure_figure_shadow_map(self):
        """The face-me figures' own shadow map for this frame, in the same
        light matrix as the model's (``_shadow_vp``, whole-model or fitted)
        — or ``None`` when no figure casts. The figures face the camera, so
        it is redrawn whenever a quad moves: an orbit, a drag, an edit. A
        handful of quads; the model's map, kept across the orbit, is never
        touched. Keyed on the very vertices it would draw: a still view
        costs building them (a few cached extents) and one comparison. The
        caller restores the scene FBO/program bindings this pass borrows."""
        light_vp = self._shadow_vp
        if light_vp is None:
            return None
        main = getattr(self, "_frame_shadow", None)
        size = min(main.width() if main is not None
                   else self._SHADOW_MAP_SIZE, self._FIG_SHADOW_MAX)
        data, draws = self._figure_caster_data(light_vp, size)
        if not draws:
            return None
        clips = getattr(self, "_clip_vecs", None) or ()
        key = (tuple(light_vp.data()), data.tobytes(),
               tuple(c.toTuple() for c in clips))
        fbo = getattr(self, "_fig_shadow_fbo", None)
        if fbo is not None and fbo.width() != size:
            fbo = self._fig_shadow_fbo = None
        if fbo is not None and getattr(self, "_fig_shadow_key", None) == key:
            return fbo
        if fbo is None:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fbo = QOpenGLFramebufferObject(size, size, fmt)
            if not fbo.isValid():
                return None
            self._fig_shadow_fbo = fbo
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
        prog.setUniformValue1f(self._loc_d_bias_const, 0.0)
        prog.setUniformValue1f(self._loc_d_bias_slope_max, 0.0)
        for i, c in enumerate(clips):
            prog.setUniformValue(self._loc_d_clip_planes[i], c)
            self._gl.glEnable(GL_CLIP_DISTANCE0 + i)
        prog.setUniformValue(self._loc_d_clip_count, len(clips))
        for i, row in enumerate(((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0),
                                 (0.0, 0.0, 1.0, 0.0),
                                 (0.0, 0.0, 0.0, 1.0))):
            self._gl.glVertexAttrib4f(3 + i, *row)
        raw = data.tobytes()
        self._shadow_bb_vbo.bind()
        self._shadow_bb_vbo.allocate(raw, len(raw))
        self._shadow_bb_vbo.release()
        prog.setUniformValue(self._loc_d_use_tex, 1)
        prog.setUniformValue(self._loc_d_tex, 0)
        self._shadow_bb_vao.bind()
        for path, start in draws:
            tex = self._get_texture(path)
            if tex is None:
                continue
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, start, 12)
            tex.release(0)
        self._shadow_bb_vao.release()
        prog.setUniformValue(self._loc_d_use_tex, 0)
        for i in range(len(clips)):
            self._gl.glDisable(GL_CLIP_DISTANCE0 + i)
        prog.release()
        fbo.release()
        self._gl.glEnable(GL_BLEND)
        self._fig_shadow_key = key
        return fbo

    @classmethod
    def _figure_caster_lift(cls, light_vp, sun, size) -> float:
        """How far, in metres along the sun, a figure's caster slides
        toward the sun so the ground under its feet is shadowed despite
        the margins a receiver keeps (basic.frag ``shadow_light``): the
        receiver's constant, plus 1.5 texels of the ground's depth slope
        (``cot(elevation)`` metres of depth per metre across the map,
        capped at 8 in map units as the shader caps it), plus one texel
        of slack. A few centimetres on a small model; under a metre on a
        plaza's whole-model map, where a texel is 20 cm anyway."""
        across, depth = cls._shadow_footprint(light_vp)
        recv = cls._shadow_biases(light_vp)[2] * depth
        elev = max(abs(sun[2]), 1e-3)
        cot = (max(1.0 - elev * elev, 0.0) ** 0.5) / elev
        slope = min(8.0 * depth, cot * across) * 1.5 / size
        return recv + slope + across / size

    def _draw_shadow_ground(self, style) -> None:
        """The on-ground shadow catcher: a world plane just under z=0 that
        draws ONLY the shadow — translucent black where the sun is blocked,
        fully transparent where it is not, so the plane itself has no
        visible colour or edges (on-ground shadows). Skipped
        over the map, terrain and photo mesh, which bring their own ground;
        depth writes OFF so below-ground geometry still draws over it and a
        real floor AT z=0 never z-fights. Not drawn either when the
        camera looks at it from below the ground (#1301): a shadow cast
        on the ground is not seen from underneath."""
        if (self._base_map_showing() or self._terrain_showing()
                or self._photo_showing()):
            return
        z = SHADOW_GROUND_Z
        if self.camera.sees_from_below(z):
            return
        lo, hi = self._shadow_bounds()
        if lo is None:
            return
        cx = (lo.x() + hi.x()) / 2.0
        cy = (lo.y() + hi.y()) / 2.0
        r = max(hi.x() - lo.x(), hi.y() - lo.y(), 20.0) * 1.5
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

    def _hard_shadow_overlay(self, width: int, height: int):
        """Draw the exact, polygonal sun-shadow contours over the view.

        The regular viewport shadows are a sampled depth map and can produce
        stair-stepped or wavering edges.  ``view_faces`` computes the same
        shadows as clipped polygons, which also makes exported pixels follow
        the model geometry instead of the shadow-map resolution.
        """
        style = self._effective_style()
        if sees_through_faces(style):        # X-ray is a flag since #1218
            return None
        signature = self._hard_shadow_signature(width, height)
        if signature is None:
            return None
        cached = getattr(self, "_hard_shadow_image_cache", None)
        if cached is not None and cached[0] == signature:
            return cached[1]
        image = _build_hard_shadow_image(self.scene, self.camera, width,
                                         height)
        self._hard_shadow_image_cache = (signature, image)
        return image

    def _hard_shadow_signature(self, width: int, height: int):
        sun = self._sun_dir_now()
        if sun is None:
            return None
        sh = getattr(self.scene, "shadows", None)
        return (
            int(width), int(height), getattr(self.scene, "version", 0),
            id(getattr(self.scene, "mesh", None)),
            tuple(float(v) for v in sun),
            tuple(float(v) for v in self.camera.view_matrix().data()),
            tuple(float(v) for v in self.camera.projection_matrix().data()),
            bool(self.camera.perspective), self._effective_style().face_mode,
            float(getattr(sh, "darkness", 0.55)),
            bool(getattr(self.scene, "show_section_cuts", True)),
            # Every cut that clips the frame (a plane, or the six faces of
            # a section box): it read the single _clip_vec of before the
            # box, gone since, so moving a cut kept the old shadow picture.
            tuple(v.toTuple() for v in (getattr(self, "_clip_vecs", None)
                                        or ())),
        )
