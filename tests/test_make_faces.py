# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Make Faces (core/make_faces.py): the faces the selected edges close,
in place, and the command in the window."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMenu

from core.make_faces import MakeFacesError, make_faces, plan, selected_edges
from core.mesh import Mesh

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

UP = QVector3D(0, 0, 50)


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _loop(mesh, pts):
    """Loose lines along ``pts``, closed; returns the edges."""
    n = len(pts)
    return [mesh.add_edge(V(*pts[i]), V(*pts[(i + 1) % n])) for i in range(n)]


def _rect(mesh, x0, y0, x1, y1, z=0.0):
    return _loop(mesh, [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])


def _no_loose(mesh):
    return [e for e in mesh.edges if not e.faces]


# ---- The core ----------------------------------------------------------------

def test_a_square_of_lines_gets_its_face_on_those_lines():
    mesh = Mesh()
    edges = _rect(mesh, 0, 0, 2, 1)
    r = make_faces(mesh, edges, UP)
    assert r["new"] == 1 and len(mesh.faces) == 1
    # The lines are the face's edges: nothing was added or doubled.
    assert len(mesh.edges) == 4 and not _no_loose(mesh)
    assert all(e.faces for e in edges)
    face = mesh.faces[0]
    assert face.normal().z() > 0.99           # a floor looks up
    assert math.isclose(face.area(), 2.0, rel_tol=1e-6)


def test_a_square_drawn_clockwise_still_looks_up():
    mesh = Mesh()
    edges = _loop(mesh, [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)])
    make_faces(mesh, edges, UP)
    assert mesh.faces[0].normal().z() > 0.99


def test_a_wall_loop_faces_the_camera():
    mesh = Mesh()
    edges = _loop(mesh, [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)])
    make_faces(mesh, edges, QVector3D(1, -20, 0.5))
    assert mesh.faces[0].normal().y() < -0.99
    mesh2 = Mesh()
    edges2 = _loop(mesh2, [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)])
    make_faces(mesh2, edges2, QVector3D(1, 20, 0.5))
    assert mesh2.faces[0].normal().y() > 0.99


def test_crossing_rectangles_split_into_three_faces_on_shared_lines():
    mesh = Mesh()
    edges = _rect(mesh, 0, 0, 4, 3) + _rect(mesh, 2, 1, 6, 5)
    r = make_faces(mesh, edges, UP)
    assert r["new"] == 3 and len(mesh.faces) == 3
    # The lines were split where they cross; no shorter edge lies over a
    # longer one and none is left without a face.
    assert len(mesh.edges) == 12 and not _no_loose(mesh)
    assert math.isclose(sum(f.area() for f in mesh.faces), 12 + 16 - 4,
                        rel_tol=1e-6)


def test_lines_at_several_heights_make_one_face_per_level():
    mesh = Mesh()
    edges = _rect(mesh, 0, 0, 3, 3) + _rect(mesh, 0, 0, 1, 1, z=0.9)
    r = make_faces(mesh, edges, UP)
    assert r["new"] == 2
    assert sorted(round(f.vertices[0].z(), 6) for f in mesh.faces) == [0, 0.9]


def test_noise_off_the_plane_is_pulled_onto_it():
    # An imported plan: one corner 0.3 mm high. The face is made on the
    # lines themselves and comes out flat.
    mesh = Mesh()
    edges = _loop(mesh, [(0, 0, 0), (4, 0, 0.0003), (4, 3, 0), (0, 3, 0)])
    edges += _rect(mesh, 2, 1, 6, 5)
    make_faces(mesh, edges, UP)
    assert len(mesh.faces) == 3 and not _no_loose(mesh)
    assert all(abs(v.position.z()) < 1e-6 for v in mesh.vertices)


def test_more_than_a_millimetre_off_is_not_one_plane():
    mesh = Mesh()
    edges = _loop(mesh, [(0, 0, 0), (4, 0, 0.01), (4, 3, 0), (0, 3, 0)])
    with pytest.raises(MakeFacesError):
        plan(edges)
    with pytest.raises(MakeFacesError):
        make_faces(mesh, edges, UP)
    assert not mesh.faces


def test_a_ring_gets_the_wall_with_its_hole_and_the_room():
    mesh = Mesh()
    edges = _rect(mesh, 0, 0, 10, 10) + _rect(mesh, 1, 1, 9, 9)
    r = make_faces(mesh, edges, UP)
    assert r["new"] == 2
    ring = next(f for f in mesh.faces if f.hole_loops)
    assert math.isclose(ring.net_area(), 100 - 64, rel_tol=1e-6)
    assert all(f.normal().z() > 0.99 for f in mesh.faces)


def test_only_the_selected_lines_are_faced():
    mesh = Mesh()
    chosen = _rect(mesh, 0, 0, 1, 1)
    other = _rect(mesh, 5, 0, 6, 1)
    make_faces(mesh, chosen, UP)
    assert len(mesh.faces) == 1
    assert not any(e.faces for e in other)


def test_an_existing_face_is_kept_and_turned_up_not_doubled():
    mesh = Mesh()
    face = mesh.add_face([V(0, 0), V(0, 1), V(1, 1), V(1, 0)])   # looks down
    face.attrs["color"] = [200, 10, 10]
    assert face.normal().z() < 0
    r = make_faces(mesh, list(mesh.edges), UP)
    assert r == {"faces": [face], "new": 0, "kept": 1, "turned": 1,
                 "covered": 0}
    assert mesh.faces == [face] and face.normal().z() > 0.99
    assert face.attrs["color"] == [200, 10, 10]


def test_a_face_of_a_solid_keeps_its_winding():
    mesh = Mesh()
    bottom = mesh.add_face([V(0, 0), V(0, 1), V(1, 1), V(1, 0)])  # down
    mesh.add_face([V(0, 0), V(1, 0), V(1, 0, 1), V(0, 0, 1)])
    edges = [mesh.find_edge(a, b) for a, b in
             zip(bottom.loop, bottom.loop[1:] + bottom.loop[:1])]
    r = make_faces(mesh, edges, UP)
    assert r["kept"] == 1 and r["turned"] == 0
    assert bottom.normal().z() < 0


def test_lines_inside_an_existing_face_are_not_covered_twice():
    mesh = Mesh()
    mesh.add_face([V(0, 0), V(10, 0), V(10, 10), V(0, 10)])
    inner = _rect(mesh, 2, 2, 4, 4)
    r = make_faces(mesh, inner, UP)
    assert r["new"] == 0 and r["covered"] == 1 and len(mesh.faces) == 1


def test_open_lines_close_no_loop():
    mesh = Mesh()
    edges = [mesh.add_edge(V(0, 0), V(1, 0)), mesh.add_edge(V(1, 0), V(1, 1))]
    with pytest.raises(MakeFacesError):
        plan(edges)
    with pytest.raises(MakeFacesError):
        plan([])


def test_a_circle_keeps_its_curve():
    mesh = Mesh()
    pts = [(math.cos(2 * math.pi * i / 24), math.sin(2 * math.pi * i / 24), 0)
           for i in range(24)]
    edges = _loop(mesh, pts)
    cid = mesh.tag_curve([V(*p) for p in pts])
    assert cid is not None
    make_faces(mesh, edges, UP)
    assert len(mesh.faces) == 1 and len(mesh.edges) == 24
    assert len({e.curve for e in mesh.edges}) == 1
    assert next(iter(mesh.edges)).curve is not None


def test_selected_edges_ignores_what_is_not_an_edge_of_the_mesh():
    mesh = Mesh()
    edges = _rect(mesh, 0, 0, 1, 1)
    face = mesh.add_face([V(3, 0), V(4, 0), V(4, 1), V(3, 1)])
    stray = Mesh().add_edge(V(0, 0), V(9, 9))
    got = selected_edges(mesh, edges + [face, stray])
    assert set(map(id, got)) == set(map(id, edges))


# ---- The window ----------------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


class _NoExecMenu(QMenu):
    opened: list = []

    def exec(self, *args, **kwargs):        # noqa: A003 - Qt's name
        _NoExecMenu.opened.append(self)
        return None


def _context_entries(win, monkeypatch, selection):
    import views.main_window as mw
    _NoExecMenu.opened.clear()
    monkeypatch.setattr(mw, "QMenu", _NoExecMenu)
    win.viewport.scene.select(list(selection))
    win.show_viewport_context_menu(QPoint(0, 0))
    assert _NoExecMenu.opened
    return [a.text() for a in _NoExecMenu.opened[0].actions()]


def _tools_menu(win):
    bar = win.menuBar()
    return next(a.menu() for a in bar.actions() if a.text() == "Tools")


def test_the_button_and_the_menu_entry_sit_after_bridge(win):
    act = win._act_make_faces
    actions = win.toolbars["modify"].actions()
    assert actions.index(act) == actions.index(win._act_bridge) + 1
    menu = _tools_menu(win).actions()
    assert menu.index(act) == menu.index(win._act_bridge) + 1
    assert not act.icon().isNull() and act.shortcuts() == []


def test_the_button_faces_the_selection_in_one_undo_step(win):
    scene = win.viewport.scene
    edges = _rect(scene.mesh, 0, 0, 4, 3) + _rect(scene.mesh, 2, 1, 6, 5)
    scene.select(edges)
    win._act_make_faces.trigger()
    assert len(scene.mesh.faces) == 3
    # The new faces end up selected, ready for Push/Pull.
    assert set(map(id, scene.selection)) == set(map(id, scene.mesh.faces))
    win.viewport.history.undo()
    assert not scene.mesh.faces and len(scene.mesh.edges) == 8
    win.viewport.history.redo()
    assert len(scene.mesh.faces) == 3


def test_a_selection_that_makes_nothing_leaves_no_undo_step(win):
    scene = win.viewport.scene
    edges = [scene.mesh.add_edge(V(0, 0), V(1, 0)),
             scene.mesh.add_edge(V(1, 0), V(1, 1)),
             scene.mesh.add_edge(V(1, 1), V(2, 1))]
    scene.select(edges)
    win._on_make_faces()
    assert not scene.mesh.faces
    assert not win.viewport.history.undo_stack


def test_inside_a_group_the_faces_stay_in_the_group(win):
    from core.group import Group
    scene = win.viewport.scene
    inner = Mesh()
    _rect(inner, 0, 0, 1, 1)
    group = Group(inner, "plan")
    scene.groups.append(group)
    scene.begin_group_edit(group)
    scene.select(list(scene.mesh.edges))
    win._on_make_faces()
    assert len(scene.mesh.faces) == 1
    assert not scene.loose_mesh.faces
    scene.end_group_edit()
    assert len(group.mesh.faces) == 1


def test_right_click_offers_make_faces_for_edges(win, monkeypatch):
    scene = win.viewport.scene
    edges = _rect(scene.mesh, 0, 0, 1, 1)
    assert "Make Faces" in _context_entries(win, monkeypatch, edges)
    assert "Make Faces" not in _context_entries(win, monkeypatch, edges[:2])
