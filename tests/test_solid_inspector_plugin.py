# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid Inspector plugin: the diagnosis must agree with the engine.

The verdicts and volumes come from the same primitives the BIM layer
uses, so whatever this dialog says must match what the takeoff would do."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from plugins.solid_inspector import (                             # noqa: E402
    SolidInspectorDialog, SolidInspectorPanel, SolidInspectorTool,
    inspect_mesh)


def _box(mesh, x0=0.0, y0=0.0, z0=0.0, dx=2.0, dy=2.0, dz=2.0,
         skip_top=False):
    """An axis-aligned box with consistent outward windings (the floor is
    clockwise seen from above — the showcase-script lesson)."""
    P = QVector3D
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    quads = [
        [P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0), P(x0, y0, z0)],
        [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)],
        [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)],
        [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)],
        [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
    ]
    if not skip_top:
        quads.append([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1),
                      P(x0, y1, z1)])
    return [mesh.add_face(q) for q in quads]


# ---- Diagnosis ------------------------------------------------------------

def test_closed_cube_is_watertight_with_volume():
    mesh = Mesh()
    _box(mesh)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is True
    assert rep["open"] == [] and rep["stray"] == [] and rep["over"] == []
    assert abs(rep["volume"] - 8.0) < 1e-6          # 2 × 2 × 2


def test_open_box_reports_the_rim():
    """A box without its top: the four rim edges are open borders — the
    exact edges a user needs to see to close the hole."""
    mesh = Mesh()
    _box(mesh, skip_top=True)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is False
    assert len(rep["open"]) == 4
    assert rep["volume"] is None
    for e in rep["open"]:
        assert abs(e.v0.position.z() - 2.0) < 1e-6   # all on the top rim
        assert abs(e.v1.position.z() - 2.0) < 1e-6


def test_stray_edge_detected():
    mesh = Mesh()
    _box(mesh)
    mesh.add_edge(QVector3D(10, 10, 0), QVector3D(12, 10, 0))
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is False
    assert len(rep["stray"]) == 1 and rep["open"] == []


def test_internal_wall_is_overconnected_but_interior_flag_heals():
    """Two boxes sharing a wall: the shared edges see 3 faces —
    overconnected. Marked interior (what core.orient does), the wall stops
    counting and the union is watertight again — same rule as the engine."""
    mesh = Mesh()
    _box(mesh, dx=2.0)
    shared = _box(mesh, x0=2.0, dx=2.0)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is False and len(rep["over"]) == 4

    # The wall between the boxes is the first quad of the second box's
    # x0-plane... find it: the face whose 4 verts all sit at x == 2.
    for f in mesh.faces:
        if all(abs(v.position.x() - 2.0) < 1e-6 for v in f.loop):
            f.interior = True
    rep2 = inspect_mesh(mesh)
    assert rep2["watertight"] is True
    assert abs(rep2["volume"] - 16.0) < 1e-6         # 4 × 2 × 2 shell


def test_empty_mesh_is_not_a_solid():
    rep = inspect_mesh(Mesh())
    assert rep["watertight"] is False and rep["volume"] is None


# ---- Dialog ---------------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_dialog_rows_and_highlight(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)                  # broken loose solid
    g = Group(Mesh(), name="Caja OK")
    _box(g.mesh)                                     # closed group
    scene.groups.append(g)

    dlg = SolidInspectorDialog(win.viewport, parent=win)
    names = [dlg._table.item(i, 0).text()
             for i in range(dlg._table.rowCount())]
    assert names[0] == "Loose geometry" and "Caja OK" in names
    # The scale figure is a billboard — flat by design, never listed.
    assert not any(getattr(g, "billboard", False) and g.name in names
                   for g in scene.groups)
    assert "Sumari" not in names

    # The group row shows its closed volume.
    i_g = names.index("Caja OK")
    assert "8.000" in dlg._table.item(i_g, 4).text()

    # Highlighting the active row selects the 4 rim edges in the viewport.
    dlg._table.setCurrentCell(0, 0)
    dlg.highlight()
    assert len(scene.selection) == 4
    assert all(e in scene.mesh.edges for e in scene.selection)

    # Highlighting the group row selects the group itself.
    dlg._table.setCurrentCell(i_g, 0)
    dlg.highlight()
    assert scene.selection == {g}
    dlg.close()


def test_dialog_group_edit_context(win):
    """Inside a group the active row inspects THAT mesh, and the group's
    own listing row is not duplicated."""
    scene = win.viewport.scene
    g = Group(Mesh(), name="Caseta")
    _box(g.mesh, skip_top=True)
    scene.groups.append(g)
    scene.begin_group_edit(g)
    try:
        dlg = SolidInspectorDialog(win.viewport, parent=win)
        names = [dlg._table.item(i, 0).text()
                 for i in range(dlg._table.rowCount())]
        assert names[0] == "Open group: Caseta"
        assert names.count("Caseta") == 0            # not listed twice
        assert "4 open borders" in dlg._table.item(0, 3).text()
        dlg.close()
    finally:
        scene.end_group_edit()


def test_tool_metadata_and_singleton(win):
    tool = SolidInspectorTool()
    assert tool.name == "Solid Inspector"
    assert tool.shortcut is None and tool.uses_snap is False
    tool.on_activate(win.viewport)
    first = win._solid_inspector
    tool.on_activate(win.viewport)
    assert win._solid_inspector is first
    first.close()


# ---- Faces: internal and reversed -------------------------------------------

from PySide6.QtGui import QMatrix4x4                              # noqa: E402

from core.orient import signed_volume                             # noqa: E402
from plugins.solid_inspector import (                             # noqa: E402
    RepairSolidsCommand, _problem_text, internal_faces, is_sound,
    problem_items, repair_mesh, reversed_faces)


def _top(mesh, z=2.0):
    return next(f for f in mesh.faces
                if all(abs(v.position.z() - z) < 1e-6 for v in f.loop))


def _two_rooms(mesh):
    """Two 2 × 2 × 2 boxes side by side sharing ONE wall face at x = 2."""
    _box(mesh, dx=2.0)
    _box(mesh, x0=2.0, dx=2.0)
    walls = [f for f in mesh.faces
             if all(abs(v.position.x() - 2.0) < 1e-6 for v in f.loop)]
    assert len(walls) == 2                     # the second box doubled it
    mesh.remove_face(walls[1])
    return walls[0]


def _row(dlg, name):
    names = [dlg._table.item(i, 0).text()
             for i in range(dlg._table.rowCount())]
    return names.index(name)


def test_reversed_face_found_without_touching_the_model():
    mesh = Mesh()
    _box(mesh)
    top = _top(mesh)
    top.loop.reverse()
    loop = list(top.loop)
    rep = inspect_mesh(mesh)
    assert rep["watertight"] is True           # closed, just wound wrong
    assert rep["reversed"] == [top]
    assert is_sound(rep) is False
    assert "1 reversed faces" in _problem_text(rep)
    assert top.loop == loop                    # inspecting changed nothing
    assert all(not f.interior for f in mesh.faces)


def test_inside_out_box_has_every_face_reversed():
    mesh = Mesh()
    _box(mesh)
    for f in mesh.faces:
        f.loop.reverse()
    assert len(reversed_faces(mesh)) == 6


def test_only_the_wrong_piece_is_asked(monkeypatch):
    """Sound pieces are settled by the cheap checks; the parity pass sees
    only the piece that needs it (it costs seconds on big models)."""
    import core.orient
    mesh = Mesh()
    _box(mesh)                                  # sound
    _box(mesh, x0=5.0)                          # inside out
    wrong = mesh.faces[6:]
    for f in wrong:
        f.loop.reverse()
    asked = []
    real = core.orient.orient_outward

    def spy(m, *a, **k):
        asked.append(len(m.faces))
        return real(m, *a, **k)

    monkeypatch.setattr(core.orient, "orient_outward", spy)
    assert set(reversed_faces(mesh)) == set(wrong)
    assert asked == [6]
    for f in wrong:
        f.loop.reverse()
    asked.clear()
    assert reversed_faces(mesh) == [] and asked == []


def test_sound_box_and_open_box_have_nothing_reversed():
    mesh = Mesh()
    _box(mesh)
    assert reversed_faces(mesh) == [] and is_sound(inspect_mesh(mesh))
    open_box = Mesh()
    _box(open_box, skip_top=True)
    assert reversed_faces(open_box) == []      # no inside to look into


def test_doubled_face_is_internal_but_only_the_copy():
    """A second face on the same four corners: the copy is the problem,
    the original is still the box's top."""
    mesh = Mesh()
    _box(mesh)
    top = _top(mesh)
    copy = mesh.add_face([QVector3D(v.position) for v in top.loop])
    rep = inspect_mesh(mesh)
    assert len(rep["over"]) == 4
    assert rep["internal"] == [copy]


def test_unmarked_partition_is_internal():
    mesh = Mesh()
    wall = _two_rooms(mesh)
    assert internal_faces(mesh) == [wall]
    wall.interior = True                       # what the engine would mark
    assert internal_faces(mesh) == []
    assert is_sound(inspect_mesh(mesh))


# ---- Repair -------------------------------------------------------------------

def test_repair_erases_stray_edges():
    mesh = Mesh()
    _box(mesh)
    mesh.add_edge(QVector3D(10, 10, 0), QVector3D(12, 10, 0))
    mesh.add_edge(QVector3D(12, 10, 0), QVector3D(12, 14, 0))
    done = repair_mesh(mesh)
    assert done["stray"] == 2
    assert is_sound(inspect_mesh(mesh))
    assert len(mesh.vertices) == 8             # no orphan corners left


def test_repair_keeps_one_of_a_doubled_face():
    mesh = Mesh()
    _box(mesh)
    mesh.add_face([QVector3D(v.position) for v in _top(mesh).loop])
    done = repair_mesh(mesh)
    assert done["duplicates"] == 1 and len(mesh.faces) == 6
    rep = inspect_mesh(mesh)
    assert is_sound(rep) and abs(rep["volume"] - 8.0) < 1e-6


def test_repair_two_boxes_with_a_doubled_wall():
    """The case the diagnosis test builds: the doubled wall loses its copy,
    the other becomes a marked partition, the union measures 16 m³."""
    mesh = Mesh()
    _box(mesh, dx=2.0)
    _box(mesh, x0=2.0, dx=2.0)
    done = repair_mesh(mesh)
    assert done["duplicates"] == 1 and done["partitions"] == 1
    rep = inspect_mesh(mesh)
    assert is_sound(rep) and abs(rep["volume"] - 16.0) < 1e-6


def test_repair_marks_a_partition_instead_of_erasing_it():
    """A wall between two rooms may be wanted: it is kept, as a partition."""
    mesh = Mesh()
    wall = _two_rooms(mesh)
    done = repair_mesh(mesh)
    assert done["partitions"] == 1 and wall in mesh.faces and wall.interior
    assert is_sound(inspect_mesh(mesh))


def test_repair_caps_a_flat_hole_facing_out():
    mesh = Mesh()
    _box(mesh, skip_top=True)
    done = repair_mesh(mesh)
    assert done["holes"] == 1
    rep = inspect_mesh(mesh)
    assert is_sound(rep) and abs(rep["volume"] - 8.0) < 1e-6
    assert signed_volume(mesh) > 0             # the new top looks up
    assert _top(mesh).normal().z() > 0.99


def test_repair_closes_two_separate_holes():
    """A tube: box without top and floor — two flat rims, two caps."""
    mesh = Mesh()
    faces = _box(mesh, skip_top=True)
    mesh.remove_face(faces[0])
    done = repair_mesh(mesh)
    assert done["holes"] == 2
    rep = inspect_mesh(mesh)
    assert is_sound(rep) and abs(rep["volume"] - 8.0) < 1e-6
    assert signed_volume(mesh) > 0


def test_repair_leaves_a_bent_hole_alone():
    """A box missing its top and its front: the rim runs round a corner,
    so no flat face can close it — it stays listed for the user."""
    mesh = Mesh()
    faces = _box(mesh, skip_top=True)
    mesh.remove_face(faces[1])                 # the y = 0 wall
    before = len(mesh.faces)
    done = repair_mesh(mesh)
    assert done["holes"] == 0 and len(mesh.faces) == before
    assert len(inspect_mesh(mesh)["open"]) == 6


def test_repair_turns_reversed_faces_out():
    mesh = Mesh()
    _box(mesh)
    for f in mesh.faces:
        f.loop.reverse()
    done = repair_mesh(mesh)
    assert done["reversed"] == 6
    assert is_sound(inspect_mesh(mesh)) and signed_volume(mesh) > 0


def test_repair_sound_box_changes_nothing():
    mesh = Mesh()
    _box(mesh)
    loops = [list(f.loop) for f in mesh.faces]
    done = repair_mesh(mesh)
    assert not any(done.values())
    assert [list(f.loop) for f in mesh.faces] == loops


# ---- Undo, groups, navigation ----------------------------------------------

def test_repair_is_one_undo_step(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)
    scene.mesh.add_edge(QVector3D(10, 0, 0), QVector3D(11, 0, 0))
    faces = len(scene.mesh.faces)
    history = win.viewport.history
    history.execute(RepairSolidsCommand([scene.mesh]))
    assert history.last_error is None
    assert is_sound(inspect_mesh(scene.mesh))
    assert history.undo()
    rep = inspect_mesh(scene.mesh)
    assert len(rep["open"]) == 4 and len(rep["stray"]) == 1
    assert len(scene.mesh.faces) == faces
    assert history.redo()
    assert is_sound(inspect_mesh(scene.mesh))


def test_undo_gives_back_the_partition_marks(win):
    scene = win.viewport.scene
    wall = _two_rooms(scene.mesh)
    win.viewport.history.execute(RepairSolidsCommand([scene.mesh]))
    assert wall.interior is True
    win.viewport.history.undo()
    assert wall.interior is False
    win.viewport.history.redo()
    assert wall.interior is True


def test_dialog_repairs_a_group_without_entering_it(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)            # loose, broken, not chosen
    g = Group(Mesh(), name="Caja rota")
    _box(g.mesh, skip_top=True)
    scene.groups.append(g)
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    i = _row(dlg, "Caja rota")
    dlg._table.setCurrentCell(i, 0)
    done = dlg.repair()
    assert done["holes"] == 1
    assert is_sound(inspect_mesh(g.mesh))
    assert len(inspect_mesh(scene.mesh)["open"]) == 4   # loose untouched
    assert dlg._table.currentRow() == i        # the choice survives refresh
    assert "✔" in dlg._table.item(i, 2).text()
    win.viewport.history.undo()
    assert len(inspect_mesh(g.mesh)["open"]) == 4
    dlg.close()


def test_repair_all_is_one_step_and_skips_sound_rows(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)
    broken, sound = Group(Mesh(), name="A"), Group(Mesh(), name="B")
    _box(broken.mesh)
    for f in broken.mesh.faces:
        f.loop.reverse()
    _box(sound.mesh)
    scene.groups += [broken, sound]
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    depth = len(win.viewport.history.undo_stack)
    done = dlg.repair_all()
    assert done["holes"] == 1 and done["reversed"] == 6
    assert len(win.viewport.history.undo_stack) == depth + 1
    for name in ("Loose geometry", "A", "B"):
        assert dlg._table.item(_row(dlg, name), 2).text().startswith("✔")
    assert dlg.repair_all() is None            # nothing left to repair
    dlg.close()


def test_status_says_reversed_on_a_closed_wrong_box(win):
    g = Group(Mesh(), name="Al revés")
    _box(g.mesh)
    _top(g.mesh).loop.reverse()
    win.viewport.scene.groups.append(g)
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    i = _row(dlg, "Al revés")
    assert dlg._table.item(i, 2).text() == "✘ faces reversed"
    # Closed, but a reversed face makes the signed sum lie (8 m³ read as
    # 2.667): no volume until it is turned.
    assert dlg._table.item(i, 4).text() == "—"
    dlg.close()


def test_problem_items_group_a_rim_into_one():
    mesh = Mesh()
    _box(mesh, skip_top=True)
    mesh.add_edge(QVector3D(10, 0, 0), QVector3D(11, 0, 0))
    items = problem_items(inspect_mesh(mesh))
    assert sorted((i["kind"], len(i["ents"])) for i in items) == [
        ("open", 4), ("stray", 1)]


def test_next_problem_selects_and_frames_each_in_turn(win):
    vp = win.viewport
    scene = vp.scene
    _box(scene.mesh, skip_top=True)
    scene.mesh.add_edge(QVector3D(10, 0, 0), QVector3D(11, 0, 0))
    dlg = SolidInspectorDialog(vp, parent=win)
    dlg._table.setCurrentCell(0, 0)
    first = dlg.next_problem()
    assert first["kind"] == "open"
    assert len(first["ents"]) == 4 and scene.selection == set(first["ents"])
    rim = QVector3D(1.0, 1.0, 2.0)                    # the top rim's centre
    assert (vp.camera.target - rim).length() < 1.5
    second = dlg.next_problem()
    assert second["kind"] == "stray"
    assert len(second["ents"]) == 1 and scene.selection == set(second["ents"])
    assert vp.camera.target.x() > 9.0                 # flew to the stray
    assert dlg.next_problem() == first                # and round again
    dlg.close()


def test_next_problem_on_a_placed_group_flies_to_its_placement(win):
    vp = win.viewport
    g = Group(Mesh(), name="Lejos")
    _box(g.mesh, skip_top=True)
    m = QMatrix4x4()
    m.translate(50.0, 0.0, 0.0)
    g.xform = m
    vp.scene.groups.append(g)
    dlg = SolidInspectorDialog(vp, parent=win)
    dlg._table.setCurrentCell(_row(dlg, "Lejos"), 0)
    assert dlg.next_problem() is not None
    assert vp.scene.selection == {g}
    assert 49.0 < vp.camera.target.x() < 53.0
    dlg.close()


def test_nested_pieces_are_listed_and_repaired(win):
    """An imported model made of parts: a container with an empty mesh and
    the pieces one level down. The container is no row of its own; each
    piece is, named by its path, and repairs where it is."""
    vp = win.viewport
    piece = Group(Mesh(), name="Pata")
    _box(piece.mesh, skip_top=True)
    m = QMatrix4x4()
    m.translate(0.0, 30.0, 0.0)
    piece.xform = m
    whole = Group(name="Mesa")
    whole.adopt([piece])
    vp.scene.groups.append(whole)
    dlg = SolidInspectorDialog(vp, parent=win)
    names = [dlg._table.item(i, 0).text()
             for i in range(dlg._table.rowCount())]
    assert "Mesa" not in names
    i = _row(dlg, "Mesa ▸ Pata")
    assert "4 open borders" in dlg._table.item(i, 3).text()
    dlg._table.setCurrentCell(i, 0)
    assert dlg.next_problem() is not None
    assert vp.scene.selection == {whole}       # selected from outside
    assert 28.0 < vp.camera.target.y() < 33.0  # through both placements
    assert dlg.repair()["holes"] == 1
    assert is_sound(inspect_mesh(piece.mesh))
    dlg.close()


def test_instances_of_one_component_are_listed_once(win):
    shared = Mesh()
    _box(shared, skip_top=True)
    a, b = Group(shared, name="Silla"), Group(shared, name="Silla#2")
    for g, x in ((a, 0.0), (b, 5.0)):
        g.xform = QMatrix4x4()
        g.xform.translate(x, 0.0, 0.0)
    win.viewport.scene.groups += [a, b]
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    names = [dlg._table.item(i, 0).text()
             for i in range(dlg._table.rowCount())]
    assert "Silla" in names and "Silla#2" not in names
    dlg.close()


def test_next_problem_on_a_sound_row_returns_none(win):
    g = Group(Mesh(), name="Bien")
    _box(g.mesh)
    win.viewport.scene.groups.append(g)
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    dlg._table.setCurrentCell(_row(dlg, "Bien"), 0)
    assert dlg.next_problem() is None
    dlg.close()


# ---- One problem at a time ---------------------------------------------------

from plugins.solid_inspector import (                             # noqa: E402
    KINDS, repair_item, why_not_repairable)


def test_edges_of_an_internal_face_are_not_a_problem_of_their_own():
    """A doubled top: its four overconnected edges are the copy's doing,
    so walking the problems shows the copy once, not the copy AND its
    edges."""
    mesh = Mesh()
    _box(mesh)
    mesh.add_face([QVector3D(v.position) for v in _top(mesh).loop])
    items = problem_items(inspect_mesh(mesh))
    assert [i["kind"] for i in items] == ["internal"]


def test_edges_shared_by_two_solids_are_listed_but_not_repairable():
    """Two boxes touching along one edge only: no face explains it, and
    which way to separate them is a decision."""
    mesh = Mesh()
    _box(mesh)
    _box(mesh, x0=2.0, z0=2.0)
    items = problem_items(inspect_mesh(mesh))
    assert [i["kind"] for i in items] == ["over"]
    assert why_not_repairable(mesh, items[0])
    assert not any(repair_item(mesh, items[0]).values())


def test_repair_item_each_kind():
    mesh = Mesh()
    _box(mesh, skip_top=True)
    mesh.add_edge(QVector3D(10, 0, 0), QVector3D(11, 0, 0))
    items = problem_items(inspect_mesh(mesh))
    rim = next(i for i in items if i["kind"] == "open")
    stray = next(i for i in items if i["kind"] == "stray")
    assert repair_item(mesh, stray)["stray"] == 1
    rep = inspect_mesh(mesh)
    assert rep["stray"] == [] and len(rep["open"]) == 4  # the hole waits
    assert repair_item(mesh, rim)["holes"] == 1
    assert is_sound(inspect_mesh(mesh))


def test_repair_item_turns_only_the_face_shown():
    mesh = Mesh()
    _box(mesh)
    for f in mesh.faces:
        f.loop.reverse()
    items = problem_items(inspect_mesh(mesh))
    assert len(items) == 6
    assert repair_item(mesh, items[0])["reversed"] == 1
    assert len(problem_items(inspect_mesh(mesh))) == 5


def test_repair_item_internal_face_copy_goes_wall_stays():
    """Two boxes with a doubled wall: the copy comes first and is erased;
    the wall left is then a partition, kept and marked."""
    mesh = Mesh()
    _box(mesh, dx=2.0)
    _box(mesh, x0=2.0, dx=2.0)
    first = problem_items(inspect_mesh(mesh))[0]
    copy = first["ents"][0]
    assert repair_item(mesh, first)["duplicates"] == 1
    assert copy not in mesh.faces
    (second,) = problem_items(inspect_mesh(mesh))
    wall = second["ents"][0]
    assert repair_item(mesh, second)["partitions"] == 1
    assert wall in mesh.faces and wall.interior
    assert is_sound(inspect_mesh(mesh))


def test_bent_hole_says_why(win):
    mesh = Mesh()
    faces = _box(mesh, skip_top=True)
    mesh.remove_face(faces[1])
    repair_mesh(mesh)                          # drops the stray top edge
    (item,) = problem_items(inspect_mesh(mesh))
    assert "not flat" in why_not_repairable(mesh, item)


def test_walk_and_repair_one_by_one(win):
    """Next shows a problem; Repair this problem fixes only it, as one
    undo step, and the next one comes on screen by itself."""
    vp = win.viewport
    scene = vp.scene
    _box(scene.mesh, skip_top=True)
    scene.mesh.add_edge(QVector3D(10, 0, 0), QVector3D(11, 0, 0))
    dlg = SolidInspectorDialog(vp, parent=win)
    dlg._table.setCurrentCell(0, 0)
    assert dlg._fix_btn.isEnabled() is False   # nothing on screen yet
    assert dlg.next_problem()["kind"] == "open"
    assert dlg._fix_btn.isEnabled()
    assert "1 of 2" in dlg._problem_label.text()
    depth = len(vp.history.undo_stack)

    assert dlg.repair_current()["holes"] == 1
    assert len(vp.history.undo_stack) == depth + 1
    cur = dlg._current
    assert cur["item"]["kind"] == "stray" and cur["count"] == 1
    assert "1 of 1" in dlg._problem_label.text()

    assert dlg.repair_current()["stray"] == 1
    assert dlg._current is None
    assert "No problems left" in dlg._problem_label.text()
    assert "✔" in dlg._table.item(0, 2).text()

    vp.history.undo()                          # the stray comes back alone
    rep = inspect_mesh(scene.mesh)
    assert len(rep["stray"]) == 1 and rep["open"] == []
    dlg.close()


def test_previous_goes_back_and_wraps(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)
    scene.mesh.add_edge(QVector3D(10, 0, 0), QVector3D(11, 0, 0))
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    dlg._table.setCurrentCell(0, 0)
    assert dlg.previous_problem()["kind"] == "stray"   # from the end
    assert dlg.previous_problem()["kind"] == "open"
    assert dlg.next_problem()["kind"] == "stray"
    dlg.close()


def test_unrepairable_problem_is_shown_with_its_reason(win):
    scene = win.viewport.scene
    _box(scene.mesh)
    _box(scene.mesh, x0=2.0, z0=2.0)
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    dlg._table.setCurrentCell(0, 0)
    assert dlg.next_problem()["kind"] == "over"
    assert dlg._fix_btn.isEnabled() is False
    assert "separate the solids" in dlg._problem_label.text()
    assert dlg.repair_current() is None
    dlg.close()


def test_problem_is_painted_in_its_colour_and_unpainted_on_close(win):
    """The overlay paints the problem on screen in its kind's colour, also
    for a group the user is not inside; closing the dialog takes it off."""
    from PySide6.QtGui import QImage, QPainter
    vp = win.viewport
    vp.resize(800, 600)
    g = Group(Mesh(), name="Rota")
    _box(g.mesh, skip_top=True)
    g.xform = QMatrix4x4()
    g.xform.translate(20.0, 0.0, 0.0)
    vp.scene.groups.append(g)
    dlg = SolidInspectorDialog(vp, parent=win)
    assert dlg._paint in vp._ext_overlays
    dlg._table.setCurrentCell(_row(dlg, "Rota"), 0)
    dlg.next_problem()

    def painted():
        img = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        dlg._paint(vp, p)
        p.end()
        red = KINDS["open"][1].rgb() & 0xFFFFFF
        return sum(1 for y in range(0, img.height(), 2)
                   for x in range(0, img.width(), 2)
                   if img.pixel(x, y) & 0xFFFFFF == red)

    assert painted() > 50
    dlg.close()
    assert dlg._paint not in vp._ext_overlays
    assert painted() == 0                      # nothing on screen any more


def test_click_on_a_row_flies_to_that_object(win):
    vp = win.viewport
    far = Group(Mesh(), name="Lejana")
    _box(far.mesh)
    far.xform = QMatrix4x4()
    far.xform.translate(0.0, 80.0, 0.0)
    vp.scene.groups.append(far)
    dlg = SolidInspectorDialog(vp, parent=win)
    i = _row(dlg, "Lejana")
    dlg._table.setCurrentCell(i, 0)
    dlg._table.cellClicked.emit(i, 0)
    assert vp.scene.selection == {far}
    assert 78.0 < vp.camera.target.y() < 84.0
    dlg.close()


def test_refresh_does_not_move_the_camera(win):
    vp = win.viewport
    g = Group(Mesh(), name="Quieta")
    _box(g.mesh)
    g.xform = QMatrix4x4()
    g.xform.translate(0.0, 80.0, 0.0)
    vp.scene.groups.append(g)
    dlg = SolidInspectorDialog(vp, parent=win)
    dlg._table.setCurrentCell(_row(dlg, "Quieta"), 0)
    before = QVector3D(vp.camera.target)
    dlg.refresh()
    assert vp.camera.target == before
    dlg.close()


def _count_colour(vp, dlg, kind):
    from PySide6.QtGui import QImage, QPainter
    img = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    dlg._paint(vp, p)
    p.end()
    rgb = KINDS[kind][1].rgb() & 0xFFFFFF
    return sum(1 for y in range(0, img.height(), 2)
               for x in range(0, img.width(), 2)
               if img.pixel(x, y) & 0xFFFFFF == rgb)


def test_highlight_paints_every_problem_of_a_group_in_its_colour(win):
    """Highlight problems on a group you are not inside: all its problems
    on screen at once, each kind in its colour, with a legend — not just
    the group selected."""
    vp = win.viewport
    vp.resize(800, 600)
    g = Group(Mesh(), name="Mezcla")
    _box(g.mesh, skip_top=True)
    g.mesh.add_edge(QVector3D(3, 0, 0), QVector3D(4, 0, 0))
    g.xform = QMatrix4x4()
    g.xform.translate(40.0, 0.0, 0.0)
    vp.scene.groups.append(g)
    dlg = SolidInspectorDialog(vp, parent=win)
    dlg._table.setCurrentCell(_row(dlg, "Mezcla"), 0)
    items = dlg.highlight()
    assert sorted(i["kind"] for i in items) == ["open", "stray"]
    assert vp.scene.selection == {g}
    assert 38.0 < vp.camera.target.x() < 46.0          # framed, placed
    assert _count_colour(vp, dlg, "open") > 50
    assert _count_colour(vp, dlg, "stray") > 5
    legend = dlg._problem_label.text()
    assert "Open border (hole) (1)" in legend and "Stray edges (1)" in legend

    # Going one by one takes over from the highlight.
    assert dlg.next_problem()["kind"] == "open"
    assert dlg._painted == []
    assert _count_colour(vp, dlg, "stray") == 0
    dlg.close()


def test_highlight_selects_the_problems_of_the_geometry_being_edited(win):
    scene = win.viewport.scene
    _box(scene.mesh)
    for f in scene.mesh.faces:
        f.loop.reverse()
    dlg = SolidInspectorDialog(win.viewport, parent=win)
    dlg._table.setCurrentCell(0, 0)
    items = dlg.highlight()
    assert len(items) == 6 and scene.selection == set(scene.mesh.faces)
    dlg.refresh()                               # refresh lets go of it
    assert dlg._painted == []
    dlg.close()


# ---- A tab of the side tray ----------------------------------------------------

def test_the_inspector_is_a_tab_of_the_side_tray(win):
    """Loaded with the app, the inspector is a tray tab beside the model —
    not a window over it — and the menu entry brings it forward."""
    dock = win._solid_inspector_dock
    assert dock.objectName() == "extension_solid_inspector"
    assert dock.widget() is win._solid_inspector
    SolidInspectorTool().on_activate(win.viewport)
    assert not dock.isHidden()


def test_narrow_tab_keeps_object_and_status_and_says_the_rest_below(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)
    panel = SolidInspectorPanel(win.viewport)
    panel.resize(320, 600)
    panel.show()
    table = panel._table
    assert [table.isColumnHidden(c) for c in range(5)] == [
        False, True, False, True, True]
    table.setCurrentCell(0, 0)
    assert "4 open borders" in panel._detail.text()
    assert panel._detail.isVisible()
    panel.resize(700, 600)
    assert not any(table.isColumnHidden(c) for c in range(5))
    assert not panel._detail.isVisible()
    panel.close()


def test_hiding_the_tab_takes_the_colours_off(win):
    scene = win.viewport.scene
    _box(scene.mesh, skip_top=True)
    panel = SolidInspectorPanel(win.viewport)
    panel.show()
    panel._table.setCurrentCell(0, 0)
    assert panel.highlight()
    assert panel._painted
    panel.hide()                                # another tab in front
    assert panel._painted == [] and panel._current is None
    assert panel._paint in win.viewport._ext_overlays   # still listening
    panel.close()
    assert panel._paint not in win.viewport._ext_overlays


def test_showing_the_tab_inspects_again(win):
    panel = SolidInspectorPanel(win.viewport)
    panel.show()
    assert panel._table.item(0, 2).text() == "(empty)"
    panel.hide()
    _box(win.viewport.scene.mesh)               # the model changed meanwhile
    panel.show()
    assert panel._table.item(0, 2).text().startswith("✔")
    panel.close()


def test_the_tab_rejoins_the_others_when_left_alone(win):
    """Restoring a saved layout can leave the inspector alone on a strip
    of its own above the tabs; it rejoins them. Moved to the other side
    of the window, it stays there."""
    from PySide6.QtCore import Qt
    from plugins.solid_inspector import _join_tray
    dock = win._solid_inspector_dock
    win.show()
    win.removeDockWidget(dock)
    win.addDockWidget(win.dockWidgetArea(win.tray), dock)   # alone, same side
    dock.show()
    assert win.tabifiedDockWidgets(dock) == []
    assert _join_tray(win, dock) is True
    assert win.tray in win.tabifiedDockWidgets(dock)
    assert _join_tray(win, dock) is False                   # already there

    other = (Qt.LeftDockWidgetArea
             if win.dockWidgetArea(win.tray) != Qt.LeftDockWidgetArea
             else Qt.RightDockWidgetArea)
    win.removeDockWidget(dock)
    win.addDockWidget(other, dock)                          # the user's choice
    dock.show()
    assert _join_tray(win, dock) is False
    assert win.dockWidgetArea(dock) == other

def test_one_click_on_a_broken_object_shows_its_first_problem_ready(win):
    """One click, not two: the first problem framed and painted, the card
    filled and «Repair this problem» ready to press."""
    vp = win.viewport
    g = Group(Mesh(), name="Rota")
    _box(g.mesh, skip_top=True)
    g.xform = QMatrix4x4()
    g.xform.translate(0.0, 60.0, 0.0)
    vp.scene.groups.append(g)
    panel = SolidInspectorPanel(vp)
    i = _row(panel, "Rota")
    panel._table.setCurrentCell(i, 0)
    panel._table.cellClicked.emit(i, 0)
    cur = panel._current
    assert cur is not None and cur["index"] == 0
    assert cur["item"]["kind"] == "open"
    assert panel._fix_btn.isEnabled()
    assert "1 of 1" in panel._problem_label.text()
    assert vp.scene.selection == {g}
    assert 58.0 < vp.camera.target.y() < 64.0        # framed where it is
    assert panel.repair_current()["holes"] == 1        # and repaired
    panel.close()


def test_one_click_on_a_sound_object_says_so(win):
    g = Group(Mesh(), name="Sana")
    _box(g.mesh)
    win.viewport.scene.groups.append(g)
    panel = SolidInspectorPanel(win.viewport)
    i = _row(panel, "Sana")
    panel._table.setCurrentCell(i, 0)
    panel._table.cellClicked.emit(i, 0)
    assert panel._current is None and not panel._fix_btn.isEnabled()
    assert "No problems left" in panel._problem_label.text()
    panel.close()
