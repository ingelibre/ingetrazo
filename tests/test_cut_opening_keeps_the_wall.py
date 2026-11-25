# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A window marked «Cut opening» (PR #1472), moved or erased, melted EVERY
connected coplanar face of the wall into one: the plinth, its paint and its
BIM tag were gone without a word. Closing a hole gives back what the hole
took, and nothing else — and the wall stays closed, a line of it run over by
the opening included."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402

from core import bim, openings  # noqa: E402
from core.edits import build_add_edges  # noqa: E402
from core.group import Group  # noqa: E402
from core.history import (DeleteGroupCommand, History,  # noqa: E402
                          InsertGroupCommand, MoveGroupCommand)
from core.scene import Scene  # noqa: E402
from tests.test_cut_opening_1272 import _closed, _wall, _window  # noqa: E402

RED, BLUE = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)


def _r(p):
    return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))


def _attrs_key(attrs):
    return repr(sorted((k, repr(v)) for k, v in attrs.items()))


def _state(mesh):
    """Faces with their attrs, and edges: everything a heal must give back."""
    faces = sorted((tuple(sorted(_r(p) for p in f.vertices)),
                    tuple(sorted(tuple(sorted(_r(p) for p in h))
                                 for h in f.holes)),
                    _attrs_key(f.attrs)) for f in mesh.faces)
    edges = sorted((*sorted((_r(e.a), _r(e.b))), e.layer or "", e.hidden)
                   for e in mesh.edges)
    return faces, edges


def _side(mesh, y, eps=1e-5):
    return [f for f in mesh.faces
            if all(abs(p.y() - y) < eps for p in f.vertices)]


def _draw(scene, mesh, a, b):
    was, scene.mesh = scene.mesh, mesh
    try:
        build_add_edges(scene, [(a, b)], detect_faces=True).do(scene)
    finally:
        scene.mesh = was


def _model(grouped, front=0.5, back=None, painted=True):
    """A 4 m wall with a plinth drawn on its front (and its back)."""
    scene = Scene()
    mesh = scene.mesh
    if grouped:
        wall = Group(name="Wall")
        scene.groups.append(wall)
        mesh = wall.mesh
    _wall(mesh, length=4)
    for y, z in ((0.0, front), (0.2, back)):
        if z is None:
            continue
        _draw(scene, mesh, V(0, y, z), V(4, y, z))
        for k, f in enumerate(_side(mesh, y)):
            low = max(p.z() for p in f.vertices) < z + 0.01
            if painted:
                f.attrs["color"] = RED if low else BLUE
                f.attrs["back"] = {"color": (0.1, 0.2, 0.3), "mat": "Plaster"}
                if low:
                    f.attrs["layer"] = "Plinths"
                    f.attrs["texture"] = {"path": "/tmp/none.png", "w": 1.0}
            bim.tag_faces([f], "IfcCovering", f"{y}-{'low' if low else 'up'}",
                          10 * int(y * 10) + (1 if low else 2)) \
                if painted else None
        for e in mesh.edges:
            if (abs(e.a.z() - z) < 1e-6 and abs(e.b.z() - z) < 1e-6
                    and abs(e.a.y() - y) < 1e-6 and abs(e.b.y() - y) < 1e-6):
                e.layer = "Lines"
    assert _closed(mesh)
    return scene, History(scene), mesh


CASES = {
    "above the line": dict(z=0.9),
    "sill on the line": dict(z=0.5),
    "head on the line": dict(z=0.1, h=0.4),
    "across the line": dict(z=0.2),
    "door across it": dict(z=0.0, h=2.1, w=0.9),
}


@pytest.mark.parametrize("back", [None, 0.5, 0.8])
@pytest.mark.parametrize("painted", [True, False])
@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("case", list(CASES))
def test_the_wall_comes_back_as_it_was(case, grouped, painted, back):
    scene, history, mesh = _model(grouped, back=back, painted=painted)
    before = _state(mesh)
    g = _window(**CASES[case])
    states = [before]
    net = sum(f.net_area() for f in _side(mesh, 0.0))
    hole = CASES[case].get("w", 1.0) * CASES[case].get("h", 1.2)
    for cmd in (InsertGroupCommand(g), MoveGroupCommand(g, V(0.6, 0, 0)),
                MoveGroupCommand(g, V(0, -2, 0)), MoveGroupCommand(g, V(0, 2, 0)),
                MoveGroupCommand(g, V(1.0, 0, 0)), DeleteGroupCommand(g)):
        history.execute(cmd)
        assert history.last_error is None
        assert _closed(mesh)
        states.append(_state(mesh))
        rec = openings.made(g)
        if rec and rec["a"] and g in scene.groups:
            assert sum(f.net_area() for f in _side(mesh, 0.0)) \
                == pytest.approx(net - hole, abs=1e-4)
    assert states[1] != before and states[3] == before and states[6] == before
    for k in range(len(states) - 1, 0, -1):
        history.undo()
        assert _state(mesh) == states[k - 1]
    for k in range(1, len(states)):
        history.redo()
        assert _state(mesh) == states[k]


def test_an_opening_across_a_line_leaves_nothing_over_the_hole():
    scene, history, mesh = _model(False)
    history.execute(InsertGroupCommand(_window(z=0.2)))
    assert openings.made(scene.groups[0])["a"]
    assert all(len(e.faces) == 2 for e in mesh.edges)
    for tag in (1, 2):
        faces = [f for f in mesh.faces
                 if (f.attrs.get("ifc") or {}).get("id") == tag]
        assert sum(f.net_area() for f in faces) == pytest.approx(
            {1: 2.0 - 0.3, 2: 8.0 - 0.9}[tag], abs=1e-4)


@pytest.mark.parametrize("grouped", [False, True])
def test_several_windows_one_after_another(grouped):
    scene, history, mesh = _model(grouped, back=0.8)
    before = _state(mesh)
    ws = [_window(w=0.6, x=0.2, z=0.9), _window(w=0.6, x=1.2, z=0.2),
          _window(w=0.6, x=2.2, z=0.0, h=2.0), _window(w=0.6, x=3.2, z=0.5)]
    for w in ws:
        history.execute(InsertGroupCommand(w))
        assert _closed(mesh) and openings.made(w)["a"]
    history.execute(MoveGroupCommand(ws[1], V(0, 0, 0.9)))
    history.execute(MoveGroupCommand(ws[0], V(0.1, 0, -0.6)))
    assert _closed(mesh)
    for k in (2, 0, 3, 1):
        history.execute(DeleteGroupCommand(ws[k]))
        assert history.last_error is None and _closed(mesh)
    assert _state(mesh) == before


@pytest.mark.parametrize("grouped", [False, True])
def test_a_line_drawn_up_to_the_jambs_leaves_no_gap(grouped):
    # Drawn after the window, it splits the jambs and not the wall's side of
    # them: the hole closed on that left the wall open along both.
    scene, history, mesh = _model(grouped, front=None)
    g = _window(z=0.2)
    history.execute(InsertGroupCommand(g))
    _draw(scene, mesh, V(0, 0, 0.5), V(1, 0, 0.5))
    _draw(scene, mesh, V(2, 0, 0.5), V(4, 0, 0.5))
    history.execute(DeleteGroupCommand(g))
    assert history.last_error is None
    assert all(len(e.faces) == 2 for e in mesh.edges if e.faces)
    assert bim.face_set_volume(mesh.faces) == pytest.approx(4 * .2 * 2.5, abs=1e-4)
    # The line the user drew is still there.
    assert {(_r(e.a)[0], _r(e.b)[0]) if _r(e.a) < _r(e.b)
            else (_r(e.b)[0], _r(e.a)[0])
            for e in mesh.edges if abs(e.a.z() - 0.5) < 1e-6
            and abs(e.b.z() - 0.5) < 1e-6} == {(0.0, 1.0), (2.0, 4.0)}


def test_repainted_while_the_window_stands_the_hole_closes_in_the_new_paint():
    scene, history, mesh = _model(False)
    g = _window(z=0.2)
    history.execute(InsertGroupCommand(g))
    for f in _side(mesh, 0.0):
        f.attrs["color"] = (0.0, 1.0, 0.0)
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh) and len(_side(mesh, 0.0)) == 2
    assert {f.attrs["color"] for f in _side(mesh, 0.0)} == {(0.0, 1.0, 0.0)}


def test_the_line_erased_while_the_window_stands_stays_erased():
    scene, history, mesh = _model(False, painted=False)
    g = _window(z=0.2)
    history.execute(InsertGroupCommand(g))
    for e in [e for e in mesh.edges if abs(e.a.z() - 0.5) < 1e-6
              and abs(e.b.z() - 0.5) < 1e-6 and abs(e.a.y()) < 1e-6
              and abs(e.b.y()) < 1e-6]:
        # Both halves divide the same two faces: the first erased joins them.
        fs = list(e.faces)
        if len(fs) == 2:
            mesh.dissolve_coplanar_region(fs)
        elif mesh.find_edge(e.v0, e.v1) is e:
            mesh.remove_edge(e)
    assert len(_side(mesh, 0.0)) == 1
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh)
    assert len(mesh.faces) == 6


@pytest.mark.parametrize("x", [1.1, 1.2])
def test_a_panel_inside_the_outline_comes_back(x):
    # A face wholly inside the opening: drawing round it divided nothing and
    # left the wall open.
    scene, history, mesh = _model(False, front=None)
    p = [V(x, 0, 1), V(x + .6, 0, 1), V(x + .6, 0, 2), V(x, 0, 2)]
    for i in range(4):
        _draw(scene, mesh, p[i], p[(i + 1) % 4])
    panel = min(_side(mesh, 0.0), key=lambda f: f.area())
    panel.attrs["color"] = RED
    before = _state(mesh)
    g = _window()
    history.execute(InsertGroupCommand(g))
    assert openings.made(g)["a"] and _closed(mesh)
    assert all(f.attrs.get("color") != RED for f in mesh.faces)
    history.execute(MoveGroupCommand(g, V(1.9, 0, 0)))
    assert _closed(mesh)
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh) and _state(mesh) == before


def test_a_panel_of_the_window_s_own_size_comes_back():
    # Every side of the outline is a line of the wall: nothing around the
    # hole says what the panel was.
    scene, history, mesh = _model(False, front=None)
    p = [V(1, 0, .9), V(2, 0, .9), V(2, 0, 2.1), V(1, 0, 2.1)]
    for i in range(4):
        _draw(scene, mesh, p[i], p[(i + 1) % 4])
    panel = min(_side(mesh, 0.0), key=lambda f: f.area())
    panel.attrs["color"] = RED
    bim.tag_faces([panel], "IfcCovering", "Panel", 7)
    before = _state(mesh)
    g = _window()
    history.execute(InsertGroupCommand(g))
    assert openings.made(g)["a"] and _closed(mesh)
    history.execute(MoveGroupCommand(g, V(1, 0, 0)))
    assert _closed(mesh)
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh) and _state(mesh) == before


def test_what_was_there_survives_a_save(tmp_path):
    from formats.igz import load_into, save_scene
    scene, history, mesh = _model(False, back=0.8)
    g = _window(z=0.2)
    before = _state(mesh)
    history.execute(InsertGroupCommand(g))
    path = tmp_path / "wall.igz"
    save_scene(scene, path)
    again = Scene()
    load_into(again, path)
    w = next(x for x in again.groups if x.name == "Window")
    History(again).execute(DeleteGroupCommand(w))
    assert _closed(again.mesh)
    # JSON brings tuples back as lists: compare the shapes and the tags.
    shape = lambda st: [(f[0], f[1]) for f in st[0]]          # noqa: E731
    assert shape(_state(again.mesh)) == shape(before)
    tags = lambda m: sorted((round(f.net_area(), 3),          # noqa: E731
                             f.attrs["ifc"]["name"], f.attrs["back"]["mat"])
                            for f in m.faces if f.attrs.get("ifc"))
    history.undo()
    assert tags(again.mesh) == tags(mesh)


@pytest.mark.parametrize("z", [0.5, 0.2, 0.9])
@pytest.mark.parametrize("grouped", [False, True])
def test_an_opening_cut_before_notes_were_kept_heals_too(grouped, z):
    # Files saved by 0.6.3: no «was» in the record. The lines that stop at
    # the hole's two sides go on across it.
    scene, history, mesh = _model(grouped, painted=False)
    for e in mesh.edges:
        e.layer = None
    before = _state(mesh)
    g = _window(z=z)
    history.execute(InsertGroupCommand(g))
    g.ext["opening"]["made"].pop("was", None)
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh) and _state(mesh) == before


def test_a_wall_group_rotated_and_moved_keeps_its_plinth():
    scene = Scene()
    history = History(scene)
    _s, _h, mesh = _model(False, back=0.8)
    wall = Group(name="Wall")
    wall.mesh = mesh
    t = QMatrix4x4()
    t.translate(7, 3, 1)
    t.rotate(37, 0, 0, 1)
    wall.xform = t
    history.execute(InsertGroupCommand(wall))
    before = _state(mesh)
    g = _window(z=0.2)
    g.xform = t * g.xform
    history.execute(InsertGroupCommand(g))
    assert openings.made(g)["host"] == wall.uid and _closed(mesh)
    history.execute(MoveGroupCommand(g, t.mapVector(V(0.7, 0, 0))))
    assert _closed(mesh) and openings.made(g)["a"]
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh) and _state(mesh) == before


def test_a_partition_meeting_the_wall_is_not_crossed():
    # A third face stands on the line: it would be left across the hole.
    scene, history, mesh = _model(False)
    mesh.add_face([V(0, 0, 0.5), V(0, -1, 0.5), V(4, -1, 0.5), V(4, 0, 0.5)])
    before = _state(mesh)
    history.execute(InsertGroupCommand(_window(z=0.2)))
    assert _state(mesh) == before


def test_a_door_over_a_joint_of_the_wall_s_foot():
    # The foot is in two pieces where the joint meets it: drawn over again,
    # the door's sill faced the whole front once more.
    scene, history, mesh = _model(False, front=None)
    _draw(scene, mesh, V(2, 0, 0), V(2, 0, 2.5))
    assert len(_side(mesh, 0.0)) == 2 and _closed(mesh)
    before = _state(mesh)
    g = _window(x=1.4, z=0.0, h=2.0)
    history.execute(InsertGroupCommand(g))
    assert openings.made(g)["a"] and _closed(mesh)
    history.execute(DeleteGroupCommand(g))
    assert _closed(mesh) and _state(mesh) == before
