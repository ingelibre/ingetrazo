# SPDX-License-Identifier: GPL-3.0-or-later
"""Lowering a curved top edge onto the bottom one makes a ramp (#1294).

A box whose front is an arc: moving the top arc down onto the bottom arc
(the endpoint snap) was refused, «Not joined: it would leave two faces
overlapping in one plane. The move was undone.», and the drawing went back
as it was. A flat front gave a ramp (#341); a bent or curved one did not:

* the top face, its back edge still up and its arc now on the ground, was
  folded by earcut, which joined arc points to arc points; those triangles,
  all on the ground, merged into a flat piece over the floor;
* a wall that ran along two segments of the arc, flattened, kept three
  corners, so the weld did not drop it: a face going out and back.

Now the top folds as a strip between its fixed and its moved corners, and
a wall flattened onto edges it already shares is dropped like a single one.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import (AddFaceCommand, History, MoveVerticesCommand,
                          TagCurveCommand)
from core.orient import is_closed
from core.scene import Scene
from core.topology import defects_near
from tests.test_fuzz_engine import _push, _up

L, W, H = 6.0, 2.0, 3.376


def _curved_front_box(segments: int, sag: float, curve: bool = False):
    """A box on a footprint whose back is straight and whose front is
    ``segments`` straight pieces bulging ``sag`` forward (an arc). With
    ``curve`` the front is tagged as one curve, as the Arc tool does."""
    front = [QVector3D(L * i / segments,
                       -sag * math.sin(math.pi * i / segments), 0.0)
             for i in range(segments + 1)]
    corners = front + [QVector3D(L, W, 0.0), QVector3D(0.0, W, 0.0)]
    scene = Scene()
    hist = History(scene)
    sides = [(corners[i], corners[(i + 1) % len(corners)])
             for i in range(len(corners))]
    extra = [AddFaceCommand(list(corners))]
    if curve:
        extra.append(TagCurveCommand(list(front), closed=False))
    hist.execute(build_add_edges(scene, sides, detect_faces=False,
                                 extra=extra))
    base = scene.mesh.faces[0]
    _push(scene, hist, base, _up(base, H))
    return scene, hist, front


def _lower_the_top_front(scene, hist, front):
    top = [QVector3D(p.x(), p.y(), H) for p in front]
    hist.execute(MoveVerticesCommand(top, QVector3D(0.0, 0.0, -H),
                                     carry_textures=True))


def _healthy(scene) -> None:
    assert is_closed(scene.mesh)
    bad = {k: n for k, n in defects_near(scene.mesh.vertices).items() if n}
    assert not bad
    # Nothing but the floor lies on the ground.
    on_ground = [f for f in scene.mesh.faces
                 if all(abs(p.z()) < 1e-6 for p in f.vertices)]
    assert len(on_ground) == 1


@pytest.mark.parametrize("segments, sag", [
    (2, 1.0),       # a front bent once
    (4, 1.0),
    (12, 1.0),      # the arc of the report
    (12, 0.3),      # a flat arc: its end walls are merged on push
    (24, 2.0),
    (48, 1.0),
])
def test_a_curved_top_edge_lowered_onto_the_bottom_makes_a_ramp(
        segments, sag):
    scene, hist, front = _curved_front_box(segments, sag)
    _lower_the_top_front(scene, hist, front)
    assert hist.last_rejected is None
    assert hist.last_error is None
    _healthy(scene)
    # The back edge stays up; every point of the arc is on the ground.
    tops = {(round(p.x(), 6), round(p.y(), 6))
            for v in scene.mesh.vertices for p in [v.position]
            if abs(p.z() - H) < 1e-6}
    assert tops == {(0.0, W), (L, W)}


def _slope(scene):
    """The faces the lowered top became: those with a corner up at the
    back and one on the ground in front of the back edge."""
    return [f for f in scene.mesh.faces
            if any(abs(p.z() - H) < 1e-6 for p in f.vertices)
            and any(abs(p.z()) < 1e-6 and p.y() < W - 1e-6
                    for p in f.vertices)
            and abs(f.normal().x()) < 0.999]      # not a side wall


@pytest.mark.parametrize("curve", [False, True])
def test_the_top_folds_as_sketchup_does_a_flat_piece_and_one_fan(curve):
    """SketchUp folds it as one flat triangle (both back corners and the
    arc's first end) and one fan from a single back corner over the arc,
    not a fan from each back corner."""
    segments = 12
    scene, hist, front = _curved_front_box(segments, 1.0, curve=curve)
    _lower_the_top_front(scene, hist, front)
    slope = _slope(scene)
    assert len(slope) == 1 + segments
    assert all(len(f.loop) == 3 for f in slope)
    back = [(0.0, W, H), (L, W, H)]
    flat = [f for f in slope
            if sum(1 for p in f.vertices
                   if (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))
                   in back) == 2]
    assert len(flat) == 1
    apexes = {tuple(round(c, 6) for c in (p.x(), p.y(), p.z()))
              for f in slope if f not in flat for p in f.vertices
              if abs(p.z() - H) < 1e-6}
    assert len(apexes) == 1                      # ONE fan


def test_an_arc_folds_into_a_smooth_cone_with_one_visible_fold():
    """On an Arc-tool curve the fan's folds are soft, so the cone reads as
    one smooth surface, as the curve's own wall did; the fold between the
    flat piece and the cone stays a line."""
    segments = 12
    scene, hist, front = _curved_front_box(segments, 1.0, curve=True)
    _lower_the_top_front(scene, hist, front)
    _healthy(scene)
    slope = {id(f) for f in _slope(scene)}
    folds = [e for e in scene.mesh.edges
             if len(e.faces) == 2 and all(id(f) in slope for f in e.faces)]
    assert len(folds) == segments                # 11 in the fan + 1
    assert sum(1 for e in folds if e.soft) == segments - 1
    assert sum(1 for e in folds if not e.soft) == 1


def test_a_bent_line_keeps_its_folds_as_lines():
    """A front of plain edges bent twice is not a curve: its folds are
    real edges and stay visible."""
    scene, hist, front = _curved_front_box(2, 1.0)
    _lower_the_top_front(scene, hist, front)
    _healthy(scene)
    assert not [e for e in scene.mesh.edges if e.soft]


def _rounded_corner_box(width: float, radius: float, segments: int,
                        length: float = 8.0):
    """The shape of the report: a long box whose front-right corner is
    rounded by a quarter arc (an Arc-tool curve) from the front, ending
    tangent to the right side. Push/pull merges that side with the arc's
    last, nearly flat, wall."""
    cx, cy = width - radius, radius
    arc = [QVector3D(cx + radius * math.sin(math.pi / 2 * i / segments),
                     cy - radius * math.cos(math.pi / 2 * i / segments), 0.0)
           for i in range(segments + 1)]
    front = ([QVector3D(0.0, 0.0, 0.0)] if radius < width else []) + arc
    corners = front + [QVector3D(width, length, 0.0),
                       QVector3D(0.0, length, 0.0)]
    scene = Scene()
    hist = History(scene)
    sides = [(corners[i], corners[(i + 1) % len(corners)])
             for i in range(len(corners))]
    hist.execute(build_add_edges(
        scene, sides, detect_faces=False,
        extra=[AddFaceCommand(list(corners)),
               TagCurveCommand(list(arc), closed=False)]))
    base = scene.mesh.faces[0]
    _push(scene, hist, base, _up(base, H))
    return scene, hist, arc


@pytest.mark.parametrize("width, radius, segments", [
    (2.5, 2.5, 12),     # the report: the arc from the front-left corner
    (2.5, 1.5, 12),     # a straight bit of front before the arc
    (3.0, 3.0, 24),     # its last wall merged into the side: a spur
    (2.0, 2.0, 6),
])
def test_the_reported_rounded_corner_lowered_makes_a_ramp(
        width, radius, segments):
    scene, hist, arc = _rounded_corner_box(width, radius, segments)
    _lower_the_top_front(scene, hist, arc)
    assert hist.last_rejected is None
    assert hist.last_error is None
    _healthy(scene)
    assert sum(1 for e in scene.mesh.edges if e.soft) == segments - 1


def test_the_ramp_undoes_to_the_box():
    scene, hist, front = _curved_front_box(12, 1.0)
    faces_before = len(scene.mesh.faces)
    _lower_the_top_front(scene, hist, front)
    assert hist.last_rejected is None
    hist.undo()
    assert len(scene.mesh.faces) == faces_before
    assert is_closed(scene.mesh)


def test_a_flat_front_still_makes_the_ramp_it_made():
    scene, hist, front = _curved_front_box(1, 0.0)
    _lower_the_top_front(scene, hist, front)
    assert hist.last_rejected is None
    assert len(scene.mesh.faces) == 5           # #341: a wedge
    _healthy(scene)


def test_a_join_that_doubles_a_face_is_still_refused():
    """The guard stays: dropping the top onto the floor flattens the
    whole box into the floor's plane, its top over its bottom."""
    scene, hist, _front = _curved_front_box(1, 0.0)
    top = [QVector3D(x, y, H) for x, y in ((0, 0), (L, 0), (L, W), (0, W))]
    faces_before = len(scene.mesh.faces)
    hist.execute(MoveVerticesCommand(top, QVector3D(0.0, 0.0, -H)))
    assert hist.last_rejected
    assert len(scene.mesh.faces) == faces_before
