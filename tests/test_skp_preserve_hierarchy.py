# SPDX-License-Identifier: GPL-3.0-or-later
"""Small and single-use SketchUp children remain independently editable."""
from types import SimpleNamespace as NS

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QVector3D as V

from core.group import Group, placement_points
from core.history import DeleteGroupCommand, History, MoveGroupCommand, SnapshotImport
from core.scene import Scene
from formats import igz, skp, skp_openskp
from tools.select import SelectTool
from views.viewport import Viewport


def definition(did, name, points=(), rings=()):
    node = NS(id=did, name=name, instances=[], faces={}, edges={},
              vertices={i: NS(x=p[0], y=p[1], z=p[2]) for i, p in enumerate(points)})
    edges = {}
    for fi, ring in enumerate(rings):
        loop = []
        for i, vi in enumerate(ring):
            vj = ring[(i + 1) % len(ring)]
            key = tuple(sorted((vi, vj)))
            if key not in edges:
                ei = len(edges)
                edges[key] = ei
                node.edges[ei] = NS(v1_id=vi, v2_id=vj)
            loop.append((edges[key], 1))
        node.faces[fi] = NS(loops=[loop], material_id=None, normal=(0, 0, 1))
    return node


def instance(did, x=0, **kwargs):
    return NS(ref_idx=did, matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1, x, 0, 0, 1], **kwargs)


def fixture(copies=1):
    column = definition(23, 'Column',
                        [(0, 0, 0), (8, 0, 0), (8, 8, 0), (0, 8, 0),
                         (0, 0, 120), (8, 0, 120), (8, 8, 120), (0, 8, 120)],
                        [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                         (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
    house = definition(10, 'House')
    house.instances = [instance(23, x=100 * i, name=f'Column {i}') for i in range(copies)]
    root = definition(0, 'ROOT_MODEL')
    root.instances = [instance(10), instance(10, x=1000)]
    model = NS(root=root, definitions={10: house, 23: column}, version='{20.0.0}')
    return model, house, column


def imported(model):
    scene = Scene()
    history = History(scene)
    payload = skp_openskp._adapt(model, 'House')
    history.execute(SnapshotImport(lambda s: skp.apply_payload(s, payload)))
    assert history.last_error is None
    return scene, history


@pytest.mark.parametrize('copies', [1, 2, 36])
def test_six_face_children_survive_below_instancing_thresholds(copies):
    model, _, _ = fixture(copies)
    scene, _ = imported(model)
    first, second = scene.groups
    assert not first.mesh.faces
    assert len(first.children) == copies
    assert all(isinstance(c, Group) and len(c.mesh.faces) == 6 for c in first.children)
    assert [c.name for c in first.children] == [f'Column {i}' for i in range(copies)]
    assert first.children[0].mesh is second.children[0].mesh
    assert first.children[0].xform is not second.children[0].xform
    children = tuple(first.children)
    scene.begin_group_edit(first)
    assert tuple(first.children) == children and not scene.mesh.faces


def test_entering_a_parent_picks_and_double_clicks_a_child_as_an_object():
    model, _, _ = fixture()
    scene, _ = imported(model)
    vp = Viewport()
    vp.scene = scene
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *args: None
    house = scene.groups[0]
    child, = house.children
    vp.begin_group_edit(house)
    points = placement_points(child)
    centre = (points.min(axis=0) + points.max(axis=0)) / 2
    vp.camera.target = V(*centre)
    vp.camera.distance = 6
    vp.camera.yaw, vp.camera.pitch = 0, 0
    pixel = vp._world_to_pixel(V(*centre))
    tool = SelectTool()
    assert tool._pick(vp, *pixel) is child
    tool.on_double_click(NS(viewport=vp, screen=QPointF(*pixel)))
    assert scene.edit_group is child and len(scene._edit_stack) == 2
    assert len(scene.mesh.faces) == 6


def test_nested_move_delete_and_undo_keep_other_placements():
    model, _, _ = fixture()
    scene, history = imported(model)
    house, other = scene.groups
    child, = house.children
    sibling, = other.children
    scene.begin_group_edit(house)
    old, other_old = child.xform, sibling.xform
    history.execute(MoveGroupCommand(child, V(1, 2, 3)))
    assert child.xform != old and sibling.xform == other_old
    history.undo()
    assert child.xform == old
    history.execute(DeleteGroupCommand(child))
    assert not house.children and other.children == [sibling]
    history.undo()
    assert house.children == [child]


def test_hidden_tagged_child_and_line_only_and_empty_groups_survive():
    model, house, _ = fixture()
    house.instances[0].hidden = True
    house.instances[0].layer = 'Structure'
    wire = definition(31, 'Wire', [(0, 0, 0), (20, 0, 0)])
    wire.edges[1] = NS(v1_id=0, v2_id=1, curve_id=123)
    empty = definition(32, 'Empty')
    model.definitions.update({31: wire, 32: empty})
    house.instances += [instance(31), instance(32)]
    scene, _ = imported(model)
    child, line, blank = scene.groups[0].children
    assert child.hidden and child.layer == 'Structure'
    assert len(line.mesh.edges) == 1 and line.mesh.edges[0].curve == 123
    assert line.mesh.next_curve_id() > 123
    assert blank.name == 'Empty' and not blank.mesh.edges and not blank.mesh.faces


def test_native_round_trip_keeps_hierarchy_and_geometry_sharing(tmp_path):
    scene, _ = imported(fixture(2)[0])
    path = tmp_path / 'nested.igz'
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    first, second = loaded.groups
    assert len(first.children) == 2 and len(first.children[0].mesh.faces) == 6
    assert first.children[0].mesh is second.children[0].mesh


def test_unplaced_library_definition_is_not_imported():
    model, _, _ = fixture()
    model.definitions[99] = definition(99, 'Unused library object')
    scene, _ = imported(model)
    assert len(scene.groups) == 2
    assert all(c.name != 'Unused library object' for g in scene.groups for c in g.children)


@pytest.mark.parametrize('cyclic', [False, True])
def test_invalid_references_fail_before_scene_mutation(cyclic):
    model, house, _ = fixture()
    house.instances = [instance(10 if cyclic else 9999)]
    with pytest.raises(ValueError, match='Cyclic|missing'):
        skp_openskp._adapt(model, 'Invalid')
