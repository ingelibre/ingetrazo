# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Offset tool geometry — polygon offset + the ring/inner face split.

Walls with thickness: offsetting a face's boundary inward splits it into a ring
(the wall footprint) and an inner face (the room), both coplanar.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import AddFaceCommand, CompoundCommand, DeleteFaceCommand, History
from core.scene import Scene
from core.topology import offset_loop


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


# ---- offset_loop ------------------------------------------------------------

def test_offset_inward_shrinks_rectangle():
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    off = offset_loop(loop, V(0, 0, 1), 0.5)
    keys = {(round(p.x(), 2), round(p.y(), 2)) for p in off}
    assert keys == {(0.5, 0.5), (3.5, 0.5), (3.5, 3.5), (0.5, 3.5)}


def test_offset_outward_grows_rectangle():
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    off = offset_loop(loop, V(0, 0, 1), -0.5)
    keys = {(round(p.x(), 2), round(p.y(), 2)) for p in off}
    assert keys == {(-0.5, -0.5), (4.5, -0.5), (4.5, 4.5), (-0.5, 4.5)}


def test_offset_overshoot_rejected():
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]   # half-width 2
    assert offset_loop(loop, V(0, 0, 1), 2.0) is None   # exactly collapses
    assert offset_loop(loop, V(0, 0, 1), 3.0) is None   # crosses


def test_offset_on_vertical_wall_plane():
    wall = [V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)]  # XZ plane, normal -Y
    off = offset_loop(wall, V(0, -1, 0), 0.5)
    assert off is not None
    assert all(abs(p.y()) < 1e-9 for p in off)            # stays in the plane
    zs = sorted({round(p.z(), 2) for p in off})
    assert zs == [0.5, 2.5]


# ---- the ring / inner split (what OffsetTool._commit builds) -----------------

def test_offset_split_makes_ring_and_inner():
    scene = Scene()
    hist = History(scene)
    face = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    inner = offset_loop([V(p.x(), p.y(), p.z()) for p in face.vertices], V(0, 0, 1), 1.0)

    hist.execute(CompoundCommand([
        DeleteFaceCommand(face),
        AddFaceCommand([V(0, 0), V(4, 0), V(4, 4), V(0, 4)], auto=False, holes=[list(inner)]),
        AddFaceCommand(list(inner), auto=False),
    ]))

    assert len(scene.mesh.faces) == 2
    ring = next(f for f in scene.mesh.faces if f.holes)
    inner_face = next(f for f in scene.mesh.faces if not f.holes)
    assert len(ring.holes) == 1                       # the ring is an annulus
    assert abs(ring.area() - 16.0) < 1e-6             # outer 4×4 boundary
    assert abs(inner_face.area() - 4.0) < 1e-6        # the 2×2 room
    # The ring's hole is exactly the inner face's loop.
    hole_keys = {(round(p.x(), 2), round(p.y(), 2)) for p in ring.holes[0]}
    inner_keys = {(round(p.x(), 2), round(p.y(), 2)) for p in inner_face.vertices}
    assert hole_keys == inner_keys == {(1, 1), (3, 1), (3, 3), (1, 3)}

    assert hist.undo() is True
    assert len(scene.mesh.faces) == 1
    assert abs(scene.mesh.faces[0].area() - 16.0) < 1e-6


def test_pushing_an_offset_ring_raises_walls_with_thickness():
    from core.history import History
    from tools.pushpull import PushPullTool

    class _VP:
        def __init__(self, scene, history):
            self.scene, self.history = scene, history
        def set_hover(self, *a): pass
        def set_suppressed_faces(self, *a): pass
        def update(self): pass

    scene = Scene()
    hist = History(scene)
    m = scene.mesh
    outer = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    inner = offset_loop([QVector3D(p) for p in outer], V(0, 0, 1), 0.15)
    m.add_face([QVector3D(p) for p in inner])          # room floor
    ring = m.add_face(list(outer), [list(inner)])      # wall footprint (annulus)

    tool = PushPullTool()
    tool.base_face = ring
    tool.extrusion = 3.0
    tool._normal = ring.normal()
    tool._prism_cap = False
    tool._anchor = ring.centroid()
    tool._mutate(scene)

    # Watertight, the room floor stays, the cap is a holed annulus up top, and
    # both wall rings (outer + inner) rose: 4 + 4 wall quads.
    assert sum(1 for e in m.edges if len(e.faces) == 1) == 0
    assert any(not f.holes and all(abs(v.z()) < 1e-6 for v in f.vertices)
               for f in m.faces)                                       # floor
    assert sum(1 for f in m.faces if f.holes
               and all(abs(v.z() - 3) < 1e-6 for v in f.vertices)) == 1  # cap
    walls = [f for f in m.faces
             if sorted({round(v.z(), 1) for v in f.vertices}) == [0.0, 3.0]]
    assert len(walls) == 8


def test_offset_value_label_and_vcb():
    from tools.offset import OffsetTool
    from tools.base import ToolContext
    from PySide6.QtCore import QPointF, Qt

    class _MockVP:
        def __init__(self, scene, history):
            self.scene, self.history = scene, history
        def set_hover(self, *a): pass
        def update(self): pass
        def _pixel_to_ray(self, sx, sy):
            return QVector3D(sx, sy, 10), QVector3D(0, 0, -1)

    scene = Scene()
    hist = History(scene)
    face = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    vp = _MockVP(scene, hist)

    tool = OffsetTool()
    assert tool.value_label() is None

    # Hover and click on face to start offset
    tool.hovered_face = face
    ctx = ToolContext(viewport=vp, world=V(2, 0), screen=QPointF(2, 0),
                      modifiers=Qt.NoModifier, snap=None)
    tool.on_click(ctx)
    assert tool.dragging is True

    # Hover at inward position
    ctx_drag = ToolContext(viewport=vp, world=V(2, 0.5), screen=QPointF(2, 0.5),
                           modifiers=Qt.NoModifier, snap=None)
    tool.on_hover(ctx_drag)
    assert abs(tool.distance - 0.5) < 1e-4

    # value_label returns (text, midpoint)
    vl = tool.value_label()
    assert vl is not None
    text, mid = vl
    from core.units import fmt_len
    assert text == fmt_len(abs(tool.distance))
    assert mid is not None

    # on_value during dragging
    assert tool.on_value(vp, 1.0) is True
    assert tool.dragging is False
    assert len(scene.mesh.faces) == 2

    # Verify inner face at 1.0 offset (2x2 area = 4)
    inner = next(f for f in scene.mesh.faces if not f.holes)
    assert abs(inner.area() - 4.0) < 1e-4

    # Hot retype: adjust offset after commit by typing 0.5
    assert tool.on_value(vp, 0.5) is True
    inner = next(f for f in scene.mesh.faces if not f.holes)
    assert abs(inner.area() - 9.0) < 1e-4

    # Hot retype window closes if another command is executed
    hist.execute(CompoundCommand([]))
    assert tool.on_value(vp, 0.8) is False


def test_offset_viewport_measurement_text():
    from views.viewport import Viewport
    from tools.offset import OffsetTool
    vp = Viewport.__new__(Viewport)
    tool = OffsetTool()
    vp.active_tool = tool
    assert vp._measurement_text() == ""
    tool.dragging = True
    tool._ref_point = V(0, 0, 0)
    tool._ref_inward = V(0, 1, 0)
    tool.distance = 0.25
    # In the document's own unit and precision, whatever an earlier test
    # left them at: the box shows what fmt_len shows.
    from core.units import fmt_len
    assert vp._measurement_text() == fmt_len(0.25)




def test_a_refused_hot_retype_keeps_the_offset_already_made():
    """Typing 1 then 3 on a 4 × 4 face: 3 is too far and is refused, and
    the 1 m offset must stay (it vanished: the retype undid it first)."""
    from tools.offset import OffsetTool
    from tools.base import ToolContext
    from PySide6.QtCore import QPointF, Qt

    class _MockVP:
        def __init__(self, scene, history):
            self.scene, self.history = scene, history
        def set_hover(self, *a): pass
        def update(self): pass
        def flash_status(self, *a, **k): pass
        def _pixel_to_ray(self, sx, sy):
            return QVector3D(sx, sy, 10), QVector3D(0, 0, -1)

    scene = Scene()
    hist = History(scene)
    face = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    vp = _MockVP(scene, hist)
    tool = OffsetTool()
    tool.hovered_face = face
    tool.on_click(ToolContext(viewport=vp, world=V(2, 0), screen=QPointF(2, 0),
                              modifiers=Qt.NoModifier, snap=None))
    tool.on_hover(ToolContext(viewport=vp, world=V(2, 0.5),
                              screen=QPointF(2, 0.5),
                              modifiers=Qt.NoModifier, snap=None))
    assert tool.on_value(vp, 1.0) is True
    assert len(scene.mesh.faces) == 2
    steps = len(hist.undo_stack)
    tool.on_value(vp, 3.0)                 # too far: refused
    assert len(scene.mesh.faces) == 2
    assert len(hist.undo_stack) == steps
    assert tool.on_value(vp, 0.5) is True  # the window is still open
    inner = next(f for f in scene.mesh.faces if not f.holes)
    assert abs(inner.area() - 9.0) < 1e-4
