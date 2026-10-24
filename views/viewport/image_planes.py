# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Image planes: drawing, outlines and picking of placed images."""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QVector3D
from views.viewport._support import (GL_TRIANGLES, GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                                     GL_POLYGON_OFFSET_FILL, GL_FALSE, GL_TRUE)


class ImagePlaneMixin:
    """Image planes: drawing, outlines and picking of placed images."""

    def _draw_image_planes(self) -> None:
        """Reference images, as textured quads under the model.

        Depth test on. An opaque image writes depth pushed back by a polygon
        offset, so a line or face drawn exactly ON it still wins the depth
        test (tracing works, no z-fighting) and whatever lies behind it stays
        hidden; a faded image writes none, so the model shows through.

        Shading is pinned to 1.0: a reference scan has to read at its true
        tones, not dimmed by the face lighting.
        """
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return
        import struct
        vao = getattr(self, "_img_vao", None)
        if vao is None:
            self._img_vao, self._img_vbo = self._create_dynamic_uv()
            vao = self._img_vao
        drawn = []
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            tex = self._get_texture(im.path)
            if tex is None:
                continue
            drawn.append((im, tex))
        if not drawn:
            return
        self._program.setUniformValue(self._loc_use_tex, 1)
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._program.setUniformValue1f(self._loc_shade, 1.0)
        # The reference layers before us may leave the foliage cutout on; a
        # scan with soft edges would come out with its alpha chopped.
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._gl.glDepthMask(GL_FALSE)
        # Blending is the frame's default state (paintGL enables it up
        # front for cutouts, glass and the shadow catcher) — a faded image
        # simply relies on it. This pass used to switch blending OFF after a
        # translucent image and never back on: every later blended pass ran
        # opaque, and the shadow catcher (translucent black, alpha 0 where
        # lit) then WROTE alpha 0 over the ground — a transparent hole the
        # size of the model's shadow square, white on screen. Only on
        # frames that reused the cached shadow map (orbit, zoom): a rebuild
        # re-enables blending on its way out, which hid the bug behind
        # every edit (Marco, 2026-09-14: «puse sombras con el tif y orbité»).
        self._gl.glEnable(GL_BLEND)
        self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        for im, tex in drawn:
            c = im.corners()
            # Two triangles, UV (0,0) at ``origin``: _get_texture uploads the
            # image mirrored (bottom-up V), so v grows with the plane's "up"
            # axis and the picture stands upright.
            quad = ((c[0], 0.0, 0.0), (c[1], 1.0, 0.0), (c[2], 1.0, 1.0),
                    (c[0], 0.0, 0.0), (c[2], 1.0, 1.0), (c[3], 0.0, 1.0))
            raw = b"".join(struct.pack("<5f", v.x(), v.y(), v.z(), u, w)
                           for v, u, w in quad)
            opacity = max(0.0, min(1.0, float(getattr(im, "opacity", 1.0))))
            self._program.setUniformValue1f(self._loc_opacity, opacity)
            # An OPAQUE image does write depth — pushed back by a polygon
            # offset larger than the faces' (1, 1), so what is drawn ON it
            # (lines, and faces traced over it) still wins, while what lies
            # BEHIND it stays hidden. Without depth, a prism pushed down
            # from a triangle traced on a photo painted its sides over the
            # photo from above the ground (a user's video, 25-09). A faded
            # image keeps writing none: the model behind must show through.
            opaque = opacity >= 0.999
            self._gl.glDepthMask(GL_TRUE if opaque else GL_FALSE)
            if opaque:
                self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
                self._gl.glPolygonOffset(4.0, 8.0)
            self._img_vbo.bind()
            self._img_vbo.allocate(raw, len(raw))
            self._img_vbo.release()
            vao.bind()
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
            tex.release(0)
            vao.release()
            if opaque:
                self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_use_tex, 0)

    def image_plane_at(self, screen_x: float, screen_y: float,
                       selectable_only: bool = False):
        """The topmost reference image under the cursor, or ``None``.

        Casts the pixel ray at each image's plane and keeps the hit whose
        ``(u, v)`` falls inside the rectangle, nearest first. Later images win
        ties, matching the order they are painted in.

        ``selectable_only`` is what separates the two callers. Picking honours
        the image's own lock; the work-plane inference does NOT — a locked
        scan is exactly the one you have finished aligning and now want to
        draw on, so it must keep offering its plane while refusing clicks.
        """
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return None
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        best, best_t = None, float("inf")
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            if selectable_only and (getattr(im, "locked", False)
                                    or not self.scene.entity_selectable(im)):
                continue
            n = im.normal()
            denom = QVector3D.dotProduct(n, direction)
            if abs(denom) < 1e-9:
                continue
            t = QVector3D.dotProduct(n, im.center() - origin) / denom
            if t < 0.0 or t > best_t:
                continue
            fu, fv = im.project(origin + direction * t)
            if im.contains_uv(fu, fv):
                best, best_t = im, t
        return best

    def pick_image_plane(self, screen_x: float, screen_y: float):
        """Selection entry point: like :meth:`image_plane_at` but skipping
        locked images, so a click on an aligned scan falls through to the
        geometry being drawn on it."""
        return self.image_plane_at(screen_x, screen_y, selectable_only=True)

    def image_in_front_of(self, face, screen_x: float, screen_y: float):
        """A selectable reference image under the cursor that lies strictly
        NEARER than ``face`` along the pixel ray, or ``None``. An image is
        an underlay — a face on its plane, or above it, still wins the
        click — but one behind it must not: with the top of a box hidden,
        its bottom took every click meant for the image lying on top
        (#426)."""
        image = self.pick_image_plane(screen_x, screen_y)
        if image is None or face is None:
            return None
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        verts = getattr(face, "vertices", None) or []
        if not verts:
            return None
        n = face.normal()
        denom = QVector3D.dotProduct(n, direction)
        if abs(denom) < 1e-9:
            return None
        t_face = QVector3D.dotProduct(n, verts[0] - origin) / denom
        ni = image.normal()
        di = QVector3D.dotProduct(ni, direction)
        if abs(di) < 1e-9:
            return None
        t_img = QVector3D.dotProduct(ni, image.center() - origin) / di
        if 0.0 <= t_img < t_face - max(1e-4, 1e-5 * abs(t_face)):
            return image
        return None

    def pick_locked_image_plane(self, screen_x: float, screen_y: float):
        """The right-click's last resort: a LOCKED image under the cursor
        (its layer still visible and unlocked). A locked image refuses
        clicks by design, but the context menu is the only door back to
        Unlock / Delete — the usual place to offer Unlock.
        Without this a locked scan could never be selected again (Marco,
        2026-09-14, the orthomosaic that arrives locked)."""
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return None
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        best, best_t = None, float("inf")
        for im in images:
            if not getattr(im, "locked", False):
                continue
            if not self.scene.entity_visible(im) or not self.scene.entity_selectable(im):
                continue
            n = im.normal()
            denom = QVector3D.dotProduct(n, direction)
            if abs(denom) < 1e-9:
                continue
            t = QVector3D.dotProduct(n, im.center() - origin) / denom
            if t < 0.0 or t > best_t:
                continue
            fu, fv = im.project(origin + direction * t)
            if im.contains_uv(fu, fv):
                best, best_t = im, t
        return best

    def _draw_image_outlines(self, painter: QPainter) -> None:
        """Border of each reference image: faint normally, selection orange
        when picked, so an image lying flat on the ground is still findable."""
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return
        pen = QPen(QColor(120, 140, 165), 1, Qt.DashLine)
        sel_pen = QPen(QColor(243, 115, 41), 2)      # selection orange
        selection = self.scene.selection
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            painter.setPen(sel_pen if im in selection else pen)
            for a, b in im.border_edges():
                seg = self._clip_segment_front(a, b)
                if seg is None:
                    continue
                pa = self._world_to_pixel(seg[0])
                pb = self._world_to_pixel(seg[1])
                if pa is not None and pb is not None:
                    painter.drawLine(QPointF(*pa), QPointF(*pb))

    def finish_image_placement(self) -> None:
        """Called by the Image tool once a picture is placed: drop back to
        Select, the classic behaviour after a one-shot placement."""
        win = self.window()
        if hasattr(win, "activate_select_tool"):
            win.activate_select_tool()
