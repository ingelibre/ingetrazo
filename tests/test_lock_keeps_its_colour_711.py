# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Colours of a point found on a lock line (#711, @BastelBaus).

Locked to an axis, a corner lined up onto the line («from point») turned
the draw line orange and painted its guide in the axis it «most» ran
along — blue for a guide that was not parallel to blue at all. The line
keeps the lock's colour now, and the guide is axis-coloured only when it
really runs along that axis, grey otherwise. Only colours: the points are
the same as before."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector3D

from core.snap import (AXIS_COLORS, COLOR_EXTENSION, COLOR_REFERENCE,
                       compute_snap)


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _w2p(p):
    return (p.x() * 100.0 + p.z() * 37.0, -p.y() * 100.0 + p.z() * 23.0)


START = V(0, 0, 0)


def _snap(cand, edges, **lock):
    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=SimpleNamespace(edges=edges),
        world_to_pixel=_w2p, threshold_px=9.0, edge_threshold_px=14.0,
        start_point=START, project_onto_line=project, **lock)


def _edge(a, b):
    return SimpleNamespace(a=a, b=b, center=False)


def test_a_corner_on_the_red_lock_keeps_the_line_red():
    edges = [_edge(V(2, -1), V(6, -1)), _edge(V(6, -1), V(6, 3))]
    hit = _snap(V(6.0, -1.0), edges, axis_lock="x")
    assert hit.kind == "from_point"
    assert hit.lock_color == AXIS_COLORS["x"]
    assert hit.point == V(6, 0)                  # the point itself unchanged


def test_shift_and_reference_locks_carry_theirs():
    edges = [_edge(V(2, -1), V(6, -1)), _edge(V(6, -1), V(6, 3))]
    hit = _snap(V(6.0, -1.0), edges, shift_lock_dir=V(1, 0, 0),
                shift_lock_color=AXIS_COLORS["x"])
    assert hit.lock_color == AXIS_COLORS["x"]
    hit = _snap(V(6.0, -1.0), edges, shift_lock_dir=V(1, 0, 0))
    assert hit.lock_color == COLOR_REFERENCE


def test_a_guide_across_the_axes_is_grey_one_along_an_axis_is_coloured():
    # Locked along X, a corner straight across in Y: the guide runs green.
    straight = [_edge(V(6, -1), V(9, -1))]
    hit = _snap(V(6.0, -1.0), straight, axis_lock="x")
    assert hit.kind == "from_point"
    assert hit.guide_color == AXIS_COLORS["y"]
    # Locked along X, a corner off in Y AND Z: the guide runs across both.
    across = [_edge(V(6, -1, 1), V(9, -1, 1))]
    hit = _snap(V(6.0, -1.0, 1.0), across, axis_lock="x")
    assert hit.kind == "from_point"
    assert hit.guide_color == COLOR_EXTENSION


def test_no_lock_no_lock_colour():
    edges = [_edge(V(2, -1), V(6, -1))]
    hit = _snap(V(2.0, -1.0), edges)
    assert hit is not None and hit.lock_color is None
