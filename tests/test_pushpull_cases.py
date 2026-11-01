# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «pushpull-casos» bench: Push/Pull cases reported with a file or with
steps that rebuild exactly, each stating what the push must leave.

Every case checks the same contract: the pushed face moved (the volume
changed by what the push swept), the solid is still closed, no edge carries
three faces, nothing was refused. A case that fails today is marked
``xfail(strict=True)`` with the reason, so fixing it flips the mark and the
bench says so. Each reported model is rebuilt here with the geometry that
made it fail (a door a hair out of true, a turned notch), not shipped.

Headless: the same direct tool calls as ``test_pushpull_ux``.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.orient import is_closed, orient_outward, signed_volume
from core.scene import Scene
from formats.igz import load_into, save_scene
from tests import test_pushpull_ux as T

# ---- helpers ---------------------------------------------------------------

def _face(mesh, centre, normal, tol=2e-3):
    """The face whose centroid sits at ``centre`` with a normal along
    ``normal`` (either way)."""
    n = V(*normal).normalized()
    best = None
    for f in mesh.faces:
        if abs(abs(V.dotProduct(f.normal().normalized(), n)) - 1) > 1e-3:
            continue
        d = (f.centroid() - V(*centre)).length()
        if best is None or d < best[0]:
            best = (d, f)
    assert best is not None and best[0] < tol, f"no face at {centre}"
    return best[1]


def _fins(mesh):
    return sum(1 for e in mesh.edges if len(e.faces) > 2)


def _borders(mesh):
    return sum(1 for e in mesh.edges if len(e.faces) == 1)


def _solid_ok(scene, vp, v0, dvol, tol=1e-3):
    m = scene.mesh
    assert vp.last_status is None, vp.last_status
    assert is_closed(m)
    assert _borders(m) == 0
    assert _fins(m) == 0
    assert signed_volume(m) == pytest.approx(v0 + dvol, abs=tol)


def _box(hist, x0, y0, z0, x1, y1, z1):
    P = V
    for loop in ([P(x0, y0, z0), P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0)],
                 [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)],
                 [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)],
                 [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)],
                 [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
                 [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)]):
        hist.execute(AddFaceCommand(loop))


def _boxed(*b):
    scene = Scene()
    hist = History(scene)
    _box(hist, *b)
    return scene, hist


def _lsolid():
    """An L in plan, 2 m high: x 0-2 with its front at y=0, x 2-4 sticking
    out to y=-1 (the #864 bench)."""
    scene = Scene()
    hist = History(scene)
    plan = [(0, 0), (2, 0), (2, -1), (4, -1), (4, 2), (0, 2)]
    hist.execute(AddFaceCommand([V(x, y, 0) for x, y in reversed(plan)]))
    hist.execute(AddFaceCommand([V(x, y, 2) for x, y in plan]))
    for (x0, y0), (x1, y1) in zip(plan, plan[1:] + plan[:1]):
        hist.execute(AddFaceCommand([V(x0, y0, 0), V(x1, y1, 0),
                                     V(x1, y1, 2), V(x0, y0, 2)]))
    return scene, hist


def _toward(face, axis, dist):
    """The signed push distance that moves ``face`` ``dist`` along +axis."""
    return dist if V.dotProduct(face.normal(), V(*axis)) > 0 else -dist


# ---- #1076: a door drawn on a wall, in a plan that has grown ---------------
#
# A floor plan of open-top rooms on a slab. The door faces are hand-drawn
# and a hair out of true; pushing them into the wall was refused at every
# depth: the room floor's plane was read off the pocket's tiny floor, which
# leaned with the door's sill, and missed the far half of the floor's
# outline. Rebuilt: two rooms (7.6 m and 7.6 m) on either side of a 0.2 m
# wall, far from the origin, one door on each side of the wall.

_W0, _W1 = 7.8, 8.0                 # the wall between the rooms (local x)
_X1, _Y1, _H, _SLAB, _T = 16.0, 6.0, 3.0, -0.4, 0.2
_OX, _OY = 8.0, 6.0
_DOORS = {
    # wall face, door span (y), the push that goes into the wall
    "A": (_W0, (2.5, 3.5), -1.0),   # faces room 1 (-x)
    "B": (_W1, (4.0, 5.0), 1.0),    # faces room 2 (+x)
}
_DOOR_H = 2.0


def _plan(door, tilt=0.0, lift=5e-5):
    """The plan with ``door`` drawn: its far foot ``lift`` above the floor
    (the sill leans) and its far top corner ``tilt`` off the wall's plane,
    pushed towards the wall."""
    scene = Scene()
    hist = History(scene)

    def P(x, y, z):
        return V(_OX + x, _OY + y, z)

    F = []

    def rect(*pts):
        F.append([P(*q) for q in pts])

    X1, Y1, H, S, t = _X1, _Y1, _H, _SLAB, _T
    rect((0, 0, S), (0, Y1, S), (X1, Y1, S), (X1, 0, S))
    rect((0, 0, S), (X1, 0, S), (X1, 0, H), (0, 0, H))
    rect((X1, Y1, S), (0, Y1, S), (0, Y1, H), (X1, Y1, H))
    rect((0, Y1, S), (0, 0, S), (0, 0, H), (0, t, H), (0, Y1 - t, H),
         (0, Y1, H))
    rect((X1, 0, S), (X1, Y1, S), (X1, Y1, H), (X1, Y1 - t, H),
         (X1, t, H), (X1, 0, H))
    # wall tops, with a vertex wherever an inner wall meets them
    xs = [t, _W0, _W1, X1 - t]
    F.append([P(0, 0, H), P(X1, 0, H), P(X1, t, H)]
             + [P(x, t, H) for x in reversed(xs)] + [P(0, t, H)])
    F.append([P(0, Y1 - t, H)] + [P(x, Y1 - t, H) for x in xs]
             + [P(X1, Y1 - t, H), P(X1, Y1, H), P(0, Y1, H)])
    for xa, xb in ((0, t), (_W0, _W1), (X1 - t, X1)):
        rect((xa, t, H), (xb, t, H), (xb, Y1 - t, H), (xa, Y1 - t, H))
    # the rooms: floors (a vertex at each door's foot) and outer walls
    (ya, yb), (yc, yd) = _DOORS["A"][1], _DOORS["B"][1]
    la = lift if door == "A" else 0.0
    lb = lift if door == "B" else 0.0
    rect((t, t, 0), (_W0, t, 0), (_W0, ya, 0), (_W0, yb, la),
         (_W0, Y1 - t, 0), (t, Y1 - t, 0))
    rect((_W1, t, 0), (X1 - t, t, 0), (X1 - t, Y1 - t, 0),
         (_W1, Y1 - t, 0), (_W1, yd, lb), (_W1, yc, 0))
    for xa, xb in ((t, _W0), (_W1, X1 - t)):
        rect((xa, t, 0), (xa, t, H), (xb, t, H), (xb, t, 0))
        rect((xa, Y1 - t, 0), (xb, Y1 - t, 0), (xb, Y1 - t, H),
             (xa, Y1 - t, H))
    rect((t, t, 0), (t, Y1 - t, 0), (t, Y1 - t, H), (t, t, H))
    rect((X1 - t, t, 0), (X1 - t, t, H), (X1 - t, Y1 - t, H),
         (X1 - t, Y1 - t, 0))
    # the two faces of the middle wall, the door on one of them
    for name, (x, (y0, y1), side) in _DOORS.items():
        if name != door:
            rect((x, t, 0), (x, y0, 0), (x, y1, 0), (x, Y1 - t, 0),
                 (x, Y1 - t, H), (x, t, H))
            continue
        top = P(x + side * tilt, y1, _DOOR_H)
        foot = P(x, y1, lift)
        F.append([P(x, t, 0), P(x, y0, 0), P(x, y0, _DOOR_H), top, foot,
                  P(x, Y1 - t, 0), P(x, Y1 - t, H), P(x, t, H)])
        F.append([P(x, y0, 0), foot, top, P(x, y0, _DOOR_H)])
    for loop in F:
        hist.execute(AddFaceCommand(loop))
    orient_outward(scene.mesh)
    assert is_closed(scene.mesh) and _fins(scene.mesh) == 0
    x, (y0, y1), _side = _DOORS[door]
    return scene, _face(scene.mesh, (_OX + x, _OY + (y0 + y1) / 2, 1.0),
                        (1, 0, 0), tol=0.05)


@pytest.mark.parametrize("door", sorted(_DOORS))
@pytest.mark.parametrize("depth", [0.05, 0.1, 0.19])
def test_1076_door_pushed_into_the_wall(door, depth):
    scene, f = _plan(door)
    v0, area = signed_volume(scene.mesh), f.area()
    vp = T._push(scene, f, -depth)
    _solid_ok(scene, vp, v0, -area * depth)


@pytest.mark.parametrize("door", sorted(_DOORS))
@pytest.mark.parametrize("tilt,lift,past", [
    (0.0, 5e-5, 0.0), (0.0, 5e-5, 2e-4), (0.0, 5e-5, 0.02),
    # the top corner out of true: the opening reaches the far side a
    # hundredth of a millimetre above the floor's edge and must still
    # meet it, with no sliver and no edge with three faces
    (2e-4, 0.0, 2e-4), (2e-4, 0.0, 0.02),
    # pushed exactly the wall's thickness: three corners meet the far face
    # while the centroid is still short of it
    (2e-4, 0.0, 0.0), (2e-4, 5e-5, 0.0), (1e-4, 5e-5, 0.0),
])
def test_1076_door_pushed_through_the_wall(door, tilt, lift, past):
    """Right onto the far face, or dragged a little past it: a door opening
    (the far wall loses the door's outline at its foot), never a cap poking
    out of the back."""
    scene, f = _plan(door, tilt, lift)
    n = f.normal().normalized()
    thick = _W1 - _W0
    v0, area = signed_volume(scene.mesh), f.area()
    vp = T._push(scene, f, -(thick + past))
    _solid_ok(scene, vp, v0, -area * thick, tol=2e-3)
    # The opening goes right through: nothing faces along the door's normal
    # inside the door's outline any more.
    assert not any(
        abs(abs(V.dotProduct(g.normal().normalized(), n)) - 1) < 1e-3
        and (g.centroid() - f.centroid() - n * V.dotProduct(
            g.centroid() - f.centroid(), n)).length() < 0.05
        for g in scene.mesh.faces)


def test_1076_door_push_survives_save_and_reopen(tmp_path):
    scene, f = _plan("A")
    T._push(scene, f, -0.1)
    sig = (len(scene.mesh.faces), len(scene.mesh.edges),
           round(signed_volume(scene.mesh), 5))
    out = tmp_path / "pp.igz"
    save_scene(scene, out)
    again = Scene()
    load_into(again, out)
    m = again.mesh
    assert (len(m.faces), len(m.edges), round(signed_volume(m), 5)) == sig
    assert is_closed(m) and _fins(m) == 0


@pytest.mark.parametrize("door", sorted(_DOORS))
@pytest.mark.parametrize("tilt", [1e-4, 2e-4, 1e-3])
@pytest.mark.parametrize("depth", [0.1, 0.19])
def test_1076_door_out_of_true_is_not_held_by_its_own_wall(door, tilt, depth):
    """The way a click does it: the push into the wall is clamped by the
    inward limit first. Door A, its top leaning towards the room, read the
    wall it is drawn on as a blocker a few hundredths of a millimetre deep
    and did not move at all; door B, leaning the other way, went in."""
    from tools.pushpull import PushPullTool
    scene, f = _plan(door, tilt)
    v0, area = signed_volume(scene.mesh), f.area()
    tool = PushPullTool()
    tool.base_face = f
    orient_outward(scene.mesh, only=(f,))
    tool._anchor = f.centroid()
    tool._normal = tool._outward_normal(f, scene.mesh)
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._compute_inward_limit(scene)
    assert tool._limit_in is None or tool._limit_in > depth
    tool._cap_positions = tool._cap_loop_positions(f)
    tool.dragging = True
    tool.extrusion = -depth
    tool._clamp_extrusion()
    vp = T._StubViewport(scene)
    tool._commit(vp)
    _solid_ok(scene, vp, v0, -area * depth, tol=2e-3)


# ---- #570: the corner triangle of a turned notch, raised (@pacaeiro) -----
#
# A block with a rectangular notch turned in plan, cut down from the top: it
# leaves a small triangle of floor at the corner. Rebuilt with the same
# shape: the notch's long side meets the front and the right side.

def _turned_notch():
    scene = Scene()
    hist = History(scene)
    w, dp, h, z1 = 1.75, 2.8, 1.65, 1.0
    A, B, C, D = (0.6, 0.5), (1.0, 1.1), (w, 0.6), (1.35, 0.0)
    P = V
    faces = [
        [P(0, 0, 0), P(0, dp, 0), P(w, dp, 0), P(w, 0, 0)],
        [P(0, 0, 0), P(0, 0, h), P(0, dp, h), P(0, dp, 0)],
        [P(0, dp, 0), P(0, dp, h), P(w, dp, h), P(w, dp, 0)],
        [P(*A, z1), P(*A, h), P(*B, h), P(*B, z1)],
        [P(*B, z1), P(*B, h), P(*C, h), P(*C, z1)],
        [P(*D, z1), P(*D, h), P(*A, h), P(*A, z1)],
        [P(0, 0, h), P(*D, h), P(*A, h), P(*B, h), P(*C, h), P(w, dp, h),
         P(0, dp, h)],
        [P(0, 0, 0), P(w, 0, 0), P(w, 0, z1), P(*D, z1), P(*D, h),
         P(0, 0, h)],
        [P(w, 0, 0), P(w, dp, 0), P(w, dp, h), P(*C, h), P(*C, z1),
         P(w, 0, z1)],
        [P(*C, z1), P(*D, z1), P(w, 0, z1)],
        [P(*A, z1), P(*D, z1), P(*C, z1), P(*B, z1)],
    ]
    for loop in faces:
        hist.execute(AddFaceCommand(loop))
    orient_outward(scene.mesh)
    assert is_closed(scene.mesh) and _fins(scene.mesh) == 0
    return scene


@pytest.mark.parametrize("d", [0.3, 0.65, 0.9])
def test_570_corner_triangle_raised(d):
    scene = _turned_notch()
    tri = next(f for f in scene.mesh.faces if len(f.vertices) == 3)
    v0, area = signed_volume(scene.mesh), tri.area()
    s = 1.0 if tri.normal().z() > 0 else -1.0
    vp = T._push(scene, tri, s * d)
    _solid_ok(scene, vp, v0, area * d)


# ---- #957: the floor of a corner notch pushed up (@pacaeiro) ---------------
#
# The block before the failure, rebuilt: 3 x 3 x 2 with a 1.5 x 1.5 corner
# notch down to 0.6.

def _notched():
    scene = Scene()
    hist = History(scene)
    P = V
    top = [(1.5, 0), (3, 0), (3, 3), (0, 3), (0, 1.5), (1.5, 1.5)]
    faces = [
        [P(0, 0, 0), P(0, 3, 0), P(3, 3, 0), P(3, 0, 0)],            # bottom
        [P(x, y, 2) for x, y in top],                                 # top L
        [P(0, 0, 0.6), P(1.5, 0, 0.6), P(1.5, 1.5, 0.6), P(0, 1.5, 0.6)],
        [P(0, 0, 0), P(3, 0, 0), P(3, 0, 2), P(1.5, 0, 2), P(1.5, 0, 0.6),
         P(0, 0, 0.6)],                                               # front
        [P(0, 3, 0), P(0, 0, 0), P(0, 0, 0.6), P(0, 1.5, 0.6), P(0, 1.5, 2),
         P(0, 3, 2)],                                                 # left
        [P(3, 0, 0), P(3, 3, 0), P(3, 3, 2), P(3, 0, 2)],
        [P(3, 3, 0), P(0, 3, 0), P(0, 3, 2), P(3, 3, 2)],
        [P(1.5, 0, 0.6), P(1.5, 0, 2), P(1.5, 1.5, 2), P(1.5, 1.5, 0.6)],
        [P(0, 1.5, 0.6), P(1.5, 1.5, 0.6), P(1.5, 1.5, 2), P(0, 1.5, 2)],
    ]
    for loop in faces:
        hist.execute(AddFaceCommand(loop))
    return scene, hist


@pytest.mark.parametrize("d", [0.7, 1.4, 1.6])
def test_957_notch_floor_pushed_up(d):
    scene, _h = _notched()
    orient_outward(scene.mesh)
    f = _face(scene.mesh, (0.75, 0.75, 0.6), (0, 0, 1))
    v0, area = signed_volume(scene.mesh), f.area()
    vp = T._push(scene, f, _toward(f, (0, 0, 1), d))
    _solid_ok(scene, vp, v0, area * d)


# ---- #864: an L step pushed flush, and what comes after --------------------

@pytest.mark.parametrize("d", [0.5, 1.0, 1.5])
def test_864_step_pushed_back(d):
    scene, _h = _lsolid()
    f = _face(scene.mesh, (3, -1, 1), (0, 1, 0))
    v0, area = signed_volume(scene.mesh), f.area()
    vp = T._push(scene, f, _toward(f, (0, 1, 0), d))
    _solid_ok(scene, vp, v0, -area * d)


@pytest.mark.xfail(strict=True, reason=(
    "#864 (PR, design decision for Marco): a step pushed flush merges the "
    "two front faces; the contact line is not kept, so the half cannot be "
    "pushed again on its own"))
def test_864_step_pushed_flush_keeps_its_outline():
    scene, _h = _lsolid()
    f = _face(scene.mesh, (3, -1, 1), (0, 1, 0))
    T._push(scene, f, _toward(f, (0, 1, 0), 1.0))
    _face(scene.mesh, (3, 0, 1), (0, 1, 0))


def test_864_box_up_and_down():
    scene, _h = _boxed(0, 0, 0, 2, 2, 2)
    v0 = signed_volume(scene.mesh)
    top = _face(scene.mesh, (1, 1, 2), (0, 0, 1))
    T._push(scene, top, _toward(top, (0, 0, 1), 1.0))
    top = _face(scene.mesh, (1, 1, 3), (0, 0, 1))
    vp = T._push(scene, top, _toward(top, (0, 0, 1), -1.0))
    _solid_ok(scene, vp, v0, 0.0)
    assert len(scene.mesh.faces) == 6


def _draw(scene, hist, loop):
    """A closed loop drawn on a face, as the Rectangle tool lays it."""
    hist.execute(build_add_edges(
        scene, [(loop[i], loop[(i + 1) % len(loop)])
                for i in range(len(loop))],
        detect_faces=False, extra=[AddFaceCommand(list(loop), auto=True)],
        plane_rebuild=True))


def _walled():
    scene, hist = _boxed(0, 0, 0, 6, 1, 3)
    _draw(scene, hist, [V(1, 0, 1), V(3, 0, 1), V(3, 0, 2), V(1, 0, 2)])
    return scene, hist


def test_864_window_pulled_out_and_back():
    scene, _h = _walled()
    v0 = signed_volume(scene.mesh)
    w = _face(scene.mesh, (2, 0, 1.5), (0, 1, 0))
    T._push(scene, w, _toward(w, (0, 1, 0), -0.5))
    w = _face(scene.mesh, (2, -0.5, 1.5), (0, 1, 0))
    vp = T._push(scene, w, _toward(w, (0, 1, 0), 0.5))
    _solid_ok(scene, vp, v0, 0.0)


def test_864_window_sunk_and_back():
    scene, _h = _walled()
    v0 = signed_volume(scene.mesh)
    w = _face(scene.mesh, (2, 0, 1.5), (0, 1, 0))
    T._push(scene, w, _toward(w, (0, 1, 0), 0.3))
    w = _face(scene.mesh, (2, 0.3, 1.5), (0, 1, 0))
    vp = T._push(scene, w, _toward(w, (0, 1, 0), -0.3))
    _solid_ok(scene, vp, v0, 0.0)


def test_864_window_through():
    scene, _h = _walled()
    v0 = signed_volume(scene.mesh)
    w = _face(scene.mesh, (2, 0, 1.5), (0, 1, 0))
    vp = T._push(scene, w, _toward(w, (0, 1, 0), 1.0))
    _solid_ok(scene, vp, v0, -2.0)


# ---- #789: a box lengthened with Ctrl, then pushed back --------------------
#
# @renancadastros01-gif's steps (video): a box, its end pushed out with Ctrl
# (a dividing face stays at the old end), then the end pushed back in past
# that division. Refused today: the push crosses an interior partition.

def test_789_box_lengthened_with_ctrl():
    scene, _h = _boxed(0, 0, 0, 2, 1, 1)
    end = _face(scene.mesh, (2, 0.5, 0.5), (1, 0, 0))
    v0, area = signed_volume(scene.mesh), end.area()
    vp = T._push(scene, end, _toward(end, (1, 0, 0), 1.0), keep_base=True)
    assert vp.last_status is None
    assert is_closed(scene.mesh)
    assert signed_volume(scene.mesh) == pytest.approx(v0 + area, abs=1e-6)


@pytest.mark.xfail(strict=True, reason=(
    "#789: pushing the end back across the Ctrl division is refused "
    "(«would break the solid»); the interior partition guard"))
def test_789_end_pushed_back_across_the_division():
    scene, _h = _boxed(0, 0, 0, 2, 1, 1)
    end = _face(scene.mesh, (2, 0.5, 0.5), (1, 0, 0))
    T._push(scene, end, _toward(end, (1, 0, 0), 1.0), keep_base=True)
    end = _face(scene.mesh, (3, 0.5, 0.5), (1, 0, 0))
    v0 = signed_volume(scene.mesh)
    vp = T._push(scene, end, _toward(end, (1, 0, 0), -1.5))
    assert vp.last_status is None
    assert is_closed(scene.mesh)
    assert signed_volume(scene.mesh) == pytest.approx(v0 - 1.5, abs=1e-6)


# ---- #1083: a ring pushed right through a slab (@owzim) --------------------

def _ringed():
    scene, hist = _boxed(0, 0, 0, 4, 3, 0.2)
    P = V
    outer = [P(0.5, 0.5, 0.2), P(3.5, 0.5, 0.2), P(3.5, 2.5, 0.2),
             P(0.5, 2.5, 0.2)]
    inner = [P(1, 1, 0.2), P(3, 1, 0.2), P(3, 2, 0.2), P(1, 2, 0.2)]
    _draw(scene, hist, outer)
    _draw(scene, hist, inner)
    return scene, hist


def _plain(mesh, z, area):
    """The hole-free horizontal face at height ``z`` with ``area`` (the
    slab's own faces share its centroid, so the centroid can't tell)."""
    return next(f for f in mesh.faces
                if not f.holes and abs(f.centroid().z() - z) < 1e-6
                and f.area() == pytest.approx(area, abs=1e-6))


def _ring(scene):
    """The ring itself, not the slab's top (which has the ring as its
    hole and the same centroid)."""
    return next(f for f in scene.mesh.faces
                if f.holes and f.area() == pytest.approx(6.0, abs=1e-4))


def test_1083_ring_pushed_partway():
    scene, _h = _ringed()
    ring = _ring(scene)
    v0, area = signed_volume(scene.mesh), ring.area()
    net = ring.net_area()               # area() is gross, with the hole
    vp = T._push(scene, ring, _toward(ring, (0, 0, 1), -0.1))
    _solid_ok(scene, vp, v0, -net * 0.1)
    assert area > net


@pytest.mark.parametrize("past", [0.0, 0.05])
def test_1083_ring_pushed_through(past):
    """The ring goes right through; the island inside it stays as a block
    of its own (its top where it was, a bottom on the far face), and the
    slab keeps the ring's outline as an opening."""
    scene, hist = _ringed()
    ring = _ring(scene)
    v0, net = signed_volume(scene.mesh), ring.net_area()
    vp = T._push(scene, ring, _toward(ring, (0, 0, 1), -(0.2 + past)))
    m = scene.mesh
    assert vp.last_status is None
    assert is_closed(m) and _fins(m) == 0 and _borders(m) == 0
    assert signed_volume(m) == pytest.approx(v0 - net * 0.2, abs=1e-6)
    bottom = _plain(m, 0.0, 2.0)                          # the island's
    assert bottom.normal().z() < 0
    slab_bottom = next(f for f in m.faces if f.holes
                       and abs(f.centroid().z()) < 1e-6)
    assert slab_bottom.normal().z() < 0
    assert hist.undo() and signed_volume(scene.mesh) == pytest.approx(v0)


def test_1083_round_ring_pushed_through():
    from core.edits import build_add_edges as _bae  # noqa: F401
    import math
    scene, hist = _boxed(0, 0, 0, 4, 4, 0.3)
    P = V

    def circle(r, n=24):
        return [P(2 + r * math.cos(2 * math.pi * k / n),
                  2 + r * math.sin(2 * math.pi * k / n), 0.3)
                for k in range(n)]
    _draw(scene, hist, circle(1.5))
    _draw(scene, hist, circle(0.8))
    ring = next(f for f in scene.mesh.faces if f.holes
                and abs(f.centroid().z() - 0.3) < 1e-6 and len(f.vertices)
                == 24)
    v0, net = signed_volume(scene.mesh), ring.net_area()
    vp = T._push(scene, ring, _toward(ring, (0, 0, 1), -0.3))
    m = scene.mesh
    assert vp.last_status is None
    assert is_closed(m) and _fins(m) == 0 and _borders(m) == 0
    assert signed_volume(m) == pytest.approx(v0 - net * 0.3, abs=1e-5)


def test_1083_ring_around_an_open_window_is_left_alone():
    """A ring framing an opening that already goes through (no island
    face in it) gets no island: the push behaves as before."""
    scene, hist = _boxed(0, 0, 0, 4, 3, 0.2)
    inner = [V(1, 1, 0.2), V(3, 1, 0.2), V(3, 2, 0.2), V(1, 2, 0.2)]
    _draw(scene, hist, inner)
    hole = _plain(scene.mesh, 0.2, 2.0)
    T._push(scene, hole, _toward(hole, (0, 0, 1), -0.2))   # the window
    assert not any(abs(f.centroid().z()) < 1e-6 and not f.holes
                   for f in scene.mesh.faces)
    _draw(scene, hist, [V(0.5, 0.5, 0.2), V(3.5, 0.5, 0.2),
                        V(3.5, 2.5, 0.2), V(0.5, 2.5, 0.2)])
    ring = _ring(scene)
    n_before = len(scene.mesh.faces)
    T._push(scene, ring, _toward(ring, (0, 0, 1), -0.2))
    # Never a cap over the window's back opening.
    assert not any(abs(f.centroid().z()) < 1e-6 and not f.holes
                   and f.area() == pytest.approx(2.0)
                   for f in scene.mesh.faces), n_before


def test_1076_push_past_a_face_in_front_does_not_bite_it():
    """The rim trim past the far face (#1076) is for the face the push
    leaves the material through. A box pulled out past the front of
    another box standing ahead of it, half in its way, leaves that front
    whole."""
    scene = Scene()
    hist = History(scene)
    _box(hist, 0, 0, 0, 2, 1, 1)
    _box(hist, 1, 2, 0, 3, 3, 1.5)
    f = _face(scene.mesh, (1, 1, 0.5), (0, 1, 0))
    T._push(scene, f, _toward(f, (0, 1, 0), 1.5))
    front = _face(scene.mesh, (2, 2, 0.75), (0, 1, 0))
    assert front.area() == pytest.approx(3.0) and not front.holes
