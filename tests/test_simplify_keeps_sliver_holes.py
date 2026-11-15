# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A plaza exported to STL and imported with «merge coplanar triangles on
the XY, XZ and YZ planes» (the default) could not be saved: «list index out
of range» (Windows round 0.6.2, already so in 0.6.1). The merge leaves a
thin triangular hole whose third corner is almost on the line of the other
two; the clean-up of collinear vertices took that corner away, and a hole
of two vertices broke _maximal_holes on save. A loop of three keeps its
corners."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V


def _plate_with_sliver_hole():
    from core.mesh import Mesh
    m = Mesh()
    outer = [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)]
    # Under a degree off the line: collinear for collapsible_vertex.
    sliver = [V(2, 2, 0), V(5, 2.02, 0), V(8, 2, 0)]
    other = [V(2, 6, 0), V(4, 6, 0), V(4, 8, 0), V(2, 8, 0)]
    m.add_face(outer, [sliver, other])
    return m


def test_a_three_corner_hole_keeps_its_corners():
    m = _plate_with_sliver_hole()
    corner = m.vertex_at(V(5, 2.02, 0))
    assert not m.collapsible_vertex(corner)


def test_simplify_leaves_no_hole_of_two_and_the_plate_saves(tmp_path):
    from core.scene import Scene
    from formats.fuse import simplify_mesh
    from formats.igz import load_into, save_scene
    sc = Scene()
    plate = _plate_with_sliver_hole()
    simplify_mesh(plate, principal_planes=True)
    assert all(len(h) >= 3 for f in plate.faces for h in f.hole_loops)
    sc.mesh.restore_state(plate.capture_state())
    save_scene(sc, tmp_path / "plate.igz")              # IndexError before
    back = Scene()
    load_into(back, tmp_path / "plate.igz")
    assert len(back.mesh.faces) == len(sc.mesh.faces) == 1


def test_a_longer_loop_still_loses_its_collinear_vertex():
    """The clean-up stays: a spare vertex on a straight side of a square
    goes, as before."""
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(5, 0, 0), V(10, 0, 0), V(10, 10, 0),
                V(0, 10, 0)])
    assert m.collapsible_vertex(m.vertex_at(V(5, 0, 0)))
