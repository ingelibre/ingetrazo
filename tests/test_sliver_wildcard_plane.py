# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A near-degenerate face must not act as a wildcard plane.

Plaza Yanque, 2026-09-10: inside a group, Marco drew one line at a corner
and all 447 faces of that group vanished — edges left, no error logged, the
command "succeeded". The mesh really had lost them.

The culprit was a 3 mm² sliver imported from SketchUp whose Newell normal
measured 5.9e-6. Face.normal() guarded degeneracy at 1e-9 and then handed
the vector to QVector3D.normalized(), which returns a NULL vector for
anything shorter than 1e-5 — four orders of magnitude above the guard. A
zero normal passes every plane test (``dot(anything, zero) == 0``), so that
sliver claimed the drawn line, and RebuildPlaneFacesCommand rebuilt "its"
plane: with a null normal every edge in the mesh is on it.

His document carried 304 such faces.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge
from core.group import Group
from core.history import History, RebuildPlaneFacesCommand
from core.mesh import Mesh
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def test_qt_nulls_short_vectors_which_is_why_we_divide_by_hand():
    """The trap itself, pinned: if Qt ever changes, this says so."""
    assert QVector3D(0.0, 0.0, 1e-4).normalized().length() == 1.0
    assert QVector3D(0.0, 0.0, 1e-5).normalized().length() == 0.0


def test_a_sliver_face_still_reports_a_unit_normal():
    mesh = Mesh()
    # Marco's measured 2.943e-6 of area, i.e. a Newell normal of 5.9e-6 —
    # under Qt's 1e-5 null threshold and over our 1e-9 degeneracy guard.
    # 3 mm x 1 mm lands in the same band; 3 mm x 2 mm does NOT (1.2e-5).
    f = mesh.add_face([V(0, 0), V(0.003, 0), V(0.003, 0.001), V(0, 0.001)])
    assert 0.0 < f.area() < 5e-6
    assert f._newell().length() < 1e-5, "not in Qt's null band"
    n = f.normal()
    assert abs(n.length() - 1.0) < 1e-6, "a zero normal is a wildcard plane"
    assert abs(abs(n.z()) - 1.0) < 1e-6, "and it points the right way"


def test_a_truly_degenerate_face_still_gets_the_documented_fallback():
    mesh = Mesh()
    f = mesh.add_face([V(0, 0), V(1, 0), V(2, 0)])      # collinear
    assert f.normal() == V(0, 0, 1)


def _group_with_a_sliver(scene):
    """A floor, and an upper slab that carries one sliver — two DIFFERENT
    planes, which is the whole point: a line drawn on the floor has no
    business touching the slab above."""
    mesh = Mesh()
    mesh.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 8, 0), V(0, 8, 0)])
    mesh.add_face([V(0, 0, 0.5), V(4, 0, 0.5), V(4, 4, 0.5), V(0, 4, 0.5)])
    mesh.add_face([V(6, 0, 0.5), V(10, 0, 0.5),
                   V(10, 4, 0.5), V(6, 4, 0.5)])
    sliver = mesh.add_face([V(4.0, 0.0, 0.5), V(4.003, 0.0, 0.5),
                            V(4.003, 0.001, 0.5), V(4.0, 0.001, 0.5)])
    g = Group(mesh, name="Losa")
    scene.groups.append(g)
    return g, sliver


def _upper(scene):
    return [f for f in scene.mesh.faces
            if all(abs(v.z() - 0.5) < 1e-6 for v in f.vertices)]


def test_a_line_on_the_floor_leaves_the_slab_above_alone():
    scene = Scene()
    g, sliver = _group_with_a_sliver(scene)
    assert sliver.normal().length() > 0.5
    history = History(scene)
    scene.begin_group_edit(g)
    upper_before = len(_upper(scene))
    assert upper_before == 3
    history.execute(
        build_add_edge(scene, V(1, 1, 0), V(9, 1, 0), detect_faces=True))
    assert history.last_error is None
    assert len(_upper(scene)) == upper_before, \
        "the sliver claimed a line on another plane and the rebuild wiped it"
    assert scene.mesh.faces, "the group lost every face"


def test_a_rebuild_with_no_plane_is_a_no_op_not_a_wipe():
    """Belt and braces: even handed a null normal, it must not empty the
    mesh — _on_plane would otherwise say yes to every point."""
    scene = Scene()
    scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    scene.mesh.add_face([V(6, 0), V(10, 0), V(10, 4), V(6, 4)])
    before = len(scene.mesh.faces)
    History(scene).execute(
        RebuildPlaneFacesCommand(V(1, 1, 0), QVector3D(0.0, 0.0, 0.0)))
    assert len(scene.mesh.faces) == before
