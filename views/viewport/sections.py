# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section planes: clipping, the cut fill and edges, plane frames and picking."""
from __future__ import annotations

import math
from typing import Optional
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QVector3D, QVector4D)
from core.i18n import tr
from core.style import xray_enabled
from core.triangulate import plane_axes
from views.viewport._support import (_active_cut, GL_LINES, GL_TRIANGLES,
                                     GL_CLIP_DISTANCE0, GL_POLYGON_OFFSET_FILL,
                                     _MAX_CUT_PLANES,
                                     _point_to_segment_distance_2d)


class SectionPlaneMixin:
    """Section planes: clipping, the cut fill and edges, plane frames and picking."""

    # ---- Section planes ------------------------------------------------------
    def _set_section_clip(self, on: bool, skip=None) -> None:
        """Enable/disable the section cut around a model-geometry pass
        (``gl_ClipDistance`` in basic.vert). ``skip`` leaves that plane (or
        those, a tuple) out: what is drawn IN a cut plane (its fill, its
        thick lines) is clipped by the others only — a box face's fill stops
        at the box.

        Every frame ends with the clip on (``_draw_previews_after``), so the
        program can still hold the last frame's planes when this frame has
        none (#1574): the first call without a cut switches them off — count
        0, every cut clip distance disabled (``+ 7`` is the ground's, left
        alone) — and later ones are no-ops."""
        vecs = getattr(self, "_clip_vecs", None)
        if not vecs:
            if getattr(self, "_section_clip_armed", False):
                self._program.setUniformValue(self._loc_clip_count, 0)
                for i in range(_MAX_CUT_PLANES):
                    self._gl.glDisable(GL_CLIP_DISTANCE0 + i)
                self._section_clip_armed = False
            return
        skips = skip if isinstance(skip, tuple) else (skip,)
        if on:
            for i, v in enumerate(vecs):
                self._program.setUniformValue(self._loc_clip_planes[i], v)
                if i in skips:
                    self._gl.glDisable(GL_CLIP_DISTANCE0 + i)
                else:
                    self._gl.glEnable(GL_CLIP_DISTANCE0 + i)
            self._program.setUniformValue(self._loc_clip_count, len(vecs))
            self._section_clip_armed = True
        else:
            self._program.setUniformValue(self._loc_clip_count, 0)
            for i in range(len(vecs)):
                self._gl.glDisable(GL_CLIP_DISTANCE0 + i)
            self._section_clip_armed = False

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
            if getattr(sp, "hidden", False) \
                    or not self.scene.entity_visible(sp) \
                    or self._box_covers_plane(sp):
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
                col = QColor.fromRgbF(*self._modeling_color("section_active"))
                width = 2.0
            else:
                col = QColor.fromRgbF(*self._modeling_color("section_inactive"))
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

    def _section_box_edges_px(self, box) -> list:
        """The section box's twelve edges on screen, ``[(a, b), ...]`` —
        the part of each in front of the camera."""
        out = []
        c = box.corners()
        for i in range(8):
            for bit in (1, 2, 4):
                if i & bit:
                    continue
                seg = self._clip_segment_front(c[i], c[i | bit])
                if seg is None:
                    continue
                a = self._world_to_pixel(seg[0])
                b = self._world_to_pixel(seg[1])
                if a is not None and b is not None:
                    out.append((a, b))
        return out

    def _section_boxes_shown(self) -> list:
        """The section boxes on screen: the one that CUTS (unless its frame
        is switched off) and one selected, to see where it stands. A box
        that does nothing draws nothing: with none cutting, the model looks
        as if there were no boxes at all. View ▸ Section Planes hides them
        as it hides the planes' frames."""
        if not getattr(self.scene, "show_section_planes", True):
            return []
        cuts = getattr(self.scene, "show_section_cuts", True)
        selection = self.scene.selection
        return [b for b in getattr(self.scene, "section_boxes", ())
                if not getattr(b, "hidden", False)
                and ((b.active and cuts) or b in selection)]

    def _box_covers_plane(self, plane) -> bool:
        """While a section box cuts, the section planes' frames step aside:
        the view is the box's. The plane's cut stays if it has one, and one
        selected in the Browser shows, to see where it stands."""
        scene = self.scene
        if plane in scene.selection \
                or not getattr(scene, "show_section_cuts", True):
            return False
        active = getattr(scene, "active_section_box", None)
        return callable(active) and active() is not None

    def _section_box_chip(self):
        """``(rect, text)`` of the notice at the top of the view while a box
        cuts — what is cutting, and the one click back to the whole model
        — or ``None``."""
        if not getattr(self.scene, "show_section_cuts", True):
            return None
        box = self.scene.active_section_box()
        if box is None:
            return None
        text = "{}  —  {}  ✕".format(
            tr("Section box: {name}", name=box.name or tr("Section Box")),
            tr("Show the whole model"))
        from PySide6.QtGui import QPaintDevice
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        fm = (QFontMetrics(font, self) if isinstance(self, QPaintDevice)
              else QFontMetrics(font))
        w = fm.horizontalAdvance(text) + 24.0
        return QRectF((self.width() - w) * 0.5, 10.0, w, fm.height() + 10.0), \
            text

    def _press_on_box_chip(self, ev) -> bool:
        """A click on the section box's notice: back to the whole model."""
        chip = self._section_box_chip()
        if chip is None or not chip[0].contains(ev.position()):
            return False
        show_all = getattr(self.window(), "_show_whole_model", None)
        if not callable(show_all):
            return False
        show_all()
        return True

    def _draw_section_box_chip(self, painter: QPainter) -> None:
        chip = self._section_box_chip()
        if chip is None:
            return
        rect, text = chip
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(font)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(243, 115, 41, 235))
        painter.drawRoundedRect(rect, rect.height() * 0.5, rect.height() * 0.5)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def _box_with_grips(self, box) -> bool:
        """Whether ``box`` shows its grips: selected, or the one the
        Section Box tool is working on."""
        if box in self.scene.selection:
            return True
        from tools.section_box import SectionBoxTool
        return isinstance(self.active_tool, SectionBoxTool) and box.active

    def _draw_section_box(self, painter: QPainter,
                          handles: bool = True) -> None:
        """Every section box's twelve edges, dashed like a section plane's
        frame: orange for the one that cuts, light grey for the others,
        solid and heavier when selected — then the grips of the box
        selected or worked on by the Section Box tool. Hidden by View ▸
        Section Planes, as the planes' frames are."""
        from tools.section_box import SectionBoxTool, draw_arrows
        tool = self.active_tool
        for box in self._section_boxes_shown():
            selected = box in self.scene.selection
            col = (QColor(243, 115, 41) if box.active
                   else QColor(150, 155, 162))
            width = (2.0 if box.active else 1.4) + (1.2 if selected else 0.0)
            painter.save()
            painter.setPen(QPen(col, width,
                                Qt.SolidLine if selected else Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            for a, b in self._section_box_edges_px(box):
                painter.drawLine(QPointF(*a), QPointF(*b))
            painter.restore()
            if not handles or not self._box_with_grips(box):
                continue                    # an exported picture: no grips
            hot = None
            if isinstance(tool, SectionBoxTool) and box.active:
                hot = (tool.drag_face if tool.drag_face is not None
                       else tool.hover_face)
            draw_arrows(self, painter, box, hot)

    def pick_section_box(self, screen_x: float, screen_y: float):
        """The section box whose grip is under the cursor (a box showing
        its grips) or whose edge is nearest it within the pick threshold,
        else ``None`` (Select / context menu / Eraser)."""
        from tools.section_box import pick_arrow
        boxes = self._section_boxes_shown()
        for box in boxes:
            if self._box_with_grips(box) and pick_arrow(
                    self, box, screen_x, screen_y) is not None:
                return box
        best, best_d = None, self.pick_threshold_px
        for box in boxes:
            for a, b in self._section_box_edges_px(box):
                d = _point_to_segment_distance_2d((screen_x, screen_y), a, b)
                if d < best_d:
                    best, best_d = box, d
        return best

    def pick_section_plane(self, screen_x: float, screen_y: float):
        """The section plane whose frame is nearest the cursor within the
        pick threshold, or ``None`` (Select / context menu / Eraser)."""
        planes = getattr(self.scene, "section_planes", None)
        if not planes or not getattr(self.scene, "show_section_planes", True):
            return None
        best, best_d = None, self.pick_threshold_px
        for sp in planes:
            if getattr(sp, "hidden", False) \
                    or not self.scene.entity_selectable(sp) \
                    or self._box_covers_plane(sp):
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

    @staticmethod
    def _cut_ident(sp):
        """Which cut ``sp`` is, across frames and poses: a section plane by
        its uid, a section box face by its index — so a face being dragged
        keeps its one cache slot, as a dragged plane does."""
        if hasattr(sp, "box"):
            return ("box", sp.index)
        return ("plane", getattr(sp, "uid", id(sp)))

    def _section_cut_segments(self, sp=None):
        """World-space cut segments: the plane ``sp`` (the active one when
        not given) ∩ every visible model triangle, vectorized over the pick
        index's (v0, e1, e2) arrays. The whole plane: where another cut
        hides them, the clip planes take them out as they draw. Cached per
        cut, per (scene version, plane pose)."""
        if sp is None:
            sp = self.scene.active_section()
        if sp is None:
            return None
        n, o = sp.normal, sp.point
        key = (self.scene.version, round(n.x(), 9), round(n.y(), 9),
               round(n.z(), 9), round(o.x(), 6), round(o.y(), 6),
               round(o.z(), 6))
        memo = getattr(self, "_section_cut_cache", None)
        if not isinstance(memo, dict):
            memo = self._section_cut_cache = {}
        ident = self._cut_ident(sp)
        cached = memo.get(ident)
        if cached is not None and cached[0] == key:
            return cached[1]
        idx = self._pick_flat(self._pick_index(near="all"))
        from core.section import cut_chords
        segs = tags = None
        if idx.tri_v0 is not None and len(idx.tri_v0):
            # Each triangle's height along the normal is kept while the
            # model and the normal stay: a plane dragged by its arrow then
            # only compares three arrays with its new offset (a furnished
            # house froze ~2 s per drag measuring every triangle again).
            # One per cut: the six faces of a section box have three
            # normals, and one shared reach was measured again every frame.
            reaches = getattr(self, "_section_reach", None)
            if not isinstance(reaches, dict):
                reaches = self._section_reach = {}
            reach = reaches.get(ident)
            if reach is None or not reach.fits(idx.tri_v0, n, idx.tri_e1,
                                               idx.tri_e2):
                from core.section import PlaneReach, cut_planes
                # Each reach holds ~110 bytes per triangle and the pick
                # index it was made from: only the cuts cutting now keep
                # one, and none of an older model's arrays stays alive.
                live = {self._cut_ident(c) for c in cut_planes(self.scene)}
                for k in [k for k, r in reaches.items()
                          if k != ident and (k not in live
                                             or r._v0 is not idx.tri_v0)]:
                    del reaches[k]
                reach = reaches[ident] = PlaneReach(
                    idx.tri_v0, idx.tri_e1, idx.tri_e2, n)
            segs, rows = cut_chords(idx.tri_v0, idx.tri_e1, idx.tri_e2, n, o,
                                    idx.ent_vis[idx.tri_ent], rows=True,
                                    reach=reach)
            if segs is not None:
                sc = self.scene
                tags = self._cut_layer_tags(
                    idx, idx.tri_ent[rows],
                    key=sc.content_version - sc.section_version)
        memo[ident] = (key, segs, tags)
        return segs

    def _section_cut_tags(self, sp=None):
        """The layer of each of ``sp``'s cut segments (the active plane
        when not given), as :meth:`_section_cut_segments` made them — or
        ``None``."""
        if sp is None:
            sp = self.scene.active_section()
        if sp is None or self._section_cut_segments(sp) is None:
            return None
        return self._section_cut_cache[self._cut_ident(sp)][2]

    @staticmethod
    def _cut_layer_tags(idx, ents, key=None):
        """The layer each cut triangle's section is filled with, as a sheet
        tags it: the face's own layer, else the nearest container's that
        has one — a wall in a group on «S_Demolition» is filled as
        demolition, not as the plane's default fill, even when the wall
        itself carries no layer (#1503)."""
        import numpy as np
        from core.layers import DEFAULT_LAYER, inherited_layer, layer_of
        # Kept on the index: it is made again by every edit of the model
        # (a face put on a layer, a layer renamed), so its entities' layers
        # stand while it does. Dragging a plane over the plaza looked the
        # same ~1 100 entities up on every frame, ~16 ms of a frame's ~50.
        # ``key``: the model's version as the caller reads it; without one
        # nothing is kept.
        kept = getattr(idx, "_cut_tag_memo", None) if key is not None else None
        if kept is not None and kept[0] == key:
            memo = kept[1]
        else:
            memo = {}
            if key is not None:
                try:
                    idx._cut_tag_memo = (key, memo)
                except AttributeError:
                    pass
        out = []
        # A lazy placement's face is built with its whole mesh when asked
        # for: its layer is read from the document instead.
        quick = getattr(idx.entities, "layer_at", None)
        # The placement each entity belongs to, when the index carries it:
        # a nested placement's proxy already wears the nearest container's
        # layer (see _expand_placements), so it answers the lookup the
        # top-level owner alone cannot.
        places = getattr(idx, "ent_placements", None)
        place_idx = getattr(idx, "ent_place_idx", None)
        for e in ents.tolist():
            tag = memo.get(e)
            if tag is None:
                if quick is not None:
                    own, owner = quick(e)
                    tag = own or DEFAULT_LAYER
                else:
                    face, owner = idx.entities[e]
                    tag = layer_of(face)
                if tag == DEFAULT_LAYER:
                    place = None
                    if places is not None and place_idx is not None:
                        pi = int(place_idx[e])
                        if 0 <= pi < len(places):
                            place = places[pi]
                    tag = inherited_layer(
                        place if place is not None else owner)
                memo[e] = tag
            out.append(tag)
        return np.asarray(out, dtype=object)

    def _section_fill_tris(self, sp=None):
        """The fill's triangles for the cut of ``sp`` (the active plane when
        not given), cached with the cut segments they come from (same
        scene version, same plane pose)."""
        import numpy as np
        if sp is None:
            sp = self.scene.active_section()
        if sp is None:
            return None
        segs = self._section_cut_segments(sp)
        memo = getattr(self, "_section_fill_cache", None)
        if not isinstance(memo, dict):
            memo = self._section_fill_cache = {}
        ident = self._cut_ident(sp)
        cached = memo.get(ident)
        if cached is not None and (cached[0] is segs or (
                segs is not None and cached[0] is not None
                and cached[0].shape == segs.shape
                and np.array_equal(cached[0], segs))):
            # A selection click moves the scene version, not the cut.
            memo[ident] = (segs, cached[1], cached[2])
            return cached[1]
        # Chaining the rings costs a fraction of a second on a model with
        # thousands of cut solids — nothing once, too much per frame while
        # a plane is dragged. A cut that keeps changing shows its lines
        # live and its fill once it rests for a moment. «Rests» counts from
        # the last time the CUT changed, not the last frame: frames that
        # keep coming with the cut still (the shadows or the ambient
        # occlusion refining) used to hold the fill back for good, until
        # the fill was switched off and on.
        import time as _t
        now = _t.monotonic()
        changed = getattr(self, "_section_fill_changed", None)
        if not isinstance(changed, dict):
            changed = self._section_fill_changed = {}
        since, seen = changed.get(ident, (0.0, None))
        if seen is not segs:
            since = now
            changed[ident] = (now, segs)
        # A picture being exported (a sheet's frame, Export image) is drawn
        # once: it waits for nothing and gets its fill now.
        exporting = getattr(self, "_export_size", None) is not None
        if cached is not None and now - since < 0.15 and not exporting:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(200, self.update)
            return None
        from core.section import fill_triangles
        tris = fill_triangles(segs, sp.normal)
        memo[ident] = (segs, tris, {})
        return tris

    def _section_layer_fills(self, color, sp=None):
        """The cut of ``sp`` (the active plane when not given) filled layer
        by layer with the layers' hatches (core.section.layer_fills) — once
        the cut rests, as its plain fill, and again only when the cut or a
        layer's hatch changes."""
        if sp is None:
            sp = self.scene.active_section()
        if sp is None or self._section_fill_tris(sp) is None:
            return None
        segs = self._section_cut_segments(sp)
        if segs is None:
            return None
        tags = self._section_cut_tags(sp)
        scene = self.scene
        sign = (id(segs), tuple(color[:3]),
                repr([ly.to_dict() for ly in scene.layers]),
                repr(getattr(scene, "bricks", None)))
        memo = getattr(self, "_section_layer_cache", None)
        if not isinstance(memo, dict):
            memo = self._section_layer_cache = {}
        ident = self._cut_ident(sp)
        kept = memo.get(ident)
        if kept is not None and kept[0] == sign:
            return kept[1]
        from core.section import layer_fills
        fills = layer_fills(segs, tags, sp.normal, scene, color)
        memo[ident] = (sign, fills)
        return fills

    def _draw_section_arrays(self, arr, rgb, mode) -> None:
        """One colour of the cut's fill: triangles or lines, world space."""
        raw = arr.reshape(-1).astype("float32").tobytes()
        self._section_vbo.bind()
        self._section_vbo.allocate(raw, len(raw))
        self._section_vbo.release()
        self._set_color(rgb[0], rgb[1], rgb[2], 1.0)
        self._program.setUniformValue(
            self._loc_back_color, QVector4D(rgb[0], rgb[1], rgb[2], 1.0))
        self._section_vao.bind()
        per = 3 if mode == GL_TRIANGLES else 2
        self._gl.glDrawArrays(mode, 0, len(arr) * per)
        self._section_vao.release()

    def _draw_layer_fills(self, fc, sp=None, i=None) -> None:
        """«Layers' hatches»: each layer's cut in its ground, its hatch
        lines over it in its ink — the sheets' patterns, in the model. The
        fill lies in its cut, left out of the clip while it draws (cut
        ``i``; the other cuts still clip it)."""
        fills = self._section_layer_fills(fc, sp)
        if not fills:
            return
        if i is None:
            self._set_section_clip(False)
        else:
            self._set_section_clip(True, skip=i)
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(2.0, 2.0)
        for tris, rgb, _lines, _ink in fills:
            self._draw_section_arrays(tris, rgb, GL_TRIANGLES)
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        for _tris, _rgb, lines, ink in fills:
            if lines is not None and len(lines):
                self._draw_section_arrays(lines, ink, GL_LINES)
        self._set_section_clip(True)

    def _section_hatch(self, spacing: float, cross: bool, sp=None):
        """The hatch lines of the cut of ``sp`` (the active plane when not
        given) whose fill is cached, per (spacing, cross) — computed once,
        while the cut stays the same."""
        if sp is None:
            sp = self.scene.active_section()
        memo = getattr(self, "_section_fill_cache", None)
        cached = (memo.get(self._cut_ident(sp))
                  if isinstance(memo, dict) and sp is not None else None)
        if cached is None:
            return None
        hatches = cached[2]
        key = (round(spacing, 9), bool(cross))
        if key not in hatches:
            from core.section import hatch_segments
            hatches[key] = hatch_segments(cached[0], sp.normal, spacing,
                                          cross)
        return hatches[key]

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
        Lives in the style (style.section_fill).

        Every cut is filled — the active plane and each face of the section
        box — each clipped by the others, so a box face's fill ends at the
        box and the plane's at the box too."""
        if not getattr(self, "_clip_vecs", None):
            return
        if mode in ("wireframe", "xray") or xray_enabled(style):
            return
        for i, sp in enumerate(self._clip_planes):
            self._draw_one_section_fill(i, sp, style)
        self._set_section_clip(True)

    def _draw_one_section_fill(self, i, sp, style) -> None:
        """The fill of cut ``i`` (``sp``) — see ``_draw_section_fill``."""
        # The plane's own fill over the style's (the style's switch is the
        # master): solid, hatched, cross-hatched or none, in its colour.
        from core.section import effective_fill
        pattern, fc, spacing = effective_fill(sp, style)
        if pattern == "none":
            return
        if pattern == "layers":
            self._draw_layer_fills(fc, sp, i)
            return
        tris = self._section_fill_tris(sp)
        if tris is None or not len(tris):
            return
        # The fill lies IN its plane, which clips: that one is left out while
        # it draws (the other cuts still clip it), nudged a hair behind so
        # the thick cut lines drawn later win the depth test.
        self._set_section_clip(True, skip=i)
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
            lines = self._section_hatch(spacing, pattern == "cross", sp)
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

    def _draw_section_cut_edges(self) -> None:
        """Thick section-cut lines: quads in each cut plane, sized
        ~2.5 px, nudged toward the CLIPPED side so they never z-fight the
        remaining geometry; each clipped by the OTHER cuts (a box face's
        lines stop at the box). Then the same line where two cuts meet in
        the material — a box's corner — which no edge of the model draws.
        Skipped when cuts are hidden."""
        if not getattr(self, "_clip_vecs", None):
            return
        import numpy as np
        planes = self._clip_planes
        normals = [np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()],
                            dtype=np.float64) for sp in planes]
        for i, sp in enumerate(planes):
            self._set_section_clip(True, skip=i)
            self._draw_cut_quads(self._section_cut_segments(sp), normals[i],
                                 sp)
        for i, a in enumerate(planes):
            for j in range(i + 1, len(planes)):
                segs = self._cut_corner_segments(a, planes[j])
                if segs is None:
                    continue
                # Both planes hold it: out of the two, along their bisector.
                n = normals[i] + normals[j]
                n /= max(float(np.linalg.norm(n)), 1e-9)
                self._set_section_clip(True, skip=(i, j))
                self._draw_cut_quads(segs, n)
        self._set_section_clip(False)

    def _cut_corner_segments(self, a, b):
        """Where the cuts ``a`` and ``b`` meet inside the material
        (``core.section.plane_pair_line``), cached with ``a``'s cut and
        ``b``'s pose. ``None`` when they are parallel or meet in the air."""
        chords = self._section_cut_segments(a)
        p, n = b.point, b.normal
        key = (id(chords), round(p.x(), 6), round(p.y(), 6), round(p.z(), 6),
               round(n.x(), 9), round(n.y(), 9), round(n.z(), 9))
        memo = getattr(self, "_section_corner_cache", None)
        if memo is None:
            memo = self._section_corner_cache = {}
        slot = (self._cut_ident(a), self._cut_ident(b))
        cached = memo.get(slot)
        if cached is not None and cached[0] == key and cached[1] is chords:
            return cached[2]
        from core.section import plane_pair_line
        segs = plane_pair_line(a, b, chords)
        memo[slot] = (key, chords, segs)
        return segs

    def _cut_line_tris(self, segs, n, sp=None):
        """The triangles of the thick line along ``segs`` ((K, 2, 3)) on the
        plane of normal ``n``: (2K, 9) float32, or ``None``. One width on
        SCREEN, ~2.5 px, all round the contour and along it:

        - worked out at each end, or the width of a chord, taken once at
          its middle, stepped where two chords of one straight line met;
        - from the depth along the view (none in a parallel view, one scale
          at every depth), not the distance to the eye;
        - against the plane's tilt: the quad lies IN the plane, where a
          width across the line shows foreshortened by an amount that
          depends on the line's direction — on a plane seen at an angle, a
          rectangle's two pairs of sides read as two thicknesses. It is
          stretched by what the view takes off.

        The ends go on by half a width, so that two lines meeting at a
        corner close it instead of leaving a notch."""
        import numpy as np
        if segs is None or not len(segs):
            return None
        a = segs[:, 0].astype(np.float64)
        b = segs[:, 1].astype(np.float64)
        t = b - a
        ln = np.linalg.norm(t, axis=1)
        keep = ln > 1e-9
        if not keep.any():
            return None
        a, b, t, ln = a[keep], b[keep], t[keep], ln[keep]
        t /= ln[:, None]
        side = np.cross(np.broadcast_to(n, t.shape), t)
        weight = (self._cut_edge_weights(sp, keep, segs)
                  if sp is not None else None)
        cam = self.camera
        eye = cam.eye()
        eyev = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float64)
        tgt = cam.target
        fwd = np.array([tgt.x(), tgt.y(), tgt.z()], dtype=np.float64) - eyev
        fwd /= max(float(np.linalg.norm(fwd)), 1e-12)
        perspective = bool(getattr(cam, "perspective", True))
        h = max(1.0, self.height())
        tan = math.tan(math.radians(getattr(cam, "fov_deg", 45.0)) * 0.5)
        # The style's section-cut width in screen pixels (#1218); 2.5 px,
        # the default, is the line this always drew.
        style = (getattr(self, "_frame_style", None)
                 or getattr(self.scene, "display_style", None))
        width_k = max(0.1, float(getattr(style, "section_cut_width",
                                         2.5))) / 2.5

        def widths(p):
            """Half a line at ``p``, in the world: its plain size, across
            the line in the plane, and along the line."""
            if perspective:
                rel = p - eyev
                depth = np.maximum(rel @ fwd, 1e-6)
                view = rel / np.maximum(
                    np.linalg.norm(rel, axis=1, keepdims=True), 1e-12)
            else:
                depth = np.full(len(p), float(cam.distance))
                view = np.broadcast_to(fwd, p.shape)
            w = np.maximum(depth * tan * 2.0 / h, 1e-6) * 1.25 * width_k
            along = t - (t * view).sum(axis=1, keepdims=True) * view
            along_len = np.linalg.norm(along, axis=1, keepdims=True)
            unit = along / np.maximum(along_len, 1e-9)
            flat = side - (side * view).sum(axis=1, keepdims=True) * view
            flat = flat - (flat * unit).sum(axis=1, keepdims=True) * unit
            across_len = np.linalg.norm(flat, axis=1, keepdims=True)
            # Edge-on, no stretch makes it show: held at five times.
            return (w[:, None], w[:, None] / np.maximum(across_len, 0.2),
                    w[:, None] / np.maximum(along_len, 0.2))

        wa, sa, ca = widths(a)
        wb, sb, cb = widths(b)
        if weight is not None:
            # A layer's own cut weight («Layers' hatches»): a whole layer's
            # line thicker or thinner, the same all round it.
            wgt = np.asarray(weight, dtype=np.float64)[:, None]
            wa, sa, ca = wa * wgt, sa * wgt, ca * wgt
            wb, sb, cb = wb * wgt, sb * wgt, cb * wgt
        lift = n * 0.6
        a2 = a - t * ca + lift * wa
        b2 = b + t * cb + lift * wb
        q0 = a2 - side * sa
        q1 = b2 - side * sb
        q2 = b2 + side * sb
        q3 = a2 + side * sa
        tris = np.empty((len(a) * 2, 9), dtype=np.float32)
        tris[0::2, 0:3] = q0
        tris[0::2, 3:6] = q1
        tris[0::2, 6:9] = q2
        tris[1::2, 0:3] = q0
        tris[1::2, 3:6] = q2
        tris[1::2, 6:9] = q3
        return tris

    def _draw_cut_quads(self, segs, n, sp=None) -> None:
        tris = self._cut_line_tris(segs, n, sp)
        if tris is None:
            return
        raw = tris.tobytes()
        self._section_vbo.bind()
        self._section_vbo.allocate(raw, len(raw))
        self._section_vbo.release()
        ec = self._modeling_color("section_cut", self._frame_style.edge_color)
        self._set_color(ec[0], ec[1], ec[2], 1.0)
        self._section_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, len(tris) * 3)
        self._section_vao.release()

    #: The sheet's cut pen (mm) a layer's own cut weight is measured
    #: against in the model: a layer at 0.50 draws the usual ~2.5 px line.
    CUT_PEN_MM = 0.5

    def _cut_edge_weights(self, plane, keep, segs=None):
        """How much thicker or thinner each cut line of ``plane`` is drawn
        than usual: with «Layers' hatches» each layer's cut weight (Muros at
        0.70 a heavy line, an insulation at 0.18 a fine one), as on a sheet;
        otherwise all alike. Only for the plane's own cut segments (a box's
        corner line has no layer)."""
        import numpy as np
        from core.section import effective_fill
        count = int(keep.sum())
        pattern = effective_fill(plane, self._frame_style)[0]
        if pattern != "layers":
            return np.ones(count)
        if segs is not None and segs is not self._section_cut_segments(plane):
            return np.ones(count)
        tags = self._section_cut_tags(plane)
        if tags is None or len(tags) != len(keep):
            return np.ones(count)
        pens = {ly.name: float(ly.cut_weight) / self.CUT_PEN_MM
                for ly in self.scene.layers
                if getattr(ly, "cut_weight", None) is not None}
        if not pens:
            return np.ones(count)
        out = np.array([pens.get(t, 1.0) for t in tags[keep].tolist()])
        return np.clip(out, 0.4, 2.4)

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
