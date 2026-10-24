# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Snapping and inference: candidate edges and points, centres, locks and the snap refresh."""
from __future__ import annotations

import math
from typing import Optional
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Face
from core.snap import SnapResult, _AXIS_VECTORS
from tools.base import ToolContext
from views.viewport._support import (_NO_SNAP_FAST, _active_cut, _SnapEdge, _group_pseudo_edge,
                                     _LOOSE_SNAP_CAP, _cache_ver, _finite_point)


class SnappingMixin:
    """Snapping and inference: candidate edges and points, centres, locks and the snap refresh."""

    #: How far from the cursor (px) a face crossing snaps, and how far
    #: either side of the crossing the search checks that each face shows.
    _CROSSING_RING_PX = 8.0
    _CROSSING_SIDE_PX = 3.0

    def _face_crossing_point(self, px: float, py: float):
        """Where the face under the cursor meets another face that crosses
        it with no edge between them — a box sunk into the floor, a beam
        through a wall: ``(world point, context)`` or ``None`` (#819,
        SketchUp's «Intersection»). A face that goes THROUGH the one in
        front is met by the cursor's own ray a little behind it, so the
        candidates come free from that ray's hits (already cast for this
        hover); a crossing counts only if, either side of it on screen,
        one face shows and then the other — the two really meet there, in
        view, and neither is merely in front of the other. ``context`` is
        "group" / "component" when one of them is inside one, for the
        «in group» tip."""
        if _active_cut(self.scene) is not None:
            return None
        f_face, f_place = self.pick_face_placement(px, py)   # memoised
        if f_face is None:
            return None
        o, d = self._pixel_to_ray(px, py)
        if o is None or d is None:
            return None
        import numpy as np
        idx = self._pick_index(near=("px", px, py))
        face_t = self._hover_face_t(idx, o, d)                # memoised
        if face_t is None or not np.isfinite(face_t).any():
            return None
        t_f = float(face_t.min())
        r = self._CROSSING_RING_PX
        o2, d2 = self._pixel_to_ray(px + r, py)
        if o2 is None or d2 is None:
            return None
        reach = ((o2 + d2 * t_f) - (o + d * t_f)).length() * 50.0
        # ``>=``: with the cursor right on the crossing both faces are hit
        # at the same depth (the face itself is skipped below).
        cand = np.where((face_t >= t_f) & (face_t <= t_f + reach))[0]
        if len(cand) == 0:
            return None
        cand = cand[np.argsort(face_t[cand], kind="stable")][:7]
        from core.snap import face_plane_world
        p_f, n_f = face_plane_world(f_face, getattr(f_place, "xform", None))
        pidx = getattr(idx, "ent_place_idx", None)
        for i in cand:
            i = int(i)
            g_face, g_owner = idx.entities[i]
            g_place = g_owner
            if pidx is not None and i < len(pidx) and pidx[i] >= 0:
                g_place = idx.ent_placements[int(pidx[i])]
            if g_face is f_face and g_place is f_place:
                continue
            p_g, n_g = face_plane_world(g_face, getattr(g_place, "xform", None))
            u = QVector3D.crossProduct(n_f, n_g)
            if u.length() < 0.02:               # (near) coplanar: no crossing
                continue
            found = self._crossing_on_screen(
                px, py, o, d, (f_face, f_place, p_f, n_f),
                (g_face, g_place, p_g, n_g, u))
            if found is not None:
                return found
        return None

    def _crossing_on_screen(self, px, py, o, d, f, g):
        """The crossing of plane ``f`` with plane ``g`` nearest the cursor
        ray, if it is within reach on screen and shows face ``f`` on one
        side and face ``g`` on the other (see :meth:`_face_crossing_point`)."""
        f_face, f_place, p_f, n_f = f
        g_face, g_place, p_g, n_g, u = g
        r = self._CROSSING_RING_PX
        # The crossing line: the point of both planes nearest the origin…
        d_f = QVector3D.dotProduct(n_f, p_f)
        d_g = QVector3D.dotProduct(n_g, p_g)
        uu = QVector3D.dotProduct(u, u)
        l0 = (QVector3D.crossProduct(n_g, u) * d_f
              + QVector3D.crossProduct(u, n_f) * d_g) / uu
        # …then its point nearest the cursor ray.
        un = u / math.sqrt(uu)
        w0 = l0 - o
        b = QVector3D.dotProduct(un, d)
        den = 1.0 - b * b
        if den < 1e-9:                          # the line runs along the ray
            return None
        s = (b * QVector3D.dotProduct(w0, d) - QVector3D.dotProduct(w0, un)) / den
        x = l0 + un * s
        pix = self._world_to_pixel(x)
        if pix is None or math.hypot(pix[0] - px, pix[1] - py) > max(
                self.edge_snap_threshold_px, r):
            return None
        # Either side of the crossing on screen: one face, then the other.
        q = self._world_to_pixel(x + un * max(1e-3, (x - o).length() * 1e-2))
        if q is None:
            return None
        sx, sy = q[0] - pix[0], q[1] - pix[1]
        ln = math.hypot(sx, sy)
        if ln < 1e-9:
            return None
        nx, ny = -sy / ln * self._CROSSING_SIDE_PX, sx / ln * self._CROSSING_SIDE_PX
        sides = [self._front_face_at(pix[0] + nx, pix[1] + ny),
                 self._front_face_at(pix[0] - nx, pix[1] - ny)]
        ids = {(id(h[0]), id(h[1])) for h in sides if h is not None}
        if ids != {(id(f_face), id(f_place)), (id(g_face), id(g_place))}:
            return None
        context = None
        for place in (f_place, g_place):
            if place is None:
                continue
            owner = self._owner_of(place)
            is_comp = getattr(owner, "is_instance", None)
            context = ("component" if is_comp is not None and is_comp()
                       else "group")
            break
        return x, context

    def _gedge_screen(self):
        """Screen-projected endpoints of every group hard edge —
        ``(ax, ay, bx, by, ok)`` arrays, cached until the scene or the
        camera moves. Shared by pick_group's edge fallback and the snap
        prefilter (during a drawing hover the camera is still, so the two
        big projections run once, not per mouse move)."""
        idx = self._pick_index(near="skip")
        if idx.gedge_a is None or not len(idx.gedge_a):
            return None
        M = self._np_mvp()
        # The rest-of-model mode changes WHICH edges the index holds
        # (hidden surroundings leave it), so it keys the projection too.
        key = (id(idx.gedge_a), id(self.scene.mesh), M.tobytes(),
               self.width(), self.height(),
               getattr(self, "_edit_rest_mode", None))
        cached = getattr(self, "_gedge_px_cache", None)
        # The array itself, not only its id(): a rebuilt index's edges can
        # be given the address of the ones they replaced.
        if (cached is not None and cached[0] == key and len(cached) > 2
                and cached[2] is idx.gedge_a):
            return cached[1]
        ax, ay, oka = self._project_px(idx.gedge_a)
        bx, by, okb = self._project_px(idx.gedge_b)
        data = (ax, ay, bx, by, oka & okb)
        self._gedge_px_cache = (key, data, idx.gedge_a)
        return data

    #: The group-edge distances' contract with their two readers (the
    #: hovered-edge pick, within ``pick_threshold_px``; the snap prefilter,
    #: the ``GEDGE_ENOUGH`` nearest within 48 px): exact within
    #: ``GEDGE_NEAR_PX``, and within ``GEDGE_REACH_PX`` too unless at least
    #: ``GEDGE_ENOUGH`` edges already lie inside the near radius — then the
    #: nearest ones are all there. Past that a big model says ``inf``.
    GEDGE_NEAR_PX = 8.0
    GEDGE_REACH_PX = 64.0
    GEDGE_ENOUGH = 48
    #: From this many group edges up, the distances come through a screen
    #: grid (core.edge_grid) instead of one pass over all of them.
    GEDGE_GRID_MIN = 20000

    def _gedge_dist(self, px: float, py: float):
        """Screen distance from the cursor to every group hard edge, shared
        by the hovered-edge pick and the snap prefilter (both used to
        compute it); see ``GEDGE_NEAR_PX`` for how far it is exact.

        On a 330 k-face city the full pass was ~30 ms of every mouse move
        for the few dozen edges that matter. A camera that stays put for a
        second hover gets the edges binned into a screen grid (once — the
        projection's own lifetime), and each move then measures the cells
        around the cursor: 0.2 ms zoomed onto a building, ~2 ms with the
        whole city in view (11 edges per pixel: the near radius already
        holds hundreds). The grid lives as long as the projection: the
        first hover of a projection keeps the full pass, so one that
        changes every event (the camera moving) never pays for a grid it
        would use once. City-L, the interaction benchmark: hover with Line
        103 -> 60 ms, a Move drag 101 -> 49 ms per event (median)."""
        import numpy as np
        from core.edge_grid import EdgeGrid, segment_distances
        proj = self._gedge_screen()
        # Whole pixels: the hovered-edge pick gets the float position and
        # the snap scene the rounded one — the same pass must serve both.
        key = (id(proj), int(round(px)), int(round(py)))
        cached = getattr(self, "_gedge_dist_cache", None)
        if (cached is not None and cached[0] == key and len(cached) > 2
                and cached[2] is proj):
            return cached[1]
        ax, ay, bx, by, ok = proj
        d = None
        if (not _NO_SNAP_FAST and len(ax) >= SnappingMixin.GEDGE_GRID_MIN
                and getattr(self, "pick_threshold_px", 0.0)
                <= SnappingMixin.GEDGE_REACH_PX):
            # (projection, grid or None): the grid waits for the second hover.
            slot = getattr(self, "_gedge_grid_cache", None)
            if slot is None or slot[0] is not proj:
                self._gedge_grid_cache = (proj, None)
            else:
                grid = slot[1]
                if grid is None:
                    grid = EdgeGrid(ax, ay, bx, by, ok, self.width(),
                                    self.height(), SnappingMixin.GEDGE_REACH_PX)
                    self._gedge_grid_cache = (proj, grid)
                near_px = max(SnappingMixin.GEDGE_NEAR_PX,
                              getattr(self, "pick_threshold_px", 0.0))
                for reach in (near_px, SnappingMixin.GEDGE_REACH_PX):
                    ids = grid.near(px, py, reach)
                    if ids is None:
                        break
                    sub = segment_distances(ax, ay, bx, by, ok, px, py, ids)
                    if (reach >= SnappingMixin.GEDGE_REACH_PX
                            or int((sub < reach).sum()) >= SnappingMixin.GEDGE_ENOUGH):
                        d = np.full(len(ax), np.inf)
                        d[ids] = sub
                        break
        if d is None:
            d = segment_distances(ax, ay, bx, by, ok, px, py)
        self._gedge_dist_cache = (key, d, proj)
        return d

    def _ledge_screen(self):
        """Screen-projected endpoints of every LOOSE edge — the
        ``_gedge_screen`` twin for the snap prefilter after an explode
        leaves a big loose mesh. Cached until the scene/camera moves."""
        idx = self._pick_index(near="skip")
        if idx.edge_a is None or not len(idx.edge_a):
            return None
        M = self._np_mvp()
        key = (self.scene.version, id(self.scene.mesh), M.tobytes(),
               self.width(), self.height())
        cached = getattr(self, "_ledge_px_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        ax, ay, oka = self._project_px(idx.edge_a)
        bx, by, okb = self._project_px(idx.edge_b)
        data = (ax, ay, bx, by, oka & okb)
        self._ledge_px_cache = (key, data)
        return data

    def _nearby_loose_edges(self, px: float, py: float,
                            radius_px: float = 64.0, cap: int = 400) -> list:
        """The loose edges whose screen segment passes near the cursor —
        real Edge objects, nearest first, at most ``cap``."""
        proj = self._ledge_screen()
        if proj is None:
            return []
        import numpy as np
        ax, ay, bx, by, ok = proj
        if not ok.any():
            return []
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        safe = np.where(l2 > 1e-12, l2, 1.0)
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe, 0.0, 1.0)
        d = np.hypot(ax + t * dx - px, ay + t * dy - py)
        d = np.where(ok, d, np.inf)
        cand = np.where(d < radius_px)[0]
        if len(cand) > cap:
            cand = cand[np.argsort(d[cand])[:cap]]
        idx = self._pick_index(near="skip")
        edges = idx.edges
        n = len(edges)
        return [edges[int(i)] for i in cand if int(i) < n]

    def _nearby_group_edges(self, px: float, py: float,
                            radius_px: float = 48.0, cap: int = 48) -> list:
        """Group hard edges whose screen-space segment passes within
        ``radius_px`` of the cursor, as :class:`_SnapEdge` pseudo-edges —
        at most ``cap``, nearest first. Vectorised prefilter:
        ``compute_snap`` walks its edge list in Python several times per
        hover, so feeding it ALL 160k edges of an import would freeze every
        mouse move; the ~dozens near the cursor cover the point/edge snaps
        the user can actually see."""
        # The placements near THIS pixel enter the index first (lazy mode,
        # #158): the projection below reads the index as it stands, and the
        # edges are read from that same one. Asking again bakes more and
        # reorders the lazy part: the measured positions then pointed at
        # other edges, or past the end (the SPR, hovering with Line).
        idx = self._pick_index(near=("snap", px, py))
        proj = self._gedge_screen()
        if proj is None:
            return []
        import numpy as np
        if not proj[4].any():
            return []
        dist = getattr(self, "_gedge_dist", None)          # stub VPs in tests
        if radius_px > SnappingMixin.GEDGE_REACH_PX or cap > SnappingMixin.GEDGE_ENOUGH:
            # Past what _gedge_dist promises (GEDGE_NEAR_PX): every edge.
            from core.edge_grid import segment_distances
            d = segment_distances(*proj, px, py)
        else:
            d = (dist(px, py) if dist is not None
                 else SnappingMixin._gedge_dist(self, px, py))
        cand = np.where(d < radius_px)[0]
        if len(cand) > cap:
            cand = cand[np.argsort(d[cand])[:cap]]
        return [_group_pseudo_edge(idx, int(i)) for i in cand]

    def pick_edge_any(self, screen_x: float, screen_y: float):
        """The edge under the cursor, loose OR a group's (as a world
        pseudo-edge with ``in_group``), nearest first — what the linear
        inferences hover: parallel / perpendicular to a component's edge,
        the reference lock, Push/Pull level with it (groups are read
        from outside without opening them)."""
        loose = self.pick_edge(screen_x, screen_y)
        # The index this pixel asks for, then its projection: the edge is
        # read from the index it was measured on (see _nearby_group_edges).
        idx = self._pick_index(near=("px", screen_x, screen_y))
        proj = self._gedge_screen()
        if proj is None:
            return loose
        import numpy as np
        ax, ay, bx, by, ok = proj
        if not ok.any():
            return loose
        d = self._gedge_dist(screen_x, screen_y)
        i = int(np.argmin(d))
        if d[i] >= self.pick_threshold_px:
            return loose
        if loose is not None:
            pa = self._world_to_pixel(loose.a)
            pb = self._world_to_pixel(loose.b)
            if pa is not None and pb is not None:
                from core.snap import _closest_on_segment_2d
                dl, _t = _closest_on_segment_2d((screen_x, screen_y), pa, pb)
                if dl <= d[i]:
                    return loose
        return _group_pseudo_edge(idx, i)

    #: How close (px) the cursor must come to a component's origin or an
    #: arc's midpoint for it to enter the snap scene at all.
    POINT_INFERENCE_PX = 40.0

    def _component_origin_points(self, px: float, py: float) -> list:
        """The "Component Origin Point": each placed group's own
        origin (its insertion point), as a degenerate pseudo-edge when it
        lies near the cursor. One projection per placement."""
        import numpy as np
        cache = getattr(self, "_corigin_cache", None)
        key = (self.scene.version, id(self.scene.edit_group))
        if cache is None or cache[0] != key:
            groups, pts = [], []
            for g in self._placements():
                xf = getattr(g, "xform", None)
                if xf is None or getattr(g, "billboard", False):
                    continue
                o = xf.map(QVector3D(0.0, 0.0, 0.0))
                groups.append(g)
                pts.append((o.x(), o.y(), o.z()))
            cache = (key, groups, np.array(pts, dtype=np.float64).reshape(-1, 3))
            self._corigin_cache = cache
        _k, groups, pts = cache
        if not len(pts):
            return []
        sx, sy, ok = self._project_px(pts)
        d = np.where(ok, np.hypot(sx - px, sy - py), np.inf)
        moving = getattr(self.active_tool, "_group", None)
        out: list = []
        for i in np.flatnonzero(d <= self.POINT_INFERENCE_PX):
            if groups[i] is moving:
                continue
            o = QVector3D(*pts[i])
            out.append(_SnapEdge(o, QVector3D(o), component_origin=True))
        return out

    def _arc_midpoints(self, px: float, py: float) -> list:
        """The "Arc Midpoint": the middle of each loose arc's sweep
        (the point on the arc bisecting its two ends — not any facet's
        midpoint). Closed curves (circles) have none. Computed once per
        scene version, offered when near the cursor."""
        cache = getattr(self, "_arc_mid_cache", None)
        if cache is None or cache[0] != self.scene.version:
            # Per MESH, keyed by its mutation serial: a scene version bump
            # (every frame of a drag) used to walk every prototype's curves
            # again — 31 ms a frame while moving a face (2026-09-14). Now a
            # mesh's midpoints are recomputed only when that mesh changed;
            # the version pass only maps them through the placements.
            by_mesh = getattr(self, "_arc_mid_by_mesh", None)
            if by_mesh is None:
                by_mesh = self._arc_mid_by_mesh = {}

            def local_mids(mesh):
                serial = getattr(mesh, "_mut_serial", None)
                hit = by_mesh.get(id(mesh))
                if hit is None or hit[0] != serial:
                    hit = by_mesh[id(mesh)] = (serial, self._mesh_arc_midpoints(mesh))
                return hit[1]
            mids = list(local_mids(self.scene.mesh))
            # …and the arcs inside every placed group / component, through
            # each placement's matrix.
            for g in self._placements():
                mesh = getattr(g, "mesh", None)
                if mesh is None or getattr(g, "billboard", False):
                    continue
                lm = local_mids(mesh)
                if not lm:
                    continue
                xf = getattr(g, "xform", None)
                mids += [xf.map(m) if xf is not None else QVector3D(m) for m in lm]
            if len(by_mesh) > 2048:
                by_mesh.clear()
            cache = (self.scene.version, mids)
            self._arc_mid_cache = cache
        out: list = []
        for m in cache[1]:
            pc = self._world_to_pixel(m)
            if pc is None or math.hypot(pc[0] - px, pc[1] - py) > self.POINT_INFERENCE_PX:
                continue
            out.append(_SnapEdge(QVector3D(m), QVector3D(m), arc_midpoint=True))
        return out

    @staticmethod
    def _mesh_arc_midpoints(mesh) -> list:
        """The sweep midpoint of every open curve chain of ``mesh`` (in the
        mesh's own space)."""
        from core.snap import fit_circle
        from core.lazy_mesh import plan_of
        plan = plan_of(mesh)
        by_curve: dict = {}
        if plan is not None:
            # A lazy mesh: its curves from the planned edges, the same
            # chains in the same order, nothing built.
            ab = plan.edges.tolist()
            for i, cid in enumerate(plan.curve):
                if cid is not None:
                    by_curve.setdefault(cid, []).append(ab[i])
        else:
            for e in mesh.edges:
                cid = getattr(e, "curve", None)
                if cid is not None:
                    by_curve.setdefault(cid, []).append(e)
        mids = []
        for edges in by_curve.values():
            degree: dict = {}
            pos: dict = {}
            for e in edges:
                if plan is not None:
                    for v in e:
                        degree[v] = degree.get(v, 0) + 1
                        if v not in pos:
                            pos[v] = QVector3D(*plan.pos[v])
                    continue
                for v in (e.v0, e.v1):
                    degree[id(v)] = degree.get(id(v), 0) + 1
                    pos[id(v)] = v.position
            ends = [pos[k] for k, n in degree.items() if n == 1]
            if len(ends) != 2 or len(pos) < 3:
                continue                     # a circle, or not a chain
            fit = fit_circle(list(pos.values()))
            if fit is None:
                continue
            c, r = fit[0], fit[1]
            m = QVector3D(0.0, 0.0, 0.0)
            for pt in pos.values():
                m += (pt - c)
            if m.length() < 1e-9:
                continue
            mids.append(c + m.normalized() * r)
        return mids

    def _billboard_snap_edges(self) -> list:
        """The one snap a face-me billboard offers: its FEET, the anchor
        point, as a degenerate pseudo-edge (a point, like a guide point) —
        enough to place a figure or measure from where it stands. It used
        to offer its base edge and vertical axis too (corners, midpoints,
        head, and two whole lines to ride), and the scale figure beside the
        origin stole the inference from the drawing around it («me está
        cogiendo el paisano», Rafael, revision 4; Marco: «siempre toma
        protagonismo»). The group a transform tool is currently dragging is
        excluded (it would snap to itself)."""
        moving = getattr(self.active_tool, "_group", None)
        out: list = []
        for g in self._placements():
            if not getattr(g, "billboard", False) or g is moving:
                continue
            if not self.scene.entity_selectable(g):
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            c = quad[0]
            feet = (c[0] + c[1]) * 0.5
            out.append(_SnapEdge(QVector3D(feet), QVector3D(feet), figure=True))
        return out

    def _snap_scene(self, px: Optional[float] = None,
                    py: Optional[float] = None):
        """The scene the snap engine sees: loose edges, construction guides as
        pseudo-edges (``Guide.a/.b`` span the long segment), and — when the
        cursor position is given — the group edges near it plus the face-me
        billboard anchors, so drawing and dimensioning over an imported
        reference model snaps to its corners and edges."""
        # Guide lines are clipped to the part in front of the camera so the
        # snap engine gets projectable endpoints (an endpoint behind the eye
        # used to kill on-line snapping in ordinary 3D views); guide POINTS
        # snap as degenerate pseudo-edges, exactly like survey points.
        lines = []
        # Guides that Move is dragging pass through the cursor: left out,
        # or the cursor locks onto its own guide (#627).
        moving = getattr(self.active_tool, "moving_guide_ids", None)
        moving = moving() if callable(moving) else ()
        for g in getattr(self.scene, "guides", None) or []:
            if id(g) in moving:
                continue
            if g.is_line:
                seg = self._guide_snap_segment(g)
                if seg is not None:
                    lines.append(_SnapEdge(*seg, guide=True))
            else:
                lines.append(_SnapEdge(QVector3D(g.point), QVector3D(g.point)))
        # Reference-image borders snap like guides: aligning a scan against
        # real geometry (or drawing to its edge) is what tracing needs.
        for im in getattr(self.scene, "image_planes", None) or []:
            if getattr(im, "locked", False) or not self.scene.entity_selectable(im):
                continue
            for a, b in im.border_edges():
                seg = self._clip_segment_front(a, b)
                if seg is not None:
                    lines.append(_SnapEdge(*seg))
        near = self._nearby_group_edges(px, py) if px is not None else []
        # What a transform tool is dragging must not attract snaps (the
        # entities in motion stay out of inference; issue #19): the
        # tool names the edges/groups in motion and they are dropped here.
        excl = getattr(self.active_tool, "snap_excluded", None)
        excl = excl() if callable(excl) else None
        if excl is not None and excl[1]:
            near = [e for e in near
                    if id(getattr(e, "group", None)) not in excl[1]]
        if px is not None:
            near += self._billboard_snap_edges()
            origins = getattr(self, "_component_origin_points", None)   # stub VPs in tests
            if origins is not None:
                near += origins(px, py)
            arcs = getattr(self, "_arc_midpoints", None)
            if arcs is not None:
                near += arcs(px, py)
        box_pts = self._selection_box_points()
        if excl is not None and excl[1]:
            # A selected group's box corners are the group itself: Scale
            # dragging it must not land its grip on its own box (#233).
            box_pts = self._selection_box_points(skip=excl[1])
        near += box_pts
        valid = getattr(self, "_valid_center_ref", None)   # stub VPs in tests
        ref = valid() if callable(valid) else None
        if ref is not None:
            # No dot, no snap: a circle too small on screen keeps quiet.
            pc = self._world_to_pixel(ref[0])
            hint = getattr(self, "_center_hint_px", None)
            if pc is not None and (hint is None or hint(ref, pc) > 0.0):
                near.append(_SnapEdge(QVector3D(ref[0]), QVector3D(ref[0]),
                                      center=True))
        sp = _active_cut(self.scene)
        if sp is not None:
            # What the cut hides must not attract snaps: drop
            # edges whose BOTH endpoints are on the hidden side.
            def _kept(e):
                return not (sp.side(e.a) > 1e-6 and sp.side(e.b) > 1e-6)
            near = [e for e in near if _kept(e)]
        # Survey points snap as degenerate pseudo-edges: the endpoint snap
        # lands EXACTLY on the surveyed coordinate (the municipal flow's whole
        # point); direction-based inferences skip zero-length edges safely.
        for gp in getattr(self.scene, "geo_points", None) or []:
            near.append(_SnapEdge(QVector3D(gp.position),
                                  QVector3D(gp.position)))
        big = (px is not None
               and len(self.scene.edges) > _LOOSE_SNAP_CAP)
        if not lines and not near and sp is None and not big and excl is None:
            return self.scene
        if big:
            loose = self._nearby_loose_edges(px, py)
        else:
            loose = list(self.scene.edges)
        loose = [e for e in loose if not getattr(e, "hidden", False)]
        if excl is not None and excl[0]:
            loose = [e for e in loose if id(e) not in excl[0]]
        if sp is not None:
            loose = [e for e in loose if _kept(e)]
        from types import SimpleNamespace
        return SimpleNamespace(edges=loose + lines + near)

    def _group_obb(self, group):
        """``(frame, lo, hi)`` of the group in its OWN axes, cached on its
        chunk. A world-aligned box on a rotated object reads as skewed and
        wraps far more air than object — and its corners, which are the
        handles you grab, end up nowhere near the thing.

        A CONTAINER's box comes from its children, and its own chunk knows
        nothing about them: cached there, the box outlived a deleted child
        (the frame stayed long after one of two fountains was gone) and
        followed the container's own matrix when entering pushed that
        matrix down into the children — the box slid to the axes while
        the fountain stayed put (Marco, 2026-09-11). So a container's box
        is cached per scene version instead: it is recomputed on any
        change, and ``placement_points`` makes that one matrix multiply
        per placement."""
        kids = getattr(group, "children", None)
        if kids:
            cache = getattr(self, "_container_obb", None)
            if cache is None:
                cache = self._container_obb = {}
            key = _cache_ver(self)
            hit = cache.get(id(group))
            if hit is not None and hit[0] == key:
                return hit[1]
            fetch = getattr(self, "_proto_points_cache", None)   # stub VPs in tests
            protos = fetch(group) if fetch is not None else None
            obb = self._compute_obb(group, protos)
            if fetch is not None:
                self._proto_points_store(group, protos)
            if len(cache) > 256:            # ids of groups long gone
                cache.clear()
            cache[id(group)] = (key, obb)
            return obb
        entry = self._group_chunk(group)
        # The box follows the group's axes (issue #44), and Change Axes can
        # turn them without touching one vertex — so the cached box is only
        # good for the frame it was measured on.
        from core.group import group_frame
        fr = group_frame(group)
        fkey = tuple(fr.data()) if fr is not None else None
        obb = entry.get("obb")
        if obb is not None and entry.get("obb_frame") == fkey:
            return obb
        obb = entry["obb"] = self._compute_obb(group)
        entry["obb_frame"] = fkey
        return obb

    def _proto_points_cache(self, group) -> dict:
        """``{id(mesh): local points}`` of the prototypes under ``group``
        that are still current. A prototype's LOCAL array only changes
        when its mesh is edited — never when a placement moves — so an
        entry is dropped when the mesh is the one open for editing (or
        under a share-back) or a mutation primitive flagged it
        (``_chunk_dirty``, O(1)). No chunk is built to find out: validating
        against fresh local chunks built one per nested child, 384 ms on
        the first box after entering the plaza."""
        from core.group import iter_placements
        store = getattr(self, "_proto_pts_store", None)
        if store is None:
            store = self._proto_pts_store = {}
        editing = self._editing_meshes()
        valid: dict = {}
        for g, _m in iter_placements(group):
            mesh = g.mesh
            if mesh is None or not mesh.vertices or id(mesh) in valid:
                continue
            hit = store.get(id(mesh))
            if hit is None:
                continue
            serial, arr = hit
            if (id(mesh) in editing
                    or getattr(mesh, "_mut_serial", None) != serial
                    or len(arr) != len(mesh.vertices)):
                del store[id(mesh)]
                continue
            valid[id(mesh)] = arr
        return valid

    def _editing_meshes(self) -> set:
        """ids of the meshes a command can be mutating right now: the open
        context's, and every level's share-back prototype."""
        scene = self.scene
        ids = {id(scene.mesh)}
        for level in getattr(scene, "_edit_stack", None) or ():
            share = level.get("share") if isinstance(level, dict) else None
            if share:
                ids.add(id(share[1]))                  # the prototype
                ids.add(id(share[0].mesh))             # the working copy
        return ids

    def _proto_points_store(self, group, protos: dict) -> None:
        store = self._proto_pts_store
        if len(store) > 512:
            store.clear()
        from core.group import iter_placements
        editing = self._editing_meshes()
        serials = {id(g.mesh): getattr(g.mesh, "_mut_serial", None)
                   for g, _m in iter_placements(group) if g.mesh is not None}
        for mid, arr in protos.items():
            if mid not in editing:
                store[mid] = (serials.get(mid), arr)

    @staticmethod
    def _compute_obb(group, protos=None):
        from core.group import (frame_axes, frame_from_points, group_frame,
                                oriented_bounds, placement_points)
        # The corners come from the POINTS — never from a merged copy of the
        # component (see ``placement_points``).
        pos = placement_points(group, protos)
        frame = group_frame(group)
        if frame is not None:
            # A group that knows its own axes is boxed on them — the
            # selection box and Scale grips follow the object's axes
            # (issue #44), turned however the object is.
            _o, x, y, z = frame_axes(frame)
            return oriented_bounds(None, (x, y, z), points=pos)
        world = oriented_bounds(None, points=pos)         # world axes
        own = oriented_bounds(None, frame_from_points(pos if len(pos) else None),
                              points=pos)

        def volume(b):
            _f, lo, hi = b
            # A flat group has zero volume; rank those by their largest face.
            side = sorted(hi[i] - lo[i] for i in range(3))
            return side[1] * side[2] * max(side[0], 1e-6)

        # Derived axes are meaningless on organic geometry — a hedge has no
        # dominant plane, and its "own" box came out 25% LARGER than the world
        # one. Keep the derived frame only when it earns its place.
        return own if volume(own) < 0.9 * volume(world) else world

    def _update_center_ref(self, x: float, y: float) -> None:
        """Acquire the centre of the circle or arc under the cursor.

        A loose curve edge gives its own curve; a face gives the curves on
        its boundary — a cylinder's lid, a rounded corner, a circular hole
        — placed through the group's matrix when the face is inside one.
        With several on one face, the one whose points come closest to the
        cursor wins. Nothing under the cursor keeps the last centre: you
        hover the rim, then travel to the centre and snap to it."""
        found = None
        edge = self._hover_edge
        if getattr(edge, "curve", None) is not None:
            found = self._center_of_edge(edge, self.scene.mesh)
        elif getattr(edge, "in_group", False) and getattr(edge, "group", None) is not None:
            found = self._center_of_group_edge(edge)
        if found is None:
            pick = getattr(self, "pick_face_placement", None) or self.pick_face_any   # stub VPs in tests
            face, group = pick(x, y)
            if face is not None:
                mesh = group.mesh if group is not None else self.scene.mesh
                found = self._center_of_face(face, group, mesh, x, y)
        if found is not None:
            self._center_ref = found
            return found
        self._valid_center_ref()
        return None

    def _center_of_group_edge(self, pseudo):
        """The rim of a circle inside a top-level group / component: the
        world pseudo-edge is matched to the group's own edge (positions in
        its space) and the curve's centre comes back through its matrix."""
        g = pseudo.group
        mesh = getattr(g, "mesh", None)
        xf = getattr(g, "xform", None)
        if mesh is None or not mesh.edges:
            return None
        inv = None
        if xf is not None:
            inv, ok = xf.inverted()
            if not ok:
                return None
        la = inv.map(pseudo.a) if inv is not None else pseudo.a
        lb = inv.map(pseudo.b) if inv is not None else pseudo.b
        # The mesh's own registry: two O(1) vertex lookups (tolerant, the
        # weld grid) and the edge between them by incidence. This used to
        # build a dict of EVERY edge of the group, keyed by rounded
        # positions, cached for one group at a time — so a cursor crossing
        # from one group to the next rebuilt it on nearly every move:
        # 9 ms of a 14 ms hover on pileta-fuente (2 500 edges per group).
        edge = None
        if not _NO_SNAP_FAST:
            va, vb = mesh.vertex_at(la), mesh.vertex_at(lb)
            if va is not None and vb is not None:
                edge = mesh.find_edge(va, vb)
        if edge is None:
            # The registry missed (a position past the weld tolerance):
            # the rounded-position table, one per mesh, built once.
            tables = getattr(self, "_group_edge_tables", None)
            if tables is None or tables[0] != self.scene.version:
                tables = self._group_edge_tables = (self.scene.version, {})
            def k(p):
                return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
            table = tables[1].get(id(mesh))
            if table is None:
                table = tables[1][id(mesh)] = {
                    frozenset((k(e.a), k(e.b))): e for e in mesh.edges}
            edge = table.get(frozenset((k(la), k(lb))))
        if edge is None or getattr(edge, "curve", None) is None:
            return None
        found = self._center_of_edge(edge, mesh)
        if found is None:
            return None
        c = xf.map(found[0]) if xf is not None else found[0]
        return (c, found[1], found[2], found[3], found[4], found[5], g)

    def _center_of_edge(self, edge, mesh):
        from core.snap import fit_circle
        pts = {}
        for e in mesh.curve_edges(edge):
            pts[id(e.v0)] = e.v0.position
            pts[id(e.v1)] = e.v1.position
        fit = fit_circle(list(pts.values())) if len(pts) >= 3 else None
        if fit is None:
            return None
        return (fit[0], fit[1], ("edge", edge.curve), self.scene.version,
                edge, mesh, None)

    def _center_of_face(self, face, group, mesh, x, y):
        from core.snap import curve_centers_of_face
        xf = getattr(group, "xform", None) if group is not None else None
        centers = curve_centers_of_face(face, xf)
        if not centers:
            return None
        if len(centers) == 1:
            c, r, key = centers[0]
        else:
            # Several arcs on one face (a rounded slab): the one whose
            # centre projects nearest the cursor.
            best = None
            for c, r, key in centers:
                pc = self._world_to_pixel(c)
                if pc is None:
                    continue
                d = math.hypot(pc[0] - x, pc[1] - y)
                if best is None or d < best[0]:
                    best = (d, c, r, key)
            if best is None:
                return None
            _d, c, r, key = best
        return (c, r, (id(face), key), self.scene.version, face, mesh, group)

    def _center_hint_px(self, ref, pc) -> float:
        """How close (px) the cursor must come for the centre's dot to show:
        a share of the circle's own size on screen, capped — so a fountain
        seen from far, a few pixels across, does not light up whenever the
        cursor wanders over it («estoy lejos y me puse cerca de la pileta y
        aparece ese círculo», Marco, 2026-09-12). Zero when the circle is
        too small on screen to mean anything."""
        rim = self._world_to_pixel(ref[0] + QVector3D(ref[1], 0.0, 0.0))
        rim2 = self._world_to_pixel(ref[0] + QVector3D(0.0, ref[1], 0.0))
        r_px = 0.0
        for q in (rim, rim2):
            if q is not None:
                r_px = max(r_px, math.hypot(q[0] - pc[0], q[1] - pc[1]))
        if r_px < self.CENTER_MIN_RADIUS_PX:
            return 0.0
        return min(self.CENTER_HINT_PX, 0.5 * r_px)

    def _valid_center_ref(self):
        """The acquired centre, re-checked against the scene: once the
        circle is gone the dot goes with it — it lingered after the circle
        was erased («elimino el círculo y el punto verde continúa allí»,
        Marco, 2026-09-11) — and once it moved, the centre follows.
        Costs nothing until the scene changes."""
        ref = getattr(self, "_center_ref", None)
        if ref is None:
            return None
        if ref[3] == self.scene.version:
            return ref
        src, mesh, group = ref[4], ref[5], ref[6]
        fresh = None
        if isinstance(src, Face):
            if src in mesh.faces:
                # the same arc of the face, wherever it is now
                from core.snap import curve_centers_of_face
                xf = getattr(group, "xform", None) if group is not None else None
                same = [c for c in curve_centers_of_face(src, xf)
                        if c[2] == ref[2][1]]
                if same:
                    fresh = (same[0][0], same[0][1], ref[2],
                             self.scene.version, src, mesh, group)
        elif src in mesh.edges:
            fresh = self._center_of_edge(src, mesh)
            xf = getattr(group, "xform", None) if group is not None else None
            if fresh is not None and xf is not None:
                fresh = (xf.map(fresh[0]), fresh[1], fresh[2], fresh[3],
                         fresh[4], fresh[5], group)
        self._center_ref = fresh
        return fresh

    def _selection_box_points(self, skip=()) -> list:
        """The corners of a selected group's bounding box, as degenerate
        pseudo-edges so the snap engine offers them as endpoints.

        Those corners are grabbable: with a group selected they are
        what you take hold of to move it somewhere exact, and the green dot
        tells you the grab landed. The box is the group's selection cue here
        too (see ``_sync_edges``), so the corners were already on screen —
        they just were not snap targets. Costs nothing: the chunk's bbox is
        already cached, so a 230k-face group contributes eight points."""
        pts: list = []
        for ent in self.scene.selection:
            if not isinstance(ent, Group) or getattr(ent, "billboard", False):
                continue
            if id(ent) in skip:
                continue
            from core.group import oriented_box_corners
            for p in oriented_box_corners(*self._group_obb(ent)):
                pts.append(_SnapEdge(p, QVector3D(p)))
        return pts

    # -- Snapping inference, delegated to self.inference -----------------
    # The reference state (the hover / acquired edges and points, the centre
    # reference, the axis and reference locks, the last snap) lives in
    # core.inference.InferenceEngine, and so do the rules that used to be the
    # two post-processors of the search (the axis-source cue, the extension
    # hooks). These properties and thin wrappers keep the surface the tools,
    # the extensions, the probe and the tests read and write, so the
    # extraction stays behaviour-neutral.
    @property
    def _acquired_point(self) -> Optional[QVector3D]:
        return self.inference._acquired_point

    @_acquired_point.setter
    def _acquired_point(self, value: Optional[QVector3D]) -> None:
        self.inference._acquired_point = value

    @property
    def _encouraged(self) -> list:
        return self.inference._encouraged

    @_encouraged.setter
    def _encouraged(self, value: list) -> None:
        self.inference._encouraged = value

    @property
    def _dwell_point(self) -> Optional[QVector3D]:
        return self.inference._dwell_point

    @_dwell_point.setter
    def _dwell_point(self, value: Optional[QVector3D]) -> None:
        self.inference._dwell_point = value

    @property
    def _dwell_timer(self) -> QTimer:
        return self.inference._dwell_timer

    @_dwell_timer.setter
    def _dwell_timer(self, value: QTimer) -> None:
        self.inference._dwell_timer = value

    @property
    def axis_lock(self) -> Optional[str]:
        return self.inference.axis_lock

    @axis_lock.setter
    def axis_lock(self, value: Optional[str]) -> None:
        self.inference.axis_lock = value

    @property
    def last_snap(self) -> Optional[SnapResult]:
        return self.inference.last_snap

    @last_snap.setter
    def last_snap(self, value) -> None:
        self.inference.last_snap = value

    @property
    def reference_edge(self):
        return self.inference.reference_edge

    @reference_edge.setter
    def reference_edge(self, value) -> None:
        self.inference.reference_edge = value

    @property
    def reference_mode(self) -> Optional[str]:
        return self.inference.reference_mode

    @reference_mode.setter
    def reference_mode(self, value: Optional[str]) -> None:
        self.inference.reference_mode = value

    @property
    def _shift_lock(self):
        return self.inference._shift_lock

    @_shift_lock.setter
    def _shift_lock(self, value) -> None:
        self.inference._shift_lock = value

    @property
    def _hover_edge(self):
        return self.inference._hover_edge

    @_hover_edge.setter
    def _hover_edge(self, value) -> None:
        self.inference._hover_edge = value

    @property
    def _hover_center(self):
        return self.inference._hover_center

    @_hover_center.setter
    def _hover_center(self, value) -> None:
        self.inference._hover_center = value

    @property
    def _center_ref(self):
        return self.inference._center_ref

    @_center_ref.setter
    def _center_ref(self, value) -> None:
        self.inference._center_ref = value

    @property
    def _acquired_edge(self):
        return self.inference._acquired_edge

    @_acquired_edge.setter
    def _acquired_edge(self, value) -> None:
        self.inference._acquired_edge = value

    @property
    def _acquired_face_normal(self):
        return self.inference._acquired_face_normal

    @_acquired_face_normal.setter
    def _acquired_face_normal(self, value) -> None:
        self.inference._acquired_face_normal = value

    def _dwell_on(self, point: Optional[QVector3D]) -> None:
        self.inference._dwell_on(point)

    def _encourage_dwelt(self) -> None:
        self.inference._encourage_dwelt()

    def encourage_point(self, point: QVector3D) -> None:
        self.inference.encourage_point(point)

    # The two post-processors of the search (the axis-source cue for the
    # tools that read the model axes as a source, the extension hooks) moved
    # behind ``self.inference.snap()`` too. The names stay on the viewport
    # because the extension tests and the probe call them from here.
    def _axis_source_cue(self, snap, px_x: float, px_y: float):
        return self.inference._axis_source_cue(snap, px_x, px_y)

    def _extension_snap(self, snap, px_x: float, px_y: float):
        return self.inference._extension_snap(snap, px_x, px_y)

    def _release_linear_mode(self) -> None:
        """Back to «all inferences» once the operation is over.

        The toggle lasts ONE operation (the classic behaviour), and Marco checked it
        against the real thing (2026-09-17): «desactivo con alt, termino de
        dibujar la línea, aprieto la flechita y aprieto otra vez la línea y
        está activo la inferencia». Ours was sticky — switched off it stayed
        off for the rest of the session, which is a trap: you turn it off
        for one line and then wonder for an hour why nothing snaps. It is
        also what made issue #26 bite so hard, since an accidental Alt+Tab
        left it off for good.

        Called where an operation can END: a click that commits, a release,
        Esc, and any change of tool."""
        if self.linear_inference_mode == "all":
            return
        tool = self.active_tool
        if tool is not None and self._tool_busy(tool):
            return
        self.linear_inference_mode = "all"
        self._refresh_snap()
        self.update()

    def _release_axis_lock_after_operation(self, committed: bool = False) -> None:
        """Drop the arrow-key axis lock when the operation that used it ends.

        The classic rule, reported by @pacaeiro (issue #30): «if you're
        drawing a line and press Arrow to lock X and finish drawing the
        line, the X lock is released automatically. In ingeTrazo the Axis
        lock keeps active». Ours only came off in the Esc cascade, so the
        lock — and its label on screen — outlived the line it was for and
        silently constrained whatever you drew next.

        Same shape as the Alt toggle two issues ago (#26): a mode meant to
        last one operation that lasted the session. The Down-arrow
        reference is deliberately NOT released here — it is bound to an
        edge the user went and picked, which is a more deliberate act than
        tapping an arrow, and it already has Esc.

        Called where an operation can END: a click that commits, a stroke
        released, a typed value applied. A no-op mid-operation, so the
        second click of a line keeps its lock.
        """
        if self.axis_lock is None:
            return
        tool = self.active_tool
        if not committed and tool is not None and self._tool_busy(tool):
            return
        self.axis_lock = None
        self._refresh_snap()
        self.update()

    def _cycle_linear_inference_mode(self) -> None:
        """Alt: cycle linear inferences all → off → parallel/perp → all.

        The classic toggle, states and all — the usual status bar reads «Alt =
        Activar/desactivar "Inferencias lineales"» while a line is being
        drawn. Offered only DURING an operation there, and here too since
        issue #26. Point snaps (endpoint, midpoint, …) stay on; explicit
        locks (arrow keys, Down reference) keep working in every mode."""
        order = {"all": "off", "off": "parallel_perp", "parallel_perp": "all"}
        self.linear_inference_mode = order[self.linear_inference_mode]
        label = {
            "all": "Linear inferences: all on",
            "off": "Linear inferences: off",
            "parallel_perp": "Linear inferences: parallel / perpendicular only",
        }[self.linear_inference_mode]
        self.measurementChanged.emit(label)
        self._refresh_snap()

    def release_constraints(self) -> bool:
        """Drop the sticky drawing constraints — the arrow-key axis lock and
        the Down-arrow parallel/perpendicular reference. First stop of the
        Esc cascade: returns True if there was one to release (that Esc press
        is consumed; the next one cancels the tool action as before)."""
        if self.axis_lock is None and self.reference_mode is None:
            return False
        self.axis_lock = None
        self.reference_edge = None
        self.reference_mode = None
        self._refresh_snap()
        return True

    def _cycle_reference_mode(self) -> None:
        """Down arrow: cycle None → parallel → perpendicular → None.

        Captures whichever edge is currently under the cursor on entry to
        parallel mode. If no edge is under the cursor when starting, do
        nothing — there is nothing to be parallel/perpendicular to.
        """
        if self.reference_mode is None:
            if self._hover_edge is None:
                return  # nothing to capture
            self.reference_edge = self._hover_edge
            self.reference_mode = "parallel"
        elif self.reference_mode == "parallel":
            self.reference_mode = "perpendicular"
        else:
            self.reference_edge = None
            self.reference_mode = None

    def _refresh_snap(self) -> None:
        """Re-run snap with the last known cursor position. Used when modifier
        state changes (axis lock, reference mode, Shift) without mouse motion."""
        self._sync_axes()
        self.update()
        if (
            self._last_mouse_pos is None
            or self.active_tool is None
            or not self.active_tool.uses_snap
        ):
            return
        from PySide6.QtGui import QGuiApplication

        modifiers = QGuiApplication.keyboardModifiers()
        p = self._last_mouse_pos.toPoint()
        snap = self._snap_at(p.x(), p.y(), modifiers)
        if snap is None:
            return                              # the ray casts no world point
        # Same bookkeeping as a hover with movement: the tool reads the KIND
        # of the snap it is being handed (``_note_snap``), and a modifier
        # changing with the hand still is exactly when a planar shape has to
        # know whether the cursor is on a FACE or on a point of the model.
        self._note_snap(snap)
        ctx = ToolContext(
            viewport=self,
            world=snap.point,
            screen=self._last_mouse_pos,
            modifiers=modifiers,
            snap=snap,
        )
        self.active_tool.on_hover(ctx)
        self.measurementChanged.emit(self._measurement_text())

    # Inferences whose direction can be captured by a Shift lock.
    _SHIFT_LOCKABLE = frozenset({
        "axis", "axis_inference", "reference", "through_point", "perp_face",
        "extension",
    })

    def _capture_shift_lock(self) -> None:
        """On Shift press, mark the plane the shape is drawing on and freeze
        the active inference's direction so it holds even as the cursor
        wanders off it (inference lock). Both at once, one does not take
        the other's place: the mark only says WHICH plane, and the pointer
        goes on marking midpoints, endpoints and alignments (Marco: «100%
        aditivo»). Each side keeps its own guard."""
        self._shift_lock = None
        self._mark_plane_for_shift()
        snap = self.last_snap
        tool = self.active_tool
        owns = getattr(tool, "owns_shift_lock", None)
        if owns is not None and owns():
            return  # the tool reads the cursor's motion itself
        start = getattr(tool, "start_point", None) if tool is not None else None
        if snap is None or start is None or snap.kind not in self._SHIFT_LOCKABLE:
            return

        # Lock to the exact inferred axis, preserving its direction.
        if snap.axis in _AXIS_VECTORS:
            d = QVector3D(_AXIS_VECTORS[snap.axis])
            if QVector3D.dotProduct(snap.point - start, d) < 0.0:
                d = -d
        else:
            d = snap.point - start
        if d.length() > 1e-6:
            self._shift_lock = (d.normalized(), snap.color)

    def _mark_plane_for_shift(self) -> None:
        """Shift marks the plane the shape would draw on — the tool's call
        (``PlaneLock.mark_plane``). Unlike the inference lock above this is
        HELD, not locked: the release hands the plane back
        (``_release_shift_plane_mark``)."""
        self._shift_plane_mark = None
        tool = self.active_tool
        if tool is None:
            return
        from tools.base import PlaneLock
        if not isinstance(tool, PlaneLock):
            return
        if tool.mark_plane(self):
            self._shift_plane_mark = tool

    def _release_shift_plane_mark(self) -> None:
        """Shift let go (or the window lost focus): hand the plane back.
        Only the mark that Shift itself put there goes — a plane locked with
        an arrow or with Down in the meantime outlives the key."""
        tool = getattr(self, "_shift_plane_mark", None)
        self._shift_plane_mark = None
        if tool is None:
            return
        ref = getattr(tool, "plane_ref", None)
        if ref is not None and ref[1] == "plane":
            tool.plane_ref = None

    # ---- Helpers ------------------------------------------------------------
    def _snap_at(
        self, px_x: float, px_y: float, modifiers
    ) -> Optional[SnapResult]:
        """The snap engine's answer for the cursor at ``(px_x, px_y)``.

        THE one code path: both ``_build_ctx`` (mouse motion and clicks) and
        ``_refresh_snap`` (a modifier changing with the hand still) go through
        here, so the :func:`compute_snap` argument list lives in exactly one
        place. Returns ``None`` when the pixel casts no world point (the ray
        misses the plane / the point is behind the camera). A tool that does
        not snap (Select, Push/Pull) gets a ``"none"`` result instead - no
        snap engine, no occlusion raycasts, no marker.

        A point that is not finite counts as no point: a NaN that reached a
        tool showed «nan m» in the length box and failed the Line's commit
        with «AddEdgeCommand: cannot convert float NaN to integer» (#466,
        #754). Whatever inference produced it, the cursor just gives
        nothing for that pixel."""
        snap = self.inference.snap(px_x, px_y, modifiers)
        if snap is not None and not _finite_point(snap.point):
            return None
        return snap

    def _build_ctx(self, ev) -> Optional[ToolContext]:
        self._sync_axes()
        p = ev.position().toPoint()
        snap = self._snap_at(p.x(), p.y(), ev.modifiers())
        if snap is None:
            return None
        return ToolContext(
            viewport=self,
            world=snap.point,
            screen=ev.position(),
            modifiers=ev.modifiers(),
            snap=snap,
        )

    def _note_snap(self, snap: SnapResult) -> None:
        """Record the cursor's snap and hand its KIND to the active tool
        (``Tool.snap_kind``).

        The kind is known only once the snap has been computed — the plane
        comes first, the point and its snap second — so a planar tool
        asking the viewport which face the cursor is over cannot be told
        whether the cursor is on that face as a FACE or snapped to a point
        that merely lies on it. The tool hears it here, on every hover and
        click, before it is called: that is where ``PlaneLock.
        snapped_plane`` decides whether the shape re-plans onto a point
        (#37) or stays on the face under the cursor (#545)."""
        self.last_snap = snap
        tool = self.active_tool
        if tool is not None:
            tool.snap_kind = getattr(snap, "kind", None)
