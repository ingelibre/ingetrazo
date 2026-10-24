# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two rooms drawn side by side on the plan; the left one is raised and then
pushed down below the plan, so the right room's corners sit partway up its
walls.

Found by the engine fuzz (plan, seed 127) once #550 wound the raised room
outward: pushing the back wall dragged the right room's corner along and
skewed it, and a later push folded a wall into a zero-area sliver around
that corner."""
from __future__ import annotations

import pytest
from tests import test_fuzz_engine as F

RIGHT_ROOM = {(3.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0), (3.0, 4.0, 0.0)}


def _p(v):
    return (round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))


def _c(v, axis):
    return getattr(v, axis)()


def _face(scene, axis, at):
    return next(f for f in scene.mesh.faces
                if abs(_c(f.normal(), axis)) > 0.99
                and all(abs(_c(v, axis) - at) < 1e-6 for v in f.vertices)
                and f.centroid().x() < 3)


def _push(scene, hist, face, axis, d):
    n = _c(face.normal(), axis)
    assert F._push(scene, hist, face, d if n > 0 else -d)


def _model():
    scene, hist, user = F._build("plan")
    _push(scene, hist, _face(scene, "z", 0.0), "z", 1.0)
    _push(scene, hist, _face(scene, "z", 1.0), "z", -1.5)
    return scene, hist, user


def _right_room_intact(scene):
    return any({_p(v) for v in f.vertices} == RIGHT_ROOM
               for f in scene.mesh.faces)


def test_the_room_raised_beside_a_sheet_faces_outward():
    scene, _, _ = F._build("plan")
    assert _face(scene, "z", 0.0).normal().z() < 0


def test_pushing_the_back_wall_leaves_the_next_room_alone():
    scene, hist, user = _model()
    pre = F._pre_state(scene)
    _push(scene, hist, _face(scene, "y", 4.0), "y", 1.0)
    F._check_all(scene, pre, user, "back wall")
    assert _right_room_intact(scene)


@pytest.mark.parametrize("d", [0.3, 1.0, 50.0])
def test_raising_the_floor_past_the_next_rooms_corner(d):
    scene, hist, user = _model()
    pre = F._pre_state(scene)
    _push(scene, hist, _face(scene, "z", -0.5), "z", d)
    F._check_all(scene, pre, user, f"floor up {d}")
    assert _right_room_intact(scene)


def test_collapsing_the_back_wall_onto_the_front():
    scene, hist, user = _model()
    _push(scene, hist, _face(scene, "y", 4.0), "y", 1.0)
    pre = F._pre_state(scene)
    _push(scene, hist, _face(scene, "y", 5.0), "y", -50.0)
    F._check_all(scene, pre, user, "collapse")
    assert _right_room_intact(scene)
