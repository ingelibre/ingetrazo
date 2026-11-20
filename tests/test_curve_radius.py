# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Changing a circle or arc's radius — Entity Info's Radius field."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D

from core.curve_segments import RescaleCurveRadiusCommand, read_curve
from core.history import History
from core.scene import Scene


def _circle(scene, r=2.0, n=24):
    pts = [QVector3D(r * math.cos(2 * math.pi * k / n),
                     r * math.sin(2 * math.pi * k / n), 0.0)
           for k in range(n)]
    scene.mesh.add_face(pts)
    scene.mesh.tag_curve(pts, closed=True)
    return next(e for e in scene.mesh.edges if e.curve is not None)


def _arc(scene, r=2.0, n=4):
    """A quarter arc (sweep = 90°), 0 → π/2."""
    pts = [QVector3D(r * math.cos(math.pi * k / (2 * n)),
                     r * math.sin(math.pi * k / (2 * n)), 0.0)
           for k in range(n + 1)]
    for a, b in zip(pts, pts[1:]):
        scene.mesh.add_edge(a, b)
    scene.mesh.tag_curve(pts, closed=False)
    return next(e for e in scene.mesh.edges if e.curve is not None)


def _edge(scene):
    return next(e for e in scene.mesh.edges if e.curve is not None)


def test_rescaling_a_circle_keeps_its_centre():
    scene = Scene()
    history = History(scene)
    edge = _circle(scene)
    shape = read_curve(scene.mesh, edge)
    center = shape.center
    assert abs(shape.radius - 2.0) < 1e-6

    history.execute(RescaleCurveRadiusCommand(edge, 3.0))
    shape = read_curve(scene.mesh, _edge(scene))
    assert abs(shape.radius - 3.0) < 1e-6
    assert (shape.center - center).length() < 1e-4

    history.undo()
    shape = read_curve(scene.mesh, _edge(scene))
    assert abs(shape.radius - 2.0) < 1e-6
    assert (shape.center - center).length() < 1e-4


def test_rescaling_an_arc_keeps_its_ends():
    scene = Scene()
    history = History(scene)
    edge = _arc(scene)
    shape = read_curve(scene.mesh, edge)
    p0 = QVector3D(shape.verts[0].position)
    p1 = QVector3D(shape.verts[-1].position)
    assert abs(shape.radius - 2.0) < 1e-6

    history.execute(RescaleCurveRadiusCommand(edge, 3.0))        # shallower
    shape = read_curve(scene.mesh, _edge(scene))
    assert abs(shape.radius - 3.0) < 1e-6
    assert (QVector3D(shape.verts[0].position) - p0).length() < 1e-4
    assert (QVector3D(shape.verts[-1].position) - p1).length() < 1e-4

    history.execute(RescaleCurveRadiusCommand(_edge(scene), 1.6))  # deeper
    shape = read_curve(scene.mesh, _edge(scene))
    assert abs(shape.radius - 1.6) < 1e-6
    assert (QVector3D(shape.verts[0].position) - p0).length() < 1e-4
    assert (QVector3D(shape.verts[-1].position) - p1).length() < 1e-4

    history.undo()
    shape = read_curve(scene.mesh, _edge(scene))
    assert abs(shape.radius - 3.0) < 1e-6


def test_a_radius_too_small_for_the_arcs_chord_is_rejected():
    scene = Scene()
    history = History(scene)
    edge = _arc(scene)
    # half-chord of a quarter arc of radius 2 is √2 ≈ 1.414; 1.0 cannot hold it.
    steps = len(history.undo_stack)
    history.execute(RescaleCurveRadiusCommand(edge, 1.0))
    assert len(history.undo_stack) == steps
    shape = read_curve(scene.mesh, _edge(scene))
    assert abs(shape.radius - 2.0) < 1e-6


@pytest.mark.parametrize("hole", [False, True])
def test_nonflat_circle_resizes_only_selected_rim_and_keeps_topology(hole):
    scene = Scene()
    mesh = scene.mesh
    n = 12
    top = [QVector3D(2 * math.cos(2 * math.pi * k / n),
                     2 * math.sin(2 * math.pi * k / n), 0)
           for k in range(n)]
    bottom = [p + QVector3D(0, 0, -3) for p in top]
    if hole:
        outer = [QVector3D(-5, -5, 0), QVector3D(5, -5, 0),
                 QVector3D(5, 5, 0), QVector3D(-5, 5, 0)]
        cap = mesh.add_face(outer, [top])
    else:
        cap = mesh.add_face(top)
    cap.attrs["color"] = (0.2, 0.3, 0.4)
    for i in range(n):
        j = (i + 1) % n
        wall = mesh.add_face([top[i], bottom[i], bottom[j], top[j]])
        wall.attrs["layer"] = "Walls"
    mesh.tag_curve(top, closed=True)
    edge = _edge(scene)
    cid = edge.curve
    original = mesh.capture_state()
    shape = read_curve(mesh, edge)
    assert not shape.flat and shape.segments == n

    history = History(scene)
    history.execute(RescaleCurveRadiusCommand(edge, 3.0))
    assert history.last_rejected is None
    assert history.last_error is None
    shape = read_curve(mesh, _edge(scene))
    assert shape is not None and shape.segments == n
    assert shape.radius == pytest.approx(3.0)
    assert all(mesh.vertex_at(p) is not None for p in bottom)
    assert len(mesh.faces) == n + 1
    assert cap.attrs["color"] == (0.2, 0.3, 0.4)
    assert all(f.attrs.get("layer") == "Walls"
               for f in mesh.faces if f is not cap)
    assert all(len(e.faces) == 2 for e in mesh.edges if e.curve == cid)
    assert len(scene.selection) == n

    history.undo()
    assert mesh.capture_state()["vpos"] == original["vpos"]
    assert read_curve(mesh, _edge(scene)).radius == pytest.approx(2.0)
    history.redo()
    assert read_curve(mesh, _edge(scene)).radius == pytest.approx(3.0)


def test_nonflat_hole_cannot_grow_past_its_face():
    scene = Scene()
    mesh = scene.mesh
    n = 12
    rim = [QVector3D(2 * math.cos(2 * math.pi * k / n),
                     2 * math.sin(2 * math.pi * k / n), 0)
           for k in range(n)]
    outer = [QVector3D(-4, -4, 0), QVector3D(4, -4, 0),
             QVector3D(4, 4, 0), QVector3D(-4, 4, 0)]
    cap = mesh.add_face(outer, [rim])
    for i in range(n):
        j = (i + 1) % n
        mesh.add_face([rim[i], rim[j], rim[j] + QVector3D(0, 0, -2),
                       rim[i] + QVector3D(0, 0, -2)])
    mesh.tag_curve(rim, closed=True)
    edge = _edge(scene)
    before = mesh.capture_state()
    history = History(scene)
    history.execute(RescaleCurveRadiusCommand(edge, 5.0))
    assert history.last_rejected is not None
    assert len(history.undo_stack) == 0
    assert mesh.capture_state()["vpos"] == before["vpos"]
    assert cap in mesh.faces
    assert read_curve(mesh, edge).radius == pytest.approx(2.0)


def test_nonflat_circle_rejects_landing_on_an_existing_vertex():
    scene = Scene()
    edge = _circle(scene)
    shape = read_curve(scene.mesh, edge)
    a, b = shape.verts[0].position, shape.verts[1].position
    scene.mesh.add_face([a, b, b + QVector3D(0, 0, 2),
                         a + QVector3D(0, 0, 2)])
    target = shape.points_at_radius(3.0)[0]
    scene.mesh.add_edge(target, target + QVector3D(0, 0, 1))
    before = scene.mesh.capture_state()
    history = History(scene)
    history.execute(RescaleCurveRadiusCommand(edge, 3.0))
    assert history.last_rejected is not None
    assert scene.mesh.capture_state()["vpos"] == before["vpos"]


def test_nonflat_radius_only_folds_faces_touched_by_the_rim():
    from core.topology import is_planar

    scene = Scene()
    edge = _circle(scene)
    shape = read_curve(scene.mesh, edge)
    a, b = shape.verts[0].position, shape.verts[1].position
    wall = scene.mesh.add_face([a, b, b + QVector3D(0, 0, 3),
                                a + QVector3D(0, 0, 2)])
    wall.attrs["layer"] = "Walls"
    wall.interior = True
    unrelated = scene.mesh.add_face([
        QVector3D(10, 0, 0), QVector3D(11, 0, 0),
        QVector3D(11, 1, 0), QVector3D(10, 1, 1)])
    assert not is_planar(unrelated.vertices)

    history = History(scene)
    history.execute(RescaleCurveRadiusCommand(edge, 3.0))
    assert history.last_error is None and history.last_rejected is None
    assert unrelated in scene.mesh.faces
    assert wall not in scene.mesh.faces
    assert sum(f.attrs.get("layer") == "Walls"
               for f in scene.mesh.faces) >= 2
    assert all(f.interior for f in scene.mesh.faces
               if f.attrs.get("layer") == "Walls")
    history.undo()
    assert wall in scene.mesh.faces and unrelated in scene.mesh.faces
