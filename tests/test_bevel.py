# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fillet 3D as a bevel: the size read four ways (radius, distance on the
faces, width or depth of the new face), the section shaped by a
superellipse profile — 0.5 the circular arc, 0.25 a straight chamfer,
toward 1 the old square edge, toward 0 a cove — and box corners closed
round or with a flat cut.

Every check is against geometry worked out by hand: the volume a chamfer
takes off a box edge is ``t²/2 · L``; a section point of profile ``ρ``
sits on ``x^r + y^r = 1`` with ``r = ln 4 / ln(1/ρ)``; on an edge whose
faces meet at α the chord is ``2·t·sin(α/2)`` and its depth
``t·cos(α/2)``.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.fillet import _exponent, apply_fillet, plan_fillet
from core.mesh import Mesh
from core.orient import is_closed, signed_volume
from tests.test_fillet import box, edge_at

TOP_FRONT = ((0, 0, 1), (2, 0, 1))      # along X, between top (+Z) and front (−Y)


def _bevel(m, edges, size, segments, profile=0.5, measure="radius",
           corners="round"):
    plan = plan_fillet(m, edges, size, segments, profile, measure, corners)
    assert not isinstance(plan, str), plan
    apply_fillet(m, plan)
    return plan


def _superellipse_quadrant(r):
    """Area of the quadrant of ``x^r + y^r <= 1``."""
    return math.gamma(1 + 1 / r) ** 2 / math.gamma(1 + 2 / r)


def _strip_points(m, first_new):
    return [q for f in m.faces[first_new:] for q in f.vertices]


def hex_prism(R=1.0, H=1.0) -> Mesh:
    """A regular hexagonal prism, outward-wound: its vertical edges are
    where two side faces meet at 120°."""
    m = Mesh()
    ring = [QVector3D(R * math.cos(math.pi / 3 * k), R * math.sin(math.pi / 3 * k), 0)
            for k in range(6)]
    up = QVector3D(0, 0, H)
    m.add_face(list(reversed(ring)))                       # bottom −Z
    m.add_face([p + up for p in ring])                     # top +Z
    for k in range(6):
        a, b = ring[k], ring[(k + 1) % 6]
        m.add_face([a, b, b + up, a + up])
    assert signed_volume(m) > 0
    return m


# ---- The plain fillet is untouched ---------------------------------------

def test_profile_one_half_and_radius_are_the_plain_fillet():
    a, b = box(), box()
    pa = plan_fillet(a, [edge_at(a, *TOP_FRONT)], 0.2, 8)
    pb = plan_fillet(b, [edge_at(b, *TOP_FRONT)], 0.2, 8, 0.5, "radius")
    assert len(pa.strips) == len(pb.strips) == 8
    for qa, qb in zip(pa.strips, pb.strips):
        assert all((x - y).length() < 1e-9 for x, y in zip(qa, qb))


# ---- Measures ---------------------------------------------------------------

@pytest.mark.parametrize("measure,size", [
    ("offset", 0.2),
    ("radius", 0.2),                     # tan 45° = 1: t = R at a box edge
    ("width", 0.2 * math.sqrt(2)),       # the chord of a 90° chamfer
    ("depth", 0.2 / math.sqrt(2)),       # from the old edge to that chord
])
def test_every_measure_gives_the_same_chamfer_on_a_box_edge(measure, size):
    m = box()
    _bevel(m, [edge_at(m, *TOP_FRONT)], size, 1, measure=measure)
    assert len(m.faces) == 6 + 1 and is_closed(m)
    top = [f for f in m.faces if all(abs(q.z() - 1) < 1e-9 for q in f.vertices)]
    assert min(q.y() for q in top[0].vertices) == pytest.approx(0.2, abs=1e-6)
    # A chamfer takes t²/2 · L off the box.
    assert abs(signed_volume(m)) == pytest.approx(2.0 - 0.2 ** 2 / 2 * 2.0, abs=1e-6)


@pytest.mark.parametrize("measure", ["offset", "width", "depth", "radius"])
def test_measures_on_a_120_degree_edge(measure):
    m = hex_prism()
    v0 = QVector3D(1, 0, 0)
    e = edge_at(m, (1, 0, 0), (1, 0, 1))
    size = 0.1
    plan = _bevel(m, [e], size, 1, measure=measure)
    assert is_closed(m)
    quad = plan.strips[0]
    bottom = [q for q in quad if abs(q.z()) < 1e-9]
    assert len(bottom) == 2
    t1, t2 = (bottom[0] - v0).length(), (bottom[1] - v0).length()
    assert t1 == pytest.approx(t2, abs=1e-6)              # symmetric cut
    chord = (bottom[0] - bottom[1]).length()
    depth = ((bottom[0] + bottom[1]) * 0.5 - v0).length()
    alpha = math.radians(120)
    got = {"offset": t1, "width": chord, "depth": depth,
           "radius": t1 * math.tan(alpha / 2)}[measure]
    assert got == pytest.approx(size, abs=1e-6)
    # The three readings of one cut agree with each other.
    assert chord == pytest.approx(2 * t1 * math.sin(alpha / 2), abs=1e-6)
    assert depth == pytest.approx(t1 * math.cos(alpha / 2), abs=1e-6)


def test_an_unknown_measure_reads_as_radius():
    a, b = box(), box()
    pa = plan_fillet(a, [edge_at(a, *TOP_FRONT)], 0.2, 4)
    pb = plan_fillet(b, [edge_at(b, *TOP_FRONT)], 0.2, 4, 0.5, "nonsense")
    assert all((x - y).length() < 1e-9
               for qa, qb in zip(pa.strips, pb.strips) for x, y in zip(qa, qb))


# ---- Profiles ---------------------------------------------------------------

@pytest.mark.parametrize("profile", [0.1, 0.3, 0.7, 0.9])
def test_section_points_lie_on_the_superellipse(profile):
    m = box()
    t = 0.2
    _bevel(m, [edge_at(m, *TOP_FRONT)], t, 8, profile, "offset")
    assert is_closed(m) and signed_volume(m) > 0
    r = _exponent(profile)
    # Centre of the section's frame: (·, t, 1 − t); the old edge is (·, 0, 1).
    for q in _strip_points(m, 6):
        u = abs(q.y() - t) / t
        v = abs(q.z() - (1 - t)) / t
        assert u <= 1 + 1e-6 and v <= 1 + 1e-6
        assert u ** r + v ** r == pytest.approx(1.0, abs=1e-4)


def test_exponent_of_the_landmark_profiles():
    assert _exponent(0.5) == pytest.approx(2.0)
    assert _exponent(0.25) == pytest.approx(1.0)
    assert _exponent(0.9) > 10 and _exponent(0.1) < 0.7


def test_profile_one_quarter_is_a_straight_chamfer():
    m = box()
    _bevel(m, [edge_at(m, *TOP_FRONT)], 0.2, 6, 0.25, "offset")
    pts = _strip_points(m, 6)
    # Every section point is on the chord from (y, z) = (0.2, 1) to (0, 0.8).
    assert all(abs(q.z() - q.y() - 0.8) < 1e-6 for q in pts)
    assert abs(signed_volume(m)) == pytest.approx(2.0 - 0.02 * 2.0, abs=1e-6)


def test_the_volume_taken_follows_the_profile():
    """Fuller profiles take less off; the area matches the superellipse's
    (the polygon of 32 segments is a hair off the curve)."""
    t, L = 0.2, 2.0
    taken = []
    for profile in (0.15, 0.25, 0.5, 0.75, 0.9):
        m = box()
        _bevel(m, [edge_at(m, *TOP_FRONT)], t, 32, profile, "offset")
        assert is_closed(m)
        removed = 2.0 - abs(signed_volume(m))
        expected = t * t * (1 - _superellipse_quadrant(_exponent(profile))) * L
        assert removed == pytest.approx(expected, rel=0.02, abs=2e-4)
        taken.append(removed)
    assert taken == sorted(taken, reverse=True)


def test_one_segment_is_flat_whatever_the_profile():
    for profile in (0.1, 0.5, 0.9):
        m = box()
        _bevel(m, [edge_at(m, *TOP_FRONT)], 0.2, 1, profile, "offset")
        assert len(m.faces) == 7
        assert abs(signed_volume(m)) == pytest.approx(1.96, abs=1e-6)


def test_the_end_caps_carry_the_profile_on_their_own_plane():
    m = box()
    _bevel(m, [edge_at(m, *TOP_FRONT)], 0.2, 8, 0.8, "offset")
    caps = [f for f in m.faces if all(abs(q.x()) < 1e-9 for q in f.vertices)]
    assert len(caps) == 1 and len(caps[0].vertices) == 3 + 9
    curves = {e.curve for e in m.edges if e.curve is not None}
    assert len(curves) == 2


# ---- Chains and corners -------------------------------------------------------

def test_a_rim_chain_with_a_non_circular_profile_closes():
    m = box()
    rim = [edge_at(m, (0, 0, 1), (2, 0, 1)), edge_at(m, (2, 0, 1), (2, 1, 1)),
           edge_at(m, (2, 1, 1), (0, 1, 1)), edge_at(m, (0, 1, 1), (0, 0, 1))]
    _bevel(m, rim, 0.15, 5, 0.7, "offset")
    assert len(m.faces) == 6 + 4 * 5 and is_closed(m) and signed_volume(m) > 0


@pytest.mark.parametrize("profile", [0.3, 0.7])
def test_all_twelve_edges_close_with_superellipsoid_corners(profile):
    m = box()
    t, n = 0.2, 4
    _bevel(m, list(m.edges), t, n, profile, "offset")
    assert len(m.faces) == 6 + 12 * n + 8 * n * n
    assert is_closed(m) and signed_volume(m) > 0
    r = _exponent(profile)
    near = [q for f in m.faces if len(f.vertices) == 3 for q in f.vertices
            if q.x() < t + 1e-6 and q.y() < t + 1e-6 and q.z() < t + 1e-6]
    assert near
    for q in near:
        s = sum((abs(c - t) / t) ** r for c in (q.x(), q.y(), q.z()))
        assert s == pytest.approx(1.0, abs=1e-4)


def test_a_chamfered_box_has_a_triangle_at_every_corner():
    m = box()
    _bevel(m, list(m.edges), 0.1, 1, 0.5, "offset")
    assert len(m.faces) == 6 + 12 + 8 and is_closed(m)
    # Each edge loses a t²/2 prism between the corner cubes; each corner
    # cube of side t keeps only the tetrahedron beyond x + y + z = 2t
    # (t³/6), so it loses 5t³/6.
    t = 0.1
    edges_between = 4 * 2.0 + 8 * 1.0 - 12 * 2 * t
    removed = t * t / 2 * edges_between + 8 * 5 * t ** 3 / 6
    assert abs(signed_volume(m)) == pytest.approx(2.0 - removed, abs=1e-6)


def test_a_turned_box_bevels_like_an_aligned_one():
    """Issue #74's float32 noise: a turned box still bevels every edge."""
    m = box()
    ang = math.radians(33)
    c, s = math.cos(ang), math.sin(ang)
    turned = Mesh()
    for f in m.faces:
        turned.add_face([QVector3D(c * q.x() - s * q.y(), s * q.x() + c * q.y(),
                                   q.z() * 0.7) for q in f.vertices])
    plan = plan_fillet(turned, list(turned.edges), 0.08, 3, 0.7, "width")
    assert not isinstance(plan, str), plan
    apply_fillet(turned, plan)
    assert is_closed(turned) and signed_volume(turned) > 0


# ---- Refusals ---------------------------------------------------------------

@pytest.mark.parametrize("profile", [0.0, 1.0, -0.2, 1.5])
def test_a_profile_outside_zero_one_is_refused(profile):
    m = box()
    before = len(m.faces), len(m.edges)
    msg = plan_fillet(m, [edge_at(m, *TOP_FRONT)], 0.2, 4, profile, "offset")
    assert isinstance(msg, str) and "profile" in msg
    assert (len(m.faces), len(m.edges)) == before


def test_a_width_too_large_for_the_face_is_refused():
    m = box()
    msg = plan_fillet(m, [edge_at(m, *TOP_FRONT)], 3.0, 1, 0.5, "width")
    assert isinstance(msg, str)
    assert len(m.faces) == 6


# ---- Box corners: round or a flat cut ---------------------------------------

@pytest.mark.parametrize("profile,n", [(0.5, 8), (0.3, 4), (0.8, 3), (0.5, 1)])
def test_a_flat_cut_caps_each_strip_end_down_to_the_corner_centre(profile, n):
    """The usual «cutoff»: at a box corner each strip end is capped by a
    flat face that reaches down to the corner's centre (t, t, t), where
    the three caps meet — no centre face."""
    m = box()
    t = 0.2
    _bevel(m, list(m.edges), t, n, profile, "offset", corners="cut")
    assert len(m.faces) == 6 + 12 * n + 8 * 3
    assert is_closed(m) and signed_volume(m) > 0
    caps = [f for f in m.faces[6 + 12 * n:]
            if all(q.x() < t + 1e-6 and q.y() < t + 1e-6 and q.z() < t + 1e-6
                   for q in f.vertices)]
    assert len(caps) == 3
    centre = QVector3D(t, t, t)
    planes = set()
    for f in caps:
        assert len(f.vertices) == n + 2              # the section + the centre
        assert any((q - centre).length() < 1e-6 for q in f.vertices)
        planes |= {axis for axis in range(3)
                   if all(abs((q.x(), q.y(), q.z())[axis] - t) < 1e-6
                          for q in f.vertices)}
    assert planes == {0, 1, 2}


def test_a_flat_cut_takes_the_corner_cube():
    """Each edge loses its rounding between the corners and each corner
    loses the whole t³ cube: with 64 segments the polygon is a hair off
    the circle."""
    t = 0.2
    m = box()
    _bevel(m, list(m.edges), t, 64, 0.5, "offset", corners="cut")
    between = 4 * 2.0 + 8 * 1.0 - 12 * 2 * t
    removed = t * t * (1 - math.pi / 4) * between + 8 * t ** 3
    assert abs(signed_volume(m)) == pytest.approx(2.0 - removed, abs=2e-4)


def test_a_one_segment_flat_cut_is_exact():
    t = 0.1
    m = box()
    _bevel(m, list(m.edges), t, 1, 0.5, "offset", corners="cut")
    between = 4 * 2.0 + 8 * 1.0 - 12 * 2 * t
    removed = t * t / 2 * between + 8 * t ** 3
    assert abs(signed_volume(m)) == pytest.approx(2.0 - removed, abs=1e-6)


def test_a_flat_cut_takes_more_than_the_round_corner():
    def volume(corners):
        m = box()
        _bevel(m, list(m.edges), 0.2, 8, 0.5, "offset", corners=corners)
        return abs(signed_volume(m))
    assert volume("cut") < volume("round")


def test_a_turned_squashed_box_takes_the_flat_cut():
    m = box()
    ang = math.radians(33)
    c, s = math.cos(ang), math.sin(ang)
    turned = Mesh()
    for f in m.faces:
        turned.add_face([QVector3D(c * q.x() - s * q.y(), s * q.x() + c * q.y(),
                                   q.z() * 0.7) for q in f.vertices])
    plan = plan_fillet(turned, list(turned.edges), 0.08, 3, 0.5, "offset", "cut")
    assert not isinstance(plan, str), plan
    apply_fillet(turned, plan)
    assert is_closed(turned) and signed_volume(turned) > 0


def test_caps_that_do_not_meet_get_a_centre_face():
    """When the bottom points part (the sections' heights differ), a
    centre face joins them and every new side is shared by two faces."""
    from core import fillet as F
    from core.fillet import _corner_cut, _key
    # Catch a box corner's inputs from a plan, then deepen one section.
    captured = {}
    real = F._corner_patch

    def spy(group, sections, *a, **k):
        captured["g"], captured["s"] = group, sections
        return real(group, sections, *a, **k)
    F._corner_patch = spy
    try:
        m2 = box()
        plan_fillet(m2, list(m2.vertex_at(QVector3D(0, 0, 0)).edges), 0.2, 3)
    finally:
        F._corner_patch = real
    group, sections = captured["g"], captured["s"]
    group[0].c_off = group[0].c_off * 1.5
    v = m2.vertex_at(QVector3D(0, 0, 0))
    faces = _corner_cut(group, sections, v)
    assert faces is not None and len(faces) == 4
    sides: dict = {}
    for loop in faces:
        for i, p in enumerate(loop):
            q = loop[(i + 1) % len(loop)]
            key = frozenset((_key(p), _key(q)))
            sides[key] = sides.get(key, 0) + 1
    arcs = {frozenset((_key(sec[k]), _key(sec[k + 1])))
            for sec in sections for k in range(len(sec) - 1)}
    assert all(n == 2 for key, n in sides.items() if key not in arcs)
    assert all(sides.get(key) == 1 for key in arcs)


def test_cut_corner_edges_stay_sharp_and_are_curves():
    m = box()
    _bevel(m, list(m.edges), 0.2, 4, 0.5, "offset", corners="cut")
    t = 0.2
    corner_arcs = [e for e in m.edges if e.curve is not None
                   and max(e.a.x(), e.b.x()) < t + 1e-6
                   and max(e.a.y(), e.b.y()) < t + 1e-6
                   and max(e.a.z(), e.b.z()) < t + 1e-6]
    assert corner_arcs and not any(e.soft for e in corner_arcs)


def test_an_unknown_corner_mode_reads_as_round():
    a, b = box(), box()
    pa = plan_fillet(a, list(a.edges), 0.2, 3, 0.5, "offset")
    pb = plan_fillet(b, list(b.edges), 0.2, 3, 0.5, "offset", "nonsense")
    assert pb.corners == "round" and len(pa.patches) == len(pb.patches)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_a_flat_profile_fills_the_corner_with_a_flat_triangle(n):
    """The usual flat bevel: a chamfer of several segments meets at a box
    corner in one flat triangle (subdivided) — no notch, no bulge."""
    m = box()
    t = 0.2
    _bevel(m, list(m.edges), t, n, 0.25, "offset", corners="round")
    assert is_closed(m)
    tris = [f for f in m.faces[6 + 12 * n:]
            if all(q.x() < t + 1e-6 and q.y() < t + 1e-6 and q.z() < t + 1e-6
                   for q in f.vertices)]
    assert len(tris) == n * n
    for f in tris:
        assert all(abs(q.x() + q.y() + q.z() - 2 * t) < 1e-6 for q in f.vertices)
