# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bevelling corners (vertices) instead of edges.

Checked against geometry worked out by hand: a one-segment cut of a box
corner by ``t`` takes the tetrahedron ``t³/6``; with profile 0.5 the
round cap at a box corner is the sphere about ``(t, t, t)`` of radius
``t·√2`` through the three face arcs; any profile puts the cap on
``X^r + Y^r + Z^r = 2`` in the frame of the three cut edges.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.fillet import _exponent, apply_fillet
from core.mesh import Mesh
from core.orient import is_closed, signed_volume
from core.vertex_bevel import plan_vertex_bevel
from tests.test_fillet import box, edge_at

ORIGIN = (0, 0, 0)


def _corner(m, p=ORIGIN):
    v = m.vertex_at(QVector3D(*p))
    assert v is not None
    return v


def _bevel(m, verts, size, segments, profile=0.5):
    plan = plan_vertex_bevel(m, verts, size, segments, profile)
    assert not isinstance(plan, str), plan
    apply_fillet(m, plan)
    return plan


def _near_origin(m, t):
    return [f for f in m.faces
            if all(q.x() < t + 1e-6 and q.y() < t + 1e-6 and q.z() < t + 1e-6
                   for q in f.vertices)]


def _cap_removed(r, steps=400):
    """Volume (per t³) between a box corner and the cap X^r+Y^r+Z^r = 2."""
    total = 0.0
    h = 1.0 / steps
    for i in range(steps):
        x = (i + 0.5) * h
        for j in range(steps):
            y = (j + 0.5) * h
            rest = 2.0 - x ** r - y ** r
            if rest < 1.0:                    # the cap is below z = 1 here
                total += (1.0 - max(rest, 0.0) ** (1.0 / r)) * h * h
    return total


def pyramid() -> Mesh:
    """A square pyramid, outward-wound: four edges meet at the apex."""
    m = Mesh()
    p = QVector3D
    a, b, c, d, top = p(0, 0, 0), p(2, 0, 0), p(2, 2, 0), p(0, 2, 0), p(1, 1, 1)
    m.add_face([a, d, c, b])
    for u, w in ((a, b), (b, c), (c, d), (d, a)):
        m.add_face([u, w, top])
    assert signed_volume(m) > 0
    return m


# ---- Solid corners -------------------------------------------------------------

def test_one_segment_cuts_every_box_corner_flat():
    m = box()
    t = 0.2
    _bevel(m, list(m.vertices), t, 1)
    assert len(m.faces) == 6 + 8 and is_closed(m)
    assert abs(signed_volume(m)) == pytest.approx(2.0 - 8 * t ** 3 / 6, abs=1e-6)
    tri = [f for f in _near_origin(m, t) if len(f.vertices) == 3]
    assert len(tri) == 1
    assert all(abs(q.x() + q.y() + q.z() - t) < 1e-6 for q in tri[0].vertices)


def test_a_round_corner_is_the_sphere_through_the_face_arcs():
    m = box()
    t, n = 0.2, 8
    _bevel(m, [_corner(m)], t, n)
    assert is_closed(m) and signed_volume(m) > 0
    assert len(m.faces) == 6 + n * n
    centre = QVector3D(t, t, t)
    for f in m.faces[6:]:
        for q in f.vertices:
            assert (q - centre).length() == pytest.approx(t * math.sqrt(2), abs=1e-6)
    # Each face around the corner traded its corner for the arc.
    top_bottom = [f for f in m.faces[:6] if all(abs(q.z()) < 1e-9 for q in f.vertices)]
    assert len(top_bottom) == 1 and len(top_bottom[0].vertices) == 3 + n + 1


@pytest.mark.parametrize("profile", [0.3, 0.5, 0.8])
def test_the_cap_follows_the_profile(profile):
    m = box()
    t, n = 0.2, 6
    _bevel(m, [_corner(m)], t, n, profile)
    assert is_closed(m) and signed_volume(m) > 0
    r = _exponent(profile)
    for f in m.faces[6:]:
        for q in f.vertices:
            s = sum(((t - c) / t) ** r for c in (q.x(), q.y(), q.z()))
            assert s == pytest.approx(2.0, abs=1e-5)


def test_the_volume_taken_matches_the_cap():
    t = 0.2
    for profile in (0.35, 0.5, 0.7):
        m = box()
        _bevel(m, [_corner(m)], t, 24, profile)
        removed = 2.0 - abs(signed_volume(m))
        expected = _cap_removed(_exponent(profile)) * t ** 3
        assert removed == pytest.approx(expected, rel=0.03)


def test_fuller_profiles_take_less():
    taken = []
    for profile in (0.2, 0.4, 0.6, 0.8):
        m = box()
        _bevel(m, [_corner(m)], 0.2, 8, profile)
        taken.append(2.0 - abs(signed_volume(m)))
    assert taken == sorted(taken, reverse=True)


def test_the_cap_inherits_a_shared_material_and_edges_keep_their_flags():
    m = box()
    for f in m.faces:
        f.attrs = {"color": (200, 30, 30)}
    e = edge_at(m, (0, 0, 0), (2, 0, 0))
    e.layer = "Muros"
    _bevel(m, [_corner(m)], 0.2, 4)
    assert all(f.attrs.get("color") == (200, 30, 30) for f in m.faces)
    short = edge_at(m, (0.2, 0, 0), (2, 0, 0))
    assert short.layer == "Muros"


def test_two_corners_on_one_edge_share_it():
    m = box()
    _bevel(m, [_corner(m), _corner(m, (2, 0, 0))], 0.3, 3)
    assert is_closed(m)
    assert edge_at(m, (0.3, 0, 0), (1.7, 0, 0)) is not None


def test_a_four_edge_apex_cuts_flat_with_one_segment():
    m = pyramid()
    apex = _corner(m, (1, 1, 1))
    _bevel(m, [apex], 0.3, 1)
    assert is_closed(m) and signed_volume(m) > 0
    square = [f for f in m.faces if len(f.vertices) == 4 and
              all(q.z() > 0.5 for q in f.vertices)]
    assert len(square) == 1
    z = square[0].vertices[0].z()
    assert all(abs(q.z() - z) < 1e-6 for q in square[0].vertices)


def test_a_four_edge_apex_refuses_a_round_cap():
    m = pyramid()
    msg = plan_vertex_bevel(m, [_corner(m, (1, 1, 1))], 0.3, 4)
    assert isinstance(msg, str) and "three" in msg


# ---- Flat figures -------------------------------------------------------------

def test_a_corner_of_a_flat_figure_rounds_in_its_plane():
    m = Mesh()
    p = QVector3D
    m.add_face([p(0, 0, 0), p(2, 0, 0), p(2, 1, 0), p(0, 1, 0)])
    plan = _bevel(m, [_corner(m)], 0.25, 6)
    assert len(m.faces) == 1 and not plan.patches
    f = m.faces[0]
    assert len(f.vertices) == 3 + 7
    assert all(abs(q.z()) < 1e-9 for q in f.vertices)
    # The arc is the quarter circle about (0.25, 0.25) of radius 0.25.
    arc = [q for q in f.vertices if q.x() < 0.25 + 1e-9 and q.y() < 0.25 + 1e-9]
    assert len(arc) == 7
    for q in arc:
        assert math.hypot(q.x() - 0.25, q.y() - 0.25) == pytest.approx(0.25, abs=1e-6)
    assert len({e.curve for e in m.edges if e.curve is not None}) == 1


def test_all_four_corners_of_a_rectangle():
    m = Mesh()
    p = QVector3D
    m.add_face([p(0, 0, 0), p(2, 0, 0), p(2, 1, 0), p(0, 1, 0)])
    _bevel(m, list(m.vertices), 0.2, 1)
    assert len(m.faces[0].vertices) == 8
    area = 2.0 - 4 * 0.2 * 0.2 / 2
    assert abs(m.faces[0].area()) == pytest.approx(area, abs=1e-6)


# ---- Refusals -----------------------------------------------------------------

def test_refusals_leave_the_mesh_untouched():
    m = box()
    before = (len(m.faces), len(m.edges))
    v = _corner(m)
    assert isinstance(plan_vertex_bevel(m, [], 0.1), str)
    assert isinstance(plan_vertex_bevel(m, [v], 0.0), str)
    assert isinstance(plan_vertex_bevel(m, [v], 0.1, 4, 1.0), str)
    assert isinstance(plan_vertex_bevel(m, [v], 1.0), str)       # edge is 1 long
    both = [v, _corner(m, (0, 1, 0))]
    assert isinstance(plan_vertex_bevel(m, both, 0.5), str)      # 2 × 0.5 = 1
    assert (len(m.faces), len(m.edges)) == before


def test_a_corner_with_a_loose_edge_is_refused():
    m = box()
    m.add_edge(QVector3D(0, 0, 0), QVector3D(-1, 0, 0))
    msg = plan_vertex_bevel(m, [_corner(m)], 0.1)
    assert isinstance(msg, str) and "no face" in msg
