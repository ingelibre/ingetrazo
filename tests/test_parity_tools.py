# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SketchUp-parity batch: Pie, arc radius suffix, Make Component,
Make Unique, Flip and Freehand."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import (
    FlipGroupsCommand,
    FlipVerticesCommand,
    History,
    MakeGroupCommand,
    MakeUniqueCommand,
    mirror_matrix,
)
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass

    def set_hover(self, *_):
        pass


def _ctx(vp, x, y, z=0.0, sx=None, sy=None):
    return ToolContext(viewport=vp, world=V(x, y, z),
                       screen=QPointF(sx if sx is not None else x * 100.0,
                                      sy if sy is not None else y * 100.0),
                       modifiers=Qt.NoModifier, snap=None)


# ---- Pie + radius suffix ----------------------------------------------------

def test_pie_closes_the_wedge_with_a_face():
    from tools.arc import PieTool
    scene = Scene()
    vp = _Vp(scene)
    t = PieTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))                     # centre
    t.on_click(_ctx(vp, 2, 0))                     # radius arm (r = 2)
    t.on_hover(_ctx(vp, 0, 2))
    t.on_click(_ctx(vp, 0, 2))                     # sweep 90°
    assert len(scene.mesh.faces) == 1              # the wedge closed
    # Both radius edges reach the centre.
    at_centre = [e for e in scene.mesh.edges
                 if (e.a.length() < 1e-6 or e.b.length() < 1e-6)]
    assert len(at_centre) == 2
    area = scene.mesh.faces[0].area()
    assert abs(area - math.pi) < 0.15              # quarter circle r=2 ≈ π
    assert vp.history.undo()
    assert len(scene.mesh.faces) == 0


def test_arc_radius_suffix_parses_and_commits():
    from views.viewport import Viewport
    kind, r = Viewport._parse_value_buffer("2r")
    assert kind == "radius" and r == 2.0
    assert Viewport._parse_value_buffer("2.5r") == ("radius", 2.5)
    assert Viewport._parse_value_buffer("r") is None

    from tools.arc import ArcTool
    scene = Scene()
    vp = _Vp(scene)
    t = ArcTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))
    t.on_click(_ctx(vp, 2, 0))                     # chord L=2 → half=1
    t.on_hover(_ctx(vp, 1, 1))                     # bulge side +Y
    assert t.on_radius_value(vp, 0.4) is True      # r < half: refused
    assert len(scene.mesh.edges) == 0
    t.on_click(_ctx(vp, 0, 0))                     # restart (refusal reset it?)
    # The refusal does NOT reset the chord — retype works:
    t2 = ArcTool()
    t2.on_activate(vp)
    t2.on_click(_ctx(vp, 0, 0))
    t2.on_click(_ctx(vp, 2, 0))
    t2.on_hover(_ctx(vp, 1, 1))
    assert t2.on_radius_value(vp, 1.0) is True     # r = half → semicircle
    assert len(scene.mesh.edges) > 4               # a real arc landed
    tops = [max(e.a.y(), e.b.y()) for e in scene.mesh.edges]
    assert abs(max(tops) - 1.0) < 0.05             # sagitta = radius = 1


# ---- Make Component / Make Unique -------------------------------------------

def test_make_component_shares_definition_with_copies():
    from core.group import copy_group
    scene = Scene()
    hist = History(scene)
    f = scene.mesh.add_face([V(2, 3), V(4, 3), V(4, 5), V(2, 5)])
    hist.execute(MakeGroupCommand([f], [], component=True, name="Columna"))
    assert len(scene.groups) == 1
    inst = scene.groups[0]
    assert inst.name == "Columna"
    assert inst.xform is not None                  # it IS an instance
    # Prototype lives in LOCAL coordinates (min corner at the origin)…
    lx = [v.position.x() for v in inst.mesh.vertices]
    ly = [v.position.y() for v in inst.mesh.vertices]
    assert min(lx) == 0.0 and min(ly) == 0.0
    # …and the transform puts it back exactly where it was drawn.
    w = inst.xform.map(V(0, 0, 0))
    assert abs(w.x() - 2.0) < 1e-9 and abs(w.y() - 3.0) < 1e-9
    # A copy SHARES the definition (SketchUp components).
    twin = copy_group(inst)
    assert twin.mesh is inst.mesh
    assert hist.undo()
    assert scene.groups == []


def test_make_unique_detaches_the_instance():
    scene = Scene()
    hist = History(scene)
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    a = Group(proto, name="Poste")
    from PySide6.QtGui import QMatrix4x4
    a.xform = QMatrix4x4()
    scene.groups.append(a)
    hist.execute(MakeUniqueCommand(a))
    assert a.xform is None and a.mesh is not proto  # its own mesh now
    assert hist.undo()
    assert a.mesh is proto and a.xform is not None  # sharing restored


# ---- Flip -------------------------------------------------------------------

def test_mirror_matrix_reflects_and_is_involutive():
    m = mirror_matrix(V(1, 0, 0), V(1, 0, 0))
    p = m.map(V(3, 2, 5))
    assert abs(p.x() + 1.0) < 1e-6                # x: 3 → 2·1−3 = −1
    assert abs(p.y() - 2.0) < 1e-6 and abs(p.z() - 5.0) < 1e-6
    back = m.map(p)
    assert (back - V(3, 2, 5)).length() < 1e-6


def test_flip_vertices_mirrors_and_keeps_faces_outward():
    scene = Scene()
    hist = History(scene)
    f = scene.mesh.add_face([V(1, 0), V(3, 0), V(3, 2), V(1, 2)])
    n0 = QVector3D(f.normal())
    pos = [QVector3D(v) for v in f.vertices]
    hist.execute(FlipVerticesCommand(pos, V(2, 1, 0), V(1, 0, 0), faces=[f]))
    xs = sorted(round(v.x()) for v in scene.mesh.faces[0].vertices)
    assert xs == [1, 1, 3, 3]                      # mirrored about x=2
    n1 = scene.mesh.faces[0].normal()
    assert QVector3D.dotProduct(n0, n1) > 0.99     # still facing the same way
    assert hist.undo()


def test_flip_tool_flips_group_and_copy_mode():
    from tools.flip import FlipTool
    scene = Scene()
    vp = _Vp(scene)
    m = Mesh()
    m.add_face([V(1, 0), V(2, 0), V(2, 1), V(1, 1)])
    g = Group(m)
    scene.groups.append(g)
    scene.selection.add(g)

    t = FlipTool()
    t.on_activate(vp)
    assert t.on_key(vp, Qt.Key_Right, Qt.NoModifier) is True   # red = X plane
    t.on_click(_ctx(vp, 0, 0))
    xs = sorted(round(v.position.x(), 2) for v in g.mesh.vertices)
    assert xs == [1.0, 1.0, 2.0, 2.0]              # mirrored about centre 1.5
    assert vp.history.undo()

    assert t.on_key(vp, Qt.Key_Control, Qt.NoModifier) is True  # copy mode
    assert t._lock_axis == "x"                     # the red lock stays armed
    t.on_click(_ctx(vp, 0, 0))
    assert len(scene.groups) == 2                  # original + flipped copy
    assert t._copy is False                        # one-shot modifier
    assert vp.history.undo()
    assert scene.groups == [g]


# ---- Freehand ---------------------------------------------------------------

def test_freehand_stroke_lands_as_one_curve():
    from tools.freehand import FreehandTool
    scene = Scene()
    vp = _Vp(scene)
    t = FreehandTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))
    for i in range(1, 30):
        x = i * 0.2
        t.on_hover(_ctx(vp, x, math.sin(x)))
    t.on_release(vp)
    edges = scene.mesh.edges
    assert len(edges) >= 4                         # simplified, not 30 raw
    ids = {e.curve for e in edges}
    assert len(ids) == 1 and None not in ids       # ONE selectable contour
    assert vp.history.undo()
    assert len(scene.mesh.edges) == 0


def test_freehand_closed_stroke_forms_a_face():
    from tools.freehand import FreehandTool
    scene = Scene()
    vp = _Vp(scene)
    t = FreehandTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))
    for ang in range(12, 360, 12):                 # walk a circle back home
        a = math.radians(ang)
        t.on_hover(_ctx(vp, 2 - 2 * math.cos(a), 2 * math.sin(a)))
    t.on_hover(_ctx(vp, 0.001, 0.001, sx=0.4, sy=0.4))
    t.on_release(vp)
    assert len(scene.mesh.faces) == 1              # the loop became a face


def test_group_converts_to_component_in_place():
    # Make Component on a CLASSIC group: in-place conversion, free — the
    # mesh becomes the shared definition under an identity transform (no
    # explode detour, no geometry copied).
    from PySide6.QtGui import QVector3D
    from core.group import Group
    from core.history import GroupToComponentCommand, History
    from core.mesh import Mesh
    from core.scene import Scene

    scene = Scene()
    hist = History(scene)
    m = Mesh()
    m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    g = Group(m, name="Seto")
    scene.groups.append(g)

    hist.execute(GroupToComponentCommand(g, "Arbusto"))
    assert g.xform is not None and g.xform.isIdentity()
    assert g.mesh is m                      # free: same mesh, no copy
    assert g.name == "Arbusto"

    assert hist.undo() is True
    assert g.xform is None and g.name == "Seto"
