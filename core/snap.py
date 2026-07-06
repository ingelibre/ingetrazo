# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Snap engine: pick the best snap target near the cursor.

Snap kinds (priority high → low):
1. ``"axis"``           — explicit axis lock from arrow keys.
2. ``"reference"``      — parallel/perpendicular lock to a reference edge.
3. ``"axis"`` via Shift — Shift held while an axis inference is active.
4. ``"close"``          — closing the current polygon chain.
5. ``"endpoint"``       — vertex of an existing edge.
6. ``"midpoint"``       — midpoint of an existing edge.
7. ``"origin"``         — world origin.
8. ``"on_edge"``        — arbitrary point along an edge (start a shape on it).
9. ``"axis_inference"`` — soft auto-detected axis alignment (visual cue only).
10. ``"none"``          — no snap.

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


# ---- Helpers ---------------------------------------------------------------

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
    nx = abs(delta.x()) / length
    ny = abs(delta.y()) / length
    nz = abs(delta.z()) / length
    # Pick the strongest alignment if multiple pass.
    candidates = [(nx, "x"), (ny, "y"), (nz, "z")]
    candidates.sort(reverse=True)
    if candidates[0][0] >= cos_thresh:
        return candidates[0][1]
    return None


def _direction_from_edge(edge, mode: str) -> Optional[QVector3D]:
    """Return a unit-length direction in the work plane for ``mode``.

    ``parallel``      → the edge's own direction.
    ``perpendicular`` → the edge's direction rotated 90° in the XY plane.

    For perpendicular we ignore the edge's Z component, so the lock stays
    on the ground plane (Z=0), which matches the user expectation in
    architecture / civil flows.
    """
    direction = edge.b - edge.a
    if direction.length() < 1e-6:
        return None
    if mode == "perpendicular":
        # 90° rotation in XY plane.
        direction = QVector3D(-direction.y(), direction.x(), 0.0)
    return direction.normalized()


# ---- Entry point ------------------------------------------------------------

# Type alias for the projection callback the viewport provides. Given the
# chain start point and a direction in world space, it returns the closest
# point on that infinite line to the camera ray that currently passes
# through the cursor pixel. This is what makes Z-axis locks usable (and
# X/Y locks correct when the start point is off the ground plane).
ProjectOntoLine = Callable[[QVector3D, QVector3D], QVector3D]


# Unit vectors for each world axis, used by the axis lock paths.
_AXIS_VECTORS = {
    "x": QVector3D(1.0, 0.0, 0.0),
    "y": QVector3D(0.0, 1.0, 0.0),
    "z": QVector3D(0.0, 0.0, 1.0),
}


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


def _vertex_on_line(
    vertex: QVector3D, line_start: QVector3D, line_dir: QVector3D, tol: float = 1e-4
) -> bool:
    """Whether ``vertex`` lies on the infinite line through ``line_start`` in
    ``line_dir`` (perpendicular distance below ``tol``)."""
    rel = vertex - line_start
    proj = QVector3D.dotProduct(rel, line_dir) * line_dir
    return (rel - proj).length() < tol


def _extension_snap(
    candidate_world, cx, cy, scene, world_to_pixel, et, start_point, is_occluded
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
    best_ext = None  # (dist, proj, from_end, edge, dir)
    for edge in scene.edges:
        ab = edge.b - edge.a
        if ab.length() < 1e-9:
            continue
        u = ab.normalized()
        if abs(QVector3D.dotProduct(draw, u)) < 0.966:  # ~15°: drawing along it
            continue
        t = QVector3D.dotProduct(candidate_world - edge.a, u)
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
) -> Optional[SnapResult]:
    """'From point' inference ("Desde el punto"), the single clean version.

    Fires **only when the draw runs along an axis** (within ``axis_deg``), the
    way SketchUp lights up the red/green/blue axis line. For every corner (and
    midpoint) it snaps to the *fixed* foot of that point on the axis-aligned draw
    line — the corner's coordinate along the draw, the start's other coords. So
    the green point pins one spot (lined up with the corner) instead of sliding
    along the projection or scattering when the draw wanders off-axis.

    Corners → green 'from point' with an axis-coloured guide; midpoints → cyan."""
    if start_point is None or draw_dir.length() < 1e-6:
        return None
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
        refs.append((edge.a, "from_point", COLOR_ENDPOINT))
        refs.append((edge.b, "from_point", COLOR_ENDPOINT))
        refs.append(((edge.a + edge.b) * 0.5, "midpoint", COLOR_MIDPOINT))

    best = None  # (dist, foot, ref, kind, color)
    for ref, kind, color in refs:
        s = QVector3D.dotProduct(ref - start_point, adir)
        if s <= 1e-6:
            continue  # at or behind the start along the draw
        foot = start_point + adir * s
        if (foot - ref).length() < 1e-4:
            continue  # ref already on the draw line (collinear, not a crossing)
        qp = world_to_pixel(foot)
        if qp is None:
            continue
        d = math.hypot(qp[0] - cx, qp[1] - cy)
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
    is_occluded: Optional[Callable[[QVector3D], bool]] = None,
    face_under_cursor: bool = False,
    edge_threshold_px: Optional[float] = None,
    magnetic_axis_deg: Optional[float] = None,
    acquired_edge=None,
    acquired_point=None,
    acquired_face_normal=None,
    shift_lock_dir=None,
    shift_lock_color=None,
    linear_mode: str = "all",
) -> SnapResult:
    # Linear-inference toggle (SketchUp's Alt): "all" = every inference, "off" =
    # point snaps only, "parallel_perp" = keep only parallel/perpendicular. The
    # explicit locks (arrow keys, Down-arrow reference) always work regardless.
    allow_axis = linear_mode == "all"          # axis / from-point / extension
    allow_parperp = linear_mode != "off"       # parallel / perpendicular

    # 1. Explicit axis lock (arrow keys). Use the viewport's camera-aware
    #    projection so locks to Z (vertical) actually move along Z. Existing
    #    vertices that fall on the lock line still get an endpoint snap, so
    #    you can land exactly on them without leaving the lock.
    if axis_lock and start_point is not None and project_onto_line is not None:
        axis_dir = _AXIS_VECTORS[axis_lock]
        locked = project_onto_line(start_point, axis_dir)
        cx, cy = candidate_pixel
        # 1a. Existing vertices that sit on the lock line → endpoint snap, so
        #     you can land exactly on a corner without leaving the lock.
        for edge in scene.edges:
            for vertex in (edge.a, edge.b):
                if not _vertex_on_line(vertex, start_point, axis_dir):
                    continue
                vp = world_to_pixel(vertex)
                if vp is None:
                    continue
                if math.hypot(vp[0] - cx, vp[1] - cy) <= threshold_px:
                    return SnapResult(
                        vertex, "endpoint", COLOR_ENDPOINT
                    )
        # 1b. Where the lock line crosses another edge → intersection snap
        #     (green point), so a locked line landing on a crossing wall offers
        #     the exact junction without breaking the lock.
        best_hit: Optional[tuple[float, QVector3D]] = None
        for edge in scene.edges:
            hit = _line_segment_intersection(start_point, axis_dir, edge.a, edge.b)
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
        # 1c. 'From point' along the lock line: line up with a corner (green) or
        #     midpoint (cyan) projected onto the locked axis.
        fp = _from_point_snap(
            scene, start_point, axis_dir, cx, cy, world_to_pixel,
            threshold_px, is_occluded, extra_point=acquired_point,
        )
        if fp is not None:
            return fp
        return SnapResult(locked, "axis", AXIS_COLORS[axis_lock], axis=axis_lock)

    # 1.5 Sticky inference lock (Shift captured an active inference): hold that
    #     direction regardless of cursor, the way SketchUp's Shift locks whatever
    #     inference was showing. Vertices on the lock line still snap so you can
    #     land exactly on a corner without leaving the lock.
    if (
        shift_lock_dir is not None
        and start_point is not None
        and project_onto_line is not None
    ):
        cx, cy = candidate_pixel
        for edge in scene.edges:
            for vertex in (edge.a, edge.b):
                if not _vertex_on_line(vertex, start_point, shift_lock_dir):
                    continue
                vp = world_to_pixel(vertex)
                if vp is not None and math.hypot(vp[0] - cx, vp[1] - cy) <= threshold_px:
                    return SnapResult(vertex, "endpoint", COLOR_ENDPOINT)
        locked = project_onto_line(start_point, shift_lock_dir)
        color = shift_lock_color if shift_lock_color is not None else COLOR_REFERENCE
        return SnapResult(locked, "reference", color)

    # 2. Reference edge lock (Down arrow + edge under cursor).
    if (
        reference_edge is not None
        and reference_mode
        and start_point is not None
        and project_onto_line is not None
    ):
        direction = _direction_from_edge(reference_edge, reference_mode)
        if direction is not None:
            locked = project_onto_line(start_point, direction)
            return SnapResult(locked, "reference", COLOR_REFERENCE)

    # 3. Shift held + auto axis inference → lock to that axis.
    if allow_axis and shift_held and start_point is not None and project_onto_line is not None:
        inferred = _detect_axis_alignment(
            start_point, candidate_world, inference_angle_deg
        )
        if inferred is not None:
            locked = project_onto_line(start_point, _AXIS_VECTORS[inferred])
            return SnapResult(locked, "axis", AXIS_COLORS[inferred], axis=inferred)

    cx, cy = candidate_pixel
    et = edge_threshold_px if edge_threshold_px is not None else threshold_px
    best: Optional[tuple[float, QVector3D, str, tuple[float, float, float]]] = None

    def _consider(
        world: QVector3D,
        kind: str,
        color: tuple[float, float, float],
        occludable: bool = True,
    ) -> None:
        nonlocal best
        px = world_to_pixel(world)
        if px is None:
            return
        d = math.hypot(px[0] - cx, px[1] - cy)
        if d > threshold_px:
            return
        # Only snap to geometry the user can actually see — a vertex hidden
        # behind a face shouldn't light up. The occlusion test is run after
        # the cheap pixel filter so it only fires for points near the cursor.
        if occludable and is_occluded is not None and is_occluded(world):
            return
        if best is None or d < best[0]:
            best = (d, world, kind, color)

    # 4. Vertex snaps (close, endpoint) — the highest-priority discrete points.
    if (
        chain_first_point is not None
        and start_point is not None
        and chain_first_point is not start_point
    ):
        # The point being chained to is part of the live drawing, not hidden
        # scene geometry — never occlusion-cull it.
        _consider(chain_first_point, "close", COLOR_CLOSE, occludable=False)
    if best is None or best[2] != "close":
        for edge in scene.edges:
            _consider(edge.a, "endpoint", COLOR_ENDPOINT)
            _consider(edge.b, "endpoint", COLOR_ENDPOINT)
    if best is not None:
        return SnapResult(best[1], best[2], best[3])

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
                perp = _direction_from_edge(edge, "perpendicular")
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
                if allow_axis:
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
    if allow_axis and start_point is not None:
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
    if allow_axis:
        ext = _extension_snap(
            candidate_world, cx, cy, scene, world_to_pixel, et, start_point, is_occluded
        )
        if ext is not None:
            return ext

    # 5b. 'From point' ("Desde el punto"): drawing along an axis, line up with a
    #     corner (green) or midpoint (cyan) — the fixed foot of that point on the
    #     axis-aligned draw line. Only fires on-axis, so free-angle draws stay
    #     quiet and the point never scatters or slides.
    if allow_axis and start_point is not None:
        fp = _from_point_snap(
            scene, start_point, candidate_world - start_point,
            cx, cy, world_to_pixel, threshold_px, is_occluded,
            extra_point=acquired_point,
        )
        if fp is not None:
            return fp

    # 6. Midpoint + origin.
    best = None
    for edge in scene.edges:
        _consider((edge.a + edge.b) * 0.5, "midpoint", COLOR_MIDPOINT)
    _consider(QVector3D(0.0, 0.0, 0.0), "origin", COLOR_ORIGIN)
    if best is not None:
        return SnapResult(best[1], best[2], best[3])

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
            best_edge = (d, on_pt)
    if best_edge is not None:
        return SnapResult(best_edge[1], "on_edge", COLOR_ON_EDGE)

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

    # 9. Axis inference. Normally a soft visual cue only (you Shift to lock).
    #    When ``magnetic_axis_deg`` is set (the Move tool), the inference is
    #    *magnetic*: within that wider angle of an axis the point is projected
    #    onto the axis line and hard-locked, so dragging roughly up moves
    #    straight up and the geometry keeps its length and alignment without
    #    holding a modifier. Point/edge snaps above still win, so you can still
    #    move exactly onto an existing vertex.
    if start_point is not None:
        if magnetic_axis_deg is not None and project_onto_line is not None:
            inferred = _detect_axis_alignment(
                start_point, candidate_world, magnetic_axis_deg
            )
            if inferred is not None:
                locked = project_onto_line(start_point, _AXIS_VECTORS[inferred])
                return SnapResult(locked, "axis", AXIS_COLORS[inferred], axis=inferred)
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
