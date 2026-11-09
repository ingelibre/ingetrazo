# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An engaged axis silences the derived linear inferences while the cursor
stays inside its reach (issue #140; ``docs/snap-robustness-plan.md``, "The
rule the fix has to implement"):

    An engaged strong inference (an axis, a held lock, an acquired reference)
    silences the weak ones while the cursor stays inside its reach. The reach
    of a direction is a wide cone and is generous; the reach of a point is a
    disk and is small. Getting a point while an axis is engaged means leaving
    the cone and landing on the point.

Two invariants hold the rule together and this file pins both.

* The DERIVED linear inferences go quiet while the axis is engaged, so none
  of them can steal the point off the line: the perpendicular to the wall you
  started on (4b), the extension (5), 'from point' (5b), the edge/guide
  intersection (5c), the on-edge point (7) and the parallel/perpendicular
  locks learned from an acquired edge or face (8b, 8c). Each is exercised
  against its own control - the same call with the magnet not asked for -
  which proves the inference was really there and that the axis is what
  silenced it.

* The POINT inferences are deliberately NOT silenced: fetching a vertex with
  the mouse - an endpoint, 'through point', the origin - is the one thing that
  must keep winning, and a cursor that leaves the cone gets its point back.

Everything is asked of ``compute_snap`` exactly as the viewport asks it: the
same candidate and the same scene, the only difference between the two calls
being whether the tool asked for the magnet at all.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D

from core.snap import _AXIS_VECTORS, compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _edge(a, b, **kw):
    return SimpleNamespace(a=a, b=b, center=False, **kw)


def _w2p(p):
    """A plan view the three world axes do not collapse into each other:
    x to the right, y up the screen, one metre per 100 px."""
    return (p.x() * 100.0, -p.y() * 100.0)


def _closest_on_line(cand):
    """``project_onto_line`` as the viewport provides it: the point of the
    line (start, direction) nearest the cursor. Direction need not be unit."""
    def project(s, d):
        dd = QVector3D.dotProduct(d, d)
        if dd < 1e-12:
            return QVector3D(s)
        return s + d * (QVector3D.dotProduct(cand - s, d) / dd)
    return project


def _snap(cand, *, edges=(), start=V(0, 0, 0), engaged=True, magnetic=3.0, **extra):
    """The call the viewport makes. ``engaged=False`` simply does not ask the
    tool's magnet for an axis; the geometry and the cursor are identical."""
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=list(edges)), world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=start,
        project_onto_line=_closest_on_line(cand),
        magnetic_axis_deg=magnetic if engaged else None,
        **extra,
    )


def _same(a, b, tol=1e-5):
    return (a - b).length() <= tol


# The acquired edge for 8b: parallel to the draw, 12 deg off the red axis (so
# it is no axis itself), and offset well clear of the draw line so nothing
# else - the extension, on-edge - can claim the cursor first.
_A12 = math.radians(12.0)
_U12 = (math.cos(_A12), math.sin(_A12))
_PARALLEL_EDGE = _edge(
    V(3.0, -3.0), V(3.0 + 2.0 * _U12[0], -3.0 + 2.0 * _U12[1])
)

#: id, edges, start, candidate, magnetic_deg, extra kwargs, the inference kind
#: that must appear when the magnet is silent.
_DERIVED = [
    pytest.param(
        [_edge(V(0, -1), V(0, 1))], V(0, 0, 0), V(2.0, 0.05), 3.0, {}, "reference",
        id="4b-perpendicular-to-the-wall-you-started-on",
    ),
    pytest.param(
        [_edge(V(1, 0), V(3, 0))], V(0, 0, 0), V(4.0, 0.05), 3.0, {}, "extension",
        id="5-extension",
    ),
    pytest.param(
        [_edge(V(2, 1), V(3, 1))], V(0, 0, 0), V(2.0, 0.05), 3.0, {}, "from_point",
        id="5b-from-point",
    ),
    pytest.param(
        [_edge(V(0, -2), V(5, 3)), _edge(V(1, 1), V(5, -3))],
        V(0, 0, 0), V(2.0, 0.05), 3.0, {}, "intersection",
        id="5c-edge-intersection",
    ),
    pytest.param(
        [_edge(V(0.2, 0), V(3, 0))], V(0, 0, 0), V(2.0, 0.05), 3.0, {}, "on_edge",
        id="7-on-edge",
    ),
    pytest.param(
        [_PARALLEL_EDGE], V(0, 0, 0), V(5.0 * _U12[0], 5.0 * _U12[1]), 15.0,
        {"acquired_edge": _PARALLEL_EDGE}, "reference",
        id="8b-acquired-edge-parallel",
    ),
    pytest.param(
        [], V(0, 0, 0), V(2.0, 0.05), 3.0,
        {"acquired_face_normal": V(1, 0, 0)}, "perp_face",
        id="8c-perpendicular-to-an-encouraged-face",
    ),
]


@pytest.mark.parametrize("edges, start, cand, magnetic, extra, kind", _DERIVED)
def test_the_axis_silences_the_derived_inference(edges, start, cand, magnetic, extra, kind):
    # Control first: with no magnet asked for, the very same call returns the
    # inference - so it was there, and the axis is what silenced it.
    loose = _snap(cand, edges=edges, start=start, engaged=False,
                  magnetic=magnetic, **extra)
    assert loose.kind == kind, (loose.kind, loose.point)

    # Engaged: the axis takes command and the inference is gone. Where an
    # edge under the cursor crosses the axis line, that crossing is offered
    # (7a) - it lies ON the line, so it steals nothing from it.
    held = _snap(cand, edges=edges, start=start, engaged=True,
                 magnetic=magnetic, **extra)
    assert held.kind in ("axis", "intersection"), (held.kind, held.point)
    axis = held.axis or _engaged_name(start, held.point)
    assert axis is not None
    # ...and it lands on the axis line through the start, at the cursor's foot.
    on_the_line = _closest_on_line(cand)(start, _AXIS_VECTORS[axis])
    assert _same(held.point, on_the_line), (held.point, on_the_line)


def _engaged_name(start, p):
    """The world axis the segment start→p runs along, if any."""
    d = p - start
    for name, v in _AXIS_VECTORS.items():
        if QVector3D.crossProduct(d, v).length() <= 1e-5 * max(d.length(), 1.0):
            return name
    return None


def test_an_edge_crossing_the_engaged_axis_offers_the_crossing():
    """The chair backrest of the tutorial hunt (2026-10-12): drawing along red
    from the left edge of a face to the right one, with the cursor on the
    right edge, must land exactly ON that edge - 0.5.7 did, the engaged axis
    left the point 1-2 mm inside or outside depending on the pixel and the arc
    left loose stubs. The crossing is on the axis line, so the rule above
    (nothing may pull the point off the line) still holds."""
    wall = _edge(V(0.5, -1.0), V(0.5, 0.6))     # its midpoint is 20 px away
    for dx in (-0.03, 0.0, 0.03):              # ±3 px around the edge
        cand = V(0.5 + dx, 0.02)
        held = _snap(cand, edges=[wall], start=V(0, 0, 0), engaged=True,
                     magnetic=3.0)
        assert held.kind == "intersection", (dx, held.kind, held.point)
        assert _same(held.point, V(0.5, 0.0)), (dx, held.point)


def test_an_edge_parallel_to_the_engaged_axis_still_gives_the_axis():
    """An edge running along the axis never crosses it: the axis keeps the
    point at the cursor's foot (the 7-on-edge case above, from the other
    side)."""
    held = _snap(V(2.0, 0.05), edges=[_edge(V(0.2, 0.08), V(3, 0.08))],
                 start=V(0, 0, 0), engaged=True, magnetic=3.0)
    assert held.kind == "axis", (held.kind, held.point)


def test_a_vertex_under_the_cursor_is_not_silenced_though_it_sits_off_the_axis():
    """8 cm off the red axis, but under the cursor: the point must come back
    where it is, not be pulled to y = 0. A point fetched with the mouse is the
    one thing the axis may not switch off."""
    edge = _edge(V(2.0, 0.08, 0), V(3.0, 0.08, 0))
    held = _snap(V(2.0, 0.05), edges=[edge], start=V(0, 0, 0), engaged=True,
                 magnetic=3.0)
    assert held.kind == "endpoint"
    assert held.point.y() == pytest.approx(0.08, abs=1e-5)


def test_the_origin_is_not_silenced_by_an_axis_through_it():
    """The origin is a named point like a corner (issue #27): an axis drawn
    towards it may not swallow it."""
    held = _snap(V(-0.03, 0.02), start=V(-2, 0, 0), engaged=True, magnetic=3.0)
    assert held.kind == "origin"
    assert _same(held.point, V(0, 0, 0))


def test_through_point_still_wins_over_the_engaged_axis():
    """Heading along the line from the start through an encouraged corner
    locks onto it even while the axis is engaged (4e)."""
    held = _snap(V(2.2, 0.02), start=V(0, 0, 0), engaged=True, magnetic=3.0,
                 acquired_point=V(2, 0, 0))
    assert held.kind == "through_point"


def test_leaving_the_cone_gives_the_point_back():
    """8 deg off the red axis, past the soft cone: the magnet lets go and the
    cursor's own point comes back - drawing deliberately off-axis stays
    possible. The cone is generous, not a step."""
    cand = V(4.0, 4.0 * math.tan(math.radians(8.0)))
    r = _snap(cand, edges=[_edge(V(1, 0), V(3, 0))], start=V(0, 0, 0),
              engaged=True, magnetic=3.0)
    assert r.kind != "axis"
    assert _same(r.point, cand)
