# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""#551: Rotate+Ctrl must subdivide coplanar overlaps instead of stacking faces."""
from collections import Counter
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.history import EraseSelectionCommand, History, rotation_matrix
from core.mesh import Mesh
from core.scene import Scene
from tests.test_explode_merges_shared_walls_721 import _covers
from tests.test_rotate_array import _rotate_copy, _Vp
from tools.rotate import RotateTool


def _rectangle(scene, u=V(1, 0, 0), v=V(0, 1, 0), hole=False):
    def p(x, y):
        return u * x + v * y
    loop = [p(-2, -1), p(2, -1), p(2, 1), p(-2, 1)]
    holes = [[p(-0.5, -0.5), p(0.5, -0.5), p(0.5, 0.5), p(-0.5, 0.5)]]
    return scene.mesh.add_face(loop, holes if hole else None)


def _rotate(scene, face, angles, axis=V(0, 0, 1), center=V()):
    tool = RotateTool()
    tool.start_point = center
    tool._custom_axis = axis
    tool._copy = True
    tool._sel_faces = [face]
    tool._sel_edges = [e for e in scene.mesh.edges if face in e.faces]
    history = History(scene)
    history.execute(tool._make_builder()(angles))
    assert history.last_error is None
    assert history.last_rejected is None
    return history


def _area(scene):
    return sum(f.net_area() for f in scene.mesh.faces)


def _geometry(mesh):
    def loop(points):
        keys = tuple((round(p.x(), 5), round(p.y(), 5), round(p.z(), 5))
                     for p in points)
        return min(keys[i:] + keys[:i] for i in range(len(keys)))
    return Counter((loop(f.vertices), tuple(sorted(loop(h) for h in f.holes)))
                   for f in mesh.faces)


@pytest.mark.parametrize("u,v", [
    (V(1, 0, 0), V(0, 1, 0)),
    (V(1, 0, 0), V(0, 0, 1)),
    (V(1, -1, 0).normalized(), V(1, 1, -2).normalized()),
])
def test_rotated_overlap_is_covered_once_on_any_plane(u, v):
    scene = Scene()
    source = _rectangle(scene, u, v)
    _rotate(scene, source, [90], V.crossProduct(u, v).normalized())
    assert _area(scene) == pytest.approx(12, abs=1e-4)
    assert sorted(f.net_area() for f in scene.mesh.faces) == pytest.approx([2, 2, 2, 2, 4])
    assert _covers(scene.mesh, u * 0.2 + v * 0.3) == 1


@pytest.mark.parametrize("angle,area", [(-90, 12), (180, 8), (360, 8)])
def test_clockwise_and_coincident_copies_do_not_double_count(angle, area):
    scene = Scene()
    source = _rectangle(scene)
    _rotate(scene, source, [angle])
    assert _area(scene) == pytest.approx(area, abs=1e-4)
    assert _covers(scene.mesh, V(0.2, 0.3, 0)) == 1


def test_overlapping_array_is_one_exact_undo_redo_step():
    scene = Scene()
    source = _rectangle(scene)
    vertices, edges = list(scene.mesh.vertices), list(scene.mesh.edges)
    history = _rotate(scene, source, [90, 180, 270])
    assert _area(scene) == pytest.approx(12)
    result = _geometry(scene.mesh)
    for _ in range(3):
        assert history.undo()
        assert scene.mesh.faces == [source]
        assert scene.mesh.edges == edges and scene.mesh.vertices == vertices
        assert history.redo()
        assert _geometry(scene.mesh) == result
    assert len(history.undo_stack) == 1


def test_copies_can_overlap_each_other_without_touching_the_source():
    scene = Scene()
    face = scene.mesh.add_face([V(2, -0.5, 0), V(4, -0.5, 0),
                                V(4, 0.5, 0), V(2, 0.5, 0)])
    _rotate(scene, face, [85, 95])
    assert face in scene.mesh.faces
    assert _covers(scene.mesh, V(0.02, 3.03, 0)) == 1
    assert 4 < _area(scene) < 6


def test_a_shared_hole_stays_open_and_attributes_survive():
    scene = Scene()
    face = _rectangle(scene, hole=True)
    face.attrs.update(color=(12, 34, 56), ifc_class="IfcSlab")
    _rotate(scene, face, [90])
    assert _area(scene) == pytest.approx(11)
    assert _covers(scene.mesh, V(0.1, 0.2, 0)) == 0
    assert all(f.attrs == face.attrs for f in scene.mesh.faces)
    assert all(f.normal().z() > 0.99 for f in scene.mesh.faces)


def test_reversed_face_winding_survives_the_merge():
    scene = Scene()
    face = _rectangle(scene, v=V(0, -1, 0))
    _rotate(scene, face, [90])
    assert _area(scene) == pytest.approx(12)
    assert all(f.normal().z() < -0.99 for f in scene.mesh.faces)


def test_split_boundaries_keep_their_soft_and_curve_flags():
    scene = Scene()
    face = _rectangle(scene)
    curve = Mesh.next_curve_id()
    for edge in scene.mesh.edges:
        edge.soft, edge.curve = True, curve
    history = _rotate(scene, face, [90])
    assert _area(scene) == pytest.approx(12)
    assert all(e.soft and e.curve is not None for e in scene.mesh.edges)
    history.undo()
    assert all(e.soft and e.curve == curve for e in scene.mesh.edges)
    history.redo()
    assert all(e.soft and e.curve is not None for e in scene.mesh.edges)


def test_disjoint_copy_leaves_unrelated_coincident_faces_untouched():
    scene = Scene()
    face = scene.mesh.add_face([V(2, 0, 0), V(4, 0, 0), V(4, 1, 0), V(2, 1, 0)])
    loop = [V(20, 20, 0), V(21, 20, 0), V(21, 21, 0), V(20, 21, 0)]
    a, b = scene.mesh.add_face(loop), scene.mesh.add_face(loop)
    history = _rotate(scene, face, [90])
    assert all(f in scene.mesh.faces for f in (face, a, b))
    assert len(scene.mesh.faces) == 4
    history.undo()
    assert scene.mesh.faces == [face, a, b]


def test_merging_an_overlap_does_not_rebuild_a_distant_face():
    scene = Scene()
    face = _rectangle(scene)
    far = scene.mesh.add_face([V(20, 20, 0), V(21, 20, 0), V(21, 21, 0), V(20, 21, 0)])
    before = _geometry(SimpleNamespace(faces=[far]))
    _rotate(scene, face, [90])
    assert far in scene.mesh.faces
    assert _geometry(SimpleNamespace(faces=[far])) == before
    assert _area(scene) == pytest.approx(13)


def test_the_new_shared_edges_can_be_erased_and_both_edits_undo():
    scene = Scene()
    source = _rectangle(scene)
    history = _rotate(scene, source, [90])
    result = _geometry(scene.mesh)
    a, b = scene.mesh.vertex_at(V(1, -1, 0)), scene.mesh.vertex_at(V(1, 1, 0))
    assert a is not None and b is not None
    shared = scene.mesh.find_edge(a, b)
    assert shared is not None and len(shared.faces) == 2
    history.execute(EraseSelectionCommand([shared]))
    assert history.last_error is None
    assert _area(scene) == pytest.approx(12) and len(scene.mesh.faces) == 4
    assert history.undo() and _geometry(scene.mesh) == result
    assert history.undo() and scene.mesh.faces == [source]
    assert history.redo() and history.redo()
    assert _area(scene) == pytest.approx(12) and len(scene.mesh.faces) == 4


def test_a_disjoint_complex_copy_keeps_all_supplied_faces():
    from pathlib import Path
    from core.geometry import Face
    from formats.igz import load_into

    document = Scene()
    load_into(document, Path(__file__).resolve().parents[1]
              / "examples" / "banca-pergola-yanque.igz")

    def walk(groups):
        for group in groups:
            yield group
            yield from walk(group.children or ())

    mesh = next(g.mesh for g in walk(document.groups) if g.name == "Group 7")
    scene = Scene(mesh=mesh)
    faces, edges = list(mesh.faces), list(mesh.edges)
    transform = rotation_matrix(V(20, 0, 0), V(0, 0, 1), 180)
    expected = _geometry(mesh) + _geometry(SimpleNamespace(faces=[
        Face([transform.map(p) for p in f.vertices],
             [[transform.map(p) for p in h] for h in f.holes]) for f in faces]))
    tool = RotateTool()
    tool.start_point, tool._custom_axis, tool._copy = V(20, 0, 0), V(0, 0, 1), True
    tool._sel_faces, tool._sel_edges = faces, edges
    history = History(scene)
    history.execute(tool._make_builder()([180]))
    assert history.last_error is None
    assert len(mesh.faces) == 86 and _geometry(mesh) == expected
    assert all(f in mesh.faces for f in faces)
    history.undo()
    assert mesh.faces == faces and mesh.edges == edges


def test_a_copy_on_another_plane_keeps_both_faces():
    scene = Scene()
    source = _rectangle(scene)
    _rotate(scene, source, [90], V(1, 0, 0))
    assert source in scene.mesh.faces and len(scene.mesh.faces) == 2
    assert _area(scene) == pytest.approx(16)


def test_undo_redo_after_leaving_a_group_preserves_the_outer_selection():
    scene = Scene()
    group = Group(Mesh(), name="Edited")
    _rectangle(Scene(mesh=group.mesh))
    scene.groups.append(group)
    outer = scene.mesh
    scene.begin_group_edit(group)
    source = scene.mesh.faces[0]
    scene.selection = {source}
    history = _rotate(scene, source, [90])
    scene.end_group_edit()
    scene.selection = {group}
    assert history.undo()
    assert group.mesh.faces == [source]
    assert scene.mesh is outer and not outer.faces and scene.selection == {group}
    assert history.redo()
    assert sum(f.net_area() for f in group.mesh.faces) == pytest.approx(12)
    assert scene.mesh is outer and not outer.faces and scene.selection == {group}


def test_real_ctrl_copy_retyping_and_array_rebuild_the_overlap():
    scene = Scene()
    source = _rectangle(scene)
    scene.selection = {source}
    vp, tool = _Vp(scene), RotateTool()
    _rotate_copy(vp, tool, 90)
    assert _area(scene) == pytest.approx(12)
    assert tool.on_value(vp, 180)
    assert _area(scene) == pytest.approx(8)
    assert tool.on_array_value(vp, 3, "/")
    assert _covers(scene.mesh, V(0.2, 0.3, 0)) == 1
    assert vp.history.undo()
    assert scene.mesh.faces == [source]


def test_mixed_group_copy_survives_overlap_undo_redo():
    scene = Scene()
    source = _rectangle(scene)
    group = Group(Mesh(), name="Separate")
    _rectangle(Scene(mesh=group.mesh))
    scene.groups.append(group)
    tool = RotateTool()
    tool.start_point, tool._custom_axis, tool._copy = V(), V(0, 0, 1), True
    tool._sel_faces, tool._sel_edges, tool._groups = [source], list(scene.mesh.edges), [group]
    history = History(scene)
    history.execute(tool._make_builder()([90]))
    assert history.last_error is None
    assert _area(scene) == pytest.approx(12)
    assert len(scene.groups) == 2
    history.undo()
    assert scene.mesh.faces == [source] and scene.groups == [group]
    history.redo()
    assert _area(scene) == pytest.approx(12) and len(scene.groups) == 2
