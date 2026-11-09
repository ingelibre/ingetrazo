# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A flat tilted circle is flat however far from the origin it is (#571).

``is_planar`` took the plane's normal from the first two vertices whose
cross product passed 1e-6 — on a circle, two neighbours nearly in line —
and worked it out in single precision, so the normal tilted more the farther
the circle sat from the origin: at 1000 m a third of exactly flat 24-sided
circles were "not planar", did not become faces and were folded into
triangles after a move. The plane now goes through the first vertex and
the two that span the widest triangle with it, in double precision, and
what is really warped is still refused."""
from __future__ import annotations

import math
import random

import pytest
from PySide6.QtGui import QVector3D as V

from core.mesh import Mesh
from core.topology import fold_nonplanar_faces, is_planar


def _frame(rng):
    """A random orthonormal pair (u, w): the plane of a tilted circle."""
    while True:
        a = [rng.gauss(0, 1) for _ in range(3)]
        la = math.sqrt(sum(c * c for c in a))
        if la > 1e-3:
            break
    u = [c / la for c in a]
    t = [1, 0, 0] if abs(u[0]) < 0.9 else [0, 1, 0]
    w = [u[1] * t[2] - u[2] * t[1], u[2] * t[0] - u[0] * t[2],
         u[0] * t[1] - u[1] * t[0]]
    lw = math.sqrt(sum(c * c for c in w))
    return u, [c / lw for c in w]


def _circle(rng, dist, sides=24):
    r = rng.uniform(0.5, 10.0)
    u, w = _frame(rng)
    d = [rng.gauss(0, 1) for _ in range(3)]
    ld = math.sqrt(sum(c * c for c in d))
    o = [dist * c / ld for c in d]
    out = []
    for k in range(sides):
        th = 2 * math.pi * k / sides
        c, s = r * math.cos(th), r * math.sin(th)
        out.append(V(*(o[i] + c * u[i] + s * w[i] for i in range(3))))
    return out


@pytest.mark.parametrize("dist", [0.0, 100.0, 500.0, 1000.0, 5000.0])
def test_flat_tilted_circles_are_planar_far_from_the_origin(dist):
    rng = random.Random(571 + int(dist))
    rejected = sum(not is_planar(_circle(rng, dist)) for _ in range(200))
    assert rejected == 0


def test_a_flat_circle_far_away_is_not_folded_after_a_move():
    rng = random.Random(5710)
    mesh = Mesh()
    for _ in range(20):
        mesh.add_face(_circle(rng, 1000.0))
    faces = len(mesh.faces)
    assert fold_nonplanar_faces(mesh) == []
    assert len(mesh.faces) == faces


@pytest.mark.parametrize("dist", [0.0, 1000.0, 5000.0])
def test_a_lifted_corner_is_still_refused(dist):
    """1 m square, one corner 1.5 mm off the plane: warped beyond the 1 mm
    tolerance. A best-fit plane would share the 1.5 mm out as ±0.4 mm and
    call it flat; a plane through three of its corners does not."""
    o = V(dist, dist * 0.5, dist * 0.25)
    sq = [o + V(0, 0, 0), o + V(1, 0, 0), o + V(1, 1, 0.0015), o + V(0, 1, 0)]
    assert not is_planar(sq)
    flat = [o + V(0, 0, 0), o + V(1, 0, 0), o + V(1, 1, 0.0005), o + V(0, 1, 0)]
    assert is_planar(flat)


@pytest.mark.parametrize("dist", [0.0, 1000.0])
def test_a_bent_outline_is_still_refused(dist):
    """An L folded along its corner — two planes — is not a face."""
    o = V(dist, 0, 0)
    bent = [o + V(0, 0, 0), o + V(2, 0, 0), o + V(2, 1, 0), o + V(1, 1, 0),
            o + V(1, 1, 0.3), o + V(0, 1, 0.3)]
    assert not is_planar(bent)


def test_degenerate_input_stays_refused():
    assert not is_planar([V(0, 0, 0), V(1, 0, 0)])
    assert not is_planar([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0)])
    assert not is_planar([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0), V(3, 0, 0)])


def test_a_figure_eight_is_judged_by_its_points():
    """Two lobes wound opposite ways (their areas cancel): still flat, and
    one point lifted out of it is still refused."""
    pts = [V(0, 0, 0), V(1, 1, 0), V(2, 0, 0), V(2, 1, 0), V(1, 0, 0),
           V(0, 1, 0)]
    assert is_planar(pts)
    assert not is_planar(pts[:3] + [V(2, 1, 0.5)] + pts[4:])
