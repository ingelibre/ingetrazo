# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A box stretched along its length with Ctrl (keep the base), then pulled.

Two Ctrl-pushes in a row leave two kept bases standing one behind the other.
Each hid the other from the orientation rays, so neither read as a partition
and the second came out flipped: the solid reported 2 m³ less than it was.

With the first part then pulled up into a tall block, pulling the second
part's top up against it was refused («would break the solid»): the strip
landing on the tall block's wall was dropped as inside the solid, the side
faces dissolved the crease the kept base stands on, and the base was left
open on three edges."""
from __future__ import annotations

import pytest

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.orient import is_closed, signed_volume
from core.scene import Scene
from tests import test_pushpull_ux as T

V = T.V

W, D, H = 3.46, 3.11, 0.68
L1 = W + 3.30
L2 = L1 + 0.39


def _end(scene, x):
    return next(f for f in scene.faces
                if f.normal().x() > 0.9 and abs(f.centroid().x() - x) < 1e-6)


def _top(scene, x0, x1, z):
    return next(f for f in scene.faces
                if f.normal().z() > 0.9
                and all(abs(v.z() - z) < 1e-6 and x0 - 1e-6 <= v.x() <= x1 + 1e-6
                        for v in f.vertices))


def _stretched(times: int):
    scene = Scene()
    hist = History(scene)
    g = [V(0, 0), V(W, 0), V(W, D), V(0, D)]
    hist.execute(build_add_edges(
        scene, [(g[i], g[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(g))]))
    T._push(scene, scene.faces[0], H)
    T._push(scene, _end(scene, W), L1 - W, keep_base=True)
    if times > 1:
        T._push(scene, _end(scene, L1), L2 - L1, keep_base=True)
    return scene


def _sound(m):
    assert is_closed(m)
    assert all(len(e.faces) >= 2 for e in m.edges)


@pytest.mark.parametrize("times", [1, 2])
def test_kept_bases_stay_partitions(times):
    scene = _stretched(times)
    m = scene.mesh
    _sound(m)
    length = L2 if times > 1 else L1
    assert abs(signed_volume(m) - length * D * H) < 1e-4
    kept = [f for f in m.faces if f.interior]
    assert len(kept) == times
    assert all(abs(f.normal().y()) < 1e-6 and abs(f.normal().z()) < 1e-6
               for f in kept)


@pytest.mark.parametrize("times", [1, 2])
@pytest.mark.parametrize("d", [0.5, 2.0, 2.5])
def test_pulling_up_beside_a_raised_part(times, d):
    scene = _stretched(times)
    T._push(scene, _top(scene, 0, W, H), 2.0)
    before = signed_volume(scene.mesh)
    vp = T._push(scene, _top(scene, W, L1, H), d)
    m = scene.mesh
    assert vp.last_status is None                 # not refused
    _sound(m)
    assert abs(signed_volume(m) - (before + (L1 - W) * D * d)) < 1e-4


def test_pushing_the_raised_parts_wall_out_over_the_rest():
    scene = _stretched(1)
    T._push(scene, _top(scene, 0, W, H), 2.0)
    wall = next(f for f in scene.faces
                if f.normal().x() > 0.9 and abs(f.centroid().x() - W) < 1e-6
                and f.centroid().z() > H)
    before = signed_volume(scene.mesh)
    vp = T._push(scene, wall, 0.3)
    m = scene.mesh
    assert vp.last_status is None                 # not refused
    _sound(m)
    assert abs(signed_volume(m) - (before + 0.3 * D * 2.0)) < 1e-4
