# SPDX-License-Identifier: GPL-3.0-or-later
"""A point acquired where the operation started does not compete with the
axis it starts (#368, @pacaeiro).

Pausing on a cube's corner acquires it; clicking it then starts a Move from
that very corner. Every line through the start along an axis IS the axis
inference, but the acquired copy offered it again as «From point» — which
outranks the soft axis cue — so dragging along red read «From point» all the
way and even nudged the point off the cursor."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.scene import Scene
from core.snap import compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


def _snap(cand, **kw):
    return compute_snap(cand, _w2p(cand), Scene(), _w2p, threshold_px=9.0,
                        edge_threshold_px=14.0, screen_axis_px=9.0, **kw)


def test_dragging_along_red_from_the_acquired_start_reads_the_axis():
    start = V(4, 0)
    for x in (3.7, 3.3, 2.5, 1.0):
        r = _snap(V(x, 0.02), start_point=start, acquired_point=V(4, 0))
        assert r.kind != "from_point", (x, r.kind)
        assert abs(r.point.x() - x) < 0.02          # no jump off the cursor


def test_another_acquired_point_still_gives_from_point():
    # The inference itself is untouched: a corner OTHER than the start.
    r = _snap(V(2.0, 3.01), start_point=V(0, 0), acquired_point=V(5, 3))
    assert r.kind == "from_point"
