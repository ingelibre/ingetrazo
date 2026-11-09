# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bridge (issue #614): side faces between two faces, a face and a line,
or two lines (core/bridge.py)."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.bridge import (BridgeError, align_loop, bridge, plan,
                         profiles_from_selection, strips)
from core.mesh import Mesh
from core.orient import is_closed, signed_volume


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _square(z, size=1.0, start=0, reverse=False, x0=0.0):
    pts = [V(x0, 0, z), V(x0 + size, 0, z), V(x0 + size, size, z),
           V(x0, size, z)]
    if reverse:
        pts.reverse()
    return pts[start:] + pts[:start]


def _circle(z, r, n, cx=0.0, cy=0.0):
    return [V(cx + r * math.cos(2 * math.pi * i / n),
              cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)]


def _line(mesh, pts):
    return [mesh.add_edge(a, b) for a, b in zip(pts, pts[1:])]


def _run(mesh, selection):
    return bridge(mesh, profiles_from_selection(mesh, selection))


# ------------------------------------------------------------ face to face

def test_two_squares_become_a_closed_box():
    m = Mesh()
    a = m.add_face(_square(0))
    b = m.add_face(_square(2))
    new = _run(m, {a, b})
    assert len(new) == 4                      # four flat sides, one each
    assert a in m.faces and b in m.faces      # the faces stay as caps
    assert is_closed(m)
    assert abs(signed_volume(m) - 2.0) < 1e-6  # wound outward


def test_the_edges_picked_with_the_faces_do_not_count_as_lines():
    # Double click on a face selects its edges too.
    m = Mesh()
    a = m.add_face(_square(0))
    b = m.add_face(_square(2))
    sel = {a, b} | {e for e in m.edges}
    assert len(_run(m, sel)) == 4
    assert is_closed(m)


@pytest.mark.parametrize("start,reverse", [(1, False), (3, False),
                                           (0, True), (2, True)])
def test_a_loop_wound_or_started_elsewhere_does_not_twist(start, reverse):
    m = Mesh()
    a = m.add_face(_square(0))
    b = m.add_face(_square(2, start=start, reverse=reverse))
    new = _run(m, {a, b})
    assert len(new) == 4                      # untwisted: four flat quads
    assert all(len(f.loop) == 4 for f in new)
    assert abs(signed_volume(m) - 2.0) < 1e-6


def test_tilted_faces_still_close_and_bend_softly():
    # The issue's picture: two loose rectangles at an angle to each other
    # — here also turned, so the sides are not flat.
    m = Mesh()
    a = m.add_face([V(-1, -1, 0), V(1, -1, 0), V(1, 1, 0), V(-1, 1, 0)])
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    b = m.add_face([V(x * c - y * s, x * s + y * c, 3 + 0.3 * x)
                    for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    new = _run(m, {a, b})
    assert is_closed(m)
    assert signed_volume(m) > 0
    # A side that is not flat is split, and its diagonal softened.
    tris = [f for f in new if len(f.loop) == 3]
    assert tris
    soft = [e for e in m.edges if e.soft]
    assert soft and all(len(e.faces) == 2 for e in soft)


def test_a_square_to_a_circle_has_triangles_between_the_corners():
    m = Mesh()
    a = m.add_face([V(-1, -1), V(1, -1), V(1, 1), V(-1, 1)])
    b = m.add_face(_circle(2, 1.0, 24))
    new = _run(m, {a, b})
    assert is_closed(m)
    vol = signed_volume(m)
    # Between the 2×2 square prism (8) and the unit cylinder (2π).
    assert 2 * math.pi < vol < 8
    # No side crosses the solid: every new edge runs from z=0 to z=2 or
    # lies on one of the two caps.
    for f in new:
        zs = {round(p.z(), 6) for p in f.vertices}
        assert zs <= {0.0, 2.0}


@pytest.mark.parametrize("circle_first", [False, True])
@pytest.mark.parametrize("n", [16, 24, 32, 48])
def test_a_square_to_a_circle_joins_each_point_to_its_nearest_corner(
        n, circle_first):
    # «El cuadrado y el círculo sale torciendo»: with the circle as the
    # first profile, the square was the one turned to match — and from
    # its four corners it could only start a corner's worth (45°) off.
    # Every point of the circle must go to its nearest corner, whichever
    # of the two the selection gives first.
    m = Mesh()
    a = m.add_face([V(-1, -1), V(1, -1), V(1, 1), V(-1, 1)])
    b = m.add_face(_circle(2, 1.0, n))
    profiles = profiles_from_selection(m, {a, b})
    if (profiles[0].face is b) != circle_first:
        profiles.reverse()
    new = bridge(m, profiles)

    def angle(p):
        return math.degrees(math.atan2(p.y(), p.x())) % 360

    for f in new:
        pts = f.vertices
        for p, q in zip(pts, pts[1:] + pts[:1]):
            if abs(p.z() - q.z()) < 1e-9:
                continue                      # an edge of a cap
            d = abs(angle(p) - angle(q)) % 360
            assert min(d, 360 - d) <= 45 + 1e-6, (n, angle(p), angle(q))


def test_circles_of_different_points_make_a_smooth_cone():
    m = Mesh()
    a = m.add_face(_circle(0, 2.0, 48))
    b = m.add_face(list(reversed(_circle(3, 1.0, 32))))   # wound the other way
    new = _run(m, {a, b})
    assert is_closed(m)
    # A truncated cone, a little under its smooth volume.
    smooth = math.pi * 3 / 3 * (4 + 2 + 1)
    assert 0.95 * smooth < signed_volume(m) < smooth
    # Untwisted: every side climbs straight, never across the axis.
    for f in new:
        assert len(f.loop) in (3, 4)
        angles = [math.atan2(p.y(), p.x()) for p in f.vertices]
        spread = max(angles) - min(angles)
        assert spread < 0.5 or spread > 2 * math.pi - 0.5


def test_two_rings_make_a_pipe():
    m = Mesh()
    hole0 = list(reversed(_square(0, 0.5, x0=0.25)))
    hole0 = [p + V(0, 0.25, 0) for p in hole0]
    hole2 = [p + V(0, 0, 2) for p in hole0]
    a = m.add_face(_square(0), [hole0])
    b = m.add_face(_square(2), [hole2])
    new = _run(m, {a, b})
    assert len(new) == 8                      # four outside, four inside
    assert is_closed(m)
    assert abs(abs(signed_volume(m)) - 2 * 0.75) < 1e-6


def test_faces_with_different_holes_are_refused():
    m = Mesh()
    hole = [V(0.25, 0.25), V(0.25, 0.75), V(0.75, 0.75), V(0.75, 0.25)]
    a = m.add_face(_square(0), [hole])
    b = m.add_face(_square(2))
    with pytest.raises(BridgeError):
        _run(m, {a, b})
    assert len(m.faces) == 2                  # nothing was added


def test_two_faces_on_one_plane_are_refused():
    m = Mesh()
    a = m.add_face(_square(0))
    b = m.add_face(_square(0, x0=3.0))
    with pytest.raises(BridgeError):
        _run(m, {a, b})


def test_faces_that_touch_are_refused():
    m = Mesh()
    a = m.add_face(_square(0))
    b = m.add_face([V(1, 0, 0), V(1, 1, 0), V(1, 1, 1), V(1, 0, 1)])
    with pytest.raises(BridgeError):
        _run(m, {a, b})


# ------------------------------------------------------------ face to line

def test_a_rectangle_and_a_ridge_make_a_hip_roof():
    m = Mesh()
    base = m.add_face([V(0, 0), V(4, 0), V(4, 2), V(0, 2)])
    ridge = _line(m, [V(1, 1, 1), V(3, 1, 1)])
    new = _run(m, {base, *ridge})
    assert sorted(len(f.loop) for f in new) == [3, 3, 4, 4]
    assert is_closed(m)
    # Middle prism (2 × triangle of area 1) + two end pyramids of 2/3.
    assert abs(signed_volume(m) - 10 / 3) < 1e-6


def test_a_face_and_a_point_line_order_does_not_matter():
    m = Mesh()
    ridge = _line(m, [V(3, 1, 1), V(1, 1, 1)])     # drawn the other way
    base = m.add_face([V(0, 0), V(4, 0), V(4, 2), V(0, 2)])
    _run(m, {*ridge, base})
    assert abs(signed_volume(m) - 10 / 3) < 1e-6


# ------------------------------------------------------------ line to line

def test_two_parallel_lines_make_one_face():
    m = Mesh()
    l1 = _line(m, [V(0, 0), V(4, 0)])
    l2 = _line(m, [V(0, 3), V(4, 3)])
    new = _run(m, {*l1, *l2})
    assert len(new) == 1
    assert abs(new[0].area() - 12) < 1e-6
    assert not is_closed(m)


def test_two_lines_drawn_opposite_ways_do_not_cross():
    m = Mesh()
    l1 = _line(m, [V(0, 0), V(4, 0)])
    l2 = _line(m, [V(4, 3), V(0, 3)])
    new = _run(m, {*l1, *l2})
    assert len(new) == 1
    assert abs(new[0].area() - 12) < 1e-6


def test_skew_lines_make_two_triangles_with_a_soft_diagonal():
    m = Mesh()
    l1 = _line(m, [V(0, 0, 0), V(2, 0, 0)])
    l2 = _line(m, [V(0, 2, 1), V(2, 2, -1)])
    new = _run(m, {*l1, *l2})
    assert len(new) == 2 and all(len(f.loop) == 3 for f in new)
    shared = [e for e in m.edges if len(e.faces) == 2]
    assert len(shared) == 1 and shared[0].soft


def test_lines_of_different_points_pair_by_length():
    m = Mesh()
    l1 = _line(m, [V(0, 0, 0), V(2, 0, 0), V(4, 0, 0)])
    l2 = _line(m, [V(0, 0, 2), V(1, 0, 2), V(3, 0, 2), V(4, 0, 2)])
    new = _run(m, {*l1, *l2})
    # One flat strip: merged into a single face 4 × 2.
    assert sum(f.area() for f in new) == pytest.approx(8.0)


def test_a_curve_and_its_copy_above_make_a_smooth_wall():
    # Issue #615's picture: a wavy line turned into a wall. Copy the line
    # up and bridge the two.
    m = Mesh()
    wave = [V(x * 0.5, math.sin(x * 0.5), 0) for x in range(13)]
    low = _line(m, wave)
    high = _line(m, [p + V(0, 0, 3) for p in wave])
    new = _run(m, {*low, *high})
    # The whole wall: the line's length times the height (panels that
    # come out flat with their neighbour are merged into one).
    length = sum((b - a).length() for a, b in zip(wave, wave[1:]))
    area = sum(f.area() for f in new)
    assert area == pytest.approx(3 * length, rel=1e-3)
    # Every side stands upright, and the seams between them are soft:
    # one curved wall, not a row of panels.
    for f in new:
        assert abs(f.normal().normalized().z()) < 1e-6
    seams = [e for e in m.edges if len(e.faces) == 2]
    assert seams and all(e.soft for e in seams)


def test_two_closed_loops_of_edges_make_an_open_tube():
    m = Mesh()
    c1 = _circle(0, 1.0, 12)
    c2 = _circle(3, 1.0, 12)
    l1 = _line(m, c1 + c1[:1])
    l2 = _line(m, c2 + c2[:1])
    new = _run(m, {*l1, *l2})
    assert len(new) == 12
    assert not is_closed(m)                   # no caps: there were no faces
    # The seams of a round tube are soft, so it reads as one surface.
    seams = [e for e in m.edges if len(e.faces) == 2]
    assert seams and all(e.soft for e in seams)


# ------------------------------------------------------------ selection

def test_one_face_alone_is_refused():
    m = Mesh()
    a = m.add_face(_square(0))
    with pytest.raises(BridgeError):
        _run(m, {a})


def test_three_profiles_are_refused():
    m = Mesh()
    faces = [m.add_face(_square(z)) for z in (0, 1, 2)]
    with pytest.raises(BridgeError):
        _run(m, set(faces))


def test_a_branching_line_is_refused():
    m = Mesh()
    a = m.add_face(_square(0))
    t = _line(m, [V(0, 0, 2), V(2, 0, 2)]) + _line(m, [V(1, 0, 2),
                                                      V(1, 1, 2)])
    with pytest.raises(BridgeError):
        _run(m, {a, *t})


def test_plan_touches_no_mesh():
    m = Mesh()
    a = m.add_face(_square(0))
    b = m.add_face(_square(2))
    profiles = profiles_from_selection(m, {a, b})
    faces = len(m.faces)
    assert len(plan(profiles)) == 4
    assert len(m.faces) == faces


def test_strips_mix_quads_and_triangles_by_length():
    a = [V(0, 0), V(1, 0), V(2, 0)]
    b = [V(0, 1), V(2, 1)]
    polys = strips(a, b, closed=False)
    # A triangle while only ``a`` advances, then a quad as both reach
    # their ends together.
    assert sorted(len(p) for p in polys) == [3, 4]


def test_align_loop_finds_the_matching_start():
    a = _square(0)
    b = _square(2, start=2, reverse=True)
    got = align_loop(a, b)
    assert [(p.x(), p.y()) for p in got] == [(p.x(), p.y()) for p in a]


def test_more_than_two_faces_is_refused_at_once():
    mesh = Mesh()
    faces = [mesh.add_face([V(i * 2, 0), V(i * 2 + 1, 0), V(i * 2 + 1, 1),
                            V(i * 2, 1)]) for i in range(3)]
    with pytest.raises(BridgeError):
        profiles_from_selection(mesh, faces)


def test_three_loose_lines_are_refused_before_sorting(monkeypatch):
    # The right-click menu asks on every click: a third line is enough to
    # say no, without ordering thousands of pieces first.
    import core.bridge
    mesh = Mesh()
    for i in range(3):
        mesh.add_edge(V(i, 0), V(i, 1))
    monkeypatch.setattr(core.bridge, "_key", lambda *_a: pytest.fail(
        "the pieces were sorted"))
    with pytest.raises(BridgeError):
        profiles_from_selection(mesh, list(mesh.edges))
