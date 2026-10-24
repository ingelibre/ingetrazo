# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Geo-referenced content: base-map tiles, terrain, photo mesh, sky and the geo overlays."""
from __future__ import annotations

from array import array
from core.units import fmt_len as _fmt_len
from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import (QColor, QFont, QImage, QMatrix4x4, QPainter, QPen, QPolygonF,
                           QVector3D, QVector4D)
from PySide6.QtOpenGL import QOpenGLTexture
from core.i18n import tr
from views.viewport._support import (GL_LINES, GL_TRIANGLES, GL_DEPTH_TEST,
                                     GL_POLYGON_OFFSET_FILL, GL_FALSE, GL_TRUE,
                                     GL_MAX_TEXTURE_SIZE)


class GeoMixin:
    """Geo-referenced content: base-map tiles, terrain, photo mesh, sky and the geo overlays."""

    # ---- Base-map tiles (Track G) -------------------------------------------
    def _base_map_showing(self) -> bool:
        """True when a georeferenced base map is currently visible."""
        layer = getattr(self.scene, "tile_layer", None)
        return (layer is not None and getattr(layer, "visible", False)
                and getattr(self.scene, "georef", None) is not None)

    def _ensure_tile_fetcher(self):
        """Create the tile fetcher on first use (needs a running app)."""
        if self._tile_fetcher is None:
            from georef.tile_fetcher import TileFetcher
            self._tile_fetcher = TileFetcher(parent=self)
            self._tile_fetcher.tileReady.connect(self._on_tile_ready)
        return self._tile_fetcher

    def _on_tile_ready(self, source_id, x, y, z, image) -> None:
        """A downloaded tile arrived: stash its image and schedule a repaint."""
        layer = getattr(self.scene, "tile_layer", None)
        if (layer is not None and layer.source.id == source_id
                and z == layer.zoom):
            layer.images[(x, y, z)] = image
            self.tilesChanged.emit()
            self.update()

    def _disk_cached_tile(self, source, x, y, z):
        """Tile ``(x, y, z)`` of ``source`` from the on-disk cache, or None.
        The same cache the fetcher fills, read without the fetcher: safe
        inside paintGL, where the fetcher's network manager must not be
        created (#327)."""
        if z < 0 or z > source.max_zoom:
            return None
        if self._tile_fetcher is not None:
            cache = self._tile_fetcher.cache
        else:
            cache = getattr(self, "_tile_disk_cache", None)
            if cache is None:
                from georef.tiles import TileCache, default_cache_dir
                cache = self._tile_disk_cache = TileCache(default_cache_dir())
        data = cache.get(source.id, x, y, z)
        if data is None:
            return None
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QImage
        img = QImage()
        return img if img.loadFromData(QByteArray(data)) else None

    def _schedule_tile_requests(self) -> None:
        """Start missing tile requests after the current GL paint returns."""
        if self._tile_requests_scheduled:
            return
        self._tile_requests_scheduled = True
        QTimer.singleShot(0, self._request_missing_tiles)

    def _request_missing_tiles(self) -> None:
        """Fetch the current layer's missing images outside ``paintGL``.

        Cache hits are copied into the layer immediately and repaint once;
        network misses are delivered later by :meth:`_on_tile_ready`.
        Reading the current scene here also makes a callback queued just before
        a source/location change harmless.
        """
        self._tile_requests_scheduled = False
        layer = getattr(self.scene, "tile_layer", None)
        datum = getattr(self.scene, "georef", None)
        if layer is None or datum is None or not getattr(layer, "visible", False):
            return
        try:
            tiles = layer.flat_tiles(datum)
        except Exception:
            return
        fetcher = self._ensure_tile_fetcher()
        cached = False
        for x, y in tiles:
            key = (x, y, layer.zoom)
            if key in layer.images:
                continue
            image = fetcher.request(layer.source, x, y, layer.zoom)
            if image is not None:
                layer.images[key] = image
                cached = True
        if cached:
            self.update()

    #: Per-document caches keyed by ``id()`` of the document's groups,
    #: meshes and placements — the render/pick chunks and what hangs off
    #: them. Nothing but the document boundary makes them all stale at once.
    _DOCUMENT_CACHES = ("_group_chunks", "_inst_chunks", "_fp_memo",
                        "_proto_wrappers", "_proto_draw", "_faceme_cache",
                        "_proto_pts_store", "_container_obb", "_placement_frames",
                        "_pick_live",
                        # Also keyed by id(): a face-me's placed sprite, the
                        # nested-placement proxies and the arc midpoints per
                        # mesh. A group of the next document born at a dead
                        # one's address met its entry — the scale figure
                        # «transported» into an opened file (issue #75).
                        "_billboard_world", "_placement_proxies",
                        "_arc_mid_by_mesh")

    def reset_tiles(self) -> None:
        """Drop cached GL textures + pending images (source/datum changed)."""
        if self._tile_textures:
            # Destroying GL textures needs the context current — this runs from
            # the Tray, not paintGL.
            self.makeCurrent()
            try:
                for tex in self._tile_textures.values():
                    if tex is not None:
                        tex.destroy()
            finally:
                self.doneCurrent()
        self._tile_textures.clear()
        self._tile_geom = None       # capture patches / datum may have changed
        if self._tile_fetcher is not None:
            self._tile_fetcher.cancel_all()
        layer = getattr(self.scene, "tile_layer", None)
        if layer is not None:
            layer.images.clear()
        self.update()

    # Max NEW GL textures created per frame. Uploading hundreds at once (a big
    # capture) overwhelms Mesa and reads back as garbage (black/green tears at
    # the far edge); creating a few per frame spreads it — the map fills in over
    # a second and repaints itself until done.
    # P4: 6 uploads (each with mipmap generation, ~5-15 ms on the iGPU)
    # stacked into one frame was the ~100 ms hitch while zooming over the
    # base map. 2 per frame keeps every frame under the 33 ms gate; the
    # deferred-repaint loop below spreads the rest across frames.
    _TEX_PER_FRAME = 2

    def _tile_texture(self, layer, x, y):
        """GL texture for tile ``(x, y)`` of ``layer``, or ``None`` if not yet
        available (a download is kicked off and the frame repaints on arrival)."""
        z = layer.zoom
        key = (layer.source.id, x, y, z)
        if key in self._tile_textures:
            return self._tile_textures[key]
        img = layer.images.get((x, y, z))
        if img is None:
            # A tile already on disk is read now — a file, no network — so a
            # sheet frame or an export, drawn once, still gets every cached
            # tile. Only a DOWNLOAD waits: QtNetwork must not start (the
            # fetcher builds its network manager on first use) inside
            # paintGL. On Windows/AMD that crashed in ntdll while the GL
            # driver callback was active (#327). The queued callback runs
            # when this paint has returned.
            img = self._disk_cached_tile(layer.source, x, y, z)
            if img is None:
                self._schedule_tile_requests()
                return None
            layer.images[(x, y, z)] = img
        if self._tex_budget <= 0:
            self._tex_deferred = True     # too many this frame — next frame
            return None
        self._tex_budget -= 1
        tex = QOpenGLTexture(img)  # QImage is top-down; our UVs map north→v=0
        tex.setWrapMode(QOpenGLTexture.ClampToEdge)
        tex.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
        tex.setMagnificationFilter(QOpenGLTexture.Linear)
        self._tile_textures[key] = tex
        return tex

    def _terrain_showing(self) -> bool:
        t = getattr(self.scene, "terrain", None)
        return t is not None and getattr(t, "visible", False)

    def prefetch_tiles(self, source, tile_list, zoom) -> None:
        """Request the given tiles so their images populate ``tile_layer.images``
        (used to build the 3D terrain mosaic even when the flat map is hidden)."""
        layer = getattr(self.scene, "tile_layer", None)
        if layer is None:
            return
        fetcher = self._ensure_tile_fetcher()
        for (x, y) in tile_list:
            img = fetcher.request(source, x, y, zoom)
            if img is not None:
                layer.images[(x, y, zoom)] = img

    def upload_terrain(self, terrain) -> None:
        """Build the terrain VBO (pos+uv) and its mosaic texture from a
        :class:`~georef.terrain.TerrainObject`."""
        if terrain is None or not terrain.vertices or not terrain.triangles:
            self._terrain_count = 0
            return
        self.makeCurrent()
        try:
            raw = array("f")
            verts, uvs = terrain.vertices, terrain.uvs
            for (i, j, k) in terrain.triangles:
                for idx in (i, j, k):
                    v = verts[idx]
                    u, w = uvs[idx]
                    raw.extend([v.x(), v.y(), v.z(), u, w])
            data = raw.tobytes()
            self._terrain_vbo.bind()
            self._terrain_vbo.allocate(data, len(data))
            self._terrain_vbo.release()
            self._terrain_count = len(raw) // 5
            if self._terrain_texture is not None:
                self._terrain_texture.destroy()
                self._terrain_texture = None
            img = terrain.texture_image
            if img is not None and not img.isNull():
                self._terrain_texture = QOpenGLTexture(img)
                self._terrain_texture.setWrapMode(QOpenGLTexture.ClampToEdge)
                self._terrain_texture.setMinificationFilter(
                    QOpenGLTexture.LinearMipMapLinear)
                self._terrain_texture.setMagnificationFilter(QOpenGLTexture.Linear)
        finally:
            self.doneCurrent()
        self.update()

    def _render_terrain(self) -> None:
        if not self._terrain_showing() or self._terrain_count == 0:
            return
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        self._terrain_vao.bind()
        if self._terrain_texture is not None:
            self._program.setUniformValue(self._loc_use_tex, 1)
            self._terrain_texture.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._terrain_count)
            self._terrain_texture.release(0)
            self._program.setUniformValue(self._loc_use_tex, 0)
        else:
            self._set_color(0.55, 0.60, 0.52, 1.0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._terrain_count)
        self._terrain_vao.release()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    # ---- Photogrammetric survey (Track G, G6) ------------------------------

    def _photo_showing(self) -> bool:
        m = getattr(self.scene, "photo_mesh", None)
        if m is None or not getattr(m, "visible", False) or self._photo_count == 0:
            return False
        # Its own switch AND its layer, the way a Group works: an entity can be
        # hidden individually or by the layer it carries.
        return self.scene.entity_visible(m)

    def max_texture_size(self) -> int:
        """The driver's ``GL_MAX_TEXTURE_SIZE`` — the hard ceiling for an atlas.

        Queried rather than assumed: ODM routinely emits 24576px sheets, which
        no current GPU accepts (this machine's Radeon 780M reports 16384), and
        an oversized upload fails outright instead of degrading.
        """
        if self._gl is None:
            return 4096                      # conservative until GL is up
        self.makeCurrent()
        try:
            value = self._gl.glGetIntegerv(GL_MAX_TEXTURE_SIZE)
        finally:
            self.doneCurrent()
        try:
            value = int(value[0] if hasattr(value, "__len__") else value)
        except (TypeError, ValueError):
            return 4096
        return value if value > 0 else 4096

    def upload_photo_mesh(self, mesh, images=None) -> None:
        """Upload a :class:`~georef.photomesh.PhotoMesh` and its atlases.

        ``images`` maps a material index → already-loaded ``QImage`` (the reader
        is slow enough that the caller does it off the GUI thread); anything
        missing simply draws untextured rather than blocking here.
        """
        if mesh is None or mesh.triangle_count == 0:
            self.release_photo_textures()
            self._photo_count = 0
            self.update()
            return

        import numpy as np

        self.makeCurrent()
        try:
            # Inside makeCurrent: destroying a QOpenGLTexture without a current
            # context leaks it and prints "Texture has not been destroyed".
            self._release_photo_textures_unsafe()
            # Expand indexed triangles to the flat pos+uv layout the shared
            # VAO expects. Vectorised: the terrain's per-vertex Python loop is
            # fine for a 180x180 grid and hopeless for 362k triangles.
            tri = mesh.triangles
            pos = mesh.vertices[tri]                     # (M, 3, 3)
            uv = mesh.uvs[tri]                           # (M, 3, 2)
            data = np.concatenate([pos, uv], axis=2).astype(np.float32).tobytes()
            self._photo_vbo.bind()
            self._photo_vbo.allocate(data, len(data))
            self._photo_vbo.release()
            self._photo_count = int(tri.shape[0]) * 3

            # Materials are contiguous triangle runs, so each becomes one
            # glDrawArrays over its slice of the same buffer.
            images = images or {}
            for index, material in enumerate(mesh.materials):
                texture = None
                image = images.get(index)
                if image is not None and not image.isNull():
                    texture = QOpenGLTexture(image)
                    texture.setWrapMode(QOpenGLTexture.ClampToEdge)
                    texture.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
                    texture.setMagnificationFilter(QOpenGLTexture.Linear)
                self._photo_textures.append(texture)
                self._photo_ranges.append(
                    (material.start * 3, material.count * 3, texture))
        finally:
            self.doneCurrent()
        self.update()

    def release_photo_textures(self) -> None:
        """Drop the survey's atlases (closing a document, or importing another).

        Half a gigabyte of VRAM is worth freeing eagerly rather than waiting for
        Qt to notice at teardown — when there is no current context left and the
        textures leak with a warning instead.
        """
        if not self._photo_textures:
            self._photo_ranges = []
            return
        self.makeCurrent()
        try:
            self._release_photo_textures_unsafe()
        finally:
            self.doneCurrent()

    def _release_photo_textures_unsafe(self) -> None:
        """Destroy the atlases. The caller must hold a current GL context."""
        for texture in self._photo_textures:
            if texture is not None:
                texture.destroy()
        self._photo_textures = []
        self._photo_ranges = []

    def _render_photo_mesh(self) -> None:
        if not self._photo_showing():
            return
        # Same polygon offset as the terrain: the survey is the ground, and
        # traced lines drawn on it must win the depth fight.
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        self._photo_vao.bind()
        for first, count, texture in self._photo_ranges:
            if count <= 0:
                continue
            if texture is not None:
                self._program.setUniformValue(self._loc_use_tex, 1)
                texture.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, first, count)
                texture.release(0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            else:
                # Untextured run (atlas missing or still loading): neutral clay
                # so it reads as "there is geometry here", not as a hole.
                self._set_color(0.62, 0.60, 0.56, 1.0)
                self._gl.glDrawArrays(GL_TRIANGLES, first, count)
        self._photo_vao.release()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    def _ensure_tile_geometry(self, layer, datum):
        """Build the base-map tile quad VBO **once** for the current capture
        patches (not per frame), returning ``[(x, y, vert_start), ...]``. The
        capture is static, so a strip of many tiles still draws fast — each
        frame just binds textures and draws slices; no per-tile re-allocation."""
        key = (id(datum), getattr(datum, "north", 0.0), tuple(layer.patches),
               layer.zoom, layer.source.id)
        cache = getattr(self, "_tile_geom", None)
        if cache is not None and cache[0] == key:
            return cache[1]
        raw = array("f")
        runs = []
        for (x, y) in layer.flat_tiles(datum):
            start = len(raw) // 5
            for pos, (u, v) in layer.quad_local(datum, x, y):
                raw.extend([pos.x(), pos.y(), pos.z(), u, v])
            runs.append((x, y, start))
        self._tile_quad_vbo.bind()
        self._tile_quad_vbo.allocate(raw.tobytes(), len(raw) * 4 or 4)
        self._tile_quad_vbo.release()
        self._tile_geom = (key, runs)
        return runs

    # Sky (top) and ground (bottom) backdrop colours — subtle two-tone.
    _SKY_RGB = (0.925, 0.935, 0.945)
    _GROUND_RGB = (0.815, 0.820, 0.815)

    def _horizon_ndc_y(self, mvp) -> float:
        """Screen-space NDC y of the horizon (the ground plane at infinity),
        from the camera orientation. Returns a value that may exceed ±1 when the
        horizon is off-screen (looking straight down = all ground)."""
        eye = self.camera.eye()
        fwd = self.camera.target - eye
        # Horizontal component of the view direction → its vanishing point.
        dh = QVector3D(fwd.x(), fwd.y(), 0.0)
        if dh.length() < 1e-5:
            # Looking straight down/up: no horizon on screen.
            return 2.0 if fwd.z() < 0 else -2.0
        dh = dh.normalized()
        # A point very far along the horizontal heading, at eye height: as the
        # distance → ∞ it converges to the horizon, so it stays put on zoom.
        far = eye + dh * 1.0e6
        clip = mvp.map(QVector4D(far.x(), far.y(), far.z(), 1.0))
        if abs(clip.w()) < 1e-9:
            return 2.0 if fwd.z() < 0 else -2.0
        return clip.y() / clip.w()

    #: NDC span over which each half of the backdrop completes its ramp.
    _SKY_GRAD_SPAN = 1.4
    _GROUND_GRAD_SPAN = 0.9

    @staticmethod
    def _sky_gradient(sky_rgb, ground_rgb, hy):
        """Corner colours of the backdrop gradient: the style's sky tone at
        the zenith and ground tone underfoot, both hazed toward white at the
        horizon (atmosphere — the one-colour input stays the one the user
        picked). Computed against the UNCLAMPED horizon ``hy``, so a pitched
        camera sees the right slice of the ramp (all zenith when looking up,
        all ground when looking down). Returns ``(sky_bottom, sky_top,
        ground_top, ground_bottom, horizon_line)``; the ramps are linear in
        NDC y, so colouring only the quad corners is exact."""
        def mix(a, b, t):
            return (a[0] + (b[0] - a[0]) * t,
                    a[1] + (b[1] - a[1]) * t,
                    a[2] + (b[2] - a[2]) * t)

        white = (1.0, 1.0, 1.0)
        sky_h = mix(sky_rgb, white, 0.55)
        gnd_h = mix(ground_rgb, white, 0.30)

        def sky_at(y):
            t = min(1.0, max(0.0, (y - hy) / GeoMixin._SKY_GRAD_SPAN))
            return mix(sky_h, sky_rgb, t)

        def gnd_at(y):
            t = min(1.0, max(0.0, (hy - y) / GeoMixin._GROUND_GRAD_SPAN))
            return mix(gnd_h, ground_rgb, t)

        y0 = max(-1.0, min(1.0, hy))
        line = mix(mix(sky_h, gnd_h, 0.5), (0.0, 0.0, 0.0), 0.12)
        return sky_at(y0), sky_at(1.0), gnd_at(y0), gnd_at(-1.0), line

    def _draw_sky(self, mvp) -> None:
        """Sky above the horizon and ground below, each a vertical gradient
        (style tones hazed toward the horizon — see ``_sky_gradient``), with
        a subtle horizon line where they meet. Per-vertex colours; GL
        interpolates per pixel. The class constants ``_SKY_RGB`` /
        ``_GROUND_RGB`` are the historical defaults, kept as fallbacks."""
        style = getattr(self, "_frame_style", None)
        sky_rgb = tuple(getattr(style, "sky_color", None)
                        or self._SKY_RGB)[:3]
        ground_rgb = tuple(getattr(style, "ground_color", None)
                           or self._GROUND_RGB)[:3]
        hy_raw = self._horizon_ndc_y(mvp)
        hy = max(-1.0, min(1.0, hy_raw))
        c_sky0, c_sky1, c_gnd0, c_gnd1, c_line = self._sky_gradient(
            sky_rgb, ground_rgb, hy_raw)
        self._program.setUniformValue(self._loc_mvp, QMatrix4x4())  # identity/NDC
        self._gl.glDisable(GL_DEPTH_TEST)
        self._gl.glDepthMask(GL_FALSE)

        def gquad(y0, y1, c0, c1):
            data = array("f", [-1, y0, 0, *c0, 1, y0, 0, *c0, 1, y1, 0, *c1,
                               -1, y0, 0, *c0, 1, y1, 0, *c1, -1, y1, 0, *c1])
            self._sky_grad_vbo.bind()
            self._sky_grad_vbo.allocate(data.tobytes(), len(data) * 4)
            self._sky_grad_vbo.release()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)

        self._sky_grad_vao.bind()
        self._program.setUniformValue(self._loc_use_vcolor, 1)
        if hy < 1.0:
            gquad(hy, 1.0, c_sky0, c_sky1)
        if hy > -1.0:
            gquad(-1.0, hy, c_gnd1, c_gnd0)
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._sky_grad_vao.release()
        # A subtle horizon line where sky meets ground, in a tone
        # derived from the two haze colours so custom skies keep it legible.
        if -1.0 < hy < 1.0:
            line = array("f", [-1.0, hy, 0.0, 1.0, hy, 0.0])
            self._sky_vao.bind()
            self._sky_vbo.bind()
            self._sky_vbo.allocate(line.tobytes(), len(line) * 4)
            self._sky_vbo.release()
            self._set_color(*c_line, 1.0)
            self._gl.glDrawArrays(GL_LINES, 0, 2)
            self._sky_vao.release()
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthMask(GL_TRUE)

    def _render_tiles(self) -> None:
        if self._terrain_showing():
            return  # the 3D terrain replaces the flat map
        layer = getattr(self.scene, "tile_layer", None)
        datum = getattr(self.scene, "georef", None)
        if layer is None or datum is None or not getattr(layer, "visible", False):
            return
        try:
            runs = self._ensure_tile_geometry(layer, datum)
        except Exception:
            return
        if not runs:
            return
        # Budget new texture uploads this frame (see _tile_texture).
        self._tex_budget = self._TEX_PER_FRAME
        self._tex_deferred = False
        self._program.setUniformValue(self._loc_use_tex, 1)
        # A faded map (opacity < 1) blends over the background so the
        # model and its lines read on top of the imagery.
        opacity = max(0.0, min(1.0, float(getattr(layer, "opacity", 1.0))))
        self._program.setUniformValue1f(self._loc_opacity, opacity)
        self._gl.glDepthMask(GL_FALSE)
        self._tile_quad_vao.bind()
        for (x, y, start) in runs:
            tex = self._tile_texture(layer, x, y)
            if tex is None:
                continue
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, start, 6)
            tex.release(0)
        self._tile_quad_vao.release()
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._program.setUniformValue(self._loc_use_tex, 0)
        if self._tex_deferred:            # more tiles to upload — schedule a frame
            self.update()

    def _draw_geo_surfaces(self, painter: QPainter) -> None:
        """Draw terrain-surface fills as shaded, back-to-front triangles so the
        relief reads in 3D (Track G). Semi-transparent, so the base map shows."""
        paths = getattr(self.scene, "geo_paths", None)
        if not paths:
            return
        eye = self.camera.eye()
        light = QVector3D(0.3, 0.4, 0.85)
        light = light.normalized()
        for path in paths:
            tris = getattr(path, "_surface_tris", None)
            if not tris:
                continue
            flat = getattr(path, "surface", None) == "flat"
            # Painter's algorithm: far triangles first.
            ordered = sorted(
                tris, key=lambda t: -((t[0] + t[1] + t[2]) - eye * 3.0).lengthSquared())
            painter.setPen(Qt.NoPen)
            for v0, v1, v2 in ordered:
                p0 = self._world_to_pixel(v0)
                p1 = self._world_to_pixel(v1)
                p2 = self._world_to_pixel(v2)
                if p0 is None or p1 is None or p2 is None:
                    continue
                # Flat shading from the face normal (relief legibility).
                n = QVector3D.crossProduct(v1 - v0, v2 - v0)
                if n.length() > 1e-9:
                    n = n.normalized()
                shade = 0.55 + 0.45 * max(0.0, abs(QVector3D.dotProduct(n, light)))
                if flat:
                    col = QColor(int(90 * shade), int(120 * shade), int(200 * shade), 150)
                else:
                    col = QColor(int(120 * shade), int(160 * shade), int(90 * shade), 150)
                painter.setBrush(col)
                painter.drawPolygon(QPolygonF([QPointF(*p0), QPointF(*p1), QPointF(*p2)]))
            painter.setBrush(Qt.NoBrush)

    def ground_height(self, x: float, y: float) -> float | None:
        """Ground elevation at a plan position, or ``None`` where none is known.

        One place to ask, so the survey-beats-DEM precedence lives here instead
        of being re-decided by every caller (drape, the elevation readout, the
        profile sampler chooser).
        """
        survey = getattr(self.scene, "photo_mesh", None)
        if survey is not None and getattr(survey, "visible", False):
            z = survey.height_at(x, y)
            if z is not None:
                return z
        t = getattr(self.scene, "terrain", None)
        if t is not None and getattr(t, "visible", False):
            return t.height_at(x, y)
        return None

    def _emit_coordinate(self, ev) -> None:
        """Publish the UTM coordinate under the cursor for the status bar.

        Rides the coalesced hover rather than every mouse event: the readout is
        for reading, and 16 updates a second is already more than an eye can
        follow. Silent without a datum — local scene metres are not a
        coordinate anybody can use.
        """
        datum = getattr(self.scene, "georef", None)
        if datum is None:
            if self._last_coordinate:
                self._last_coordinate = ""
                self.coordinateChanged.emit("")
            return
        p = ev.position().toPoint()
        world = self._world_from_pixel(p.x(), p.y())
        if world is None:
            return
        east, north, _ = datum.local_to_utm(world)
        z = self.ground_elevation(world.x(), world.y())
        # Compact on the bar — a decimetre is the pointer's own precision on
        # a site plan, and the zone does not change under the mouse — and in
        # full on hover (Marco, 23-09: the bar had no room for the hint).
        text = f"E {east:.1f}  N {north:.1f}"
        full = (f"E {east:,.2f}  N {north:,.2f}  "
                f"{datum.zone}{datum.hemisphere}")
        if z is not None:
            text += f"  ·  {z:.1f} m"
            full += f"  ·  {z:,.2f} m"
        self._last_coordinate_full = full
        if text != self._last_coordinate:
            self._last_coordinate = text
            self.coordinateChanged.emit(text)

    def ground_elevation(self, x: float, y: float) -> float | None:
        """Ground elevation as a REAL altitude, not a local offset.

        ``ground_height`` answers in scene metres, which is what geometry
        needs; this adds the datum's altitude back so what reaches the user is
        the number they would read off a level — 1783.19, not 37.19. Anything
        shown to a person goes through here.
        """
        z = self.ground_height(x, y)
        if z is None:
            return None
        datum = getattr(self.scene, "georef", None)
        return z + float(getattr(datum, "alt", 0.0) or 0.0)

    def vertical_reference(self) -> str:
        """Token naming what the scene's elevations are measured against, for
        labelling. See :mod:`georef.photomesh` for the meanings."""
        from georef.photomesh import VERTICAL_DEM, VERTICAL_LOCAL, VERTICAL_ODM
        survey = getattr(self.scene, "photo_mesh", None)
        if survey is not None and getattr(survey, "visible", False):
            return getattr(survey, "vertical_reference", VERTICAL_ODM)
        t = getattr(self.scene, "terrain", None)
        if t is not None and getattr(t, "visible", False):
            return VERTICAL_DEM
        return VERTICAL_LOCAL

    def has_ground_surface(self) -> bool:
        """Whether anything is showing that a trace could be draped onto."""
        for name in ("photo_mesh", "terrain"):
            obj = getattr(self.scene, name, None)
            if obj is not None and getattr(obj, "visible", False):
                return True
        return False

    def drape(self, v: QVector3D) -> QVector3D:
        """Lift a Z=0 georef point onto the ground (its relief height) when a
        ground surface is showing, so routes/markers sit on it instead of
        floating at the Z=0 reference plane. A no-op otherwise.

        The **survey wins over the DEM terrain** where both are present: it is
        the user's own flight at centimetres per pixel against 30 m global
        cells, so a trace should follow what was actually captured.
        """
        z = self.ground_height(v.x(), v.y())
        return QVector3D(v.x(), v.y(), z) if z is not None else v

    def _draw_geo_points(self, painter: QPainter) -> None:
        """Draw imported survey points (GPS / total station): a small cross
        marker with the point's name — the surveyed skeleton the user traces
        over. Reference-only; they carry their own elevation (no draping)."""
        points = getattr(self.scene, "geo_points", None)
        if not points:
            return
        ink = QColor(206, 66, 87)               # survey red — distinct from
        painter.setPen(QPen(ink, 1.6))          # cyan paths / orange selection
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for gp in points:
            q = self._world_to_pixel(gp.position)
            if q is None:
                continue
            x, y = q
            painter.setPen(QPen(ink, 1.6))
            painter.drawLine(QPointF(x - 5, y), QPointF(x + 5, y))
            painter.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))
            if gp.name:
                painter.setPen(QColor(120, 34, 48))
                painter.drawText(QPointF(x + 7, y - 4), gp.name)

    def _draw_geo_paths(self, painter: QPainter) -> None:
        """Draw committed georef paths (roads / boundaries): a coloured polyline
        with node handles. Selected paths and the hovered node highlight."""
        paths = getattr(self.scene, "geo_paths", None)
        if not paths:
            return
        base_ink = QColor(0, 190, 210)          # cyan — reads over terrain
        sel_ink = QColor(243, 115, 41)          # selection orange
        selection = self.scene.selection
        hover_node = getattr(self, "_hover_geo_node", None)
        for path in paths:
            ink = sel_ink if path in selection else base_ink
            pix = [self._world_to_pixel(self.drape(p)) for p in path.points]
            painter.setPen(QPen(ink, 2.5))
            for a, b in zip(pix, pix[1:]):
                if a is not None and b is not None:
                    painter.drawLine(QPointF(*a), QPointF(*b))
            if path.closed and len(pix) > 2 and pix[0] and pix[-1]:
                painter.drawLine(QPointF(*pix[-1]), QPointF(*pix[0]))
            # Node handles.
            painter.setBrush(ink)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            for i, q in enumerate(pix):
                if q is None:
                    continue
                r = 5.0 if (hover_node == (path, i)) else 3.5
                painter.drawEllipse(QPointF(*q), r, r)
            painter.setBrush(Qt.NoBrush)
            # Area + perimeter label at the centroid of a selected polygon.
            if path in selection and path.closed and len(path.points) >= 3:
                self._draw_geo_path_label(painter, path)

    def _draw_geo_path_label(self, painter: QPainter, path) -> None:
        n = len(path.points)
        cx = sum(p.x() for p in path.points) / n
        cy = sum(p.y() for p in path.points) / n
        cz = sum(p.z() for p in path.points) / n
        q = self._world_to_pixel(self.drape(QVector3D(cx, cy, cz)))
        if q is None:
            return
        area = path.area()
        text = f"{tr('Area')}: {area:.1f} m²  ({area / 10000:.3f} ha)\n" \
               f"{tr('Perimeter')}: {_fmt_len(path.perimeter())}"
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        lines = text.split("\n")
        tw = max(fm.horizontalAdvance(ln) for ln in lines)
        th = fm.height() * len(lines)
        x, y = q[0] - tw / 2, q[1] - th / 2
        painter.fillRect(int(x) - 5, int(y) - 3, tw + 10, th + 6,
                         QColor(20, 24, 30, 190))
        painter.setPen(QColor(255, 255, 255))
        for i, ln in enumerate(lines):
            painter.drawText(QPointF(x, y + fm.ascent() + i * fm.height()), ln)
