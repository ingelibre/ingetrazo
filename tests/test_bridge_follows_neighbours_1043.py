# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bridge winds its new faces like the faces they join (issue #1043:
«the two faces were not reversed but the bridge was created with the
faces reversed»).

A closed result was already turned outward by ``orient_outward``. An open
one — the usual model: walls, roofs, a terrain — has no outside, so the
sides kept whatever winding the order of the walk gave them, against the
bridged faces half the time. Now each new face winds like its neighbour
across the shared edge (the bridged faces first), and no face that was
already there is ever turned to suit the new ones."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as Q

from core.bridge import bridge, follow_neighbours, profiles_from_selection
from core.mesh import Mesh
from core.orient import is_closed, signed_volume


def _sq(z, x0=0.0, up=True):
    p = [Q(x0, 0, z), Q(x0 + 1, 0, z), Q(x0 + 1, 1, z), Q(x0, 1, z)]
    return p if up else p[::-1]


def _incoherent(faces) -> int:
    uses: dict = {}
    for f in faces:
        for lp in (f.loop, *f.hole_loops):
            n = len(lp)
            for i in range(n):
                a, b = lp[i], lp[(i + 1) % n]
                uses.setdefault(frozenset((id(a), id(b))), []).append(
                    (id(a), id(b)))
    return sum(1 for u in uses.values() if len(u) == 2 and u[0] == u[1])


def _normals(mesh):
    return {f: f.normal() for f in mesh.faces}


def _run(mesh, sel):
    return bridge(mesh, profiles_from_selection(mesh, sel))


@pytest.mark.parametrize("up", [True, False])
@pytest.mark.parametrize("x0", [0.0, 3.0])
def test_faces_of_open_surfaces_get_sides_that_match_them(up, x0):
    """Each face to bridge belongs to an open surface (a flap hangs from
    it), so the result is open: the sides must still wind like the faces
    they leave from — the bottom one facing down, the top one up."""
    m = Mesh()
    a = m.add_face(_sq(0, up=not up))
    # A flap hanging from the bottom face, wound with it: the result is open.
    m.add_face([Q(0, 0, 0), Q(1, 0, 0), Q(1, 0, -1), Q(0, 0, -1)][::1 if up else -1])
    b = m.add_face(_sq(2, x0=x0, up=up))
    before = _normals(m)
    _run(m, {a, b})
    assert not is_closed(m)
    assert all(Q.dotProduct(f.normal(), n) > 0 for f, n in before.items())
    assert _incoherent(m.faces) == 0


@pytest.mark.parametrize("outward", [True, False])
def test_a_roof_between_two_walls_winds_like_the_walls(outward):
    """Two parallel walls bridged along their top edges (two lines): the
    roof is open with the walls, and must face the way they do."""
    m = Mesh()
    w1 = [Q(0, 0, 0), Q(4, 0, 0), Q(4, 0, 3), Q(0, 0, 3)]      # faces -y
    w2 = [Q(0, 5, 0), Q(0, 5, 3), Q(4, 5, 3), Q(4, 5, 0)]      # faces +y
    if not outward:
        w1, w2 = w1[::-1], w2[::-1]
    f1, f2 = m.add_face(w1), m.add_face(w2)
    top1 = m.find_edge(m.vertex_at(Q(0, 0, 3)), m.vertex_at(Q(4, 0, 3)))
    top2 = m.find_edge(m.vertex_at(Q(0, 5, 3)), m.vertex_at(Q(4, 5, 3)))
    sel = {top1, top2}
    new = _run(m, sel)
    assert len(new) == 1
    roof = new[0]
    assert _incoherent(m.faces) == 0
    assert (roof.normal().z() > 0) == outward
    assert f1.normal().y() * (1 if outward else -1) < 0   # walls untouched
    assert f2.normal().y() * (1 if outward else -1) > 0


def test_a_closed_box_is_still_turned_outward():
    m = Mesh()
    a = m.add_face(_sq(0))
    b = m.add_face(_sq(2))
    _run(m, {a, b})
    assert is_closed(m)
    assert abs(signed_volume(m) - 2.0) < 1e-6
    assert _incoherent(m.faces) == 0


def test_follow_neighbours_never_turns_an_old_face():
    m = Mesh()
    old = m.add_face(_sq(0))
    side = m.add_face([Q(0, 0, 0), Q(0, 0, 1), Q(1, 0, 1), Q(1, 0, 0)])
    # Make ``side`` disagree with ``old`` on purpose, then let it follow.
    if _incoherent([old, side]) == 0:
        from core.mesh import turn_face_over
        turn_face_over(side)
    n_old = old.normal()
    turned = follow_neighbours(m, [side], [old])
    assert turned == [side]
    assert Q.dotProduct(old.normal(), n_old) > 0
    assert _incoherent([old, side]) == 0
