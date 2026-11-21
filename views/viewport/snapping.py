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
from views.viewport._support import (_NO_SNAP_FAST, _active_cut, _SnapEdge,
                                     _copy_snap_edge, _snap_context_of,
                                     _group_pseudo_edge, _LOOSE_SNAP_CAP,
                                     _LOOSE_NATIVE_MIN, _proto_wrapper,
                                     _paint_of, _content_ver,
                                     _plan_curved_edges,
                                     _lazy_edge_may_be_curve,
                                     _snap_dropped_loose, _edges_snappable,
                                     _nearest_within,
                                     _EDGES_SHARED, shown_guides,
                                     _finite_point)

#: The Viewport class, set by views/viewport/__init__.py once it exists: a
#: method here that names ``Viewport.X`` reads (and writes) the class itself.
Viewport = None


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
        the «Intersection» snap). A face that goes THROUGH the one in
        front is met by the cursor's own ray a little behind it, so the
        candidates come free from that ray's hits (already cast for this
        hover); a crossing counts only if, either side of it on screen,
        one face shows and then the other — the two really meet there, in
        view, and neither is merely in front of the other. ``context`` is
        "group" / "component" when one of them is inside one, for the
        «in group» tip."""
        if _active_cut(self.scene) is not None:
            return None
        f_face, f_place = self.pick_face_inference(px, py)   # memoised
        if f_face is None:
            return None
        o, d = self._pixel_to_ray(px, py)
        if o is None or d is None:
            return None
        import numpy as np
        idx = self._pick_index(near=Viewport._ray_near(self, px, py))
        hits = self._infer_hits(idx, o, d)                    # memoised
        if hits is None or not np.isfinite(hits.t).any():
            return None
        face_t = hits.t
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
        f = (f_face, f_place, p_f, n_f)
        pairs = []
        for i in cand:
            i = int(i)
            g_face = hits.ent(i)[0]
            g_place = hits.place(i)
            if g_face is f_face and g_place is f_place:
                continue
            p_g, n_g = face_plane_world(g_face, getattr(g_place, "xform", None))
            u = QVector3D.crossProduct(n_f, n_g)
            if u.length() < 0.02:               # (near) coplanar: no crossing
                continue
            g = (g_face, g_place, p_g, n_g, u)
            sides = self._crossing_sides(px, py, o, d, f, g)
            if sides is not None:
                pairs.append((g, sides))
        # The probes either side of every crossing bake what they cross
        # first, together: one at a time, each that met a new lazy
        # placement rebuilt the index for the next (up to five rebuilds a
        # pointer move with Rectangle over the plant of #158).
        mat = getattr(self, "_pick_materialize", None)
        if (mat is not None and hasattr(self, "_pick_lazy_table")
                and Viewport._ray_near(self, px, py) != "skip"):
            for _g, (_x, probes) in pairs:
                for q in probes:
                    mat(("px", q[0], q[1]))
        for g, sides in pairs:
            found = self._crossing_on_screen(f, g, sides)
            if found is not None:
                return found
        return None

    def _crossing_sides(self, px, py, o, d, f, g):
        """The crossing of plane ``f`` with plane ``g`` nearest the cursor
        ray, if it is within reach on screen: ``(world point, (pixel one
        side, pixel the other side))``, or ``None``."""
        _f_face, _f_place, p_f, n_f = f
        _g_face, _g_place, p_g, n_g, u = g
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
        return x, ((pix[0] + nx, pix[1] + ny), (pix[0] - nx, pix[1] - ny))

    def _crossing_on_screen(self, f, g, found):
        """The crossing ``found`` by :meth:`_crossing_sides` if it shows
        face ``f`` on one side and face ``g`` on the other (see
        :meth:`_face_crossing_point`): ``(world point, context)`` or
        ``None``."""
        f_face, f_place = f[0], f[1]
        g_face, g_place = g[0], g[1]
        x, probes = found
        want = {(id(f_face), id(f_place)), (id(g_face), id(g_place))}
        ids = set()
        for q in probes:
            # Each side must show one of the two, the sides not the same
            # one: a side that does not ends the search there (each probe
            # is a ray through the model, ~2 ms over the plant of #158,
            # and dense spots try five crossings a move that fail).
            h = self._front_face_at(q[0], q[1], "infer")
            if h is None or (id(h[0]), id(h[1])) not in want:
                return None
            ids.add((id(h[0]), id(h[1])))
        if ids != want:
            return None
        context = None
        found_ctx = []
        for place in (f_place, g_place):
            if place is None:
                continue        # the open context's own loose geometry
            word = _snap_context_of(self, place)
            if word is not None:
                found_ctx.append(word)
        if "outside" in found_ctx:
            context = "outside"
        elif found_ctx:
            context = found_ctx[0]
        return x, context

    def _face_outline_world(self, px: float, py: float):
        """The face under the cursor as ``(outer loop, holes, context)`` in
        world space (``context``: "group" / "component" when it is inside
        one), or ``None``. What a line piercing the face is tested against.
        The rest of the model around an open group counts: a line drawn
        inside it can pierce a face left outside."""
        face, place = self.pick_face_inference(px, py)    # memoised
        if face is None:
            return None
        xf = getattr(place, "xform", None)

        def w(p):
            return xf.map(QVector3D(p)) if xf is not None else QVector3D(p)
        outer = [w(p) for p in face.vertices]
        holes = [[w(p) for p in h] for h in face.holes]
        context = None
        if place is not None:
            owner = self._owner_of(place)
            is_comp = getattr(owner, "is_instance", None)
            if is_comp is not None:
                # A reference wrapper (the outer loose mesh) has no
                # ``is_instance``: it is not "in" a group, it IS the root.
                context = ("component" if is_comp() else "group")
        return outer, holes, context

    def _face_center_under(self, px: float, py: float):
        """The «Face center» inference: ``(point, context)`` for the centre
        of area of the face under the cursor, or ``None`` — no face, the
        centre falls outside it (an L, a ring), it is too far from the
        cursor to matter, or the face is in motion (a face being bent, a
        group being moved: the point would chase the cursor)."""
        face, place = self.pick_face_placement(px, py)
        if face is None:
            return None
        tool = self.active_tool
        if place is None:
            moving = getattr(tool, "moving_face_ids", None)
            if callable(moving) and id(face) in moving():
                return None
            context = None
        else:
            owner = self._owner_of(place)
            excl = getattr(tool, "snap_excluded", None)
            excl = excl() if callable(excl) else None
            if excl is not None and (id(owner) in excl[1] or id(place) in excl[1]):
                return None
            is_comp = getattr(owner, "is_instance", None)
            context = "component" if (callable(is_comp) and is_comp()) else "group"
        from core.snap import face_center_of_face
        c = face_center_of_face(face, getattr(place, "xform", None))
        if c is None:
            return None
        pc = self._world_to_pixel(c)
        if pc is None or math.hypot(pc[0] - px, pc[1] - py) > self.POINT_INFERENCE_PX:
            return None
        return c, context

    #: More selected faces than this and their centres are neither drawn
    #: nor offered: a «select all» would bury the model in dots.
    FACE_CENTER_SELECTION_MAX = 500

    def _selected_face_centers(self) -> list:
        """The «Face center» of every selected face, ``[QVector3D]`` in
        world space: drawn as dots and offered to the snap engine wherever
        the cursor is, so a ring's centre — in its hole, where no face is
        under the cursor — can be reached. Only faces picked one by one: a
        selected group offers none (a whole object would fill with dots).
        An open group's faces are loose and already in world space. A face
        a tool is bending is left out (its centre would chase the cursor).
        Cached per scene version and selection. None at all while the
        «Face center» switch is off (Tools ▸ Inferences, #1410)."""
        from core.snap import snap_toggle_enabled
        if not snap_toggle_enabled("face_center"):
            return []
        faces = [e for e in self.scene.selection if isinstance(e, Face)]
        if not faces or len(faces) > self.FACE_CENTER_SELECTION_MAX:
            return []
        moving = getattr(self.active_tool, "moving_face_ids", None)
        moving = moving() if callable(moving) else ()
        key = (self.scene.version, tuple(id(f) for f in faces),
               frozenset(moving))
        cached = getattr(self, "_sel_face_centers", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        from core.snap import face_center_of_face
        pts = []
        for f in faces:
            if id(f) in moving:
                continue
            c = face_center_of_face(f)
            if c is not None:
                pts.append(c)
        self._sel_face_centers = (key, pts)
        return pts

    def _face_centers_near(self, px: float, py: float) -> list:
        """The «Face center» points for the snap engine, ``[(point,
        context)]``: the face under the cursor, and the selected faces whose
        centre is near it."""
        out = []
        under = self._face_center_under(px, py)
        if under is not None:
            out.append(under)
        for c in self._selected_face_centers():
            pc = self._world_to_pixel(c)
            if pc is not None and math.hypot(pc[0] - px, pc[1] - py) <= self.POINT_INFERENCE_PX:
                out.append((c, None))
        return out

    def _face_context_under(self, px: float, py: float):
        """The ScreenTip's context for the face under the cursor: "outside"
        while a group / component is open and the face is not part of it;
        "group" / "component" for a placement; ``None`` for the open
        context's own loose mesh (and at the root)."""
        face, place = self.pick_face_inference(px, py)
        if face is None:
            return None
        return _snap_context_of(self, place)

    def _gedge_screen(self):
        """Screen-projected endpoints of every group hard edge —
        ``(ax, ay, bx, by, ok)`` arrays, cached until the scene or the
        camera moves. Shared by pick_group's edge fallback and the snap
        prefilter (during a drawing hover the camera is still, so the two
        big projections run once, not per mouse move)."""
        import numpy as np
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
        # A hover that brings new lazy placements in rebuilds the index:
        # the fixed part's edges lead it unchanged and each lazy chunk
        # keeps its edge array, so only what is new to this view is
        # projected (all 1.6 M edges, four times a mouse move with Line
        # beside the plant of #158).
        fx = getattr(idx, "gedge_fixed", None)
        head = getattr(self, "_gedge_px_head", None)
        vkey = key[1:]
        if fx is None or fx[1] + sum(map(len, fx[2])) != len(idx.gedge_a):
            ax, ay, oka = self._project_px(idx.gedge_a)
            bx, by, okb = self._project_px(idx.gedge_b)
            data = (ax, ay, bx, by, oka & okb)
        else:
            n = fx[1]
            if (head is None or head[0] != vkey or head[1] is not fx[0]
                    or head[2] != n):
                ax, ay, oka = self._project_px(idx.gedge_a[:n])
                bx, by, okb = self._project_px(idx.gedge_b[:n])
                head = self._gedge_px_head = (vkey, fx[0], n,
                                              (ax, ay, bx, by, oka & okb))
            memo = getattr(self, "_gedge_px_pieces", None)
            if memo is None or memo[0] != vkey:
                memo = self._gedge_px_pieces = (vkey, {})
            pieces, todo = memo[1], []
            for ge in fx[2]:
                hit = pieces.get(id(ge))
                if hit is None or hit[0] is not ge:
                    todo.append(ge)
            if todo:
                # The new chunks in one projection, split back after.
                flat = np.concatenate([ge.reshape(-1, 3) for ge in todo])
                x, y, ok = self._project_px(flat)
                o = 0
                for ge in todo:
                    m = 2 * len(ge)
                    sx, sy, sk = x[o:o + m], y[o:o + m], ok[o:o + m]
                    pieces[id(ge)] = (ge, (sx[0::2], sy[0::2], sx[1::2],
                                           sy[1::2], sk[0::2] & sk[1::2]))
                    o += m
            parts = [head[3]] + [pieces[id(ge)][1] for ge in fx[2]]
            data = tuple(np.concatenate([p[k] for p in parts])
                         for k in range(5))
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
    #: The radius of the snap's own search of group edges near the cursor
    #: (``_nearby_group_edges``'s default), which narrower ones in the
    #: same event are read off (see _nearby_edges_unbaked).
    GEDGE_SHARED_PX = 48.0
    #: From this many group edges up, the distances come through a screen
    #: grid (core.edge_grid) instead of one pass over all of them.
    GEDGE_GRID_MIN = 20000

    def warm_edge_grid(self) -> None:
        """Bin the group edges for the current projection now (see
        :meth:`_gedge_dist`), as its second hover would: a tool whose drag
        keeps the camera and the model still (Push/Pull on the overlay)
        asks right after its click, so no move of the drag builds it
        (~14 ms in a 9 674-face group of the Plaza, 19-11)."""
        from core.edge_grid import EdgeGrid
        if _NO_SNAP_FAST or (getattr(self, "pick_threshold_px", 0.0)
                             > Viewport.GEDGE_REACH_PX):
            return
        proj = self._gedge_screen()
        ax, ay, bx, by, ok = proj
        if len(ax) < Viewport.GEDGE_GRID_MIN:
            return
        slot = getattr(self, "_gedge_grid_cache", None)
        if slot is not None and slot[0] is proj and slot[1] is not None:
            return
        self._gedge_grid_cache = (proj, EdgeGrid(
            ax, ay, bx, by, ok, self.width(), self.height(),
            Viewport.GEDGE_REACH_PX))

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
        if (not _NO_SNAP_FAST and len(ax) >= Viewport.GEDGE_GRID_MIN
                and getattr(self, "pick_threshold_px", 0.0)
                <= Viewport.GEDGE_REACH_PX):
            # (projection, grid or None): the grid waits for the second hover.
            slot = getattr(self, "_gedge_grid_cache", None)
            if slot is None or slot[0] is not proj:
                self._gedge_grid_cache = (proj, None)
            else:
                grid = slot[1]
                if grid is None:
                    grid = EdgeGrid(ax, ay, bx, by, ok, self.width(),
                                    self.height(), Viewport.GEDGE_REACH_PX)
                    self._gedge_grid_cache = (proj, grid)
                near_px = max(Viewport.GEDGE_NEAR_PX,
                              getattr(self, "pick_threshold_px", 0.0))
                for reach in (near_px, Viewport.GEDGE_REACH_PX):
                    ids = grid.near(px, py, reach)
                    if ids is None:
                        break
                    sub = segment_distances(ax, ay, bx, by, ok, px, py, ids)
                    if (reach >= Viewport.GEDGE_REACH_PX
                            or int((sub < reach).sum()) >= Viewport.GEDGE_ENOUGH):
                        d = np.full(len(ax), np.inf)
                        d[ids] = sub
                        break
        if d is None:
            d = segment_distances(ax, ay, bx, by, ok, px, py)
        self._gedge_dist_cache = (key, d, proj)
        return d

    def _ledge_screen(self):
        """Screen-projected endpoints of every loose edge — the
        ``_gedge_screen`` twin for the snap prefilter after an explode
        leaves a big loose mesh. While a context is open the rest of the
        model's loose edges ride along (see ``_outer_loose_meshes``); their
        ``edge_sel`` is False, so picks and the box leave them alone.
        Cached until the scene/camera moves."""
        idx = self._pick_index(near="skip")
        if idx.edge_a is None or not len(idx.edge_a):
            return None
        M = self._np_mvp()
        # Whether the rest of the model's loose edges are in the index
        # changes with «Hide rest of model», which bumps no scene version.
        key = (_content_ver(self), id(self.scene.mesh), M.tobytes(),
               self.width(), self.height(),
               bool(getattr(self, "_rest_is_hidden", lambda: False)()))
        cached = getattr(self, "_ledge_px_cache", None)
        # The index's own arrays too: _pick_edge reads this projection as
        # the one of the index it holds, whatever rebuilt it.
        if (cached is not None and cached[0] == key
                and cached[2] is idx.edge_a and cached[3] is idx.edge_b):
            return cached[1]
        ax, ay, oka = self._project_px(idx.edge_a)
        bx, by, okb = self._project_px(idx.edge_b)
        data = (ax, ay, bx, by, oka & okb)
        self._ledge_px_cache = (key, data, idx.edge_a, idx.edge_b)
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
        # The same distances through the engine when it is on (its
        # arithmetic is _numpy_distances', checked at start-up by
        # _native_pass): ~0.4 ms of NumPy a snap over the Plaza's 9 674-face
        # group, and again each move of a push (19-11).
        from core.edge_grid import _native_pass, _numpy_distances
        mod = _native_pass() if len(ax) >= _LOOSE_NATIVE_MIN else None
        if mod is not None:
            f = np.ascontiguousarray
            d = np.asarray(mod.segment_distances(
                f(ax, np.float64), f(ay, np.float64), f(bx, np.float64),
                f(by, np.float64), f(ok, bool), float(px), float(py), None))
        else:
            d = _numpy_distances(ax, ay, bx, by, ok, px, py)
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
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if (nat is not None and radius_px <= Viewport.GEDGE_REACH_PX
                and cap <= Viewport.GEDGE_ENOUGH):
            return self._nearby_edges_unbaked(px, py, radius_px, cap, nat)
        idx = self._pick_index(near=("snap", px, py))
        proj = self._gedge_screen()
        if proj is None:
            return []
        import numpy as np
        if not proj[4].any():
            return []
        dist = getattr(self, "_gedge_dist", None)          # stub VPs in tests
        if radius_px > Viewport.GEDGE_REACH_PX or cap > Viewport.GEDGE_ENOUGH:
            # Past what _gedge_dist promises (GEDGE_NEAR_PX): every edge.
            from core.edge_grid import segment_distances
            d = segment_distances(*proj, px, py)
        else:
            d = (dist(px, py) if dist is not None
                 else Viewport._gedge_dist(self, px, py))
        cand = np.where(d < radius_px)[0]
        if len(cand) > cap:
            # The nearest ``cap`` first, then those in order: sorting all
            # of them was 90 ms a move with the whole plant of #158 in view
            # (half a million edges inside the radius).
            dc = d[cand]
            if len(cand) > 4 * cap:
                part = np.argpartition(dc, cap - 1)[:cap]
                cand, dc = cand[part], dc[part]
            cand = cand[np.lexsort((cand, dc))[:cap]]
        return [_group_pseudo_edge(idx, int(i)) for i in cand]

    def _nearby_edges_unbaked(self, px, py, radius, cap, nat,
                              with_d=False) -> list:
        """``_nearby_group_edges`` with the lazy placements' edges from the
        native engine, none of them baked (#158): the fixed placements'
        edges as the index holds them, those of the placements the snap's
        footprint takes in as their bakes would hold them — the nearest
        ``cap`` within ``radius`` px, nearest first (with their distances
        as ``(d, edge)`` when ``with_d``).

        Within one input event the cursor's own edge (``pick_edge_any``:
        the nearest under the pick threshold) and the snap's (the nearest
        48 within 48 px) are both read off one search of the wider: by
        distance, then fixed before lazy, then index or (candidate, edge),
        the order is total, so the nearest ``cap`` within ``radius`` are
        those of the wider within it. Over the plant of #158 each search
        was ~10 ms, twice a pointer move."""
        wide, ncap = Viewport.GEDGE_SHARED_PX, Viewport.GEDGE_ENOUGH
        serial = getattr(self, "_input_serial", None)
        if (not _EDGES_SHARED or serial is None or not radius <= wide
                or not 0 < cap <= ncap):
            out = self._nearby_edges_found(px, py, radius, cap, nat)
        else:
            key = (serial, float(px), float(py), id(nat[0]), id(nat[1]),
                   self._placements_epoch(),
                   getattr(self.scene, "version", None),
                   tuple(self._np_mvp().ravel()), self.width(),
                   self.height(), id(self._pick_index(near="skip")),
                   id(self._gedge_screen()),
                   id(getattr(self, "_depth_snap", None)))
            memo = getattr(self, "_edges_near_shared", None)
            if memo is None or memo[0] != key:
                memo = self._edges_near_shared = (key, self._nearby_edges_found(
                    px, py, wide, ncap, nat))
            out = [(d, _copy_snap_edge(e)) for d, e in memo[1]
                   if d < radius][:cap]
        return out if with_d else [e for _d, e in out]

    def _nearby_edges_found(self, px, py, radius, cap, nat) -> list:
        """_nearby_edges_unbaked's search: ``(d, edge)``, nearest first."""
        import numpy as np
        iset, snap, _vis = nat
        idx = self._pick_index(near="skip")
        fx = getattr(idx, "gedge_fixed", None)
        m = fx[1] if fx is not None else 0
        out = []                           # (d, edge)
        if m and self._gedge_screen() is not None:
            d = self._gedge_dist(px, py)[:m]
            cand = _nearest_within(d, radius, cap)
            out += [(float(d[i]), _group_pseudo_edge(idx, int(i)))
                    for i in cand]
        table = self._pick_lazy_table()
        rows = self._footprint_need(table, float(px), float(py), radius)
        rows = rows[np.isin(rows, snap)] if len(rows) else rows
        if len(rows):
            M = self._np_mvp()
            pl, _e, a, b, d = iset.edges_near(
                np.ascontiguousarray(rows, np.int64),
                np.ascontiguousarray(M.T).ravel().tolist(),
                float(self.width()), float(self.height()), float(px),
                float(py), float(radius), int(cap))
            groups = table[0]
            for i, aa, bb, dd in zip(pl.tolist(), a.tolist(), b.tolist(),
                                     d.tolist()):
                owner = self._owner_of(groups[i])
                out.append((dd, _SnapEdge(
                    QVector3D(*aa), QVector3D(*bb), in_group=True,
                    context=_snap_context_of(self, groups[i]), group=owner)))
        out.sort(key=lambda de: de[0])        # stable: the fixed ones first
        return out[:cap]

    def _pick_group_edge_unbaked(self, px, py, nat):
        """pick_group's edge fallback with the lazy placements' edges from
        the engine, none baked (#158): ``(d, owner)`` of the nearest group
        edge within the pick threshold that a pick may land on and the
        user can see, or ``(threshold, None)``."""
        import numpy as np
        best = self.pick_threshold_px
        idx = self._pick_index(near="skip")
        cands = []                         # (d, a, b, t, owner)
        fx = getattr(idx, "gedge_fixed", None)
        m = fx[1] if fx is not None else 0
        proj = self._gedge_screen() if m else None
        if proj is not None:
            ax, ay, bx, by, ok = (v[:m] for v in proj)
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            safe = np.where(l2 > 1e-12, l2, 1.0)
            t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe, 0.0, 1.0)
            d = np.hypot(ax + t * dx - px, ay + t * dy - py)
            sel = getattr(idx, "gedge_sel", None)
            if sel is not None:
                ok = ok & sel[:m]
            d = np.where(ok, d, np.inf)
            near = np.where(d < best)[0]
            for i in near[np.argsort(d[near], kind="stable")]:
                cands.append((float(d[i]), QVector3D(*idx.gedge_a[i]),
                              QVector3D(*idx.gedge_b[i]), float(t[i]),
                              idx.gedge_groups[int(idx.gedge_gi[i])]))
        table = self._pick_lazy_table()
        rows = self._footprint_need(table, float(px), float(py), best)
        if len(rows):
            rows = rows[np.isin(rows, Viewport._lazy_sel_rows(self, nat))]
        if len(rows):
            M = self._np_mvp()
            pl, _e, a, b, d = nat[0].edges_near(
                np.ascontiguousarray(rows, np.int64),
                np.ascontiguousarray(M.T).ravel().tolist(),
                float(self.width()), float(self.height()), float(px),
                float(py), float(best), int(Viewport.GEDGE_ENOUGH))
            if len(pl):
                # Where along each the cursor is, as the index's
                # projection of it reads it.
                ex, ey, _ok = self._project_px(
                    np.concatenate([np.asarray(a, np.float64),
                                    np.asarray(b, np.float64)]))
                n = len(pl)
                ax, ay, bx, by = ex[:n], ey[:n], ex[n:], ey[n:]
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                safe = np.where(l2 > 1e-12, l2, 1.0)
                t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe,
                            0.0, 1.0)
                groups = table[0]
                for k, i in enumerate(pl.tolist()):
                    cands.append((float(d[k]), QVector3D(*a[k]),
                                  QVector3D(*b[k]), float(t[k]),
                                  self._owner_of(groups[i])))
        cands.sort(key=lambda c: c[0])         # stable: the fixed ones first
        for dd, a, b, t, owner in cands:
            if not self._is_occluded(a + (b - a) * t):
                return dd, owner
        return best, None

    def pick_edge_any(self, screen_x: float, screen_y: float):
        """The edge under the cursor, loose OR a group's (as a world
        pseudo-edge with ``in_group``), nearest first — what the linear
        inferences hover: parallel / perpendicular to a component's edge,
        the reference lock, Push/Pull level with it (groups are read
        from outside without opening them).

        The loose half is picked with the SNAP rule, not the click one: the
        rest of the model drawn around an open group / component is a
        reference too, even though a click cannot select it."""
        loose = self._pick_edge(screen_x, screen_y, visible_only=False,
                                which="snap")
        nat = (self._lazy_native() if hasattr(self, "_lazy_native")
               else None)
        if nat is not None:
            # The nearest group edge under the threshold, fixed or lazy
            # (see _nearby_edges_unbaked), against the loose one as below.
            near = self._nearby_edges_unbaked(screen_x, screen_y,
                                              self.pick_threshold_px, 1, nat,
                                              with_d=True)
            if not near:
                return loose
            dg, g = near[0]
            if loose is not None:
                pa = self._world_to_pixel(loose.a)
                pb = self._world_to_pixel(loose.b)
                if pa is not None and pb is not None:
                    from core.snap import _closest_on_segment_2d
                    dl, _t = _closest_on_segment_2d((screen_x, screen_y),
                                                    pa, pb)
                    if dl <= dg:
                        return loose
            return g
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
        # The content's version: a view-only bump (a hover's highlight, a
        # click) moves no origin — 21 000 of them re-mapped a mouse move.
        key = (_content_ver(self), id(self.scene.edit_group))
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
        near = np.flatnonzero(d <= self.POINT_INFERENCE_PX)
        cap = Viewport.GEDGE_ENOUGH
        if len(near) > cap:
            # The nearest ones, as with the group edges: with the whole
            # plant of #158 in view 17 000 origins fell inside the radius
            # and the snap weighed each in Python (~0.1 s a mouse move).
            near = near[np.lexsort((near, d[near]))[:cap + 1]]
        for i in near:
            if groups[i] is moving:
                continue
            if len(out) >= cap:
                break
            o = QVector3D(*pts[i])
            out.append(_SnapEdge(o, QVector3D(o), component_origin=True,
                                 context=_snap_context_of(self, groups[i])))
        return out

    def _arc_midpoints(self, px: float, py: float) -> list:
        """The "Arc Midpoint": the middle of each loose arc's sweep
        (the point on the arc bisecting its two ends — not any facet's
        midpoint). Closed curves (circles) have none. Computed once per
        scene version, offered when near the cursor."""
        cache = getattr(self, "_arc_mid_cache", None)
        # On the content, not the version: a click's selection bump made
        # every placement's midpoints over again.
        ckey = (_content_ver(self), id(self.scene.mesh),
                id(self.scene.edit_group),
                bool(getattr(self, "_rest_is_hidden", lambda: False)()))
        if cache is None or cache[0] != ckey:
            # Per MESH, keyed by its mutation serial: a scene version bump
            # (every frame of a drag) used to walk every prototype's curves
            # again — 31 ms a frame while moving a face (2026-09-14). Now a
            # mesh's midpoints are recomputed only when that mesh changed;
            # the version pass only maps them through the placements.
            by_mesh = getattr(self, "_arc_mid_by_mesh", None)
            if by_mesh is None:
                by_mesh = self._arc_mid_by_mesh = {}
            # Only the meshes met in this pass are kept. Emptying the whole
            # memo past 2 048 meshes emptied it on EVERY pass on a model
            # with more (2 721 on the plant of #158): all of them were
            # worked out again, ~0.5 s of the first hover after an edit.
            seen: dict = {}

            def local_mids(mesh):
                serial = getattr(mesh, "_mut_serial", None)
                hit = seen.get(id(mesh)) or by_mesh.get(id(mesh))
                if hit is None or hit[0] != serial or hit[2] is not mesh:
                    hit = (serial, self._mesh_arc_midpoints(mesh), mesh)
                seen[id(mesh)] = hit
                return hit[1]
            mids = [(m, None) for m in local_mids(self.scene.mesh)]
            # …the root loose mesh drawn around an open context (a reference
            # outside it), in its own world coordinates…
            outer_of = getattr(self, "_outer_loose_meshes", None)
            for om in (outer_of() if outer_of is not None else ()):
                mids += [(m, "outside") for m in local_mids(om)]
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
                ctx = _snap_context_of(self, g)
                mids += [(xf.map(m) if xf is not None else QVector3D(m), ctx)
                         for m in lm]
            self._arc_mid_by_mesh = seen
            cache = (ckey, mids)
            self._arc_mid_cache = cache
        out: list = []
        for m, ctx in cache[1]:
            pc = self._world_to_pixel(m)
            if pc is None or math.hypot(pc[0] - px, pc[1] - py) > self.POINT_INFERENCE_PX:
                continue
            out.append(_SnapEdge(QVector3D(m), QVector3D(m),
                                 arc_midpoint=True, context=ctx))
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
            # (only the curve edges listed: listing all of them was
            # most of the first hover over the plant of #158)
            curved = _plan_curved_edges(plan)
            ab = plan.edges[curved].tolist()
            for k, i in enumerate(curved.tolist()):
                by_curve.setdefault(plan.curve[i], []).append(ab[k])
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

    def _billboard_placements(self) -> list:
        """The face-me placements of ``_placements()``, kept while it is:
        walking the 21 406 placements of #158 for the two of them was
        ~2 ms of every pointer move."""
        groups = self._placements()
        epoch_of = getattr(self, "_placements_epoch", None)
        if epoch_of is None:                         # stub viewports
            return [g for g in groups if getattr(g, "billboard", False)]
        key = (epoch_of(), id(groups), len(groups))
        memo = getattr(self, "_billboard_memo", None)
        if memo is None or memo[0] != key or memo[1] is not groups:
            memo = self._billboard_memo = (
                key, groups,
                [g for g in groups if getattr(g, "billboard", False)])
        return memo[2]

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
        for g in self._billboard_placements():
            if g is moving:
                continue
            if not self.scene.group_snappable(g):
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
        reference model snaps to its corners and edges.

        Loose edges the scene itself says are not there (hidden, or on a
        hidden layer) are left out — see :func:`_snap_dropped_loose`."""
        # Guide lines are clipped to the part in front of the camera so the
        # snap engine gets projectable endpoints (an endpoint behind the eye
        # used to kill on-line snapping in ordinary 3D views); guide POINTS
        # snap as degenerate pseudo-edges, exactly like survey points.
        lines = []
        circles = []
        # Guides that Move is dragging pass through the cursor: left out,
        # or the cursor locks onto its own guide (#627).
        moving = getattr(self.active_tool, "moving_guide_ids", None)
        moving = moving() if callable(moving) else ()
        for g in shown_guides(self.scene):
            if id(g) in moving:
                continue
            if getattr(g, "is_circle", False):
                circles.append(g)   # rim is resolved in compute_snap; centre below
                continue
            if g.is_line:
                seg = self._guide_snap_segment(g)
                if seg is not None:
                    lines.append(_SnapEdge(*seg, guide=True))
            else:
                lines.append(_SnapEdge(QVector3D(g.point), QVector3D(g.point)))
        # Reference-image borders snap like guides: aligning a scan against
        # real geometry (or drawing to its edge) is what tracing needs.
        placed_images = getattr(self, "_placed_image_planes", None)
        if callable(placed_images):
            placed_images = placed_images()
        else:
            # A few focused tests borrow this method on a lightweight
            # viewport double.  It still needs the top-level image borders,
            # even though it has no group-placement collector.
            placed_images = ((im, None, im)
                             for im in getattr(self.scene, "image_planes", ()))
        for im, matrix, owner in placed_images:
            target = owner if owner is not im else im
            if (getattr(im, "locked", False)
                    or not self.scene.entity_selectable(target)):
                continue
            edges = im.border_edges()
            if matrix is not None:
                edges = [(matrix.map(a), matrix.map(b)) for a, b in edges]
            for a, b in edges:
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
        # 10/Oct/26 added BastelBaus: add snapping to dimension edges.
        # Added before the early return below (a scene with only dimensions
        # must still snap to them) and before the cut filter (a dimension
        # the section hides must not attract snaps).
        for dim in getattr(self.scene, "dimensions", None) or []:
            if not self.scene.entity_selectable(dim):
                continue
            near.append(_SnapEdge(*dim.line_points()))
        # A guide circle's centre is a permanent snap target, like the centre
        # of a visited mesh circle (the rim is resolved in compute_snap).
        for c in circles:
            near.append(_SnapEdge(QVector3D(c.center), QVector3D(c.center),
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
            if self.scene.outside_section_box(gp):
                continue                # the section box leaves it out
            near.append(_SnapEdge(QVector3D(gp.position),
                                  QVector3D(gp.position)))
        # The rest of the model's loose geometry — the root mesh drawn faded
        # around an open group / component — is a reference too.
        # Its edges are filtered one by one (each carries its own layer and
        # hidden flag), and «Hide rest of model» leaves them out already.
        outer_of = getattr(self, "_outer_loose_meshes", None)
        outer = []
        for om in (outer_of() if outer_of is not None else ()):
            edges = om.edges
            outer += [e for e, ok in zip(
                edges, _edges_snappable(self.scene, edges)) if ok]
        big = (px is not None
               and (len(self.scene.edges) + len(outer)) > _LOOSE_SNAP_CAP)
        if not lines and not near and not circles and sp is None \
                and not big and not outer and excl is None \
                and not _snap_dropped_loose(self):
            return self.scene
        if big:
            # Only the edges near the cursor are considered, so ask each one
            # (dozens) rather than walking a mesh of 160k to build the drop
            # set above. The index holds the rest of the model's loose
            # edges too, so this reaches them.
            loose = self._nearby_loose_edges(px, py)
            loose = [e for e, ok in zip(
                loose, _edges_snappable(self.scene, loose)) if ok]
        else:
            loose = list(self.scene.edges) + outer
            drops = _snap_dropped_loose(self)
            if drops:
                loose = [e for e in loose if id(e) not in drops]
        if excl is not None and excl[0]:
            loose = [e for e in loose if id(e) not in excl[0]]
        if sp is not None:
            loose = [e for e in loose if _kept(e)]
        if outer:
            # The ScreenTip must say these are outside the open context:
            # a real Edge carries no context of its own.
            outer_ids = {id(e) for e in outer}
            loose = [_SnapEdge(e.a, e.b, context="outside")
                     if id(e) in outer_ids else e for e in loose]
        from types import SimpleNamespace
        return SimpleNamespace(edges=loose + lines + near, circles=circles)

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
        if kids or getattr(group, "images", None):
            cache = getattr(self, "_container_obb", None)
            if cache is None:
                cache = self._container_obb = {}
            key = _content_ver(self)
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
        # The box follows the group's axes (issue #44), and Change Axes can
        # turn them without touching one vertex — so the cached box is only
        # good for the frame it was measured on.
        from core.group import group_frame
        fr = group_frame(group)
        fkey = tuple(fr.data()) if fr is not None else None
        xf = getattr(group, "xform", None)
        if xf is not None and id(group) not in (
                getattr(self, "_inst_chunks", None) or ()):
            # A placement nobody has baked to the world: the box is measured
            # on the points, the bake would only have carried it. Selecting
            # the 590 objects of a big model baked them all (#1092). Good for
            # what its bake would have been good for.
            base = self._group_chunk(
                _proto_wrapper(self, group.mesh, _paint_of(self, group)))
            key = (base["uid"], tuple(xf.data()), base.get("rev"), fkey)
            memo = getattr(self, "_inst_obb", None)
            if memo is None:
                memo = self._inst_obb = {}
            hit = memo.get(id(group))
            if hit is not None and hit[0] == key:
                return hit[1]
            obb = self._compute_obb(group)
            if len(memo) > 65536:          # ids of placements long gone
                memo.clear()
            memo[id(group)] = (key, obb)
            return obb
        entry = self._group_chunk(group)
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
        from core.mesh import DeferredMesh
        for g, _m in iter_placements(group):
            mesh = g.mesh
            if mesh is None or id(mesh) in valid:
                continue
            # A lazy mesh still unbuilt was never edited (an edit builds
            # it): its cached points stand, and asking for its vertices
            # would build it -- the box over a big model built them all.
            lazy = type(mesh) is DeferredMesh
            if not lazy and not mesh.vertices:
                continue
            hit = store.get(id(mesh))
            if hit is None:
                continue
            serial, arr = hit
            if (id(mesh) in editing
                    or getattr(mesh, "_mut_serial", None) != serial
                    or (not lazy and len(arr) != len(mesh.vertices))):
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
            pick = (getattr(self, "pick_face_inference", None)
                    or getattr(self, "pick_face_placement", None)
                    or self.pick_face_any)   # stub VPs in tests
            face, group = pick(x, y)
            if face is not None:
                mesh = getattr(group, "mesh", None) if group is not None \
                    else self.scene.mesh
                if mesh is None:
                    mesh = self.scene.mesh
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
        if mesh is None:
            return None
        inv = None
        if xf is not None:
            inv, ok = xf.inverted()
            if not ok:
                return None
        la = inv.map(pseudo.a) if inv is not None else pseudo.a
        lb = inv.map(pseudo.b) if inv is not None else pseudo.b
        if not _lazy_edge_may_be_curve(mesh, la, lb):
            # A lazy mesh with no curve edge where the lookups below could
            # land: building it (~0.5 s for a big group of the plant of
            # #158, on the hover that crosses into it) would answer None.
            return None
        if not mesh.edges:
            return None
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
        real = getattr(src, "real", None)
        from core.mesh import DeferredMesh
        lazy = real is not None and type(mesh) is DeferredMesh
        if real is not None and not lazy:
            # Found over a lazy mesh's light face, since built: an edit asks
            # of the real one. Still lazy, the mesh has not changed: only the
            # matrix can have, and building it here cost a big group's whole
            # build on the frame after any edit (#1092).
            src = real()
        if isinstance(src, Face):
            if lazy or src in mesh.faces:
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
    def _shift_lock_ref(self):
        return self.inference._shift_lock_ref

    @_shift_lock_ref.setter
    def _shift_lock_ref(self, value) -> None:
        self.inference._shift_lock_ref = value

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
        "extension", "from_point",
    })

    def _capture_shift_lock(self) -> None:
        """On Shift press, mark the plane the shape is drawing on and freeze
        the active inference's direction so it holds even as the cursor
        wanders off it (inference lock). Both at once, one does not take
        the other's place: the mark only says WHICH plane, and the pointer
        goes on marking midpoints, endpoints and alignments (Marco: «100%
        aditivo»). Each side keeps its own guard."""
        self._shift_lock = None
        self._shift_lock_ref = None
        self._mark_plane_for_shift()
        snap = self.last_snap
        tool = self.active_tool
        owns = getattr(tool, "owns_shift_lock", None)
        if owns is not None and owns():
            return  # the tool reads the cursor's motion itself
        start = getattr(tool, "start_point", None) if tool is not None else None
        if snap is None or snap.kind not in self._SHIFT_LOCKABLE:
            return
        axis = snap.axis if snap.axis in _AXIS_VECTORS else None
        if start is None and axis is None:
            return          # no start point and no axis: nothing to lock

        # Lock to the exact inferred axis, preserving its direction.
        if axis is not None:
            d = QVector3D(_AXIS_VECTORS[axis])
            if start is not None and QVector3D.dotProduct(snap.point - start, d) < 0.0:
                d = -d
        else:
            d = snap.point - start
        if d.length() > 1e-6:
            self._shift_lock = (d.normalized(), snap.color)
            if (snap.kind == "from_point" and axis is not None
                    and getattr(snap, "guide", None) is not None):
                self._shift_lock_ref = (snap.guide[0], axis)

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
        nothing for that pixel.

        The answer is values, no face: whatever the search picks it only
        reads, so a big lazy mesh under the cursor stays unbuilt (#1092)."""
        from views.array_bake import reading_only
        with reading_only():
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
