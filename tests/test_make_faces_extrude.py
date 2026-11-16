# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Make Faces and Extrude (core/make_faces_extrude.py): the faces the
selected edges close, each one straight into its own solid group, and the
command in the window."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMenu

from core.group import Group
from core.history import History
from core.make_faces import MakeFacesError
from core.make_faces_extrude import (MakeFacesExtrudeCommand, check,
                                     prism_group)
from core.mesh import Mesh
from core.scene import Scene
from core.solids import is_solid

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
    n = len(pts)
    return [mesh.add_edge(V(*pts[i]), V(*pts[(i + 1) % n])) for i in range(n)]


def _rect(mesh, x0, y0, x1, y1, z=0.0):
    return _loop(mesh, [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])


def _circle(mesh, cx, cy, r, n=24):
    cid = Mesh.next_curve_id()
    pts = [(cx + r * math.cos(2 * math.pi * i / n),
            cy + r * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    edges = _loop(mesh, pts)
    for e in edges:
        e.curve = cid
    return edges


def _run(scene, edges, height, eye=UP):
    history = History(scene)
    cmd = MakeFacesExtrudeCommand(edges, height, eye)
    history.execute(cmd)
    return history, cmd


def _z_span(group):
    zs = [v.position.z() for v in group.mesh.vertices]
    return min(zs), max(zs)


def _volume(mesh):
    """Signed volume by the divergence theorem: positive when every face
    looks out."""
    from core.make_faces_extrude import _newell
    total = 0.0
    for f in mesh.faces:
        n = f.normal()
        area = _newell(f.vertices).length() / 2.0 - sum(
            _newell(h).length() / 2.0 for h in f.holes)
        total += QVector3D.dotProduct(f.vertices[0], n) * area
    return total / 3.0


# ---- The core ----------------------------------------------------------------

def test_a_square_of_lines_becomes_a_closed_box_in_its_own_group():
    scene = Scene()
    edges = _rect(scene.mesh, 0, 0, 2, 1)
    _run(scene, edges, 3.0)
    assert len(scene.groups) == 1
    box = scene.groups[0]
    assert len(box.mesh.faces) == 6 and is_solid(box)
    assert _z_span(box) == pytest.approx((0.0, 3.0))
    assert _volume(box.mesh) == pytest.approx(6.0, rel=1e-6)
    # The face became the solid; the lines are still there, loose.
    assert not scene.mesh.faces
    assert len(scene.mesh.edges) == 4
    assert set(scene.selection) == {box}


def test_two_faces_sharing_an_edge_make_two_separate_solids():
    scene = Scene()
    edges = _rect(scene.mesh, 0, 0, 2, 2) + _rect(scene.mesh, 2, 0, 4, 2)
    _run(scene, edges, 1.0)
    assert len(scene.groups) == 2
    for g in scene.groups:
        assert len(g.mesh.faces) == 6 and is_solid(g)
        assert _volume(g.mesh) == pytest.approx(4.0, rel=1e-6)
    # Neighbours of each other only: both faces gave way to their solids
    # (they used to stay under them, each one the other's "neighbour").
    assert not scene.mesh.faces
    assert len(scene.mesh.edges) == 7


def test_a_negative_height_goes_down_and_stays_outward():
    scene = Scene()
    _run(scene, _rect(scene.mesh, 0, 0, 1, 1), -0.5)
    g = scene.groups[0]
    assert _z_span(g) == pytest.approx((-0.5, 0.0))
    assert is_solid(g) and _volume(g.mesh) == pytest.approx(0.5, rel=1e-6)


def test_a_wall_outline_extrudes_towards_the_camera():
    scene = Scene()
    edges = _loop(scene.mesh, [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)])
    _run(scene, edges, 0.2, eye=QVector3D(1, -30, 0.5))
    ys = [v.position.y() for v in scene.groups[0].mesh.vertices]
    assert min(ys) == pytest.approx(-0.2) and max(ys) == pytest.approx(0.0)


def test_a_room_ringed_by_walls_stays_empty_by_default():
    scene = Scene()
    edges = _rect(scene.mesh, 0, 0, 4, 4) + _rect(scene.mesh, 1, 1, 3, 3)
    _, cmd = _run(scene, edges, 1.0)
    # Only the ring of walls, with the hole through it; the room is not
    # filled, and its face is not left behind either: lines, as it came.
    assert len(scene.groups) == 1 and is_solid(scene.groups[0])
    assert _volume(scene.groups[0].mesh) == pytest.approx(12.0, rel=1e-6)
    assert cmd.result["inner"] == 1
    assert not scene.mesh.faces and len(scene.mesh.edges) == 8


def test_with_fill_holes_the_inner_loop_is_a_solid_too():
    scene = Scene()
    edges = _rect(scene.mesh, 0, 0, 4, 4) + _rect(scene.mesh, 1, 1, 3, 3)
    history = History(scene)
    history.execute(MakeFacesExtrudeCommand(edges, 1.0, UP, fill_holes=True))
    vols = sorted(_volume(g.mesh) for g in scene.groups)
    assert vols == pytest.approx([4.0, 12.0], rel=1e-6)
    assert all(is_solid(g) for g in scene.groups)


def test_an_existing_face_in_the_hole_is_left_as_it_was():
    scene = Scene()
    edges = _rect(scene.mesh, 0, 0, 4, 4) + _rect(scene.mesh, 1, 1, 3, 3)
    floor = scene.mesh.add_face([V(1, 1), V(3, 1), V(3, 3), V(1, 3)])
    _run(scene, edges, 1.0)
    assert len(scene.groups) == 1
    assert floor in scene.mesh.faces


def test_a_circle_stays_round_soft_sides_and_curves_on_both_rings():
    scene = Scene()
    _run(scene, _circle(scene.mesh, 0, 0, 1.0), 2.0)
    g = scene.groups[0]
    assert is_solid(g)
    seams = [e for e in g.mesh.edges
             if abs(e.a.z() - e.b.z()) > 1.0]          # the upright edges
    assert len(seams) == 24 and all(e.soft for e in seams)
    rings = {e.curve for e in g.mesh.edges if e.curve is not None}
    assert len(rings) == 2
    assert not any(e.soft for e in g.mesh.edges
                   if abs(e.a.z() - e.b.z()) < 1e-6)


def test_a_square_keeps_its_corner_edges_visible():
    scene = Scene()
    _run(scene, _rect(scene.mesh, 0, 0, 1, 1), 1.0)
    assert not any(e.soft for e in scene.groups[0].mesh.edges)


def test_paint_and_layer_travel_from_the_face_to_its_solid():
    mesh = Mesh()
    _rect(mesh, 0, 0, 1, 1)
    face = mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    face.attrs.update({"color": (200, 10, 10), "layer": "Walls"})
    g = prism_group(face, 1.0, mesh)
    assert g.layer == "Walls"
    assert all(f.attrs.get("color") == (200, 10, 10) for f in g.mesh.faces)


def test_one_undo_step_takes_it_all_back_and_redo_brings_it():
    scene = Scene()
    edges = _rect(scene.mesh, 0, 0, 2, 1)
    history, _ = _run(scene, edges, 3.0)
    history.undo()
    assert not scene.groups and not scene.mesh.faces
    assert len(scene.mesh.edges) == 4
    history.redo()
    assert len(scene.groups) == 1 and is_solid(scene.groups[0])
    assert not scene.mesh.faces


def test_a_face_that_belongs_to_a_solid_stays_and_gets_a_solid_beside_it():
    scene = Scene()
    # An open box: floor + one wall share an edge; the floor's lines are
    # selected again.
    floor = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    scene.mesh.add_face([V(0, 0), V(0, 0, 1), V(1, 0, 1), V(1, 0)])
    edges = [e for e in scene.mesh.edges
             if abs(e.a.z()) < 1e-9 and abs(e.b.z()) < 1e-9]
    _run(scene, edges, 0.5)
    assert floor in scene.mesh.faces              # not torn out of the box
    assert len(scene.groups) == 1


def test_zero_height_or_open_lines_are_refused_before_anything_changes():
    mesh = Mesh()
    with pytest.raises(MakeFacesError):
        check(_rect(mesh, 0, 0, 1, 1), 0.0)
    open_lines = [mesh.add_edge(V(5, 0), V(6, 0)),
                  mesh.add_edge(V(6, 0), V(6, 1))]
    with pytest.raises(MakeFacesError):
        check(open_lines, 1.0)
    assert not mesh.faces


def test_inside_a_group_the_solids_are_born_in_the_group():
    scene = Scene()
    inner = Mesh()
    _rect(inner, 0, 0, 1, 1)
    group = Group(inner, "plan")
    scene.groups.append(group)
    scene.begin_group_edit(group)
    _run(scene, list(scene.mesh.edges), 1.0)
    assert group.children and len(group.children) == 1
    assert scene.groups == [group]
    scene.end_group_edit()


# ---- Translations ------------------------------------------------------------

_STRINGS = (
    "Make Faces and Extrude…", "Make Faces and Extrude",
    "Make the faces that the selected edges close and extrude each one "
    "into its own solid group.",
    "A negative height extrudes the other way.",
    "Make Faces and Extrude: {n} solids, {h} high",
    "The height cannot be zero.",
    "Extrude inner loops too",
    "Off: a loop inside another is left as a hole (the room inside the "
    "walls, the bore of a tube).\nOn: it becomes a solid of its own too "
    "(a column inside a slab).",
)


def test_every_language_translates_the_new_strings():
    root = Path(__file__).resolve().parent.parent / "i18n"
    for path in sorted(root.glob("*.json")):
        if path.name == "en.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in _STRINGS:
            assert data.get(key), f"{path.name}: {key!r}"
            if "{n}" in key:
                assert "{n}" in data[key] and "{h}" in data[key], path.name


# ---- The window ----------------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    # A new window brings its scale figure: only the groups made here count.
    w.viewport.scene.groups.clear()
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


def test_the_button_and_the_menu_entry_sit_after_make_faces(win):
    act = win._act_make_faces_extrude
    actions = win.toolbars["modify"].actions()
    assert actions.index(act) == actions.index(win._act_make_faces) + 1
    menu = _tools_menu(win).actions()
    assert menu.index(act) == menu.index(win._act_make_faces) + 1
    assert not act.icon().isNull() and act.shortcuts() == []


def test_the_button_asks_the_height_and_extrudes_in_one_step(win,
                                                             monkeypatch):
    scene = win.viewport.scene
    edges = _rect(scene.mesh, 0, 0, 4, 3) + _rect(scene.mesh, 4, 0, 6, 3)
    monkeypatch.setattr(win, "_make_faces_extrude_dialog", lambda: (2.5, False))
    scene.select(edges)
    win._act_make_faces_extrude.trigger()
    assert len(scene.groups) == 2
    assert all(is_solid(g) for g in scene.groups)
    assert all(_z_span(g) == pytest.approx((0.0, 2.5)) for g in scene.groups)
    assert set(scene.selection) == set(scene.groups)
    assert len(win.viewport.history.undo_stack) == 1
    win.viewport.history.undo()
    assert not scene.groups and not scene.mesh.faces


def test_cancelling_the_dialog_changes_nothing(win, monkeypatch):
    scene = win.viewport.scene
    scene.select(_rect(scene.mesh, 0, 0, 1, 1))
    monkeypatch.setattr(win, "_make_faces_extrude_dialog", lambda: None)
    win._on_make_faces_extrude()
    assert not scene.groups and not scene.mesh.faces
    assert not win.viewport.history.undo_stack


def test_open_lines_do_not_even_open_the_dialog(win, monkeypatch):
    scene = win.viewport.scene
    scene.select([scene.mesh.add_edge(V(0, 0), V(1, 0)),
                  scene.mesh.add_edge(V(1, 0), V(1, 1)),
                  scene.mesh.add_edge(V(1, 1), V(2, 1))])
    asked = []
    monkeypatch.setattr(win, "_make_faces_extrude_dialog",
                        lambda: asked.append(1) or (1.0, False))
    win._on_make_faces_extrude()
    assert not asked and not scene.groups
    assert not win.viewport.history.undo_stack


def test_the_dialog_remembers_the_last_height(win, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QCheckBox
    QSettings().setValue(win._MFE_HEIGHT_KEY, 0.75)
    QSettings().setValue(win._MFE_FILL_KEY, False)
    seen = []

    def fake_exec(dlg):
        from views.length_field import LengthSpinBox
        spin = dlg.findChild(LengthSpinBox)
        box = dlg.findChild(QCheckBox)
        seen.append((spin.value(), box.isChecked()))
        spin.setValue(1.25)
        box.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    height, fill = win._make_faces_extrude_dialog()
    assert height == pytest.approx(1.25) and fill is True
    assert seen == [(pytest.approx(0.75), False)]
    assert float(QSettings().value(win._MFE_HEIGHT_KEY)) == pytest.approx(1.25)
    assert QSettings().value(win._MFE_FILL_KEY, type=bool) is True
    # Next time it opens with both.
    seen.clear()
    win._make_faces_extrude_dialog()
    assert seen == [(pytest.approx(1.25), True)]


def test_right_click_offers_it_with_make_faces(win, monkeypatch):
    scene = win.viewport.scene
    edges = _rect(scene.mesh, 0, 0, 1, 1)
    entries = _context_entries(win, monkeypatch, edges)
    assert entries.index("Make Faces and Extrude…") == \
        entries.index("Make Faces") + 1
    assert "Make Faces and Extrude…" not in _context_entries(
        win, monkeypatch, edges[:2])
