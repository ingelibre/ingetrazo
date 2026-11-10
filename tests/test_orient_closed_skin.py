# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A closed skin wound one way is oriented by asking a few of its faces.

Every edit re-decided every face of the solid it touched: two thousand
faces, each with its rays, three times per circle drawn and pushed — 0.5 s
of every operation on a slab with sixty cylinders. A skin whose every edge
is walked by two faces, once each way, has no partitions and cannot
disagree with itself: its faces all look out or all look in, and a
handful of them say which.

What is not such a skin (a partition, one face turned over) still goes
through the pass that asks every face, and gets the answer it always got.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core import orient
from core.history import History, translate_points
from core.mesh import Mesh
from core.orient import orient_outward, signed_volume
from core.scene import Scene
from core.topology import _key
from tests.test_pushpull_large_solid_cost import (_circle,
                                                  _slab_with_cylinders)
from tests.test_pushpull_ux import _cube, _push


def V(x, y, z):
    return QVector3D(x, y, z)


def _box_loops(x0, y0, z0, x1, y1, z1):
    """The six faces of a box, each wound to look out."""
    return [
        [V(x0, y0, z0), V(x0, y1, z0), V(x1, y1, z0), V(x1, y0, z0)],  # down
        [V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)],  # up
        [V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)],  # front
        [V(x0, y1, z0), V(x0, y1, z1), V(x1, y1, z1), V(x1, y1, z0)],  # back
        [V(x0, y0, z0), V(x0, y0, z1), V(x0, y1, z1), V(x0, y1, z0)],  # left
        [V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)],  # right
    ]


def _box(mesh, *corners, turned=()):
    faces = []
    for i, loop in enumerate(_box_loops(*corners)):
        faces.append(mesh.add_face(loop[::-1] if i in turned else loop))
    return faces


def _every_face(monkeypatch):
    """The pass as it was: no skin is taken at the word of a few faces."""
    monkeypatch.setattr(orient, "_coherent_shells", lambda faces, comp: set())


def _count_questions(monkeypatch) -> list:
    asked = []
    real = orient._face_side_state
    monkeypatch.setattr(
        orient, "_face_side_state",
        lambda face, *a, **k: asked.append(face) or real(face, *a, **k))
    return asked


def test_a_solid_with_many_features_is_asked_a_handful_of_faces(monkeypatch):
    scene, _hist = _slab_with_cylinders(4)
    assert len(scene.mesh.faces) > 100
    asked = _count_questions(monkeypatch)
    assert orient_outward(scene.mesh) == []
    assert 0 < len(asked) <= orient._SHELL_SAMPLES


def test_a_push_on_that_solid_asks_a_handful_too(monkeypatch):
    scene, hist = _slab_with_cylinders(4)
    face = _circle(scene, hist, 4)
    asked = _count_questions(monkeypatch)
    _push(scene, face, 0.5)
    # Two passes per push (before and after), a sample each.
    assert 0 < len(asked) <= 2 * orient._SHELL_SAMPLES
    assert all(not f.interior for f in scene.mesh.faces)
    assert signed_volume(scene.mesh) > 0


def test_the_holed_cap_does_not_hide_the_skin():
    """A hole is walked the way its face's loop is, so the wall standing on
    it walks the same segment the same way round: read as written, every
    opening looked like a disagreement and no holed solid was ever a skin."""
    scene, _hist = _slab_with_cylinders(3)
    assert any(f.hole_loops for f in scene.mesh.faces)
    comp = orient._face_components(scene.mesh)
    assert orient._coherent_shells(scene.mesh.faces, comp) == set(
        comp.values())


def test_a_skin_wound_inwards_is_turned_whole(monkeypatch):
    mesh = Mesh()
    faces = _box(mesh, 0, 0, 0, 2, 3, 4, turned=range(6))
    assert signed_volume(mesh) < 0
    asked = _count_questions(monkeypatch)
    flipped = orient_outward(mesh)
    assert set(flipped) == set(faces)
    assert len(asked) <= orient._SHELL_SAMPLES
    assert signed_volume(mesh) > 0
    assert orient_outward(mesh) == []


def test_one_face_turned_over_is_not_a_skin_and_is_found(monkeypatch):
    mesh = Mesh()
    faces = _box(mesh, 0, 0, 0, 2, 3, 4, turned=(3,))
    comp = orient._face_components(mesh)
    assert orient._coherent_shells(mesh.faces, comp) == set()
    assert orient_outward(mesh) == [faces[3]]
    assert signed_volume(mesh) > 0


def test_a_partition_is_not_a_skin_and_keeps_its_mark():
    """Two rooms sharing a wall: its edges carry three faces."""
    mesh = Mesh()
    _box(mesh, 0, 0, 0, 2, 2, 2)
    for i, loop in enumerate(_box_loops(2, 0, 0, 4, 2, 2)):
        if i != 4:                      # its left wall is the first's right
            mesh.add_face(loop)
    comp = orient._face_components(mesh)
    assert orient._coherent_shells(mesh.faces, comp) == set()
    orient_outward(mesh)
    walls = [f for f in mesh.faces if f.interior]
    assert len(walls) == 1
    assert all(abs(v.x() - 2.0) < 1e-6 for v in walls[0].vertices)


def test_a_skin_closed_only_on_paper_is_asked_face_by_face(monkeypatch):
    """A box standing on a cube and reaching past its side, through an
    opening that reaches past the cube's top too (an edit caught mid-way,
    found by the fuzzer): every edge has its two faces, walked both ways,
    and yet the overhang has no floor. The few faces asked would all say
    "outward"; asked one by one, the top says otherwise."""
    mesh = Mesh()
    for i, loop in enumerate(_box_loops(0, 0, 0, 4, 4, 4)):
        if i == 1:
            mesh.add_face(loop, [[V(0.5, 1, 4), V(5, 1, 4), V(5, 3, 4),
                                  V(0.5, 3, 4)]])
        else:
            mesh.add_face(loop)
    for i, loop in enumerate(_box_loops(0.5, 1, 4, 5, 3, 5)):
        if i != 0:
            mesh.add_face(loop)
    comp = orient._face_components(mesh)
    assert orient._coherent_shells(mesh.faces, comp) == set(comp.values())
    asked = _count_questions(monkeypatch)
    orient_outward(mesh)
    assert len(set(asked)) == len(mesh.faces)
    quick = [f.interior for f in mesh.faces]
    with monkeypatch.context() as m:
        _every_face(m)
        orient_outward(mesh)
    assert [f.interior for f in mesh.faces] == quick


def test_a_few_faces_say_what_every_face_says(monkeypatch):
    """The same solids through both passes: same faces turned, same marks."""
    def build(turned):
        scene = Scene()
        hist = History(scene)
        _cube(scene, hist, size=10.0, height=3.0)
        for i in range(3):
            _push(scene, _circle(scene, hist, i), 0.5)
        if turned:
            for f in scene.mesh.faces:
                orient.turn_face_over(f)
        return scene.mesh

    for turned in (False, True):
        quick = build(turned)
        slow = build(turned)
        got = orient_outward(quick)
        with monkeypatch.context() as m:
            _every_face(m)
            want = orient_outward(slow)
        index = {f: i for i, f in enumerate(quick.faces)}
        index_slow = {f: i for i, f in enumerate(slow.faces)}
        assert sorted(index[f] for f in got) == sorted(
            index_slow[f] for f in want)
        assert [f.interior for f in quick.faces] == [
            f.interior for f in slow.faces]
        assert len(got) == (len(quick.faces) if turned else 0)


def test_an_open_mesh_is_marked_but_never_turned():
    """As before: without a closed mesh, a pass over everything turns
    nothing — a closed box wound inwards beside a loose face included."""
    mesh = Mesh()
    _box(mesh, 0, 0, 0, 1, 1, 1, turned=range(6))
    mesh.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0.5)])
    assert orient_outward(mesh) == []
    assert signed_volume(mesh) < 0


def test_a_moved_corner_is_triangulated_again():
    """The pass keeps each face's triangles while its corners stay put, and
    only then."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=4.0, height=3.0)
    mesh = scene.mesh
    before = orient._face_triangles(mesh)
    again = orient._face_triangles(mesh)
    assert all(again[f] is before[f] for f in mesh.faces)
    top = {_key(v.position) for v in mesh.vertices
           if abs(v.position.z() - 3.0) < 1e-6}
    translate_points(scene, top, V(0, 0, 1.0))
    after = orient._face_triangles(mesh)
    moved = [f for f in mesh.faces if after[f] is not before[f]]
    assert len(moved) == 5              # all but the floor
    assert max(p.z() for f in moved for t in after[f] for p in t) == 4.0
    assert orient_outward(mesh) == []
    assert abs(signed_volume(mesh) - 4 * 4 * 4) < 1e-3
