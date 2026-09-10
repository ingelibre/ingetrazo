# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Robust polygon offset: slide the edges, let the arrangement sort out the
mess, keep the regions that are really there.

:func:`core.topology.offset_loop` slides every edge and re-intersects the
neighbours. That is exact while the result stays a polygon with the same
corners — and gives up the moment one of them disappears, because it has no
way to DROP a segment. On a real drawing that happens constantly: Marco's
paved slab, whose boundary carries the segmented bite the round plaza takes
out of it, refused any inward offset past 2.65 cm (Plaza Yanque,
2026-09-10). SketchUp does it, because it removes what collapses.

The recipe here is the standard one, and it costs little because the hard
part already exists: :mod:`core.arrangement` computes every intersection,
traces the minimal faces and tells outer loops from holes.

1. Slide each edge by ``d``.
2. Join the corners with a MITRE, bevelling when the spike runs past the
   mitre limit (a very sharp corner would otherwise throw its offset corner
   arbitrarily far).
3. Hand the segments to the arrangement, which resolves the crossings the
   collapses create.
4. Keep the regions whose interior really sits ``d`` inside the original —
   the pockets that closed produce regions that fail this and drop out.

Step 4 is the whole trick, and it is one signed distance per region.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QVector3D

#: How far past the offset corner a mitre may reach before it is bevelled,
#: as a multiple of the distance. Clipper's default is 2; the same value
#: keeps a 20° spike honest without chamfering ordinary corners.
MITRE_LIMIT = 2.0

#: The kept region must sit this fraction of ``d`` inside — not the full ``d``,
#: because the arrangement's interior point is a triangle centroid, not the
#: deepest point, and a thin valid sliver would fail an exact test.
_KEEP = 0.75


def _dist_to_boundary(p: QVector3D, loop: list) -> float:
    best = float("inf")
    count = len(loop)
    for i in range(count):
        a = loop[i]
        ab = loop[(i + 1) % count] - a
        length2 = ab.lengthSquared()
        if length2 < 1e-18:
            best = min(best, (p - a).length())
            continue
        t = QVector3D.dotProduct(p - a, ab) / length2
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        best = min(best, (p - (a + ab * t)).length())
    return best


def _inside(p: QVector3D, loop: list, normal: QVector3D) -> bool:
    from core.arrangement import _point_in_polygon, plane_basis
    u, w = plane_basis(normal)
    origin = loop[0]

    def proj(q):
        rel = q - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    return _point_in_polygon(proj(p), [proj(q) for q in loop])


def interior_point(loop: list, normal: QVector3D) -> Optional[QVector3D]:
    """A point genuinely inside ``loop``: the centroid of its biggest
    triangle. The average of the vertices is not one — for a concave loop it
    can land outside the loop itself."""
    if len(loop) < 3:
        return None
    from core.triangulate import triangulate
    try:
        tris = triangulate(list(loop), [], normal)
    except Exception:                    # noqa: BLE001 — geometry, not flow
        return None
    best = None
    best_area = 0.0
    for a, b, c in tris:
        area = QVector3D.crossProduct(b - a, c - a).lengthSquared()
        if area > best_area:
            best_area = area
            best = (a + b + c) / 3.0
    return best


def _offset_segments(loop: list, normal: QVector3D, d: float) -> list:
    """The slid edges, joined corner to corner (mitre, or bevel past the
    limit). Returns ``[(a, b), …]`` ready for the arrangement."""
    from core.topology import _offset_line_intersection
    lines = []
    count = len(loop)
    for i in range(count):
        a = loop[i]
        b = loop[(i + 1) % count]
        edge = b - a
        if edge.length() < 1e-9:
            continue                     # a zero-length edge is not an edge
        direction = edge.normalized()
        push = QVector3D.crossProduct(normal, direction).normalized() * d
        lines.append([a + push, b + push, direction])
    total = len(lines)
    if total < 3:
        return []
    # Two passes on purpose. Mitring as we emit would fix the LAST corner
    # onto the first line after its segment had already gone out with the
    # un-mitred start, leaving the loop open by one corner — the arrangement
    # then prunes the spur and traces nothing at all.
    reach = MITRE_LIMIT * abs(d) + 1e-9
    corners: list = []
    for i in range(total):
        _start, end, direction = lines[i]
        nxt = lines[(i + 1) % total]
        corner = _offset_line_intersection(end, direction, nxt[0], nxt[2],
                                           normal)
        corners.append(corner if corner is not None
                       and (corner - end).length() <= reach else None)
    segments = []
    for i in range(total):
        start, end, _direction = lines[i]
        back = corners[(i - 1) % total]
        here = corners[i]
        a = QVector3D(back) if back is not None else QVector3D(start)
        b = QVector3D(here) if here is not None else QVector3D(end)
        segments.append((a, b))
        if here is None:
            # Bevel across the gap to the next line's own start.
            nxt_start = lines[(i + 1) % total][0]
            segments.append((QVector3D(end), QVector3D(nxt_start)))
    return segments


def offset_regions(loop: list, normal: QVector3D, d: float) -> list:
    """Offset ``loop`` by ``d`` (positive inward) and return the regions that
    survive, as ``[(outer, [holes]), …]``.

    Empty when the offset consumes the whole polygon — which is a real
    answer, not a failure: 10 cm inward of a 20 cm kerb is nothing.
    """
    if len(loop) < 3 or abs(d) < 1e-9:
        return []
    from core.arrangement import planar_arrangement
    unit = normal.normalized()
    if unit.lengthSquared() < 0.5:
        return []
    segments = _offset_segments(loop, unit, d)
    if not segments:
        return []
    try:
        faces = planar_arrangement(segments, loop[0], unit)
    except Exception:                    # noqa: BLE001 — geometry, not flow
        return []
    kept = []
    for outer, holes in faces:
        point = interior_point(outer, unit)
        if point is None:
            continue
        # Signed depth: positive inside the ORIGINAL, negative outside. One
        # test covers both directions — inward wants d of clearance, outward
        # allows straying |d| past the boundary.
        depth = _dist_to_boundary(point, loop)
        if not _inside(point, loop, unit):
            depth = -depth
        if depth < d * _KEEP if d > 0 else depth < d:
            continue
        kept.append((outer, holes))
    return kept
