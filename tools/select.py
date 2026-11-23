# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Select tool: pick edges and faces and delete them.

Behavior:
- Left click on / near an edge: select that edge. Click on a face interior
  (when no edge is closer): select the face. Edges win ties because they sit
  on top of faces, the usual convention.
- Modifiers, the classic ones: Shift-click TOGGLES what it picks (click an
  already-selected line or face to drop it out of the selection — the way you
  carve a wall out of a box selection), Ctrl-click adds, Shift+Ctrl-click
  removes, and a plain click replaces the whole selection. The rubber-band box
  reads the same modifiers.
- Left click on empty space: clear the selection.
- Hover highlights whatever the click would pick, so the user sees the target
  before committing.
- Delete / Backspace: remove the selected edges and faces from the scene.
"""
from __future__ import annotations

import math

from views import prompts as _prompts

from PySide6.QtCore import Qt

from core.dimension import Dimension
from core.textlabel import TextLabel
from core.group import Group
from core.mesh import Edge, Face
from core.guide import is_guide
from core.section import SectionBox, SectionPlane
from core.history import (
    CompoundCommand,
    DeleteDimensionsCommand,
    DeleteGeoPathsCommand,
    DeleteGroupCommand,
    DeleteGuidesCommand,
    DeleteSectionPlanesCommand,
    DeleteTextLabelsCommand,
    SetActiveSectionCommand,
    section_boxes_removed,
    EditTextLabelCommand,
    EraseSelectionCommand,
)
from georef.geopath import GeoPath
from tools.base import Tool, ToolContext



def selection_mode(modifiers) -> str:
    """How a click (or a rubber-band box) joins the current selection, from
    the keyboard modifiers — the classic rules: Shift toggles, Ctrl adds,
    Shift+Ctrl removes, nothing replaces."""
    shift = bool(modifiers & Qt.ShiftModifier)
    ctrl = bool(modifiers & Qt.ControlModifier)
    if shift and ctrl:
        return "remove"
    if ctrl:
        return "add"
    return "toggle" if shift else "replace"


def _seg_rect_mask(ax, ay, bx, by, ok, rect, crossing):
    """Vectorized rect test for N screen segments: window mode = both
    endpoints inside; crossing mode = an endpoint inside or the segment
    intersecting one of the four borders. NumPy twin of _pt_in_rect /
    _seg_rect_overlap for import-scale meshes."""
    import numpy as np
    x0, y0, x1, y1 = rect
    in_a = ok & (ax >= x0) & (ax <= x1) & (ay >= y0) & (ay <= y1)
    in_b = ok & (bx >= x0) & (bx <= x1) & (by >= y0) & (by <= y1)
    if not crossing:
        return in_a & in_b
    cross = in_a | in_b
    todo = ok & ~cross
    if todo.any():
        for px, py, qx, qy in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                               (x1, y1, x0, y1), (x0, y1, x0, y0)):
            d1 = (qx - px) * (ay - py) - (qy - py) * (ax - px)
            d2 = (qx - px) * (by - py) - (qy - py) * (bx - px)
            d3 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            d4 = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax)
            hit = todo & (d1 * d2 < 0) & (d3 * d4 < 0)
            cross |= hit
            todo &= ~hit
            if not todo.any():
                break
    return cross


# ---- Regions: the box, and the lasso drawn around what to take ----------------
#
# Every test the box makes asks the same few questions of its rectangle: is
# this point inside, does this segment touch it, does it lie wholly inside.
# A region answers them, so a lasso — any closed outline on the screen —
# takes exactly what the box would take, by the same rules, wherever the
# box looks: loose geometry, groups and components, guides, dimensions and
# labels. The rectangle keeps the box's own arithmetic, unchanged.

class _Region:
    """A selection outline on the screen, in pixels."""
    #: A projection keeps what is inside a box inside the hull of its
    #: corners; a region that is not convex cannot be trusted with that.
    convex = True
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)

    def contains(self, p) -> bool:
        raise NotImplementedError

    def touches(self, a, b) -> bool:
        """Segment ``a-b`` has a point inside or crosses the outline."""
        raise NotImplementedError

    def encloses(self, a, b) -> bool:
        """Segment ``a-b`` lies wholly inside."""
        raise NotImplementedError

    def inside_mask(self, xs, ys, ok):
        raise NotImplementedError

    def seg_mask(self, ax, ay, bx, by, ok, crossing):
        raise NotImplementedError


class _RectRegion(_Region):
    """The rubber-band box: ``(x0, y0, x1, y1)``, normalized."""

    def __init__(self, rect) -> None:
        self.rect = tuple(float(v) for v in rect)
        self.bbox = self.rect

    def contains(self, p) -> bool:
        return _pt_in_rect(p, self.rect)

    def touches(self, a, b) -> bool:
        return _seg_rect_overlap(a, b, self.rect)

    def encloses(self, a, b) -> bool:
        return _pt_in_rect(a, self.rect) and _pt_in_rect(b, self.rect)

    def inside_mask(self, xs, ys, ok):
        x0, y0, x1, y1 = self.rect
        return ok & (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)

    def seg_mask(self, ax, ay, bx, by, ok, crossing):
        return _seg_rect_mask(ax, ay, bx, by, ok, self.rect, crossing)


#: A lasso keeps at most this many corners: a freehand stroke delivers one
#: point per mouse move, and every test walks the outline once per corner.
LASSO_MAX_POINTS = 256


def simplify_outline(points, tolerance: float = 1.5,
                     limit: int = LASSO_MAX_POINTS) -> list:
    """``points`` (screen pixels) with the corners that bend it less than
    ``tolerance`` px dropped (Ramer–Douglas–Peucker, iterative), the
    tolerance doubled until at most ``limit`` remain. Repeated points go
    first."""
    pts = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if not pts or abs(q[0] - pts[-1][0]) + abs(q[1] - pts[-1][1]) > 1e-9:
            pts.append(q)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) <= 3:
        return pts

    def rdp(tol):
        keep = [False] * len(pts)
        keep[0] = keep[-1] = True
        stack = [(0, len(pts) - 1)]
        while stack:
            i, j = stack.pop()
            ax, ay = pts[i]
            bx, by = pts[j]
            dx, dy = bx - ax, by - ay
            norm = (dx * dx + dy * dy) ** 0.5
            far, at = -1.0, -1
            for k in range(i + 1, j):
                px, py = pts[k]
                if norm < 1e-12:
                    d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
                else:
                    d = abs(dy * (px - ax) - dx * (py - ay)) / norm
                if d > far:
                    far, at = d, k
            if at >= 0 and far > tol:
                keep[at] = True
                stack.append((i, at))
                stack.append((at, j))
        return [p for p, k in zip(pts, keep) if k]

    tol = tolerance
    out = rdp(tol)
    while len(out) > limit:
        tol *= 2.0
        out = rdp(tol)
    return out


def outline_area(points) -> float:
    """Signed area of the closed outline in screen pixels (y down):
    positive when it was drawn clockwise as seen on the screen."""
    n = len(points)
    s = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


class LassoRegion(_Region):
    """Any closed outline on the screen. Inside is the even–odd rule; a
    point on the outline counts as inside, as on the box's border."""

    def __init__(self, points) -> None:
        import numpy as np
        pts = simplify_outline(points)
        if len(pts) < 3:
            # A lasso smaller than the thinning's tolerance keeps its own
            # corners rather than collapse to a line.
            pts = simplify_outline(points, tolerance=0.0)
        if len(pts) < 3:
            raise ValueError("a lasso needs three corners")
        self.points = pts
        self.px = np.array([p[0] for p in pts], dtype=np.float64)
        self.py = np.array([p[1] for p in pts], dtype=np.float64)
        self.qx = np.roll(self.px, -1)
        self.qy = np.roll(self.py, -1)
        self.bbox = (float(self.px.min()), float(self.py.min()),
                     float(self.px.max()), float(self.py.max()))
        self.convex = self._is_convex()

    def _is_convex(self) -> bool:
        n = len(self.points)
        sign = 0
        for i in range(n):
            ax, ay = self.points[i]
            bx, by = self.points[(i + 1) % n]
            cx, cy = self.points[(i + 2) % n]
            z = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
            if abs(z) < 1e-9:
                continue
            s = 1 if z > 0 else -1
            if sign == 0:
                sign = s
            elif s != sign:
                return False
        return True

    # ---- One at a time (the per-entity walk) ---------------------------------
    def _in_bbox(self, p) -> bool:
        x0, y0, x1, y1 = self.bbox
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1

    def _on_outline(self, p) -> bool:
        x, y = p
        pts = self.points
        n = len(pts)
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
            if abs(cross) > 1e-6 * max(1.0, abs(bx - ax) + abs(by - ay)):
                continue
            if (min(ax, bx) - 1e-9 <= x <= max(ax, bx) + 1e-9
                    and min(ay, by) - 1e-9 <= y <= max(ay, by) + 1e-9):
                return True
        return False

    def contains(self, p) -> bool:
        if not self._in_bbox(p):
            return False
        x, y = p
        inside = False
        pts = self.points
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > y) != (yj > y):
                xc = xj + (y - yj) * (xi - xj) / (yi - yj)
                if x < xc:
                    inside = not inside
            j = i
        return inside or self._on_outline(p)

    def _crosses(self, a, b) -> bool:
        pts = self.points
        n = len(pts)
        return any(_seg_seg_2d(a, b, pts[i], pts[(i + 1) % n])
                   for i in range(n))

    def touches(self, a, b) -> bool:
        if self.contains(a) or self.contains(b):
            return True
        x0, y0, x1, y1 = self.bbox
        if (max(a[0], b[0]) < x0 or min(a[0], b[0]) > x1
                or max(a[1], b[1]) < y0 or min(a[1], b[1]) > y1):
            return False
        return self._crosses(a, b)

    def encloses(self, a, b) -> bool:
        if not (self.contains(a) and self.contains(b)):
            return False
        return self.convex or not self._crosses(a, b)

    # ---- Many at once (NumPy, import-scale meshes) ----------------------------
    def inside_mask(self, xs, ys, ok):
        import numpy as np
        x0, y0, x1, y1 = self.bbox
        cand = ok & (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
        out = np.zeros(len(xs), dtype=bool)
        idx = np.nonzero(cand)[0]
        if not len(idx):
            return out
        x = xs[idx]
        y = ys[idx]
        inside = np.zeros(len(idx), dtype=bool)
        on = np.zeros(len(idx), dtype=bool)
        for ax, ay, bx, by in zip(self.px, self.py, self.qx, self.qy):
            straddle = (ay > y) != (by > y)
            if straddle.any():
                with np.errstate(divide="ignore", invalid="ignore"):
                    xc = bx + (y - by) * (ax - bx) / (ay - by)
                inside ^= straddle & (x < xc)
            cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
            tol = 1e-6 * max(1.0, abs(bx - ax) + abs(by - ay))
            on |= ((np.abs(cross) <= tol)
                   & (x >= min(ax, bx) - 1e-9) & (x <= max(ax, bx) + 1e-9)
                   & (y >= min(ay, by) - 1e-9) & (y <= max(ay, by) + 1e-9))
        out[idx] = inside | on
        return out

    def _cross_mask(self, ax, ay, bx, by, todo):
        """Which of the ``todo`` segments properly cross the outline."""
        import numpy as np
        hit = np.zeros(len(ax), dtype=bool)
        x0, y0, x1, y1 = self.bbox
        todo = (todo & (np.maximum(ax, bx) >= x0) & (np.minimum(ax, bx) <= x1)
                & (np.maximum(ay, by) >= y0) & (np.minimum(ay, by) <= y1))
        idx = np.nonzero(todo)[0]
        if not len(idx):
            return hit
        sax, say, sbx, sby = ax[idx], ay[idx], bx[idx], by[idx]
        got = np.zeros(len(idx), dtype=bool)
        for px, py, qx, qy in zip(self.px, self.py, self.qx, self.qy):
            d1 = (qx - px) * (say - py) - (qy - py) * (sax - px)
            d2 = (qx - px) * (sby - py) - (qy - py) * (sbx - px)
            d3 = (sbx - sax) * (py - say) - (sby - say) * (px - sax)
            d4 = (sbx - sax) * (qy - say) - (sby - say) * (qx - sax)
            got |= (d1 * d2 < 0) & (d3 * d4 < 0)
        hit[idx] = got
        return hit

    def seg_mask(self, ax, ay, bx, by, ok, crossing):
        in_a = self.inside_mask(ax, ay, ok)
        in_b = self.inside_mask(bx, by, ok)
        if not crossing:
            both = in_a & in_b
            if self.convex or not both.any():
                return both
            return both & ~self._cross_mask(ax, ay, bx, by, both)
        cross = in_a | in_b
        todo = ok & ~cross
        if todo.any():
            cross |= self._cross_mask(ax, ay, bx, by, todo)
        return cross


def as_region(rect) -> _Region:
    """The region a box test reads: a region as it is, a rectangle tuple
    as the classic box."""
    return rect if isinstance(rect, _Region) else _RectRegion(rect)


def _box_loose_fast(viewport, rect, crossing):
    """Vectorized box select over the loose mesh: edges via the cached
    screen projection, faces derived from their boundary edges. Returns
    (edges, faces) or None to fall back to the per-entity walk (stub
    viewports in tests, or a viewport without the caches)."""
    if (getattr(viewport, "_ledge_screen", None) is None
            or getattr(viewport, "_pick_index", None) is None):
        return None
    try:
        proj = viewport._ledge_screen()
        idx = viewport._pick_index()
    except Exception:  # noqa: BLE001 — any stub oddity: python path
        return None
    if proj is None or idx.edge_a is None:
        return None
    import numpy as np
    ax, ay, bx, by, ok = proj
    edges_all = idx.edges
    if len(edges_all) != len(ax):
        return None
    mask = as_region(rect).seg_mask(ax, ay, bx, by, ok, crossing)
    sel = viewport.scene.entity_selectable
    # What the context lets a click take. The index also carries the rest of
    # the model's loose edges (a reference while a group is open); those are
    # drawn faded and must not be caught by the box.
    pick_ok = getattr(idx, "edge_sel", None)
    hit_idx = np.where(mask)[0]
    if pick_ok is not None:
        hit_idx = hit_idx[pick_ok[hit_idx]]
    edges = [edges_all[int(i)] for i in hit_idx
             if sel(edges_all[int(i)])
             and not getattr(edges_all[int(i)], "hidden", False)]
    faces = []
    if crossing:
        seen = set()
        for i in hit_idx:
            for f in edges_all[int(i)].faces:
                if id(f) not in seen:
                    seen.add(id(f))
                    if sel(f):
                        faces.append(f)
    else:
        hit_ids = {id(edges_all[int(i)]) for i in hit_idx}
        face_edges: dict = {}
        for e in edges_all:
            for f in e.faces:
                face_edges.setdefault(id(f), []).append(e)
        for f in viewport.scene.faces:
            es = face_edges.get(id(f))
            if es and all(id(e) in hit_ids for e in es) and sel(f):
                faces.append(f)
    return edges, faces


# Bound temporary triangle/edge arrays and camera projections independently
# of the import's size (#1175). Even-sized batches keep edge pairs together.
_BOX_BATCH_POINTS = 8192


def _box_source(viewport, pg):
    """A placement's cached world chunk, or its prototype and lazy maps.

    An uncached instance must not materialize its entire transformed mesh
    just to answer a selection rectangle.
    """
    xf = getattr(pg, "xform", None)
    if xf is None or getattr(pg, "mesh", None) is None:
        return viewport._group_chunk(pg), None, None
    from views.viewport import _paint_of, _placed_maps, _proto_wrapper
    base = viewport._group_chunk(
        _proto_wrapper(viewport, pg.mesh, _paint_of(viewport, pg)))
    cur = (getattr(viewport, "_inst_chunks", None) or {}).get(id(pg))
    if cur is not None and cur["ikey"] == (base["uid"], tuple(xf.data())):
        return cur, None, None
    _L, tv, tp = _placed_maps(xf)
    return base, tv, tp


def _box_point_batches(ch, tv=None, tp=None):
    """Yield ``(points, paired_edges)`` in bounded batches, without writes.

    Match the renderer's term order: transform each triangle's origin and
    directions separately before adding them. Placed edge buffers round to
    float32, just as an instance chunk does.
    """
    import numpy as np
    v0, e1, e2 = ch["v0"], ch["e1"], ch["e2"]
    if v0 is not None:
        for i in range(0, len(v0), _BOX_BATCH_POINTS):
            sl = slice(i, i + _BOX_BATCH_POINTS)
            a = tp(v0[sl]) if tp is not None else v0[sl]
            yield a, False
            yield a + (tv(e1[sl]) if tv is not None else e1[sl]), False
            yield a + (tv(e2[sl]) if tv is not None else e2[sl]), False
    pair = np.frombuffer(ch["edges"], np.float32).reshape(-1, 3)
    for i in range(0, len(pair), _BOX_BATCH_POINTS):
        points = pair[i:i + _BOX_BATCH_POINTS].astype(np.float64)
        if tp is not None:
            points = tp(points).astype(np.float32).astype(np.float64)
        yield points, True


def _local_bounds(ch):
    """``(lo, hi)`` of everything the box test reads of chunk ``ch`` (the
    triangle corners and the edges), cached on it; None when empty."""
    import numpy as np
    import weakref
    # Keyed on the very arrays: a moved chunk gets new ones (a shift
    # rebuilds them), and stale bounds would answer for where it was.
    key = (ch["v0"], ch["e1"], ch["e2"], ch["edges"])
    hit = ch.get("_box_bounds")
    if (hit is not None and len(hit) == 3 and isinstance(hit[0], tuple)
            and hit[1] is key[3]
            and all((ref is None and array is None)
                    or (array is not None and ref is not None and ref() is array)
                    for ref, array in zip(hit[0], key[:3]))):
        return hit[2]
    lo = hi = None
    for points, _paired in _box_point_batches(ch):
        low, high = points.min(axis=0), points.max(axis=0)
        lo = low if lo is None else np.minimum(lo, low)
        hi = high if hi is None else np.maximum(hi, high)
    bounds = (lo, hi) if lo is not None else None
    # Do not retain obsolete triangle arrays after a chunk changes.
    refs = tuple(weakref.ref(a) if a is not None else None for a in key[:3])
    ch["_box_bounds"] = (refs, key[3], bounds)
    return bounds


def _placement_side(viewport, pg, rect):
    """``"in"`` when everything the box test reads of placement ``pg``
    projects inside ``rect``, ``"out"`` when all of it lies past one side
    of it, ``"empty"`` when it has nothing, None when that takes the full
    test. Decided on the eight
    corners of its bounding box, all in front of the camera: a projection
    keeps what is inside a box inside the hull of its corners."""
    import numpy as np
    xf = getattr(pg, "xform", None)
    if xf is None or getattr(pg, "mesh", None) is None:
        ch = viewport._group_chunk(pg)
        tp = None
    else:
        from views.viewport import _paint_of, _placed_maps, _proto_wrapper
        ch = viewport._group_chunk(
            _proto_wrapper(viewport, pg.mesh, _paint_of(viewport, pg)))
        tp = _placed_maps(xf)[2]
    bb = _local_bounds(ch)
    if bb is None:
        return "empty"
    lo, hi = bb
    box = np.array([[x, y, z] for x in (lo[0], hi[0])
                    for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    if tp is not None:
        box = tp(box)
    xs, ys, ok = viewport._project_px(box)
    if not ok.all():
        return None
    region = as_region(rect)
    x0, y0, x1, y1 = region.bbox
    # «In» trusts the hull of the corners: only a convex outline holds a
    # hull whose corners it holds (a lasso bent round a corner does not).
    if region.convex and region.inside_mask(xs, ys, ok).all():
        return "in"
    if (xs < x0).all() or (xs > x1).all() or (ys < y0).all() \
            or (ys > y1).all():
        return "out"
    return None


def _box_group_fast(viewport, group, rect, crossing):
    """Vectorized box test for one (non-billboard) group via its chunk
    arrays. True/False, or None to fall back to the per-vertex walk."""
    if (getattr(group, "billboard", False)
            or getattr(viewport, "_group_chunk", None) is None
            or getattr(viewport, "_project_px", None) is None):
        return None
    # A component's geometry lives in the placements it holds, each with its
    # own chunk: reading only the top-level one found an EMPTY array for an
    # imported component and dropped the whole test to the per-vertex Python
    # walk — 1.15M vertices for the hedge.
    expand = getattr(viewport, "_expand_placements", None)
    places = expand(group) if expand is not None else [group]
    region = as_region(rect)
    seen = False
    try:
        for pg in places:
            # A placement whose box lands wholly inside the rectangle, or
            # wholly past one of its sides, answers without its triangles:
            # on a model of 2 000 instances the corners of every triangle
            # carried to world and projected were most of a box's 5 s.
            side = _placement_side(viewport, pg, region)
            if side == "empty":
                continue
            seen = True
            if side == "out":
                if not crossing:
                    return False
                continue
            if side == "in":
                if crossing:
                    return True
                continue
            ch, tv, tp = _box_source(viewport, pg)
            for points, paired in _box_point_batches(ch, tv, tp):
                xs, ys, ok = viewport._project_px(points)
                inside = region.inside_mask(xs, ys, ok)
                if not crossing:
                    if not inside.all():
                        return False
                    # Every corner inside a bent lasso, an edge still
                    # running out past its bend.
                    if paired and not region.convex and not region.seg_mask(
                            xs[0::2], ys[0::2], xs[1::2], ys[1::2],
                            ok[0::2] & ok[1::2], False).all():
                        return False
                elif inside.any():
                    return True
                elif paired and region.seg_mask(
                        xs[0::2], ys[0::2], xs[1::2], ys[1::2],
                        ok[0::2] & ok[1::2], True).any():
                    return True
    except Exception:  # noqa: BLE001
        return None
    return (not crossing) if seen else None


def _frame_projector(viewport):
    """``viewport._world_to_pixel`` with this frame's projection*view built
    once: the box walks every vertex of the groups it cannot test from
    their chunks (face-me figures), and rebuilding the camera matrices for
    each point cost ~1.6 s of a 3 s box on the villa of issue #1006. Same
    math, same pixels."""
    w2p = viewport._world_to_pixel
    cam = getattr(viewport, "camera", None)
    try:
        import inspect
        if "mvp" not in inspect.signature(w2p).parameters:
            return w2p
        mvp = cam.projection_matrix() * cam.view_matrix()
    except (AttributeError, TypeError, ValueError):
        return w2p                      # a stand-in viewport (tests)
    return lambda point: w2p(point, mvp)


def _pt_in_rect(p, rect) -> bool:
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def _seg_seg_2d(p1, p2, p3, p4) -> bool:
    """Whether 2D segments ``p1-p2`` and ``p3-p4`` properly cross."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _seg_rect_overlap(a, b, rect) -> bool:
    """Whether segment ``a-b`` touches the rectangle (endpoint inside or an
    edge crossing) — the crossing-selection test."""
    if _pt_in_rect(a, rect) or _pt_in_rect(b, rect):
        return True
    x0, y0, x1, y1 = rect
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return any(_seg_seg_2d(a, b, corners[i], corners[(i + 1) % 4]) for i in range(4))


class SelectTool(Tool):
    name = "Select"
    shortcut = ""  # Space, bound in main_window; "S" is Scale
    description = (
        "Pick edges, faces and objects. Shift+click adds or takes away, "
        "Ctrl+click adds, Shift+Ctrl+click takes away; the same with a "
        "box.")
    uses_snap = False  # selecting picks geometry; no snap markers
    box_select = True   # supports the rubber-band window / crossing box

    def on_activate(self, viewport) -> None:
        pass

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)

    def _pick(self, viewport, screen_x: float, screen_y: float):
        """A group (picked as a unit) takes priority; then the edge under the
        cursor (screen-space priority), then a dimension annotation, then the
        front face."""
        pick_label = getattr(viewport, "pick_text_label", None)
        if pick_label is not None:
            # The text block overdraws all geometry, so a click on the glyphs
            # is unambiguous — it outranks every 3D pick. The label's thin
            # leader line keeps its normal (post-edge) priority below.
            label = pick_label(screen_x, screen_y, rect_only=True)
            if label is not None:
                return label
        group = viewport.pick_group(screen_x, screen_y)
        # Only an edge the user can SEE takes the click (issue #71): the
        # hidden seams of a smooth surface, or edges behind the model, left
        # a cylinder's side all but unclickable.
        pick_visible = getattr(viewport, "pick_visible_edge", None)
        edge = (pick_visible or viewport.pick_edge)(screen_x, screen_y)
        if group is not None and edge is not None:
            # A loose line drawn ON a group's face (or crossing in front of
            # it) is the deliberate target — the thin edge is picked
            # before the object behind it. Only a VISIBLE edge wins: one
            # hidden behind the group's faces leaves the group as the pick.
            point = getattr(viewport, "edge_point_under_cursor", None)
            occluded = getattr(viewport, "_is_occluded", None)
            if point is not None and occluded is not None:
                p = point(edge, screen_x, screen_y)
                if p is not None and not occluded(p):
                    return edge
        if group is not None:
            return group
        if edge is not None:
            return edge
        dim = viewport.pick_dimension(screen_x, screen_y)
        if dim is not None:
            return dim
        pick_label = getattr(viewport, "pick_text_label", None)
        label = pick_label(screen_x, screen_y) if pick_label else None
        if label is not None:
            return label
        path = viewport.pick_geopath(screen_x, screen_y)
        if path is not None:
            return path
        # Section planes pick by their frame, above guides.
        pick_sec = getattr(viewport, "pick_section_plane", None)
        sec = pick_sec(screen_x, screen_y) if pick_sec else None
        if sec is not None:
            return sec
        # The section box picks by its edges, like a plane by its frame.
        pick_box = getattr(viewport, "pick_section_box", None)
        box = pick_box(screen_x, screen_y) if pick_box else None
        if box is not None:
            return box
        # Guides select the usual way (click + Delete / right-click). Real
        # geometry outranks them; a guide crossing a face still beats the face
        # (a thin line is the more deliberate target).
        pick_guide = getattr(viewport, "pick_guide", None)
        guide = pick_guide(screen_x, screen_y) if pick_guide else None
        if guide is not None:
            return guide
        face = viewport.pick_face(screen_x, screen_y)
        if face is not None:
            # Unless a picture lies in front of it (#426).
            in_front = getattr(viewport, "image_in_front_of", None)
            image = in_front(face, screen_x, screen_y) if in_front else None
            return image if image is not None else face
        # A reference image is the last candidate: it is an underlay, so
        # anything drawn on top of it must win the click. Only bare picture
        # selects the picture — which is how you then move or resize it.
        pick_image = getattr(viewport, "pick_image_plane", None)
        return pick_image(screen_x, screen_y) if pick_image else None

    def on_press_grab(self, ctx: ToolContext) -> bool:
        """The viewport asks before a press turns into a rubber band: a
        press on an arrow of the SELECTED section box picks up the Section
        Box tool and starts sliding that face — the arrows are there to be
        pulled. True if it took the press."""
        viewport = ctx.viewport
        shown = getattr(viewport, "_section_boxes_shown", None)
        if shown is None:
            return False
        from tools.section_box import pick_arrow
        box = face = None
        for b in shown():
            if b in viewport.scene.selection:
                face = pick_arrow(viewport, b, ctx.screen.x(), ctx.screen.y())
                if face is not None:
                    box = b
                    break
        if box is None:
            return False
        # The tool works on the box that cuts: this one, from now on.
        viewport.scene.select([box])
        window = viewport.window() if hasattr(viewport, "window") else None
        activate = getattr(window, "_activate_tool", None)
        if not callable(activate):
            return False
        activate("section_box")
        tool = viewport.active_tool
        begin = getattr(tool, "begin_drag", None)
        if callable(begin):
            begin(viewport, face, ctx.screen.x(), ctx.screen.y())
        return True

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        mode = selection_mode(ctx.modifiers)
        # An extension's item (a render light) is drawn over the model, so
        # a click on it outranks the geometry behind (issue #205).
        pick_item = getattr(viewport, "pick_extension_item", None)
        hit = (pick_item(ctx.screen.x(), ctx.screen.y())
               if pick_item is not None else None)
        if hit is not None:
            viewport.scene.clear_selection()
            viewport.set_extension_pick(hit)
            return
        if getattr(viewport, "extension_pick", None) is not None:
            viewport.clear_extension_pick()
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        if entity is None:
            if viewport.scene.edit_group is not None and mode == "replace" \
                    and not viewport.scene.selection:
                # The dotted edit box, not the occupied faces, is the context
                # boundary. Irregular geometry and the deliberate gutter
                # around a cube leave empty pixels INSIDE that frame; those
                # pixels must not throw the user out of the group. Beyond the
                # projected box, step out ONE level so a nested edit leaves
                # you in its parent, not directly in the model.
                contains = getattr(viewport,
                                   "edit_group_box_contains_pixel", None)
                if not callable(contains) or not contains(
                        ctx.screen.x(), ctx.screen.y()):
                    viewport.end_one_group_edit()
                    return
            if mode == "replace":
                viewport.scene.clear_selection()
        else:
            picked = self._expand(viewport, entity)
            viewport.scene.select(picked, mode=mode)
        viewport.update()

    @staticmethod
    def _expand(viewport, entity):
        """Grow a pick to its natural whole: a curved surface (faces joined by
        soft edges) for a face, or the whole drawn curve (circle/arc) for one of
        its segments — the classic behaviour. Plain entities select alone.

        With Camera ▸ Hidden Geometry on, the soft edges show and a face of
        a curved surface selects alone, so one facet of a cylinder's side
        can be picked, pushed or painted on its own (#831)."""
        if isinstance(entity, Face):
            if getattr(viewport.scene, "show_hidden_geometry", False):
                return [entity]
            return viewport.scene.mesh.surface_of(entity)
        if isinstance(entity, Edge) and getattr(entity, "curve", None) is not None:
            return viewport.scene.mesh.curve_edges(entity)
        return [entity]

    def on_double_click(self, ctx: ToolContext) -> None:
        """Double click: a face selects itself plus its bounding
        edges; an edge selects itself plus its faces — and a GROUP opens for
        editing (Groups v2: draw, push, erase inside it)."""
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        if isinstance(entity, Group):
            # A 3D text too: double-click ENTERS it, as users expect (its
            # letters are groups); re-editing the text is the right-click's
            # «Edit 3D Text…» (Marco, 2026-09-18).
            viewport.begin_group_edit(entity)
            return
        if isinstance(entity, SectionBox):
            # Double-clicking the section box takes up its tool: its faces
            # and arrows to drag.
            window = viewport.window() if hasattr(viewport, "window") \
                else None
            activate = getattr(window, "_activate_tool", None)
            if callable(activate):
                activate("section_box")
            return
        if isinstance(entity, SectionPlane):
            # Double-clicking a section plane toggles the active cut.
            viewport.history.execute(SetActiveSectionCommand(
                None if entity.active else entity))
            viewport.scene.select([entity])
            viewport.update()
            return
        if isinstance(entity, TextLabel):
            # As usual, double-clicking a leader text edits its text.
            from core.i18n import tr
            from views.prompts import get_multiline_text
            text, ok = get_multiline_text(
                viewport.window(), tr("Text"), tr("Label text:"),
                entity.text)
            if ok and text.strip() and text.strip() != entity.text:
                viewport.history.execute(
                    EditTextLabelCommand(entity, text.strip()))
            viewport.update()
            return
        if isinstance(entity, Dimension):
            # Double-clicking the dimension text edits it; "<>"
            # stands for the measured value, and an empty text (or a bare
            # "<>") goes back to the automatic value.
            from PySide6.QtWidgets import QInputDialog
            from core.i18n import tr
            from core.history import EditDimensionTextCommand
            fmt = getattr(viewport, "_format_dim_value", None)
            style = getattr(viewport.scene, "dimension_style", {}) or {}
            measured = (fmt(entity.value(), style) if fmt is not None
                        else entity.label())
            current = entity.text if entity.text else measured
            text, ok = _prompts.get_text(
                viewport.window(), tr("Dimension"),
                tr("Dimension text (<> = measured value):"), text=current)
            if ok:
                new = text.strip()
                if new in ("", "<>", measured):
                    new = None
                if new != entity.text:
                    viewport.history.execute(
                        EditDimensionTextCommand(entity, new))
            viewport.update()
            return
        if not isinstance(entity, (Face, Edge)):
            self.on_click(ctx)
            return
        mesh = viewport.scene.mesh
        picked = list(self._expand(viewport, entity))
        if isinstance(entity, Face):
            for f in list(picked):
                if not isinstance(f, Face):
                    continue
                for lp in (f.loop, *f.hole_loops):
                    n = len(lp)
                    for i in range(n):
                        e = mesh.find_edge(lp[i], lp[(i + 1) % n])
                        if e is not None:
                            picked.append(e)
        else:
            for e in list(picked):
                if isinstance(e, Edge):
                    picked.extend(e.faces)
        viewport.scene.select(picked, mode=selection_mode(ctx.modifiers))
        viewport.update()

    def on_triple_click(self, ctx: ToolContext) -> None:
        """Triple click: everything physically connected to the
        picked entity (the whole solid), walked through shared vertices."""
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        if not isinstance(entity, (Face, Edge)):
            self.on_click(ctx)
            return
        from core.select_ops import all_connected
        viewport.scene.select(all_connected([entity]),
                              mode=selection_mode(ctx.modifiers))
        viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        # A face under the cursor is not marked (#832:
        # «very visually distracting»); edges still light up, thin lines
        # being hard to hit. Unmarked, a face is also never what Delete
        # erases with nothing selected.
        viewport.set_hover(None if isinstance(entity, Face) else entity)

    def on_box_select(self, viewport, rect, crossing: bool,
                      additive: bool = False, mode: str | None = None) -> None:
        region = as_region(rect)
        w2p = _frame_projector(viewport)
        picked = []
        fast = _box_loose_fast(viewport, region, crossing)
        if fast is not None:
            picked.extend(fast[0])
            picked.extend(fast[1])
        loose_iter = ((), ()) if fast is not None else (
            viewport.scene.edges, viewport.scene.faces)
        for edge in loose_iter[0]:
            if not viewport.scene.entity_selectable(edge):
                continue                        # hidden or locked layer
            pa = w2p(edge.a)
            pb = w2p(edge.b)
            if pa is None or pb is None:
                continue
            if crossing:
                if region.touches(pa, pb):
                    picked.append(edge)
            elif region.encloses(pa, pb):
                picked.append(edge)
        for face in loose_iter[1]:
            if not viewport.scene.entity_selectable(face):
                continue                        # hidden or locked layer
            pts = [w2p(v) for v in face.vertices]
            if any(p is None for p in pts):
                continue
            if crossing:
                n = len(pts)
                touches = any(region.contains(p) for p in pts) or any(
                    region.touches(pts[i], pts[(i + 1) % n]) for i in range(n)
                )
                if touches:
                    picked.append(face)
            elif all(region.encloses(pts[i], pts[(i + 1) % len(pts)])
                     for i in range(len(pts))):
                picked.append(face)
        # Groups and component instances (the "box select skips groups"
        # report). Window mode: every vertex inside. Crossing mode: any vertex
        # inside, else any wireframe edge touching the box. Early exits keep
        # the common reject cheap. Inside a group the box works on what the
        # open group holds: its loose geometry above, and its
        # CHILDREN here — the parts of an imported fountain are groups, and
        # a box that skipped them could never take the whole fountain
        # («quiero seleccionar toda esa pileta, no selecciona», Marco,
        # 2026-09-11).
        ctx = viewport.scene.edit_group
        candidates = (getattr(viewport.scene, "groups", []) if ctx is None
                      else (getattr(ctx, "children", None) or []))
        if candidates:
            for group in candidates:
                if not viewport.scene.entity_selectable(group):
                    continue
                verdict = _box_group_fast(viewport, group, rect, crossing)
                if verdict is not None:
                    if verdict:
                        picked.append(group)
                    continue
                # A component's geometry lives in the placements it holds,
                # so the box has to test the whole subtree — the top-level
                # mesh of an imported component is often empty, and reading
                # only that made it unselectable by rubber band.
                from core.group import iter_placements
                places = [(pg, xf) for pg, xf in iter_placements(group)
                          if pg.mesh.vertices]
                if not places:
                    continue

                def gw2p(point, xf):
                    return w2p(xf.map(point) if xf is not None else point)

                if crossing:
                    hit = False
                    for pg, xf in places:
                        for v in pg.mesh.vertices:
                            p = gw2p(v.position, xf)
                            if p is not None and region.contains(p):
                                hit = True
                                break
                        if hit:
                            break
                    if not hit:
                        for pg, xf in places:
                            for e in pg.mesh.edges:
                                pa, pb = gw2p(e.a, xf), gw2p(e.b, xf)
                                if (pa is not None and pb is not None
                                        and region.touches(pa, pb)):
                                    hit = True
                                    break
                            if hit:
                                break
                    if hit:
                        picked.append(group)
                else:
                    inside = True
                    for pg, xf in places:
                        for v in pg.mesh.vertices:
                            p = gw2p(v.position, xf)
                            if p is None or not region.contains(p):
                                inside = False
                                break
                        if not inside:
                            break
                    if inside and not region.convex:
                        # A bent lasso: an edge may still run out past it.
                        for pg, xf in places:
                            for e in pg.mesh.edges:
                                pa, pb = gw2p(e.a, xf), gw2p(e.b, xf)
                                if (pa is None or pb is None
                                        or not region.encloses(pa, pb)):
                                    inside = False
                                    break
                            if not inside:
                                break
                    if inside:
                        picked.append(group)
        # Guides: an infinite line can never be fully enclosed, so a window
        # box skips it and only a crossing box takes it. Guide
        # points behave like any point. The line is clipped to the part in
        # front of the camera before projecting (as render/snap do).
        for g in getattr(viewport.scene, "guides", []):
            if not viewport.scene.entity_selectable(g):
                continue
            if g.is_line:
                if not crossing:
                    continue
                clip = getattr(viewport, "_clip_segment_front", None)
                seg = clip(*g.segment()) if clip else g.segment()
                if seg is None:
                    continue
                pa, pb = w2p(seg[0]), w2p(seg[1])
                if (pa is not None and pb is not None
                        and region.touches(pa, pb)):
                    picked.append(g)
            elif getattr(g, "is_circle", False):
                # A finite circle: a window box takes it whole, a crossing
                # box takes it when its rim passes through.
                rim = [w2p(p) for p in g.sample_points(24)]
                if any(p is None for p in rim):
                    continue
                if crossing:
                    if any(region.contains(p) for p in rim):
                        picked.append(g)
                elif all(region.contains(p) for p in rim):
                    picked.append(g)
            else:
                p = w2p(g.point)
                if p is not None and region.contains(p):
                    picked.append(g)
        selectable = getattr(viewport.scene, "entity_selectable",
                             lambda _e: True)
        for dim in getattr(viewport.scene, "dimensions", []):
            if not selectable(dim):
                continue
            ap, bp = dim.line_points()
            pa, pb = w2p(ap), w2p(bp)
            if pa is None or pb is None:
                continue
            if crossing:
                if region.touches(pa, pb):
                    picked.append(dim)
            elif region.encloses(pa, pb):
                picked.append(dim)
        for lab in getattr(viewport.scene, "text_labels", []):
            if not selectable(lab):
                continue
            pa, pp = w2p(lab.anchor), w2p(lab.position())
            if pp is None:
                continue
            if crossing:
                if region.contains(pp) or (
                        pa is not None and region.touches(pa, pp)):
                    picked.append(lab)
            elif region.contains(pp) and (
                    pa is None or region.encloses(pa, pp)):
                picked.append(lab)
        if mode == "replace" and getattr(viewport, "extension_pick",
                                         None) is not None:
            viewport.clear_extension_pick()
        viewport.scene.select(picked, additive=additive, mode=mode)
        viewport.update()

    def on_key(self, viewport, key: int, modifiers: Qt.KeyboardModifiers) -> bool:
        if key == Qt.Key_Delete:
            delete_selection_or_hover(viewport)
            return True
        if key == Qt.Key_Backspace:
            # The selection only, never the hover: with the typed value
            # emptied, one Backspace too many lands here and must not erase
            # the face under the cursor.
            erase_entities(viewport, list(viewport.scene.selection))
            return True
        return False

    def on_lasso_select(self, viewport, points, crossing: bool,
                        additive: bool = False,
                        mode: str | None = None) -> None:
        """A closed outline released: take what it holds (``crossing``
        False) or what it touches (True), joined to the selection by
        ``mode`` as a box would be."""
        try:
            region = LassoRegion(points)
        except ValueError:
            return
        self.on_box_select(viewport, region, crossing, additive, mode=mode)


class LassoSelectTool(SelectTool):
    """Lasso: select with an outline drawn around what to take.

    Drag to draw it freehand; it closes when the button comes up. Or click
    corner after corner and close it with a double-click, Enter, or a
    click back on the first corner — a drag between clicks draws that
    stretch freehand. Drawn clockwise it takes what lies wholly inside
    (blue, like a box dragged to the right); anticlockwise, whatever it
    touches (green and dashed, like a box dragged to the left). Shift,
    Ctrl and Shift+Ctrl join the catch to the selection as with the box.
    Backspace takes back the last corner, Esc drops the outline."""

    name = "Lasso Select"
    icon = "lasso"
    shortcut = "Shift+Space"
    description = (
        "Select with an outline: drag around what to take, or click its "
        "corners and close with a double-click or Enter. Clockwise takes "
        "what is inside, anticlockwise what it touches.")
    box_select = False          # the press is the lasso's own (on_screen_*)

    #: Below this travel a press and release are a click: a corner.
    DRAG_PX = 4.0
    #: A freehand stroke keeps a point every this many pixels.
    STEP_PX = 3.0
    #: A click this close to the first corner closes the outline.
    CLOSE_PX = 8.0

    def __init__(self) -> None:
        super().__init__()
        self._reset()

    def _reset(self) -> None:
        self.nodes: list = []       # the outline's corners so far (pixels)
        self._stroke = None         # the stretch being dragged, or None
        self._press = None
        self._cursor = None

    # ---- Lifecycle ------------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        super().on_deactivate(viewport)

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        # A click here sets a corner; it picks nothing to highlight.
        ctx.viewport.set_hover(None)

    # ---- The outline ----------------------------------------------------------
    def outline(self) -> list:
        """The corners drawn so far, the stroke being dragged included."""
        pts = list(self.nodes)
        if self._stroke:
            pts.extend(self._stroke)
        return pts

    def on_screen_press(self, viewport, pos) -> bool:
        self._press = (float(pos.x()), float(pos.y()))
        self._stroke = None
        return True

    def on_screen_drag(self, viewport, pos) -> None:
        if self._press is None:
            return
        p = (float(pos.x()), float(pos.y()))
        self._cursor = p
        if self._stroke is None:
            if math.hypot(p[0] - self._press[0],
                          p[1] - self._press[1]) < self.DRAG_PX:
                return
            self._stroke = [self._press]
        last = self._stroke[-1]
        if math.hypot(p[0] - last[0], p[1] - last[1]) >= self.STEP_PX:
            self._stroke.append(p)

    def on_screen_release(self, viewport, pos) -> None:
        press, stroke = self._press, self._stroke
        self._press = None
        self._stroke = None
        if press is None:
            return
        p = (float(pos.x()), float(pos.y()))
        if stroke is not None:
            stroke.append(p)
            if not self.nodes:
                # One drag, start to finish: a freehand lasso.
                self.nodes = stroke
                self.finish(viewport)
                return
            self.nodes.extend(stroke)        # a freehand stretch, then on
            viewport.update()
            return
        if (len(self.nodes) >= 3 and math.hypot(
                press[0] - self.nodes[0][0],
                press[1] - self.nodes[0][1]) <= self.CLOSE_PX):
            self.finish(viewport)
            return
        self.nodes.append(press)
        viewport.update()

    def on_screen_hover(self, viewport, pos) -> bool:
        self._cursor = (float(pos.x()), float(pos.y()))
        if self.nodes:
            viewport.update()            # the rubber line follows the cursor
        return False

    def on_double_click(self, ctx: ToolContext) -> None:
        # The first click of the pair already set the last corner.
        if len(self.nodes) >= 3:
            self.finish(ctx.viewport)
            return
        # Not an outline yet: a double-click opens a group, as in Select.
        self._reset()
        super().on_double_click(ctx)

    def on_triple_click(self, ctx: ToolContext) -> None:
        self._reset()
        super().on_triple_click(ctx)

    def on_click(self, ctx: ToolContext) -> None:
        pass                             # the corners come from on_screen_*

    def on_key(self, viewport, key: int, modifiers: Qt.KeyboardModifiers) -> bool:
        if self.nodes:
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.finish(viewport)
                return True
            if key == Qt.Key_Backspace:
                self.nodes.pop()
                viewport.update()
                return True
        return super().on_key(viewport, key, modifiers)

    def crossing(self, points=None) -> bool:
        """Anticlockwise on the screen: a crossing lasso."""
        pts = self.outline() if points is None else points
        return outline_area(pts) < 0

    def finish(self, viewport, modifiers=None) -> bool:
        """Close the outline and select with it. False when it encloses
        nothing worth the name (fewer than three corners, no area)."""
        pts = self.outline()
        self._reset()
        if len(pts) < 3 or abs(outline_area(pts)) < 1.0:
            viewport.update()
            return False
        if modifiers is None:
            from PySide6.QtWidgets import QApplication
            modifiers = QApplication.keyboardModifiers()
        mode = selection_mode(modifiers)
        self.on_lasso_select(viewport, pts, self.crossing(pts),
                             mode != "replace", mode=mode)
        viewport.update()
        return True

    # ---- Drawing --------------------------------------------------------------
    def draw_overlay(self, viewport, painter) -> None:
        pts = self.outline()
        if self.nodes and self._stroke is None and self._cursor is not None:
            pts.append(self._cursor)
        if len(pts) < 2:
            return
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
        crossing = len(pts) >= 3 and self.crossing(pts)
        if crossing:
            pen = QPen(QColor(40, 158, 92), 1.5, Qt.DashLine)
            fill = QColor(40, 158, 92, 28)
        else:
            pen = QPen(QColor(51, 102, 199), 1.5, Qt.SolidLine)
            fill = QColor(51, 102, 199, 28)
        poly = QPolygonF([QPointF(x, y) for x, y in pts])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawPolygon(poly)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(poly)
        # The closing side, faint: where the outline will shut.
        faint = QPen(pen)
        c = pen.color()
        faint.setColor(QColor(c.red(), c.green(), c.blue(), 110))
        faint.setStyle(Qt.DotLine)
        painter.setPen(faint)
        painter.drawLine(poly[poly.size() - 1], poly[0])
        if self.nodes and self._stroke is None:
            # The first corner: click it to close.
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            x, y = self.nodes[0]
            painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        painter.restore()


# ---- Delete: the selection, or what is under the cursor ------------------------

def expand_pick(viewport, entity) -> list:
    """What a click on ``entity`` would select (see ``SelectTool._expand``)."""
    return SelectTool._expand(viewport, entity)


def erase_entities(viewport, entities) -> bool:
    """Erase ``entities`` (any mix of pickable types) as ONE undoable step.
    True if anything was erased."""
    edges = [e for e in entities if isinstance(e, Edge)]
    faces = [f for f in entities if isinstance(f, Face)]
    groups = [g for g in entities if isinstance(g, Group)]
    dims = [d for d in entities if isinstance(d, Dimension)]
    labels = [t for t in entities if isinstance(t, TextLabel)]
    paths = [p for p in entities if isinstance(p, GeoPath)]
    guides = [g for g in entities if is_guide(g)]
    splanes = [p for p in entities if isinstance(p, SectionPlane)]
    boxes = [b for b in entities if isinstance(b, SectionBox)]
    commands = []
    if edges or faces:
        # Erasing an edge between two coplanar faces merges them back
        # into one (as usual); any other erased edge takes its faces.
        commands.append(EraseSelectionCommand(edges, faces))
    commands.extend(DeleteGroupCommand(g) for g in groups)
    if guides:
        commands.append(DeleteGuidesCommand(guides))
    if splanes:
        commands.append(DeleteSectionPlanesCommand(splanes))
    if boxes:
        commands.append(section_boxes_removed(viewport.scene, boxes))
    if dims:
        commands.append(DeleteDimensionsCommand(dims))
    if labels:
        commands.append(DeleteTextLabelsCommand(labels))
    if paths:
        commands.append(DeleteGeoPathsCommand(paths))
    if not commands:
        return False
    cmd = commands[0] if len(commands) == 1 else CompoundCommand(commands)
    viewport.history.execute(cmd)
    viewport.update()
    return True


def delete_selection_or_hover(viewport) -> bool:
    """The Delete key: erase the selection; with NOTHING selected, erase
    what is highlighted under the cursor — hover an edge or a face and press
    Supr, no click needed. The hover grows like a click would (a whole
    circle, a whole smooth surface), so what goes is what a click-then-Supr
    would have erased. True if anything was erased."""
    if getattr(viewport, "extension_pick", None) is not None:
        return viewport.delete_extension_pick()      # a render light, say
    selection = list(viewport.scene.selection)
    if selection:
        return erase_entities(viewport, selection)
    hovered = getattr(viewport, "_hover_entity", None)
    if hovered is None:
        return False
    viewport.set_hover(None)        # it is about to be gone
    return erase_entities(viewport, expand_pick(viewport, hovered))
