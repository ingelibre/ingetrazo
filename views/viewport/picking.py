# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Picking: the pick index, ray hits and the pick_* queries."""
from __future__ import annotations

import math
import time as _time_mod
from PySide6.QtGui import QFont, QFontMetrics, QVector3D, QVector4D
from views.viewport._support import (_PERF, _plog, _active_cut, _split_chunk_spans, _ray_aabb,
                                     _INSTANCE_FILTER, _cache_ver, _ray_triangle,
                                     _point_to_segment_distance_2d)
from views.viewport.snapping import SnappingMixin


class PickingMixin:
    """Picking: the pick index, ray hits and the pick_* queries."""

    def _front_face_at(self, x: float, y: float):
        """``(face, placement)`` of the front-most selectable face on the ray
        through pixel ``(x, y)``, or ``None``. A bare pass with no memo:
        the face-crossing search asks it at pixels around the cursor, and
        :meth:`pick_face_any`'s memo holds the cursor's own answer."""
        o, d = self._pixel_to_ray(x, y)
        if o is None or d is None:
            return None
        import numpy as np
        idx = self._pick_index(near=("px", x, y))
        if not idx.entities:
            return None
        t = self._ray_hits(idx, o, d, idx.ent_sel)
        if t is None or len(t) == 0:
            return None
        i = int(np.argmin(t))
        if not np.isfinite(t[i]):
            return None
        face, owner = idx.entities[i]
        pidx = getattr(idx, "ent_place_idx", None)
        if pidx is not None and i < len(pidx) and pidx[i] >= 0:
            return face, idx.ent_placements[int(pidx[i])]
        return face, owner

    #: Component placements holding more faces than this, all together,
    #: switch the pick index to LAZY placements (issue #158): below it the
    #: index is exactly what it always was.
    _PICK_LAZY_MIN_FACES = 1_000_000
    #: How many faces of lazy placements the index keeps baked at once.
    _PICK_LIVE_MAX_FACES = 600_000
    #: Lazy placements baked by one query at most (the nearest first).
    _PICK_NEW_PER_QUERY = 300
    #: Screen margin, in pixels, around the cursor for «near the cursor».
    _PICK_NEAR_PX = 32.0

    def _pick_lazy_table(self):
        """The component placements the pick index takes lazily — only when
        a query comes near them — as ``(groups, lo, hi, nf, ids)``, or
        ``None`` when they are too few to bother (the index then holds
        everything, as it always did).

        Baking every placement to world coordinates for the index was what
        a model of 21 406 placements (14 million faces) could not survive:
        the first hover with Select went past 8 GB (issue #158)."""
        import numpy as np
        key = self._placements_epoch()
        memo = getattr(self, "_pick_lazy_memo", None)
        if memo is not None and memo[0] == key:
            return memo[1]
        groups = [g for g in self._placements()
                  if getattr(g, "xform", None) is not None
                  and not getattr(g, "billboard", False)]
        from core.mesh import face_count
        nf = np.fromiter((face_count(g.mesh) for g in groups), np.int64,
                         count=len(groups))
        table = None
        if int(nf.sum()) >= self._PICK_LAZY_MIN_FACES:
            inf = float("inf")
            lo = np.empty((len(groups), 3))
            hi = np.empty((len(groups), 3))
            for i, g in enumerate(groups):
                box = self._placement_frame(g)[0]
                lo[i], hi[i] = box if box else ((-inf,) * 3, (inf,) * 3)
            table = (groups, lo, hi, nf, {id(g) for g in groups})
        self._pick_lazy_memo = (key, table)
        return table

    def _pick_instance_set(self, table):
        """core._native's InstanceSet over the lazy placements of ``table``
        (see _pick_lazy_table), or ``None`` without the experimental
        engine. A prototype's index (a BVH of its pick triangles, its hard
        edges, from its local bake) is kept while its bake is."""
        if not _INSTANCE_FILTER:
            return None
        from core import _native
        mod = _native.native
        if mod is None or not hasattr(mod, "InstanceSet"):
            return None
        memo = getattr(self, "_inst_set_memo", None)
        if memo is not None and memo[0] is table:
            return memo[1]
        import numpy as np
        from core.group import effective_material
        groups = table[0]
        cache = getattr(self, "_inst_proto_cache", None) or {}
        keep: dict = {}
        by_mesh: dict = {}
        protos: list = []
        proto_of = np.empty(len(groups), dtype=np.int64)
        mats = np.empty((len(groups), 16), dtype=np.float64)
        for i, g in enumerate(groups):
            k = by_mesh.get(id(g.mesh))
            if k is None:
                # Every placement of a mesh has the same triangles and hard
                # edges, whatever its paint: one bake (the first one's).
                base = self._proto_base_chunk(g.mesh, effective_material(g))
                ckey = (base.get("uid"), base.get("rev"))
                ip = cache.get(ckey)
                if ip is None:
                    z = np.zeros((0, 3))
                    v0 = base.get("v0")
                    edges = (np.frombuffer(base["edges"], dtype=np.float32)
                             .reshape(-1, 6).astype(np.float64)
                             if base.get("edges") else np.zeros((0, 6)))
                    ip = mod.InstanceProto(
                        np.ascontiguousarray(v0) if v0 is not None else z,
                        np.ascontiguousarray(base["e1"]) if v0 is not None
                        else z,
                        np.ascontiguousarray(base["e2"]) if v0 is not None
                        else z, edges)
                keep[ckey] = ip
                k = by_mesh[id(g.mesh)] = len(protos)
                protos.append(ip)
            proto_of[i] = k
            mats[i] = g.xform.data()
        self._inst_proto_cache = keep
        iset = mod.InstanceSet(protos, proto_of, mats)
        self._inst_set_memo = (table, iset)
        return iset

    def _pick_materialize(self, near) -> None:
        """Bake into the pick index the lazy placements a query needs:
        ``near`` = ``None`` (around the cursor), ``("px", x, y)`` (around a
        widget pixel), ``("ray", origin, direction)`` or ``"all"``. What was
        baked stays until the cap needs room (least recently needed first);
        ``_pick_gen`` counts the changes, which key the index."""
        import numpy as np
        from collections import OrderedDict
        table = self._pick_lazy_table()
        live = getattr(self, "_pick_live", None)
        if table is None:
            if live:
                live.clear()
                self._pick_gen = getattr(self, "_pick_gen", 0) + 1
            return
        groups, lo, hi, nf, _ids = table
        if live is None:
            live = self._pick_live = OrderedDict()
        if near == "skip":
            return                              # a loose-only query
        px_at = None
        if isinstance(near, tuple) and near[0] == "px":
            px_at = (float(near[1]), float(near[2]))
            # A pick at a pixel only meets what the ray through it crosses:
            # the 32 px footprint is for snaps (``("snap", x, y)``), and on a
            # dense plant it took in thousands of placements per hover.
            o, d = self._pixel_to_ray(float(near[1]), float(near[2]))
            if o is None or d is None:
                return
            near = ("ray", o, d)
        elif isinstance(near, tuple) and near[0] == "snap":
            near = (None, near[1], near[2])
        if near == "all":
            need = np.arange(len(groups))
        elif isinstance(near, tuple) and near[0] == "ray":
            o, d = near[1], near[2]
            reach = near[3] if len(near) > 3 else None
            o = np.array([o.x(), o.y(), o.z()])
            d = np.array([d.x(), d.y(), d.z()])
            with np.errstate(divide="ignore", invalid="ignore"):
                inv = 1.0 / np.where(np.abs(d) > 1e-12, d, 1e-12)
                t1 = (lo - o) * inv
                t2 = (hi - o) * inv
            tmin = np.nanmax(np.minimum(t1, t2), axis=1)
            tmax = np.nanmin(np.maximum(t1, t2), axis=1)
            hit = tmax >= np.maximum(tmin, 0.0)
            if reach is not None:
                # A bounded query (the walkthrough's wall feelers, half a
                # metre ahead) needs nothing past its reach: an unbounded
                # one baked every placement down the street, and turning
                # the head brought in new ones and rebuilt the index.
                hit &= tmin <= reach
            if px_at is not None and hit.sum() > 1:
                # Whatever starts behind the surface the frame shows at this
                # pixel can be neither picked nor seen.
                seen = self._depth_world_at(*px_at)
                if seen is not None and seen[0] == "hit":
                    t_vis = float(np.linalg.norm(
                        np.array([seen[1].x(), seen[1].y(), seen[1].z()]) - o))
                    hit &= tmin <= t_vis * 1.02 + 0.05
            need = np.flatnonzero(hit)
            iset = self._pick_instance_set(table) if len(need) else None
            if iset is not None:
                # Of the boxes the ray crosses, the placements whose
                # triangles it can meet (the spatial index, with margins
                # past the exact test's): only those are baked.
                need = np.asarray(iset.ray_filter(
                    need.astype(np.int64), tuple(o.tolist()),
                    tuple(d.tolist()), reach), dtype=np.int64)
        else:
            if near is None:
                pos = getattr(self, "_last_mouse_pos", None)
                if pos is None:
                    return
                x, y = float(pos.x()), float(pos.y())
            else:
                x, y = float(near[1]), float(near[2])
            ckey = (self._placements_epoch(), round(x), round(y),
                    tuple(self._np_mvp().ravel()))
            cmemo = getattr(self, "_pick_near_memo", None)
            if cmemo is not None and cmemo[0] == ckey:
                need = cmemo[1]
            else:
                need = self._placements_under_px(lo, hi, x, y)
                far = self._visible_depth_limit(x, y)
                if far is not None and len(need):
                    # What lies wholly behind what is on screen around the
                    # cursor can be neither picked nor snapped to (hidden
                    # snaps are dropped): a dense plant stacks thousands of
                    # placements under one pixel (#158).
                    e = self.camera.eye()
                    e = np.array([e.x(), e.y(), e.z()])
                    near_pt = np.clip(e, lo[need], hi[need])
                    dist = np.linalg.norm(near_pt - e, axis=1)
                    need = need[dist <= far]
                iset = self._pick_instance_set(table) if len(need) else None
                if iset is not None:
                    # Of the boxes near the cursor, the placements with a
                    # hard edge within the farthest reach a snap measures
                    # or a triangle within the footprint (with margins).
                    M = self._np_mvp()
                    need = np.asarray(iset.screen_filter(
                        need.astype(np.int64),
                        np.ascontiguousarray(M.T).ravel().tolist(),
                        float(self.width()), float(self.height()), x, y,
                        SnappingMixin.GEDGE_REACH_PX + 2.0,
                        self._PICK_NEAR_PX + 2.0), dtype=np.int64)
                self._pick_near_memo = (ckey, need)
        new = [int(i) for i in need if id(groups[int(i)]) not in live]
        if len(new) > self._PICK_NEW_PER_QUERY and near != "all":
            # A first snap over a dense spot met thousands at once (2.3 s):
            # the nearest to the eye come in now, the rest on the next moves.
            e = self.camera.eye()
            e = np.array([e.x(), e.y(), e.z()])
            nn = np.array(new)
            dist = np.linalg.norm(np.clip(e, lo[nn], hi[nn]) - e, axis=1)
            keep_new = set(nn[np.argsort(dist)[:self._PICK_NEW_PER_QUERY]]
                           .tolist())
            need = [int(i) for i in need
                    if id(groups[int(i)]) in live or int(i) in keep_new]
        changed = False
        for i in need:
            g = groups[int(i)]
            k = id(g)
            if k in live:
                live.move_to_end(k)
            else:
                live[k] = (g, int(nf[int(i)]))
                changed = True
        faces = sum(v[1] for v in live.values())
        if faces > self._PICK_LIVE_MAX_FACES and near != "all":
            keep = {id(groups[int(i)]) for i in need}
            inst = getattr(self, "_inst_chunks", None)
            for k in list(live):
                if faces <= self._PICK_LIVE_MAX_FACES:
                    break
                if k in keep:
                    continue
                faces -= live.pop(k)[1]
                if inst is not None:
                    inst.pop(k, None)     # its world bake goes with it
                changed = True
        if changed:
            self._pick_gen = getattr(self, "_pick_gen", 0) + 1

    def _visible_depth_limit(self, x: float, y: float):
        """The farthest distance from the eye of what the last frame shows
        within ``_PICK_NEAR_PX`` of widget pixel ``(x, y)``, with a margin —
        or ``None`` when the frame cannot say (no read-back, the camera
        moved since, or sky in the window: then anything may be there)."""
        import numpy as np
        if self._depth_world_at(x, y) is None:
            return None
        snap = self._depth_snap
        buf, inv, w, h = snap[0], snap[2], snap[3], snap[4]
        dpr = w / max(1, self.width())
        r = int(self._PICK_NEAR_PX * dpr) + 1
        cx, cy = int(x * dpr), int(h - 1 - y * dpr)
        win = buf[max(cy - r, 0):cy + r + 1, max(cx - r, 0):cx + r + 1]
        if not win.size or float(win.max()) >= 1.0:
            return None
        iy, ix = np.unravel_index(int(np.argmax(win)), win.shape)
        px = max(cx - r, 0) + ix
        py = max(cy - r, 0) + iy
        d = float(win.max())
        q = inv.map(QVector4D((px + 0.5) / w * 2 - 1, (py + 0.5) / h * 2 - 1,
                              d * 2 - 1, 1.0))
        if abs(q.w()) < 1e-12:
            return None
        far = (QVector3D(q.x() / q.w(), q.y() / q.w(), q.z() / q.w())
               - self.camera.eye()).length()
        return far * 1.02 + 0.05

    def _placements_under_px(self, lo, hi, x, y):
        """Indices of the boxes ``lo``/``hi`` whose screen footprint comes
        within ``_PICK_NEAR_PX`` of widget pixel ``(x, y)``; a box that
        crosses the eye plane counts (it can be anywhere on screen)."""
        import numpy as np
        M = self._np_mvp()
        corners = np.stack([np.where(np.array([(i >> k) & 1 for k in range(3)],
                                              bool), hi, lo)
                            for i in range(8)], axis=1)          # (P, 8, 3)
        finite = np.isfinite(corners).all(axis=(1, 2))
        c = np.where(np.isfinite(corners), corners, 0.0)
        clip = c @ M[:, :3].T + M[:, 3]                          # (P, 8, 4)
        w = clip[..., 3]
        front = w > 1e-9
        ww = np.where(front, w, 1.0)
        sx = (clip[..., 0] / ww * 0.5 + 0.5) * self.width()
        sy = (1.0 - (clip[..., 1] / ww * 0.5 + 0.5)) * self.height()
        big = 1e12
        x0 = np.where(front, sx, big).min(axis=1)
        x1 = np.where(front, sx, -big).max(axis=1)
        y0 = np.where(front, sy, big).min(axis=1)
        y1 = np.where(front, sy, -big).max(axis=1)
        r = self._PICK_NEAR_PX
        inside = (x0 - r <= x) & (x <= x1 + r) & (y0 - r <= y) & (y <= y1 + r)
        straddle = front.any(axis=1) & ~front.all(axis=1)
        return np.flatnonzero((inside & front.all(axis=1)) | straddle
                              | ~finite)

    def _pick_block_part(self, candidatos, tocables, lazy_set, base):
        """One part of the pick block (see _pick_index): the faces, owners,
        triangles and hard edges of ``candidatos``, numbered after ``base``
        (the part before it, or None). Lists, joined by _pick_join_parts."""
        import numpy as np
        scene = self.scene
        chunks = []
        for g in candidatos:
            if getattr(g, "billboard", False):
                continue          # per-frame quad; picked separately
            gvis = scene.entity_visible(g)
            # The layer says whether it can be snapped to; the context
            # says whether it can be picked.
            gsnap = scene.entity_selectable(g)
            gsel = gsnap and id(g) in tocables
            if not (gvis or gsnap):
                continue
            chunk = self._group_chunk(g)
            if not (chunk["faces"] or chunk["edges"]):
                continue          # nothing in it to pick or snap to
            # Note the `or edges`: a group of nothing but lines and arcs
            # has no faces, and skipping it here dropped it out of the
            # index ENTIRELY — so inference found none of its edges and
            # the edge fallback below, written for "a lines-only group",
            # read an empty array and never found it either (GitHub #8).
            # The OWNER a hit resolves to depends on the open context
            # (inside the plaza its children are the objects): it keys
            # the block too, or a double-click into the plaza kept
            # answering "the plaza" for the arch inside (Marco,
            # 2026-09-14).
            chunks.append((g, chunk, gvis, gsel, gsnap))
        n_ent = base["n_ent"] if base else 0
        n_plist = base["n_plist"] if base else 0
        b_tri_off = base["n_tri"] if base else 0
        n_ggroups = base["n_ggroups"] if base else 0
        b_entities: list = []
        # Per entity, the PLACEMENT (proxy) whose matrix puts the
        # face in the world — the owner above is what a click
        # selects. Run-length, one int per face: a Python object
        # per face doubled the cold build (30 → 65 ms).
        b_pidx: list = []
        b_plist: list = []
        b_v0, b_e1, b_e2, b_te = [], [], [], []
        b_area, b_vis, b_sel = [], [], []
        b_spans: list = []    # (bbox, tri start, count) per chunk
        # Group hard edges, flat — pick_group's fallback (cursor over
        # empty space / lines-only group) walked every group edge in
        # Python (~300 ms per mouse move against a 300k-edge import).
        b_gea, b_geb, b_ggi = [], [], []
        b_gsel: list = []     # per edge: may pick_group land on it
        b_ggroups: list = []
        # Lazy placements (#158) keep their triangles in their own
        # arrays — spans the ray walks as they are — and go after
        # the static chunks, whose concatenation is kept: joining
        # every array on each change of the lazy set copied
        # hundreds of MB per hover.
        b_own: list = []
        static_key: list = []
        count = 0
        for g, chunk, gvis, gsel, gsnap in chunks:
            n = len(chunk["faces"])
            off = n_ent + count
            owner = self._owner_of(g)
            # A chunk keeps its (face, owner) list: the block is
            # rebuilt whenever the lazy placements change (#158),
            # and re-making a tuple per face of everything already
            # in it cost ~250 ms a hover on 14 million faces.
            ents = chunk.get("_pick_ents")
            if ents is None or ents[0] is not owner:
                from views import array_bake
                if isinstance(chunk["faces"], array_bake.DeferredFaces):
                    # A lazy mesh (experimental engine): its faces
                    # are built when a pick lands on one.
                    pairs = array_bake.LazyPairs(chunk["faces"], owner)
                else:
                    pairs = [(f, owner) for f in chunk["faces"]]
                ents = chunk["_pick_ents"] = (owner, pairs)
            b_entities.append(ents[1])
            count += n
            b_pidx.append(np.full(n, n_plist + len(b_plist), dtype=np.int32))
            b_plist.append(g)
            b_area.append(chunk["areas"])
            b_vis.append(np.full(n, gvis, dtype=bool))
            b_sel.append(np.full(n, gsel, dtype=bool))
            if chunk["v0"] is not None and id(g) in lazy_set:
                b_own.append((chunk.get("bbox"), chunk["v0"],
                              chunk["e1"], chunk["e2"],
                              chunk["tri_ent"], off))
            elif chunk["v0"] is not None:
                static_key.append((chunk.get("uid", id(chunk)), chunk.get("rev"), off))
                v0, e1, e2, te, cells = _split_chunk_spans(chunk)
                b_v0.append(v0)
                b_e1.append(e1)
                b_e2.append(e2)
                b_te.append(te + off)
                if cells is None:
                    b_spans.append((chunk.get("bbox"), b_tri_off,
                                    len(v0)))
                else:
                    # One span per grid cell, each with its own box:
                    # a ray meets the cells it crosses, not the chunk.
                    b_spans += [(bb, b_tri_off + s0, n)
                                for bb, s0, n in cells]
                b_tri_off += len(v0)
            if gsnap and chunk["edges"]:
                ge = chunk.get("_pick_ge")
                if ge is None or ge[0] is not chunk["edges"]:
                    ge = chunk["_pick_ge"] = (
                        chunk["edges"],
                        np.frombuffer(chunk["edges"], dtype=np.float32)
                        .reshape(-1, 2, 3).astype(np.float64))
                ge = ge[1]
                b_gea.append(ge[:, 0])
                b_geb.append(ge[:, 1])
                b_ggi.append(np.full(len(ge), n_ggroups + len(b_ggroups),
                                     dtype=np.int64))
                b_gsel.append(np.full(len(ge), gsel, dtype=bool))
                b_ggroups.append(owner)
        part = {"entities": b_entities, "pidx": b_pidx, "plist": b_plist,
                "area": b_area, "vis": b_vis, "sel": b_sel,
                "own": b_own, "static_key": static_key,
                "v0": b_v0, "e1": b_e1, "e2": b_e2, "te": b_te,
                "spans": b_spans, "gea": b_gea, "geb": b_geb, "ggi": b_ggi,
                "gsel": b_gsel, "ggroups": b_ggroups,
                "n_ent": n_ent + count, "n_plist": n_plist + len(b_plist),
                "n_tri": b_tri_off,
                "n_ggroups": n_ggroups + len(b_ggroups)}
        if base is None:
            # The fixed part joins its own lists once, here: it is kept.
            for k in ("pidx", "area", "vis", "sel", "gea", "geb", "ggi",
                      "gsel"):
                part[k] = [np.concatenate(part[k])] if part[k] else []
            if all(isinstance(e, list) for e in b_entities):
                part["entities"] = [[x for e in b_entities for x in e]]
        return part

    def _pick_join_parts(self, fixed, lazy) -> dict:
        """The pick block of the fixed part followed by the lazy one — the
        very arrays the single pass made, in the same order."""
        import numpy as np
        from views.array_bake import PickEntities

        def cat(k, empty):
            parts = fixed[k] + lazy[k]
            return np.concatenate(parts) if parts else empty
        ents = fixed["entities"] + lazy["entities"]
        if not lazy["entities"] and len(ents) == 1 and \
                isinstance(ents[0], list):
            entities: list = ents[0]      # the fixed part's, kept
        elif all(isinstance(e, list) for e in ents) and \
                sum(map(len, ents)) < 200_000:
            entities = [x for e in ents for x in e]
        else:
            entities = PickEntities()
            for e in ents:
                entities.extend(e)
        static = fixed["static_key"] + lazy["static_key"]
        gea = fixed["gea"] + lazy["gea"]
        return {
            "entities": entities,
            "place_idx": cat("pidx", np.empty(0, np.int32)),
            "placements": fixed["plist"] + lazy["plist"],
            "areas": cat("area", np.empty(0)),
            "vis": cat("vis", np.empty(0, bool)),
            "sel": cat("sel", np.empty(0, bool)),
            **PickingMixin._pick_static_tris(self, tuple(static),
                                         fixed["v0"] + lazy["v0"],
                                         fixed["e1"] + lazy["e1"],
                                         fixed["e2"] + lazy["e2"],
                                         fixed["te"] + lazy["te"]),
            "own": fixed["own"] + lazy["own"],
            "gedge_a": np.concatenate(gea) if gea else None,
            "gedge_b": cat("geb", None) if gea else None,
            "gedge_gi": cat("ggi", None) if gea else None,
            "gedge_sel": cat("gsel", None) if gea else None,
            "gedge_groups": fixed["ggroups"] + lazy["ggroups"],
            "spans": fixed["spans"] + lazy["spans"],
        }

    def _pick_index(self, near=None):
        """Flat NumPy pick index of the scene — triangles of every loose and
        group face (with visibility/selectability masks and areas) plus the
        loose edges — rebuilt when the scene changes.

        Every mouse-move pick used to walk the mesh in Python re-running
        earcut per face (~1–2 s per move against an imported 17k-triangle
        building — the app read as frozen); batched over this index a pick
        is a couple of milliseconds.

        On a model whose component placements hold more than
        ``_PICK_LAZY_MIN_FACES`` faces, those placements enter only when a
        query comes near them (``near``, see ``_pick_materialize``): the
        rest of the index is the same."""
        if hasattr(self, "_pick_lazy_table"):
            # The snap asks occlusion hundreds of times per mouse move, each
            # through here: the same cursor query in the same tick has
            # nothing new to bake (#158).
            pos = getattr(self, "_last_mouse_pos", None)
            qkey = (getattr(self, "_tick", 0), _cache_ver(self),
                    (pos.x(), pos.y()) if near is None and pos is not None
                    else repr(near) if not isinstance(near, tuple) or
                    near[0] != "ray" else None)
            if qkey[2] is None or getattr(self, "_pick_last_q", None) != qkey:
                self._pick_materialize(near)
                self._pick_last_q = qkey
        oculto = getattr(self, "_rest_is_hidden", None)
        oculto = bool(oculto()) if callable(oculto) else False
        # The open context decides what a hit RESOLVES to (inside the
        # plaza its children are the objects, not the plaza): a stale index
        # kept answering "the plaza" after a double-click opened it, so the
        # arch inside never opened (Marco, 2026-09-14).
        key = (_cache_ver(self), id(self.scene.mesh), oculto,
               id(self.scene.edit_group), getattr(self, "_pick_gen", 0))
        cached = getattr(self, "_pick_index_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        if (cached is not None and len(cached) > 2
                and cached[0][:4] == key[:4]
                and getattr(self, "_frozen_cache_version", None) is not None
                and cached[2] is not None
                and cached[2] is getattr(self, "_pick_block", None)):
            # Only the lazy set moved, under a frozen preview (a drag): the
            # block is kept frozen as it is, the loose part is the same —
            # the rebuild would make this very index again (it did, ~35 ms
            # a pointer move dragging beside the plant of #158).
            self._pick_index_cache = (key, cached[1], cached[2])
            return cached[1]
        _p0 = _time_mod.perf_counter() if _PERF else 0.0
        import numpy as np
        from types import SimpleNamespace
        scene = self.scene
        entities: list = []           # (face, group_or_None)
        place_idx = None              # per entity: index into placements, -1 = loose
        placements: list = []
        ent_area: list = []
        ent_sel: list = []
        ent_vis: list = []
        ent_loose: list = []
        tris: list = []
        tri_ent: list = []

        # Stub viewports in tests call this unbound — fall back to the
        # uncached face methods when the memo helpers aren't there.
        area_of = getattr(self, "_area_of", None) or (lambda f: f.area())
        tris_of = getattr(self, "_tris_of", None) or \
            (lambda f: f.triangulate())

        def add_face(f, grp, vis, sel):
            i = len(entities)
            entities.append((f, grp))
            ent_area.append(area_of(f))
            ent_vis.append(vis)
            ent_sel.append(sel)
            ent_loose.append(grp is None)
            for t0, t1, t2 in tris_of(f):
                tris.append((t0.x(), t0.y(), t0.z(),
                             t1.x(), t1.y(), t1.z(),
                             t2.x(), t2.y(), t2.z()))
                tri_ent.append(i)

        for f in scene.faces:
            add_face(f, None, scene.entity_visible(f),
                     scene.entity_selectable(f))

        # Loose part → arrays; groups append their cached chunk arrays.
        if tris:
            t = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
            v0s = [t[:, 0]]
            e1s = [t[:, 1] - t[:, 0]]
            e2s = [t[:, 2] - t[:, 0]]
            tents = [np.asarray(tri_ent, dtype=np.int64)]
        else:
            v0s, e1s, e2s, tents = [], [], [], []
        areas = [np.asarray(ent_area, dtype=np.float64)]
        vis_parts = [np.asarray(ent_vis, dtype=bool)]
        sel_parts = [np.asarray(ent_sel, dtype=bool)]
        loose_parts = [np.asarray(ent_loose, dtype=bool)]

        # Per-chunk triangle spans (P3): a hover/zoom ray prefilters chunks
        # by AABB and runs Möller-Trumbore only on the spans it crosses.
        tri_spans: list = [(None, 0, len(tris))] if tris else []
        own_spans: list = []      # lazy placements' own arrays (#158)
        # What the current context lets you TOUCH: the whole scene at the
        # root, the children of the group you are inside otherwise. This
        # used to be `if scene.edit_group is None`, which took EVERY group
        # out of the index while you were inside one — so a group's children
        # were drawn and could not be clicked, and «todo está combinado»
        # (Marco, 2026-09-11).
        del_contexto = self._context_placements()
        tocables = {id(g) for g in del_contexto}
        # What the snap engine may LAND ON is the whole model. Inside a
        # group the snap still infers against the rest — faded, but every
        # corner and edge of it is a reference. Holding only the context
        # here meant no green dot on the pavement while moving a nested
        # group onto it («me debería salir un punto verde de la referencia»,
        # Marco, 2026-09-11). So the index carries every placement and the
        # context decides SELECTABILITY, not membership: the rest occludes
        # and snaps, and cannot be picked. What the open group itself owns is
        # already here as the loose part. «Hide» is the exception — what is
        # not drawn is not there.
        ctx = scene.edit_group
        if ctx is None or oculto:
            candidatos = del_contexto
        else:
            candidatos = [g for g in self._placements()
                          if g is not ctx and self._owner_of(g) is not ctx]
        lazy = (self._pick_lazy_table()
                if hasattr(self, "_pick_lazy_table") else None)
        if lazy is not None:
            live = getattr(self, "_pick_live", None) or {}
            lazy_ids = lazy[4]
            candidatos = [g for g in candidatos
                          if id(g) not in lazy_ids or id(g) in live]
        if candidatos:
            # The group block is cached across versions (keyed by each
            # chunk's identity + rev + flags): re-deriving per-face masks and
            # re-offsetting 300k triangle rows per scene change cost ~130 ms
            # per stroke/drag frame beside a big import.
            # The block (every placement's faces, owners and hard edges) is
            # keyed on the placements epoch: a loose edit — every frame of a
            # Move drag — no longer walks 1 300 chunks to learn that none of
            # them changed (2026-09-14).
            epoch_of = getattr(self, "_placements_epoch", None)   # stub VPs in tests
            sig = (epoch_of() if epoch_of is not None else _cache_ver(self),
                   oculto, len(candidatos), getattr(self, "_pick_gen", 0))
            blk = getattr(self, "_pick_block", None)
            frozen = getattr(self, "_frozen_cache_version", None) is not None
            if blk is None or (blk[0] != sig and not frozen):
                # Two parts, fixed placements first, as the block always
                # ran: the fixed part lasts while the placements do, and a
                # change of the lazy set rebuilds only the lazy part on its
                # offsets. Re-making the fixed one each time (900
                # placements, half a million faces) was most of every hover
                # that met new lazy placements on the plant of #158.
                lazy_set = (lazy[4] if lazy is not None else ())
                fixed = [g for g in candidatos if id(g) not in lazy_set]
                lazies = [g for g in candidatos if id(g) in lazy_set]
                fkey = (sig[0], oculto, len(fixed), id(scene.edit_group))
                fpart = getattr(self, "_pick_fixed_part", None)
                if fpart is None or fpart[0] != fkey:
                    # Called through the class: the stub viewports of the
                    # tests run this unbound.
                    fpart = self._pick_fixed_part = (fkey, PickingMixin._pick_block_part(
                        self, fixed, tocables, lazy_set, None))
                lpart = PickingMixin._pick_block_part(self, lazies, tocables,
                                                  lazy_set, fpart[1])
                blk = (sig, PickingMixin._pick_join_parts(self, fpart[1], lpart))
                self._pick_block = blk
            block = blk[1]
            if block["entities"]:
                offset = len(entities)
                loose_count = len(entities)
                if not isinstance(block["entities"], list):
                    from views.array_bake import PickEntities
                    entities = PickEntities(entities)
                entities.extend(block["entities"])
                place_idx = np.concatenate([
                    np.full(loose_count, -1, dtype=np.int32),
                    block.get("place_idx", np.full(len(block["entities"]), -1, np.int32))])
                placements = block.get("placements", [])
                areas.append(block["areas"])
                vis_parts.append(block["vis"])
                sel_parts.append(block["sel"])
                loose_parts.append(
                    np.zeros(len(block["entities"]), dtype=bool))
                if block["v0"] is not None:
                    v0s.append(block["v0"])
                    e1s.append(block["e1"])
                    e2s.append(block["e2"])
                    tents.append(block["te"] + offset)
                    tri_spans += [(bb, len(tris) + s, n)
                                  for bb, s, n in block.get("spans", ())]
                own_spans = [(bb, a, b, c, te, o + offset)
                             for bb, a, b, c, te, o in block.get("own", ())]

        gedge_a = gedge_b = gedge_gi = gedge_sel = None
        gedge_groups: list = []
        if candidatos:
            block = self._pick_block[1] if getattr(self, "_pick_block", None) \
                else {}
            gedge_a = block.get("gedge_a")
            gedge_b = block.get("gedge_b")
            gedge_gi = block.get("gedge_gi")
            gedge_sel = block.get("gedge_sel")
            gedge_groups = block.get("gedge_groups", [])

        edges: list = []
        ea: list = []
        eb: list = []
        esel: list = []
        esoft: list = []
        for e in scene.edges:
            edges.append(e)
            esoft.append(bool(getattr(e, "soft", False)))
            ea.append([e.a.x(), e.a.y(), e.a.z()])
            eb.append([e.b.x(), e.b.y(), e.b.z()])
            # A hidden EDGE (Hide on raw geometry, a smoothed surface's
            # inner edges) is selectable only while the hidden view shows
            # it — what window selection already did; a click found it
            # through here with the view off.
            esel.append(scene.entity_selectable(e)
                        and (not getattr(e, "hidden", False)
                             or bool(getattr(scene, "show_hidden_geometry",
                                             False))))

        idx = SimpleNamespace(
            entities=entities,
            ent_place_idx=(place_idx if place_idx is not None
                           else np.full(len(entities), -1, np.int32)),
            ent_placements=placements,
            ent_area=np.concatenate(areas) if entities else np.empty(0),
            ent_sel=np.concatenate(sel_parts) if entities else np.empty(0, bool),
            ent_vis=np.concatenate(vis_parts) if entities else np.empty(0, bool),
            ent_loose=(np.concatenate(loose_parts) if entities
                       else np.empty(0, bool)),
            tri_v0=np.concatenate(v0s) if v0s else None,
            tri_e1=np.concatenate(e1s) if v0s else None,
            tri_e2=np.concatenate(e2s) if v0s else None,
            tri_ent=np.concatenate(tents) if v0s else None,
            edges=edges,
            edge_a=np.asarray(ea, dtype=np.float64) if edges else None,
            edge_b=np.asarray(eb, dtype=np.float64) if edges else None,
            edge_sel=np.asarray(esel, dtype=bool) if edges else None,
            edge_soft=np.asarray(esoft, dtype=bool) if edges else None,
            gedge_a=gedge_a,
            gedge_b=gedge_b,
            gedge_gi=gedge_gi,
            gedge_sel=gedge_sel,
            gedge_groups=gedge_groups,
            tri_spans=None,
        )
        # Spans must tile the triangle array exactly, or the prefilter would
        # silently drop triangles (a stale cached block predating spans).
        total_tris = len(idx.tri_v0) if idx.tri_v0 is not None else 0
        if tri_spans and sum(n for _, _, n in tri_spans) == total_tris:
            idx.tri_spans = tri_spans
        idx.own_spans = own_spans
        if _PERF:
            _plog("pick_index", (_time_mod.perf_counter() - _p0) * 1000.0)
        self._pick_index_cache = (key, idx, getattr(self, "_pick_block", None))
        return idx

    def _pick_static_tris(self, key, v0, e1, e2, te) -> dict:
        """The static chunks' triangles joined, kept while the same chunks
        sit at the same entity offsets: the lazy set changes on many
        hovers (#158), the static part does not."""
        import numpy as np
        memo = getattr(self, "_pick_static_memo", None)
        if memo is not None and memo[0] == key:
            return memo[1]
        out = {"v0": np.concatenate(v0) if v0 else None,
               "e1": np.concatenate(e1) if v0 else None,
               "e2": np.concatenate(e2) if v0 else None,
               "te": np.concatenate(te) if v0 else None}
        self._pick_static_memo = (key, out)
        return out

    @staticmethod
    def _pick_flat(idx):
        """``idx`` with the lazy placements' own spans joined into the flat
        triangle arrays — for the passes that read every triangle (hidden
        lines, section cuts); kept on the index once made."""
        own = getattr(idx, "own_spans", None)
        if not own:
            return idx
        flat = getattr(idx, "_flat", None)
        if flat is not None:
            return flat
        import numpy as np
        from types import SimpleNamespace
        parts = ([(idx.tri_v0, idx.tri_e1, idx.tri_e2, idx.tri_ent)]
                 if idx.tri_v0 is not None else [])
        parts += [(a, b, c, te + o) for _bb, a, b, c, te, o in own]
        flat = SimpleNamespace(**vars(idx))
        flat.tri_v0 = np.concatenate([p[0] for p in parts])
        flat.tri_e1 = np.concatenate([p[1] for p in parts])
        flat.tri_e2 = np.concatenate([p[2] for p in parts])
        flat.tri_ent = np.concatenate([p[3] for p in parts])
        flat.tri_spans = None
        flat.own_spans = []
        idx._flat = flat
        return flat

    def ray_distance(self, origin: QVector3D, direction: QVector3D,
                     reach: float | None = None):
        """Distance along ``direction`` (unit) from ``origin`` to the nearest
        VISIBLE face, or ``None`` when the ray meets nothing. What the
        walkthrough tools ask — the floor under the eye, the wall ahead —
        over the same index every pick uses (hidden objects and hidden
        layers are not there to bump into). With ``reach``, only faces
        within that distance count: the query bakes and tests only what
        lies within it."""
        near = (("ray", origin, direction) if reach is None
                else ("ray", origin, direction, float(reach)))
        idx = self._pick_index(near=near)
        if idx is None or (getattr(idx, "tri_v0", None) is None
                           and not getattr(idx, "own_spans", None)):
            return None
        t = self._ray_hits(idx, origin, direction, idx.ent_vis,
                           reduce_global=True, reach=reach)
        if t is None or t == float("inf") or (reach is not None
                                               and t > reach):
            return None
        return float(t)

    def _ray_hits(self, idx, origin, direction, ent_mask,
                  reduce_global: bool = False, reach: float | None = None):
        """Per-entity nearest ray parameter over the index triangles whose
        entity passes ``ent_mask``. Returns an (E,) array of t (``inf`` = no
        hit), the single nearest t as a float when ``reduce_global``, or
        ``None`` when the index has no triangles. Same acceptance
        thresholds as :func:`_ray_triangle`.

        P3: the Möller–Trumbore pass runs per chunk SPAN on array views,
        after a ray-vs-AABB prefilter — a hover/zoom ray only pays for the
        chunks it actually crosses (the full 700k-row pass cost 25–45 ms
        per pick against the piscina scene)."""
        import numpy as np
        own = getattr(idx, "own_spans", None) or ()
        if idx.tri_v0 is None and not own:
            return None
        o = np.array([origin.x(), origin.y(), origin.z()])
        d = np.array([direction.x(), direction.y(), direction.z()])
        if idx.tri_v0 is None:
            spans = []
        else:
            spans = (getattr(idx, "tri_spans", None)
                     or [(None, 0, len(idx.tri_v0))])
        # Lazy placements' own arrays (#158) ride the same loop: a span is
        # then (bbox, v0, e1, e2, local tri_ent, entity offset).
        spans = list(spans) + list(own)
        if len(spans) > 64:
            # Thousands of spans on a huge model: which boxes the ray meets
            # is one NumPy pass, not a Python test per span (900 000 of
            # them in one snap hover, #158).
            boxes = getattr(idx, "_span_boxes", None)
            if boxes is None or boxes[0] != len(spans):
                inf = float("inf")
                blo = np.array([sp[0][0] if sp[0] is not None else (-inf,) * 3
                                for sp in spans], dtype=np.float64)
                bhi = np.array([sp[0][1] if sp[0] is not None else (inf,) * 3
                                for sp in spans], dtype=np.float64)
                boxes = idx._span_boxes = (len(spans), blo, bhi)
            _n, blo, bhi = boxes
            with np.errstate(divide="ignore", invalid="ignore"):
                inv_d = 1.0 / np.where(np.abs(d) > 1e-12, d, 1e-12)
                t1 = (blo - o) * inv_d
                t2 = (bhi - o) * inv_d
            tmin = np.nanmax(np.minimum(t1, t2), axis=1)
            tmax = np.nanmin(np.maximum(t1, t2), axis=1)
            meet = tmax >= np.maximum(tmin, 0.0)
            if reach is not None:
                meet &= tmin <= reach
            spans = [(None,) + tuple(spans[i][1:])
                     for i in np.flatnonzero(meet)]
        o3 = (float(o[0]), float(o[1]), float(o[2]))
        d3 = (float(d[0]), float(d[1]), float(d[2]))
        lim = float("inf") if reach is None else float(reach)
        best = float("inf")
        face_t = None if reduce_global else np.full(len(idx.entities), np.inf)
        # The static spans the ray meets go through Möller–Trumbore in ONE
        # pass: with the span grid a ray meets dozens of small spans, and a
        # NumPy call per span (~30 µs) became the ray's whole cost.
        ranges = []
        rest = []
        for span in spans:
            if len(span) == 3:
                bb, s0, n = span
                if n and (bb is None or _ray_aabb(o3, d3, bb[0], bb[1])):
                    ranges.append((s0, n))
            else:
                rest.append(span)
        if ranges:
            if len(ranges) == 1:
                s0, n = ranges[0]
                sel = slice(s0, s0 + n)
            else:
                sel = np.concatenate([np.arange(s0, s0 + n)
                                      for s0, n in ranges])
            rest.insert(0, (None, idx.tri_v0[sel], idx.tri_e1[sel],
                            idx.tri_e2[sel], idx.tri_ent[sel], 0))
        spans = rest
        for span in spans:
            if len(span) == 3:
                bb, s0, n = span
                if not n:
                    continue
                if bb is not None and not _ray_aabb(o3, d3, bb[0], bb[1],
                                                    lim):
                    continue
                v0 = idx.tri_v0[s0:s0 + n]
                e1 = idx.tri_e1[s0:s0 + n]
                e2 = idx.tri_e2[s0:s0 + n]
                te = idx.tri_ent[s0:s0 + n]
            else:
                bb, v0, e1, e2, te_local, eoff = span
                if not len(v0):
                    continue
                if bb is not None and not _ray_aabb(o3, d3, bb[0], bb[1],
                                                    lim):
                    continue
                te = te_local + eoff
            p = np.cross(d, e2)
            det = np.einsum("ij,ij->i", e1, p)
            ok = np.abs(det) > 1e-6
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            s = o - v0
            u = np.einsum("ij,ij->i", s, p) * inv
            q = np.cross(s, e1)
            v = (q @ d) * inv
            t = np.einsum("ij,ij->i", e2, q) * inv
            hit = (ok & (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (u + v <= 1.0)
                   & (t > 1e-6) & ent_mask[te])
            if reduce_global:
                # Zoom focus wants ONE nearest t, not per-entity buckets.
                th = t[hit]
                if len(th):
                    tm = float(th.min())
                    if tm < best:
                        best = tm
            else:
                hit_rows = np.where(hit)[0]
                if len(hit_rows):
                    # minimum.at only over the triangles the ray actually
                    # hits (a handful) — over the full array it alone cost
                    # ~100 ms per snap hover.
                    np.minimum.at(face_t, te[hit_rows], t[hit_rows])
        return best if reduce_global else face_t

    def _hover_face_t(self, idx, origin, direction):
        """Per-entity nearest-hit ``t`` against every *selectable* entity,
        memoised for the current cursor ray. One SelectTool hover fires
        pick_group + pick_face on the same mouse move, and each used to re-run
        the full Möller–Trumbore pass (~20 ms over a 260k-triangle import);
        they now share one pass and post-mask by loose/group."""
        key = (self.scene.version, id(self.scene.mesh),
               origin.x(), origin.y(), origin.z(),
               direction.x(), direction.y(), direction.z())
        cached = getattr(self, "_hover_hits_cache", None)
        # The answer is per entity OF THIS INDEX: a lazy index (#158) is
        # rebuilt between two asks of one hover when a query brings new
        # placements in, and the old index's per-entity times read against
        # the new one picked the wrong face, or ran past its end.
        if cached is not None and cached[0] == key and cached[2] is idx:
            return cached[1]
        face_t = self._ray_hits(idx, origin, direction, idx.ent_sel)
        sp = _active_cut(self.scene)
        if sp is not None and face_t is not None:
            # Hits beyond the active cut are on clipped-away geometry.
            import numpy as np
            finite = np.isfinite(face_t)
            if finite.any():
                o = np.array([origin.x(), origin.y(), origin.z()])
                d = np.array([direction.x(), direction.y(), direction.z()])
                n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
                c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
                pts = o + d * face_t[finite, None]
                hidden = (pts @ n - c) > 1e-6
                vals = face_t[finite]
                vals[hidden] = np.inf
                face_t[finite] = vals
        self._hover_hits_cache = (key, face_t, idx)
        return face_t

    def edge_point_under_cursor(self, edge, screen_x: float, screen_y: float):
        """The world point of ``edge`` nearest the cursor (closest point of
        its screen-space segment, mapped back along the edge), or None when
        the edge does not project."""
        pa = self._world_to_pixel(edge.a)
        pb = self._world_to_pixel(edge.b)
        if pa is None or pb is None:
            return None
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        l2 = dx * dx + dy * dy
        if l2 < 1e-12:
            return QVector3D(edge.a)
        t = ((screen_x - pa[0]) * dx + (screen_y - pa[1]) * dy) / l2
        t = max(0.0, min(1.0, t))
        return edge.a + (edge.b - edge.a) * t

    def pick_edge(self, screen_x: float, screen_y: float):
        """Return the edge closest to ``(screen_x, screen_y)`` within threshold."""
        return self._pick_edge(screen_x, screen_y, visible_only=False)

    def pick_visible_edge(self, screen_x: float, screen_y: float):
        """The edge a CLICK means: like :meth:`pick_edge`, but an edge the
        user cannot see never wins — a soft edge (the seams of a smooth
        surface, which are not drawn) unless hidden geometry is shown, and
        an edge behind the model. The usual rule, and what made a
        cylinder's side unclickable (@pacaeiro, issue #71: the invisible
        seams, front and back, took up to 90 % of the side at normal zoom).
        Tools that want the tube's seam as a reference keep pick_edge."""
        return self._pick_edge(screen_x, screen_y, visible_only=True)

    def _pick_edge(self, screen_x: float, screen_y: float,
                   visible_only: bool):
        import numpy as np
        idx = self._pick_index(near="skip")
        if idx.edge_a is None:
            return None
        ax, ay, oka = self._project_px(idx.edge_a)
        bx, by, okb = self._project_px(idx.edge_b)
        ok = oka & okb & idx.edge_sel
        soft = getattr(idx, "edge_soft", None)
        if (visible_only and soft is not None
                and not getattr(self.scene, "show_hidden_geometry", False)):
            ok &= ~soft
        sp = _active_cut(self.scene)
        if sp is not None:
            n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
            c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
            da = idx.edge_a @ n - c
            db = idx.edge_b @ n - c
            ok &= ~((da > 1e-6) & (db > 1e-6))
        if not ok.any():
            return None
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        safe = np.where(l2 > 1e-12, l2, 1.0)
        t = np.clip(((screen_x - ax) * dx + (screen_y - ay) * dy) / safe,
                    0.0, 1.0)
        d = np.hypot(ax + t * dx - screen_x, ay + t * dy - screen_y)
        d = np.where(ok, d, np.inf)
        if not visible_only:
            i = int(np.argmin(d))
            return idx.edges[i] if d[i] < self.pick_threshold_px else None
        # Nearest first, skipping the ones hidden behind the model; a few
        # tries are plenty (the threshold holds only a handful).
        for i in np.argsort(d)[:8]:
            i = int(i)
            if not d[i] < self.pick_threshold_px:
                return None
            e = idx.edges[i]
            p = self.edge_point_under_cursor(e, screen_x, screen_y)
            if p is None or not self._is_occluded(p):
                return e
        return None

    def pick_dimension(self, screen_x: float, screen_y: float):
        """Return the dimension whose lines (extension + dimension line) are
        closest to the cursor within the pick threshold, or ``None``."""
        dims = getattr(self.scene, "dimensions", None)
        if not dims:
            return None
        best = None
        best_d = self.pick_threshold_px
        for dim in dims:
            if not self.scene.entity_selectable(dim):   # hidden / locked
                continue
            ap, bp = dim.line_points()
            for s, e in ((dim.a, ap), (dim.b, bp), (ap, bp)):
                ps = self._world_to_pixel(s)
                pe = self._world_to_pixel(e)
                if ps is None or pe is None:
                    continue
                d = _point_to_segment_distance_2d((screen_x, screen_y), ps, pe)
                if d < best_d:
                    best_d = d
                    best = dim
        return best

    def pick_text_label(self, screen_x: float, screen_y: float,
                        rect_only: bool = False):
        """Return the leader-text label under the cursor, or ``None``.

        A click anywhere on the drawn text block (same font-metrics layout
        as ``_draw_text_labels``) is a hit — the glyphs are what the user
        aims at. Failing that, the label position and the leader line count
        within the pick threshold. ``rect_only`` restricts to the text
        block: the block overdraws all geometry, so that hit outranks edge
        and face picks, while the (thin) leader keeps normal priority."""
        labels = getattr(self.scene, "text_labels", None)
        if not labels:
            return None
        style = getattr(self.scene, "dimension_style", {})
        font = QFont()
        font.setPointSize(int(style.get("font_size", 9)))
        font.setBold(True)
        # Measured on THIS widget, as the painter that draws the labels
        # does: bare QFontMetrics(font) reads the primary screen's DPI, and
        # on a scaled display the glyph box it gave missed the letters
        # (Marco, 2026-09-23: the eraser only took a text by its leader).
        from PySide6.QtGui import QPaintDevice
        fm = (QFontMetrics(font, self) if isinstance(self, QPaintDevice)
              else QFontMetrics(font))        # the test stubs bind this
        best, best_d = None, self.pick_threshold_px * 2.0
        for lab in labels:
            if not self.scene.entity_selectable(lab):   # hidden / locked
                continue
            pp = self._world_to_pixel(lab.position())
            if pp is None:
                continue
            pa = self._world_to_pixel(lab.anchor)
            # The text block: lines start at _text_block_x(...), first
            # baseline at pp.y - 4, one fm.height() apart (mirror of
            # _draw_text_labels).
            lines = lab.text.splitlines() or [""]
            x0 = self._text_block_x(
                pp, pa, max(fm.horizontalAdvance(ln) for ln in lines))
            for i, line in enumerate(lines):
                base = pp[1] - 4 + i * fm.height()
                if (x0 - 3 <= screen_x <= x0 + fm.horizontalAdvance(line) + 3
                        and base - fm.ascent() - 3 <= screen_y
                        <= base + fm.descent() + 3):
                    return lab
            if rect_only:
                continue
            d = math.hypot(pp[0] - screen_x, pp[1] - screen_y)
            if pa is not None:
                d = min(d, _point_to_segment_distance_2d(
                    (screen_x, screen_y), pa, pp))
            if d < best_d:
                best_d = d
                best = lab
        return None if rect_only else best

    def pick_geopath(self, screen_x: float, screen_y: float):
        """Return the georef path whose polyline is closest to the cursor within
        the pick threshold, or ``None`` (Track G)."""
        paths = getattr(self.scene, "geo_paths", None)
        if not paths:
            return None
        best, best_d = None, self.pick_threshold_px
        for path in paths:
            for a, b in path.segments():
                pa = self._world_to_pixel(self.drape(a))
                pb = self._world_to_pixel(self.drape(b))
                if pa is None or pb is None:
                    continue
                d = _point_to_segment_distance_2d((screen_x, screen_y), pa, pb)
                if d < best_d:
                    best_d = d
                    best = path
        return best

    def pick_axis(self, screen_x: float, screen_y: float):
        """The model axis line under the cursor — ``"x"`` / ``"y"`` /
        ``"z"`` — or ``None``. The Tape reads an axis as a guide source
        (Rafael, Revisión 3: «pinchas el eje y sacas una guía
        paralela a 20 m del origen» before anything is drawn)."""
        from core.guide import GUIDE_HALF_LEN
        from core import axes as _axes
        best, best_d = None, self.pick_threshold_px
        o = _axes.origin()
        for name in ("x", "y", "z"):
            d = _axes.axis(name) * GUIDE_HALF_LEN
            seg = self._clip_segment_front(o - d, o + d)
            if seg is None:
                continue
            pa = self._world_to_pixel(seg[0])
            pb = self._world_to_pixel(seg[1])
            if pa is None or pb is None:
                continue
            dist = _point_to_segment_distance_2d((screen_x, screen_y), pa, pb)
            if dist < best_d:
                best_d = dist
                best = name
        return best

    def _axis_source_visible(self, name: str, point: QVector3D) -> bool:
        """Whether an axis has a visible screen direction at ``point``.

        An axis viewed end-on has no usable screen direction; near its
        vanishing point a small world step must still move visibly on screen.
        """
        from core import axes as _axes
        axis = _axes.axis(name)
        half_step = 0.25
        before = self._world_to_pixel(point - axis * half_step)
        after = self._world_to_pixel(point + axis * half_step)
        if before is None or after is None:
            return False
        return math.hypot(after[0] - before[0],
                          after[1] - before[1]) >= 0.5

    def pick_guide(self, screen_x: float, screen_y: float):
        """Return the construction guide nearest the cursor within the pick
        threshold, or ``None`` (for the Eraser)."""
        guides = getattr(self.scene, "guides", None)
        if not guides:
            return None
        best, best_d = None, self.pick_threshold_px
        for g in guides:
            seg = self._clip_segment_front(*g.segment())
            if seg is None:
                continue
            pa = self._world_to_pixel(seg[0])
            pb = self._world_to_pixel(seg[1])
            if pa is None or pb is None:
                continue
            d = _point_to_segment_distance_2d((screen_x, screen_y), pa, pb)
            if d < best_d:
                best_d = d
                best = g
        return best

    def pick_vertex(self, screen_x: float, screen_y: float):
        """Return the scene vertex (corner) closest to the cursor within the
        pick threshold, or ``None``. Used to acquire a corner as a 'from point'
        reference while drawing. Occluded vertices are ignored (tested in
        ascending screen distance, so the nearest visible corner wins — the
        same answer the old per-edge scan produced)."""
        import numpy as np
        idx = self._pick_index(near=("px", screen_x, screen_y))
        # On the projections the viewport already caches per camera pose
        # (this runs on EVERY hover now — encouraged points): one numpy
        # distance pass, no re-projection of the model per mouse move.
        xs, ys, oks = [], [], []
        n = 0
        ledge = getattr(self, "_ledge_screen", None)      # stub VPs in tests
        lp = ledge() if ledge is not None else None
        if lp is None and idx.edge_a is not None and len(idx.edge_a):
            ax, ay, oka = self._project_px(idx.edge_a)
            bx, by, okb = self._project_px(idx.edge_b)
            lp = (ax, ay, bx, by, oka & okb)
        if lp is not None:
            ax, ay, bx, by, ok = lp
            xs += [ax, bx]; ys += [ay, by]; oks += [ok, ok]
            n = len(idx.edges)
        m = 0
        gp = self._gedge_screen()
        if gp is not None:
            # Group corners too — dimensioning/drawing over an imported
            # reference model needs its vertices as 'from points'.
            ax, ay, bx, by, ok = gp
            xs += [ax, bx]; ys += [ay, by]; oks += [ok, ok]
            m = len(idx.gedge_a)
        if not xs:
            return None
        # The concatenation is the same until the scene or camera moves.
        ckey = (id(lp), id(gp), n, m)
        cat = getattr(self, "_vertex_px_cache", None)
        if cat is None or cat[0] != ckey:
            cat = (ckey, np.concatenate(xs), np.concatenate(ys), np.concatenate(oks))
            self._vertex_px_cache = cat
        _c, px, py, ok = cat
        d = np.where(ok, np.hypot(px - screen_x, py - screen_y), np.inf)
        cand = np.where(d < self.pick_threshold_px)[0]

        def vertex_of(i):
            if i < 2 * n:
                e = idx.edges[int(i) % n]
                return e.a if i < n else e.b
            j = int(i) - 2 * n
            arr = idx.gedge_a if j < m else idx.gedge_b
            p = arr[j % m]
            return QVector3D(p[0], p[1], p[2])
        order = cand[np.argsort(d[cand])]
        if not len(order):
            return None
        # The nearest one, alone first (usually the answer); then the
        # rest in batches of 8, 16, 32… sharing one occlusion pass, as the
        # snap engine reads its candidates. One ray per candidate, in turn,
        # took minutes a pointer move over a dense mesh whose hundreds of
        # nearby corners were nearly all hidden (a 128 788-face STL in #158).
        first = vertex_of(order[0])
        if not self._is_occluded(first):
            return first
        many = getattr(self, "_occluded_many", None)
        k, size = 1, 8
        while k < len(order):
            batch = [vertex_of(i) for i in order[k:k + size]]
            hidden = (many(batch) if many is not None
                      else [self._is_occluded(v) for v in batch])
            for v, h in zip(batch, hidden):
                if not h:
                    return v
            k += size
            size *= 2
        return None

    def pick_face(self, screen_x: float, screen_y: float):
        """Return the face the cursor ray hits, or ``None``.

        Normally that's the front-most face. But when several *coplanar* faces
        overlap at the cursor — e.g. a small rectangle drawn on a larger face
        that didn't subdivide it — the ray hits them at the same depth. In that
        case prefer the smallest one, so push/pull and select grab the inner
        face the user is pointing at instead of the big face behind it (the
        old behaviour silently pushed the whole face)."""
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        import numpy as np
        idx = self._pick_index(near=("px", screen_x, screen_y))
        if not idx.entities:
            return None
        face_t = self._hover_face_t(idx, origin, direction)
        if face_t is None:
            return None
        face_t = np.where(idx.ent_loose, face_t, np.inf)
        best_t = face_t.min()
        if not np.isfinite(best_t):
            return None
        eps = self._coplanar_eps(origin, direction, float(best_t))
        cand = np.where(face_t <= best_t + eps)[0]
        if len(cand) == 1:
            return idx.entities[int(cand[0])][0]
        return idx.entities[int(cand[np.argmin(idx.ent_area[cand])])][0]

    def pick_face_any(self, screen_x: float, screen_y: float):
        """Front-most face under the cursor across the loose mesh **and** every
        group: returns ``(face, group_or_None)``. Same coplanar tiebreak as
        :meth:`pick_face` (the smallest of the overlapping faces wins). The
        group half is what lets a tool tell "this face is inside a container"
        — drawing takes its plane, Push/Pull refuses it until the group is
        opened. While a group IS open its own faces are the loose part and
        come back with ``None``; the model around it is in the index for
        snapping and occlusion only, never as an answer here.

        Memoised per cursor position and view: a hover asks up to three
        times (work plane, acquisition, on-face flag) for the same answer."""
        idx = self._pick_index(near=("px", screen_x, screen_y))
        try:
            cam = self.camera
            key = (round(screen_x, 2), round(screen_y, 2), id(idx),
                   cam.yaw, cam.pitch, cam.distance, cam.perspective,
                   cam.target.x(), cam.target.y(), cam.target.z(),
                   self.width(), self.height())
        except AttributeError:            # a bare stand-in (tests): no memo
            key = None
        cached = getattr(self, "_face_any_memo", None)
        # Keyed by the index itself, not its id(): a rebuilt index can be
        # given the address of the one it replaced.
        if (key is not None and cached is not None and cached[0] == key
                and len(cached) > 2 and cached[2] is idx):
            return cached[1]
        result = (None, None)
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is not None and direction is not None and idx.entities:
            import numpy as np
            face_t = self._hover_face_t(idx, origin, direction)
            if face_t is not None:
                best_t = face_t.min()
                if np.isfinite(best_t):
                    eps = self._coplanar_eps(origin, direction, float(best_t))
                    cand = np.where(face_t <= best_t + eps)[0]
                    if len(cand) == 1:
                        chosen = int(cand[0])
                    else:
                        chosen = int(cand[np.argmin(idx.ent_area[cand])])
                    result = idx.entities[chosen]
                    self._face_any_index = chosen
        if key is not None:
            self._face_any_memo = (key, result, idx)
        return result

    def pick_face_placement(self, screen_x: float, screen_y: float):
        """Like :meth:`pick_face_any`, but the group half is the PLACEMENT
        the face was hit through — the proxy whose composed matrix puts it
        in the world — not the top-level owner a click would select. What
        every face-PLANE reading needs: the owner of a nested component
        carries the container's matrix, so a rectangle on the pergola's
        post got the post's plane in the wrong place (Marco, 2026-09-14)."""
        face, owner = self.pick_face_any(screen_x, screen_y)
        if face is None:
            return None, None
        idx = self._pick_index(near=("px", screen_x, screen_y))
        i = getattr(self, "_face_any_index", None)
        pidx = getattr(idx, "ent_place_idx", None)
        if (pidx is not None and i is not None and i < len(pidx)
                and idx.entities[i][0] is face and pidx[i] >= 0):
            return face, idx.ent_placements[int(pidx[i])]
        return face, owner

    def pick_group(self, screen_x: float, screen_y: float):
        """The group whose geometry the cursor hits (front-most face, or nearest
        edge for a group that's only lines), or ``None``."""
        if (self.scene.edit_group is not None
                and not getattr(self.scene.edit_group, "children", None)):
            return None                     # inside a plain group: its content
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is not None and direction is not None:
            import numpy as np
            best = None  # (t, group)
            idx = self._pick_index(near=("px", screen_x, screen_y))
            loose_t = np.inf
            if idx.entities:
                face_t = self._hover_face_t(idx, origin, direction)
                if face_t is not None:
                    loose_t = float(np.where(idx.ent_loose, face_t,
                                             np.inf).min())
                    face_t = np.where(idx.ent_loose, np.inf, face_t)
                    i = int(np.argmin(face_t))
                    if np.isfinite(face_t[i]):
                        best = (float(face_t[i]), idx.entities[i][1])
            for g in self._context_placements():
                # The figure test first: it is an attribute, the layer test
                # walks tags — asked of every placement on every hover it
                # cost ~90 ms on 21 406 placements (issue #158).
                if not getattr(g, "billboard", False):
                    continue
                if not self.scene.entity_selectable(g):
                    continue                    # hidden or locked layer
                if True:
                    quad = self._billboard_quad(g)
                    if quad is not None:
                        c = quad[0]
                        for tri in ((c[0], c[1], c[2]), (c[0], c[2], c[3])):
                            t = _ray_triangle(origin, direction, *tri)
                            if t is not None and (best is None or t < best[0]):
                                best = (t, self._owner_of(g))
            if best is not None:
                # A loose face clearly in FRONT hides the group: what the
                # cursor shows is that face, and every caller asks for the
                # group it can see (#276, #363, #378 — a loose box before
                # a component could not be clicked). Coplanar faces keep
                # the old answer.
                eps = self._coplanar_eps(origin, direction, best[0])
                if np.isfinite(loose_t) and loose_t < best[0] - eps:
                    return None
                return best[1]
        # Edge fallback (cursor over empty space, or a lines-only group):
        # screen-space distance to every group hard edge, batched over the
        # cached projected arrays — the Python per-edge walk took ~300 ms per
        # mouse move against a 300k-edge imported model.
        import numpy as np
        best_d = self.pick_threshold_px
        best_g = None
        # The index first, then its projection (see _nearby_group_edges).
        idx = self._pick_index(near=("px", screen_x, screen_y))
        proj = self._gedge_screen()
        if proj is not None:
            ax, ay, bx, by, ok = proj
            if ok.any():
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                safe = np.where(l2 > 1e-12, l2, 1.0)
                t = np.clip(((screen_x - ax) * dx
                             + (screen_y - ay) * dy) / safe, 0.0, 1.0)
                d = np.hypot(ax + t * dx - screen_x,
                             ay + t * dy - screen_y)
                # The index also carries the edges of the model OUTSIDE the
                # open group (snap targets); those cannot be picked.
                sel = getattr(idx, "gedge_sel", None)
                if sel is not None:
                    ok = ok & sel
                d = np.where(ok, d, np.inf)
                # Only an edge the user can SEE takes the click: the far
                # edge of a slab, hidden behind a loose box standing on it,
                # lies a few pixels from a click on that box and handed the
                # slab the selection. The nearest visible one decides.
                near = np.where(d < best_d)[0]
                for i in near[np.argsort(d[near])]:
                    a = QVector3D(*idx.gedge_a[i])
                    p = a + (QVector3D(*idx.gedge_b[i]) - a) * float(t[i])
                    if not self._is_occluded(p):
                        best_d = float(d[i])
                        best_g = idx.gedge_groups[int(idx.gedge_gi[i])]
                        break
        # Billboard outlines: clicking a figure exactly on its snapped feet
        # point lands ON the quad's boundary, which the ray-triangle test
        # rejects — the outline proximity test catches it.
        for g in self._placements():
            if not getattr(g, "billboard", False):
                continue
            if not self.scene.entity_selectable(g):
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            c = quad[0]
            for i, j in ((0, 1), (1, 2), (2, 3), (3, 0)):
                pa = self._world_to_pixel(c[i])
                pb = self._world_to_pixel(c[j])
                if pa is None or pb is None:
                    continue
                d2 = _point_to_segment_distance_2d(
                    (screen_x, screen_y), pa, pb)
                if d2 < best_d:
                    best_d = d2
                    best_g = self._owner_of(g)
        return best_g

    # ---- Items an extension lets the user select (issue #205) ---------------
    #: The one extension item selected — ``(entry, item_id, scene version)``
    #: — or None. Kept APART from ``scene.selection``, which only ever holds
    #: the model's own entities, so nothing that walks the selection (Move,
    #: layers, zoom, copy) meets a thing it does not know.
    extension_pick = None

    def pick_extension_item(self, px: float, py: float):
        """The first extension item under the pixel, as ``(entry, id)``."""
        for entry in getattr(self, "_ext_pickables", ()):
            try:
                item = entry["pick"](self, px, py)
            except Exception:  # noqa: BLE001 — an extension's bug, not ours
                import logging
                logging.getLogger(__name__).exception("pickable failed")
                continue
            if item is not None:
                return entry, item
        return None

    def set_extension_pick(self, hit) -> None:
        """Select one extension item (``hit`` from pick_extension_item),
        telling the extension what was let go and what was taken."""
        self.clear_extension_pick()
        entry, item = hit
        self.extension_pick = (entry, item, self.scene.version)
        if entry.get("on_select") is not None:
            entry["on_select"](item)
        self.update()

    def clear_extension_pick(self, notify: bool = True) -> None:
        pick = self.extension_pick
        self.extension_pick = None
        if pick is not None and notify and pick[0].get("on_select") is not None:
            pick[0]["on_select"](None)

    def delete_extension_pick(self) -> bool:
        """Supr on a selected extension item: the extension deletes it (as
        its own undo step). A pick older than the document's last change
        is dropped instead — after an undo the id may name another item."""
        pick = self.extension_pick
        if pick is None:
            return False
        entry, item, version = pick
        self.clear_extension_pick()
        if version != self.scene.version or entry.get("delete") is None:
            return version != self.scene.version
        entry["delete"](item)
        self.update()
        return True
