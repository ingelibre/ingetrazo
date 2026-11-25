# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Picking: the pick index, ray hits and the pick_* queries."""
from __future__ import annotations

import math
import time as _time_mod
from PySide6.QtGui import QFont, QFontMetrics, QVector3D, QVector4D
from views.viewport._support import (_PERF, _NO_SPAN_GRID, _SPAN_GRID_MIN,
                                     _plog, _active_cut, _snap_context_of,
                                     _inst_proto_of, _PickWarm,
                                     _pick_warm_take, _entity_owner,
                                     _split_chunk_spans, _ray_aabb,
                                     _boxes_meet_native, _boxes_meet_numpy,
                                     _occlusion_native, _INSTANCE_FILTER,
                                     _LAZY_NATIVE, _PICK_WARM, _paint_of,
                                     _cache_ver, _content_ver,
                                     _plain_edge_rules, _edge_rows, _px_near,
                                     _nearest_order, _FRONT_LEAN, _placed_maps,
                                     _cat_kept, _offset_kept, _slab_far,
                                     _slab_near, _moller_trumbore, _MT_SHADOW,
                                     _MT_FAILED, _mt_judge, _mt_same,
                                     _mt_arrays_ok, _mt_native,
                                     _moller_trumbore_py, shown_guides,
                                     _ray_triangle,
                                     _point_to_segment_distance_2d,
                                     _face_geometry)

#: The Viewport class, set by views/viewport/__init__.py once it exists: a
#: method here that names ``Viewport.X`` reads (and writes) the class itself.
Viewport = None


class PickingMixin:
    """Picking: the pick index, ray hits and the pick_* queries."""

    def pick_locked_group(self, screen_x: float, screen_y: float):
        """Inspect or unlock a LOCKED group or component: the
        front-most face or a visible edge under the cursor, or ``None``.
        Its layer must be visible and unlocked. Editing tools still
        use ``pick_group``, which excludes locked objects."""
        context = self.scene.edit_group
        groups = self.scene.groups if context is None else context.children
        allowed = {g for g in groups if self.scene.entity_locked(g)
                   and self.scene.entity_inspectable(g)}
        if not allowed:
            return None
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        import numpy as np
        idx = self._pick_index(near=Viewport._ray_near(self, screen_x, screen_y))
        if idx is None:
            return None
        hits = Viewport._face_hits(self, idx, origin, direction, "vis")
        Viewport._drop_past_cut(self, hits, origin, direction)
        if hits is not None and len(hits.t):
            front = Viewport._smallest_at_front(self, hits, origin, direction)
            if len(front):
                owner = hits.owner(int(front[0]))
                for group in (owner, getattr(owner, "owner", None)):
                    if group in allowed:
                        return group
        return self._pick_locked_group_edge(screen_x, screen_y, allowed)


    def _pick_locked_group_edge(self, x, y, allowed):
        """Locked wire groups and face boundaries use the usual edge tolerance."""
        import numpy as np

        best_d, best = self.pick_threshold_px, None
        nat = self._lazy_native()
        table = self._pick_lazy_table()
        lazy_ids = set() if table is None else {id(g) for g in table[0]}
        if nat is not None:
            best_d, best = self._pick_group_edge_unbaked(
                x, y, nat, allowed_groups=allowed)
            near_ids = set()  # The engine already checked the lazy placements.
        elif table is not None:
            rows = self._footprint_need(table, float(x), float(y), best_d)
            near_ids = {id(table[0][int(i)]) for i in rows}
        else:
            near_ids = set()
        for placement in self._context_placements():
            owner = self._owner_of(placement)
            if owner not in allowed:
                continue
            if id(placement) in lazy_ids and id(placement) not in near_ids:
                continue
            # Locked edges are deliberately absent from the snapping index.
            # Read their cached drawing chunk without making them snap targets.
            raw = self._group_chunk(placement)["edges"]
            if not raw:
                continue
            edges = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2, 3)
            xs, ys, valid = self._project_px(edges.reshape(-1, 3))
            ax, ay, bx, by = xs[::2], ys[::2], xs[1::2], ys[1::2]
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = np.clip(((x - ax) * dx + (y - ay) * dy)
                        / np.where(length2 > 1e-12, length2, 1.0), 0.0, 1.0)
            ok = valid[::2] & valid[1::2]
            distance = np.where(ok, np.hypot(ax + t * dx - x, ay + t * dy - y), np.inf)
            near = np.flatnonzero(distance < best_d)
            for i in near[np.argsort(distance[near])]:
                a, b = QVector3D(*edges[i, 0]), QVector3D(*edges[i, 1])
                if not self._is_occluded(a + (b - a) * float(t[i])):
                    best_d, best = float(distance[i]), owner
                    break
        return best


    def _front_face_at(self, x: float, y: float, which: str = "sel"):
        """``(face, placement)`` of the front-most face on the ray through
        pixel ``(x, y)`` that passes ``which`` (see :meth:`_face_hits`), or
        ``None``. A bare pass with no memo: the face-crossing search asks it
        at pixels around the cursor, and :meth:`pick_face_any`'s memo holds
        the cursor's own answer."""
        o, d = self._pixel_to_ray(x, y)
        if o is None or d is None:
            return None
        import numpy as np
        idx = self._pick_index(near=Viewport._ray_near(self, x, y))
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if nat is not None and _FRONT_LEAN:
            return Viewport._front_face_lean(self, idx, nat, o, d, which)
        hits = Viewport._face_hits(self, idx, o, d, which)
        if hits is None or len(hits.t) == 0:
            return None
        i = int(np.argmin(hits.t))
        return hits.ent(i)[0], hits.place(i)

    def _front_face_lean(self, idx, nat, o, d, which: str = "sel"):
        """_front_face_at's answer over the engine's lazy placements (#158)
        without gathering every face the ray meets: the index's nearest
        face, then the lazy placements' only nearer than it (a tie goes to
        the index's, as the argmin over the index's then the lazy faces
        does), and of those only the nearest made into a face — the
        first of equals in the order _lazy_face_hits keeps. Each probe of
        a face crossing (see _crossing_on_screen) is one of these, ~2 ms
        over the plant when every face met was made."""
        import numpy as np
        best_t, best = float("inf"), None
        if len(idx.entities):
            if which == "sel":
                mask = idx.ent_sel
            elif which == "infer":
                mask = getattr(idx, "ent_infer", idx.ent_sel)
            else:
                mask = idx.ent_vis
            face_t = self._ray_hits(idx, o, d, mask, own=False)
            if face_t is not None and len(face_t):
                i = int(np.argmin(face_t))
                if np.isfinite(face_t[i]):
                    best_t = float(face_t[i])
                    pidx = getattr(idx, "ent_place_idx", None)
                    place = (idx.ent_placements[int(pidx[i])]
                             if pidx is not None and i < len(pidx)
                             and pidx[i] >= 0
                             else _entity_owner(idx.entities, i))
                    best = (idx.entities[i][0], place)
        if which == "sel":
            rows = Viewport._lazy_sel_rows(self, nat)
        elif which == "infer":
            rows = nat[1]
        else:
            rows = nat[2]
        if not len(rows):
            return best
        iset = nat[0]
        oo = np.array([o.x(), o.y(), o.z()])
        dd = np.array([d.x(), d.y(), d.z()])
        # A margin past the index's nearest: the engine's boxes decide
        # which triangles to hand, the exact test below which win.
        reach = (best_t * 1.001 + 1e-6 if np.isfinite(best_t)
                 else float("inf"))
        pl, tr, v0, e1, e2 = iset.ray_cands(
            np.ascontiguousarray(rows, np.int64), tuple(oo.tolist()),
            tuple(dd.tolist()), reach)
        if not len(pl):
            return best
        t, hit = _moller_trumbore(oo, dd, v0, e1, e2)
        k = np.flatnonzero(hit & (t < best_t))
        if not len(k):
            return best
        tmin = t[k].min()
        k = k[t[k] == tmin]
        groups = self._pick_lazy_table()[0]
        lazy_pos = self._pick_cands_memo[3]
        win = None
        for i, r in zip(pl[k].tolist(), tr[k].tolist()):
            g = groups[i]
            base = self._proto_base_chunk(g.mesh, _paint_of(self, g))
            j = int(base["tri_ent"][r])
            key = (lazy_pos[id(g)][0], j)
            if win is None or key < win[0]:
                win = (key, base, i, j)
        _key, base, i, j = win
        return base["faces"][j], groups[i]

    #: Component placements holding more faces than this, all together,
    #: switch the pick index to LAZY placements (issue #158): below it the
    #: index is exactly what it always was.
    _PICK_LAZY_MIN_FACES = 1_000_000
    #: How many faces of lazy placements the index keeps baked at once.
    _PICK_LIVE_MAX_FACES = 600_000
    #: Lazy placements baked by one query at most (the nearest first) —
    #: by all the footprint queries of one input event together.
    _PICK_NEW_PER_QUERY = 300
    #: A snap's footprint skips placements under this many framebuffer
    #: pixels across — the ones the frame does not draw.
    _PICK_MIN_PX = 1.0
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
        if memo is not None and self._epoch_only_matrices(memo[0], key):
            # A Move: picking up changes no row, putting down the rows of
            # what moved. Made again, the table framed 20 500 placements
            # (~0.55 s) on the first pointer move after either.
            table, xfs = memo[1], memo[2]
            if table is not None:
                # The nested placements' proxies take their composed
                # matrices here: the rows are read through them.
                self._placements()
                groups, lo, hi = table[0], table[1], table[2]
                moved = [i for i, g in enumerate(groups)
                         if tuple(g.xform.data()) != xfs[i]]
                if moved:
                    inf = float("inf")
                    lo, hi, xfs = lo.copy(), hi.copy(), list(xfs)
                    for i in moved:
                        box = self._placement_frame(groups[i])[0]
                        lo[i], hi[i] = (box if box
                                        else ((-inf,) * 3, (inf,) * 3))
                        xfs[i] = tuple(groups[i].xform.data())
                    table = (groups, lo, hi) + table[3:]
            self._pick_lazy_memo = (key, table, xfs)
            return table
        groups = [g for g in self._placements()
                  if getattr(g, "xform", None) is not None
                  and not getattr(g, "billboard", False)]
        # An object or two added or taken away (a Delete, a Paste): the
        # rows of the others are the old table's.
        kept = (self._epoch_kept_tops(memo[0], key, ctx=True)
                if memo is not None and memo[1] is not None else None)
        src = None
        if kept:
            o_groups, o_lo, o_hi, o_nf = memo[1][:4]
            row = {id(g): i for i, g in enumerate(o_groups)}
            top_of = self._placement_top
            src = np.fromiter(
                (row.get(id(g), -1) if top_of(g) in kept else -1
                 for g in groups), np.int64, count=len(groups))
        from core.mesh import face_count
        if src is None:
            nf = np.fromiter((face_count(g.mesh) for g in groups), np.int64,
                             count=len(groups))
        else:
            nf = np.fromiter((face_count(g.mesh) if k < 0 else 0
                              for g, k in zip(groups, src.tolist())),
                             np.int64, count=len(groups))
            at = np.flatnonzero(src >= 0)
            nf[at] = o_nf[src[at]]
        table = None
        if int(nf.sum()) >= self._PICK_LAZY_MIN_FACES:
            inf = float("inf")
            lo = np.empty((len(groups), 3))
            hi = np.empty((len(groups), 3))
            if src is None:
                todo = range(len(groups))
            else:
                lo[at], hi[at] = o_lo[src[at]], o_hi[src[at]]
                todo = np.flatnonzero(src < 0).tolist()
            for i in todo:
                box = self._placement_frame(groups[i])[0]
                lo[i], hi[i] = box if box else ((-inf,) * 3, (inf,) * 3)
            table = (groups, lo, hi, nf, {id(g) for g in groups})
        if table is None:
            xfs = None
        elif src is None:
            xfs = [tuple(g.xform.data()) for g in groups]
        else:
            o_xfs = memo[2]
            xfs = [tuple(g.xform.data()) if k < 0 else o_xfs[k]
                   for g, k in zip(groups, src.tolist())]
        self._pick_lazy_memo = (key, table, xfs)
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
        _pick_warm_take(self)
        groups = table[0]
        cache = getattr(self, "_inst_proto_cache", None) or {}
        keep: dict = {}
        by_mesh: dict = {}
        protos: list = []
        proto_of = np.empty(len(groups), dtype=np.int64)
        mats = np.empty((len(groups), 16), dtype=np.float64)
        todo: list = []                       # (position in protos, key, bake)
        for i, g in enumerate(groups):
            k = by_mesh.get(id(g.mesh))
            if k is None:
                # Every placement of a mesh has the same triangles and hard
                # edges, whatever its paint: one bake (the first one's).
                base = self._proto_base_chunk(g.mesh, _paint_of(self, g))
                ckey = (base.get("uid"), base.get("rev"))
                ip = cache.get(ckey)
                if ip is None:
                    todo.append((len(protos), ckey, base))
                keep[ckey] = ip
                k = by_mesh[id(g.mesh)] = len(protos)
                protos.append(ip)
            proto_of[i] = k
            mats[i] = g.xform.data()

        def build(job):
            pos, ckey, base = job
            ip = _inst_proto_of(mod, base)
            protos[pos] = ip
            keep[ckey] = ip
        # The engine lets go of the GIL for each tree: side by side, not the
        # 2.4 s of a big model's first hover one after another (#1092).
        if len(todo) > 1:
            import os
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(
                    max_workers=min(8, os.cpu_count() or 2)) as ex:
                list(ex.map(build, todo))
        else:
            for job in todo:
                build(job)
        self._inst_proto_cache = keep
        iset = mod.InstanceSet(protos, proto_of, mats,
                               np.ascontiguousarray(table[1], np.float64),
                               np.ascontiguousarray(table[2], np.float64))
        self._inst_set_memo = (table, iset)
        return iset

    def start_pick_warmup(self) -> None:
        """A big document is on screen: work out the heavy parts of the pick
        index behind it, so the first move of the pointer does not wait for
        them (4 s on a model of 5 M faces, #1092). Whoever moves the mouse
        needs them, whatever the tool, and the answers cannot change: the
        same calls with the same arrays, only sooner. Only with the engine
        and on a model big enough for lazy placements."""
        if not _PICK_WARM or not _INSTANCE_FILTER:
            return
        from core import _native
        mod = _native.native
        if mod is None or not hasattr(mod, "InstanceSet"):
            return
        table = self._pick_lazy_table()
        if table is None:
            return
        memo = getattr(self, "_inst_set_memo", None)
        if memo is not None and memo[0] is table:
            return                       # the pointer got there first
        seen: set = set()
        protos: list = []
        for g in table[0]:
            if id(g.mesh) not in seen:
                seen.add(id(g.mesh))
                base = self._proto_base_chunk(g.mesh, _paint_of(self, g))
                protos.append(((base.get("uid"), base.get("rev")), base))
        grids: list = []
        if not _NO_SPAN_GRID:
            fixed = Viewport._pick_candidates(self, False, table)[1]
            for g in fixed:
                if not getattr(g, "billboard", False):
                    c = self._group_chunk(g)
                    if (c["v0"] is not None and len(c["v0"]) > _SPAN_GRID_MIN
                            and "_span_grid" not in c):
                        grids.append(c)
        # What a box selection asks of each, the first time (2 s over 257).
        bounds = [base for _k, base in protos]
        self._pick_warm = _PickWarm(mod, protos, grids, bounds)

    def _static_occluders(self, idx):
        """core._native's InstanceSet over the pick index's own triangles
        that hide what is behind them, placed by the identity (which the
        engine maps bit for bit): the fixed placements' as one prototype,
        kept while those triangles and their visibility are — a stroke
        changes only the loose part, the other prototype. Made once per
        index."""
        import numpy as np
        hit = getattr(idx, "_static_occl", None)
        if hit is not None:
            return hit
        mod = _occlusion_native()
        if mod is None or not hasattr(mod, "InstanceSet"):
            return None
        st = getattr(self, "_pick_static_memo", None)
        fv0 = st[1]["v0"] if st is not None else None
        n = len(idx.tri_v0)
        nf = len(fv0) if fv0 is not None else 0
        if nf > n or (nf and not np.array_equal(idx.tri_v0[n - nf], fv0[0])):
            nf = 0                       # not the index's tail: one part
        vis = idx.ent_vis[idx.tri_ent]

        def proto(lo, hi):
            keep = np.flatnonzero(vis[lo:hi]) + lo
            return mod.InstanceProto(
                np.ascontiguousarray(idx.tri_v0[keep], np.float64),
                np.ascontiguousarray(idx.tri_e1[keep], np.float64),
                np.ascontiguousarray(idx.tri_e2[keep], np.float64),
                np.zeros((0, 6))), keep
        memo = getattr(self, "_static_occl_memo", None)
        fkeep = vis[n - nf:]
        if (nf and memo is not None and memo[0] is fv0
                and np.array_equal(memo[1], fkeep)):
            fixed = memo[2]
        elif nf:
            fixed = proto(n - nf, n)
            self._static_occl_memo = (fv0, fkeep.copy(), fixed)
        else:
            fixed = None
        parts = [proto(0, n - nf)] + ([fixed] if fixed is not None else [])
        iset = mod.InstanceSet([p for p, _k in parts],
                               np.arange(len(parts), dtype=np.int64),
                               np.tile(np.eye(4).reshape(1, 16),
                                       (len(parts), 1)))
        # Prototype p's triangle r is index row rows[start[p] + r].
        rows = np.concatenate([k for _p, k in parts])
        start = np.cumsum([0] + [len(k) for _p, k in parts[:-1]])
        idx._static_occl = (iset, np.arange(len(parts), dtype=np.int64),
                            rows, start)
        return idx._static_occl

    def _static_ray_rows(self, idx, ent_mask, o3, d3):
        """The index rows of the triangles the ray from ``o3`` along ``d3``
        may meet, in order, from the engine's BVH over the visible ones
        (_static_occluders) — or None where that cannot answer for
        ``ent_mask``: no engine, or an entity it passes that is not visible
        (its triangles are not in there). A superset of what the exact test
        accepts, so the hits are the same as over every span the ray's box
        test keeps (hundreds of thousands of triangles of a big fixed part,
        30 ms a hover over the plant of #158)."""
        import numpy as np
        if not (hasattr(self, "_lazy_native")
                and self._lazy_native() is not None):
            return None
        memo = idx.__dict__.setdefault("_mask_in_vis", {})
        ok = memo.get(id(ent_mask))
        if ok is None or ok[0] is not ent_mask:
            ok = memo[id(ent_mask)] = (
                ent_mask, not bool((ent_mask & ~idx.ent_vis).any()))
        if not ok[1]:
            return None
        stat = self._static_occluders(idx)
        if stat is None:
            return None
        iset, cand, rows, start = stat
        pl, tr, _v0, _e1, _e2 = iset.ray_cands(cand, o3, d3, float("inf"))
        return np.sort(rows[start[pl] + tr])

    def _lazy_native(self):
        """What the experimental engine answers for the context's lazy
        placements without baking them (#158): ``(iset, snap, vis)`` —
        core._native's InstanceSet over the lazy table, and the table rows
        of the placements the pick index would take that a snap may land
        on and that hide what is behind them, in the index's order — or
        ``None`` (no lazy table, no engine)."""
        if not _LAZY_NATIVE:
            return None
        table = self._pick_lazy_table()
        if table is None:
            return None
        iset = self._pick_instance_set(table)
        if iset is None or not hasattr(iset, "corners_near"):
            return None
        oculto = getattr(self, "_rest_is_hidden", None)
        oculto = bool(oculto()) if callable(oculto) else False
        ckey = (self._placements_epoch(), id(self.scene.edit_group), oculto,
                id(table))
        cmemo = getattr(self, "_pick_cands_memo", None)
        if cmemo is None or cmemo[0] != ckey:
            self._pick_index(near="skip")         # the candidates it takes
            cmemo = getattr(self, "_pick_cands_memo", None)
            if cmemo is None or cmemo[0] != ckey:
                return None
        memo = getattr(self, "_lazy_native_memo", None)
        if memo is not None and memo[0] is cmemo and memo[1] is iset:
            return memo[2]
        import numpy as np
        scene = self.scene
        row = {id(g): i for i, g in enumerate(table[0])}
        ordered = [g for _p, g in sorted(cmemo[3].values(),
                                         key=lambda pg: pg[0])]
        snap = np.fromiter((row[id(g)] for g in ordered
                            if scene.group_snappable(g)), np.int64)
        vis = np.fromiter((row[id(g)] for g in ordered
                           if scene.entity_visible(g)), np.int64)
        out = (iset, snap, vis)
        self._lazy_native_memo = (cmemo, iset, out)
        return out

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
        footprint = False
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
            tmin = _slab_far(np.minimum(t1, t2))
            tmax = _slab_near(np.maximum(t1, t2))
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
            footprint = True
            need = self._footprint_need(table, x, y)
        if footprint and len(need):
            # A footprint takes in the placements nearest the eye that fit
            # in most of the cap, and those stay (see the eviction below):
            # zoomed out over the plant of #158 it met ~3 400 placements,
            # far more than fit, and each pointer move the first ray let go
            # of 300 the footprint then brought in again — two rebuilds of
            # the lazy part a move, for the same set.
            room = self._PICK_LIVE_MAX_FACES * 0.8
            need = np.asarray(need, dtype=np.int64)
            if float(nf[need].sum()) > room:
                e = self.camera.eye()
                e = np.array([e.x(), e.y(), e.z()])
                dist = np.linalg.norm(np.clip(e, lo[need], hi[need]) - e,
                                      axis=1)
                srt = need[np.argsort(dist, kind="stable")]
                fit = np.cumsum(nf[srt]) <= room
                fit[0] = True
                need = srt[fit]
            self._pick_foot_keep = {id(groups[int(i)]) for i in need}
        new = [int(i) for i in need if id(groups[int(i)]) not in live]
        # The footprint queries of one input event (the snap, the cursor's
        # own) share the cap: each brought in its own 300 over the same
        # spot, and each change rebuilt the lazy part of the index — five
        # rebuilds a pointer move over the plant of #158.
        serial = getattr(self, "_input_serial", None)
        cap = self._PICK_NEW_PER_QUERY
        budget = None
        if footprint and serial is not None:
            budget = getattr(self, "_pick_budget", None)
            if budget is None or budget[0] != serial:
                budget = self._pick_budget = [serial, cap]
            cap = budget[1]
        if len(new) > cap and near != "all":
            # A first snap over a dense spot met thousands at once (2.3 s):
            # the nearest to the eye come in now, the rest on the next moves.
            e = self.camera.eye()
            e = np.array([e.x(), e.y(), e.z()])
            nn = np.array(new)
            dist = np.linalg.norm(np.clip(e, lo[nn], hi[nn]) - e, axis=1)
            keep_new = set(nn[np.argsort(dist)[:cap]].tolist())
            need = [int(i) for i in need
                    if id(groups[int(i)]) in live or int(i) in keep_new]
        if budget is not None:
            budget[1] = max(0, cap - min(len(new), cap))
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
        # Making room once per input event: the ray picks that follow the
        # snap over the same spot let go of what it had just brought in,
        # and every such change rebuilt the index (up to twice the cap).
        evict = faces > self._PICK_LIVE_MAX_FACES and near != "all"
        if (evict and serial is not None
                and getattr(self, "_pick_evicted_at", None) == serial
                and faces <= 2 * self._PICK_LIVE_MAX_FACES):
            evict = False
        if evict:
            self._pick_evicted_at = serial
            keep = {id(groups[int(i)]) for i in need}
            keep |= getattr(self, "_pick_foot_keep", None) or set()
            inst = getattr(self, "_inst_chunks", None)
            for k in list(live):
                if faces <= self._PICK_LIVE_MAX_FACES:
                    break
                if k in keep:
                    continue
                gone, nf_k = live.pop(k)
                faces -= nf_k
                # Its world bake goes with it — unless the static buffers
                # draw it, and then the next sync baked it all over again
                # (13 placements, ~0.15 s of picking an object up on #158).
                if inst is not None and self._instanced_eligible(gone):
                    inst.pop(k, None)
                changed = True
        if changed:
            self._pick_gen = getattr(self, "_pick_gen", 0) + 1

    def _depth_limits(self, x: float, y: float, r: float):
        """What the last frame shows within ``r`` px of widget pixel
        ``(x, y)``: per device pixel of that patch, the distance from the
        eye past which a point there is hidden by something drawn — the
        farthest surface drawn at the pixel and the 8 around it, plus what
        the depth buffer cannot tell apart (8 steps of a 24-bit depth),
        0.2 % and 2 cm; inf where it cannot say (sky at the pixel, the edge
        of the frame). ``(eye, limits (gh, gw), x0, y0, dpr, device height)``
        as core.instances.DepthLimits reads it, or None without a frame."""
        import numpy as np
        if self._depth_world_at(x, y) is None:
            return None
        buf, inv, w, h = (self._depth_snap[0], self._depth_snap[2],
                          self._depth_snap[3], self._depth_snap[4])
        dpr = w / max(1, self.width())
        x0 = int(np.floor((x - r) * dpr)) - 1
        x1 = int(np.floor((x + r) * dpr)) + 1
        yb0 = h - 1 - (int(np.floor((y + r) * dpr)) + 1)
        yb1 = h - 1 - (int(np.floor((y - r) * dpr)) - 1)
        ix, iy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(yb0, yb1 + 1))
        inside = (ix >= 1) & (ix < w - 1) & (iy >= 1) & (iy < h - 1)
        cx, cy = np.clip(ix, 1, w - 2), np.clip(iy, 1, h - 2)
        # The farthest of what is drawn among the nine (the sky among them
        # is nothing in front): a corner on a silhouette is measured
        # against the farther side of it.
        d = np.zeros(ix.shape, dtype=np.float64)
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                b = buf[cy + oy, cx + ox]
                d = np.maximum(d, np.where(b < 1.0, b, 0.0))
        M = np.array(inv.data(), dtype=np.float64).reshape(4, 4, order="F")
        e = self.camera.eye()
        e = np.array([e.x(), e.y(), e.z()])

        def dist_at(depth):
            ndc = np.stack([(ix + 0.5) / w * 2.0 - 1.0,
                            (iy + 0.5) / h * 2.0 - 1.0,
                            depth * 2.0 - 1.0, np.ones(ix.shape)], axis=-1)
            q = ndc @ M.T
            with np.errstate(divide="ignore", invalid="ignore"):
                r_ = np.linalg.norm(q[..., :3] / q[..., 3:4] - e, axis=-1)
            return np.where(np.abs(q[..., 3]) >= 1e-12, r_, np.nan)
        far = dist_at(d)
        step = dist_at(np.minimum(d + 8.0 / (1 << 24), 1.0)) - far
        lim = far + np.abs(step) + 0.0005 * far + 0.01
        ok = (inside & (buf[cy, cx] < 1.0) & np.isfinite(lim)
              & (far <= 1.01 * self.camera.far_plane()))
        lim = np.ascontiguousarray(np.where(ok, lim, np.inf))
        return (e.tolist(), lim, x0, yb0, float(dpr), int(h))

    @staticmethod
    def _depth_hidden(seen, pts, sx, sy):
        """core.instances.DepthLimits.hides for arrays: per point (N,3) at
        widget pixel ``(sx, sy)``, whether it lies past its pixel's limit."""
        import numpy as np
        eye, lim, x0, y0, dpr, hdev = seen
        gh, gw = lim.shape
        ix = np.floor(sx * dpr).astype(np.int64) - x0
        iy = hdev - 1 - np.floor(sy * dpr).astype(np.int64) - y0
        at = (ix >= 0) & (iy >= 0) & (ix < gw) & (iy < gh)
        out = np.zeros(len(pts), dtype=bool)
        k = np.flatnonzero(at)
        if len(k):
            dist = np.sqrt(((pts[k] - np.array(eye)) ** 2).sum(axis=1))
            out[k] = dist > lim[iy[k], ix[k]]
        return out

    def _footprint_need(self, table, x: float, y: float, reach=None):
        """The rows of the lazy ``table`` a snap's footprint at widget pixel
        ``(x, y)`` takes in (see _pick_materialize): the boxes near the
        pixel, but what lies wholly behind what the frame shows there or
        under a pixel, and of those the ones the spatial index finds
        something near the cursor in. ``reach`` widens the boxes' margin
        past ``_PICK_NEAR_PX`` (the edges near the cursor are looked for
        farther out). Memoised per view and pixel."""
        import numpy as np
        lo, hi = table[1], table[2]
        r = max(float(reach or 0.0), self._PICK_NEAR_PX)
        ckey = (self._placements_epoch(), round(x), round(y),
                tuple(self._np_mvp().ravel()), r)
        # One per margin: a hover asks for both (the pick's, the edges').
        slot = ("_pick_near_memo" if r == self._PICK_NEAR_PX
                else "_edge_near_memo")
        cmemo = getattr(self, slot, None)
        if cmemo is not None and cmemo[0] == ckey:
            return cmemo[1]
        need = self._placements_under_px(lo, hi, x, y, r)
        far = self._visible_depth_limit(x, y)
        if len(need) and (far is not None or self._PICK_MIN_PX > 0.0):
            dist, small = self._footprint_rows(table)
            if far is not None:
                # What lies wholly behind what is on screen around the
                # cursor can be neither picked nor snapped to (hidden
                # snaps are dropped): a dense plant stacks thousands of
                # placements under one pixel (#158).
                need = need[dist[need] <= far]
            if small is not None:
                # Nor what the frame leaves out for being under a pixel
                # (see _instances_below_a_pixel): from the whole plant
                # of #158 the snap's footprint met more placements
                # than the cap, and each pointer move threw out the
                # last move's to bring in as many again.
                need = need[~small[need]]
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
                Viewport.GEDGE_REACH_PX + 2.0,
                r + 2.0), dtype=np.int64)
        setattr(self, slot, (ckey, need))
        return need

    def _footprint_rows(self, table):
        """For every row of the lazy ``table``, how far its box lies from
        the eye and whether it spans under ``_PICK_MIN_PX`` (None when
        that floor is off): what _footprint_need cuts by, the same for
        any pixel of the view. Kept for the view: over the 16 000 rows
        near the cursor in the plant of #158 they cost ~2 ms a search,
        two searches a pointer move."""
        import numpy as np
        lo, hi = table[1], table[2]
        e = self.camera.eye()
        h = (self._export_size or self._fb_size())[1]
        key = (self._placements_epoch(), tuple(self._np_mvp().ravel()),
               (e.x(), e.y(), e.z()), h, bool(self.camera.perspective),
               self._PICK_MIN_PX)
        memo = getattr(self, "_footprint_rows_memo", None)
        if (memo is not None and memo[0] == key and memo[1] is lo
                and memo[2] is hi):
            return memo[3]
        eye = np.array([e.x(), e.y(), e.z()])
        dist = np.linalg.norm(np.clip(eye, lo, hi) - eye, axis=1)
        small = None
        if self._PICK_MIN_PX > 0.0:
            ctr, rad = self._bounding_spheres(lo, hi)
            small = self._spheres_below_a_pixel(ctr, rad, self._PICK_MIN_PX)
        self._footprint_rows_memo = (key, lo, hi, (dist, small))
        return dist, small

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

    def _placements_under_px(self, lo, hi, x, y, r=None):
        """Indices of the boxes ``lo``/``hi`` whose screen footprint comes
        within ``r`` (``_PICK_NEAR_PX``) of widget pixel ``(x, y)``; a box that
        crosses the eye plane counts (it can be anywhere on screen)."""
        import numpy as np
        from core import _native
        M = self._np_mvp()
        r = self._PICK_NEAR_PX if r is None else r
        mod = _native.native
        if mod is not None and hasattr(mod, "boxes_near_px"):
            # The same test in parallel: ~9 ms of NumPy a pointer move over
            # the 21 406 boxes of #158, twice (the pick's, the edges').
            return mod.boxes_near_px(
                np.ascontiguousarray(lo, np.float64),
                np.ascontiguousarray(hi, np.float64),
                np.ascontiguousarray(M, np.float64).ravel().tolist(),
                float(self.width()), float(self.height()), float(x),
                float(y), float(r))
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
        inside = (x0 - r <= x) & (x <= x1 + r) & (y0 - r <= y) & (y <= y1 + r)
        straddle = front.any(axis=1) & ~front.all(axis=1)
        return np.flatnonzero((inside & front.all(axis=1)) | straddle
                              | ~finite)

    def _pick_block_part(self, candidatos, tocables, lazy_set, base):
        """One part of the pick block (see _pick_index): the faces, owners,
        triangles and hard edges of ``candidatos``, numbered after ``base``
        (the part before it, or None). Lists, joined by _pick_join_parts."""
        import numpy as np
        from core.layers import inherited_layer
        scene = self.scene
        chunks = []
        for g in candidatos:
            if getattr(g, "billboard", False):
                continue          # per-frame quad; picked separately
            gvis = scene.entity_visible(g)
            # Locked objects remain inference references, but cannot be
            # edited. The context further limits what a pick may touch.
            gsnap = scene.group_snappable(g)
            gsel = scene.entity_selectable(g) and id(g) in tocables
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
        _pick_warm_take(self)
        # Each big chunk's grid is its own work, mostly NumPy: side by side
        # (0.9 s of a big model's first hover one after another, #1092). Each
        # keeps it on its chunk, where the loop below finds it.
        big = [c for g, c, _v, _s, _n in chunks
               if c["v0"] is not None and id(g) not in lazy_set
               and len(c["v0"]) > _SPAN_GRID_MIN and "_span_grid" not in c]
        if len(big) > 1 and not _NO_SPAN_GRID:
            import os
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(
                    max_workers=min(8, os.cpu_count() or 2)) as ex:
                list(ex.map(_split_chunk_spans, big))
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
        b_area, b_vis, b_sel, b_infer = [], [], [], []
        b_spans: list = []    # (bbox, tri start, count) per chunk
        # Group hard edges, flat — pick_group's fallback (cursor over
        # empty space / lines-only group) walked every group edge in
        # Python (~300 ms per mouse move against a 300k-edge import).
        b_gea, b_geb, b_ggi = [], [], []
        b_gel: list = []
        b_gbase: list = []    # each chunk's (n, 2, 3) edge array, kept
        b_gsel: list = []     # per edge: may pick_group land on it
        b_ggroups: list = []
        b_gilayer: list = []  # per group: the nearest container's layer
        b_gctx: list = []     # per group: the tip's context word
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
            # Inferred from even when the open context makes it untouchable:
            # the rest of the model is a reference, not an answer.
            b_infer.append(np.full(n, gsnap, dtype=bool))
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
                b_gbase.append(ge)
                b_gea.append(ge[:, 0])
                b_geb.append(ge[:, 1])
                b_ggi.append(np.full(len(ge), n_ggroups + len(b_ggroups),
                                     dtype=np.int64))
                own = chunk.get("edge_layer")
                gel = np.empty(len(ge), dtype=object)
                if own is not None and len(own) == len(ge):
                    gel[:] = own
                b_gel.append(gel)
                b_gsel.append(np.full(len(ge), gsel, dtype=bool))
                b_ggroups.append(owner)
                # The placement's own layer — the nearest container's, not
                # the top-level object's — is what its hard edges are inked
                # with on a sheet (#1503).
                b_gilayer.append(inherited_layer(g))
                # "outside" while a group/component is open and this
                # placement is not part of it (see _snap_context_of).
                b_gctx.append(_snap_context_of(self, g))
        part = {"entities": b_entities, "pidx": b_pidx, "plist": b_plist,
                "area": b_area, "vis": b_vis, "sel": b_sel,
                "infer": b_infer,
                "own": b_own, "static_key": static_key,
                "v0": b_v0, "e1": b_e1, "e2": b_e2, "te": b_te,
                "spans": b_spans, "gea": b_gea, "geb": b_geb, "ggi": b_ggi,
                "gel": b_gel,
                "gsel": b_gsel, "ggroups": b_ggroups, "gctx": b_gctx,
                "gilayer": b_gilayer,
                "gbase": b_gbase,
                "n_ent": n_ent + count, "n_plist": n_plist + len(b_plist),
                "n_tri": b_tri_off,
                "n_ggroups": n_ggroups + len(b_ggroups)}
        if base is None:
            # The fixed part joins its own lists once, here: it is kept.
            for k in ("pidx", "area", "vis", "sel", "infer", "gea", "geb",
                      "ggi", "gel", "gsel"):
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
            "infer": cat("infer", np.empty(0, bool)),
            **Viewport._pick_static_tris(self, tuple(static),
                                         fixed["v0"] + lazy["v0"],
                                         fixed["e1"] + lazy["e1"],
                                         fixed["e2"] + lazy["e2"],
                                         fixed["te"] + lazy["te"]),
            "own": fixed["own"] + lazy["own"],
            "gedge_a": np.concatenate(gea) if gea else None,
            "gedge_b": cat("geb", None) if gea else None,
            "gedge_gi": cat("ggi", None) if gea else None,
            "gedge_layer": cat("gel", None) if gea else None,
            "gedge_sel": cat("gsel", None) if gea else None,
            "gedge_groups": fixed["ggroups"] + lazy["ggroups"],
            "gedge_ilayer": fixed.get("gilayer", []) + lazy.get("gilayer", []),
            "gedge_ctx": fixed.get("gctx", []) + lazy.get("gctx", []),
            # The fixed part's edges lead, and that part outlives many lazy
            # rebuilds: their screen projection is kept across them.
            "gedge_fixed": (fixed, sum(map(len, fixed["gea"])),
                            lazy["gbase"]),
            "spans": fixed["spans"] + lazy["spans"],
        }

    def _outer_loose_meshes(self):
        """The root loose mesh drawn AROUND an open group / component, as a
        tuple of meshes (usually one, or none).

        Opening a group points ``scene.mesh`` at its mesh: the loose
        geometry of the outer context stops being the loose part of the
        index, and it was nowhere else in it — the rest of the model could
        be inferred on only where it was grouped («estoy dentro del
        componente y no me snapea a lo de fuera»). It is drawn faded
        (``scene.loose_mesh``), so it must occlude, snap and be acquirable
        as a reference like every other faded thing.

        Hidden with «Hide rest of model» it is not drawn, so it is not
        offered either (same rule as the placements, see
        ``_pick_candidates``). A mesh a placement already draws is left out
        or the model would be snapped through twice (a copied group can
        share the loose mesh)."""
        scene = self.scene
        if scene.edit_group is None:
            return ()
        rest_hidden = getattr(self, "_rest_is_hidden", None)
        if callable(rest_hidden) and rest_hidden():
            return ()
        outer = getattr(scene, "loose_mesh", None)
        if outer is None or outer is scene.mesh:
            return ()
        key = (_content_ver(self), id(outer), id(scene.edit_group),
               id(scene.mesh))
        memo = getattr(self, "_outer_loose_memo", None)
        if memo is not None and memo[0] == key:
            return memo[1]
        carried = {id(g.mesh) for g in self._placements()}
        meshes = () if id(outer) in carried else (outer,)
        self._outer_loose_memo = (key, meshes)
        return meshes

    def _loose_mesh_wrapper(self, mesh):
        """A stable stand-in for a mesh that is a *reference*, not an
        object: what an outer loose face rides in the index so the snap
        paths can tell its mesh (and its world frame: identity) from the
        open context's. Cached, as ``_group_chunk`` keys on ``id``."""
        wrappers = getattr(self, "_loose_wrappers", None)
        if wrappers is None:
            wrappers = self._loose_wrappers = {}
        w = wrappers.get(id(mesh))
        if w is None:
            from types import SimpleNamespace
            w = wrappers[id(mesh)] = SimpleNamespace(
                mesh=mesh, xform=None, material=None, name=None,
                billboard=False, hidden=False, locked=False, layer=None)
        return w

    #: From this many faces on, the open mesh's part of the pick index
    #: comes from its chunk (see :meth:`_open_mesh_pick_part`).
    PICK_FROM_CHUNK_MIN = 500

    def _open_mesh_pick_part(self):
        """``(entities, areas, visible, selectable, (v0, e1, e2, tri_ent))``
        of the open mesh's faces, read from the open group's chunk — the
        triangles and areas the per-face walk would make, in its order
        (tests/test_pick_open_mesh_from_chunk.py) — or ``None`` to walk.

        Inside a 9 674-face group the walk was ~0.4 s an edit: every face
        triangulated again and asked its layer twice. A face that is not
        hidden is visible and selectable by its layer alone, so each layer
        is asked once. Only when no face is hidden: the chunk leaves those
        out, and the walk keeps them (as not visible)."""
        scene = self.scene
        E = scene.edit_group
        mesh = scene.mesh
        if (E is None or getattr(E, "xform", None) is not None
                or getattr(E, "mesh", None) is not mesh
                or len(mesh.faces) < getattr(self, "PICK_FROM_CHUNK_MIN", 500)
                or not hasattr(self, "_group_chunk")):
            return None
        ch = self._group_chunk(E)
        faces = mesh.faces
        drawn = ch.get("faces")
        if (ch.get("mesh") is not mesh or drawn is None
                or len(drawn) != len(faces) or ch.get("v0") is None
                or not all(a is b for a, b in zip(drawn, faces))):
            return None
        from core import layers as _layers
        by_layer: dict = {}
        vis: list = []
        sel: list = []
        for f in faces:
            name = _layers.layer_of(f)
            hit = by_layer.get(name)
            if hit is None:
                hit = by_layer[name] = (scene.entity_visible(f),
                                        scene.entity_selectable(f))
            vis.append(hit[0])
            sel.append(hit[1])
        return ([(f, None) for f in faces], ch["areas"].tolist(), vis, sel,
                (ch["v0"], ch["e1"], ch["e2"], ch["tri_ent"]))

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
            qkey = (getattr(self, "_tick", 0), _content_ver(self),
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
        # The content version: a click (a view-only bump) changes nothing
        # in it — on the plant of #158 it rebuilt it on every click.
        key = (Viewport._pick_geometry_ver(self), id(self.scene.mesh), oculto,
               id(self.scene.edit_group), getattr(self, "_pick_gen", 0))
        cached = getattr(self, "_pick_index_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        prev = getattr(self, "_pick_index_prev", None)
        if (prev is not None and prev[0] == key
                and prev[2] is getattr(self, "_pick_block", None)):
            # The rest state of a prism push again (see note_same_geometry):
            # the index made for it, not a rebuild of the very same one.
            self._pick_index_prev, self._pick_index_cache = cached, prev
            return prev[1]
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
        ent_infer: list = []
        tris: list = []
        tri_ent: list = []

        # Stub viewports in tests call this unbound — fall back to the
        # uncached face methods when the memo helpers aren't there.
        area_of = getattr(self, "_area_of", None) or (lambda f: f.area())
        tris_of = getattr(self, "_tris_of", None) or \
            (lambda f: f.triangulate())

        # Inside a group its faces are the loose part, rebuilt here on every
        # edit: the per-face geometry its chunk keeps (exact corners → the
        # same normal, area and earcut) saves the walk for every face the
        # edit did not touch — ~0.3 s an edit in a 9 674-face group of the
        # Plaza (night of 18-11).
        gmemo = None
        if scene.edit_group is not None and getattr(self, "_tris_of", None):
            gmemo = scene.mesh.__dict__.get("_face_geom_memo")
        if gmemo is not None:
            from core.triangulate import triangulate as _earcut

        def add_face(f, grp, vis, sel, infer=None, loose=None):
            i = len(entities)
            entities.append((f, grp))
            geom = (_face_geometry(f, gmemo, _earcut)
                    if gmemo is not None and grp is None
                    and hasattr(f, "loop") else None)
            ent_area.append(area_of(f) if geom is None else geom[2])
            ent_vis.append(vis)
            ent_sel.append(sel)
            # What the snap engine may INFER FROM: visible, not merely
            # selectable — a locked layer protects its objects from
            # editing, not from being snapped to (#1510), and the rest
            # of the model outside the open context is a reference even
            # though it cannot be picked (see _face_hits "infer").
            ent_infer.append(vis if infer is None else infer)
            ent_loose.append((grp is None) if loose is None else loose)
            if geom is not None:
                for t0, t1, t2 in geom[3]:
                    tris.append(t0 + t1 + t2)
                    tri_ent.append(i)
                return
            for t0, t1, t2 in tris_of(f):
                tris.append((t0.x(), t0.y(), t0.z(),
                             t1.x(), t1.y(), t1.z(),
                             t2.x(), t2.y(), t2.z()))
                tri_ent.append(i)

        # The loose part lasts while the content and the context do: a
        # change of the lazy set (a few times a pointer move over the plant
        # of #158) rebuilds the index, and walked the loose faces again.
        lmemo = getattr(self, "_pick_loose_memo", None)
        if lmemo is not None and lmemo[0] == key[:4]:
            loose = lmemo[1]
        else:
            # (Test stand-ins of the viewport have no such part.)
            part = getattr(self, "_open_mesh_pick_part", None)
            fast = part() if callable(part) else None
            if fast is not None:
                f_ents, f_area, f_vis, f_sel, f_tris = fast
                entities.extend(f_ents)
                ent_area.extend(f_area)
                ent_vis.extend(f_vis)
                ent_sel.extend(f_sel)
                ent_infer.extend(f_vis)   # a reference when seen (#1510)
                ent_loose.extend([True] * len(f_ents))
            else:
                f_tris = None
                for f in scene.faces:
                    add_face(f, None, scene.entity_visible(f),
                             scene.entity_selectable(f))
            # The loose mesh drawn AROUND an open group / component: the
            # rest of the model when it was never grouped. It cannot be
            # picked or selected from inside the context, but it is drawn
            # (faded), so it occludes and the snap engine infers from it
            #. Its own mesh rides with the face (the wrapper) so
            # the plane and the centre come from the right mesh.
            outer_of = getattr(self, "_outer_loose_meshes", None)
            for om in (outer_of() if outer_of is not None else ()):
                wrap = self._loose_mesh_wrapper(om)
                for f in om.faces:
                    add_face(f, wrap, scene.entity_visible(f),
                             False, infer=scene.entity_visible(f),
                             loose=True)
            # Loose part → arrays; groups append their cached chunk arrays.
            cells = None
            if tris or f_tris is not None:
                t = (np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
                     if tris else np.zeros((0, 3, 3)))
                v0, e1, e2 = t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
                te = np.asarray(tri_ent, dtype=np.int64)
                if f_tris is not None:
                    # The open mesh's triangles come first, as its faces.
                    v0 = np.concatenate([f_tris[0], v0])
                    e1 = np.concatenate([f_tris[1], e1])
                    e2 = np.concatenate([f_tris[2], e2])
                    te = np.concatenate([f_tris[3], te])
                # The loose part on the span grid a group's chunk gets: an
                # open group's own faces are loose, and as ONE span every
                # ray that met the model ran Möller–Trumbore over all of
                # them — 25 800 faces, ~2.5 ms a ray, a few rays a hover
                # (#1392). The order is free: each triangle carries its
                # entity.
                if len(te):
                    *lt, cells = _split_chunk_spans(
                        {"v0": v0, "e1": e1, "e2": e2, "tri_ent": te})
                    lt = tuple(lt)
                else:
                    lt = None
            else:
                lt = None
            loose = (list(entities), lt,
                     len(tris) + (len(f_tris[3]) if f_tris is not None else 0),
                     np.asarray(ent_area, dtype=np.float64),
                     np.asarray(ent_vis, dtype=bool),
                     np.asarray(ent_sel, dtype=bool),
                     np.asarray(ent_infer, dtype=bool),
                     np.asarray(ent_loose, dtype=bool), cells)
            self._pick_loose_memo = (key[:4], loose)
        entities = list(loose[0])
        lt, n_loose_tris = loose[1], loose[2]
        if lt is not None:
            v0s, e1s, e2s, tents = [lt[0]], [lt[1]], [lt[2]], [lt[3]]
        else:
            v0s, e1s, e2s, tents = [], [], [], []
        areas, vis_parts, sel_parts, infer_parts, loose_parts = (
            [loose[3]], [loose[4]], [loose[5]], [loose[6]], [loose[7]])

        # Per-chunk triangle spans (P3): a hover/zoom ray prefilters chunks
        # by AABB and runs Möller-Trumbore only on the spans it crosses.
        tri_spans: list = ((list(loose[8]) if loose[8]
                            else [(None, 0, n_loose_tris)])
                           if n_loose_tris else [])
        own_spans: list = []      # lazy placements' own arrays (#158)
        # What the current context lets you TOUCH: the whole scene at the
        # root, the children of the group you are inside otherwise. This
        # used to be `if scene.edit_group is None`, which took EVERY group
        # out of the index while you were inside one — so a group's children
        # were drawn and could not be clicked, and «todo está combinado»
        # (Marco, 2026-09-11).
        lazy = (self._pick_lazy_table()
                if hasattr(self, "_pick_lazy_table") else None)
        epoch_of = getattr(self, "_placements_epoch", None)   # stub VPs in tests
        # The context's placements, split into fixed and lazy, last as long
        # as the placements and the context: walking all 21 000 of them on
        # each change of the lazy set was ~20 ms of every such rebuild, a
        # few times a mouse move over the plant of #158.
        ckey = ((epoch_of(), id(scene.edit_group), oculto, id(lazy))
                if epoch_of is not None else None)
        cmemo = getattr(self, "_pick_cands_memo", None)
        if ckey is None or cmemo is None or cmemo[0] != ckey:
            cmemo = (ckey, *Viewport._pick_candidates(self, oculto, lazy))
            if ckey is not None:
                self._pick_cands_memo = cmemo
        _ck, tocables, fixed_c, lazy_pos = cmemo
        if lazy is not None:
            live = getattr(self, "_pick_live", None) or {}
            lazies_c = [lazy_pos[k][1] for k in sorted(
                (k for k in live if k in lazy_pos),
                key=lambda k: lazy_pos[k][0])]
        else:
            lazies_c = [g for _p, g in lazy_pos.values()]
        candidatos = fixed_c + lazies_c
        if candidatos:
            # The group block is cached across versions (keyed by each
            # chunk's identity + rev + flags): re-deriving per-face masks and
            # re-offsetting 300k triangle rows per scene change cost ~130 ms
            # per stroke/drag frame beside a big import.
            # The block (every placement's faces, owners and hard edges) is
            # keyed on the placements epoch: a loose edit — every frame of a
            # Move drag — no longer walks 1 300 chunks to learn that none of
            # them changed (2026-09-14).
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
                fixed, lazies = fixed_c, lazies_c
                fkey = (sig[0], oculto, len(fixed), id(scene.edit_group))
                fpart = getattr(self, "_pick_fixed_part", None)
                if fpart is None or fpart[0] != fkey:
                    # Called through the class: the stub viewports of the
                    # tests run this unbound.
                    fpart = self._pick_fixed_part = (fkey, Viewport._pick_block_part(
                        self, fixed, tocables, lazy_set, None))
                lpart = Viewport._pick_block_part(self, lazies, tocables,
                                                  lazy_set, fpart[1])
                blk = (sig, Viewport._pick_join_parts(self, fpart[1], lpart))
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
                infer_parts.append(block.get("infer", block["sel"]))
                loose_parts.append(
                    np.zeros(len(block["entities"]), dtype=bool))
                if block["v0"] is not None:
                    v0s.append(block["v0"])
                    e1s.append(block["e1"])
                    e2s.append(block["e2"])
                    tents.append(_offset_kept(self, block["te"], offset))
                    tri_spans += [(bb, n_loose_tris + s, n)
                                  for bb, s, n in block.get("spans", ())]
                own_spans = [(bb, a, b, c, te, o + offset)
                             for bb, a, b, c, te, o in block.get("own", ())]

        gedge_a = gedge_b = gedge_gi = gedge_sel = gedge_fixed = None
        gedge_layer = None
        gedge_groups: list = []
        gedge_ilayer: list = []
        gedge_ctx: list = []
        if candidatos:
            block = self._pick_block[1] if getattr(self, "_pick_block", None) \
                else {}
            gedge_a = block.get("gedge_a")
            gedge_b = block.get("gedge_b")
            gedge_gi = block.get("gedge_gi")
            gedge_layer = block.get("gedge_layer")
            gedge_sel = block.get("gedge_sel")
            gedge_groups = block.get("gedge_groups", [])
            gedge_ilayer = block.get("gedge_ilayer", [])
            gedge_ctx = block.get("gedge_ctx", [])
            gedge_fixed = block.get("gedge_fixed")

        edges: list = []
        ea: list = []
        eb: list = []
        esel: list = []
        esnap: list = []
        esoft: list = []
        show_hidden = bool(getattr(scene, "show_hidden_geometry", False))
        done = False
        head = None
        if _plain_edge_rules(scene):
            # Plain edges of the open mesh: selectable and snappable come
            # down to their layer and their own Hide (see _plain_edge_rules),
            # asked once per layer name, and the rest is read in flat
            # passes — the two questions and the rows per edge were most
            # of a 20 000-edge rebuild (~0.3 s, night of 19-11).
            from core.mesh import Edge as _Edge
            elist = scene.edges
            if all(type(e) is _Edge for e in elist):
                n = len(elist)
                xyz = np.fromiter(
                    (c for e in elist for v in (e.v0, e.v1)
                     for c in v.position.toTuple()),
                    dtype=np.float64, count=6 * n).reshape(n, 6)
                names = [getattr(e, "layer", None) for e in elist]
                states: dict = {}
                for nm, e in zip(names, elist):
                    if nm not in states:
                        states[nm] = scene._layer_state(e)
                vis = np.fromiter((states[nm][0] for nm in names),
                                  dtype=bool, count=n)
                lock = np.fromiter((states[nm][1] for nm in names),
                                   dtype=bool, count=n)
                shown = ~np.fromiter(
                    (bool(getattr(e, "hidden", False)) for e in elist),
                    dtype=bool, count=n) | show_hidden
                soft = np.fromiter(
                    (bool(getattr(e, "soft", False)) for e in elist),
                    dtype=bool, count=n)
                edges.extend(elist)
                head = (xyz[:, :3], xyz[:, 3:], vis & ~lock & shown,
                        vis & shown, soft)
                done = True
        for e in (() if done else scene.edges):
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
            # Snapping is a different question from selecting: a locked
            # edge is no target for a click and a fine target for a
            # dimension, while an edge that draws nothing is neither. The
            # same rule the snap scene applies (Scene.edge_snappable), kept
            # here so the corner a from-point acquires cannot come from a
            # line the user cannot see.
            esnap.append(scene.edge_snappable(e))
        # The rest of the model's loose edges — drawn around an open group /
        # component, a reference to snap to and never a thing to pick. They
        # are what a move started inside the component aligns to, and what
        # occludes the corners behind them.
        outer_of = getattr(self, "_outer_loose_meshes", None)
        for om in (outer_of() if outer_of is not None else ()):
            for e in om.edges:
                edges.append(e)
                esoft.append(bool(getattr(e, "soft", False)))
                ea.append([e.a.x(), e.a.y(), e.a.z()])
                eb.append([e.b.x(), e.b.y(), e.b.z()])
                esel.append(False)
                esnap.append(scene.edge_snappable(e))

        idx = SimpleNamespace(
            entities=entities,
            ent_place_idx=(place_idx if place_idx is not None
                           else np.full(len(entities), -1, np.int32)),
            ent_placements=placements,
            ent_area=np.concatenate(areas) if entities else np.empty(0),
            ent_sel=np.concatenate(sel_parts) if entities else np.empty(0, bool),
            ent_infer=(np.concatenate(infer_parts) if entities
                       else np.empty(0, bool)),
            ent_vis=np.concatenate(vis_parts) if entities else np.empty(0, bool),
            ent_loose=(np.concatenate(loose_parts) if entities
                       else np.empty(0, bool)),
            tri_v0=_cat_kept(self, "v0", v0s) if v0s else None,
            tri_e1=_cat_kept(self, "e1", e1s) if v0s else None,
            tri_e2=_cat_kept(self, "e2", e2s) if v0s else None,
            tri_ent=_cat_kept(self, "te", tents) if v0s else None,
            edges=edges,
            edge_a=_edge_rows(head, 0, ea, edges),
            edge_b=_edge_rows(head, 1, eb, edges),
            edge_sel=_edge_rows(head, 2, esel, edges),
            edge_snap=_edge_rows(head, 3, esnap, edges),
            edge_soft=_edge_rows(head, 4, esoft, edges),
            gedge_a=gedge_a,
            gedge_b=gedge_b,
            gedge_gi=gedge_gi,
            gedge_layer=gedge_layer,
            gedge_sel=gedge_sel,
            gedge_groups=gedge_groups,
            gedge_ilayer=gedge_ilayer,
            gedge_ctx=gedge_ctx,
            gedge_fixed=gedge_fixed,
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
        # The rest state's index stays beside the new one while a drag goes
        # back to it each pointer move (see note_same_geometry); otherwise
        # one index at a time, as ever (they are big on a big model).
        rest = getattr(self, "_pick_rest", None)
        self._pick_index_prev = (
            cached if cached is not None and rest is not None
            and cached[0][0] == rest[0]
            and _content_ver(self) - rest[1] <= 2 else None)
        self._pick_index_cache = (key, idx, getattr(self, "_pick_block", None))
        return idx

    def note_same_geometry(self, same_as) -> None:
        """The model is now, to the last bit, what it was at content version
        ``same_as`` — a prism push slid its cap back to where the drag took
        it, and only its own moves bumped the version since: the pick index
        made at ``same_as`` answers for this version too (it is the index a
        rebuild would make), and is kept while the drag returns to it. The
        caller vouches for it; the next version bump ends it."""
        now = _content_ver(self)
        if not isinstance(now, int) or not isinstance(same_as, int):
            return                       # a frozen preview: not this case
        self._pick_geom_alias = (now, same_as)
        self._pick_rest = (same_as, now)

    def _pick_geometry_ver(self):
        """``_content_ver``, read through :meth:`note_same_geometry`'s
        alias while it stands."""
        now = _content_ver(self)
        alias = getattr(self, "_pick_geom_alias", None)
        return alias[1] if alias is not None and alias[0] == now else now

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
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        near = (("ray", origin, direction) if reach is None
                else ("ray", origin, direction, float(reach)))
        idx = self._pick_index(near="skip" if nat is not None else near)
        if nat is not None:
            # The lazy placements from the engine, none baked (#158).
            t = self._ray_hits(idx, origin, direction, idx.ent_vis,
                               reduce_global=True, reach=reach, own=False)
            lz = Viewport._lazy_face_hits(self, nat, origin, direction,
                                          "vis", reach)
            if lz is not None:
                tl = float(lz[0].min())
                t = tl if t is None else min(t, tl)
        elif idx is None or (getattr(idx, "tri_v0", None) is None
                             and not getattr(idx, "own_spans", None)):
            return None
        else:
            t = self._ray_hits(idx, origin, direction, idx.ent_vis,
                               reduce_global=True, reach=reach)
        if t is None or t == float("inf") or (reach is not None
                                               and t > reach):
            return None
        return float(t)

    def _ray_hits(self, idx, origin, direction, ent_mask,
                  reduce_global: bool = False, reach: float | None = None,
                  own: bool = True):
        """:meth:`_ray_hits_np`, through the native engine when its ray
        pass gives this NumPy's bits (:func:`_mt_native`): the same rows,
        the same per-entity minima, without the row gathers and the NumPy
        calls per pass (~1.3 ms a call in the Plaza's 9 674-face group,
        19-11). While it is on trial NumPy answers and the two are
        compared."""
        import numpy as np
        nat = _mt_native()
        if nat is None or not _mt_arrays_ok(*(
                (idx.tri_v0, idx.tri_e1, idx.tri_e2)
                if getattr(idx, "tri_v0", None) is not None else ())):
            return Viewport._ray_hits_np(self, idx, origin, direction,
                                         ent_mask, reduce_global, reach, own)
        try:
            got = Viewport._ray_hits_np(self, idx, origin, direction,
                                        ent_mask, reduce_global, reach, own,
                                        nat=nat)
        except (ValueError, TypeError):
            got = _MT_FAILED
        if got is not _MT_FAILED and _MT_SHADOW[0] <= 0:
            return got
        want = Viewport._ray_hits_np(self, idx, origin, direction, ent_mask,
                                     reduce_global, reach, own)
        if got is not _MT_FAILED:
            if want is None or got is None or reduce_global:
                same = (want is got if want is None or got is None
                        else _mt_same(np.float64(got), np.float64(want)))
            else:
                same = _mt_same(got, want)
            _mt_judge(same)
        return want

    def _ray_hits_np(self, idx, origin, direction, ent_mask,
                     reduce_global: bool = False, reach: float | None = None,
                     own: bool = True, nat=None):
        """Per-entity nearest ray parameter over the index triangles whose
        entity passes ``ent_mask``. Returns an (E,) array of t (``inf`` = no
        hit), the single nearest t as a float when ``reduce_global``, or
        ``None`` when the index has no triangles. Same acceptance
        thresholds as :func:`_ray_triangle`.

        P3: the Möller–Trumbore pass runs per chunk SPAN on array views,
        after a ray-vs-AABB prefilter — a hover/zoom ray only pays for the
        chunks it actually crosses (the full 700k-row pass cost 25–45 ms
        per pick against the piscina scene). ``own`` False leaves out the
        lazy placements' own spans (the engine answers for them, see
        _face_hits)."""
        import numpy as np
        own = (getattr(idx, "own_spans", None) or ()) if own else ()
        if idx.tri_v0 is None and not own:
            return None
        o = np.array([origin.x(), origin.y(), origin.z()])
        d = np.array([direction.x(), direction.y(), direction.z()])
        fast = (Viewport._static_ray_rows(
                    self, idx, ent_mask,
                    (float(o[0]), float(o[1]), float(o[2])),
                    (float(d[0]), float(d[1]), float(d[2])))
                if (reach is None and not own and idx.tri_v0 is not None
                    and hasattr(self, "_static_occluders"))
                else None)
        if fast is not None:
            # The engine's BVH in place of the span boxes below.
            spans = ([(None, idx.tri_v0[fast], idx.tri_e1[fast],
                       idx.tri_e2[fast], idx.tri_ent[fast], 0)]
                     if len(fast) and nat is None else [])
        elif idx.tri_v0 is None:
            spans = []
        else:
            spans = (getattr(idx, "tri_spans", None)
                     or [(None, 0, len(idx.tri_v0))])
        # Lazy placements' own arrays (#158) ride the same loop: a span is
        # then (bbox, v0, e1, e2, local tri_ent, entity offset).
        spans = list(spans) + list(own)
        if len(spans) > 64 and fast is None:
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
            met = _boxes_meet_native(o, d, blo, bhi, reach)
            if met is None:
                met = _boxes_meet_numpy(o, d, blo, bhi, reach)
            spans = [(None,) + tuple(spans[i][1:]) for i in met.tolist()]
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
        if nat is not None:
            return Viewport._ray_pass_native(
                idx, nat, o3, d3, lim, fast, ranges, rest, ent_mask,
                face_t, reduce_global)
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
            t, hit = _moller_trumbore_py(o, d, v0, e1, e2)
            hit &= ent_mask[te]
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

    @staticmethod
    def _ray_pass_native(idx, nat, o3, d3, lim, fast, ranges, rest,
                         ent_mask, face_t, reduce_global):
        """The end of :meth:`_ray_hits_np` in the native engine
        (core/rays.rs): the index rows the BVH named (``fast``) or the
        span ``ranges`` the ray's boxes kept, read in place as ONE pass
        (its row count picks the gemv's mode, as NumPy's one pass would),
        then the lazy placements' own spans (``rest``) one by one; each
        pass's hits are masked and folded into ``face_t`` or the global
        minimum there. Raises TypeError where the engine cannot read the
        arrays as they are (then NumPy answers the call)."""
        import numpy as np
        mod, modes = nat
        best = float("inf")
        ft = None if reduce_global else face_t

        def run(v0, e1, e2, te, eoff, rows=None, rng=None):
            if not _mt_arrays_ok(v0, e1, e2):
                raise TypeError("ray pass arrays")
            te = np.asarray(te)
            if te.dtype != np.int64:
                te = te.astype(np.int64)
            return mod.ray_face_min(o3, d3, v0, e1, e2, te, int(eoff),
                                    ent_mask, modes, rows=rows, ranges=rng,
                                    face_t=ft, best=best)
        if fast is not None and len(fast):
            best = run(idx.tri_v0, idx.tri_e1, idx.tri_e2, idx.tri_ent, 0,
                       rows=np.ascontiguousarray(fast, dtype=np.int64))
        if ranges:
            best = run(idx.tri_v0, idx.tri_e1, idx.tri_e2, idx.tri_ent, 0,
                       rng=np.array(ranges, dtype=np.int64).reshape(-1, 2))
        for span in rest:
            bb, v0, e1, e2, te_local, eoff = span
            if not len(v0):
                continue
            if bb is not None and not _ray_aabb(o3, d3, bb[0], bb[1], lim):
                continue
            best = run(v0, e1, e2, te_local, eoff)
        return best if reduce_global else face_t

    @staticmethod
    def _sel_infer_union(idx):
        """``ent_sel | ent_infer`` of the pick index, or None where the two
        masks are the same (at the model root, with the rest hidden): worked
        out once per index (#1392)."""
        sel = getattr(idx, "ent_sel", None)
        inf = getattr(idx, "ent_infer", None)
        if sel is None or inf is None or inf is sel:
            return None
        memo = getattr(idx, "_sel_infer_union_memo", None)
        if memo is not None and memo[0] is sel and memo[1] is inf:
            return memo[2]
        union = (sel | inf if len(sel) == len(inf)
                 and bool((sel != inf).any()) else None)
        try:
            idx._sel_infer_union_memo = (sel, inf, union)
        except AttributeError:          # a bare stand-in index (tests)
            pass
        return union

    def _ray_hits_sel_infer(self, idx, origin, direction, nat, union):
        """:meth:`_ray_hits` over the entities that are selectable OR
        inferable, memoised for this ray, index and scene version: ``(t,
        rows)`` — the per-entity nearest t and the rows the ray met — that
        both :meth:`_face_hits` "sel" and "infer" mask afterwards (#1392),
        or None. Read-only: the two share it."""
        key = (origin.x(), origin.y(), origin.z(),
               direction.x(), direction.y(), direction.z(),
               getattr(self.scene, "version", None),
               id(getattr(self.scene, "mesh", None)))
        # Two rays kept: a hover reads the cursor at the event's own
        # position (the references) and at the whole pixel (the snap, the
        # coordinate readout), interleaved — one slot lost each to the
        # other.
        last = getattr(self, "_ray_union_memo", None)
        for memo in (last, getattr(self, "_ray_union_prev", None)):
            if (memo is not None and memo[0] == key and memo[2] is idx
                    and memo[3] is nat and memo[4] is union):
                return memo[1]
        self._ray_union_prev = last
        face_t = self._ray_hits(idx, origin, direction, union,
                                own=nat is None)
        if face_t is not None:
            import numpy as np
            face_t.flags.writeable = False
            hit = np.flatnonzero(np.isfinite(face_t))
            hit.flags.writeable = False
            face_t = (face_t, hit)
        self._ray_union_memo = (key, face_t, idx, nat, union)
        return face_t

    def _ray_near(self, x: float, y: float):
        """What a ray pick at widget pixel ``(x, y)`` asks the pick index
        to bake: nothing with the engine, which answers for the lazy
        placements itself (see _face_hits), the placements the ray meets
        otherwise."""
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        return "skip" if nat is not None else ("px", x, y)

    def _face_hits(self, idx, origin, direction, which: str = "sel"):
        """The faces the ray from ``origin`` along ``direction`` meets, each
        at its nearest t, of the index entities that pass ``which``
        ("sel": selectable, "vis": visible, "infer": a face the snap
        engine may infer from — the selectable ones PLUS the rest of the
        model around an open group / component, which cannot be picked but
        is drawn as a reference) — in the index's order, which the ties of
        every pick go by: ``SimpleNamespace(t, area, loose, ent(k) →
        (face, owner), place(k) → placement)``, or None when the index has
        no triangles. With the experimental engine the lazy placements'
        faces come from it, none of them baked (#158), after the index's
        own, in the order their bakes would follow them."""
        import numpy as np
        from types import SimpleNamespace
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if which == "sel":
            mask = idx.ent_sel
        elif which == "infer":
            mask = getattr(idx, "ent_infer", idx.ent_sel)
        else:
            mask = idx.ent_vis
        union = (Viewport._sel_infer_union(idx)
                 if which in ("sel", "infer") else None)
        rows = None
        if not len(idx.entities):
            face_t = None
        elif union is not None:
            # Inside an open group a hover asks for both readings of the
            # same ray — the snap engine's ("infer", #1327) and the pick's
            # ("sel": the «Face center» of #736, the tools' planes): one
            # pass over the union answers both, each masked after. The
            # nearest t of an entity does not depend on which others pass,
            # and the pass costs the same whatever the mask (#1392).
            shared = Viewport._ray_hits_sel_infer(self, idx, origin,
                                                  direction, nat, union)
            face_t = None if shared is None else shared[0]
            if face_t is not None:
                hit = shared[1]                 # the union's rows met
                rows = hit[mask[hit]]
        else:
            face_t = self._ray_hits(idx, origin, direction, mask,
                                    own=nat is None)
        lazy = (Viewport._lazy_face_hits(self, nat, origin, direction, which)
                if nat is not None else None)
        if face_t is None and lazy is None:
            return None
        if rows is None:
            rows = (np.flatnonzero(np.isfinite(face_t)) if face_t is not None
                    else np.empty(0, np.int64))
        pidx = getattr(idx, "ent_place_idx", None)
        n = len(rows)

        def ent(k):
            if k < n:
                return idx.entities[int(rows[k])]
            return lazy[3](k - n)

        def owner(k):
            if k < n:
                return _entity_owner(idx.entities, int(rows[k]))
            return lazy[5](k - n)

        def place(k):
            if k < n:
                i = int(rows[k])
                if pidx is not None and i < len(pidx) and pidx[i] >= 0:
                    return idx.ent_placements[int(pidx[i])]
                return _entity_owner(idx.entities, i)
            return lazy[4](k - n)
        t = face_t[rows] if n else np.empty(0)
        area = idx.ent_area[rows] if n else np.empty(0)
        loose = idx.ent_loose[rows] if n else np.empty(0, bool)
        if lazy is not None:
            t = np.concatenate([t, lazy[0]])
            area = np.concatenate([area, lazy[1]])
            loose = np.concatenate([loose, np.zeros(len(lazy[0]), bool)])
        return SimpleNamespace(t=t, area=area, loose=loose, ent=ent,
                               owner=owner, place=place)

    def _lazy_sel_rows(self, nat):
        """The rows of the lazy table whose faces a pick may land on (see
        _lazy_native's ``snap``, less what the open context keeps from
        being touched), in the index's order."""
        import numpy as np
        memo = getattr(self, "_lazy_sel_memo", None)
        if memo is not None and memo[0] is nat:
            return memo[1]
        toc = self._pick_cands_memo[1]
        groups = self._pick_lazy_table()[0]
        snap = nat[1]
        sel = np.fromiter((i for i in snap.tolist() if id(groups[i]) in toc
                          and self.scene.entity_selectable(groups[i])),
                          np.int64)
        self._lazy_sel_memo = (nat, sel)
        return sel

    def _lazy_face_hits(self, nat, origin, direction, which,
                        reach: float | None = None):
        """The lazy placements' faces the ray meets, from the engine (see
        _face_hits): ``(t, area, order, ent(k), place(k))`` as their bakes
        would give them, or None. The engine hands the triangles the ray
        may meet; which it meets, and where, is decided here by the pick
        index's own test."""
        import numpy as np
        iset, snap, vis = nat
        if which == "sel":
            rows = Viewport._lazy_sel_rows(self, nat)
        elif which == "infer":
            # The lazy placements the snap may land on (visible, unlocked),
            # touchable or not — see _face_hits.
            rows = snap
        else:
            rows = vis
        if not len(rows):
            return None
        o = np.array([origin.x(), origin.y(), origin.z()])
        d = np.array([direction.x(), direction.y(), direction.z()])
        pl, tr, v0, e1, e2 = iset.ray_cands(
            np.ascontiguousarray(rows, np.int64), tuple(o.tolist()),
            tuple(d.tolist()), float("inf") if reach is None else float(reach))
        if not len(pl):
            return None
        t, hit = _moller_trumbore(o, d, v0, e1, e2)
        k = np.flatnonzero(hit)
        if not len(k):
            return None
        groups = self._pick_lazy_table()[0]
        lazy_pos = self._pick_cands_memo[3]
        bases: dict = {}
        best: dict = {}                     # (row, entity) → nearest t
        for i, r, tt in zip(pl[k].tolist(), tr[k].tolist(), t[k].tolist()):
            base = bases.get(i)
            if base is None:
                g = groups[i]
                base = bases[i] = self._proto_base_chunk(
                    g.mesh, _paint_of(self, g))
            key = (i, int(base["tri_ent"][r]))
            if tt < best.get(key, float("inf")):
                best[key] = tt
        keys = sorted(best, key=lambda ij: (lazy_pos[id(groups[ij[0]])][0],
                                            ij[1]))
        scale: dict = {}
        for i in bases:
            # The placed areas as _instance_chunk makes them.
            L = _placed_maps(groups[i].xform)[0]
            scale[i] = abs(float(np.linalg.det(L))) ** (2.0 / 3.0)
        tt = np.array([best[ij] for ij in keys], dtype=np.float64)
        area = np.array([bases[i]["areas"][j] * scale[i] for i, j in keys],
                        dtype=np.float64)

        def ent(m):
            i, j = keys[m]
            return bases[i]["faces"][j], self._owner_of(groups[i])

        def place(m):
            return groups[keys[m][0]]

        def owner(m):
            return self._owner_of(groups[keys[m][0]])
        return tt, area, keys, ent, place, owner

    def _hover_hits(self, idx, origin, direction):
        """:meth:`_face_hits` of the selectable faces, memoised for the
        current cursor ray, without what lies past the active cut. One
        SelectTool hover fires pick_group + pick_face on the same mouse
        move, and each used to re-run the full Möller–Trumbore pass (~20 ms
        over a 260k-triangle import); they now share one pass and post-mask
        by loose/group."""
        key = (self.scene.version, id(self.scene.mesh),
               origin.x(), origin.y(), origin.z(),
               direction.x(), direction.y(), direction.z())
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        cached = getattr(self, "_hover_hits_cache", None)
        # The answer is per entity OF THIS INDEX: a lazy index (#158) is
        # rebuilt between two asks of one hover when a query brings new
        # placements in, and the old index's per-entity times read against
        # the new one picked the wrong face, or ran past its end.
        if (cached is not None and cached[0] == key and cached[2] is idx
                and cached[3] is nat):
            return cached[1]
        hits = Viewport._face_hits(self, idx, origin, direction, "sel")
        Viewport._drop_past_cut(self, hits, origin, direction)
        self._hover_hits_cache = (key, hits, idx, nat)
        return hits

    def _infer_hits(self, idx, origin, direction):
        """:meth:`_hover_hits` of the faces the snap engine may INFER FROM:
        every selectable one plus the rest of the model around an open group
        / component (drawn faded, never pickable). Geometry being moved is
        still left out by the caller's own rules — this only widens the
        context, not the moving set."""
        key = (self.scene.version, id(self.scene.mesh),
               origin.x(), origin.y(), origin.z(),
               direction.x(), direction.y(), direction.z())
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        cached = getattr(self, "_infer_hits_cache", None)
        if (cached is not None and cached[0] == key and cached[2] is idx
                and cached[3] is nat):
            return cached[1]
        hits = Viewport._face_hits(self, idx, origin, direction, "infer")
        Viewport._drop_past_cut(self, hits, origin, direction)
        self._infer_hits_cache = (key, hits, idx, nat)
        return hits

    def _drop_past_cut(self, hits, origin, direction) -> None:
        """Hits beyond the active cut are on clipped-away geometry: their
        ``t`` becomes ``inf``, in place."""
        sp = _active_cut(self.scene)
        if sp is not None and hits is not None and len(hits.t):
            import numpy as np
            o = np.array([origin.x(), origin.y(), origin.z()])
            d = np.array([direction.x(), direction.y(), direction.z()])
            with np.errstate(invalid="ignore"):
                pts = o + d * hits.t[:, None]
                hidden = sp.hidden(pts)
            hits.t = np.where(hidden, np.inf, hits.t)

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

    def pick_visible_edge(self, screen_x: float, screen_y: float,
                          with_soft: bool = False):
        """The edge a CLICK means: like :meth:`pick_edge`, but an edge the
        user cannot see never wins — a soft edge (the seams of a smooth
        surface, which are not drawn) unless hidden geometry is shown, and
        an edge behind the model. The usual rule, and what made a
        cylinder's side unclickable (@pacaeiro, issue #71: the invisible
        seams, front and back, took up to 90 % of the side at normal zoom).
        Tools that want the tube's seam as a reference keep pick_edge.

        ``with_soft``: soft edges count even with hidden geometry off (the
        Eraser's soften / harden strokes, #831); edges behind the model
        still never win."""
        return self._pick_edge(screen_x, screen_y, visible_only=True,
                               with_soft=with_soft)

    def _pick_edge(self, screen_x: float, screen_y: float,
                   visible_only: bool, which: str = "sel",
                   with_soft: bool = False):
        """``which``: "sel" for the edges a click means, "snap" for the ones a
        reference may hold — the rest of the model's loose edges, drawn
        around an open group / component, are snappable and not selectable."""
        import numpy as np
        from core.edge_grid import segment_distances
        idx = self._pick_index(near="skip")
        if idx.edge_a is None:
            return None
        # The projection pick_vertex and the snap read too, kept while the
        # camera and the loose edges stay (two fresh projections of the open
        # group's edges were ~3 ms of every hover with Line in the Plaza,
        # 19-11).
        ledge = getattr(self, "_ledge_screen", None)      # stub VPs in tests
        lp = ledge() if ledge is not None and len(idx.edge_a) else None
        if lp is None:
            ax, ay, oka = self._project_px(idx.edge_a)
            bx, by, okb = self._project_px(idx.edge_b)
            lp = (ax, ay, bx, by, oka & okb)
        ax, ay, bx, by, ok = lp
        allowed = (idx.edge_sel if which == "sel"
                   else getattr(idx, "edge_snap", idx.edge_sel))
        ok = ok & allowed
        soft = getattr(idx, "edge_soft", None)
        if (visible_only and not with_soft and soft is not None
                and not getattr(self.scene, "show_hidden_geometry", False)):
            ok &= ~soft
        sp = _active_cut(self.scene)
        if sp is not None:
            ok &= ~(sp.hidden(idx.edge_a) & sp.hidden(idx.edge_b))
        if not ok.any():
            return None
        # core.edge_grid's pass is this one's arithmetic (native past
        # NATIVE_MIN segments, bit for bit).
        d = segment_distances(ax, ay, bx, by, ok, screen_x, screen_y)
        if not visible_only:
            i = int(np.argmin(d))
            return idx.edges[i] if d[i] < self.pick_threshold_px else None
        # Nearest first, skipping the ones hidden behind the model; a few
        # tries are plenty (the threshold holds only a handful).
        for i in _nearest_order(d, self.pick_threshold_px)[:8]:
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

    def _shown_guides(self) -> list:
        return shown_guides(self.scene)

    def _circle_pick_distance(self, g, screen_x: float, screen_y: float):
        """Screen distance from the cursor to a guide circle's rim, or None
        when it cannot be projected. Sampling is display-only; the stored
        circle stays analytic."""
        pts = []
        for p in g.sample_points(64):
            px = self._world_to_pixel(p)
            if px is None:
                return None            # part of the circle is behind the eye
            pts.append(px)
        best = float("inf")
        n = len(pts)
        for i in range(n):
            d = _point_to_segment_distance_2d((screen_x, screen_y),
                                              pts[i], pts[(i + 1) % n])
            if d < best:
                best = d
        return best

    def pick_guide(self, screen_x: float, screen_y: float):
        """Return the construction guide nearest the cursor within the pick
        threshold, or ``None`` (for the Eraser). One on a hidden or
        locked layer is not there to pick."""
        selectable = getattr(self.scene, "entity_selectable", None)
        guides = [g for g in getattr(self.scene, "guides", None) or ()
                  if selectable is None or selectable(g)]
        if not guides:
            return None
        best, best_d = None, self.pick_threshold_px
        for g in guides:
            if getattr(g, "is_circle", False):
                d = self._circle_pick_distance(g, screen_x, screen_y)
                if d is not None and d < best_d:
                    best_d = d
                    best = g
                continue
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
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if nat is not None:
            return self._pick_vertex_unbaked(screen_x, screen_y, nat)
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
        # The corners within the threshold, in index order, at the
        # distances one np.hypot pass over all of them gives: with the
        # engine only the candidates are measured (~3 ms of NumPy a hover
        # over the ~1 000 placements of the Plaza, 19-11).
        cand, dc = _px_near(px, py, ok, screen_x, screen_y,
                            self.pick_threshold_px)

        def vertex_of(i):
            if i < 2 * n:
                e = idx.edges[int(i) % n]
                return e.a if i < n else e.b
            j = int(i) - 2 * n
            arr = idx.gedge_a if j < m else idx.gedge_b
            p = arr[j % m]
            return QVector3D(p[0], p[1], p[2])
        order = cand[np.argsort(dc)]
        if not len(order):
            return None
        # A corner only an edge that draws nothing holds is not on screen:
        # acquiring it as a from-point is how a phantom point gets into the
        # next face (the same rule the snap scene applies to the edges).
        snap_ok = None if n == 0 else getattr(idx, "edge_snap", None)
        if snap_ok is not None:
            order = np.asarray([i for i in order
                                if i >= 2 * n or snap_ok[int(i) % n]],
                               dtype=order.dtype)
            if not len(order):
                return None
        # The nearest one, alone first (usually the answer); then the
        # rest in batches of 8, 16, 32… sharing one occlusion pass, as the
        # snap engine reads its candidates. One ray per candidate, in turn,
        # took minutes a pointer move over a dense mesh whose hundreds of
        # nearby corners were nearly all hidden (a 128 788-face STL in #158).
        # A corner shared by several edges comes once per end: asked once
        # (the same point, the same answer), in batches of at most 1 024 —
        # zoomed out over the plant of #158 some 65 000 hidden corners lay
        # under the cursor, and a batch of 32 768 rays built ~1.4 GB of box
        # tests and took 7 s.
        first = vertex_of(order[0])
        if not self._is_occluded(first):
            return first
        if len(order) > 1:
            # Each point once, where it first comes (the nearest of its
            # copies on screen): the same answer as asking every copy.
            xyz = np.empty((len(order), 3))
            for lo_i, hi_i, arr, base in (
                    (0, n, idx.edge_a, 0), (n, 2 * n, idx.edge_b, n),
                    (2 * n, 2 * n + m, idx.gedge_a, 2 * n),
                    (2 * n + m, 2 * n + 2 * m, idx.gedge_b, 2 * n + m)):
                w = np.flatnonzero((order >= lo_i) & (order < hi_i))
                if len(w):
                    xyz[w] = arr[order[w] - base]
            _u, at = np.unique(xyz, axis=0, return_index=True)
            at.sort()
            order = order[at]
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
            size = min(size * 2, 1024)
        return None

    def _pick_vertex_unbaked(self, screen_x, screen_y, nat):
        """``pick_vertex`` with the lazy placements' corners from the
        native engine, none of them baked (#158): the loose edges' and the
        fixed placements' corners as the index holds them, every lazy
        placement's as its bake would hold them, at the same pixels —
        nearest first, the hidden ones left out, as there."""
        import numpy as np
        iset, snap, _vis = nat
        idx = self._pick_index(near="skip")
        thr = self.pick_threshold_px
        parts = []                       # (px, py, in front, points)
        ledge = getattr(self, "_ledge_screen", None)
        lp = ledge() if ledge is not None else None
        if lp is None and idx.edge_a is not None and len(idx.edge_a):
            ax, ay, oka = self._project_px(idx.edge_a)
            bx, by, okb = self._project_px(idx.edge_b)
            lp = (ax, ay, bx, by, oka & okb)
        if lp is not None:
            ax, ay, bx, by, ok = lp
            # Corners only an edge that draws nothing holds are not on
            # screen (see pick_vertex).
            snap_ok = getattr(idx, "edge_snap", None)
            if snap_ok is not None:
                ok = ok & snap_ok
            parts += [(ax, ay, ok, idx.edge_a), (bx, by, ok, idx.edge_b)]
        fx = getattr(idx, "gedge_fixed", None)
        m = fx[1] if fx is not None else 0
        gp = self._gedge_screen() if m else None
        if gp is not None:
            # The fixed placements' edges lead the index's; the lazy ones
            # it holds now are among those the engine answers for.
            ax, ay, bx, by, ok = gp
            parts += [(ax[:m], ay[:m], ok[:m], idx.gedge_a[:m]),
                      (bx[:m], by[:m], ok[:m], idx.gedge_b[:m])]
        # What the frame shows in front of a corner hides it: zoomed out
        # over the plant of #158 some 800 000 corners of the copies lay
        # under the cursor, nearly all hidden, and a ray each took 15 s.
        # The rule that kept such placements out of the index unbaked (see
        # _pick_materialize), per corner at its own pixel. A corner whose
        # pixel and the 8 around it all show something nearer is not to be
        # seen on screen, even where an ideal ray to its very point grazes
        # past (a post rising beside it, seen from afar): one such corner
        # in 109 cursor positions over that plant, left for another a pixel
        # away. Whatever comes back is still a ray's visible answer.
        seen = self._depth_limits(float(screen_x), float(screen_y), thr)
        ds, ps = [], []
        for x, y, ok, pts in parts:
            k, d = _px_near(x, y, ok, screen_x, screen_y, thr, pts, seen)
            if len(k):
                ds.append(d)
                ps.append(pts[k])
        if len(snap):
            M = self._np_mvp()
            pl, _e, _n, xyz, rx, ry = iset.corners_near(
                snap, np.ascontiguousarray(M.T).ravel().tolist(),
                float(self.width()), float(self.height()),
                float(screen_x), float(screen_y), thr * (1.0 + 1e-9) + 1e-9,
                seen)
            if len(pl):
                d = np.hypot(rx - screen_x, ry - screen_y)
                k = np.flatnonzero(d < thr)
                if len(k):
                    ds.append(d[k])
                    ps.append(xyz[k])
        if not ds:
            return None
        d = np.concatenate(ds)
        pts = np.concatenate(ps)[np.argsort(d, kind="stable")]
        at = self._first_clear(pts)
        if at is not None:
            return QVector3D(*pts[at].tolist()) if at >= 0 else None
        first = QVector3D(*pts[0].tolist())
        if not self._is_occluded(first):
            return first
        if len(pts) > 1:
            # Each point once, where it first comes (see pick_vertex): a
            # stable sort by x, y, z puts the copies of a point together,
            # the first first (np.unique by rows took 6 ms on 11 000).
            by = np.lexsort((pts[:, 2], pts[:, 1], pts[:, 0]))
            srt = pts[by]
            lead = np.ones(len(srt), dtype=bool)
            lead[1:] = (srt[1:] != srt[:-1]).any(axis=1)
            pts = pts[np.sort(by[lead])]
        # Batches of 8, 32, 128… up to 1 024: with the rays this cheap the
        # calls were the cost (~0.4 ms each, 13 over the 7 000 corners a
        # roof hides near the cursor over the plant of #158).
        k, size = 1, 8
        while k < len(pts):
            batch = pts[k:k + size]
            seen_at = np.flatnonzero(~np.array(self._occluded_many(batch),
                                               dtype=bool))
            if len(seen_at):
                return QVector3D(*batch[seen_at[0]].tolist())
            k += size
            size = min(size * 4, 1024)
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
        idx = self._pick_index(near=Viewport._ray_near(self, screen_x, screen_y))
        hits = self._hover_hits(idx, origin, direction)
        if hits is None or not len(hits.t):
            return None
        face_t = np.where(hits.loose, hits.t, np.inf)
        best_t = face_t.min()
        if not np.isfinite(best_t):
            return None
        eps = self._coplanar_eps(origin, direction, float(best_t))
        cand = np.where(face_t <= best_t + eps)[0]
        if len(cand) == 1:
            return hits.ent(int(cand[0]))[0]
        return hits.ent(int(cand[np.argmin(hits.area[cand])]))[0]

    def pick_face_any(self, screen_x: float, screen_y: float):
        """Front-most face under the cursor across the loose mesh **and** every
        group: returns ``(face, group_or_None)``. Same coplanar tiebreak as
        :meth:`pick_face` (the smallest of the overlapping faces wins). The
        group half is what lets a tool tell "this face is inside a container"
        — drawing takes its plane, Push/Pull refuses it until the group is
        opened. While a group IS open its own faces are the loose part and
        come back with ``None``; the model around it is in the index for
        snapping and occlusion only, never as an answer here (the snap
        engine's own reading is :meth:`pick_face_inference`).

        Memoised per cursor position and view: a hover asks up to three
        times (work plane, acquisition, on-face flag) for the same answer."""
        face, owner, _place, _mesh = Viewport._face_any(
            self, screen_x, screen_y, "sel")
        return face, owner

    def _face_any(self, screen_x: float, screen_y: float, which: str):
        """``pick_face_any`` behind ``which`` (see :meth:`_face_hits`):
        ``(face, owner, placement, mesh)``, memoised per variant."""
        if which == "infer" and (
                self.scene.edit_group is None
                or bool(getattr(self, "_rest_is_hidden",
                                lambda: False)())):
            # At the root (and with the rest hidden) there is nothing outside
            # the context to widen to: the same faces answer, and the hover
            # pays for one ray pass, not two.
            return Viewport._face_any(self, screen_x, screen_y, "sel")
        idx = self._pick_index(near=Viewport._ray_near(self, screen_x, screen_y))
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        try:
            cam = self.camera
            from views.array_bake import reading_now
            key = (which, round(screen_x, 2), round(screen_y, 2), id(idx),
                   cam.yaw, cam.pitch, cam.distance, cam.perspective,
                   cam.target.x(), cam.target.y(), cam.target.z(),
                   self.width(), self.height(), reading_now())
        except AttributeError:            # a bare stand-in (tests): no memo
            key = None
        slot = ("_face_any_memo" if which == "sel"
                else "_face_infer_memo")
        cached = getattr(self, slot, None)
        # Keyed by the index itself, not its id(): a rebuilt index can be
        # given the address of the one it replaced.
        if (key is not None and cached is not None and cached[0] == key
                and len(cached) > 3 and cached[2] is idx
                and cached[3] is nat):
            return cached[1]
        result = (None, None, None, None)
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is not None and direction is not None:
            import numpy as np
            hits = (self._hover_hits(idx, origin, direction) if which == "sel"
                    else self._infer_hits(idx, origin, direction))
            if hits is not None and len(hits.t):
                face_t = hits.t
                best_t = face_t.min()
                if np.isfinite(best_t):
                    eps = self._coplanar_eps(origin, direction, float(best_t))
                    cand = np.where(face_t <= best_t + eps)[0]
                    if len(cand) == 1:
                        chosen = int(cand[0])
                    else:
                        chosen = int(cand[np.argmin(hits.area[cand])])
                    face, owner = hits.ent(chosen)
                    place = hits.place(chosen)
                    mesh = (getattr(place, "mesh", None)
                            if place is not None else self.scene.mesh)
                    result = (face, owner, place, mesh)
        if key is not None:
            setattr(self, slot, (key, result, idx, nat))
        return result

    def pick_face_inference(self, screen_x: float, screen_y: float):
        """The face the SNAP ENGINE may read under the cursor as
        ``(face, placement_or_None)``: selectable faces as
        :meth:`pick_face_placement`, plus the rest of the model drawn
        around an open group / component — faded, never pickable, but a
        reference the cursor may infer «On face» from, and the plane a
        planar tool or a moved part lands on.

        Picking never uses this: a click outside the open context must not
        select or edit what it cannot touch (see :meth:`pick_face_any`)."""
        face, _owner, place, _mesh = Viewport._face_any(
            self, screen_x, screen_y, "infer")
        return face, place

    def pick_face_placement(self, screen_x: float, screen_y: float):
        """Like :meth:`pick_face_any`, but the group half is the PLACEMENT
        the face was hit through — the proxy whose composed matrix puts it
        in the world — not the top-level owner a click would select. What
        every face-PLANE reading needs: the owner of a nested component
        carries the container's matrix, so a rectangle on the pergola's
        post got the post's plane in the wrong place (Marco, 2026-09-14)."""
        face, _owner, place, _mesh = Viewport._face_any(
            self, screen_x, screen_y, "sel")
        if face is None:
            return None, None
        return face, place

    def _smallest_at_front(self, hits, origin, direction):
        """Rows of ``hits`` a ray pick lands on: of the faces at the nearest
        depth (see :meth:`_coplanar_eps`), the smallest, with those of the
        same area up to float noise. Empty when nothing was hit. The same
        tiebreak as :meth:`pick_face`, for the picks that answer an object."""
        import numpy as np
        nearest = float(hits.t.min())
        if not np.isfinite(nearest):
            return np.empty(0, np.intp)
        eps = self._coplanar_eps(origin, direction, nearest)
        cand = np.flatnonzero(hits.t <= nearest + eps)
        area = hits.area[cand]
        return cand[area <= float(area.min()) * (1.0 + 1e-6)]

    def pick_group(self, screen_x: float, screen_y: float):
        """The group whose geometry the cursor hits (front-most face, or nearest
        edge for a group that's only lines), or ``None``. Faces sharing a plane
        go to the smallest, as in :meth:`pick_face`: a disc grouped on a wall
        group's face lies at the wall's depth to the last float (#982)."""
        if (self.scene.edit_group is not None
                and not getattr(self.scene.edit_group, "children", None)):
            return None                     # inside a plain group: its content
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is not None and direction is not None:
            import numpy as np
            best = None  # (t, group)
            idx = self._pick_index(near=Viewport._ray_near(self, screen_x, screen_y))
            loose_t = np.inf
            hits = self._hover_hits(idx, origin, direction)
            if hits is not None and len(hits.t):
                loose_t = float(np.where(hits.loose, hits.t, np.inf).min())
                if np.isfinite(np.where(hits.loose, np.inf, hits.t).min()):
                    # A loose face in FRONT hides the group: what the cursor
                    # shows is that face, and every caller asks for the group
                    # it can see (#276, #363, #378 — a loose box before a
                    # component could not be clicked). So does a loose face
                    # ON a group's face, unless the group's is the smaller
                    # (#982); at the same size the loose one is the target.
                    front = Viewport._smallest_at_front(self, hits, origin,
                                                        direction)
                    best = (float(hits.t[front].min()),
                            None if hits.loose[front].any()
                            else hits.owner(int(front[0])))
            faces_answer = best
            # A grouped photo has no topology face to enter the pick index.
            # Hit its real rectangle and return the container, preserving
            # photo semantics without an invisible helper mesh.
            for g in self._context_placements():
                images = getattr(g, "images", None) or ()
                if not images or not self.scene.entity_selectable(g):
                    continue
                matrix = getattr(g, "xform", None)
                for image in images:
                    corners = image.corners()
                    if matrix is not None:
                        corners = [matrix.map(point) for point in corners]
                    for tri in ((corners[0], corners[1], corners[2]),
                                (corners[0], corners[2], corners[3])):
                        t = _ray_triangle(origin, direction, *tri)
                        if t is not None and (best is None or t < best[0]):
                            best = (t, self._owner_of(g))
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
                if best is faces_answer:
                    return best[1]
                # A figure: a loose face in front of it or on it hides it.
                eps = self._coplanar_eps(origin, direction, best[0])
                if np.isfinite(loose_t) and loose_t <= best[0] + eps:
                    return None
                return best[1]
        # Edge fallback (cursor over empty space, or a lines-only group):
        # screen-space distance to every group hard edge, batched over the
        # cached projected arrays — the Python per-edge walk took ~300 ms per
        # mouse move against a 300k-edge imported model.
        import numpy as np
        best_d = self.pick_threshold_px
        best_g = None
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if nat is not None:
            best_d, best_g = self._pick_group_edge_unbaked(
                screen_x, screen_y, nat)
        else:
            # The index first, then its projection (see
            # _nearby_group_edges).
            idx = self._pick_index(near=("px", screen_x, screen_y))
            proj = self._gedge_screen()
        if nat is None and proj is not None:
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

    def _pick_candidates(self, oculto, lazy):
        """What the pick index takes from the placements: the ids the
        context lets you touch, the fixed placements in order, and the lazy
        ones as ``id → (position, group)`` (see ``_pick_index``)."""
        scene = self.scene
        del_contexto = self._context_placements()
        tocables = {id(g) for g in del_contexto}
        # What the current context lets you TOUCH: the whole scene at the
        # root, the children of the group you are inside otherwise. This
        # used to be `if scene.edit_group is None`, which took EVERY group
        # out of the index while you were inside one — so a group's children
        # were drawn and could not be clicked, and «todo está combinado»
        # (Marco, 2026-09-11).
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
        lazy_ids = lazy[4] if lazy is not None else ()
        fixed = [g for g in candidatos if id(g) not in lazy_ids]
        lazy_pos = {id(g): (i, g) for i, g in enumerate(candidatos)
                    if id(g) in lazy_ids}
        return tocables, fixed, lazy_pos

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
