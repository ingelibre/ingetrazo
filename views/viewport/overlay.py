# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The 2D QPainter overlay: snap indicator, guides, labels, dimensions and text."""
from __future__ import annotations

import math
from typing import Optional
from core.units import fmt_len as _fmt_len
from core.units import typed_value_text as _typed_value_text
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QVector3D
from core.i18n import tr
from core.snap import SnapResult


class OverlayMixin:
    """The 2D QPainter overlay: snap indicator, guides, labels, dimensions and text."""

    def _draw_rubber_band_overlay(self, painter: QPainter) -> None:
        if self._overlay_rubber is None:
            return
        segments, color, width = self._overlay_rubber
        r, g, b = color[0], color[1], color[2]
        a = color[3] if len(color) > 3 else 1.0
        pen = QPen(QColor.fromRgbF(r, g, b, a), width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for p0, p1 in segments:
            q = self._segment_to_pixels(p0, p1)
            if q is not None:
                painter.drawLine(QPointF(*q[0]), QPointF(*q[1]))

    def _draw_guide_preview(self, painter: QPainter) -> None:
        """The guide the Tape or the Protractor is about to leave, dashed
        like the guides themselves, following the cursor (#89, @pacaeiro)."""
        tool = self.active_tool
        lines = (tool.guide_preview_lines()
                 if tool is not None
                 and hasattr(tool, "guide_preview_lines") else [])
        if not lines:
            return
        pen = QPen(QColor(70, 90, 120), 1.5, Qt.DashLine)
        pen.setDashPattern([10.0, 7.0])
        painter.setPen(pen)
        for p0, p1 in lines:
            q = self._segment_to_pixels(p0, p1)
            if q is not None:
                painter.drawLine(QPointF(*q[0]), QPointF(*q[1]))

    # ---- 2D overlay (QPainter on top of OpenGL) -----------------------------
    def _draw_overlay(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # Rubber band for the "always on top" tools (Line/Rectangle/Move),
        # drawn here with a thick, reliable pen.
        self._draw_rubber_band_overlay(painter)
        self._draw_guide_preview(painter)

        # The acquired circle centre (Center inference): a small
        # green dot at the centre of the last circle or arc the cursor
        # visited — shown only once the cursor comes NEAR it, not the whole
        # time you are on the face («solo debería aparecer cuando me ponga
        # cerca del medio del círculo», Marco, 2026-09-11).
        ref = self._valid_center_ref()
        snapped_on_it = (self.last_snap is not None
                         and self.last_snap.kind == "center")
        if ref is not None and self.active_tool is not None \
                and self.active_tool.uses_snap \
                and not snapped_on_it and self._last_mouse_pos is not None:
            pc = self._world_to_pixel(ref[0])
            near = pc is not None and self._center_hint_px(ref, pc) > 0.0 \
                and math.hypot(pc[0] - self._last_mouse_pos.x(),
                               pc[1] - self._last_mouse_pos.y()) \
                <= self._center_hint_px(ref, pc)
            if near:
                from core.snap import COLOR_ENDPOINT as _CE
                painter.setPen(QPen(QColor(255, 255, 255, 230), 3.0))
                painter.setBrush(QColor.fromRgbF(*_CE, 1.0))
                painter.drawEllipse(QPointF(*pc), 4.0, 4.0)
                painter.setPen(QPen(QColor.fromRgbF(*_CE, 1.0), 1.5))
                painter.drawEllipse(QPointF(*pc), 4.0, 4.0)
        # Snap indicator
        if (
            self.active_tool is not None
            and self.last_snap is not None
            and self.last_snap.kind != "none"
        ):
            self._draw_snap_indicator(painter, self.last_snap)

        # Push/Pull distance-inference marker (a green square on the corner/face
        # the extrusion is snapping level with).
        self._draw_inference_marker(painter)

        # Construction guides (Tape Measure) — fine dashed scaffolding lines.
        self._draw_guides(painter)

        # Borders of the reference images, so one lying flat is still findable.
        self._draw_image_outlines(painter)

        # The Scale tool's grip box (yellow box with green grips).
        self._draw_scale_box(painter)
        self._draw_section_planes(painter)
        # Tool-owned overlay (the Flip planes; the future Axes gizmo): a tool
        # exposing ``draw_overlay(viewport, painter)`` paints after the
        # document annotations, before the edit-group frame.
        hook = getattr(self.active_tool, "draw_overlay", None)
        if callable(hook):
            hook(self, painter)
        # Extensions' overlays (``ExtensionApp.add_overlay``).
        self._draw_extension_overlays(painter)

        # Terrain-surface fills (draped / flat) under the georef paths — Track G.
        self._draw_geo_surfaces(painter)

        # Traced georef paths (roads / boundaries) — Track G.
        self._draw_geo_paths(painter)

        # Imported survey points (GPS / total station) — Track G.
        self._draw_geo_points(painter)

        # Profile→plan marker: the route point at the station hovered in the
        # profile panel (Track G).
        if self._route_marker is not None:
            q = self._world_to_pixel(self.drape(self._route_marker))
            if q is not None:
                painter.setBrush(QColor(243, 115, 41))
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.drawEllipse(QPointF(*q), 6, 6)
                painter.setBrush(Qt.NoBrush)

        # Persistent dimension annotations
        self._draw_dimensions(painter)

        # Leader-text annotations
        self._draw_text_labels(painter)

        # Length measurement near rubber band
        self._draw_length_label(painter)

        # Labels in the top-left. Reference > explicit axis lock > soft inference.
        if self.reference_mode is not None:
            self._draw_reference_label(painter)
        elif self.axis_lock is not None:
            self._draw_axis_lock_label(painter)
        elif getattr(self.active_tool, "plane_lock", None) is not None:
            self._draw_plane_lock_label(painter)
        else:
            self._draw_inference_label(painter)

        # Linear-inference toggle state (Alt), shown while not on the default.
        if self.linear_inference_mode != "all":
            self._draw_linear_mode_label(painter)

        # Rubber-band selection box.
        self._draw_selection_box(painter)
        self._draw_zoom_box(painter)

        painter.end()

    def _draw_linear_mode_label(self, painter: QPainter) -> None:
        # The mirror image of the bug above: these had the Spanish written
        # into the source, so an English UI showed Spanish.
        text = {
            "off": tr("Linear inferences: OFF (Alt)"),
            "parallel_perp": tr("Inferences: parallel / perpendicular only (Alt)"),
        }.get(self.linear_inference_mode)
        if not text:
            return
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QPen(QColor(210, 150, 40)))
        painter.drawText(QPointF(14, self.height() - 16), text)

    def _draw_selection_box(self, painter: QPainter) -> None:
        if not self._box_active or self._box_start is None or self._box_cur is None:
            return
        s, c = self._box_start, self._box_cur
        if math.hypot(c.x() - s.x(), c.y() - s.y()) < self.BOX_DRAG_THRESHOLD_PX:
            return
        rect = QRectF(
            min(s.x(), c.x()), min(s.y(), c.y()),
            abs(c.x() - s.x()), abs(c.y() - s.y()),
        )
        crossing = (c.x() - s.x()) < 0
        if crossing:
            # Crossing: dashed green, selects anything it touches.
            pen = QPen(QColor(40, 158, 92), 1.5, Qt.DashLine)
            fill = QColor(40, 158, 92, 28)
        else:
            # Window: solid blue, selects only fully enclosed.
            pen = QPen(QColor(51, 102, 199), 1.5, Qt.SolidLine)
            fill = QColor(51, 102, 199, 28)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRect(rect)

    def _draw_zoom_box(self, painter: QPainter) -> None:
        if (not self._zoom_box_active or self._zoom_box_start is None
                or self._zoom_box_cur is None):
            return
        s, c = self._zoom_box_start, self._zoom_box_cur
        rect = QRectF(
            min(s.x(), c.x()), min(s.y(), c.y()),
            abs(c.x() - s.x()), abs(c.y() - s.y()),
        )
        painter.setPen(QPen(QColor(243, 115, 41), 1.5, Qt.DashLine))
        painter.setBrush(QColor(243, 115, 41, 26))
        painter.drawRect(rect)

    def _draw_snap_indicator(self, painter: QPainter, snap: SnapResult) -> None:
        # Axis-lock and inference state is conveyed by the coloured rubber
        # band; no badge follows the cursor along the lock line. Only the
        # discrete point snaps get a marker.
        if snap.kind in ("axis_inference", "axis"):
            return
        pixel = self._world_to_pixel(snap.point)
        if pixel is None:
            return
        r, g, b = snap.color
        color = QColor.fromRgbF(r, g, b, 1.0)
        # Dashed guide line (the extension inference shows the edge's dashed
        # continuation to the cursor).
        if snap.guide is not None:
            gp0 = self._world_to_pixel(snap.guide[0])
            gp1 = self._world_to_pixel(snap.guide[1])
            if gp0 is not None and gp1 is not None:
                # A snap can colour its guide differently from the marker (the
                # 'from point' guide is axis-coloured while the point is green).
                gc = snap.guide_color if snap.guide_color is not None else (r, g, b)
                dash = QPen(QColor.fromRgbF(gc[0], gc[1], gc[2], 0.9), 2.0, Qt.DashLine)
                painter.setPen(dash)
                vis = self._clip_pixel_line(gp0, gp1)
                if vis is not None:
                    painter.drawLine(QPointF(*vis[0]), QPointF(*vis[1]))
        for ga, gb_, gc in (snap.guides or []):
            gp0 = self._world_to_pixel(ga)
            gp1 = self._world_to_pixel(gb_)
            if gp0 is not None and gp1 is not None:
                painter.setPen(QPen(QColor.fromRgbF(gc[0], gc[1], gc[2], 0.9), 2.0, Qt.DashLine))
                vis = self._clip_pixel_line(gp0, gp1)
                if vis is not None:
                    painter.drawLine(QPointF(*vis[0]), QPointF(*vis[1]))
        # A white halo under the marker lifts it off busy geometry, then
        # the coloured marker on top — bigger and bolder than before so the
        # snap point reads at a glance (a common request: the dots were too
        # small to aim with).
        halo = QPen(QColor(255, 255, 255, 230), 4.5)
        mark = QPen(color, 2.6)
        painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
        px, py = pixel
        if snap.kind == "intersection":
            # X marker at the crossing (drawn line × projected guide).
            for pen in (halo, mark):
                painter.setPen(pen)
                painter.drawLine(QPointF(px - 8, py - 8), QPointF(px + 8, py + 8))
                painter.drawLine(QPointF(px - 8, py + 8), QPointF(px + 8, py - 8))
        elif snap.kind == "center":
            # The centre of a circle: a filled dot.
            painter.setPen(halo)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
            painter.setPen(mark)
            painter.setBrush(QColor.fromRgbF(r, g, b, 0.85))
            painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
        elif snap.kind in ("endpoint", "origin", "component_origin", "on_edge",
                           "on_axis",
                           "on_line", "extension", "from_point", "aligned",
                           "tangent"):
            rect = QRectF(px - 7, py - 7, 14, 14)
            painter.setPen(halo)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            painter.setPen(mark)
            painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
            painter.drawRect(rect)
        elif snap.kind in ("midpoint", "arc_midpoint"):
            # Cyan diamond.
            diamond = QPolygonF([
                QPointF(px, py - 9), QPointF(px + 9, py),
                QPointF(px, py + 9), QPointF(px - 9, py),
            ])
            painter.setPen(halo)
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(diamond)
            painter.setPen(mark)
            painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
            painter.drawPolygon(diamond)
        elif snap.kind == "on_face":
            painter.setPen(halo)
            painter.drawEllipse(QPointF(px, py), 5.5, 5.5)
            painter.setPen(mark)
            painter.drawEllipse(QPointF(px, py), 5.5, 5.5)
        elif snap.kind == "close":
            painter.setPen(halo)
            painter.drawEllipse(QPointF(px, py), 9.0, 9.0)
            painter.setPen(mark)
            painter.drawEllipse(QPointF(px, py), 9.0, 9.0)
        elif snap.kind in ("reference", "through_point", "perp_face"):
            painter.setPen(halo)
            painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
            painter.setPen(mark)
            painter.drawEllipse(QPointF(px, py), 6.5, 6.5)

        # Tooltip text next to the marker ("On Edge", etc.).
        label = self._SNAP_LABELS.get(snap.kind)
        if snap.kind == "aligned" and snap.axis == "z":
            label = "Level with point"
        if label:
            label = tr(label)
        if getattr(snap, "label", None):
            label = snap.label               # an extension's own words
        if label:
            ctx_ = getattr(snap, "context", None)
            if ctx_ == "component":
                label += " " + tr("in component")
            elif ctx_ == "group":
                label += " " + tr("in group")
            font = QFont()
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(QPen(QColor(255, 255, 255, 220)))
            painter.drawText(QPointF(px + 11, py + 17), label)
            painter.setPen(QPen(color))
            painter.drawText(QPointF(px + 10, py + 16), label)

    def _edit_group_box_corners(self):
        """The eight corners of the dashed box around the group being edited
        — the visual cue that you are INSIDE it (the classic dashed
        box) — or None. Drawn in the GL pass, depth-tested."""
        group = self.scene.edit_group
        if group is None:
            return None
        if not group.mesh.vertices and not getattr(group, "children", None):
            return None     # nothing to wrap
        # A CONTAINER's own mesh is usually empty — its geometry is in its
        # children — so testing that mesh alone left you inside a group with
        # no box at all, the one cue that tells you where you are.
        # In the group's OWN axes, like the selection cue: on a rotated
        # object a world-aligned box reads as skewed and wraps mostly air.
        from core.group import oriented_box_corners
        return oriented_box_corners(*self._group_obb(group))

    def _draw_scale_box(self, painter: QPainter) -> None:
        """The scaling box: yellow edges, green grips, the grabbed grip
        and its anchor in red. Drawn from whatever the active tool reports via
        ``scale_box_state()`` (duck-typed, so this file needs no tool import);
        while an operation is live the box rides the same matrix the geometry
        is being scaled by."""
        tool = self.active_tool
        state_fn = getattr(tool, "scale_box_state", None)
        if state_fn is None:
            return
        state = state_fn()
        if state is None:
            return
        box_pen = QPen(QColor(214, 174, 0), 1)          # grip-box yellow
        painter.setPen(box_pen)
        for a, b in state["segments"]:
            seg = self._clip_segment_front(a, b)
            if seg is None:
                continue
            pa = self._world_to_pixel(seg[0])
            pb = self._world_to_pixel(seg[1])
            if pa is not None and pb is not None:
                painter.drawLine(QPointF(*pa), QPointF(*pb))
        green = QColor(60, 160, 60)
        red = QColor(220, 40, 40)
        # Far grips first, so a grip at the front of the box is drawn over
        # the one behind it rather than under it (#833).
        eye = self.camera.eye()
        fwd = self.camera.target - eye
        grips = sorted(state["grips"], key=lambda g: -QVector3D.dotProduct(
            g[0] - eye, fwd))
        for pos, role in grips:
            px = self._world_to_pixel(pos)
            if px is None:
                continue
            half = 5.0 if role in ("hover", "active", "anchor") else 4.0
            color = green if role == "idle" else red
            painter.fillRect(QRectF(px[0] - half, px[1] - half,
                                    half * 2, half * 2), color)
            painter.setPen(QPen(QColor(30, 30, 30), 1))
            painter.drawRect(QRectF(px[0] - half, px[1] - half,
                                    half * 2, half * 2))
        painter.setPen(box_pen)

    def _clip_pixel_line(
        self, p0: tuple[float, float], p1: tuple[float, float],
        margin: float = 64.0,
    ) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
        """Liang-Barsky clip of a 2D pixel segment to the widget rect (plus a
        margin). Overlay guides are only clipped in 3D to the part in front of
        the camera (``_clip_segment_front``), so their on-screen endpoints land
        MILLIONS of pixels from origin. Qt's dash stroker runs in fixed point
        and collapses a dashed pen into a solid line at that scale (measured:
        a guide of 400 k px still dashes, 4 M px comes out solid). Trimming to
        the visible area first keeps the dashes — and spares the rasteriser
        hundreds of thousands of dash repeats. Returns the clipped endpoints,
        or ``None`` when the segment misses the widget entirely."""
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = x1 - x0, y1 - y0
        xmin, ymin = -margin, -margin
        xmax, ymax = self.width() + margin, self.height() + margin
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, x0 - xmin), (dx, xmax - x0),
                     (-dy, y0 - ymin), (dy, ymax - y0)):
            if p == 0.0:
                if q < 0.0:
                    return None
                continue
            r = q / p
            if p < 0.0:
                if r > t1:
                    return None
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return None
                if r < t1:
                    t1 = r
        return ((x0 + t0 * dx, y0 + t0 * dy),
                (x0 + t1 * dx, y0 + t1 * dy))

    def _draw_guides(self, painter: QPainter) -> None:
        """The small crosses of guide POINTS, the usual scaffolding.

        Guide LINES are not here any more: they are drawn in the GL pass so
        the depth buffer hides them behind geometry (issue #23). A cross is
        a screen-space mark a few pixels wide, not a line through the
        model, so it stays in the overlay where its size is in pixels."""
        guides = getattr(self.scene, "guides", None)
        if not guides:
            return
        pen = QPen(QColor(70, 90, 120), 1, Qt.DashLine)
        pen.setDashPattern([14.0, 10.0])
        sel_pen = QPen(QColor(243, 115, 41), 2, Qt.DashLine)  # selection orange
        sel_pen.setDashPattern([14.0, 10.0])
        selection = self.scene.selection
        for g in guides:
            if g.is_line:
                continue
            painter.setPen(sel_pen if g in selection else pen)
            q = self._world_to_pixel(g.point)
            if q is not None:
                painter.drawLine(QPointF(q[0] - 5, q[1]), QPointF(q[0] + 5, q[1]))
                painter.drawLine(QPointF(q[0], q[1] - 5), QPointF(q[0], q[1] + 5))

    @staticmethod
    def _text_block_x(p_pos, p_anchor, block_w: float) -> float:
        """Left edge of a leader-text block whose leader ends at ``p_pos``.

        The block sits on the side of the leader end AWAY from the anchor
        (the usual convention): to the right when the anchor is left of the label, to the
        LEFT when the leader arrives from the right — otherwise the leader
        runs straight through the words (Marco's "Pileta de piedra basalto"
        label, 2026-09-02). Shared by the paint pass and the text pick so
        the hit box is the drawn box."""
        if p_anchor is not None and p_pos[0] < p_anchor[0]:
            return p_pos[0] - 6 - block_w
        return p_pos[0] + 6

    def _draw_text_labels(self, painter: QPainter) -> None:
        """Draw every leader-text annotation: a leader line from the anchor
        (hidden where geometry occludes it, like dimensions) up to the label,
        an anchor dot, and the multi-line text with a white halo."""
        labels = getattr(self.scene, "text_labels", None)
        if not labels:
            return
        style = getattr(self.scene, "dimension_style", {})
        col = style.get("color", [45, 55, 75])
        default_ink = QColor(col[0], col[1], col[2])
        sel_ink = QColor(243, 115, 41)
        selection = self.scene.selection
        font = QFont()
        font.setPointSize(int(style.get("font_size", 9)))
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        for lab in labels:
            if not self.scene.entity_visible(lab):      # hidden layer
                continue
            ink = (sel_ink if (lab in selection or lab is self._hover_entity)
                   else default_ink)
            pos = lab.position()
            p_anchor = self._world_to_pixel(lab.anchor)
            p_pos = self._world_to_pixel(pos)
            if p_pos is None:
                continue
            painter.setPen(QPen(ink, 1.2))
            self._draw_occluded_segment(painter, lab.anchor, pos)   # leader
            if p_anchor is not None and not self._occluded_on_screen(lab.anchor):
                painter.setBrush(ink)
                painter.drawEllipse(QPointF(*p_anchor), 2.5, 2.5)
                painter.setBrush(Qt.NoBrush)
            lines = lab.text.splitlines() or [""]
            x = self._text_block_x(
                p_pos, p_anchor, max(fm.horizontalAdvance(ln) for ln in lines))
            for i, line in enumerate(lines):
                y = p_pos[1] - 4 + i * fm.height()
                painter.setPen(QPen(QColor(255, 255, 255, 230)))
                painter.drawText(QPointF(x + 1, y + 1), line)
                painter.setPen(QPen(ink))
                painter.drawText(QPointF(x, y), line)

    def _draw_dimensions(self, painter: QPainter) -> None:
        """Draw every committed static dimension: extension lines from the
        measured endpoints out to the dimension line, the dimension line with
        end ticks, and the value label at its midpoint."""
        dims = getattr(self.scene, "dimensions", None)
        if not dims:
            return
        style = getattr(self.scene, "dimension_style", {})
        col = style.get("color", [45, 55, 75])
        default_ink = QColor(col[0], col[1], col[2])
        sel_ink = QColor(243, 115, 41)  # selection orange
        selection = self.scene.selection
        font = QFont()
        font.setPointSize(int(style.get("font_size", 9)))
        font.setBold(True)
        # A groups preview (Move/Rotate) moves no geometry until the commit:
        # the dimensions held by the movers' vertices are drawn where the
        # commit will put them, or they lagged behind the whole drag (#621).
        riders = getattr(self, "_preview_groups", None)
        carry = self._groups_preview_transform() if riders else None
        for dim in dims:
            if not self.scene.entity_visible(dim):      # hidden layer
                continue
            ink = (sel_ink if (dim in selection or dim is self._hover_entity)
                   else default_ink)
            if riders:
                ends = dim.ends_riding(riders)
                if ends:
                    dim = dim.carried(carry, ends)
            ap, bp = dim.line_points()
            pap = self._world_to_pixel(ap)
            pbp = self._world_to_pixel(bp)
            if pap is None or pbp is None:
                continue
            # Lines are hidden where solid geometry sits in front of them, so a
            # dimension reads as part of the model instead of floating over it.
            # Each 3D segment is sampled and only its visible runs are drawn.
            painter.setPen(QPen(ink, 1.0))
            self._draw_occluded_segment(painter, dim.a, ap)      # extension
            self._draw_occluded_segment(painter, dim.b, bp)
            painter.setPen(QPen(ink, 1.5))
            self._draw_occluded_segment(painter, ap, bp)         # dimension line
            # The ends, in screen space, drawn only where the end point
            # itself is visible: filled arrows pointing outward (the
            # document's default), oblique ticks, or nothing.
            dx, dy = pbp[0] - pap[0], pbp[1] - pap[1]
            ln = math.hypot(dx, dy)
            ends = style.get("ends", "arrow") or "arrow"
            if ln > 1e-6 and ends != "none":
                ux, uy = dx / ln, dy / ln
                for (cx, cy), w, sign in ((pap, ap, 1.0), (pbp, bp, -1.0)):
                    if self._occluded_on_screen(w):
                        continue
                    if ends == "tick":
                        ox, oy = -uy * 4.0, ux * 4.0
                        painter.drawLine(QPointF(cx - ox, cy - oy),
                                         QPointF(cx + ox, cy + oy))
                    else:
                        # tip at the end, wings trailing INTO the line
                        # (inside arrows: they point at the extension lines)
                        L, half = 10.0, 2.2
                        bx, by = cx + sign * ux * L, cy + sign * uy * L
                        painter.save()
                        painter.setBrush(ink)
                        painter.setPen(Qt.NoPen)
                        painter.drawPolygon(QPolygonF([
                            QPointF(cx, cy),
                            QPointF(bx - uy * half, by + ux * half),
                            QPointF(bx + uy * half, by - ux * half)]))
                        painter.restore()
            # Value label at the dimension line's midpoint — hidden if that
            # point is behind the solid.
            mid_world = dim.midpoint()
            mid = self._world_to_pixel(mid_world)
            if mid is not None and not self._occluded_on_screen(mid_world):
                text = dim.display_text(
                    self._format_dim_value(dim.value(), style))
                painter.setFont(font)
                painter.setPen(QPen(QColor(255, 255, 255, 230)))
                painter.drawText(QPointF(mid[0] + 5, mid[1] - 4), text)
                painter.setPen(QPen(ink))
                painter.drawText(QPointF(mid[0] + 4, mid[1] - 5), text)

    @staticmethod
    def _format_dim_value(metres: float, style: dict) -> str:
        """Format a length (metres) per the dimension style: unit + precision
        (see :mod:`core.units` — metric, decimal or fractional imperial)."""
        from core.units import format_length
        return format_length(metres, style.get("units", "m"),
                             int(style.get("decimals", 2)))

    def _draw_occluded_segment(self, painter: QPainter, p3a: QVector3D,
                               p3b: QVector3D, samples: int = 16) -> None:
        """Draw the 3D segment ``p3a``–``p3b`` in screen space, skipping the
        parts hidden behind solid geometry (CPU occlusion sample). A sub-segment
        is drawn only when both its sampled ends are visible, so the line never
        bleeds over the solid; the silhouette gap is sub-pixel at this density."""
        prev_px = None
        prev_vis = False
        for i in range(samples + 1):
            t = i / samples
            w = p3a + (p3b - p3a) * t
            px = self._world_to_pixel(w)
            vis = px is not None and not self._occluded_on_screen(w)
            if prev_px is not None and px is not None and prev_vis and vis:
                painter.drawLine(QPointF(*prev_px), QPointF(*px))
            prev_px, prev_vis = px, vis

    def _draw_inference_marker(self, painter: QPainter) -> None:
        """Green endpoint-style square where the active tool's distance
        inference is engaged (Push/Pull snapping level with a corner or face)."""
        tool = self.active_tool
        provider = getattr(tool, "inference_marker", None) if tool is not None else None
        if not callable(provider):
            return
        result = provider()
        if result is None:
            return
        world, kind = result
        # The same colours and words as the snap markers: a corner is the
        # endpoint green, an edge the on-edge red, a face the on-face blue
        # — the classic cue says "On edge" while you push level with one.
        from core.snap import (COLOR_ENDPOINT, COLOR_ON_EDGE, COLOR_ON_FACE,
                               COLOR_ORIGIN)
        palette = {
            "origin": (COLOR_ORIGIN, "origin"),
            "edge": (COLOR_ON_EDGE, "on_edge"),
            "face": (COLOR_ON_FACE, "on_face"),
            "guide_line": (COLOR_ON_EDGE, "on_line"),
            "guide_point": (COLOR_ENDPOINT, "guide_point"),
        }
        rgb, label = palette.get(kind, (COLOR_ENDPOINT, "endpoint"))
        color = QColor.fromRgbF(*rgb, 1.0)
        # The dotted «level with» reference line from the geometry the
        # inference locked onto to the moving cap, dashed in that snap-kind
        # colour. Drawn before the marker's own point is projected: a point
        # behind the eye is dropped whole, a segment crossing it is merely
        # clipped, and the reference must survive (Fix 3).
        guide_provider = getattr(tool, "inference_guide_lines", None)
        if callable(guide_provider):
            pen = QPen(color, 1.5, Qt.DashLine)
            pen.setDashPattern([10.0, 7.0])
            for a, b, g_kind in guide_provider():
                g_rgb = palette.get(g_kind, (COLOR_ENDPOINT, "endpoint"))[0]
                pen.setColor(QColor.fromRgbF(*g_rgb, 1.0))
                painter.setPen(pen)
                seg = self._segment_to_pixels(a, b)
                if seg is not None:
                    painter.drawLine(QPointF(*seg[0]), QPointF(*seg[1]))
        pixel = self._world_to_pixel(world)
        if pixel is None:
            return
        px, py = pixel
        painter.setPen(QPen(QColor(255, 255, 255, 230), 4.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(px - 6, py - 6, 12, 12))
        painter.setPen(QPen(color, 2.4))
        painter.setBrush(QColor.fromRgbF(*rgb, 0.30))
        painter.drawRect(QRectF(px - 6, py - 6, 12, 12))
        text = tr(self._SNAP_LABELS.get(label, ""))
        if text:
            font = QFont()
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(QPen(QColor(255, 255, 255, 220)))
            painter.drawText(QPointF(px + 11, py + 17), text)
            painter.setPen(QPen(color))
            painter.drawText(QPointF(px + 10, py + 16), text)

    def _draw_length_label(self, painter: QPainter) -> None:
        tool = self.active_tool
        if tool is None:
            return

        # Tool-provided label takes priority (e.g. PushPullTool's signed
        # extrusion distance). Otherwise fall back to the single-segment
        # length used by LineTool.
        label_provider = getattr(tool, "value_label", None)
        if callable(label_provider):
            result = label_provider()
            if result is None:
                return
            # Extension tools are outside the viewport's control. A malformed
            # value_label() must not break the OpenGL paint loop repeatedly.
            if not isinstance(result, (tuple, list)) or len(result) != 2:
                return
            text, mid_world = result
            if mid_world is None:        # VCB-only value (Walkthrough eye height)
                return
        else:
            segments = tool.rubber_band_lines()
            if len(segments) != 1:
                return
            start, hover = segments[0]
            text = _fmt_len((hover - start).length())
            mid_world = QVector3D(
                (start.x() + hover.x()) * 0.5,
                (start.y() + hover.y()) * 0.5,
                (start.z() + hover.z()) * 0.5,
            )
        pixel = self._world_to_pixel(mid_world)
        if pixel is None:
            return
        if self._value_buffer:
            unitless = getattr(tool, "value_is_unitless", None)
            if callable(unitless) and unitless():
                text = self._value_buffer   # an angle or a count: no unit mark
            else:
                text = _typed_value_text(self._value_buffer)
            fg = QColor("#0F141B")
            shadow = QColor(255, 220, 130, 235)  # warm tint while typing
        else:
            fg = QColor("#0F141B")
            shadow = QColor(255, 255, 255, 220)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(shadow))
        painter.drawText(QPointF(pixel[0] + 12, pixel[1] - 7), text)
        painter.setPen(QPen(fg))
        painter.drawText(QPointF(pixel[0] + 11, pixel[1] - 8), text)

    def _measurement_text(self) -> str:
        """Live measurement string for the VCB box: the active tool's
        ``value_label`` text (rectangle dimensions, push distance, …) or the
        single-segment length a line is drawing. Empty when nothing applies."""
        tool = self.active_tool
        if tool is None:
            return ""
        provider = getattr(tool, "value_label", None)
        if callable(provider):
            result = provider()
            if result is not None:
                return result[0]
        segments = tool.rubber_band_lines()
        if len(segments) == 1:
            start, hover = segments[0]
            return _fmt_len((hover - start).length())
        return ""

    def _draw_axis_lock_label(self, painter: QPainter) -> None:
        label = {
            "x": ("X", QColor(220, 56, 69)),
            "y": ("Y", QColor(40, 158, 92)),
            "z": ("Z", QColor(51, 102, 199)),
        }[self.axis_lock]
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(label[1]))
        # Through tr(): this read "X axis locked" in English even with the
        # Spanish UI, because an f-string never reaches the catalogue.
        painter.drawText(QPointF(14, 24),
                         tr("{axis} axis locked", axis=label[0]))

    def _draw_plane_lock_label(self, painter: QPainter) -> None:
        """The arrow-key plane lock of a planar tool, in the colour of the
        axis the plane is normal to."""
        from tools.base import PLANE_LOCK_NAMES
        axis = self.active_tool.plane_lock
        color = {"x": QColor(220, 56, 69), "y": QColor(40, 158, 92),
                 "z": QColor(51, 102, 199)}[axis]
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(QPointF(14, 24), tr(
            "Drawing plane locked: {plane}", plane=PLANE_LOCK_NAMES[axis]))

    def _draw_inference_label(self, painter: QPainter) -> None:
        """Show 'On Red Axis' style label when soft inference is active."""
        snap = self.last_snap
        if snap is None or snap.kind != "axis_inference":
            return
        names = {"x": "Red", "y": "Green", "z": "Blue"}
        name = names.get(snap.axis or "", "?")
        r, g, b = snap.color
        font = QFont()
        font.setPointSize(10)
        font.setItalic(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor.fromRgbF(r, g, b, 0.95)))
        painter.drawText(QPointF(14, 44), f"On {name} Axis (hold Shift to lock)")

    def _draw_reference_label(self, painter: QPainter) -> None:
        if self.reference_mode is None or self.reference_edge is None:
            return
        r, g, b = (0.85, 0.30, 0.80)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor.fromRgbF(r, g, b, 1.0)))
        word = "Parallel" if self.reference_mode == "parallel" else "Perpendicular"
        painter.drawText(QPointF(14, 24), f"{word} to reference edge")

    def _draw_extension_overlays(self, painter: QPainter) -> None:
        """Extensions' overlays (``ExtensionApp.add_overlay``): whatever the
        active tool, and never able to break the frame. Each call is fenced
        by save/restore, and one that raises is logged ONCE and dropped: a
        paint handler failing on every frame would flood the log and leave
        the view half drawn for good."""
        for fn in list(getattr(self, "_ext_overlays", ())):
            painter.save()
            try:
                fn(self, painter)
            except Exception:  # noqa: BLE001 — a plugin never breaks paint
                import logging
                logging.getLogger("ingetrazo.plugins").exception(
                    "extension overlay %r failed; removed", fn)
                try:
                    self._ext_overlays.remove(fn)
                except ValueError:
                    pass
            finally:
                painter.restore()
