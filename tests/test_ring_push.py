# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Concentric-rings push (the 'eye' model): three concentric circles on a slab,
pushed ring by ring. Each ring rises against the wall of the one around it —
the new prism's side lands back to back on an existing wall, the shape of
issue #94. That used to be the known deep class (the wall kept as an interior
partition, then the next push refused); since #94 the wall goes and every push
lands with the exact volume. The guard still refuses what would break the
solid — see the tops-out test below."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import (
    AddFaceCommand,
    History,
    RebuildPlanarFacesCommand,
    TagCurveCommand,
)
from core.orient import is_closed
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool


class _Vp:
    """Just enough viewport for a scripted push (no Qt widgets)."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.messages = []

    def set_hover(self, *_):
        pass

    def set_suppressed_faces(self, *_):
        pass

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.messages.append(text)


def _circle(r):
    return [QVector3D(r * math.cos(2 * math.pi * i / 24),
                      r * math.sin(2 * math.pi * i / 24), 0) for i in range(24)]


def _setup():
    scene = Scene()
    vp = _Vp(scene)

    def V(x, y):
        return QVector3D(x, y, 0)

    sq = [V(-8, -8), V(8, -8), V(8, 8), V(-8, 8)]
    vp.history.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)],
        detect_faces=True, extra=[AddFaceCommand(sq)]))
    for r in (5, 3, 1.5):
        pts = _circle(r)
        segs = [(pts[i], pts[(i + 1) % 24]) for i in range(24)]
        vp.history.execute(build_add_edges(
            scene, segs, detect_faces=False,
            extra=[TagCurveCommand(list(pts), closed=True),
                   RebuildPlanarFacesCommand()]))
    return vp, scene


def _push(vp, face, dist):
    pp = PushPullTool()
    pp.hovered_face = face
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=QVector3D(0, 0, 0),
                            screen=QPointF(500, 350),
                            modifiers=Qt.NoModifier, snap=None))
    pp.extrusion = dist
    pp._commit(vp)


def _at0(f):
    return all(abs(v.position.z()) < 1e-6 for v in f.loop)


def _rings(scene):
    ext = [f for f in scene.mesh.faces if _at0(f) and len(f.loop) == 4
           and f.hole_loops][0]
    return ext


def _volume(mesh):
    v = 0.0
    for f in mesh.faces:
        for a, b, c in f.triangulate():
            v += QVector3D.dotProduct(a, QVector3D.crossProduct(b, c)) / 6.0
    return v


def test_ring_pushes_between_levels_land_exactly():
    """Each ring rises against the wall of the one around it — the side of
    the new prism lands back to back on an existing wall, as in #94. Until
    #94 the first push kept that wall as an interior partition (volume
    391.9 instead of 406.4) and the second was refused outright; now the
    wall between them goes and both land with the exact volume."""
    vp, sc = _setup()
    _push(vp, _rings(sc), 2.0)
    v0 = _volume(sc.mesh)
    ring1 = [f for f in sc.mesh.faces if _at0(f)
             and abs(f.area() - 77.65) < 2 and f.hole_loops][0]
    a1 = ring1.area() - 27.95                       # r5 minus its r3 hole
    _push(vp, ring1, 1.0)
    assert is_closed(sc.mesh)
    assert abs(_volume(sc.mesh) - (v0 + a1 * 1.0)) < 2e-2
    ring2 = [f for f in sc.mesh.faces if _at0(f)
             and abs(f.area() - 27.95) < 2 and f.hole_loops][0]
    a2 = ring2.area() - 6.99                        # r3 minus its r1.5 hole
    v1 = _volume(sc.mesh)
    _push(vp, ring2, 0.5)
    assert is_closed(sc.mesh)
    assert abs(_volume(sc.mesh) - (v1 + a2 * 0.5)) < 2e-2
    assert not any("refused" in m.lower() for m in vp.messages)
    # No wall stays inside the solid: every edge of the rings' solid has
    # two faces, bar the membranes still spanning the innermost hole.
    from collections import Counter
    assert Counter(len(e.faces) for e in sc.mesh.edges)[3] == 24


def test_refused_push_tops_out_at_the_reachable_height():
    # The pure eye model: three concentric circles ONLY (the whole disc, so
    # the first push leaves a closed mesh and the guard is armed). Pushing the
    # iris (middle annulus) up to the EXACT level of the already-raised outer
    # ring is digested by the rebuild and refused by the guard. Refusing
    # outright would leave the user's drag doing nothing, so the COMMIT
    # bisects down to the furthest height the guard accepts and lands there.
    # (The drag itself is an overlay now — no pipeline runs until the commit.)
    from tools.circle import CircleTool

    scene = Scene()
    vp = _Vp(scene)
    for r in (5, 3, 1.5):
        t = CircleTool()
        t.work_plane = None
        for x in (0, r):
            t.on_click(ToolContext(viewport=vp, world=QVector3D(x, 0, 0),
                                   screen=QPointF(0, 0),
                                   modifiers=Qt.NoModifier, snap=None))

    def face_by_area(area):
        return next(f for f in scene.mesh.faces
                    if abs(f.area() - area) < 0.6
                    and all(abs(v.position.z()) < 1e-6 for v in f.loop))

    _push(vp, face_by_area(77.6), 2.0)             # outer ring up 2
    vp.messages.clear()
    iris = face_by_area(28.0)
    pp = PushPullTool()
    pp.hovered_face = iris
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=QVector3D(0, 0, 0),
                            screen=QPointF(500, 350),
                            modifiers=Qt.NoModifier, snap=None))
    faces_before = len(scene.mesh.faces)
    for d in (1.5, 1.9, 2.0, 2.4):                 # a drag across the level
        pp.extrusion = d
        pp._show_light_preview(vp)
        assert len(scene.mesh.faces) == faces_before   # overlay only
    pp.extrusion = 2.4
    pp._commit(vp)

    assert is_closed(scene.mesh)                   # never commits a crack
    assert len(scene.mesh.faces) != faces_before   # ...and it DID something
    assert 0.0 < PushPullTool.last_distance < 2.4  # topped out below the level
    cap_z = {round(v.position.z(), 4)
             for f in scene.mesh.faces for v in f.loop}
    assert any(abs(z - PushPullTool.last_distance) < 1e-3 for z in cap_z)
    assert any("stopped" in m.lower() for m in vp.messages)


def test_add_face_drops_nested_holes():
    """A hole inside another hole of the same face is geometric nonsense: it
    corrupts earcut (phantom wedge triangles across the opening — the 'eye'
    model's visible symptom) and registers the face on rim edges it does not
    touch, letting ``is_closed`` bless a broken solid. ``mesh.add_face`` is the
    single choke point (draw, push rebuild, heal, ``.igz`` load) — it must keep
    only the outermost hole."""
    sc = Scene()
    outer = [QVector3D(x, y, 2.0) for x, y in
             ((-4, -4), (4, -4), (4, 4), (-4, 4))]
    big = _circle(2.0)
    small = _circle(0.8)
    for lp in (big, small):
        for p in lp:
            p.setZ(2.0)
    face = sc.mesh.add_face(outer, [big, small])
    assert len(face.hole_loops) == 1                # nested r=0.8 dropped
    hole_r = {round(math.hypot(v.position.x(), v.position.y()), 1)
              for v in face.hole_loops[0]}
    assert hole_r == {2.0}
    # earcut stays sane: no triangle lands inside the opening
    for a, b, c in face.triangulate():
        cen = (a + b + c) / 3.0
        assert math.hypot(cen.x(), cen.y()) > 2.0 - 1e-6
