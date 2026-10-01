# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Snap engine: pick the best snap target near the cursor.

Snap kinds (priority high → low):
1. ``"axis"``           — explicit axis lock from arrow keys.
2. ``"reference"``      — parallel/perpendicular lock to a reference edge.
3. ``"axis"`` via Shift — Shift held while an axis inference is active.
4. ``"close"``          — closing the current polygon chain.
5. ``"endpoint"``       — vertex of an existing edge.
6. ``"intersection"``   — where two edges / guide lines actually cross (green X).
7. ``"midpoint"``       — midpoint of an existing edge.
8. ``"origin"``         — world origin.
9. ``"on_edge"``        — arbitrary point along an edge (start a shape on it).
10. ``"aligned"``       — level with / in line with an encouraged point across
                          the face under the cursor (the axis plane through it).
11. ``"axis_inference"`` — soft auto-detected axis alignment (visual cue only).
12. ``"none"``          — no snap.

Distance checks for point snaps are done in **screen-space pixels** so the
snap radius stays constant under zoom. The caller supplies a
``world_to_pixel`` callback so this module does not depend on Qt's
viewport directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtGui import QVector3D


# Colors used by the rubber band and the 2D snap indicator. RGB floats [0, 1].
COLOR_ENDPOINT = (0.16, 0.62, 0.36)
COLOR_MIDPOINT = (0.20, 0.66, 0.74)  # cyan — midpoint of an edge
COLOR_ON_EDGE = (0.86, 0.22, 0.27)   # red — arbitrary point on an edge
COLOR_ON_FACE = (0.42, 0.46, 0.92)   # blue/violet — point on a face
COLOR_ORIGIN = (0.95, 0.45, 0.16)
COLOR_CLOSE = (0.20, 0.40, 0.78)
COLOR_AXIS_X = (0.86, 0.22, 0.27)
COLOR_AXIS_Y = (0.16, 0.62, 0.36)
COLOR_AXIS_Z = (0.20, 0.40, 0.78)
COLOR_REFERENCE = (0.85, 0.30, 0.80)  # magenta — parallel / perpendicular
COLOR_EXTENSION = (0.55, 0.55, 0.58)  # grey — collinear extension of an edge
COLOR_IN_GROUP = (0.85, 0.30, 0.80)   # magenta — a point inside a group / component
COLOR_TANGENT = (0.20, 0.66, 0.74)    # cyan — an arc tangent to the arc it starts from
COLOR_NONE = (0.0, 0.0, 0.0)

AXIS_COLORS = {
    "x": COLOR_AXIS_X,
    "y": COLOR_AXIS_Y,
    "z": COLOR_AXIS_Z,
}

AXIS_NAMES = {"x": "X", "y": "Y", "z": "Z"}


@dataclass
class SnapResult:
    point: QVector3D
    kind: str
    color: tuple[float, float, float] = COLOR_NONE
    axis: Optional[str] = None  # "x" / "y" / "z" when kind is "axis" or "axis_inference"
    # Two world points defining a dashed guide line to draw (the extension
    # inference shows the dashed continuation of the edge to the cursor).
    guide: Optional[tuple] = None
    # Colour for the dashed guide line when it should differ from the marker
    # colour (e.g. 'from point' draws an axis-coloured guide but a green point).
    guide_color: Optional[tuple[float, float, float]] = None
    # Extra dashed guides, ``[(a, b, rgb), ...]`` — the two-point 'from point'
    # draws one from each encouraged point.
    guides: Optional[list] = None
    # ``"group"`` / ``"component"`` when the point belongs to one — the
    # ScreenTip adds "in group" / "in component".
    context: Optional[str] = None
    #: The ScreenTip's own words, already translated — what an extension's
    #: inference says («Level PA»); wins over the kind's built-in label.
    label: Optional[str] = None


# ---- Helpers ---------------------------------------------------------------

def project_to_view_plane(point: QVector3D, ref: QVector3D,
                          forward: QVector3D, threshold: float = 0.97):
    """Project *point* onto the plane through *ref* facing the camera, when
    the view is axis-aligned (a standard front/plan/side view).

    In a front elevation, a dimension should read the FRONTAL span — the
    height/width you see — not the true 3-D diagonal that a bit of depth
    between the two picked points would add. So the moving endpoint has its
    depth (the dominant view axis) pulled to the reference point's, keeping
    the measurement in the plane of the drawing. Oblique views return the
    point untouched (true 3-D distance, the classic behaviour).
    """
    if forward.length() < 1e-9:
        return point
    f = forward.normalized()
    from core import axes as _axes
    if not _axes.is_world():
        # Inside a turned group the standard views face ITS axes (#44).
        lf = _axes.to_local(f)
        comps = [(abs(lf.x()), "x"), (abs(lf.y()), "y"), (abs(lf.z()), "z")]
        best, name = max(comps)
        if best < threshold:
            return point
        a = _axes.AXES[name]
        return point + a * QVector3D.dotProduct(ref - point, a)
    ax, ay, az = abs(f.x()), abs(f.y()), abs(f.z())
    if max(ax, ay, az) < threshold:
        return point
    if ax >= ay and ax >= az:
        return QVector3D(ref.x(), point.y(), point.z())
    if ay >= az:
        return QVector3D(point.x(), ref.y(), point.z())
    return QVector3D(point.x(), point.y(), ref.z())


def first_point_work_plane(forward: QVector3D, scene_center: QVector3D,
                           threshold: float = 0.97):
    """Fallback work plane for a tool's FIRST point clicked in empty space.

    When the camera looks (near-)straight down a principal axis — a
    standard view (front / plan / side) — the natural plane to place an
    unsnapped point on is the one FACING the camera, through the model's
    centre, not the ground: dimensioning a front view must stay in the
    frontal plane instead of dropping the point to Z=0 at some arbitrary
    depth. Returns ``(point, normal)`` for such axis-aligned views, or
    ``None`` for oblique (orbit) views, where the caller keeps its usual
    ground/face behaviour so freehand modelling is unchanged.
    """
    if forward.length() < 1e-9:
        return None
    f = forward.normalized()
    from core import axes as _axes
    if not _axes.is_world():
        lf = _axes.to_local(f)
        comps = [(abs(lf.x()), "x"), (abs(lf.y()), "y"), (abs(lf.z()), "z")]
        best, name = max(comps)
        if best < threshold:
            return None
        a = _axes.axis(name)
        sign = 1.0 if QVector3D.dotProduct(f, a) > 0 else -1.0
        return scene_center, a * sign
    if max(abs(f.x()), abs(f.y()), abs(f.z())) < threshold:
        return None                     # oblique view — not axis-aligned
    # snap the normal to the exact dominant axis so the plane is clean
    if abs(f.x()) >= abs(f.y()) and abs(f.x()) >= abs(f.z()):
        normal = QVector3D(1.0 if f.x() > 0 else -1.0, 0.0, 0.0)
    elif abs(f.y()) >= abs(f.z()):
        normal = QVector3D(0.0, 1.0 if f.y() > 0 else -1.0, 0.0)
    else:
        normal = QVector3D(0.0, 0.0, 1.0 if f.z() > 0 else -1.0)
    return scene_center, normal


def face_plane_world(face, xform=None):
    """A face's plane as ``(point, normal)`` in WORLD coordinates.

    A component instance's face lives in its prototype's local frame, so
    its centroid and normal describe the copy at the origin — using them
    raw put the drawing plane of every instance in the wrong place (no
    reference on the far face of a placed slat: Marco, 2026-09-03). The
    normal is rebuilt from the mapped polygon, exact for any affine map."""
    if xform is None:
        return face.centroid(), face.normal()
    pts = [xform.map(QVector3D(v)) for v in face.vertices]
    n = len(pts)
    c = QVector3D(0.0, 0.0, 0.0)
    for p in pts:
        c += p
    c /= float(n)
    nx = ny = nz = 0.0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        nx += (a.y() - b.y()) * (a.z() + b.z())
        ny += (a.z() - b.z()) * (a.x() + b.x())
        nz += (a.x() - b.x()) * (a.y() + b.y())
    normal = QVector3D(nx, ny, nz)
    if normal.length() < 1e-12:
        return c, xform.mapVector(face.normal()).normalized()
    return c, normal.normalized()


def _detect_axis_alignment(
    start: QVector3D, candidate: QVector3D, angle_deg: float
) -> Optional[str]:
    """If the start→candidate direction is within ``angle_deg`` of an axis,
    return that axis as ``"x"``/``"y"``/``"z"``. Otherwise ``None``."""
    delta = candidate - start
    length = delta.length()
    if length < 1e-6:
        return None
    cos_thresh = math.cos(math.radians(angle_deg))
    from core import axes as _axes
    if not _axes.is_world():
        delta = _axes.to_local(delta)     # the context's own axes (#44)
    nx = abs(delta.x()) / length
    ny = abs(delta.y()) / length
    nz = abs(delta.z()) / length
    # Pick the strongest alignment if multiple pass.
    candidates = [(nx, "x"), (ny, "y"), (nz, "z")]
    candidates.sort(reverse=True)
    if candidates[0][0] >= cos_thresh:
        return candidates[0][1]
    return None


#: An axis whose screen projection is shorter than this is pointing at the
#: camera: its image is a dot, every cursor is "on" it, and the
#: perpendicular distance below means nothing. Skip it rather than let it
#: swallow the screen (looking straight down would glue everything to blue).
_MIN_AXIS_SCREEN_PX = 12.0

#: How far along an axis the resolved point may land, as a multiple of how
#: far the cursor itself is from the start. See the guard in ``compute_snap``.
_MAX_AXIS_REACH = 5.0


def _detect_axis_on_screen(
    start: QVector3D, candidate_world: QVector3D,
    candidate_pixel: tuple[float, float], world_to_pixel, threshold_px: float
) -> Optional[str]:
    """Which axis the cursor is sitting on, measured in PIXELS.

    The world-space detector above can only ever see the axes contained in
    the work plane, because that is where ``_world_from_pixel`` puts the
    candidate. Measured over the whole camera grid on 2026-09-18: every
    camera reaches exactly two axes and never three — x/y from the top,
    x/z from the front, y/z from the side. That is issue #31's second
    point, and it is geometry, not a threshold that needs widening.

    A straight line in the world projects to a straight line on screen, so
    two projected points give the axis's exact screen line and the question
    becomes the cursor's perpendicular distance to it. The reach is taken
    from how far the user is already drawing, which keeps the sampled point
    in the same region of the screen as the cursor.
    """
    reach = (candidate_world - start).length()
    if reach < 1e-6:
        return None
    sx, sy = world_to_pixel(start)
    cx, cy = candidate_pixel
    best: Optional[tuple[float, str]] = None
    for name in ("x", "y", "z"):
        ax, ay = world_to_pixel(start + _AXIS_VECTORS[name] * reach)
        dx, dy = ax - sx, ay - sy
        span = math.hypot(dx, dy)
        if span < _MIN_AXIS_SCREEN_PX:
            continue
        # Distance from the cursor to the INFINITE line: the axis runs both
        # ways from the start point, as the arrow lock does.
        dist = abs((cx - sx) * dy - (cy - sy) * dx) / span
        if dist <= threshold_px and (best is None or dist < best[0]):
            best = (dist, name)
    return best[1] if best else None


def _direction_from_edge(edge, mode: str,
                        plane_normal: Optional[QVector3D] = None
                        ) -> Optional[QVector3D]:
    """Return a unit-length direction for ``mode``.

    ``parallel``      → the edge's own direction.
    ``perpendicular`` → square to the edge, IN THE PLANE BEING DRAWN ON.

    The plane matters. Perpendicular used to be a flat 90° turn in XY,
    which is right on the ground and wrong everywhere else: on a ramp it
    locks the line to a horizontal direction that does not lie on the ramp,
    so drawing from one edge of the slope across to the other was pulled
    off the face by a magenta lock that could not be satisfied (Marco,
    2026-09-10). ``cross(plane_normal, edge)`` is the same thing on a
    horizontal plane — cross((0,0,1), (dx,dy,dz)) is (-dy, dx, 0), the old
    formula exactly — and the right thing on a tilted or vertical one.
    """
    direction = edge.b - edge.a
    if direction.length() < 1e-6:
        return None
    if mode == "perpendicular":
        from core.axes import AXES
        normal = plane_normal if plane_normal is not None else QVector3D(AXES["z"])
        perp = QVector3D.crossProduct(normal, direction)
        if perp.length() < 1e-9:
            return None          # the edge stands square to the plane
        return perp / perp.length()
    return direction.normalized()


# ---- Entry point ------------------------------------------------------------

# Type alias for the projection callback the viewport provides. Given the
# chain start point and a direction in world space, it returns the closest
# point on that infinite line to the camera ray that currently passes
# through the cursor pixel. This is what makes Z-axis locks usable (and
# X/Y locks correct when the start point is off the ground plane).
ProjectOntoLine = Callable[[QVector3D, QVector3D], QVector3D]


# Unit vectors for each world axis, used by the axis lock paths.
# The SAME dict as core.axes.AXES (updated in place): the world's axes at
# the top level, the open group's own inside it (issue #44).
from core.axes import AXES as _AXIS_VECTORS  # noqa: E402


def _closest_on_segment_2d(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    """Closest point on 2D segment ``ab`` to ``p``. Returns ``(distance, t)``
    where ``t`` in [0, 1] is the parameter along ``ab`` of that closest point."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx = bx - ax
    dy = by - ay
    denom = dx * dx + dy * dy
    if denom == 0.0:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.hypot(px - qx, py - qy), t


def _on_edge_point(edge, t: float,
                   project_onto_line: Optional[ProjectOntoLine]) -> QVector3D:
    """The point of ``edge`` under the cursor, given the screen parameter
    ``t`` from :func:`_closest_on_segment_2d`. Under perspective ``t`` is
    not the world parameter: on a long edge — a construction guide is tens
    of metres once clipped to the view — lerping it put the «hovered» point
    metres away and off screen, so a lock line could never take a guide's
    height (issue #166, @pacaeiro: Shift on the blue axis, hover the guide).
    Through the cursor ray instead, as rule 7 does, when the caller has it."""
    ab = edge.b - edge.a
    if project_onto_line is not None and ab.length() > 1e-9:
        proj = project_onto_line(edge.a, ab)
        if proj is not None:
            tt = QVector3D.dotProduct(proj - edge.a, ab) / QVector3D.dotProduct(ab, ab)
            return edge.a + ab * max(0.0, min(1.0, tt))
    return edge.a + ab * t


def _line_segment_intersection(
    p: QVector3D, u: QVector3D, a: QVector3D, b: QVector3D, tol: float = 1e-3
) -> Optional[QVector3D]:
    """Where the infinite line through ``p`` (unit direction ``u``) crosses the
    segment ``a``–``b``, or ``None`` if they're parallel, skew (closest approach
    > ``tol``), or the crossing falls outside the segment."""
    v = b - a
    if v.length() < 1e-9:
        return None
    w0 = p - a
    bb = QVector3D.dotProduct(u, v)
    cc = QVector3D.dotProduct(v, v)
    dd = QVector3D.dotProduct(u, w0)
    ee = QVector3D.dotProduct(v, w0)
    denom = cc - bb * bb  # u·u == 1 (u is unit)
    if abs(denom) < 1e-12:
        return None
    sc = (bb * ee - cc * dd) / denom
    tc = (ee - bb * dd) / denom
    if tc < -1e-6 or tc > 1.0 + 1e-6:
        return None
    on_line = p + u * sc
    on_seg = a + v * tc
    if (on_line - on_seg).length() > tol:
        return None  # skew — they don't actually meet
    return on_seg


def _point_on_segment_world(
    p: QVector3D, a: QVector3D, b: QVector3D, tol: float = 1e-3
) -> bool:
    """Whether ``p`` lies on segment ``a``–``b`` (within ``tol`` world units)."""
    ab = b - a
    length_sq = QVector3D.dotProduct(ab, ab)
    if length_sq < 1e-12:
        return (p - a).length() < tol
    t = QVector3D.dotProduct(p - a, ab) / length_sq
    if t < -1e-6 or t > 1.0 + 1e-6:
        return False
    return (p - (a + ab * t)).length() < tol


def fit_circle(points, tol_rel: float = 0.01):
    """The circle through ``points`` (world, coplanar): ``(centre, radius)``
    or ``None`` when they do not sit on one. Least squares in the points'
    own plane; every point must lie within ``tol_rel`` of the radius (or
    2 mm), so a polyline that merely bends never passes for an arc."""
    import numpy as np
    pts = np.array([[p.x(), p.y(), p.z()] for p in points], dtype=np.float64)
    if len(pts) < 3:
        return None
    c0 = pts.mean(axis=0)
    q = pts - c0
    # Plane basis: the two dominant directions of the point cloud.
    _w, v = np.linalg.eigh(q.T @ q)
    u, w = v[:, 2], v[:, 1]
    x, y = q @ u, q @ w
    a = np.c_[2.0 * x, 2.0 * y, np.ones(len(pts))]
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0], sol[1]
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0.0:
        return None
    r = float(math.sqrt(r2))
    dev = np.abs(np.hypot(x - cx, y - cy) - r)
    if dev.max() > max(0.002, tol_rel * r):
        return None
    c = c0 + u * cx + w * cy
    return QVector3D(float(c[0]), float(c[1]), float(c[2])), r


def _boundary_runs(loop) -> list:
    """Split a boundary loop into runs of consecutive segments that belong
    to one circle or arc, as ``[[vertex, ...], ...]`` (each run's vertices
    in order). A drawn curve says so with its ``curve`` id; an imported
    one usually only with ``soft`` segments; a bare polyline gives itself
    away by equal segments turning by a constant angle — the shape of every
    circle and arc a CAD program ever wrote."""
    n = len(loop)
    if n < 3:
        return []
    segs = []
    for i in range(n):
        v0, v1 = loop[i], loop[(i + 1) % n]
        edge = next((e for e in getattr(v0, "edges", ()) if e.other(v0) is v1),
                    None)
        cid = getattr(edge, "curve", None) if edge is not None else None
        soft = bool(getattr(edge, "soft", False)) if edge is not None else False
        segs.append((cid, soft))

    def turn(i):
        a = loop[i - 1].position if i > 0 else loop[n - 1].position
        b = loop[i].position
        c = loop[(i + 1) % n].position
        u, w = (b - a), (c - b)
        lu, lw = u.length(), w.length()
        if lu < 1e-9 or lw < 1e-9:
            return None, lu, lw
        cosang = max(-1.0, min(1.0, QVector3D.dotProduct(u, w) / (lu * lw)))
        return math.degrees(math.acos(cosang)), lu, lw

    # One key per segment: the curve id, else "soft", else the geometric
    # signature (turn at its start vertex, rounded), else None.
    keys: list = []
    for i in range(n):
        cid, soft = segs[i]
        if cid is not None:
            keys.append(("id", cid))
        elif soft:
            keys.append(("soft",))
        else:
            t, lu, lw = turn(i)
            tn, lu2, lw2 = turn((i + 1) % n)
            same = (t is not None and tn is not None and 2.0 < t < 60.0
                    and abs(t - tn) < 1.5
                    and abs(lu2 - lw) < 0.05 * max(lw, 1e-9))
            keys.append(("geo",) if same else None)
    # Runs of equal keys; "geo" and "soft" runs may wrap around the loop.
    runs: list = []
    if all(k is not None and k == keys[0] for k in keys):
        return [(list(loop), keys[0][0] == "id")]   # the whole loop is one curve
    # rotate so the loop does not start mid-run
    start = 0
    for j in range(n):
        if keys[j] != keys[j - 1]:
            start = j
            break
    order = [(start + j) % n for j in range(n)]
    cur: list = []
    cur_key = None
    for j in order:
        k = keys[j]
        if k is not None and k == cur_key:
            cur.append(j)
        else:
            if cur_key is not None and len(cur) >= 2:
                runs.append(cur)
            cur, cur_key = ([j] if k is not None else []), k
    if cur_key is not None and len(cur) >= 2:
        runs.append(cur)
    out = []
    for r in runs:
        verts = [loop[j] for j in r] + [loop[(r[-1] + 1) % n]]
        out.append((verts, keys[r[0]][0] == "id"))
    return out


def curve_centers_of_face(face, xform=None) -> list:
    """The *Center* inference: the centre of every circle or arc on
    the face's boundary — a circle face gives one, a rounded corner one
    per corner, a circular hole its own. ``[(centre, radius, key)]`` in
    world space (``xform`` places a component's face). ``key`` tells the
    arcs of one face apart.

    Drawn curves carry a ``curve`` id; imported ones usually only ``soft``
    segments; and a plain polyline is read by its shape (see
    :func:`_boundary_runs`) — the plaza's circle came from a file with
    neither."""
    out: list = []
    for li, loop in enumerate([face.loop]
                              + list(getattr(face, "hole_loops", []) or [])):
        for ri, (verts, drawn) in enumerate(_boundary_runs(loop)):
            # Three points always sit on SOME circle, and four often do
            # (every isosceles trapezoid of a revolved surface is cyclic):
            # a run read from its shape or its soft flags needs five to
            # mean anything. A drawn curve says what it is: three suffice.
            if len(verts) < (3 if drawn else 5):
                continue
            pts = [v.position for v in verts]
            if xform is not None:
                pts = [xform.map(QVector3D(p)) for p in pts]
            fit = fit_circle(pts)
            if fit is not None:
                out.append((fit[0], fit[1], (li, ri)))
    return out


def _vertex_on_line(
    vertex: QVector3D, line_start: QVector3D, line_dir: QVector3D, tol: float = 1e-4
) -> bool:
    """Whether ``vertex`` lies on the infinite line through ``line_start`` in
    ``line_dir`` (perpendicular distance below ``tol``)."""
    rel = vertex - line_start
    proj = QVector3D.dotProduct(rel, line_dir) * line_dir
    return (rel - proj).length() < tol


def _two_point_snap(
    refs, candidate, cx, cy, world_to_pixel, threshold_px, is_occluded=None,
) -> Optional[SnapResult]:
    """Where the axis lines through two encouraged points cross: for every
    pair of points and pair of DIFFERENT axes, the crossing (if the two
    lines meet — coplanar within a millimetre) within the snap radius of
    the cursor. Green point, one dotted guide from each point in its axis
    colour."""
    pts = [p for p in refs if p is not None]
    if len(pts) < 2:
        return None
    best = None
    axes = list(_AXIS_VECTORS.items())
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            p, q = pts[i], pts[j]
            for ka, a in axes:
                for kb, b in axes:
                    if ka == kb:
                        continue
                    # Closest points of the two lines p + a·s and q + b·t.
                    w = p - q
                    ab = QVector3D.dotProduct(a, b)
                    denom = 1.0 - ab * ab
                    if denom < 1e-9:
                        continue
                    wa = QVector3D.dotProduct(w, a)
                    wb = QVector3D.dotProduct(w, b)
                    s_ = (ab * wb - wa) / denom
                    t_ = (wb - ab * wa) / denom
                    pa = p + a * s_
                    pb = q + b * t_
                    if (pa - pb).length() > 1e-3:
                        continue                    # skew: no crossing
                    if abs(s_) < 1e-3 or abs(t_) < 1e-3:
                        continue                    # on a point itself
                    px = world_to_pixel(pa)
                    if px is None:
                        continue
                    d = math.hypot(px[0] - cx, px[1] - cy)
                    if d > threshold_px:
                        continue
                    if is_occluded is not None and is_occluded(pa):
                        continue
                    if best is None or d < best[0]:
                        best = (d, pa, p, ka, q, kb)
    if best is None:
        return None
    _, cross, p, ka, q, kb = best
    return SnapResult(cross, "from_point", COLOR_ENDPOINT,
                      guide=(QVector3D(p), cross), guide_color=AXIS_COLORS[ka],
                      guides=[(QVector3D(q), cross, AXIS_COLORS[kb])])


def _first_point_from_point(
    ref, candidate, cx, cy, world_to_pixel, threshold_px, is_occluded=None,
    plane_normal=None,
) -> Optional[SnapResult]:
    """The foot of the cursor on the axis line through ``ref`` (the last
    hovered corner), when the cursor sits within the snap radius of one of
    the three axis lines — a green 'from point' with the axis-coloured
    dotted guide back to the corner. Sitting ON the corner is the endpoint
    snap's job, not this one's.

    With ``plane_normal`` — the cursor is on a face, and ``candidate`` lies
    on that face's plane — the answer stays ON that plane: an axis line
    that pierces the plane offers its piercing point, one lying in the
    plane its foot as before, and one running parallel to the plane off
    it offers nothing. It used to hand back the foot on the line in the
    air, which is a point nowhere near the wall the cursor is pointing at
    and, for a rectangle started on that wall, a corner off its plane."""
    best = None
    n = None
    if plane_normal is not None and plane_normal.length() > 1e-9:
        n = plane_normal.normalized()
    for axis, a in _AXIS_VECTORS.items():
        an = QVector3D.dotProduct(a, n) if n is not None else 0.0
        if abs(an) < 1e-6:
            # The axis line runs parallel to the plane (or there is none):
            # its foot — which lies in the plane exactly when the line does.
            s = QVector3D.dotProduct(candidate - ref, a)
            if abs(s) < 1e-3:
                continue                    # that is ``ref`` itself
            if n is not None and abs(QVector3D.dotProduct(ref - candidate, n)) > 1e-4:
                continue                    # …and here it does not
            foot = ref + a * s
        else:
            # The line pierces the plane: the one point of it on the face.
            t = QVector3D.dotProduct(candidate - ref, n) / an
            if abs(t) < 1e-3:
                continue                    # that is ``ref`` itself
            foot = ref + a * t
        fp = world_to_pixel(foot)
        if fp is None:
            continue
        d = math.hypot(fp[0] - cx, fp[1] - cy)
        if d > threshold_px:
            continue
        if is_occluded is not None and is_occluded(foot):
            continue
        if best is None or d < best[0]:
            best = (d, foot, axis)
    if best is None:
        return None
    _, foot, axis = best
    return SnapResult(foot, "from_point", COLOR_ENDPOINT,
                      guide=(QVector3D(ref), foot),
                      guide_color=AXIS_COLORS[axis])


def _edge_from_point_crossing(
    edge, ref, cx, cy, world_to_pixel, threshold_px, is_occluded=None,
) -> Optional[SnapResult]:
    """Where an axis line through ``ref`` (the acquired point) crosses
    ``edge``, when that crossing is within the snap radius of the cursor —
    a green 'from point' on the edge with the axis-coloured guide back to
    ``ref``. ``None`` when no axis line meets the edge near the cursor."""
    best = None
    for axis, a in _AXIS_VECTORS.items():
        hit = _line_segment_intersection(ref, a, edge.a, edge.b)
        if hit is None or (hit - ref).length() < 1e-4:
            continue
        hp = world_to_pixel(hit)
        if hp is None:
            continue
        d = math.hypot(hp[0] - cx, hp[1] - cy)
        if d > threshold_px:
            continue
        if is_occluded is not None and is_occluded(hit):
            continue
        if best is None or d < best[0]:
            best = (d, hit, axis)
    if best is None:
        return None
    _, hit, axis = best
    return SnapResult(hit, "from_point", COLOR_ENDPOINT,
                      guide=(QVector3D(ref), hit),
                      guide_color=AXIS_COLORS[axis],
                      context=getattr(edge, "context", None))


def _in_plane_with_point_snap(
    ref, candidate, plane_normal, cx, cy, world_to_pixel, threshold_px,
    is_occluded=None,
) -> Optional[SnapResult]:
    """Level with — or in line with — an encouraged point ACROSS the face
    under the cursor: where the axis plane through ``ref`` (the horizontal
    plane at its height, or a vertical one through it) cuts the plane the
    cursor is on. That cut is a line lying on the face; when the cursor is
    within the snap radius of it, the snap is the cursor's foot on it.

    Rafael, 2026-09-16 (02:20), putting windows on a house: the corner of
    the first window gives its dotted line along its own wall «estupendamente»,
    but a window on ANOTHER wall at the same height had nothing to line up
    with — «que la línea guía se extendiera por aquí y yo pudiera fijar la
    ventana aquí… tampoco eso lo hace […]». It does not: the classic
    'from point' is the axis LINE through the corner, which meets a
    perpendicular wall in a single point and the opposite wall not at all.
    The plane through the corner meets both in a line.

    Two dotted guides, so the eye can walk from the corner to the cursor:
    from ``ref`` to where it projects onto the line (along the first
    wall), and from there along the line to the foot (along the second),
    each in the colour of the axis it runs along. ``axis`` names the
    plane's normal: ``"z"`` is 'level with', the other two 'in line with'.

    Sits BELOW the axis lines through the point (a line on the face is
    exactly one of those when the point is on the same wall, and the foot
    is then the same point) — an inference derived from a point never
    beats the point, and this one never beats the line it generalises."""
    if plane_normal is None or plane_normal.length() < 1e-9:
        return None
    n = plane_normal.normalized()
    best = None
    for axis, a in _AXIS_VECTORS.items():
        d = QVector3D.crossProduct(a, n)
        if d.length() < 1e-6:
            continue      # the axis plane is parallel to the face: no line
        d = d.normalized()
        # In the face, square to the line: the way the cursor has to move
        # to reach the plane through ``ref``.
        m = QVector3D.crossProduct(n, d)
        ma = QVector3D.dotProduct(m, a)                       # = |a × n|, > 0
        s = QVector3D.dotProduct(candidate - ref, a)
        foot = candidate - m * (s / ma)
        fp = world_to_pixel(foot)
        if fp is None:
            continue
        dist = math.hypot(fp[0] - cx, fp[1] - cy)
        if dist > threshold_px:
            continue
        if is_occluded is not None and is_occluded(foot):
            continue
        if best is None or dist < best[0]:
            best = (dist, foot, axis, d)
    if best is None:
        return None
    _, foot, axis, d = best
    # The reference's own projection onto the line: the guide's elbow.
    elbow = foot + d * QVector3D.dotProduct(ref - foot, d)

    def _colour_along(v):
        if v.length() < 1e-6:
            return COLOR_EXTENSION
        u = v.normalized()
        k = max(_AXIS_VECTORS,
                key=lambda k: abs(QVector3D.dotProduct(u, _AXIS_VECTORS[k])))
        return AXIS_COLORS[k]

    guides = []
    if (elbow - QVector3D(ref)).length() > 1e-4:
        guides.append((QVector3D(ref), elbow, _colour_along(elbow - ref)))
    return SnapResult(foot, "aligned", COLOR_ENDPOINT, axis=axis,
                      guide=(elbow, foot), guide_color=_colour_along(foot - elbow),
                      guides=guides or None)


def _extension_snap(
    candidate_world, cx, cy, scene, world_to_pixel, et, start_point, is_occluded,
    project_onto_line=None,
) -> Optional[SnapResult]:
    """Extension / intersection inference: when the draw direction is collinear
    with an edge and the cursor is on that edge's *continuation* (beyond its
    ends), snap along it — and onto where it crosses another edge (a green
    connection point), so a line extends exactly onto a perpendicular one.

    ``None`` unless the draw is collinear with an edge near the cursor, which is
    what keeps every edge's infinite line from becoming snap noise."""
    if start_point is None:
        return None
    draw = candidate_world - start_point
    if draw.length() < 1e-6:
        return None
    draw = draw.normalized()
    # The draw direction above comes from where the cursor ray meets the
    # scene. Over empty sky that is on the draw; over a face it is a point
    # on the wall BEHIND, and the direction is nonsense — the extension of
    # a sloped roof edge showed only with nothing behind it («a veces te
    # bloquea y a veces no, depende de cómo te orientes», Rafael, revision
    # 4, 03:56). So when the 3D test fails the same question is asked on
    # screen, where the cursor really is, and the point is taken on the
    # edge's line under the cursor ray instead of on that far wall.
    sp = world_to_pixel(start_point) if project_onto_line is not None else None
    sdx = sdy = 0.0
    if sp is not None:
        sdx, sdy = cx - sp[0], cy - sp[1]
    sdl = math.hypot(sdx, sdy)
    best_ext = None  # (dist, proj, from_end, edge, dir)
    for edge in scene.edges:
        # One chord of a circle, arc or smoothed surface has no line worth
        # extending — a sphere's soft edges and the next circle's segments
        # threw dashed guides across the model (issue #140) — and a hidden
        # edge is not there to be followed.
        if (getattr(edge, "soft", False) or getattr(edge, "hidden", False)
                or getattr(edge, "curve", None) is not None):
            continue
        ab = edge.b - edge.a
        if ab.length() < 1e-9:
            continue
        u = ab.normalized()
        at = candidate_world
        if abs(QVector3D.dotProduct(draw, u)) < 0.966:  # ~15°: drawing along it
            # The on-screen reading is only for EXTENDING this edge from its
            # own line (the start sits on it, as Rafael's did at the eave):
            # a merely parallel edge, or one that runs toward the camera and
            # shows as a stub, has no trustworthy screen direction — letting
            # those in handed a midpoint over to an «extension» 5.8 m deep
            # (snap matrix, front camera).
            if sdl < 4.0:
                continue
            off = start_point - edge.a
            if (off - u * QVector3D.dotProduct(off, u)).length() > 1e-3:
                continue
            pa, pb = world_to_pixel(edge.a), world_to_pixel(edge.b)
            if pa is None or pb is None:
                continue
            edx, edy = pb[0] - pa[0], pb[1] - pa[1]
            edl = math.hypot(edx, edy)
            if edl < 20.0 or abs(sdx * edx + sdy * edy) < 0.966 * sdl * edl:
                continue
            at = project_onto_line(edge.a, u)
        t = QVector3D.dotProduct(at - edge.a, u)
        if -1e-6 <= t <= ab.length() + 1e-6:
            continue  # on the segment itself
        proj = edge.a + u * t
        pp = world_to_pixel(proj)
        if pp is None:
            continue
        d = math.hypot(pp[0] - cx, pp[1] - cy)
        if d > et:
            continue
        if is_occluded is not None and is_occluded(proj):
            continue
        if best_ext is None or d < best_ext[0]:
            from_end = edge.a if t < 0 else edge.b
            best_ext = (d, proj, from_end, edge, u)
    if best_ext is None:
        return None
    _, proj, from_end, src, u = best_ext
    best_hit = None
    for other in scene.edges:
        if other is src:
            continue
        hit = _line_segment_intersection(proj, u, other.a, other.b)
        if hit is None:
            continue
        hp = world_to_pixel(hit)
        if hp is None:
            continue
        dh = math.hypot(hp[0] - cx, hp[1] - cy)
        if dh > et:
            continue
        if is_occluded is not None and is_occluded(hit):
            continue
        if best_hit is None or dh < best_hit[0]:
            best_hit = (dh, hit)
    if best_hit is not None:
        return SnapResult(best_hit[1], "intersection", COLOR_ENDPOINT,
                          guide=(from_end, best_hit[1]))
    return SnapResult(proj, "extension", COLOR_EXTENSION, guide=(from_end, proj))


def _from_point_snap(
    scene, start_point, draw_dir, cx, cy, world_to_pixel, threshold_px,
    is_occluded, extra_point=None, axis_deg: float = 10.0,
    hovered_refs: bool = False, line_dir: Optional[QVector3D] = None,
    project_onto_line: Optional[ProjectOntoLine] = None,
) -> Optional[SnapResult]:
    """'From point' inference ("Desde el punto"), the single clean version.

    Without ``line_dir``, fires only when the draw runs along an axis (within
    ``axis_deg``), the way the red/green/blue axis line lights up. Under
    an explicit directional lock, ``line_dir`` supplies that locked direction
    instead. For every corner (and midpoint) it snaps to the fixed foot of that
    point on the draw line, pinning one spot instead of sliding or scattering.

    Corners → green 'from point' with an axis-coloured guide; midpoints → cyan.

    With ``hovered_refs`` (the arrow-key lock) the cursor may also sit on the
    REFERENCE itself — a corner or midpoint, or any point of an edge — far
    from the draw line, and the snap lands on that reference's foot. That is
    how the lock is used: Tape from the wall's bottom edge, ↑, hover
    the window's corner, and the guide takes the window's height (Rafael,
    04:20: «cuando pulso la flechita para subir no me hace el snap»)."""
    if start_point is None or draw_dir.length() < 1e-6:
        return None
    if line_dir is not None:
        if line_dir.length() < 1e-6:
            return None
        adir = QVector3D(line_dir).normalized()
    else:
        u = draw_dir.normalized()
        # The draw must be along an axis; orient that axis along the draw direction.
        adir = None
        cos_axis = math.cos(math.radians(axis_deg))
        for a in _AXIS_VECTORS.values():
            dp = QVector3D.dotProduct(u, a)
            if abs(dp) >= cos_axis:
                adir = a if dp > 0 else -a
                break
        if adir is None:
            return None  # diagonal draw — no clean 'from point'

    refs = []
    if extra_point is not None:
        refs.append((extra_point, "from_point", COLOR_ENDPOINT))
    for edge in scene.edges:
        if getattr(edge, "figure", False):
            # A face-me figure is scenery, not drawing: its feet snap when you
            # point at them, but no line of the drawing lines up with it
            # (Rafael, revision 4, 04:08: the scale figure pulled «from
            # point» guides metres away from the roof he was drawing).
            continue
        refs.append((edge.a, "from_point", COLOR_ENDPOINT))
        refs.append((edge.b, "from_point", COLOR_ENDPOINT))
        refs.append(((edge.a + edge.b) * 0.5, "midpoint", COLOR_MIDPOINT))
    # The world origin is a reference like any corner. It is a named snap of
    # its own (rule 6) but lives in no edge, so under an axis lock — which
    # returns from this function and never reaches rule 6 — it existed only
    # when a piece of geometry happened to touch it. Measured with the red
    # axis locked and the cursor four pixels off each point: a corner gave
    # an exact foot, the origin gave the cursor's own projection, i.e.
    # nothing (issue #27, @pacaeiro).
    refs.append((QVector3D(0.0, 0.0, 0.0), "origin", COLOR_ORIGIN))

    if hovered_refs:
        # The point of an edge under the cursor is a reference too (the
        # window's sill, not just its corners): the closest point of the
        # nearest edge, as a plain 'from point'. Corners and midpoints come
        # first — a sub-pixel miss on a corner must not hand the snap to
        # the edge's body a few millimetres away — so the edge point only
        # competes when no point reference is within reach.
        best_edge = None
        for edge in scene.edges:
            pa, pb = world_to_pixel(edge.a), world_to_pixel(edge.b)
            if pa is None or pb is None:
                continue
            d, t = _closest_on_segment_2d((cx, cy), pa, pb)
            if d <= threshold_px and (best_edge is None or d < best_edge[0]):
                best_edge = (d, _on_edge_point(edge, t, project_onto_line))
        if best_edge is not None:
            refs.append((best_edge[1], "from_point", COLOR_ENDPOINT, True))

    best = None  # (dist, foot, ref, kind, color)
    for entry in refs:
        ref, kind, color = entry[0], entry[1], entry[2]
        if len(entry) > 3 and best is not None:
            continue                      # the edge body yields to any point
        s = QVector3D.dotProduct(ref - start_point, adir)
        if not hovered_refs and s <= 1e-6:
            continue  # at or behind the start along the draw
        # Under a lock (``hovered_refs``) the line runs BOTH ways and the
        # reference itself is a target, so no side is "behind" — and a
        # reference level with the start (s = 0) is worth showing: its foot
        # is the start, the guide says «level with it», and a click there
        # draws nothing. The side used to be decided by where the cursor
        # RAY met the lock line, which with the cursor ON a reference far
        # from the line is anywhere: measured with six dashes and five
        # cameras, each camera lost a different dash (issue #34,
        # @pacaeiro: «not all of them are detected… Origin not always
        # detected… if the position of the Origin is negative»).
        foot = start_point + adir * s
        if (foot - ref).length() < 1e-4:
            continue  # ref already on the draw line (collinear, not a crossing)
        qp = world_to_pixel(foot)
        if qp is None:
            continue
        d = math.hypot(qp[0] - cx, qp[1] - cy)
        if hovered_refs:
            rp = world_to_pixel(ref)
            if rp is not None:
                d = min(d, math.hypot(rp[0] - cx, rp[1] - cy))
        if d > threshold_px:
            continue
        if is_occluded is not None and is_occluded(foot):
            continue
        if best is None or d < best[0]:
            best = (d, foot, ref, kind, color)
    if best is None:
        return None
    _, foot, ref, kind, color = best
    # The guide runs perpendicular to the draw, from the corner to the foot —
    # colour it by the axis it most aligns with (red/green/blue).
    guide_color = None
    if kind == "from_point":
        gdn = (foot - ref).normalized()
        gaxis = max(_AXIS_VECTORS,
                    key=lambda k: abs(QVector3D.dotProduct(gdn, _AXIS_VECTORS[k])))
        guide_color = AXIS_COLORS[gaxis]
    return SnapResult(foot, kind, color, guide=(ref, foot),
                      guide_color=guide_color)


def _through_point_snap(
    start_point, through_point, draw_dir, project_onto_line, inference_deg,
) -> Optional[SnapResult]:
    """'Through point' inference ("A través del punto"): when the draw heads
    along the line from the start *through* an encouraged point, lock onto that
    line so the segment passes exactly through it. A magenta directional lock,
    like parallel/perpendicular but toward an arbitrary point."""
    if (
        start_point is None or through_point is None
        or project_onto_line is None or draw_dir.length() < 1e-6
    ):
        return None
    dirv = through_point - start_point
    if dirv.length() < 1e-6:
        return None
    dir_u = dirv.normalized()
    if abs(QVector3D.dotProduct(draw_dir.normalized(), dir_u)) < \
            math.cos(math.radians(inference_deg)):
        return None
    locked = project_onto_line(start_point, dir_u)
    return SnapResult(locked, "through_point", COLOR_REFERENCE,
                      guide=(through_point, locked))


def _perpendicular_face_snap(
    start_point, face_normal, draw_dir, project_onto_line, inference_deg,
) -> Optional[SnapResult]:
    """'Perpendicular to face' inference ("Perpendicular a la cara"): when the
    draw runs along an encouraged face's normal, lock to it so the line leaves
    the face square-on. Magenta directional lock."""
    if (
        start_point is None or face_normal is None
        or project_onto_line is None or draw_dir.length() < 1e-6
        or face_normal.length() < 1e-6
    ):
        return None
    n_u = face_normal.normalized()
    if abs(QVector3D.dotProduct(draw_dir.normalized(), n_u)) < \
            math.cos(math.radians(inference_deg)):
        return None
    locked = project_onto_line(start_point, n_u)
    return SnapResult(locked, "perp_face", COLOR_REFERENCE)


def _intersection_snap(
    cx, cy, scene, world_to_pixel, et, is_occluded
) -> Optional[SnapResult]:
    """Green intersection point where two edges / guide lines actually cross.

    Every other ``"intersection"`` in this module is *directional*: it only
    appears while a lock line is active (an axis lock, a perpendicular draw, an
    extension). Two construction guides crossing produce no such direction, so
    their meeting point was never offered — the cursor slid along whichever
    guide was nearest (``on_edge``). The X of two guides is the whole reason to
    draw them, so collect the edges whose screen span passes under the cursor
    and intersect them pairwise in 3-D (edge intersection).

    ``segment_intersection`` rejects parallel and *skew* pairs, so two edges
    that merely cross in projection do not light up a point that isn't there.
    Real model edges that cross are already split into a shared vertex by the
    topology pass (the endpoint snap wins first); this mainly catches the
    guides, which live outside the mesh, and any unsplit crossing."""

    # Local import: keep the snap engine free of a module-load dependency on
    # the topology package (and any import cycle it might grow into).
    from core.topology import segment_intersection

    # Only edges whose screen span passes under the cursor can contribute:
    # that keeps the pairwise test tiny and stops a far-away crossing (whose
    # pixel happens to land near the cursor by coincidence of depth) from
    # firing.
    near = []
    for edge in scene.edges:
        if getattr(edge, "center", False):
            continue  # the degenerate pseudo-edge that carries a circle centre
        ab = edge.b - edge.a
        if QVector3D.dotProduct(ab, ab) < 1e-12:
            continue
        pa = world_to_pixel(edge.a)
        pb = world_to_pixel(edge.b)
        if pa is None or pb is None:
            continue
        d, _t = _closest_on_segment_2d((cx, cy), pa, pb)
        if d <= et:
            near.append(edge)
    if len(near) < 2:
        return None

    best = None  # (dist_px, hit)
    for i in range(len(near)):
        e1 = near[i]
        for j in range(i + 1, len(near)):
            e2 = near[j]
            hit = segment_intersection(e1.a, e1.b, e2.a, e2.b)
            if hit is None:
                continue  # parallel, collinear or skew — no real meeting
            hp = world_to_pixel(hit)
            if hp is None:
                continue
            dh = math.hypot(hp[0] - cx, hp[1] - cy)
            if dh > et:
                continue
            if is_occluded is not None and is_occluded(hit):
                continue
            if best is None or dh < best[0]:
                best = (dh, hit)
    if best is None:
        return None
    return SnapResult(best[1], "intersection", COLOR_ENDPOINT)


def _lock_line_snaps(
    scene, start_point, line_dir, cx, cy, world_to_pixel, threshold_px,
    is_occluded, acquired_point, chain_first_point=None,
    project_onto_line=None,
) -> Optional[SnapResult]:
    """What a directional lock still lets you fetch, in order: the chain's
    own first point (closing), a vertex sitting ON the lock line, the
    crossing of the lock line with another edge, and a corner, midpoint or
    origin — hovered, or projected onto the line. Issue #27 gave these to
    the arrow lock, #31 to the Shift lock, and #34 found the third lock —
    Shift held over a soft axis cue, when the press had nothing to capture
    — with none of them: «release Shift to reposition the camera and
    reactivate it: half of the Snap points are not detected». One body
    now, three callers. ``line_dir`` must already point at the cursor."""
    # The chain's own first point closes the polyline, lock or no lock.
    # Without this the lock TRAPS you in the chain: the rule returns
    # before the close rule is ever reached, so the click that should
    # have closed the figure came back as a plain lock and the Line tool
    # went on chaining (Marco, 2026-09-18: «se cerró la figura … sigue
    # apareciendo el eje X bloqueado» — it LOOKED closed). Only when the
    # point really is on the lock line, so closing never quietly breaks
    # the lock the user asked for.
    if chain_first_point is not None and _vertex_on_line(
            chain_first_point, start_point, line_dir):
        fp_px = world_to_pixel(chain_first_point)
        if fp_px is not None and math.hypot(
                fp_px[0] - cx, fp_px[1] - cy) <= threshold_px:
            return SnapResult(QVector3D(chain_first_point), "close", COLOR_CLOSE)
    # A vertex that sits on the lock line → endpoint snap, so you can land
    # exactly on a corner without leaving the lock.
    for edge in scene.edges:
        for vertex in (edge.a, edge.b):
            if not _vertex_on_line(vertex, start_point, line_dir):
                continue
            vp = world_to_pixel(vertex)
            if vp is None:
                continue
            if math.hypot(vp[0] - cx, vp[1] - cy) <= threshold_px:
                return SnapResult(vertex, "endpoint", COLOR_ENDPOINT)
    # Where the lock line crosses another edge → intersection (green
    # point), so a locked line landing on a crossing wall offers the exact
    # junction without breaking the lock.
    best_hit: Optional[tuple[float, QVector3D]] = None
    for edge in scene.edges:
        hit = _line_segment_intersection(start_point, line_dir, edge.a, edge.b)
        if hit is None:
            continue
        hp = world_to_pixel(hit)
        if hp is None:
            continue
        dh = math.hypot(hp[0] - cx, hp[1] - cy)
        if dh > threshold_px:
            continue
        if is_occluded is not None and is_occluded(hit):
            continue
        if best_hit is None or dh < best_hit[0]:
            best_hit = (dh, hit)
    if best_hit is not None:
        return SnapResult(best_hit[1], "intersection", COLOR_ENDPOINT,
                          guide=(start_point, best_hit[1]))
    # 'From point' along the lock line: line up with a corner (green) or
    # midpoint (cyan) projected onto the locked axis — or hover it.
    return _from_point_snap(
        scene, start_point, line_dir, cx, cy, world_to_pixel,
        threshold_px, is_occluded, extra_point=acquired_point,
        hovered_refs=True, line_dir=line_dir,
        project_onto_line=project_onto_line,
    )


#: Two point candidates closer than this on screen are a tie, and the tie
#: goes to the drawing context (see ``_resolve`` in :func:`compute_snap`).
_TIE_PX = 0.5


def compute_snap(
    candidate_world: QVector3D,
    candidate_pixel: tuple[float, float],
    scene,
    world_to_pixel: Callable[[QVector3D], Optional[tuple[float, float]]],
    threshold_px: float,
    project_onto_line: Optional[ProjectOntoLine] = None,
    chain_first_point: Optional[QVector3D] = None,
    start_point: Optional[QVector3D] = None,
    axis_lock: Optional[str] = None,
    shift_held: bool = False,
    reference_edge=None,
    reference_mode: Optional[str] = None,
    inference_angle_deg: float = 3.0,
    screen_axis_px: Optional[float] = None,
    is_occluded: Optional[Callable[[QVector3D], bool]] = None,
    face_under_cursor: bool = False,
    edge_threshold_px: Optional[float] = None,
    magnetic_axis_deg: Optional[float] = None,
    acquired_edge=None,
    acquired_point=None,
    acquired_face_normal=None,
    acquired_points=None,
    shift_lock_dir=None,
    shift_lock_color=None,
    linear_mode: str = "all",
    work_plane_normal: Optional[QVector3D] = None,
    radial_arm: bool = False,
) -> SnapResult:
    # Linear-inference toggle (Alt): "all" = every inference, "off" =
    # point snaps only, "parallel_perp" = keep only parallel/perpendicular. The
    # explicit locks (arrow keys, Down-arrow reference) always work regardless.
    allow_axis = linear_mode == "all"          # axis / from-point / extension
    allow_parperp = linear_mode != "off"       # parallel / perpendicular
    # A protractor ARM (Rotate, Protractor) is a direction from the centre,
    # not a line being drawn: 'through point', 'extension' and 'from point'
    # are line-drawing inferences. On an arm they only fought the axis
    # magnet — a diameter 1.7° off X held the arm on its own direction
    # through the reference just clicked, and a chord of the next circle
    # turned the angle with the cursor's distance (issue #140, @pacaeiro).
    line_inferences = allow_axis and not radial_arm

    # 1. Explicit axis lock (arrow keys). Use the viewport's camera-aware
    #    projection so locks to Z (vertical) actually move along Z. Existing
    #    vertices that fall on the lock line still get an endpoint snap, so
    #    you can land exactly on them without leaving the lock.
    if axis_lock and start_point is not None and project_onto_line is not None:
        axis_dir = _AXIS_VECTORS[axis_lock]
        locked = project_onto_line(start_point, axis_dir)
        cx, cy = candidate_pixel
        # A lock line runs BOTH ways from the start, so point it at the
        # cursor. 'From point' below drops any reference behind the draw
        # direction — sound when the draw direction IS the cursor, but here
        # the axis was handed over as its positive vector whichever way the
        # user was going, so HALF THE AXIS offered nothing: the same corner,
        # the same lock, snapped when approached from the left and not from
        # the right (measured 2026-09-17; issue #27, @pacaeiro: «almost none
        # of them are detected»). The two rules above work on the infinite
        # line and do not care about the sign.
        if QVector3D.dotProduct(locked - start_point, axis_dir) < 0:
            axis_dir = -axis_dir
        # 1a–1d: closing, a vertex on the line, a crossing, 'from point'
        #        (``_lock_line_snaps``; issues #27, #34).
        hit = _lock_line_snaps(
            scene, start_point, axis_dir, cx, cy, world_to_pixel,
            threshold_px, is_occluded, acquired_point, chain_first_point,
            project_onto_line,
        )
        if hit is not None:
            return hit
        return SnapResult(locked, "axis", AXIS_COLORS[axis_lock], axis=axis_lock)

    # 1.5 Sticky inference lock (Shift captured an active inference): hold that
    #     direction regardless of cursor, the way Shift classically locks whatever
    #     inference was showing. Vertices on the lock line still snap so you can
    #     land exactly on a corner without leaving the lock.
    if (
        shift_lock_dir is not None
        and start_point is not None
        and project_onto_line is not None
    ):
        cx, cy = candidate_pixel
        lock_dir = QVector3D(shift_lock_dir)
        locked = project_onto_line(start_point, lock_dir)
        # The lock line runs BOTH ways from the start: point it at the cursor,
        # exactly as rule 1 does since issue #27, or half of it offers nothing.
        if QVector3D.dotProduct(locked - start_point, lock_dir) < 0:
            lock_dir = -lock_dir
        # Everything rule 1 gained in issue #27 and this one never did.
        # @pacaeiro on 0.4.4: «when I get an Axis and locked it with Shift, I
        # do not have any Snaps… P.S. If I use hard lock (arrows) I have the
        # Snaps working». He is right, and he also says why it matters: Shift
        # is the lock you use precisely to go and fetch a point from another
        # object. Held to a direction with no points to fetch, it is half a
        # tool. Same sub-rules, same order (``_lock_line_snaps``).
        hit = _lock_line_snaps(
            scene, start_point, lock_dir, cx, cy, world_to_pixel,
            threshold_px, is_occluded, acquired_point, chain_first_point,
            project_onto_line,
        )
        if hit is not None:
            return hit
        color = shift_lock_color if shift_lock_color is not None else COLOR_REFERENCE
        return SnapResult(locked, "reference", color)

    # 2. Reference edge lock (Down arrow + edge under cursor).
    if (
        reference_edge is not None
        and reference_mode
        and start_point is not None
        and project_onto_line is not None
    ):
        direction = _direction_from_edge(reference_edge, reference_mode,
                                         work_plane_normal)
        if direction is not None:
            locked = project_onto_line(start_point, direction)
            if QVector3D.dotProduct(locked - start_point, direction) < 0:
                direction = -direction
            hit = _lock_line_snaps(
                scene, start_point, direction, candidate_pixel[0],
                candidate_pixel[1], world_to_pixel, threshold_px,
                is_occluded, acquired_point, chain_first_point,
                project_onto_line,
            )
            if hit is not None:
                return hit
            return SnapResult(locked, "reference", COLOR_REFERENCE)

    # 3. Shift held + auto axis inference → lock to that axis. This is the
    #    lock you get when the Shift press found nothing to capture (after
    #    orbiting away, say) and the cursor then lines up with an axis. It
    #    had NO snaps — the third such lock (issue #34, @pacaeiro: «release
    #    Shift to reposition the camera… reactivate the Shift, half of the
    #    Snap points are not detected»). Same sub-rules as the other two.
    if allow_axis and shift_held and start_point is not None and project_onto_line is not None:
        inferred = _detect_axis_alignment(
            start_point, candidate_world, inference_angle_deg
        )
        if inferred is not None:
            axis_dir = QVector3D(_AXIS_VECTORS[inferred])
            locked = project_onto_line(start_point, axis_dir)
            if QVector3D.dotProduct(locked - start_point, axis_dir) < 0:
                axis_dir = -axis_dir
            cx3, cy3 = candidate_pixel
            hit = _lock_line_snaps(
                scene, start_point, axis_dir, cx3, cy3, world_to_pixel,
                threshold_px, is_occluded, acquired_point, chain_first_point,
                project_onto_line,
            )
            if hit is not None:
                return hit
            return SnapResult(locked, "axis", AXIS_COLORS[inferred], axis=inferred)

    cx, cy = candidate_pixel
    et = edge_threshold_px if edge_threshold_px is not None else threshold_px
    best: Optional[tuple[float, QVector3D, str, tuple[float, float, float]]] = None

    # Candidates within the snap radius, resolved LAZILY: sorted by screen
    # distance and occlusion-tested in that order until the first visible
    # one. Testing every candidate up front cast a ray per point — dozens
    # per hover next to dense geometry (the plaza's pergola: 70 ms a move,
    # measured 2026-09-14) for the same answer the nearest visible gives.
    pending: list = []

    def _consider(
        world: QVector3D,
        kind: str,
        color: tuple[float, float, float],
        occludable: bool = True,
        context: Optional[str] = None,
    ) -> None:
        px = world_to_pixel(world)
        if px is None:
            return
        d = math.hypot(px[0] - cx, px[1] - cy)
        if d > threshold_px:
            return
        pending.append((d, world, kind, color, context, occludable))

    def _resolve():
        """The nearest visible candidate, or ``None``; clears the list.

        Near-ties go to the point of the context being drawn in — a loose
        vertex beats a component's corner at the same spot. The two really
        do coincide when the line was started ON that corner, and only the
        loose vertex can be welded to; the component's copy (mapped through
        its placement, a float or two away) ended a line that closed no
        face, with the tip promising it had snapped (issue #36, @pacaeiro:
        «Endpoint in component and the vertice endpoint share the same
        coordinate, but no face created»). Same family as the 0.4.4 rule:
        a derived point never beats the point it derives from. Within the
        bucket the order stays as appended (named points before endpoints).
        """
        nonlocal best
        pending.sort(key=lambda c: (math.floor(c[0] / _TIE_PX),
                                    0 if c[4] is None else 1))
        chosen = None
        for d, world, kind, color, context, occludable in pending:
            # Only snap to geometry the user can actually see — a vertex
            # hidden behind a face shouldn't light up.
            if occludable and is_occluded is not None and is_occluded(world):
                continue
            chosen = (d, world, kind, color, context)
            break
        pending.clear()
        best = chosen
        return chosen

    # 4. Vertex snaps (close, endpoint) — the highest-priority discrete points.
    if (
        chain_first_point is not None
        and start_point is not None
        and chain_first_point is not start_point
    ):
        # The point being chained to is part of the live drawing, not hidden
        # scene geometry — never occlusion-cull it.
        _consider(chain_first_point, "close", COLOR_CLOSE, occludable=False)
        _resolve()
    if best is None or best[2] != "close":
        # The named points first (a tie goes to the first considered): an
        # arc's midpoint that happens to fall on one of its facet vertices
        # reads "Arc midpoint", the usual name, not "Endpoint".
        plain = []
        for edge in scene.edges:
            if getattr(edge, "center", False):
                # The centre of a circle or arc the cursor visited (the
                # viewport hands it in as a degenerate pseudo-edge).
                _consider(edge.a, "center", COLOR_ENDPOINT)
            elif getattr(edge, "component_origin", False):
                # A group's / component's own origin (the "Component
                # Origin Point") — its insertion point, worth grabbing.
                _consider(edge.a, "component_origin", COLOR_ORIGIN)
            elif getattr(edge, "arc_midpoint", False):
                # The middle of an arc's sweep, not of any one of its facets.
                _consider(edge.a, "arc_midpoint", COLOR_MIDPOINT)
            elif getattr(edge, "guide", False):
                # A construction guide's ends are not endpoints (they are
                # clipped to the view) — it offers 'on line' below.
                continue
            else:
                plain.append(edge)
        # The world origin is a point inference like a corner (the
        # "Origin"), so it must beat the LINEAR inferences of rule 5 — it
        # sat in rule 6, behind 'from point' and the axis line, and a
        # cursor aligned with an encouraged point or the red axis clicked
        # millimetres beside it, leaving stubs along the axis (Marco,
        # 2026-09-15: «me quiero poner en el origen y no se pone»).
        _consider(QVector3D(0.0, 0.0, 0.0), "origin", COLOR_ORIGIN)
        for edge in plain:
            # The usual convention paints every point inference magenta when
            # the geometry is inside a group or component; Marco found the
            # magenta everywhere on a model made of components tiring —
            # 2026-09-14 — so the colours stay, the tip says "in component".)
            _consider(edge.a, "endpoint", COLOR_ENDPOINT, context=getattr(edge, "context", None))
            _consider(edge.b, "endpoint", COLOR_ENDPOINT, context=getattr(edge, "context", None))
        # A "close" already chosen stands; otherwise the nearest visible of
        # the named points and endpoints (named ones first on a tie — they
        # were appended first and the sort is stable).
        if best is None:
            _resolve()
    if best is not None:
        return SnapResult(best[1], best[2], best[3], context=best[4])

    # 4b. Perpendicular to a wall you started on: drawing square to it locks the
    #     exact perpendicular (magenta) and predicts the connection — where that
    #     perpendicular line crosses another edge near the cursor (the parallel
    #     wall) as a green point. Gated on having started on the edge and drawing
    #     square to it, so it's high priority (beats midpoint/on-edge) without
    #     fighting free-angle drawing. Runs before the axis inference so it fires
    #     even when the perpendicular happens to be an axis.
    if allow_parperp and start_point is not None and project_onto_line is not None:
        draw = candidate_world - start_point
        if draw.length() > 1e-6:
            draw_u = draw.normalized()
            cos_tol = math.cos(math.radians(8.0))  # forgiving: it snaps to exact
            for edge in scene.edges:
                if not _point_on_segment_world(start_point, edge.a, edge.b):
                    continue
                perp = _direction_from_edge(edge, "perpendicular",
                                            work_plane_normal)
                if perp is None:
                    continue
                if abs(QVector3D.dotProduct(draw_u, perp)) < cos_tol:
                    continue
                best_hit = None
                for other in scene.edges:
                    if _point_on_segment_world(start_point, other.a, other.b):
                        continue
                    hit = _line_segment_intersection(
                        start_point, perp, other.a, other.b)
                    if hit is None:
                        continue
                    if QVector3D.dotProduct(hit - start_point, draw_u) <= 0:
                        continue  # behind the cursor
                    hp = world_to_pixel(hit)
                    if hp is None:
                        continue
                    dh = math.hypot(hp[0] - cx, hp[1] - cy)
                    if dh > et:
                        continue
                    if is_occluded is not None and is_occluded(hit):
                        continue
                    if best_hit is None or dh < best_hit[0]:
                        best_hit = (dh, hit)
                if best_hit is not None:
                    return SnapResult(best_hit[1], "intersection", COLOR_ENDPOINT,
                                      guide=(start_point, best_hit[1]))
                # Before settling for a bare perpendicular lock, let a corner's
                # projection win: landing where this perpendicular lines up with
                # a corner is the exact point the user is after, and the generic
                # lock would otherwise shadow it.
                if line_inferences:
                    fp = _from_point_snap(
                        scene, start_point, candidate_world - start_point,
                        cx, cy, world_to_pixel, threshold_px, is_occluded,
                        extra_point=acquired_point,
                    )
                    if fp is not None:
                        return fp
                locked = project_onto_line(start_point, perp)
                return SnapResult(locked, "reference", COLOR_REFERENCE)

    # 4e. 'Through point': heading along the line from the start through an
    #     encouraged corner locks onto it (magenta), so the segment passes
    #     exactly through that point even past it.
    #
    #     …but not when the cursor is ON that point. Then the user is not
    #     heading through it, they are landing on it, and this rule kept
    #     them on the ray SHORT of it — pausing over a point quietly made
    #     that point unsnappable. Marco, 2026-09-18: he hooked the midpoint
    #     of a rectangle's edge, saw its marker, clicked once, and the line
    #     stopped 3.9 cm short without even splitting the edge. Measured
    #     with the cursor exactly on the midpoint:
    #
    #         nothing acquired            midpoint        0.00 cm
    #         that midpoint acquired      through_point   0.73 cm
    #
    #     The offset ran precisely back along the draw direction, which is
    #     what gave it away. Same shape as the from-point fix an hour
    #     earlier: an inference DERIVED from a point must not beat the
    #     point it came from.
    if line_inferences and start_point is not None:
        sobre_el_punto = False
        if acquired_point is not None:
            ap = world_to_pixel(acquired_point)
            if ap is not None:
                sobre_el_punto = math.hypot(ap[0] - cx, ap[1] - cy) <= threshold_px
        if not sobre_el_punto:
            tp = _through_point_snap(
                start_point, acquired_point, candidate_world - start_point,
                project_onto_line, inference_angle_deg,
            )
            if tp is not None:
                return tp

    # 5. Extension: when drawing collinear with an edge, snap along its dashed
    #     continuation — and to where that extension crosses another edge (a
    #     definite green connection point), so you can extend a line exactly onto
    #     a perpendicular one. Gated on the draw direction being collinear with
    #     the edge, so it only fires when you mean to extend (no line noise).
    #     Runs before 'from point' so extending a line wins over a corner line-up.
    if line_inferences:
        ext = _extension_snap(
            candidate_world, cx, cy, scene, world_to_pixel, et, start_point,
            is_occluded, project_onto_line=project_onto_line,
        )
        if ext is not None:
            return ext

    # 5b. 'From point' ("Desde el punto"): drawing along an axis, line up with a
    #     corner (green) or midpoint (cyan) — the fixed foot of that point on the
    #     axis-aligned draw line. Only fires on-axis, so free-angle draws stay
    #     quiet and the point never scatters or slides.
    if line_inferences and start_point is not None:
        fp = _from_point_snap(
            scene, start_point, candidate_world - start_point,
            cx, cy, world_to_pixel, threshold_px, is_occluded,
            extra_point=acquired_point,
        )
        if fp is not None:
            return fp

    # 5c. Edge / guide intersection (the green X): where two edges or
    #     guide lines actually cross. Only the directional locks above build an
    #     intersection, so crossing guides never offered their meeting point —
    #     the cursor slid along the nearest guide. Runs before midpoint/on-edge
    #     so the exact crossing wins, but below every endpoint and lock.
    inter = _intersection_snap(cx, cy, scene, world_to_pixel, et, is_occluded)
    if inter is not None:
        return inter

    # 6. Midpoint + origin.
    best = None
    for edge in scene.edges:
        if getattr(edge, "guide", False) or (edge.a - edge.b).length() < 1e-9:
            continue
        _consider((edge.a + edge.b) * 0.5, "midpoint", COLOR_MIDPOINT,
                  context=getattr(edge, "context", None))
    _consider(QVector3D(0.0, 0.0, 0.0), "origin", COLOR_ORIGIN)
    _resolve()
    if best is not None:
        return SnapResult(best[1], best[2], best[3], context=best[4])

    # 7. On-edge: an arbitrary point along an edge. An edge is a big linear
    #    target, so it gets a more generous radius than the point snaps —
    #    landing a corner on it (a door on the floor line) should be forgiving.
    best_edge: Optional[tuple[float, QVector3D]] = None
    for edge in scene.edges:
        pa = world_to_pixel(edge.a)
        pb = world_to_pixel(edge.b)
        if pa is None or pb is None:
            continue
        d, t = _closest_on_segment_2d((cx, cy), pa, pb)
        if d > et:
            continue
        # The screen-space parameter ``t`` is NOT the world parameter under
        # perspective, so 3D-lerping it displaces the point by metres on a long,
        # foreshortened edge. Map back through the camera ray: the closest point
        # on the edge's line to the cursor ray, clamped to the segment.
        ab = edge.b - edge.a
        if project_onto_line is not None and ab.length() > 1e-9:
            proj = project_onto_line(edge.a, ab)
            tt = QVector3D.dotProduct(proj - edge.a, ab) / QVector3D.dotProduct(ab, ab)
            on_pt = edge.a + ab * max(0.0, min(1.0, tt))
        else:
            on_pt = edge.a + ab * t
        if is_occluded is not None and is_occluded(on_pt):
            continue
        if best_edge is None or d < best_edge[0]:
            best_edge = (d, on_pt, edge)
    if best_edge is not None:
        _d, on_pt, edge = best_edge
        if line_inferences and acquired_point is not None:
            # On an edge AND lined up with the acquired point: the one point
            # of the edge that is both. The edge used to win outright, the
            # dotted «from point» line vanished as the cursor reached the
            # wall and the length jumped with every pixel — «hasta el final
            # no me llega» (Rafael, revision 4, 01:30).
            cross = _edge_from_point_crossing(
                edge, acquired_point, cx, cy, world_to_pixel, threshold_px,
                is_occluded)
            if cross is not None:
                return cross
        if getattr(edge, "guide", False):
            return SnapResult(on_pt, "on_line", COLOR_ON_EDGE)   # a guide line
        return SnapResult(on_pt, "on_edge", COLOR_ON_EDGE,
                          context=getattr(edge, "context", None))

    # 8b. Acquired-edge parallel inference. An edge the cursor hovered while
    #     drawing is held as a reference; when the draw runs parallel to it the
    #     line locks parallel (magenta), so you can align to an off-axis wall
    #     without pressing Down. Axis-aligned edges are left to the axis
    #     inference below so they keep their red/green/blue cue.
    if (
        allow_parperp
        and acquired_edge is not None
        and start_point is not None
        and project_onto_line is not None
    ):
        ev = acquired_edge.b - acquired_edge.a
        draw = candidate_world - start_point
        if (
            ev.length() > 1e-9
            and draw.length() > 1e-6
            and _detect_axis_alignment(acquired_edge.a, acquired_edge.b,
                                       inference_angle_deg) is None
        ):
            ev_u = ev.normalized()
            par_cos = math.cos(math.radians(inference_angle_deg))
            if abs(QVector3D.dotProduct(draw.normalized(), ev_u)) >= par_cos:
                locked = project_onto_line(start_point, ev_u)
                return SnapResult(locked, "reference", COLOR_REFERENCE)

    # 8c. Perpendicular to an encouraged face: heading along its normal locks
    #     the line square-out of the face (magenta).
    if allow_parperp and start_point is not None and project_onto_line is not None:
        pf = _perpendicular_face_snap(
            start_point, acquired_face_normal, candidate_world - start_point,
            project_onto_line, inference_angle_deg,
        )
        if pf is not None:
            return pf

    # 8d. 'From point' from an encouraged point — the dotted line
    #     from the corner you last hovered. This is how a window's first
    #     corner lands level with the door's top (Rafael, 2026-09-10: «te
    #     salía una línea de extensión para poder dibujar aquí la ventana»).
    #
    #     It used to live ABOVE the named points and only before the first
    #     click. Both halves of that were wrong, and Marco found them in one
    #     afternoon. Measured with a clean 4 m line and one end acquired,
    #     the cursor sitting exactly on its midpoint:
    #
    #         nothing acquired      midpoint     0.00 cm
    #         one end acquired      from_point   0.65 cm
    #
    #     An alignment LINE was beating a named POINT, so clicking the
    #     midpoint of a wall quietly landed centimetres off and the drawing
    #     came out skewed — reported twice before it was caught («del medio
    #     de la línea quiero dibujar una línea, dibujo sale desfasada»; «sí
    #     agarra, solo cuando termina el dibujo está desfasado»). His own
    #     case was 2.8 cm on a 4 m wall.
    #
    #     Down here it sits below endpoint, midpoint, intersection and
    #     origin, and above the soft axis cue — and it no longer cares
    #     whether an operation is under way, which is the other half: the
    #     reference used to die at the first click, exactly when he needed
    #     it to hold a rectangle's length to a corner.
    #
    #     Marco, 2026-09-18, drawing a step along a wall: «en la segunda
    #     esquina está la referencia pero al momento de jalar el rectángulo
    #     se pierde la referencia». Measured with the wall's far corner
    #     acquired and the cursor pulled out to give the step its depth:
    #
    #         before the first click   from_point   x = 6.430   (the corner)
    #         rectangle under way      none         x = 6.370   (drifted)
    #
    #     The machinery was built and working; it was locked away at exactly
    #     the moment he needed it. Push/pull modellers offer it mid-operation too.
    #
    #     It is a SECOND call rather than an unlocked condition on 5d,
    #     because 5d sits above the named points: opening it in place would
    #     have let an alignment line outrank a midpoint or the origin, and
    #     that precedence is not ours to spend. Down here it competes only
    #     with the soft axis cue below — the weakest rule there is.
    if line_inferences:
        if acquired_points:
            tp = _two_point_snap(
                acquired_points, candidate_world, cx, cy, world_to_pixel,
                threshold_px, is_occluded,
            )
            if tp is not None:
                return tp
        if acquired_point is not None:
            # On a face, the point stays on the face (see the function).
            on_plane = work_plane_normal if face_under_cursor else None
            fp = _first_point_from_point(
                acquired_point, candidate_world, cx, cy, world_to_pixel,
                threshold_px, is_occluded, plane_normal=on_plane,
            )
            if fp is not None:
                return fp
            # 8e. …and level with / in line with it ACROSS this face: the
            #     axis PLANE through the point cut by the face (Rafael's
            #     window on the next wall, 2026-09-16, 02:20). Only on a
            #     face — the bare ground is not a wall to run a line along.
            if on_plane is not None:
                ip = _in_plane_with_point_snap(
                    acquired_point, candidate_world, on_plane, cx, cy,
                    world_to_pixel, threshold_px, is_occluded,
                )
                if ip is not None:
                    return ip

    # 9. Axis inference. A soft visual cue when the tool asks for nothing more.
    #    When ``magnetic_axis_deg`` is set (the Move tool), the inference is
    #    *magnetic*: within that wider angle of an axis the point is projected
    #    onto the axis line and hard-locked, so dragging roughly up moves
    #    straight up and the geometry keeps its length and alignment without
    #    holding a modifier. Point/edge snaps above still win, so you can still
    #    move exactly onto an existing vertex.
    if start_point is not None:
        # ``allow_axis`` gates the magnetic branch too. It did not, and that
        # was a hole in issue #26: Alt is supposed to switch the linear
        # inferences OFF, and measured on 2026-09-18 the Move tool still
        # snapped to the axis with the toggle off. Nobody had noticed
        # because Move was the only tool magnetic enough to show it.
        if (allow_axis and magnetic_axis_deg is not None
                and project_onto_line is not None):
            inferred = _detect_axis_alignment(
                start_point, candidate_world, magnetic_axis_deg
            )
            if inferred is not None:
                locked = project_onto_line(start_point, _AXIS_VECTORS[inferred])
                return SnapResult(locked, "axis", AXIS_COLORS[inferred], axis=inferred)
        # …and the axes that one CANNOT reach, measured in pixels instead
        # (issue #31). Deliberately placed after it and only consulted when
        # it found nothing: an axis the work plane already offers keeps
        # coming from the world detector, so this can only turn a "no
        # inference" into one and never change an answer that existed.
        # Inert until a tool asks for it by setting ``screen_axis_px``.
        if (allow_axis and screen_axis_px is not None
                and project_onto_line is not None):
            inferred = _detect_axis_on_screen(
                start_point, candidate_world, candidate_pixel,
                world_to_pixel, screen_axis_px,
            )
            if inferred is not None:
                locked = project_onto_line(start_point, _AXIS_VECTORS[inferred])
                # …but not to the other side of the county. Seen edge-on, an
                # axis occupies almost no screen, so a pixel of mouse is
                # metres of line: Marco's first live test put a point 16 km
                # out and left him staring at empty space with nothing for
                # zoom-to-extents to find. The point may not run further
                # from the start than a small multiple of where the cursor
                # actually is. Measured over the grid, the honest cases sit
                # at D/R ≈ 1 (median 0.99, p99 2.05, worst 4.01), so this
                # keeps every one of them and kills a runaway, which came
                # in at some thousands.
                reach = (candidate_world - start_point).length()
                if (locked - start_point).length() <= _MAX_AXIS_REACH * reach:
                    return SnapResult(locked, "axis", AXIS_COLORS[inferred],
                                      axis=inferred)
        if allow_axis:
            inferred = _detect_axis_alignment(
                start_point, candidate_world, inference_angle_deg
            )
            if inferred is not None:
                return SnapResult(
                    candidate_world, "axis_inference", AXIS_COLORS[inferred],
                    axis=inferred,
                )

    # 10. On-face: the cursor hovers a face with nothing closer to snap to.
    #     The candidate already lies on that face's plane (the work plane).
    if face_under_cursor:
        return SnapResult(candidate_world, "on_face", COLOR_ON_FACE)

    return SnapResult(candidate_world, "none", COLOR_NONE)
