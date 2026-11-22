# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Image planes: drawing, outlines and picking of placed images."""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QVector3D, QVector4D
from views.viewport._support import (GL_TRIANGLES, GL_DEPTH_TEST, GL_BLEND,
                                     GL_POLYGON_OFFSET_FILL, GL_FALSE, GL_TRUE,
                                     _scene_blend)


class ImagePlaneMixin:
    """Image planes: drawing, outlines and picking of placed images."""

    # ---- Camera ▸ Camera from Photo -----------------------------------------
    def enter_photo(self, view) -> bool:
        """Show the scene ``view``'s photo behind the model, the camera put
        where the photo was taken (``core.photo_match``). ``None``, or a
        scene without a photo, leaves the photo. Whether the photo shows."""
        if view is None or getattr(view, "photo", None) is None:
            self.leave_photo(restore=False)
            return False
        if self.photo_view is None:
            self._photo_prev_frame = getattr(self.camera, "frame_aspect",
                                             None)
        self.photo_view = view
        self.apply_photo_camera()
        self.update()
        return True

    def apply_photo_camera(self):
        """Put the camera where the shown photo's lines say, for this
        view's size. The solution, or the ``CalibrationError`` that stopped
        it (the camera then stays as it was)."""
        from core import photo_match as PM
        view = self.photo_view
        if view is None:
            return None
        pm = view.photo
        try:
            sol = PM.solve_match(pm)
        except PM.CalibrationError as err:
            result = err
        else:
            PM.apply_to_camera(sol, pm.aspect, self.camera,
                               max(self.width(), 1), max(self.height(), 1))
            result = sol
        self._photo_sig = PM.camera_signature(self.camera)
        self._photo_size = (self.width(), self.height())
        self._photo_state = pm.to_dict()
        return result

    def leave_photo(self, restore: bool = True) -> None:
        """The photo goes. ``restore``: the camera moved away from it (an
        orbit...), and the frame the photo put on it comes off again; a
        scene shown next brings its own lens instead."""
        view = self.photo_view
        if view is None:
            return
        self.photo_view = None
        self._photo_sig = None
        cam = self.camera
        frame = getattr(cam, "frame_aspect", None)
        if (restore and view.photo is not None and frame is not None
                and abs(frame - view.photo.aspect) < 1e-9):
            cam.frame_aspect = self._photo_prev_frame
        hook = getattr(self.active_tool, "on_photo_left", None)
        if callable(hook):
            hook(self)
        self.update()

    def _check_photo(self) -> None:
        """Every frame: a camera that moved (orbit, pan, zoom, another
        view) leaves the photo; a new size of the view, or lines changed
        by an undo, put the camera back on the photo."""
        view = self.photo_view
        if view is None or self._export_size is not None:
            return
        if view.photo is None or view not in getattr(self.scene,
                                                     "saved_views", ()):
            self.leave_photo(restore=False)
            return
        from core.photo_match import camera_signature
        if camera_signature(self.camera) != self._photo_sig:
            self.leave_photo()
            return
        if ((self.width(), self.height()) != self._photo_size
                or view.photo.to_dict() != self._photo_state):
            self.apply_photo_camera()

    def _draw_photo_backdrop(self, mvp) -> None:
        """The photo inside the camera's frame, behind everything: no depth
        test, no depth written, at its true tones."""
        import struct
        from core.camera import frame_rect
        pm = self.photo_view.photo
        tex = self._get_texture(pm.path) if pm.path else None
        if tex is None:
            return
        W, H = float(max(self.width(), 1)), float(max(self.height(), 1))
        rect = frame_rect(W, H, pm.aspect)
        inv, ok = mvp.inverted()
        if rect is None or not ok:
            return
        x, y, w, h = rect

        def corner(px, py):
            p = inv.map(QVector4D(2.0 * px / W - 1.0, 1.0 - 2.0 * py / H,
                                  0.0, 1.0))
            return QVector3D(p.x() / p.w(), p.y() / p.w(), p.z() / p.w())
        bl, br = corner(x, y + h), corner(x + w, y + h)
        top_r, top_l = corner(x + w, y), corner(x, y)
        # _get_texture uploads the image bottom-up: v = 0 at its foot.
        quad = ((bl, 0.0, 0.0), (br, 1.0, 0.0), (top_r, 1.0, 1.0),
                (bl, 0.0, 0.0), (top_r, 1.0, 1.0), (top_l, 0.0, 1.0))
        raw = b"".join(struct.pack("<5f", v.x(), v.y(), v.z(), u, t)
                       for v, u, t in quad)
        vao = getattr(self, "_img_vao", None)
        if vao is None:
            self._img_vao, self._img_vbo = self._create_dynamic_uv()
            vao = self._img_vao
        prog = self._program
        prog.setUniformValue(self._loc_use_tex, 1)
        prog.setUniformValue(self._loc_use_vcolor, 0)
        prog.setUniformValue1f(self._loc_shade, 1.0)
        prog.setUniformValue1f(self._loc_opacity, 1.0)
        prog.setUniformValue1f(self._loc_fade, 0.0)
        prog.setUniformValue(self._loc_hard_cutout, 0)
        self._gl.glDisable(GL_DEPTH_TEST)
        self._gl.glDepthMask(GL_FALSE)
        self._img_vbo.bind()
        self._img_vbo.allocate(raw, len(raw))
        self._img_vbo.release()
        vao.bind()
        tex.bind(0)
        self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
        tex.release(0)
        vao.release()
        self._gl.glDepthMask(GL_TRUE)
        self._gl.glEnable(GL_DEPTH_TEST)
        prog.setUniformValue(self._loc_use_tex, 0)

    def _draw_photo_in_front(self, painter) -> None:
        """The shown photo OVER the model, in the camera's frame: at its
        opacity when set in front, whole when the model is hidden."""
        view = self.photo_view
        pm = getattr(view, "photo", None)
        opacity = pm.overlay_opacity() if pm is not None else None
        if opacity is None or not pm.path:
            return
        from core.camera import frame_rect
        rect = frame_rect(max(self.width(), 1), max(self.height(), 1),
                          pm.aspect)
        if rect is None:
            return
        x, y, w, h = rect
        key = (pm.path, int(round(w)), int(round(h)))
        cached = getattr(self, "_photo_front_pix", None)
        if cached is None or cached[0] != key:
            from PySide6.QtGui import QPixmap
            pix = QPixmap(pm.path)
            if pix.isNull():
                return
            pix = pix.scaled(key[1], key[2], Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation)
            cached = self._photo_front_pix = (key, pix)
        painter.save()
        painter.setOpacity(opacity)
        painter.drawPixmap(QRectF(x, y, w, h), cached[1],
                           QRectF(0, 0, cached[1].width(),
                                  cached[1].height()))
        painter.restore()

    def _draw_image_planes(self) -> None:
        """Reference images, as textured quads under the model.

        Depth test on. An opaque image writes depth pushed back by a polygon
        offset, so a line or face drawn exactly ON it still wins the depth
        test (tracing works, no z-fighting) and whatever lies behind it stays
        hidden; a faded image writes none, so the model shows through.

        Shading is pinned to 1.0: a reference scan has to read at its true
        tones, not dimmed by the face lighting.
        """
        placed = list(self._placed_image_planes())
        if not placed:
            return
        import struct
        vao = getattr(self, "_img_vao", None)
        if vao is None:
            self._img_vao, self._img_vbo = self._create_dynamic_uv()
            vao = self._img_vao
        drawn = []
        for im, matrix, _owner in placed:
            tex = self._get_texture(im.path)
            if tex is None:
                continue
            rest = self._edit_rest_fade(_owner if _owner is not im else None)
            if rest is not None:
                drawn.append((im, tex, matrix, rest))
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
        _scene_blend(self._gl)
        for im, tex, matrix, rest in drawn:
            self._program.setUniformValue1f(self._loc_fade, rest)
            c = im.corners()
            if matrix is not None:
                c = [matrix.map(point) for point in c]
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
        self._program.setUniformValue1f(self._loc_fade, 0.0)
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_use_tex, 0)

    def _placed_image_planes(self):
        """Yield ``(image, matrix, owner)`` for every visible photo.

        Loose reference images have no matrix.  Images held by groups and
        components remain the same first-class entity, placed through the
        container just like its local mesh.  This list is deliberately
        independent of ``Style.face_mode``: a photo is not a face texture.
        """
        for image in getattr(self.scene, "image_planes", None) or ():
            if self.scene.entity_visible(image):
                yield image, None, image
        # The matrix is read live: a groups preview moves the proxies
        # without a version bump.
        for group, image, owner in ImagePlaneMixin._grouped_image_rows(self):
            yield image, getattr(group, "xform", None), owner

    def _grouped_image_rows(self):
        """``(placement, image, owner)`` for every visible photo held by a
        group, memoised per scene version and placements epoch.

        Walking every placement for its ``images`` ran three times a frame
        (draw, outlines, snap): ~2 ms of each orbit or zoom frame on a
        model of 3 400 groups without a single grouped photo, and ~40 ms
        on the first frame after an undo (Marco's plaza, 20-11). What the
        walk reads — the placements, their ``hidden`` and layer, the
        images a group holds and their own visibility — only changes
        through a command (a version bump) or a switch the epoch carries."""
        # Most models hold no photo in any group: once a walk has found
        # none, nothing is asked of the placements (their expansion, their
        # epoch: ~0.1 ms, three times a frame) until the scene's version or
        # the open group changes — a photo only comes into a group through
        # a command. Their visibility does not matter to "none at all".
        sc = self.scene
        none_key = (getattr(sc, "version", None), id(sc.groups),
                    len(sc.groups), id(getattr(sc, "edit_group", None)))
        if getattr(self, "_grouped_images_none", None) == none_key:
            return ()
        placements = self._placements()
        epoch_of = getattr(self, "_placements_epoch", None)
        key = (getattr(self.scene, "version", None),
               epoch_of() if callable(epoch_of) else None,
               len(placements))
        memo = getattr(self, "_grouped_images_memo", None)
        if memo is not None and memo[0] is placements and memo[1] == key:
            return memo[2]
        rows = []
        held = False
        for group in placements:
            images = getattr(group, "images", None) or ()
            if not images:
                continue
            held = True
            if not self.scene.entity_visible(group):
                continue
            for image in images:
                if self.scene.entity_visible(image):
                    rows.append((group, image, self._owner_of(group)))
        self._grouped_images_memo = (placements, key, rows)
        self._grouped_images_none = None if held else none_key
        return rows
    def _edit_rest_fade(self, group):
        """How a reference image (``group=None``) or a face-me figure is
        drawn while a group is open: the fade to apply, or ``None`` to skip
        it. These passes bypass the buffers that carry the edit split, so
        the people and images kept their colours on a grey model."""
        if self.scene.edit_group is None:
            return 0.0
        if group is not None and not self._draws_in_edit_context(group):
            return 0.0
        if self._edit_rest_mode == "hide":
            return None
        return self.edit_rest_fade if self._edit_rest_mode == "fade" else 0.0

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
        images = [(image, None) for image in
                  (getattr(self.scene, "image_planes", None) or ())]
        if not selectable_only:
            images.extend((image, matrix)
                          for image, matrix, owner in self._placed_image_planes()
                          if owner is not image)
        if not images:
            return None
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        best, best_t = None, float("inf")
        for im, matrix in images:
            if not self.scene.entity_visible(im):
                continue
            if selectable_only and (getattr(im, "locked", False)
                                    or not self.scene.entity_selectable(im)):
                continue
            placed = im.transformed(matrix) if matrix is not None else im
            n = placed.normal()
            denom = QVector3D.dotProduct(n, direction)
            if abs(denom) < 1e-9:
                continue
            t = QVector3D.dotProduct(n, placed.center() - origin) / denom
            if t < 0.0 or t > best_t:
                continue
            fu, fv = placed.project(origin + direction * t)
            if placed.contains_uv(fu, fv):
                best, best_t = placed, t
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
        """Border of a reference image, only while it is selected: in the
        selection colour, or the locked one for a locked image. The faint
        dashed rectangle every image used to show runs past the picture
        over its transparent corners — round a cut-out ornament it drew a
        box in mid-air and the model did not read clean (Marco, 21-11, the
        cow on the arch; a locked scan's dashes across the sky before, playa
        Yanque, 2026-10-27). The picture itself still takes the click."""
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return
        sel_pen = QPen(QColor.fromRgbF(*self._modeling_color("selected")), 2)
        selection = self.scene.selection
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            if im not in selection:
                continue
            if getattr(im, "locked", False):
                painter.setPen(QPen(QColor.fromRgbF(*self._modeling_color("locked")), 2))
            else:
                painter.setPen(sel_pen)
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
