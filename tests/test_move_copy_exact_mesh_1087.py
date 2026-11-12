# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""#1087: copying supplied topology must not face its empty cycles again."""
from collections import Counter
from pathlib import Path
import random

import pytest
from PySide6.QtGui import QVector3D

from core.history import History
from core.mesh import _key
from core.scene import Scene
from tools.move import MoveTool


def V(x, y, z=0):
    return QVector3D(float(x), float(y), float(z))


def _loop(points, delta):
    """Ignore the starting vertex, but retain the face's winding."""
    keys = tuple(_key(p + delta) for p in points)
    return min(keys[i:] + keys[:i] for i in range(len(keys)))


def _faces(faces, delta=QVector3D()):
    return Counter((_loop(f.vertices, delta),
                    tuple(sorted(_loop(h, delta) for h in f.holes)))
                   for f in faces)


def _two_storeys(storeys=2):
    """Wall courses share rims without an internal floor at any of them."""
    scene = Scene()
    ring = [V(0, 0), V(4, 0), V(4, 3), V(0, 3)]
    scene.mesh.add_face(list(reversed(ring)))
    scene.mesh.add_face([p + V(0, 0, storeys) for p in ring])
    for z in range(storeys):
        for a, b in zip(ring, ring[1:] + ring[:1]):
            scene.mesh.add_face([a + V(0, 0, z), b + V(0, 0, z),
                                 b + V(0, 0, z + 1), a + V(0, 0, z + 1)])
    return scene


def _copy(scene, deltas, seed=0, *, faces=None, edges=None):
    tool = MoveTool()
    tool._sel_faces = list(scene.mesh.faces if faces is None else faces)
    tool._sel_edges = list(scene.mesh.edges if edges is None else edges)
    random.Random(seed).shuffle(tool._sel_faces)
    random.Random(seed + 100).shuffle(tool._sel_edges)
    history = History(scene)
    history.execute(tool._make_copy_builder(scene)(deltas))
    assert not history.last_error
    return history


def _assert_exact(scene, deltas, seed=0):
    original = list(scene.mesh.faces)
    original_edges = list(scene.mesh.edges)
    before = _faces(original)
    expected = before.copy()
    for delta in deltas:
        expected.update(_faces(original, delta))
    history = _copy(scene, deltas, seed)
    assert _faces(scene.mesh.faces) == expected
    assert set(original).issubset(scene.mesh.faces)
    assert _faces(original) == before
    assert len(scene.mesh.edges) == len(original_edges) * (len(deltas) + 1)
    history.undo()
    assert list(scene.mesh.faces) == original
    assert list(scene.mesh.edges) == original_edges
    history.redo()
    assert _faces(scene.mesh.faces) == expected


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_copy_does_not_invent_an_internal_floor(seed):
    _assert_exact(_two_storeys(), [V(10, 0)], seed)


def test_array_preserves_each_mesh_and_undo_redo():
    _assert_exact(_two_storeys(), [V(10, 0), V(20, 0), V(30, 0)])


def test_thousands_of_faces_do_not_gain_internal_floors():
    scene = _two_storeys(512)
    assert len(scene.mesh.faces) == 2050
    _assert_exact(scene, [V(10, 0)], seed=7)


def test_overlapping_boxes_without_contact_keep_source_topology():
    scene = _two_storeys()
    faces, edges = list(scene.mesh.faces), list(scene.mesh.edges)
    # The copy lies inside this ring's opening. Its box overlaps the ring's
    # box; neither its faces nor edges actually touch the ring.
    scene.mesh.add_face([V(8, -2), V(16, -2), V(16, 8), V(8, 8)],
                        [[V(9, -1), V(15, -1), V(15, 7), V(9, 7)]])
    expected = _faces(scene.mesh.faces) + _faces(faces, V(10, 0))
    _copy(scene, [V(10, 0)], faces=faces, edges=edges)
    assert _faces(scene.mesh.faces) == expected


def test_copy_inside_existing_face_still_subdivides_its_coverage():
    scene = Scene()
    scene.mesh.add_face([V(0, 0), V(10, 0), V(10, 10), V(0, 10)])
    source = scene.mesh.add_face([V(12, 2), V(14, 2), V(14, 4), V(12, 4)])
    edges = [e for e in scene.mesh.edges if source in e.faces]
    history = _copy(scene, [V(-10, 0)], faces=[source], edges=edges)
    assert sorted(round(f.net_area(), 5) for f in scene.mesh.faces) == [4, 4, 96]
    history.undo()
    assert sorted(round(f.net_area(), 5) for f in scene.mesh.faces) == [4, 100]
    history.redo()
    assert sorted(round(f.net_area(), 5) for f in scene.mesh.faces) == [4, 4, 96]


def test_array_members_split_each_other_even_far_from_the_original():
    scene = Scene()
    scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    history = _copy(scene, [V(10, 0), V(11, 0)])
    assert sorted(round(f.net_area(), 5) for f in scene.mesh.faces) == [2, 2, 2, 4]
    history.undo()
    assert len(scene.mesh.faces) == 1
    history.redo()
    assert sorted(round(f.net_area(), 5) for f in scene.mesh.faces) == [2, 2, 2, 4]


def test_face_attributes_and_curve_flags_survive_an_exact_copy():
    from core.mesh import Mesh
    scene = _two_storeys()
    source = scene.mesh.faces[0]
    source.attrs.update(color="#123456", ifc_class="IfcSlab", custom={"id": 42})
    source.interior = True
    ring = [V(0.5, 0.5), V(1.5, 0.5), V(1.5, 1.5), V(0.5, 1.5)]
    curve = Mesh.next_curve_id()
    for a, b in zip(ring, ring[1:] + ring[:1]):
        edge = scene.mesh.add_edge(a, b)
        edge.soft = True
        edge.curve = curve
    _assert_exact(scene, [V(10, 0)])
    duplicate = next(f for f in scene.mesh.faces
                     if _faces([f]) == _faces([source], V(10, 0)))
    assert duplicate.attrs == source.attrs
    assert duplicate.interior
    copied_edges = [e for e in scene.mesh.edges
                    if e.curve is not None and e.curve != curve]
    assert len(copied_edges) == 4 and all(e.soft for e in copied_edges)
    assert len({e.curve for e in copied_edges}) == 1


@pytest.mark.parametrize("curved", [False, True])
def test_copy_of_an_unfaced_wire_stays_unfaced(curved):
    from core.mesh import Mesh
    scene = Scene()
    loop = [V(0, 0), V(1, 0), V(1, 1), V(0, 1)]
    curve = Mesh.next_curve_id() if curved else None
    for a, b in zip(loop, loop[1:] + loop[:1]):
        scene.mesh.add_edge(a, b).curve = curve
    _copy(scene, [V(4, 0)])
    assert not scene.mesh.faces
    assert len(scene.mesh.edges) == 8


@pytest.mark.parametrize("seed", [0, 7])
def test_bundled_pergola_copies_exactly_in_any_selection_order(seed):
    from formats.igz import load_into
    document = Scene()
    load_into(document, Path(__file__).resolve().parents[1]
              / "examples" / "banca-pergola-yanque.igz")

    def walk(groups):
        for group in groups:
            yield group
            yield from walk(group.children or ())

    group = next(g for g in walk(document.groups) if g.name == "Group 7")
    assert len(group.mesh.faces) == 43
    _assert_exact(Scene(mesh=group.mesh), [V(10, 0)], seed)
