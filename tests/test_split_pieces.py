# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Split into Pieces: a group regrouped by the solids that do not touch.

A model file's own parts are often surface fragments cut by material (a Sweet
Home 3D bar stool: 43 groups, five real pieces); connectivity is what finds
the pieces a person would pick up."""
from __future__ import annotations

import pytest

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, world_mesh
from core.history import SplitIntoPiecesCommand
from core.mesh import Mesh
from core.pieces import connected_parts, solid_parts, split_into_pieces
from core.scene import Scene

_QUADS = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
          (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))


def _corners(x0: float, z0: float = 0.0) -> list:
    return [QVector3D(x0 + dx, dy, z0 + dz) for dz in (0, 1) for dy in (0, 1)
            for dx in (0, 1)]


def _cube(mesh: Mesh, x0: float, z0: float = 0.0, quads=_QUADS) -> None:
    c = _corners(x0, z0)
    for q in quads:
        mesh.add_face([c[k] for k in q])


def _points(group) -> set:
    return {(round(v.position.x(), 5), round(v.position.y(), 5),
             round(v.position.z(), 5)) for v in world_mesh(group).vertices}


def test_two_separate_solids_become_two_pieces():
    mesh = Mesh()
    _cube(mesh, 0)
    _cube(mesh, 5)
    parts = connected_parts(mesh)
    assert [len(f) for f, _e in parts] == [6, 6]
    pieces = split_into_pieces(Group(mesh))
    assert [p.name for p in pieces] == ["Piece 1", "Piece 2"]
    assert not any(p.is_component() for p in pieces)   # groups (#90)
    assert all(len(p.mesh.faces) == 6 for p in pieces)


def test_fragments_across_children_join_into_the_piece_they_are():
    """Half a cube in one child, the other half in another — the way a file
    splits a part by material. Together they are one piece."""
    a, b = Mesh(), Mesh()
    _cube(a, 0, quads=_QUADS[:3])
    _cube(b, 0, quads=_QUADS[3:])
    halves = []
    for m in (a, b):
        g = Group(m)
        g.xform = QMatrix4x4()
        halves.append(g)
    stool = Group()
    stool.adopt(halves)
    assert len(world_mesh(stool).vertices) == 16
    pieces = split_into_pieces(stool)
    assert len(pieces) == 1
    assert len(pieces[0].mesh.faces) == 6
    assert len(pieces[0].mesh.vertices) == 8
    assert len(pieces[0].mesh.edges) == 12
    # Joining is specific to split analysis, not placement materialization;
    # the source fragments and their vertex identities remain independent.
    assert [len(m.vertices) for m in (a, b)] == [8, 8]
    assert len(world_mesh(stool).vertices) == 16


def test_a_piece_keeps_the_name_of_the_file_part_it_came_from():
    """A named file part split in two keeps its name on both halves; a part
    the importer only numbered does not pass its number on."""
    named = []
    for name, starts in (("Carcass", (0, 10)), ("Worktop", (3,)),
                         ("Part 7", (6,))):
        m = Mesh()
        for x0 in starts:
            _cube(m, x0)
        g = Group(m, name=name)
        g.xform = QMatrix4x4()
        named.append(g)
    unit = Group()
    unit.adopt(named)
    pieces = split_into_pieces(unit)
    assert sorted(p.name for p in pieces) == [
        "Carcass", "Carcass 2", "Piece 4", "Worktop"]


def test_a_single_piece_has_nothing_to_split():
    mesh = Mesh()
    _cube(mesh, 0)
    assert split_into_pieces(Group(mesh)) == []


def test_splitting_twice_changes_nothing():
    mesh = Mesh()
    _cube(mesh, 0)
    _cube(mesh, 5)
    group = Group(mesh)
    scene = Scene()
    scene.groups.append(group)
    SplitIntoPiecesCommand(group, split_into_pieces(group)).do(scene)
    assert split_into_pieces(group) == []


def test_touching_boards_are_separate_pieces():
    """A cabinet's carcase: closed boards welded where they meet. Plain
    connectivity reads them as one; the solids pass keeps them apart."""
    mesh = Mesh()
    _cube(mesh, 0)
    _cube(mesh, 0, z0=1)                   # stacked, sharing four corners
    _cube(mesh, 1)                         # beside, sharing an edge
    assert len(connected_parts(mesh)) == 1
    assert [len(f) for f, _e in solid_parts(mesh)] == [6, 6, 6]


def test_a_piece_does_not_take_its_neighbours_edges():
    """Welded boards share corners; a piece copied with every edge that
    touches one of its corners measured as far as the neighbour's far end
    (a 1.5 cm side board read as 85 x 60 x 55)."""
    from core.parts import part_points, part_size
    mesh = Mesh()
    _cube(mesh, 0)
    _cube(mesh, 0, z0=1)
    pieces = split_into_pieces(Group(mesh))
    assert [len(p.mesh.edges) for p in pieces] == [12, 12]
    for p in pieces:
        assert part_size(part_points(p)) == pytest.approx((1.0, 1.0, 1.0))


def test_fragments_join_the_solid_they_lie_on():
    """A file cut by material: a closed box plus an open patch lying on it
    (a double-sided decal, a strip) is one piece."""
    mesh = Mesh()
    _cube(mesh, 0)
    a, b = QVector3D(0.2, 0, 0.2), QVector3D(0.8, 0, 0.2)
    c, d = QVector3D(0.8, 0, 0.8), QVector3D(0.2, 0, 0.8)
    loose = Mesh()
    loose.add_face([a, b, c, d])            # a floating sheet: no shared corner
    for f in loose.faces:
        mesh.add_face(f.vertices)
    corner = [QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)]
    mesh.add_face(corner)                    # a patch on the cube's corners
    sizes = sorted(len(f) for f, _e in solid_parts(mesh))
    assert sizes == [1, 7]                   # sheet alone; patch with its box


def test_a_zero_thickness_double_sided_sheet_is_not_a_solid():
    mesh = Mesh()
    pts = [QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0),
           QVector3D(0, 1, 0)]
    mesh.add_face(pts)
    mesh.add_face(list(reversed(pts)))
    from core.pieces import _is_solid
    assert not _is_solid(list(mesh.faces))


def test_the_split_keeps_the_geometry_where_it_was_and_undoes():
    mesh = Mesh()
    _cube(mesh, 0)
    _cube(mesh, 5)
    mesh.faces[0].attrs["color"] = [0.8, 0.1, 0.1]
    group = Group(mesh, name="stool")
    place = QMatrix4x4()
    place.translate(QVector3D(3, 4, 0))
    place.rotate(30, 0, 0, 1)
    group.xform = place                    # a placed component
    scene = Scene()
    scene.groups.append(group)
    before = _points(group)

    cmd = SplitIntoPiecesCommand(group, split_into_pieces(group))
    cmd.do(scene)
    assert scene.groups == [group] and group.name == "stool"
    assert group.xform == place            # still placed where it was
    assert not group.mesh.faces and len(group.children) == 2
    assert _points(group) == before
    painted = [f for k in group.children for f in k.mesh.faces
               if f.attrs.get("color")]
    assert len(painted) == 1               # the paint travelled

    cmd.undo(scene)
    assert group.mesh is mesh and not group.children
    assert group.xform == place


def test_edge_flags_travel_with_the_piece():
    mesh = Mesh()
    _cube(mesh, 0)
    _cube(mesh, 5)
    for e in mesh.edges[:2]:
        e.hidden = True
        e.soft = True
    pieces = split_into_pieces(Group(mesh))
    assert sum(e.hidden for p in pieces for e in p.mesh.edges) == 2
    assert sum(e.soft for p in pieces for e in p.mesh.edges) == 2
