# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section planes: clipping, the cut fill and edges, plane frames and picking."""
from __future__ import annotations

import math
from typing import Optional
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QVector3D, QVector4D
from core.triangulate import plane_axes
from views.viewport._support import (_active_cut, GL_LINES, GL_TRIANGLES, GL_CLIP_DISTANCE0,
                                     GL_POLYGON_OFFSET_FILL, _point_to_segment_distance_2d)


class SectionPlaneMixin:
    """Section planes: clipping, the cut fill and edges, plane frames and picking."""

    # ---- Section planes ------------------------------------------------------
    def _set_section_clip(self, on: bool) -> None:
        """Enable/disable the active section cut around a model-geometry pass
        (``gl_ClipDistance`` in basic.vert). No-op when no cut is active."""
        if getattr(self, "_clip_vec", None) is None:
            return
        if on:
            self._program.setUniformValue(self._loc_clip_plane, self._clip_vec)
            self._program.setUniformValue(self._loc_clip_enable, 1)
            self._gl.glEnable(GL_CLIP_DISTANCE0)
        else:
            self._program.setUniformValue(self._loc_clip_enable, 0)
            self._gl.glDisable(GL_CLIP_DISTANCE0)

    def _section_cut_active(self):
        return _active_cut(self.scene)

    def section_plane_frame(self, sp) -> list:
        """Four world corners of the plane's drawn frame: the model's bounds
        projected onto the plane, with a margin (the plane object is sized
        to the model)."""
        u, v = plane_axes(sp.normal)
        lo, hi = self.scene.bounds()
        if lo is None:
            half_u = half_v = 1.5
            cu = cv = 0.0
        else:
            corners = [QVector3D(x, y, z)
                       for x in (lo.x(), hi.x())
                       for y in (lo.y(), hi.y())
                       for z in (lo.z(), hi.z())]
            us = [QVector3D.dotProduct(c - sp.point, u) for c in corners]
            vs = [QVector3D.dotProduct(c - sp.point, v) for c in corners]
            cu, cv = (min(us) + max(us)) * 0.5, (min(vs) + max(vs)) * 0.5
            half_u = (max(us) - min(us)) * 0.56 + 0.2
            half_v = (max(vs) - min(vs)) * 0.56 + 0.2
        c = sp.point + u * cu + v * cv
        return [c - u * half_u - v * half_v, c + u * half_u - v * half_v,
                c + u * half_u + v * half_v, c - u * half_u + v * half_v]

    def _draw_section_planes(self, painter: QPainter) -> None:
        """The section plane OBJECTS (frame + corner brackets + symbol):
        orange when active, light grey when not, a solid heavier frame when
        selected. Hidden by View ▸ Section Planes."""
        planes = getattr(self.scene, "section_planes", None)
        if not planes or not getattr(self.scene, "show_section_planes", True):
            return
        selection = self.scene.selection
        for sp in planes:
            if getattr(sp, "hidden", False):
                continue                    # its frame is off; a cut stays
            corners = self.section_plane_frame(sp)
            px = []
            ok = True
            for i in range(4):
                seg = self._clip_segment_front(corners[i],
                                               corners[(i + 1) % 4])
                if seg is None:
                    ok = False
                    break
                a = self._world_to_pixel(seg[0])
                b = self._world_to_pixel(seg[1])
                if a is None or b is None:
                    ok = False
                    break
                px.append((a, b))
            if not ok:
                continue
            # Active or not, at a glance (@pacaeiro, #62, second round): the
            # ACTIVE plane in orange, every other one light grey — the axis
            # colours of 0.4.9 said which way a plane cut, which stops
            # meaning anything once it is rotated. Orange is also the
            # selection's colour, so a selected plane draws its frame SOLID
            # and heavier instead of dashed.
            selected = sp in selection
            if sp.active:
                col = QColor(243, 115, 41)
                width = 2.0
            else:
                col = QColor(178, 182, 188)
                width = 1.4
            if selected:
                width += 1.2
            # The frame edges are drawn dashed.
            pen = QPen(col, width, Qt.SolidLine if selected else Qt.DashLine)
            painter.setPen(pen)
            for a, b in px:
                painter.drawLine(QPointF(*a), QPointF(*b))
            # Corner brackets: short SOLID ticks into the frame.
            painter.setPen(QPen(col, width))
            for i in range(4):
                c = self._world_to_pixel(corners[i])
                n1 = self._world_to_pixel(corners[(i + 1) % 4])
                n2 = self._world_to_pixel(corners[(i + 3) % 4])
                if c is None or n1 is None or n2 is None:
                    continue
                for n_ in (n1, n2):
                    dx, dy = n_[0] - c[0], n_[1] - c[1]
                    ln = math.hypot(dx, dy) or 1.0
                    k = min(14.0, ln * 0.18) / ln
                    painter.drawLine(QPointF(c[0], c[1]),
                                     QPointF(c[0] + dx * k, c[1] + dy * k))
            # The section SYMBOL rides in a little balloon at EVERY
            # corner of the frame.
            symbol = (sp.symbol or "").strip()
            if symbol:
                painter.save()
                font = painter.font()
                font.setPointSizeF(8.5)
                font.setBold(True)
                painter.setFont(font)
                r = 9.0
                for i in range(4):
                    c = self._world_to_pixel(corners[i])
                    if c is None:
                        continue
                    centre = QPointF(c[0], c[1])
                    painter.setBrush(QColor(255, 255, 255, 220))
                    painter.setPen(QPen(col, width))
                    painter.drawEllipse(centre, r, r)
                    painter.setPen(QPen(col, 1))
                    painter.drawText(
                        QRectF(c[0] - r, c[1] - r, 2 * r, 2 * r),
                        Qt.AlignCenter, symbol[:3])
                painter.restore()

    def pick_section_plane(self, screen_x: float, screen_y: float):
        """The section plane whose frame is nearest the cursor within the
        pick threshold, or ``None`` (Select / context menu / Eraser)."""
        planes = getattr(self.scene, "section_planes", None)
        if not planes or not getattr(self.scene, "show_section_planes", True):
            return None
        best, best_d = None, self.pick_threshold_px
        for sp in planes:
            if getattr(sp, "hidden", False):
                continue
            corners = self.section_plane_frame(sp)
            for i in range(4):
                seg = self._clip_segment_front(corners[i],
                                               corners[(i + 1) % 4])
                if seg is None:
                    continue
                a = self._world_to_pixel(seg[0])
                b = self._world_to_pixel(seg[1])
                if a is None or b is None:
                    continue
                d = _point_to_segment_distance_2d((screen_x, screen_y), a, b)
                if d < best_d:
                    best_d = d
                    best = sp
        return best

    def _section_cut_segments(self):
        """World-space cut segments: the active plane ∩ every visible model
        triangle, vectorized over the pick index's (v0, e1, e2) arrays.
        Cached per (scene version, plane pose)."""
        sp = self.scene.active_section()
        if sp is None:
            return None
        n, o = sp.normal, sp.point
        key = (self.scene.version, round(n.x(), 9), round(n.y(), 9),
               round(n.z(), 9), round(o.x(), 6), round(o.y(), 6),
               round(o.z(), 6))
        cached = getattr(self, "_section_cut_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        idx = self._pick_flat(self._pick_index(near="all"))
        from core.section import cut_chords
        segs = None
        if idx.tri_v0 is not None and len(idx.tri_v0):
            segs = cut_chords(idx.tri_v0, idx.tri_e1, idx.tri_e2, n, o,
                              idx.ent_vis[idx.tri_ent])
        self._section_cut_cache = (key, segs)
        return segs

    def _section_fill_tris(self):
        """The fill's triangles for the active cut, cached with the cut
        segments they come from (same scene version, same plane pose)."""
        import numpy as np
        segs = self._section_cut_segments()
        cached = getattr(self, "_section_fill_cache", None)
        if cached is not None and (cached[0] is segs or (
                segs is not None and cached[0] is not None
                and cached[0].shape == segs.shape
                and np.array_equal(cached[0], segs))):
            # A selection click moves the scene version, not the cut.
            self._section_fill_cache = (segs, cached[1])
            return cached[1]
        # Chaining the rings costs a fraction of a second on a model with
        # thousands of cut solids — nothing once, too much per frame while
        # a plane is dragged. A cut that keeps changing shows its lines
        # live and its fill once it rests for a moment.
        import time as _t
        now = _t.monotonic()
        last = getattr(self, "_section_fill_changed", 0.0)
        self._section_fill_changed = now
        if cached is not None and now - last < 0.15:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(200, self.update)
            return None
        from core.section import fill_triangles
        tris = fill_triangles(segs, self.scene.active_section().normal)
        self._section_fill_cache = (segs, tris)
        self._section_hatch_cache = {}
        return tris

    def _section_hatch(self, spacing: float, cross: bool):
        """The hatch lines of the cut whose fill is cached, per (spacing,
        cross) — computed once, while the cut stays the same."""
        cached = getattr(self, "_section_fill_cache", None)
        if cached is None:
            return None
        memo = getattr(self, "_section_hatch_cache", None)
        if memo is None:
            memo = self._section_hatch_cache = {}
        key = (round(spacing, 9), bool(cross))
        if key not in memo:
            from core.section import hatch_segments
            memo[key] = hatch_segments(
                cached[0], self.scene.active_section().normal, spacing,
                cross)
        return memo[key]

    def _draw_section_fill(self, mode, style) -> None:
        """Section Fill: paint what the active cut slices out of solids —
        and only that. The outlines come from the cut itself: the chords the
        plane takes out of the visible triangles, chained into closed rings
        with their holes (core.section.fill_triangles), the same rule the
        sheet composer's poché follows. An open surface gives no closed
        ring and stays unfilled.

        It used to be a per-pixel trick — fill the plane wherever a BACK
        face was the visible surface — which also painted faces seen from
        behind that the plane does not cut at all (a lone face, a flipped
        one, a 2D cutout): the fill showed where there was no section.
        Lives in the style (style.section_fill)."""
        if getattr(self, "_clip_vec", None) is None:
            return
        if mode in ("wireframe", "xray"):
            return
        sp = self.scene.active_section()
        if sp is None:
            return
        # The plane's own fill over the style's (the style's switch is the
        # master): solid, hatched, cross-hatched or none, in its colour.
        from core.section import effective_fill
        pattern, fc, spacing = effective_fill(sp, style)
        if pattern == "none":
            return
        tris = self._section_fill_tris()
        if tris is None or not len(tris):
            return
        # The fill lies IN the plane, which clips: unclipped while it
        # draws, nudged a hair behind so the thick cut lines drawn later
        # win the depth test.
        self._set_section_clip(False)
        raw = tris.reshape(-1).astype("float32").tobytes()
        self._section_vbo.bind()
        self._section_vbo.allocate(raw, len(raw))
        self._section_vbo.release()
        # A hatched cut sits on a pale ground of its own colour, so the
        # inside of the solid never shows between the lines.
        base = (fc if pattern == "solid"
                else tuple(c + (1.0 - c) * 0.78 for c in fc[:3]))
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(2.0, 2.0)
        self._set_color(base[0], base[1], base[2], 1.0)
        self._program.setUniformValue(
            self._loc_back_color, QVector4D(base[0], base[1], base[2], 1.0))
        self._section_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, len(tris) * 3)
        self._section_vao.release()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        if pattern in ("hatch", "cross"):
            lines = self._section_hatch(spacing, pattern == "cross")
            if lines is not None and len(lines):
                raw = lines.reshape(-1).astype("float32").tobytes()
                self._section_vbo.bind()
                self._section_vbo.allocate(raw, len(raw))
                self._section_vbo.release()
                self._set_color(fc[0], fc[1], fc[2], 1.0)
                self._program.setUniformValue(
                    self._loc_back_color,
                    QVector4D(fc[0], fc[1], fc[2], 1.0))
                self._section_vao.bind()
                self._gl.glDrawArrays(GL_LINES, 0, len(lines) * 2)
                self._section_vao.release()
        self._set_section_clip(True)

    def _draw_section_cut_edges(self) -> None:
        """Thick section-cut lines: quads in the cut plane, sized
        ~2.5 px, nudged toward the CLIPPED side so they never z-fight the
        remaining geometry. Skipped when cuts are hidden."""
        if getattr(self, "_clip_vec", None) is None:
            return
        segs = self._section_cut_segments()
        if segs is None or not len(segs):
            return
        import numpy as np
        sp = self.scene.active_section()
        n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()],
                     dtype=np.float64)
        a = segs[:, 0].astype(np.float64)
        b = segs[:, 1].astype(np.float64)
        t = b - a
        ln = np.linalg.norm(t, axis=1)
        keep = ln > 1e-9
        if not keep.any():
            return
        a, b, t, ln = a[keep], b[keep], t[keep], ln[keep]
        t /= ln[:, None]
        side = np.cross(np.broadcast_to(n, t.shape), t)
        # ~2.5 px of world width at each segment's distance from the eye.
        eye = self.camera.eye()
        eyev = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float64)
        mid = (a + b) * 0.5
        dist = np.linalg.norm(mid - eyev, axis=1)
        h = max(1.0, self.height())
        fov = math.radians(getattr(self.camera, "fov_deg", 45.0))
        wpp = np.maximum(dist * math.tan(fov * 0.5) * 2.0 / h, 1e-6)
        w = (wpp * 1.25)[:, None]
        lift = n * 0.6
        off = side * w
        q0 = a - off + lift * w
        q1 = b - off + lift * w
        q2 = b + off + lift * w
        q3 = a + off + lift * w
        tris = np.empty((len(a) * 2, 9), dtype=np.float32)
        tris[0::2, 0:3] = q0
        tris[0::2, 3:6] = q1
        tris[0::2, 6:9] = q2
        tris[1::2, 0:3] = q0
        tris[1::2, 3:6] = q2
        tris[1::2, 6:9] = q3
        raw = tris.tobytes()
        self._section_vbo.bind()
        self._section_vbo.allocate(raw, len(raw))
        self._section_vbo.release()
        ec = self._frame_style.edge_color
        self._set_color(ec[0], ec[1], ec[2], 1.0)
        self._section_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, len(a) * 6)
        self._section_vao.release()

    def _clip_segment_front(
        self, a: QVector3D, b: QVector3D
    ) -> Optional[tuple[QVector3D, QVector3D]]:
        """Clip a world segment to the part in FRONT of the camera. The long
        'infinite' guide segments (±10 km) routinely have an endpoint behind
        the eye, where ``_world_to_pixel`` returns None — which used to make
        the whole guide vanish from render, snap and pick in ordinary 3D
        views. Returns the visible sub-segment, or ``None``."""
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        wa = mvp.map(QVector4D(a.x(), a.y(), a.z(), 1.0)).w()
        wb = mvp.map(QVector4D(b.x(), b.y(), b.z(), 1.0)).w()
        eps = 1e-3
        if wa <= eps and wb <= eps:
            return None
        if wa <= eps or wb <= eps:
            t = (eps - wa) / (wb - wa)   # w is linear along the segment
            cut = a + (b - a) * t
            return (cut, QVector3D(b)) if wa <= eps else (QVector3D(a), cut)
        return (QVector3D(a), QVector3D(b))

    def _guide_snap_segment(
        self, g, margin: float = 1.5
    ) -> Optional[tuple[QVector3D, QVector3D]]:
        """The span of guide line ``g`` the snap engine works on: the part
        inside the view (widened by ``margin`` so the ends stay well off
        screen), computed in double precision from the guide's own point
        and direction.

        The ±10 km segment of ``Guide.segment()`` is fine for drawing but not
        for arithmetic: float32 rounds a coordinate of 10 000 m to ~1 mm, so
        every crossing, 'on line' point and lock-line hit computed from those
        endpoints was off by up to 2 mm — lines drawn from the X of two
        diagonal guides visibly left the guides when zoomed in (#110).
        Clipped to the view the endpoints are as large as what is on
        screen, and the error scales with it (µm at a working zoom)."""
        from core.guide import GUIDE_HALF_LEN
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        p, u = g.point, g.direction
        c0 = mvp.map(QVector4D(p.x(), p.y(), p.z(), 1.0))
        c1 = mvp.map(QVector4D(u.x(), u.y(), u.z(), 0.0))
        c0 = (c0.x(), c0.y(), c0.w())
        c1 = (c1.x(), c1.y(), c1.w())
        lo, hi = -GUIDE_HALF_LEN, GUIDE_HALF_LEN
        # Clip coordinates are affine in s along the line: keep
        # w >= eps and |x|, |y| <= margin * w (Liang–Barsky on four planes).
        planes = ((c0[2] - 1e-3, c1[2]),
                  (margin * c0[2] - c0[0], margin * c1[2] - c1[0]),
                  (margin * c0[2] + c0[0], margin * c1[2] + c1[0]),
                  (margin * c0[2] - c0[1], margin * c1[2] - c1[1]),
                  (margin * c0[2] + c0[1], margin * c1[2] + c1[1]))
        for f0, f1 in planes:           # need f0 + f1 * s >= 0
            if abs(f1) < 1e-15:
                if f0 < 0.0:
                    return None
                continue
            s = -f0 / f1
            if f1 > 0.0:
                lo = max(lo, s)
            else:
                hi = min(hi, s)
            if lo >= hi:
                return None
        px, py, pz = p.x(), p.y(), p.z()
        ux, uy, uz = u.x(), u.y(), u.z()
        return (QVector3D(px + ux * lo, py + uy * lo, pz + uz * lo),
                QVector3D(px + ux * hi, py + uy * hi, pz + uz * hi))
