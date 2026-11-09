# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Shaped bevel profiles — the presets of the usual bevel's custom
profile: steps, a round with support loops, a cornice and a crown
moulding.

A profile is drawn in the unit square as a side view of a bevel between
two faces at a right angle: it runs from ``(1, 0)``, the cut on the
first face, to ``(0, 1)``, the cut on the second; ``(1, 1)`` is the old
edge and ``(0, 0)`` the far corner inside the solid. :func:`sample`
turns a preset into the section's points; :mod:`core.fillet` maps them
onto each edge through the parallelogram of the two cut points and the
old edge, so they follow faces at any angle.

A profile can also be drawn by hand: a list of control points
``(x, y, smooth)`` from ``(1, 0)`` to ``(0, 1)`` (:func:`valid`), which
is what the panel's editor hands over; :func:`controls` gives any preset
as such a list to start from.

Control points are those of the usual presets. A sharp point is a corner
of the outline; runs of smooth points are passed through by a
Catmull–Rom curve. Straight pieces get no points in their middle; the
segments go to the curved pieces, by length.
"""
from __future__ import annotations

import math

#: Presets offered beside the superellipse, in menu order.
PRESETS = ("steps", "supports", "cornice", "crown")

#: Presets that read differently from each side: they start on the face
#: that looks up (a cornice hangs from the top), see core.fillet.
ASYMMETRIC = frozenset({"cornice", "crown"})

# (x, y, smooth) — the usual control points.
_CORNICE = [
    (1.0, 0.0, False), (1.0, 0.125, False), (0.92, 0.16, True),
    (0.875, 0.25, False), (0.8, 0.25, False), (0.733, 0.433, True),
    (0.582, 0.522, True), (0.4, 0.6, True), (0.289, 0.727, True),
    (0.25, 0.925, False), (0.175, 0.925, False), (0.175, 1.0, False),
    (0.0, 1.0, False),
]
_CROWN = [
    (1.0, 0.0, False), (1.0, 0.25, False), (0.75, 0.25, False),
    (0.75, 0.325, False), (0.925, 0.4, True), (0.975, 0.5, True),
    (0.94, 0.65, True), (0.85, 0.75, True), (0.75, 0.875, True),
    (0.7, 1.0, False), (0.0, 1.0, False),
]


def steps_count(segments: int) -> int:
    """Steps of a staircase of about ``segments`` pieces: a riser and a
    tread each, so an odd count rounds up — the usual preset leaves its
    last piece lying on the face then, half a step that is not one."""
    return max(1, (int(segments) + 1) // 2)


def _steps(segments: int) -> list:
    """A staircase of :func:`steps_count` equal steps, a riser down from
    the first face and a tread toward the second in turn; symmetric, so
    it reads the same from either face."""
    k = steps_count(segments)
    pts = [(1.0, 0.0)]
    for i in range(k):
        x = 1.0 - (i + 1) / k
        pts.append((x, i / k))
        pts.append((x, (i + 1) / k))
    pts[-1] = (0.0, 1.0)
    return pts


def _supports(segments: int) -> list:
    """A quarter round with a straight run on each side — the «support
    loops» that keep the round crisp."""
    arc = max(1, segments - 2)
    pts = [(1.0, 0.0)]
    for k in range(arc + 1):
        a = math.pi / 2.0 * k / arc
        pts.append((0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)))
    pts.append((0.0, 1.0))
    return pts


def _catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2
                        + (-a + 3 * b - 3 * c + d) * t3)
                 for a, b, c, d in zip(p0, p1, p2, p3))


def _from_controls(controls, segments: int) -> list:
    pts = [(x, y) for x, y, _s in controls]
    smooth = [s for _x, _y, s in controls]
    pieces = list(range(len(pts) - 1))
    curved = [i for i in pieces if smooth[i] or smooth[i + 1]]
    spare = max(0, segments - (len(pieces) - len(curved)))

    def length(i):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        return math.hypot(x1 - x0, y1 - y0)
    total = sum(length(i) for i in curved) or 1.0
    out = [pts[0]]
    for i in pieces:
        if i not in curved:
            out.append(pts[i + 1])
            continue
        k = max(1, round(spare * length(i) / total))
        # Neighbours for the tangent: a sharp end is its own neighbour,
        # so the curve leaves a corner straight toward the next point.
        p0 = pts[i - 1] if i > 0 and smooth[i] else pts[i]
        p3 = pts[i + 2] if i + 2 < len(pts) and smooth[i + 1] else pts[i + 1]
        for j in range(1, k + 1):
            out.append(_catmull(p0, pts[i], pts[i + 1], p3, j / k))
    return out


def valid(controls) -> bool:
    """Whether ``controls`` is a drawable outline: two points or more,
    from (1, 0) to (0, 1), all inside the unit square."""
    try:
        pts = [(float(x), float(y), bool(sm)) for x, y, sm in controls]
    except (TypeError, ValueError):
        return False
    if len(pts) < 2:
        return False
    if abs(pts[0][0] - 1) > 1e-9 or abs(pts[0][1]) > 1e-9:
        return False
    if abs(pts[-1][0]) > 1e-9 or abs(pts[-1][1] - 1) > 1e-9:
        return False
    return all(-1e-9 <= c <= 1 + 1e-9 for x, y, _s in pts for c in (x, y))


def controls(shape, segments: int) -> list:
    """``shape`` as editable control points: a preset's own, a drawn
    outline as it is, or — for anything else — a quarter round."""
    if isinstance(shape, (list, tuple)) and valid(shape):
        return [(float(x), float(y), bool(sm)) for x, y, sm in shape]
    if shape == "cornice":
        return list(_CORNICE)
    if shape == "crown":
        return list(_CROWN)
    if shape == "steps":
        return [(x, y, False) for x, y in _steps(segments)]
    if shape == "supports":
        pts = [(1.0, 0.0, False), (1.0, 0.5, False)]
        for k in (1, 2, 3):
            a = math.pi / 8.0 * k
            pts.append((0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a), True))
        return pts + [(0.5, 1.0, False), (0.0, 1.0, False)]
    pts = [(1.0, 0.0, False)]
    for k in (1, 2, 3):
        a = math.pi / 8.0 * k
        pts.append((math.cos(a), math.sin(a), True))
    return pts + [(0.0, 1.0, False)]


def sample(shape, segments: int) -> list:
    """The points of ``shape`` from ``(1, 0)`` to ``(0, 1)``, for about
    ``segments`` pieces (steps round an odd count up to whole steps; the
    mouldings take at least their own corners)."""
    segments = max(int(segments), 1)
    if isinstance(shape, (list, tuple)):
        return _from_controls(controls(shape, segments), segments)
    if shape == "steps":
        return _steps(segments)
    if shape == "supports":
        return _supports(segments)
    if shape == "cornice":
        return _from_controls(_CORNICE, segments)
    if shape == "crown":
        return _from_controls(_CROWN, segments)
    raise ValueError(shape)


def mirrored(points: list) -> list:
    """The same outline read from the other face."""
    return [(y, x) for x, y in reversed(points)]
