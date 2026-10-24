# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Screen-depth occlusion for the overlay's annotations and the snap."""
from __future__ import annotations

from PySide6.QtGui import QVector3D, QVector4D
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from views.viewport._support import (_active_cut, GL_FLOAT, GL_DEPTH_BUFFER_BIT,
                                     GL_READ_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_NEAREST,
                                     _occlusion_native)


class OcclusionMixin:
    """Screen-depth occlusion for the overlay's annotations and the snap."""

    # ---- Screen-depth occlusion for the overlay's annotations ---------------
    def _annotations_need_depth(self) -> bool:
        if self._effective_style().face_mode in ("xray", "wireframe"):
            return False
        sc = self.scene
        return bool(getattr(sc, "dimensions", None)
                    or getattr(sc, "text_labels", None))

    def _capture_depth(self, w: int, h: int) -> None:
        """Copy the frame's depth out of the (multisampled) scene FBO into a
        single-sample one and read it back once. The overlay then answers
        «is this point hidden?» with a lookup instead of a ray cast against
        the whole model: a house from a 2018 .skp with 25 dimensions spent
        2.8 s of every frame casting 1350 rays against 284 000 triangles
        (Juan José Noriega's files, 26-09-2026); the read-back is ~8 ms."""
        try:
            import numpy as np
            from PySide6.QtOpenGL import (QOpenGLFramebufferObject,
                                          QOpenGLFramebufferObjectFormat)
            dfbo = getattr(self, "_depth_fbo", None)
            if dfbo is None or (dfbo.width(), dfbo.height()) != (w, h):
                fmt = QOpenGLFramebufferObjectFormat()
                fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
                fmt.setSamples(0)
                dfbo = self._depth_fbo = QOpenGLFramebufferObject(w, h, fmt)
            extra = self.context().extraFunctions()
            self._gl.glBindFramebuffer(GL_READ_FRAMEBUFFER,
                                       self._scene_fbo.handle())
            self._gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dfbo.handle())
            extra.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h,
                                    GL_DEPTH_BUFFER_BIT, GL_NEAREST)
            self._gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, dfbo.handle())
            buf = np.empty((h, w), dtype=np.float32)
            self._gl.glReadPixels(0, 0, w, h, 0x1902, GL_FLOAT, buf)  # DEPTH
        except Exception:  # noqa: BLE001 — fall back to rays, never break paint
            self._depth_snap = None
            return
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        inv, ok = mvp.inverted()
        if not ok:
            return
        self._depth_snap = (buf, mvp, inv, w, h, self.camera.eye(),
                            self.camera.forward())

    def _occluded_on_screen(self, world: QVector3D) -> bool:
        """``_is_occluded`` for what the overlay draws this frame, read from
        the depth the frame just rendered (``_capture_depth``). The point is
        hidden when the nearest surface at its pixel lies clearly in front
        of it along the view — with a tolerance, so a dimension ending ON a
        face or an edge is not hidden by that same surface. Without a
        snapshot (an export, a failed read-back) it asks the rays."""
        snap = getattr(self, "_depth_snap", None)
        if snap is None:
            return self._is_occluded(world)
        buf, mvp, inv, w, h, eye, fwd = snap
        c = mvp.map(QVector4D(world.x(), world.y(), world.z(), 1.0))
        if c.w() <= 1e-9:
            return False
        nx, ny = c.x() / c.w(), c.y() / c.w()
        px, py = (nx + 1.0) * 0.5 * w, (ny + 1.0) * 0.5 * h
        ix, iy = int(px), int(py)
        if not (0 <= ix < w and 0 <= iy < h):
            return False
        # The FARTHEST depth of the 3×3 around the pixel: a point on a
        # silhouette must not be hidden by the face next to it.
        d = float(buf[max(iy - 1, 0):iy + 2, max(ix - 1, 0):ix + 2].max())
        if d >= 1.0:
            return False                       # background: nothing in front
        q = inv.map(QVector4D(nx, ny, d * 2.0 - 1.0, 1.0))
        if abs(q.w()) < 1e-12:
            return False
        surf = QVector3D(q.x() / q.w(), q.y() / q.w(), q.z() / q.w())
        along_pt = QVector3D.dotProduct(world - eye, fwd)
        along_surf = QVector3D.dotProduct(surf - eye, fwd)
        tol = max(0.02, 0.003 * abs(along_pt))
        return along_surf < along_pt - tol

    def _is_occluded(self, world: QVector3D) -> bool:
        """Whether geometry sits between the camera and ``world`` — i.e. the
        point is hidden from the current view. Used to keep snaps from firing
        on edges and vertices the user cannot see.

        Asks the PICK INDEX, which is the only place that knows the whole
        model: it holds the loose mesh AND every group's cached triangles, in
        world space, with per-chunk boxes to prefilter the ray. The old pass
        triangulated ``scene.faces`` alone — the loose mesh — so nothing
        inside a group ever hid anything, and drawing on a box snapped
        straight through it to the edge on the far side (Marco, 2026-08-27).
        Sharing the index also means occlusion and picking can never disagree
        about what is in front.

        Only VISIBLE geometry occludes (``ent_vis``, not ``ent_sel``): an
        object on a locked layer is still solid to the eye, while one on a
        hidden layer must not hide anything. A small epsilon on the far end
        keeps a point lying ON a face — an edge on that face's boundary —
        from being reported as occluded by its own face.

        X-ray and wireframe show everything, so nothing hides a snap there
        (the usual trick: switch to X-ray to dimension the floor of a pool through
        its water). Hidden-line and shaded keep the visible-only rule.

        The active section cut is checked first, in every style: what it
        cuts away is gone, not behind something. Dropping only the edges
        with BOTH ends on the hidden side (``_snap_scene``) left the edge
        that crosses the cut — a wall's vertical, cut halfway up — and its
        hidden end and stretch still snapped (#384).
        """
        sp = _active_cut(self.scene)
        if sp is not None and sp.side(world) > 1e-6:
            return True
        if self._effective_style().face_mode in ("xray", "wireframe"):
            return False
        idx = self._pick_index()
        if getattr(idx, "tri_v0", None) is None \
                and not getattr(idx, "own_spans", None):
            return False
        origin = self.camera.eye()
        delta = world - origin
        dist = delta.length()
        if dist < 1e-9:
            return False
        d = delta / dist
        sp = _active_cut(self.scene)
        if sp is None:
            # Nothing to sort out per face: the single nearest hit decides,
            # and asking for it skips allocating a per-face array on every
            # query (this fires dozens of times a frame).
            nearest = self._ray_hits(idx, origin, d, idx.ent_vis,
                                     reduce_global=True)
            return nearest is not None and nearest < dist - 1e-3
        face_t = self._ray_hits(idx, origin, d, idx.ent_vis)
        if face_t is None:
            return False
        import numpy as np
        hit = np.isfinite(face_t) & (face_t < dist - 1e-3)
        if not hit.any():
            return False
        # An active cut removes what it hides, so a hit on the clipped-away
        # side is not an occluder. A ray meets a planar face at most once, so
        # the per-face nearest hit IS the hit — testing it is exact.
        eye = np.array([origin.x(), origin.y(), origin.z()])
        dv = np.array([d.x(), d.y(), d.z()])
        n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
        c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
        pts = eye + dv * face_t[hit][:, None]
        return bool(((pts @ n - c) <= 1e-6).any())

    #: Cap on rays × triangles in one NumPy block of ``_occluded_many``
    #: (×3 float64 per array: ~50 MB at most).
    _OCCL_BLOCK = 2_000_000

    def _occluded_many(self, worlds) -> list:
        """``_is_occluded`` for several points at once — the snap engine's
        candidates, which all cast from the same eye. One ray at a time,
        each paid for its own span cull and a Möller–Trumbore pass per span
        it met, in small NumPy calls whose overhead was the cost (0.8 ms a
        ray, ~41 rays a hover on a 330 k-face city, 60 % of the inference
        pass). Here the rays share it: one box test for all of them against
        every span, then each span's triangles against the rays that reach
        it. Same rays (built with the same QVector3D arithmetic), same
        acceptance as ``_ray_hits``; with an active section cut — per-face
        rules — it asks ``_is_occluded`` point by point."""
        import numpy as np
        worlds = list(worlds)
        if worlds and _active_cut(self.scene) is not None:
            return [self._is_occluded(w) for w in worlds]   # the cut first (#384)
        out = [False] * len(worlds)
        if not worlds or self._effective_style().face_mode in ("xray",
                                                               "wireframe"):
            return out
        idx = self._pick_index()
        own = getattr(idx, "own_spans", None) or ()
        if getattr(idx, "tri_v0", None) is None and not own:
            return out
        if _active_cut(self.scene) is not None:
            return [self._is_occluded(w) for w in worlds]
        origin = self.camera.eye()
        rows, dirs, dists = [], [], []
        for i, w in enumerate(worlds):
            delta = w - origin
            dist = delta.length()
            if dist < 1e-9:
                continue
            d = delta / dist
            rows.append(i)
            dirs.append((d.x(), d.y(), d.z()))
            dists.append(dist)
        if not rows:
            return out
        o = np.array([origin.x(), origin.y(), origin.z()])
        D = np.array(dirs, dtype=np.float64)
        best = np.full(len(rows), np.inf)
        spans = ([] if idx.tri_v0 is None else
                 list(getattr(idx, "tri_spans", None)
                      or [(None, 0, len(idx.tri_v0))]))
        spans += list(own)
        inf = float("inf")
        boxes = getattr(idx, "_span_boxes", None)
        if boxes is None or boxes[0] != len(spans):
            blo = np.array([sp[0][0] if sp[0] is not None else (-inf,) * 3
                            for sp in spans], dtype=np.float64).reshape(-1, 3)
            bhi = np.array([sp[0][1] if sp[0] is not None else (inf,) * 3
                            for sp in spans], dtype=np.float64).reshape(-1, 3)
            boxes = idx._span_boxes = (len(spans), blo, bhi)
        _n, blo, bhi = boxes
        # The box prefilter _ray_hits applies, in both its regimes: the
        # vectorised slab past 64 spans, ``_ray_aabb`` (with its tolerance
        # for a ray parallel to an axis) below — they differ on exactly
        # those rays, the standard views'.
        with np.errstate(divide="ignore", invalid="ignore"):
            if len(spans) > 64:
                inv_d = 1.0 / np.where(np.abs(D) > 1e-12, D, 1e-12)  # (R, 3)
                t1 = (blo[None, :, :] - o) * inv_d[:, None, :]        # (R, S, 3)
                t2 = (bhi[None, :, :] - o) * inv_d[:, None, :]
                tmin = np.nanmax(np.minimum(t1, t2), axis=2)
                tmax = np.nanmin(np.maximum(t1, t2), axis=2)
                meet = tmax >= np.maximum(tmin, 0.0)
            else:
                par = np.abs(D) < 1e-12                               # (R, 3)
                inv_d = 1.0 / np.where(par, 1.0, D)
                t1 = (blo[None, :, :] - o) * inv_d[:, None, :]
                t2 = (bhi[None, :, :] - o) * inv_d[:, None, :]
                lo_t = np.where(par[:, None, :], -inf, np.minimum(t1, t2))
                hi_t = np.where(par[:, None, :], inf, np.maximum(t1, t2))
                tmin = np.maximum(lo_t.max(axis=2), 0.0)
                tmax = hi_t.min(axis=2)
                inside = (o >= blo - 1e-9) & (o <= bhi + 1e-9)        # (S, 3)
                meet = ((~par[:, None, :] | inside[None, :, :]).all(axis=2)
                        & (tmin <= tmax))
                unboxed = np.array([sp[0] is None for sp in spans], dtype=bool)
                meet |= unboxed[None, :]
                tmin = np.where(unboxed[None, :], -inf, tmin)
        limit = np.array(dists) - 1e-3                                # (R,)
        # Only what lies BEFORE the point can hide it: a span whose box the
        # ray enters past the point is skipped (an occluding hit at t < limit
        # enters its box before that), and spans go nearest first so a ray
        # settled as hidden stops asking.
        meet = meet & (tmin < limit[:, None])                         # (R, S)
        ent_mask = idx.ent_vis
        native = _occlusion_native()
        o3 = (float(o[0]), float(o[1]), float(o[2]))
        live_spans = np.flatnonzero(meet.any(axis=0))
        order = np.argsort(np.where(meet[:, live_spans],
                                    tmin[:, live_spans], np.inf).min(axis=0))
        for si in live_spans[order]:
            span = spans[si]
            if len(span) == 3:
                _bb, s0, n = span
                if not n:
                    continue
                v0 = idx.tri_v0[s0:s0 + n]
                e1 = idx.tri_e1[s0:s0 + n]
                e2 = idx.tri_e2[s0:s0 + n]
                te = idx.tri_ent[s0:s0 + n]
            else:
                _bb, v0, e1, e2, te_local, eoff = span
                if not len(v0):
                    continue
                te = te_local + eoff
            live = ent_mask[te]
            if not live.any():
                continue
            if not live.all():
                v0, e1, e2 = v0[live], e1[live], e2[live]
            r_all = np.flatnonzero(meet[:, si] & (best >= limit))
            if not len(r_all):
                continue
            if native is not None:
                # The same block in the native engine; the rays it cannot
                # call bit for bit (core/occlusion.rs) come back to NumPy
                # below, from where they stood before this span.
                before = best[r_all]
                nb, doubt = native.occlusion_span(
                    o3, np.ascontiguousarray(D[r_all]), before,
                    np.ascontiguousarray(limit[r_all]), v0, e1, e2)
                best[r_all] = np.where(doubt, before, nb)
                r_all = r_all[doubt]
                if not len(r_all):
                    continue
            s = o - v0                                                # (n, 3)
            q = np.cross(s, e1)                                       # (n, 3)
            uq = np.einsum("ij,ij->i", e2, q)                         # (n,)
            step = max(1, self._OCCL_BLOCK // max(len(v0), 1))
            for k in range(0, len(r_all), step):
                r = r_all[k:k + step]
                d = D[r]                                              # (r, 3)
                p = np.cross(d[:, None, :], e2[None, :, :])           # (r, n, 3)
                det = np.einsum("nj,rnj->rn", e1, p)
                ok = np.abs(det) > 1e-6
                inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
                u = np.einsum("nj,rnj->rn", s, p) * inv
                v = (d @ q.T) * inv
                t = uq[None, :] * inv
                hit = (ok & (u >= 0.0) & (u <= 1.0) & (v >= 0.0)
                       & (u + v <= 1.0) & (t > 1e-6))
                tm = np.where(hit, t, np.inf).min(axis=1)
                best[r] = np.minimum(best[r], tm)
        for j, i in enumerate(rows):
            out[i] = bool(best[j] < limit[j])
        return out
