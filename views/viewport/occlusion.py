# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Screen-depth occlusion for the overlay's annotations and the snap."""
from __future__ import annotations

from PySide6.QtGui import QVector3D, QVector4D
from core.section import active_scoped_planes
from core.style import base_face_mode, xray_enabled, sees_through_faces
from views.viewport._support import (_active_cut, GL_FLOAT,
                                     GL_DEPTH_BUFFER_BIT, GL_READ_FRAMEBUFFER,
                                     GL_DRAW_FRAMEBUFFER, GL_NEAREST,
                                     _occlusion_native, _OCCLUSION_MEMO,
                                     _FIRST_CLEAR, _cache_ver, _content_ver,
                                     _qv_hypot3, _unit_rays, _occlusion_block,
                                     _occlusion_det_ok, _slab_far, _slab_near)


class OcclusionMixin:
    """Screen-depth occlusion for the overlay's annotations and the snap."""

    # ---- Screen-depth occlusion for the overlay's annotations ---------------
    def _annotations_need_depth(self) -> bool:
        if sees_through_faces(self._effective_style()):
            return False
        sc = self.scene
        return bool(getattr(sc, "dimensions", None)
                    or getattr(sc, "text_labels", None))

    def _read_scene_depth(self, w: int, h: int):
        """The frame's depth, copied out of the (multisampled) scene FBO
        into a single-sample one and read back: an ``(h, w)`` float array,
        or None when the driver refuses. Leaves the read framebuffer bound
        to that copy; the caller rebinds what it draws into."""
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
        except Exception:  # noqa: BLE001
            return None
        return buf

    def _capture_depth(self, w: int, h: int) -> None:
        """Copy the frame's depth out of the (multisampled) scene FBO into a
        single-sample one and read it back once. The overlay then answers
        «is this point hidden?» with a lookup instead of a ray cast against
        the whole model: a house from a 2018 .skp with 25 dimensions spent
        2.8 s of every frame casting 1350 rays against 284 000 triangles
        (Juan José Noriega's files, 26-09-2026); the read-back is ~8 ms."""
        buf = self._read_scene_depth(w, h)
        if buf is None:             # fall back to rays, never break paint
            self._depth_snap = None
            return
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        inv, ok = mvp.inverted()
        if not ok:
            return
        self._depth_snap = (buf, mvp, inv, w, h, self.camera.eye(),
                            self.camera.forward())
        # The kept model it was read from, if nothing over it wrote depth.
        self._depth_snap_of = getattr(self, "_depth_clean", None)

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
        if sees_through_faces(self._effective_style()):
            return False
        if active_scoped_planes(self.scene):
            origin = self.camera.eye()
            delta = world - origin
            distance = delta.length()
            if distance < 1e-9:
                return False
            direction = delta / distance
            idx = self._pick_index(near=("ray", origin, direction, distance))
            hits = self._face_hits(idx, origin, direction, "vis")
            self._drop_past_cut(hits, origin, direction)
            return hits is not None and bool((hits.t < distance - 1e-3).any())
        if (sp is None and hasattr(self, "_lazy_native")
                and self._lazy_native() is not None):
            # Every lazy placement, unbaked, through the batched pass.
            return self._occluded_many([world])[0]
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
        pts = eye + dv * face_t[hit][:, None]
        return bool((~sp.hidden(pts)).any())

    #: Cap on rays × triangles in one NumPy block of ``_occluded_many``
    #: (×3 float64 per array: ~50 MB at most).
    _OCCL_BLOCK = 2_000_000

    def _occluded_many(self, worlds) -> list:
        """``_occluded_many_now``, each point asked once a view: drawing over
        the plant of #158 every pointer move asked again the ~7000 corners
        a roof hides near the cursor, the same ones as the move before, and
        they were 17 ms of it. What a point's ray meets hangs on the eye,
        the model and the occluders the engine holds (``_occluded_memo_key``),
        never on the cursor — only with the engine's placements (#158):
        without them the index bakes what lies near the cursor."""
        import numpy as np
        if not len(worlds):
            return []
        key = self._occluded_memo_key()
        if key is None:
            return self._occluded_many_now(worlds)
        memo = getattr(self, "_occluded_memo", None)
        if memo is None or memo[0] != key or len(memo[1]) > 400_000:
            memo = self._occluded_memo = (key, {})
        known = memo[1]
        if isinstance(worlds, np.ndarray):
            pts = [tuple(p) for p in worlds.reshape(-1, 3).tolist()]
        else:
            worlds = list(worlds)
            pts = [(w.x(), w.y(), w.z()) for w in worlds]
        ask = [i for i, p in enumerate(pts) if p not in known]
        if ask:
            new = self._occluded_many_now(
                np.array([pts[i] for i in ask], dtype=np.float64)
                .reshape(-1, 3))
            for i, h in zip(ask, new):
                known[pts[i]] = bool(h)
        return [known[p] for p in pts]

    def _first_clear(self, pts):
        """The index of the first of ``pts`` (N, 3), in order, that
        ``_occluded_many`` calls seen (-1: none), asked of the native
        engine in one call — the same rays, the same occluders, the rays it
        cannot call bit for bit asked here as before — or None where it
        cannot answer for ``_occluded_many_now``: no engine's placements,
        a section cut (it asks face by face), no static set for the index's
        triangles, or a library whose vector length the rays cannot copy.
        Over the plant of #158 the ~7000 corners a roof hides near the
        cursor took a dozen batches, the memo's bookkeeping and the rays'."""
        import numpy as np
        if not _FIRST_CLEAR or not len(pts):
            return None
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if nat is None or not hasattr(nat[0], "first_clear"):
            return None
        if (_active_cut(self.scene) is not None
                or active_scoped_planes(self.scene) or not _qv_hypot3()):
            return None
        if sees_through_faces(self._effective_style()):
            return 0                     # nothing hides anything
        idx = self._pick_index(near="skip")
        stat = None
        if getattr(idx, "tri_v0", None) is not None:
            stat = self._static_occluders(idx)
            if stat is None:
                return None
        iset, _snap, vis = nat
        e = self.camera.eye()
        pts = np.ascontiguousarray(pts, dtype=np.float64).reshape(-1, 3)
        first, doubts = iset.first_clear(
            np.ascontiguousarray(vis, np.int64), (e.x(), e.y(), e.z()), pts,
            stat[0] if stat is not None else None,
            stat[1] if stat is not None else None, _qv_hypot3())
        for j in doubts.tolist():
            if not self._occluded_many_now(pts[j:j + 1])[0]:
                return j
        return int(first)

    def _occluded_memo_key(self):
        """What ``_occluded_many_now``'s answer for a point hangs on, or
        None where it may hang on more (a section cut asks face by face,
        X-ray and wireframe hide nothing, and without the engine's
        placements the index bakes around the cursor)."""
        if not _OCCLUSION_MEMO:
            return None
        if _active_cut(self.scene) is not None or active_scoped_planes(self.scene):
            return None
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if nat is None or not len(nat[2]):
            return None
        idx = self._pick_index(near="skip")
        eye = self.camera.eye()
        sc = self.scene
        return (eye.x(), eye.y(), eye.z(), id(idx), id(nat[0]),
                id(sc), sc.version, _cache_ver(self), _content_ver(self),
                self._placements_epoch(), id(sc.edit_group),
                self._rest_is_hidden(), base_face_mode(self._effective_style()),
                xray_enabled(self._effective_style()))

    def _occluded_many_now(self, worlds) -> list:
        """``_is_occluded`` for several points at once — the snap engine's
        candidates, which all cast from the same eye. One ray at a time,
        each paid for its own span cull and a Möller–Trumbore pass per span
        it met, in small NumPy calls whose overhead was the cost (0.8 ms a
        ray, ~41 rays a hover on a 330 k-face city, 60 % of the inference
        pass). Here the rays share it: one box test for all of them against
        every span, then each span's triangles against the rays that reach
        it. Same rays (built with the same QVector3D arithmetic), same
        acceptance as ``_ray_hits``; with an active section cut — per-face
        rules — it asks ``_is_occluded`` point by point.

        ``worlds`` may also be an (N, 3) array of points, read as the
        QVector3D of each would hold them."""
        import numpy as np
        arr = None
        if isinstance(worlds, np.ndarray):
            arr = worlds.reshape(-1, 3)
            worlds = arr
        else:
            worlds = list(worlds)
        if len(worlds) and (_active_cut(self.scene) is not None
                            or active_scoped_planes(self.scene)):
            if arr is not None:
                worlds = [QVector3D(*p) for p in arr.tolist()]
            return [self._is_occluded(w) for w in worlds]   # the cut first (#384)
        out = [False] * len(worlds)
        if not len(worlds) or sees_through_faces(self._effective_style()):
            return out
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        # Unbaked, the lazy placements need nothing around the cursor here.
        idx = self._pick_index(near="skip" if nat is not None else None)
        own = getattr(idx, "own_spans", None) or ()
        if nat is not None:
            # The lazy placements are asked of the engine, every one the
            # index would take — not only those baked now (#158).
            own = ()
            if not len(nat[2]):
                nat = None
        if getattr(idx, "tri_v0", None) is None and not own and nat is None:
            return out
        origin = self.camera.eye()
        rays = _unit_rays(origin, arr if arr is not None else
                          [(w.x(), w.y(), w.z()) for w in worlds])
        if rays is not None:
            rows, D, dists = rays
        else:
            if arr is not None:
                worlds = [QVector3D(*p) for p in arr.tolist()]
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
            D = np.array(dirs, dtype=np.float64).reshape(-1, 3)
        if not len(rows):
            return out
        o = np.array([origin.x(), origin.y(), origin.z()])
        best = np.full(len(rows), np.inf)
        settled = None
        stat = (self._static_occluders(idx) if nat is not None
                and getattr(idx, "tri_v0", None) is not None else None)
        if stat is not None:
            # The loose and fixed triangles in the engine too: span by span
            # in NumPy, the tens of thousands of corners a roof hides from
            # far off took a second a pointer move (#158). Only the rays it
            # cannot call bit for bit go through the spans below.
            hid, doubt = stat[0].occluded(
                stat[1], (float(o[0]), float(o[1]), float(o[2])),
                D, np.array(dists) - 1e-3)
            best[hid] = -np.inf
            settled = hid | ~doubt
        whole = None
        if settled is not None and settled.any() and not settled.all():
            # The spans below for the rays the engine left open only: the
            # box tests are rays × spans, and it settles nearly all of them.
            whole = (np.flatnonzero(~settled), D, best, np.asarray(dists))
            D, best = D[whole[0]], best[whole[0]]
            dists, settled = whole[3][whole[0]], None
        spans = ([] if idx.tri_v0 is None
                 or (settled is not None and settled.all()) else
                 list(getattr(idx, "tri_spans", None)
                      or [(None, 0, len(idx.tri_v0))]))
        spans += list(own)
        inf = float("inf")
        boxes = getattr(idx, "_span_boxes", None)
        if not spans:
            boxes = (0, np.empty((0, 3)), np.empty((0, 3)))   # not kept
        elif boxes is None or boxes[0] != len(spans):
            blo = np.array([sp[0][0] if sp[0] is not None else (-inf,) * 3
                            for sp in spans], dtype=np.float64).reshape(-1, 3)
            bhi = np.array([sp[0][1] if sp[0] is not None else (inf,) * 3
                            for sp in spans], dtype=np.float64).reshape(-1, 3)
            boxes = idx._span_boxes = (len(spans), blo, bhi)
        _n, blo, bhi = boxes
        # The rays leave one eye inside a cone; a span whose bounding
        # sphere lies outside it meets none of them, and is left out of the
        # box test below (rays x spans x 3: zoomed out over the plant of
        # #158, hundreds of rays against 1 700 spans, most of them far off
        # to the side). Conservative, so the answer is the same; the
        # regime below is still chosen by the whole count.
        sel = np.arange(len(spans))
        if len(rows) > 1 and len(spans) > 64:
            axis = D.sum(axis=0)
            na = float(np.linalg.norm(axis))
            cos_min = float((D @ axis).min()) / na if na > 0 else -1.0
            fin = np.isfinite(blo).all(axis=1) & np.isfinite(bhi).all(axis=1)
            if cos_min > 0.5 and fin.any():
                a = axis / na
                theta = float(np.arccos(min(cos_min, 1.0)))
                with np.errstate(divide="ignore", invalid="ignore"):
                    c = (blo + bhi) * 0.5 - o           # unboxed: kept anyway
                    rad = (np.linalg.norm(bhi - blo, axis=1) * 0.5
                           * (1 + 1e-6) + 1e-6)
                    L = np.linalg.norm(c, axis=1)
                    ang = np.arccos(np.clip((c @ a) / L, -1.0, 1.0))
                    widen = np.arcsin(np.clip(rad / L, 0.0, 1.0))
                keep = (~fin | (L <= rad)
                        | (ang - widen <= theta + 1e-6))
                if not keep.all():
                    sel = np.flatnonzero(keep)
        many_spans = len(spans) > 64
        blo, bhi = blo[sel], bhi[sel]
        # The box prefilter _ray_hits applies, in both its regimes: the
        # vectorised slab past 64 spans, ``_ray_aabb`` (with its tolerance
        # for a ray parallel to an axis) below — they differ on exactly
        # those rays, the standard views'.
        with np.errstate(divide="ignore", invalid="ignore"):
            if many_spans:
                inv_d = 1.0 / np.where(np.abs(D) > 1e-12, D, 1e-12)  # (R, 3)
                t1 = (blo[None, :, :] - o) * inv_d[:, None, :]        # (R, S, 3)
                t2 = (bhi[None, :, :] - o) * inv_d[:, None, :]
                tmin = _slab_far(np.minimum(t1, t2))
                tmax = _slab_near(np.maximum(t1, t2))
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
                unboxed = np.array([spans[j][0] is None for j in sel],
                                   dtype=bool)
                meet |= unboxed[None, :]
                tmin = np.where(unboxed[None, :], -inf, tmin)
        limit = np.array(dists) - 1e-3                                # (R,)
        # Only what lies BEFORE the point can hide it: a span whose box the
        # ray enters past the point is skipped (an occluding hit at t < limit
        # enters its box before that), and spans go nearest first so a ray
        # settled as hidden stops asking.
        meet = meet & (tmin < limit[:, None])                         # (R, S)
        if settled is not None:
            meet &= ~settled[:, None]
        ent_mask = idx.ent_vis
        native = _occlusion_native()
        o3 = (float(o[0]), float(o[1]), float(o[2]))
        live_spans = np.flatnonzero(meet.any(axis=0))
        order = np.argsort(np.where(meet[:, live_spans],
                                    tmin[:, live_spans], np.inf).min(axis=0))
        for si in live_spans[order]:
            span = spans[sel[si]]
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
                ok = _occlusion_det_ok(det, d, e1, e2)
                inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
                u = np.einsum("nj,rnj->rn", s, p) * inv
                v = (d @ q.T) * inv
                t = uq[None, :] * inv
                hit = (ok & (u >= 0.0) & (u <= 1.0) & (v >= 0.0)
                       & (u + v <= 1.0) & (t > 1e-6))
                tm = np.where(hit, t, np.inf).min(axis=1)
                best[r] = np.minimum(best[r], tm)
        if whole is not None:
            u, D, best_all, dists = whole
            best_all[u] = best
            best = best_all
            limit = dists - 1e-3
        if nat is not None:
            left = np.flatnonzero(best >= limit)
            if len(left):
                iset, _snap, vis = nat
                hid, doubt = iset.occluded(
                    vis, o3, np.ascontiguousarray(D[left]),
                    np.ascontiguousarray(limit[left]))
                best[left[hid]] = -np.inf
                for r in left[doubt]:
                    # Too close to call bit for bit: the block above, on
                    # the triangles the ray may meet, as baked.
                    v0, e1, e2 = iset.ray_tris(vis, o3, tuple(D[r].tolist()),
                                               float(limit[r]))
                    if _occlusion_block(o, D[r:r + 1], v0, e1, e2)[0] \
                            < limit[r]:
                        best[r] = -np.inf
        res = np.zeros(len(worlds), dtype=bool)
        res[np.asarray(rows, dtype=np.intp)] = best < limit
        return res.tolist()
