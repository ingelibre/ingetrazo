# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Face-me components and billboards: orientation, meshes, drawing and outlines."""
from __future__ import annotations

import math
from array import array
from PySide6.QtGui import QVector3D, QVector4D
from core.group import Group
from views.viewport._support import GL_LINES, GL_TRIANGLES, _cache_ver


class BillboardMixin:
    """Face-me components and billboards: orientation, meshes, drawing and outlines."""

    def _faceme_dir(self, anchor: QVector3D) -> QVector3D:
        """Direction a face-me sprite at ``anchor`` turns toward (not yet
        flattened or normalised). Perspective: toward the eye, so figures
        left and right of centre turn slightly. Parallel: the
        VIEW direction for every sprite — a parallel camera has no real eye,
        and using the fictitious one made a figure far from the orbit target
        turn 45° away when zoomed in (Marco: "Sumari no se ve bien en vista
        frontal", 2026-09-02)."""
        cam = self.camera
        if cam.perspective:
            return cam.eye() - anchor
        return cam.eye() - cam.target

    def _billboard_mesh(self, group):
        """A billboard's mesh in WORLD space. A face-me placed INSIDE a
        component — the torito on the arch, brought in with the arch —
        keeps its prototype in the component's frame and reaches the draw
        list as a proxy with a matrix; reading the raw mesh put the bull at
        the file's origin, not on the cornice (Marco, 2026-09-11). Sprites
        are a face or two, so the placed copy is cached per matrix."""
        xf = getattr(group, "xform", None)
        if xf is None:
            return group.mesh
        cache = getattr(self, "_billboard_world", None)
        if cache is None:
            cache = self._billboard_world = {}
        key = (id(group.mesh), tuple(xf.data()), _cache_ver(self))
        hit = cache.get(id(group))
        if hit is not None and hit[0] == key:
            return hit[1]
        from core.group import transformed_mesh
        placed = transformed_mesh(group.mesh, xf)
        if len(cache) > 256:
            cache.clear()
        cache[id(group)] = (key, placed)
        return placed

    def _billboard_quad(self, group, face_dir=None):
        """The face-me quad of a billboard group, rotated around its vertical
        anchor axis to face the camera NOW (or ``face_dir`` when given).
        Returns (corners[4], tex_path) or ``None``. Shared by the render
        pass, picking and the shadow casters."""
        verts = self._billboard_mesh(group).vertices
        if not verts:
            return None
        xs = [v.position.x() for v in verts]
        ys = [v.position.y() for v in verts]
        zs = [v.position.z() for v in verts]
        anchor = QVector3D((min(xs) + max(xs)) / 2,
                           (min(ys) + max(ys)) / 2, min(zs))
        # A billboard being Move/Rotate-dragged previews through THIS pass
        # (its raw mesh quad in the scratch VBOs showed the texture swimming
        # and ignored the face-me turn): carry the preview transform on the
        # anchor so the figure follows the cursor, camera-facing, fixed UVs.
        if id(group) in (getattr(self, "_preview_groups", None) or ()):
            m = getattr(self, "_preview_matrix", None)
            if m is not None:
                anchor = m.map(anchor)
            else:
                off = getattr(self, "_preview_offset", None)
                if off is not None:
                    anchor = anchor + off
        # Planar width: hypot handles a sprite plane at any yaw (an imported
        # face-me sits wherever its baked transform left it); an axis-aligned
        # quad gives the same value as before.
        w = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        h = max(zs) - min(zs)
        tex = None
        for f in group.mesh.faces:
            t = f.attrs.get("texture")
            if t and t.get("path"):
                tex = t["path"]
                break
        # tex may stay None for a vector-art face-me (solid-colour faces,
        # e.g. a 2D person from a .skp file): picking/outline/snap still need the
        # quad; the legacy textured-quad render skips texture-less groups.
        if w < 1e-9 or h < 1e-9:
            return None
        # Facing: the camera by default; the shadow pass passes the SUN so a
        # figure's cast silhouette holds still while the camera orbits
        # (face-me "shadows face sun").
        d = face_dir if face_dir is not None else self._faceme_dir(anchor)
        d = QVector3D(d.x(), d.y(), 0.0)
        if d.length() < 1e-6:
            d = QVector3D(1.0, 0.0, 0.0)
        d = d.normalized()
        r = QVector3D(-d.y(), d.x(), 0.0)
        up = QVector3D(0.0, 0.0, 1.0)
        c0 = anchor - r * (w / 2)
        c1 = anchor + r * (w / 2)
        return ([c0, c1, c1 + up * h, c0 + up * h], tex)

    def _draw_billboards(self) -> None:
        """Per-frame pass: each face-me billboard is a textured cutout quad
        turned toward the camera (2D people). Depth-tested, so it
        hides behind walls correctly; the shader discards transparent texels."""
        # The face-me figures are a handful among thousands of placements:
        # found once per change of the placements, not on every frame.
        bkey = self._placements_epoch()
        bmemo = getattr(self, "_billboard_groups", None)
        if bmemo is not None and bmemo[0] == bkey:
            groups = bmemo[1]
        else:
            groups = [g for g in self._placements()
                      if getattr(g, "billboard", False)
                      and self.scene.entity_visible(g)]
            self._billboard_groups = (bkey, groups)
        if not groups:
            return
        self._program.setUniformValue(self._loc_use_tex, 1)
        # Hard alpha cut for face-me figures: their mipmapped edge alpha
        # under the Bayer dither would stipple dots around the silhouette
        # (user report); scene cutouts keep the dither (distant fences).
        self._program.setUniformValue(self._loc_hard_cutout, 1)
        self._billboard_vao.bind()
        for g in groups:
            if getattr(g, "billboard", False) == "mesh":
                # Imported face-me silhouette: its REAL geometry (a cut
                # outline, not a rectangle) turns toward the camera.
                self._draw_faceme_mesh(g)
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            corners, path = quad
            tex = self._get_texture(path)
            if tex is None:
                continue
            data = array("f")
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for idx in (0, 1, 2, 0, 2, 3):
                c = corners[idx]
                u, v = uvs[idx]
                data.extend([c.x(), c.y(), c.z(), u, v])
            raw = data.tobytes()
            self._billboard_vbo.bind()
            self._billboard_vbo.allocate(raw, len(raw))
            self._billboard_vbo.release()
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
            if g in self.scene.selection:
                # Selection cue: repaint with the highlight colour untextured.
                pass
        self._billboard_vao.release()
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._program.setUniformValue(self._loc_use_tex, 0)

    def _draw_billboard_outlines(self) -> None:
        """Selection cue for face-me billboards: an orange outline around the
        quad AS DRAWN this frame (it rotates toward the camera). Tinting the
        group's static mesh painted a stray plane through the figure —
        the usual convention shows a selected 2D person as an outlined box too."""
        sel = [g for g in self.scene.selection
               if isinstance(g, Group) and getattr(g, "billboard", False)
               and self.scene.entity_visible(g)]
        if not sel:
            return
        data = array("f")
        for g in sel:
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            c = quad[0]
            for i, j in ((0, 1), (1, 2), (2, 3), (3, 0)):
                data.extend([c[i].x(), c[i].y(), c[i].z(),
                             c[j].x(), c[j].y(), c[j].z()])
        if not data:
            return
        raw = data.tobytes()
        self._bb_sel_vbo.bind()
        self._bb_sel_vbo.allocate(raw, len(raw))
        self._bb_sel_vbo.release()
        self._set_color(0.95, 0.45, 0.16, 1.0)  # selection orange
        self._bb_sel_vao.bind()
        self._gl.glDrawArrays(GL_LINES, 0, len(data) // 3)
        self._bb_sel_vao.release()

    def _faceme_base(self, g):
        """Cached base data of a mesh face-me billboard: interleaved pos+uv
        arrays per image, the vertical anchor axis and the horizontal base
        normal. Rebuilt when the scene changes (sprites are tiny)."""
        cache = getattr(self, "_faceme_cache", None)
        if cache is None:
            cache = self._faceme_cache = {}
        xf = getattr(g, "xform", None)
        key = (self.scene.version, id(self.scene.mesh),
               None if xf is None else tuple(xf.data()))
        cur = cache.get(id(g))
        if cur is not None and cur[0] == key:
            return cur[1]
        import numpy as np
        mesh = self._billboard_mesh(g)       # world space, matrix applied
        by_tex: dict = {}
        by_color: dict = {}      # rgb tuple -> interleaved pos+uv (uv unused)
        n0 = None
        best_area = 0.0
        for f in mesh.faces:
            area = f.area() if hasattr(f, "area") else 0.0
            if n0 is None or area > best_area:
                n0 = f.normal()
                best_area = area
            tex = f.attrs.get("texture")
            if tex is not None and tex.get("path"):
                self._append_textured_face(by_tex, f, tex)
                continue
            # Solid-colour face (a vector-art person from a .skp file):
            # same interleaved layout, uv ignored, drawn with u_color.
            col = tuple(f.attrs.get("color") or (0.96, 0.95, 0.925))
            buf = by_color.setdefault(col, array("f"))
            for t0, t1, t2 in self._tris_of(f):
                for p in (t0, t1, t2):
                    buf.extend([p.x(), p.y(), p.z(), 0.0, 0.0])
        verts = mesh.vertices
        entry = None
        if n0 is not None and verts and (by_tex or by_color):
            xs = [v.position.x() for v in verts]
            ys = [v.position.y() for v in verts]
            zs = [v.position.z() for v in verts]
            # The anchor is the figure's FEET (x, y, min z), like the simple
            # quad's: _draw_faceme_mesh aims the face-me from it in 3D. A 2-D
            # anchor here raised IndexError inside paintGL and left the whole
            # viewport blank for any model carrying a mesh face-me (Susan in
            # plaza Yanque(2).skp — v0.3.9 shipped with it).
            anchor = np.array([(min(xs) + max(xs)) / 2,
                               (min(ys) + max(ys)) / 2, min(zs)])
            nh = np.array([n0.x(), n0.y()])
            ln = float(np.hypot(nh[0], nh[1]))
            if ln > 1e-9:
                nh = nh / ln
                arrays = {p: np.frombuffer(buf.tobytes(),
                                           dtype=np.float32).reshape(-1, 5)
                          for p, buf in by_tex.items()}
                colors = {c: np.frombuffer(buf.tobytes(),
                                           dtype=np.float32).reshape(-1, 5)
                          for c, buf in by_color.items()}
                entry = (arrays, colors, anchor, nh)
        cache[id(g)] = (key, entry)
        return entry

    def _draw_faceme_mesh(self, g) -> None:
        """Draw a mesh face-me billboard: rotate its geometry around the
        vertical axis through its anchor so its plane faces the camera NOW.
        Runs inside the billboard pass (textured, billboard VAO bound)."""
        base = self._faceme_base(g)
        if base is None:
            return
        arrays, colors, anchor, nh = base
        import numpy as np
        if len(anchor) < 3:                      # an older cached entry
            anchor = np.array([anchor[0], anchor[1], 0.0])
        # Preview transform (Move/Rotate drag): the figure follows the
        # cursor through THIS pass, camera-facing with its baked UVs —
        # see _billboard_quad for the simple-quad twin.
        ox = oy = oz = 0.0
        if id(g) in (getattr(self, "_preview_groups", None) or ()):
            m = getattr(self, "_preview_matrix", None)
            if m is not None:
                p = m.map(QVector3D(anchor[0], anchor[1], anchor[2]))
                ox, oy, oz = (p.x() - anchor[0], p.y() - anchor[1],
                              p.z() - anchor[2])
            else:
                off = getattr(self, "_preview_offset", None)
                if off is not None:
                    ox, oy, oz = off.x(), off.y(), off.z()
        fd = self._faceme_dir(QVector3D(anchor[0] + ox, anchor[1] + oy,
                                        anchor[2] + oz))
        d = np.array([fd.x(), fd.y()])
        ln = float(np.hypot(d[0], d[1]))
        d = nh if ln < 1e-9 else d / ln
        cos = float(nh[0] * d[0] + nh[1] * d[1])
        sin = float(nh[0] * d[1] - nh[1] * d[0])

        def _rotated(arr):
            a = arr.copy()
            x = a[:, 0] - anchor[0]
            y = a[:, 1] - anchor[1]
            a[:, 0] = anchor[0] + cos * x - sin * y + ox
            a[:, 1] = anchor[1] + sin * x + cos * y + oy
            if oz:
                a[:, 2] += oz
            return a

        for (path, _shade), arr in arrays.items():
            # billboards turn toward the camera: no fixed-normal shade
            tex = self._get_texture(path)
            if tex is None:
                continue
            a = _rotated(arr)
            raw = a.tobytes()
            self._billboard_vbo.bind()
            self._billboard_vbo.allocate(raw, len(raw))
            self._billboard_vbo.release()
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, len(a))
        if colors:
            # Solid-colour runs (vector-art face-me like Susan): same VAO,
            # texture sampling off, u_color per run; restore for the pass.
            self._program.setUniformValue(self._loc_use_tex, 0)
            for col, arr in colors.items():
                r, gc, b = col[0], col[1], col[2]
                self._program.setUniformValue(
                    self._loc_color, QVector4D(r, gc, b, 1.0))
                self._program.setUniformValue(
                    self._loc_back_color, QVector4D(r, gc, b, 1.0))
                a = _rotated(arr)
                raw = a.tobytes()
                self._billboard_vbo.bind()
                self._billboard_vbo.allocate(raw, len(raw))
                self._billboard_vbo.release()
                self._gl.glDrawArrays(GL_TRIANGLES, 0, len(a))
            self._program.setUniformValue(self._loc_use_tex, 1)
