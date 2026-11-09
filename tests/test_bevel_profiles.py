# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Drawn bevel profiles — steps, a round with support loops, a cornice
and a crown moulding — in place of the superellipse.

Each outline is checked by its own geometry — the steps' risers and
treads, the supports' half-size quarter circle, the mouldings' control
points — and on a box by the volume it takes: the corner square minus
the area the outline leaves, along the edge."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core import bevel_profiles as bp
from core.fillet import apply_fillet, plan_fillet
from core.orient import is_closed, signed_volume
from tests.test_fillet import box, edge_at

TOP_FRONT = ((0, 0, 1), (2, 0, 1))
RIM = [((0, 0, 1), (2, 0, 1)), ((2, 0, 1), (2, 1, 1)),
       ((2, 1, 1), (0, 1, 1)), ((0, 1, 1), (0, 0, 1))]


def _area_kept(points):
    """Area between the outline and the inner corner (0, 0) of the unit
    square: the part of the corner square the bevel leaves."""
    loop = [(0.0, 0.0)] + list(points)
    a = 0.0
    for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


@pytest.mark.parametrize("shape", bp.PRESETS)
@pytest.mark.parametrize("segments", [1, 3, 6, 12])
def test_every_outline_runs_from_one_face_to_the_other(shape, segments):
    pts = bp.sample(shape, segments)
    assert pts[0] == pytest.approx((1.0, 0.0))
    assert pts[-1] == pytest.approx((0.0, 1.0))
    assert all(-1e-9 <= c <= 1.0 + 1e-9 for p in pts for c in p)
    assert len(pts) >= 2


def test_steps_are_whole_symmetric_steps():
    for n, steps in ((1, 1), (2, 1), (3, 2), (4, 2), (6, 3), (9, 5)):
        pts = bp.sample("steps", n)
        assert len(pts) == 2 * steps + 1
        # Every piece is a riser or a tread: one coordinate stays put.
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            assert x0 == pytest.approx(x1) or y0 == pytest.approx(y1)
        # It reads the same from either face.
        back = bp.mirrored(pts)
        assert all(a == pytest.approx(b) for a, b in zip(back, pts))


def test_the_round_with_supports_is_a_half_size_quarter_circle():
    pts = bp.sample("supports", 8)
    assert pts[1] == pytest.approx((1.0, 0.5)) and pts[-2] == pytest.approx((0.5, 1.0))
    for x, y in pts[1:-1]:
        assert math.hypot(x - 0.5, y - 0.5) == pytest.approx(0.5)


@pytest.mark.parametrize("shape,controls", [("cornice", bp._CORNICE),
                                            ("crown", bp._CROWN)])
def test_mouldings_pass_through_their_control_points(shape, controls):
    pts = bp.sample(shape, 24)
    for x, y, _smooth in controls:
        assert min(math.hypot(x - px, y - py) for px, py in pts) < 1e-9


def test_mirrored_reads_the_outline_from_the_other_face():
    pts = bp.sample("cornice", 12)
    back = bp.mirrored(pts)
    assert back[0] == pytest.approx((1.0, 0.0)) and back[-1] == pytest.approx((0.0, 1.0))
    assert bp.mirrored(back) == pts


@pytest.mark.parametrize("shape", bp.PRESETS)
def test_one_edge_with_a_drawn_profile_takes_its_area(shape):
    m = box()
    t, n = 0.2, 8
    plan = plan_fillet(m, [edge_at(m, *TOP_FRONT)], t, n, 0.5, "offset", "round", shape)
    assert not isinstance(plan, str), plan
    apply_fillet(m, plan)
    assert is_closed(m) and signed_volume(m) > 0
    removed = 2.0 - abs(signed_volume(m))
    expected = (1.0 - _area_kept(bp.sample(shape, n))) * t * t * 2.0
    assert removed == pytest.approx(expected, abs=1e-6)


def _sound(m):
    """Closed, and every edge between exactly two faces."""
    return is_closed(m) and all(len(e.faces) == 2 for e in m.edges)


@pytest.mark.parametrize("shape", bp.PRESETS)
@pytest.mark.parametrize("corners", ["round", "cut"])
@pytest.mark.parametrize("segments", [2, 5, 12])
def test_a_rim_and_a_whole_box_close(shape, corners, segments):
    m = box()
    plan = plan_fillet(m, [edge_at(m, *e) for e in RIM], 0.2, segments, 0.5,
                       "offset", corners, shape)
    assert not isinstance(plan, str), plan
    apply_fillet(m, plan)
    assert _sound(m) and signed_volume(m) > 0
    m = box()
    plan = plan_fillet(m, list(m.edges), 0.2, segments, 0.5, "offset", corners, shape)
    assert not isinstance(plan, str), plan
    apply_fillet(m, plan)
    assert _sound(m) and signed_volume(m) > 0


@pytest.mark.parametrize("segments", [2, 4, 6, 10])
def test_three_staircases_meet_in_a_stepped_pyramid(segments):
    """Each edge loses (1 − kept area)·t² along it; each corner cube of k³
    cells keeps those whose indices pair up under k − 1 — exact."""
    t = 0.2
    k = bp.steps_count(segments)
    m = box()
    plan = plan_fillet(m, list(m.edges), t, segments, 0.5, "offset", "round", "steps")
    apply_fillet(m, plan)
    assert _sound(m)
    kept2 = sum(1 for a in range(k) for b in range(k) if a + b < k - 1) / k ** 2
    kept3 = sum(1 for a in range(k) for b in range(k) for c in range(k)
                if a + b < k - 1 and a + c < k - 1 and b + c < k - 1) / k ** 3
    between = 4 * 2.0 + 8 * 1.0 - 12 * 2 * t
    removed = (1 - kept2) * t * t * between + 8 * (1 - kept3) * t ** 3
    assert abs(signed_volume(m)) == pytest.approx(2.0 - removed, abs=1e-6)
    # The pyramid is made of flat squares a step wide.
    step = t / k
    for f in plan.patches:
        sides = [(f[i] - f[(i + 1) % len(f)]).length() for i in range(len(f))]
        assert len(f) == 4 and all(s == pytest.approx(step, abs=1e-6) for s in sides)


def test_a_round_outline_drawn_by_hand_fills_like_the_sphere():
    """The spherical product of a quarter circle is the sphere."""
    from core.fillet import _corner_product
    import core.fillet as F
    arc = [(math.cos(a), math.sin(a), True)
           for a in (math.pi / 2 * i / 12 for i in range(13))]
    arc[0], arc[-1] = (1.0, 0.0, False), (0.0, 1.0, False)
    t = 0.2
    m = box()
    plan = plan_fillet(m, list(m.vertex_at(QVector3D(0, 0, 0)).edges), t, 12,
                       0.5, "offset", "round", arc)
    assert not isinstance(plan, str), plan
    centre = QVector3D(t, t, t)
    near = [q for f in plan.patches for q in f]
    assert near
    # Points of the drawn arc are on the sphere; between them (Catmull–Rom)
    # a hair off it.
    for q in near:
        assert (q - centre).length() == pytest.approx(t, abs=2e-3)


def test_drawn_outlines_are_checked():
    assert bp.valid([(1, 0, False), (0, 1, False)])
    assert not bp.valid([(1, 0, False)])
    assert not bp.valid([(0.9, 0, False), (0, 1, False)])
    assert not bp.valid([(1, 0, False), (1.2, 0.5, True), (0, 1, False)])
    m = box()
    msg = plan_fillet(m, [edge_at(m, *TOP_FRONT)], 0.2, 4, 0.5, "offset", "round",
                      [(1, 0, False), (0.5, 0.5, True)])
    assert isinstance(msg, str) and len(m.faces) == 6


@pytest.mark.parametrize("shape", list(bp.PRESETS) + [None])
def test_every_preset_opens_in_the_editor_as_itself(shape):
    ctl = bp.controls(shape, 8)
    assert bp.valid(ctl)
    if shape == "steps":
        assert [(x, y) for x, y, _s in ctl] == bp.sample("steps", 8)
    if shape in ("cornice", "crown"):
        assert ctl == list(bp._CORNICE if shape == "cornice" else bp._CROWN)



def test_a_hand_drawn_outline_follows_the_up_face_too():
    drawn = [(1.0, 0.0, False), (1.0, 0.3, False), (0.4, 0.4, True), (0.0, 1.0, False)]
    t = 0.2
    for e in RIM:
        m = box()
        plan = plan_fillet(m, [edge_at(m, *e)], t, 6, 0.5, "offset", "round", drawn)
        assert not isinstance(plan, str), plan
        on_top = [q for q in plan.strips if all(abs(p.z() - 1.0) < 1e-9 for p in q)]
        assert len(on_top) == 1                       # (1, 0) → (1, 0.3) on top


def test_a_cornice_hangs_from_the_face_that_looks_up():
    """The outline starts on the top face whichever face the edge lists
    first, so a rim reads the same all round: the cornice's first step,
    (1, 0) → (1, 0.125), lies ON the top face as a strip 0.125·t wide."""
    t = 0.2
    for e in RIM:
        m = box()
        plan = plan_fillet(m, [edge_at(m, *e)], t, 12, 0.5, "offset",
                           "round", "cornice")
        assert not isinstance(plan, str), plan
        on_top = [q for q in plan.strips
                  if all(abs(p.z() - 1.0) < 1e-9 for p in q)]
        assert len(on_top) == 1
        quad = on_top[0]
        widths = sorted((quad[i] - quad[(i + 1) % 4]).length() for i in range(4))
        assert widths[0] == pytest.approx(0.125 * t, abs=1e-6)


def test_an_unknown_shape_is_the_superellipse():
    a, b = box(), box()
    pa = plan_fillet(a, [edge_at(a, *TOP_FRONT)], 0.2, 4)
    pb = plan_fillet(b, [edge_at(b, *TOP_FRONT)], 0.2, 4, 0.5, "radius", "round", "nonsense")
    assert pb.shape is None
    assert all((x - y).length() < 1e-9
               for qa, qb in zip(pa.strips, pb.strips) for x, y in zip(qa, qb))
