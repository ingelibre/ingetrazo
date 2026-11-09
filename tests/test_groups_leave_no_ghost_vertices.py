# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Making a group or a component leaves no vertices behind, and deleting one
sweeps whatever the session was still carrying.

The report: draw a box, make a component of it, delete the component, keep
drawing — and the new geometry comes out cut in two, with seams running to
corners that are not there, and the cursor snapping to points nobody can see.

Reading the mesh after «make component» showed why: the eight corners of the
box were still in the loose mesh, unreferenced by any edge or face, and still
in the position registry. Nothing draws them and ``bounds()`` ignores them, so
the only thing that could notice was the next thing drawn there — which welds
to them and gets subdivided at a point the user never made.

``Mesh.purge_debris`` is the sweep; ``MakeGroupCommand`` and
``DeleteGroupCommand`` call it. Undo is unaffected: the group command keeps a
full mesh snapshot.
"""
from __future__ import annotations

import itertools

from PySide6.QtGui import QVector3D

from core.history import DeleteGroupCommand, History, MakeGroupCommand
from core.scene import Scene


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


_LOOPS = [
    [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)],
    [V(0, 0, 2), V(0, 2, 2), V(2, 2, 2), V(2, 0, 2)],
    [V(0, 0, 0), V(0, 0, 2), V(2, 0, 2), V(2, 0, 0)],
    [V(2, 0, 0), V(2, 0, 2), V(2, 2, 2), V(2, 2, 0)],
    [V(2, 2, 0), V(2, 2, 2), V(0, 2, 2), V(0, 2, 0)],
    [V(0, 2, 0), V(0, 2, 2), V(0, 0, 2), V(0, 0, 0)],
]


def _box(scene) -> None:
    for loop in _LOOPS:
        scene.mesh.add_face(loop)
    scene.version += 1


def _orphans(mesh) -> list:
    """Vertices no edge and no face holds: the ones that only snap."""
    held = set()
    for f in mesh.faces:
        for v in f.loop:
            held.add(id(v))
        for hole in f.hole_loops:
            for v in hole:
                held.add(id(v))
    return [v for v in mesh.vertices if not v.edges and id(v) not in held]


def _registry_ghosts(mesh) -> list:
    live = {id(v) for v in mesh.vertices}
    return [k for k, v in mesh._registry.items() if id(v) not in live]


def _snapshot(mesh) -> tuple:
    return (len(mesh.vertices), len(mesh.edges), len(mesh.faces),
            len(mesh._registry))


def test_a_box_made_a_component_leaves_nothing_in_the_loose_mesh():
    scene = Scene()
    _box(scene)
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces), [], component=True))
    mesh = scene.mesh
    assert (mesh.vertices, mesh.edges, mesh.faces) == ([], [], [])
    assert _orphans(mesh) == []
    assert _registry_ghosts(mesh) == []
    # The eight corners travelled into the component's own mesh.
    assert len(scene.groups[0].mesh.vertices) == 8


def test_a_box_made_a_group_leaves_nothing_in_the_loose_mesh():
    scene = Scene()
    _box(scene)
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces), []))
    assert _orphans(scene.mesh) == []
    assert _registry_ghosts(scene.mesh) == []
    assert len(scene.groups[0].mesh.vertices) == 8


def test_a_corner_triple_leaves_no_vertex_behind():
    """Grouping three faces that meet at a corner used to strand that corner:
    none of the loose edges touched it any more, and no face held it."""
    scene = Scene()
    _box(scene)
    hist = History(scene)
    faces = list(scene.mesh.faces)
    hist.execute(MakeGroupCommand([faces[0], faces[2], faces[5]], []))
    assert _orphans(scene.mesh) == []
    assert _registry_ghosts(scene.mesh) == []


def test_every_small_selection_comes_out_clean():
    for n in (1, 2, 3):
        for combo in itertools.combinations(range(6), n):
            scene = Scene()
            _box(scene)
            hist = History(scene)
            faces = list(scene.mesh.faces)
            hist.execute(MakeGroupCommand([faces[i] for i in combo], []))
            assert _orphans(scene.mesh) == [], combo
            assert _registry_ghosts(scene.mesh) == [], combo


def test_undo_brings_the_whole_loose_mesh_back():
    scene = Scene()
    _box(scene)
    hist = History(scene)
    before = _snapshot(scene.mesh)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces), [], component=True))
    hist.undo()
    assert _snapshot(scene.mesh) == before
    assert len(scene.mesh.faces) == 6
    assert _orphans(scene.mesh) == []


def test_deleting_a_group_sweeps_a_ghost_the_session_carried():
    """Anything that left a vertex with nothing on it (a grouping, an edit
    that removed geometry without sweeping) is gone by the time the delete
    is over: the loose mesh is the loose mesh again."""
    scene = Scene()
    _box(scene)
    hist = History(scene)
    hist.execute(MakeGroupCommand([list(scene.mesh.faces)[0]], []))
    ghost = scene.mesh.vertex(V(9, 9, 9))         # a corner nothing uses
    assert scene.mesh.vertex_at(V(9, 9, 9)) is ghost
    hist.execute(DeleteGroupCommand(scene.groups[0]))
    assert _orphans(scene.mesh) == []
    assert scene.mesh.vertex_at(V(9, 9, 9)) is None


def test_nothing_drawn_afterwards_welds_to_a_deleted_component():
    """The point of the sweep: the next face drawn there is a new face, not
    one subdivided through a corner the user cannot see."""
    scene = Scene()
    _box(scene)
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces), [], component=True))
    hist.execute(DeleteGroupCommand(scene.groups[0]))
    fresh = scene.mesh.add_face(
        [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    assert len(scene.mesh.faces) == 1
    assert [len(f.vertices) for f in scene.mesh.faces] == [4]
    assert len(fresh.vertices) == 4
    assert scene.mesh.vertex_at(V(0, 0, 0)).edges      # a real, used corner


def test_deleting_a_group_keeps_its_own_mesh_for_undo():
    scene = Scene()
    _box(scene)
    hist = History(scene)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces), []))
    group = scene.groups[0]
    kept = group.mesh
    hist.execute(DeleteGroupCommand(group))
    assert group.mesh is kept and len(kept.faces) == 6   # restored whole
    hist.undo()
    assert scene.groups == [group] and len(group.mesh.faces) == 6
