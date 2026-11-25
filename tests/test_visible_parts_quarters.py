# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A face under many covers is worked out quarter by quarter, and comes
out whole.

Seen on the villa in plan: the ground (1 360 m²) lies under 690 000 of the
drawing's 692 726 faces, and taking them all away from the one region,
batch after batch, took 210 s for that face alone — 155 s of the export,
without a word to the progress bar. Under more than a few hundred covers
the engine now cuts the face into quarters, each losing only the covers
over it, and joins the pieces at the end. Here a ground under 900 tiles,
slabs half above and half below it, and pieces that straddle the
quarters' seams: what is left of each face must be what the Python pass
leaves, and the ground one piece with its holes — not cut along the
seams."""
from __future__ import annotations

import numpy as np
import pytest

from core import _native
from core import vista_caras as VC
from core.vista_caras import FaceFill

native = _native.available()
pytestmark = pytest.mark.skipif(
    native is None or not hasattr(native, "visible_parts"),
    reason="Rust engine without visible_parts")


def _square(x, y, s):
    return np.array([(x, y), (x + s, y), (x + s, y + s), (x, y + s)], float)


def _face(ring, near, depth):
    return FaceFill(rings=[ring], rgb=(0, 0, 0), layer="0", opacity=1.0,
                    depth=depth, extra={"near": near})


def _scene():
    rng = np.random.default_rng(7)
    faces = [_face(_square(0.0, 0.0, 30.0), (0.0, 0.0, 0.0), 0.0)]  # ground
    # 900 tiles above it, a gap between each: the ground shows between.
    for i in range(30):
        for j in range(30):
            s = 0.6 + 0.2 * rng.random()
            faces.append(_face(_square(i + 0.1, j + 0.1, s),
                               (0.0, 0.0, 1.0 + 0.001 * (i + j)), 1.0))
    # Slabs that pass in front of the ground on one side only (a tilted
    # nearness plane), and long pieces across the middle seams.
    for k in range(12):
        x = 2.0 + 2.2 * k
        faces.append(_face(_square(x, 5.0 + k, 1.7),
                           (0.3, 0.0, -0.3 * (x + 0.8)), 0.5))
    faces.append(_face(np.array([(3.0, 14.2), (27.0, 14.6), (27.0, 15.4),
                                 (3.0, 15.8)], float), (0.0, 0.0, 2.0), 2.0))
    faces.append(_face(np.array([(14.3, 2.0), (15.7, 2.0), (15.2, 28.0),
                                 (14.8, 28.0)], float), (0.0, 0.0, 2.5), 2.5))
    return faces


def _key(out):
    return sorted((round(f.depth, 6), round(sum(VC._area(r) for r in f.rings), 7),
                   len(f.rings)) for f in out)


def test_a_face_under_hundreds_of_covers_comes_out_whole_as_python_has_it():
    py = VC._visible_parts_py(_scene())
    rust = VC._visible_parts_native(_scene(), native)
    assert len(rust) == len(py)
    ground_py = [f for f in py if f.depth == 0.0]
    ground_rust = [f for f in rust if f.depth == 0.0]
    assert len(ground_py) == len(ground_rust) == 1
    # One outer contour with its holes, as Python has it: the quarters'
    # pieces joined again, no seam left.
    assert len(ground_rust[0].rings) == len(ground_py[0].rings)
    a_py = sum(VC._area(r) for r in ground_py[0].rings)
    a_rust = sum(VC._area(r) for r in ground_rust[0].rings)
    assert abs(a_py - a_rust) < 1e-6, (a_py, a_rust)
    for (d1, a1, n1), (d2, a2, n2) in zip(_key(rust), _key(py)):
        assert d1 == d2 and abs(a1 - a2) < 1e-6 and n1 == n2
