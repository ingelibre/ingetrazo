# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A group or component instance takes a material of its own (issue #47,
@pacaeiro), by the usual rules as he spelled them out:

  a. a face carries its own material (front, and a back of its own);
  b. the container's material dresses every face inside that wears the
     default material, front and back;
  the face's own material always wins over the container's;
  d. exploding the container leaves its paint on the faces that wore it.
"""
from __future__ import annotations

import types

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, copy_group, effective_material
from core.history import (ExplodeGroupCommand, History,
                          SetGroupMaterialCommand)
from core.materials import effective_attrs, has_own_material
from core.mesh import Mesh
from core.scene import Scene
from formats import igz
from tools.base import ToolContext
from tools.paint import PaintTool
from views.viewport import Viewport


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


RED = {"color": [1.0, 0.0, 0.0]}


# ---- the rule -------------------------------------------------------------

def test_effective_attrs_lets_the_faces_own_paint_win():
    assert effective_attrs({}, RED)["color"] == [1.0, 0.0, 0.0]
    assert effective_attrs({}, RED)["back"] is True          # both sides
    own = {"color": [0.0, 0.0, 1.0]}
    assert effective_attrs(own, RED) is own                  # untouched
    tex = {"texture": {"path": "x.png", "sw": 1.0, "sh": 1.0}}
    assert effective_attrs(tex, RED) is tex
    assert effective_attrs({"opacity": 0.5}, None) == {"opacity": 0.5}
    assert not has_own_material({}) and has_own_material(own)


def test_effective_material_reaches_a_nested_piece_through_its_owner():
    top = Group(Mesh(), "silla")
    top.material = RED
    piece = Group(Mesh(), "pata")
    piece.owner = top
    assert effective_material(piece) is RED
    piece.material = {"color": [0, 1, 0]}
    assert effective_material(piece)["color"] == [0, 1, 0]   # its own first
    assert effective_material(Group()) is None


# ---- command, copy, file --------------------------------------------------

def _two_face_group(scene):
    m = Mesh()
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])           # default paint
    blue = m.add_face([V(2, 0), V(3, 0), V(3, 1), V(2, 1)])
    blue.attrs["color"] = [0.0, 0.0, 1.0]                       # its own
    g = Group(m, "caja")
    scene.groups.append(g)
    scene.version += 1
    return g, blue


def test_set_group_material_is_one_undo_step_and_touches_no_face():
    scene = Scene()
    hist = History(scene)
    g, blue = _two_face_group(scene)
    hist.execute(SetGroupMaterialCommand(g, RED))
    assert g.material == RED
    assert blue.attrs["color"] == [0.0, 0.0, 1.0]
    assert "color" not in g.mesh.faces[0].attrs                 # still default
    hist.undo()
    assert g.material is None
    hist.redo()
    assert g.material == RED
    assert copy_group(g).material == RED


def test_the_group_material_survives_the_igz(tmp_path):
    scene = Scene()
    g, _blue = _two_face_group(scene)
    g.material = dict(RED)
    path = tmp_path / "pintado.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.groups[0].material == RED


def test_explode_leaves_the_paint_on_the_faces_that_wore_it():
    scene = Scene()
    hist = History(scene)
    g, _blue = _two_face_group(scene)
    g.material = dict(RED)
    hist.execute(ExplodeGroupCommand(g))
    colours = sorted(tuple(f.attrs.get("color")) for f in scene.mesh.faces)
    assert colours == [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0)]       # own kept, default took it
    hist.undo()
    assert not scene.mesh.faces and g.material == RED


# ---- the bake: what the viewport actually draws ---------------------------

class _VP:
    def __init__(self, scene):
        self.scene = scene

    def width(self):
        return 100

    def height(self):
        return 100


def _stub(scene):
    """A Viewport with no GL: every plain method bound (the recipe of
    test_chunk_stale_materials)."""
    vp = _VP(scene)
    for name in dir(Viewport):
        if name.startswith("__") or hasattr(vp, name):
            continue
        attr = next((k.__dict__[name] for k in Viewport.__mro__
                     if k.__module__.startswith("views.viewport")
                     and name in k.__dict__), None)
        if isinstance(attr, types.FunctionType):
            setattr(vp, name, attr.__get__(vp))
        elif isinstance(attr, staticmethod):
            setattr(vp, name, attr.__func__)
        elif not callable(attr) and attr is not None:
            setattr(vp, name, attr)
    vp.active_tool = None
    vp._chunk_cache_load = None
    vp._chunk_cache_store = None
    return vp


def _vcol_colours(entry):
    import numpy as np
    raw = entry["vcol"]
    arr = np.frombuffer(raw if isinstance(raw, (bytes, bytearray)) else raw.tobytes(),
                        dtype=np.float32).reshape(-1, 6)
    return {tuple(round(float(c), 3) for c in row[3:6]) for row in arr}


def test_the_bake_dresses_default_faces_and_keeps_painted_ones():
    scene = Scene()
    vp = _stub(scene)
    g, _blue = _two_face_group(scene)
    plain = _vcol_colours(vp._group_chunk(g))
    red_shaded = tuple(round(float(c), 3)
                       for c in vp._shaded_color((1.0, 0.0, 0.0), V(0, 0, 1)))
    blue_shaded = tuple(round(float(c), 3)
                        for c in vp._shaded_color((0.0, 0.0, 1.0), V(0, 0, 1)))
    assert blue_shaded in plain and red_shaded not in plain
    g.material = dict(RED)
    scene.version += 1
    painted = _vcol_colours(vp._group_chunk(g))
    assert red_shaded in painted and blue_shaded in painted   # rule: own wins
    g.material = None
    scene.version += 1
    assert red_shaded not in _vcol_colours(vp._group_chunk(g))  # unpaint rebakes


def test_two_instances_of_one_prototype_can_wear_different_paint():
    scene = Scene()
    vp = _stub(scene)
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    a, b = Group(proto, "a"), Group(proto, "b")
    for g, dx in ((a, 0.0), (b, 3.0)):
        xf = QMatrix4x4()
        xf.translate(dx, 0, 0)
        g.xform = xf
        scene.groups.append(g)
    b.material = dict(RED)
    scene.version += 1
    red_shaded = tuple(round(float(c), 3)
                       for c in vp._shaded_color((1.0, 0.0, 0.0), V(0, 0, 1)))
    assert red_shaded not in _vcol_colours(vp._group_chunk(a))
    assert red_shaded in _vcol_colours(vp._group_chunk(b))


# ---- the tool --------------------------------------------------------------

class _PaintVP:
    """Enough viewport for Paint: the face under the cursor belongs to a
    group picked from outside."""

    def __init__(self, scene, face, group):
        self.scene = scene
        self.history = History(scene)
        self._face, self._group = face, group
        self.flashed: list = []

    def pick_face_any(self, x, y):
        return self._face, self._group

    def pick_group(self, x, y):
        return self._group

    def _pixel_to_ray(self, x, y):
        return None, None

    def set_hover(self, e):
        pass

    def update(self):
        pass

    def flash_status(self, text, *a, **k):
        self.flashed.append(text)


def _ctx(vp, modifiers=Qt.NoModifier):
    return ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                       modifiers=modifiers, snap=None)


def test_paint_clicked_on_a_group_from_outside_paints_the_group():
    scene = Scene()
    g, blue = _two_face_group(scene)
    default_face = g.mesh.faces[0]
    vp = _PaintVP(scene, default_face, g)
    PaintTool.current_color = (1.0, 0.0, 0.0)
    PaintTool.current_texture = None
    PaintTool.current_opacity = None
    PaintTool.current_material = None
    tool = PaintTool()
    tool.on_click(_ctx(vp))
    assert g.material == {"color": [1.0, 0.0, 0.0]}
    assert "color" not in default_face.attrs                    # the face itself untouched
    assert blue.attrs["color"] == [0.0, 0.0, 1.0]
    vp.history.undo()
    assert g.material is None


def test_the_eyedropper_on_a_default_face_inside_a_painted_group_samples_the_groups_paint():
    scene = Scene()
    g, _blue = _two_face_group(scene)
    g.material = {"color": [0.2, 0.4, 0.6]}
    vp = _PaintVP(scene, g.mesh.faces[0], g)
    PaintTool.current_color = (1.0, 1.0, 1.0)
    tool = PaintTool()
    tool.on_click(_ctx(vp, Qt.AltModifier))
    assert tuple(round(c, 3) for c in PaintTool.current_color) == (0.2, 0.4, 0.6)


# ---- the .skp keeps it on the instance ------------------------------------

def test_the_skp_carries_the_instance_paint(tmp_path):
    openskp = __import__("pytest").importorskip("openskp")
    from formats.skp_out import save_skp
    scene = Scene()
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    a, b = Group(proto, "a"), Group(proto, "b")
    for g, dx in ((a, 0.0), (b, 3.0)):
        xf = QMatrix4x4()
        xf.translate(dx, 0, 0)
        g.xform = xf
        scene.groups.append(g)
    b.material = {"color": [1.0, 0.0, 0.0], "mat": "Rojo contenedor"}
    path = tmp_path / "pintado.skp"
    save_skp(scene, str(path))
    model = openskp.SkpFile.open(str(path)).parse()
    names = {getattr(m, "name", "") for m in (getattr(model, "materials", None) or [])}
    assert "Rojo_contenedor" in names          # export-safe spelling
    # openskp reads the instance's material back where it exposes it.
    root = getattr(model, "root", None)
    insts = list(getattr(root, "instances", []) or []) if root is not None else []
    painted = [i for i in insts if getattr(i, "material", None) not in (None, "", 0)]
    if insts and any(hasattr(i, "material") for i in insts):
        assert len(painted) == 1, [getattr(i, "material", None) for i in insts]


# ---- the instanced draw pools by paint too --------------------------------

def test_the_instanced_pool_splits_a_painted_instance_from_its_siblings():
    """Marco, bench test 21: painted from outside, the cube did not change;
    inside (the loose bake) it was red. The instanced pass pooled by
    prototype mesh alone and drew every sibling from the plain bake."""
    scene = Scene()
    vp = _stub(scene)
    vp.camera = None
    vp._preview_groups = None
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    a, b = Group(proto, "a"), Group(proto, "b")
    for g, dx in ((a, 0.0), (b, 3.0)):
        xf = QMatrix4x4()
        xf.translate(dx, 0, 0)
        g.xform = xf
        scene.groups.append(g)
    scene.version += 1
    epoch0 = vp._placements_epoch()
    b.material = dict(RED)
    scene.version += 1
    assert vp._placements_epoch() != epoch0          # the paint is part of the key
    from core.materials import material_sig
    assert material_sig(RED) != material_sig(None)
    pooled = {}
    for g in (a, b):
        from core.group import effective_material
        paint = effective_material(g)
        pooled.setdefault((id(g.mesh), material_sig(paint)), []).append(g)
    assert len(pooled) == 2                          # two pools, one prototype
    assert vp._instanced_eligible(a) and vp._instanced_eligible(b)


def test_exploding_a_group_of_groups_lifts_them_whole():
    """@pacaeiro, issue #72: «Make cube and group. Copy the cube (group) to
    the side. Group those 2 cubes. Explode the bigger group. The inside
    groups explode as well.» They must come out as the two groups, where
    they were, and an unpainted one wears the paint the container gave it."""
    from core.edits import build_add_edges
    from core.history import (InsertGroupCommand, MakeGroupCommand,
                              MakeNestedGroupCommand, MoveGroupCommand)
    from core.group import world_mesh
    scene = Scene()
    hist = History(scene)
    sq = [V(0, 0), V(1, 0), V(1, 1), V(0, 1)]
    hist.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)], detect_faces=True))
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    a = scene.groups[0]
    b = copy_group(a, V(3, 0))
    hist.execute(InsertGroupCommand(b))
    b.material = {"color": [0.0, 0.0, 1.0]}          # painted itself
    hist.execute(MakeNestedGroupCommand([], [], [a, b]))
    big = scene.groups[0]
    hist.execute(MoveGroupCommand(big, V(0, 5)))
    hist.execute(SetGroupMaterialCommand(big, dict(RED)))

    def xs_ys(g):
        vs = world_mesh(g).vertices
        return (sorted({round(v.position.x(), 6) for v in vs}),
                sorted({round(v.position.y(), 6) for v in vs}))

    hist.execute(ExplodeGroupCommand(big))
    assert scene.groups == [a, b]
    assert not scene.mesh.faces                      # nothing went loose
    assert xs_ys(a) == ([0.0, 1.0], [5.0, 6.0])      # where the move left it
    assert xs_ys(b) == ([3.0, 4.0], [5.0, 6.0])
    assert a.material["color"] == [1.0, 0.0, 0.0]    # took the container's
    assert b.material["color"] == [0.0, 0.0, 1.0]    # kept its own
    hist.undo()
    assert scene.groups == [big] and big.children == [a, b]
    assert a.material is None and xs_ys(a)[1] == [0.0, 1.0]


def test_explode_keeps_the_container_paint_on_the_back_too():
    """@pacaeiro, #47 point 3: inside the painted group both sides wore it;
    after Explode the backs fell back to the default."""
    scene = Scene()
    hist = History(scene)
    g, _blue = _two_face_group(scene)
    g.material = dict(RED)
    hist.execute(ExplodeGroupCommand(g))
    red = [f for f in scene.mesh.faces
           if f.attrs.get("color") == [1.0, 0.0, 0.0]]
    assert red and all(f.attrs.get("back") for f in red)
