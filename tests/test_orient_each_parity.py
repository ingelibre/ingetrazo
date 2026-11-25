# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``orient_outward_each`` is the loop it replaces, bit for bit, at a cost
that does not grow with the selection (0.6.3 modelling test, 20-11).

Push/Pull started on one of many selected faces oriented each of the others
with ``orient_outward(mesh, only=(f,))``, and every call re-read the face's
whole component — triangulated, packed and flooded it — before its few
rays: ~0.2 s a face in a 16 000-face group, 21 s for 100 faces.
``orient_outward_each`` keeps those reads between calls while no face has
been turned. Each case below runs the old loop and the new call from the
same captured state, and every face must come out with the same winding,
the same ``interior`` mark, and the same faces reported turned, in order.
"""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QVector3D

import core.orient as orient_mod
from core.mesh import Mesh, turn_face_over
from core.orient import orient_outward, orient_outward_each


def V(x, y, z):
    return QVector3D(float(x), float(y), float(z))


def _box(m, lo, hi, skip=(), split_top=False):
    """Six faces wound outward; ``skip`` leaves faces out by name;
    ``split_top`` cuts the top into two coplanar faces side by side."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    loops = {"bottom": (0, 3, 2, 1), "top": (4, 5, 6, 7),
             "front": (0, 1, 5, 4), "right": (1, 2, 6, 5),
             "back": (2, 3, 7, 6), "left": (3, 0, 4, 7)}
    faces = []
    for name, loop in loops.items():
        if name in skip:
            continue
        if name == "top" and split_top:
            xm = (x0 + x1) / 2
            faces.append(m.add_face([V(x0, y0, z1), V(xm, y0, z1),
                                     V(xm, y1, z1), V(x0, y1, z1)]))
            faces.append(m.add_face([V(xm, y0, z1), V(x1, y0, z1),
                                     V(x1, y1, z1), V(xm, y1, z1)]))
            continue
        faces.append(m.add_face([p[i] for i in loop]))
    return faces


def _frame(m, ox=10.0):
    """A square ring 4 × 4 with a 2 × 2 hole, 1 high: top and bottom are
    faces with a hole."""
    o = [V(ox, 0, 0), V(ox + 4, 0, 0), V(ox + 4, 4, 0), V(ox, 4, 0)]
    i = [V(ox + 1, 1, 0), V(ox + 3, 1, 0), V(ox + 3, 3, 0), V(ox + 1, 3, 0)]
    up = V(0, 0, 1)
    ot, it = [q + up for q in o], [q + up for q in i]
    faces = [m.add_face(list(reversed(o)), [list(reversed(i))]),   # bottom
             m.add_face(ot, [it])]                                 # top
    for k in range(4):
        a, b = k, (k + 1) % 4
        faces.append(m.add_face([o[a], o[b], ot[b], ot[a]]))       # outer
        faces.append(m.add_face([i[b], i[a], it[a], it[b]]))       # inner
    return faces


def _grid_box(m, n, lo=(0.0, 0.0, 0.0), size=4.0):
    """A cube whose six sides are each cut into n × n faces: one closed
    skin wound one way (the shell path)."""
    x0, y0, z0 = lo
    s = size / n
    faces = []
    for i in range(n):
        for j in range(n):
            a, b = i * s, (i + 1) * s
            c, d = j * s, (j + 1) * s
            faces.append(m.add_face([V(x0 + a, y0 + c, z0), V(x0 + a, y0 + d, z0),
                                     V(x0 + b, y0 + d, z0), V(x0 + b, y0 + c, z0)]))
            faces.append(m.add_face([V(x0 + a, y0 + c, z0 + size), V(x0 + b, y0 + c, z0 + size),
                                     V(x0 + b, y0 + d, z0 + size), V(x0 + a, y0 + d, z0 + size)]))
            faces.append(m.add_face([V(x0 + a, y0, z0 + c), V(x0 + b, y0, z0 + c),
                                     V(x0 + b, y0, z0 + d), V(x0 + a, y0, z0 + d)]))
            faces.append(m.add_face([V(x0 + a, y0 + size, z0 + c), V(x0 + a, y0 + size, z0 + d),
                                     V(x0 + b, y0 + size, z0 + d), V(x0 + b, y0 + size, z0 + c)]))
            faces.append(m.add_face([V(x0, y0 + a, z0 + c), V(x0, y0 + a, z0 + d),
                                     V(x0, y0 + b, z0 + d), V(x0, y0 + b, z0 + c)]))
            faces.append(m.add_face([V(x0 + size, y0 + a, z0 + c), V(x0 + size, y0 + b, z0 + c),
                                     V(x0 + size, y0 + b, z0 + d), V(x0 + size, y0 + a, z0 + d)]))
    return faces


def _state(mesh):
    return [(tuple(id(v) for v in f.loop),
             tuple(tuple(id(v) for v in h) for h in f.hole_loops),
             f.interior) for f in mesh.faces]


def _both(mesh, faces):
    """Old loop and new call from the same state: (old, new) as
    (turned faces' ids, every face's state)."""
    snap = mesh.capture_state()
    for f in mesh.faces:
        f.interior = "unset"
    turned = []
    for f in faces:
        turned.extend(orient_outward(mesh, only=(f,)))
    old = ([id(f) for f in turned], _state(mesh))
    mesh.restore_state(snap)
    for f in mesh.faces:
        f.interior = "unset"
    new = ([id(f) for f in orient_outward_each(mesh, faces)], _state(mesh))
    mesh.restore_state(snap)
    return old, new


def _case_boxes_some_turned():
    m = Mesh()
    a = _box(m, (0, 0, 0), (2, 2, 2))
    b = _box(m, (4, 0, 0), (6, 1, 3))
    turn_face_over(a[1])
    turn_face_over(b[3])
    turn_face_over(b[4])
    return m


def _case_whole_box_inward():
    m = Mesh()
    for f in _box(m, (0, 0, 0), (2, 2, 2)):
        turn_face_over(f)
    _box(m, (5, 0, 0), (7, 2, 2))
    return m


def _case_holed_frame():
    m = Mesh()
    fs = _frame(m)
    turn_face_over(fs[1])                   # the holed top, inverted
    turn_face_over(fs[5])                   # an inner wall
    _box(m, (0, 0, 0), (2, 2, 2))
    return m


def _case_holed_frame_all_inward():
    m = Mesh()
    for f in _frame(m):
        turn_face_over(f)
    return m


def _case_coplanar_neighbours():
    m = Mesh()
    fs = _box(m, (0, 0, 0), (3, 2, 1), split_top=True)
    turn_face_over(fs[2])                   # one half of the split top
    return m


def _case_partition():
    """Two boxes sharing a wall: its edges carry three faces."""
    m = Mesh()
    _box(m, (0, 0, 0), (1, 1, 1))
    fs = _box(m, (1, 0, 0), (2, 1, 1), skip=("left",))
    turn_face_over(fs[0])
    return m


def _case_open_and_closed():
    m = Mesh()
    fs = _box(m, (0, 0, 0), (2, 2, 2), skip=("top",))
    turn_face_over(fs[1])
    gs = _box(m, (4, 0, 0), (6, 2, 2))
    turn_face_over(gs[0])
    return m


def _case_grid_shell(turned=()):
    def build():
        m = Mesh()
        fs = _grid_box(m, 4)
        for k in turned:
            turn_face_over(fs[k])
        return m
    return build


def _case_grid_inward():
    m = Mesh()
    for f in _grid_box(m, 3):
        turn_face_over(f)
    return m


CASES = {
    "boxes-some-turned": _case_boxes_some_turned,
    "whole-box-inward": _case_whole_box_inward,
    "holed-frame": _case_holed_frame,
    "holed-frame-inward": _case_holed_frame_all_inward,
    "coplanar-neighbours": _case_coplanar_neighbours,
    "partition": _case_partition,
    "open-and-closed": _case_open_and_closed,
    "grid-shell": _case_grid_shell(),
    "grid-shell-turned": _case_grid_shell(turned=(3, 17, 40, 41, 77)),
    "grid-inward": _case_grid_inward,
}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("pick", range(4))
def test_each_matches_the_loop(name, pick):
    mesh = CASES[name]()
    faces = list(mesh.faces)
    rng = random.Random(1000 * pick + len(name))
    if pick == 0:
        chosen = faces                                  # every face
    elif pick == 1:
        chosen = faces[::-1][:max(2, len(faces) // 2)]  # reverse order
    else:
        chosen = rng.sample(faces, max(2, len(faces) // 3))
        if pick == 3:
            chosen = chosen + chosen[:2]                # repeats
    old, new = _both(mesh, chosen)
    assert new[0] == old[0], "different faces turned"
    assert new[1] == old[1], "a face came out wound or marked differently"


def test_the_cases_really_turn_faces():
    """The parity above is no parity if nothing is ever turned."""
    turned = 0
    for name, build in CASES.items():
        mesh = build()
        old, _new = _both(mesh, list(mesh.faces))
        turned += len(old[0])
    assert turned > 20


# ---- the cost: one read of the component, not one per face --------------

@pytest.fixture
def reads(monkeypatch):
    calls = []
    real = orient_mod._face_triangles

    def counting(mesh, only=None):
        calls.append(None)
        return real(mesh, only)
    monkeypatch.setattr(orient_mod, "_face_triangles", counting)
    return calls


def test_one_read_for_a_whole_selection_of_one_skin(reads):
    mesh = Mesh()
    faces = _grid_box(mesh, 5)                  # 150 faces, wound outward
    assert orient_outward_each(mesh, faces[:60]) == []
    assert len(reads) == 1


def test_a_turn_reads_the_component_again_once(reads):
    mesh = _case_grid_inward()                   # the whole skin inward
    turned = orient_outward_each(mesh, list(mesh.faces)[:30])
    assert len(turned) == len(mesh.faces)        # turned by the first call
    assert len(reads) == 2                       # read again after it, once


def test_the_loop_it_replaces_read_once_per_face(reads):
    """The control: the old loop re-read the component for every face."""
    mesh = Mesh()
    faces = _grid_box(mesh, 5)
    for f in faces[:60]:
        orient_outward(mesh, only=(f,))
    assert len(reads) == 60


def test_push_pull_takes_its_extra_faces_with_one_read(reads):
    from types import SimpleNamespace

    from tools.pushpull import PushPullTool
    mesh = Mesh()
    faces = _grid_box(mesh, 5)
    scene = SimpleNamespace(mesh=mesh, selection=set(faces[:80]))
    tool = PushPullTool()
    tool._take_extras(faces[0], scene)
    assert len(tool._extra_faces) == 79
    assert len(reads) == 1
