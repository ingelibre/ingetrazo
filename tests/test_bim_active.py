# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""BIM active class (tag-as-you-draw): drawn faces assume the active tag,
push/pull extends a tagged base to the solid it raises, undo/redo exact."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.bim import collect_objects, tag_faces
from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def set_hover(self, *_):
        pass

    def set_suppressed_faces(self, *_):
        pass

    def flash_status(self, *a, **k):
        pass


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _draw_rect(scene, vp, pts):
    vp.history.execute(build_add_edges(
        scene, [(pts[i], pts[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(pts))]))


def _push(scene, vp, face, dist):
    pp = PushPullTool()
    pp.hovered_face = face
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                            modifiers=Qt.NoModifier, snap=None))
    pp.extrusion = dist
    pp._commit(vp)


WALL = {"class": "IfcWall", "name": "Muros N1"}


def test_drawn_face_assumes_active_tag_and_push_extends_it():
    scene = Scene()
    vp = _Vp(scene)
    scene.active_ifc = dict(WALL)
    _draw_rect(scene, vp, [V(0, 0), V(4, 0), V(4, 0.15), V(0, 0.15)])
    tag = scene.mesh.faces[0].attrs.get("ifc")
    assert tag and tag["class"] == "IfcWall" and tag["name"] == "Muros N1"
    assert isinstance(tag["id"], int)               # id allocated at commit
    _push(scene, vp, scene.mesh.faces[0], 2.6)      # raise the wall
    # The WHOLE solid carries the tag — one BIM object, exact volume.
    assert all(f.attrs.get("ifc") == tag for f in scene.mesh.faces)
    (obj,) = collect_objects(scene)
    assert obj["class"] == "IfcWall" and obj["name"] == "Muros N1"
    assert abs(obj["volume"] - 4.0 * 0.15 * 2.6) < 1e-6


def test_each_trace_is_its_own_object():
    # Two walls drawn under one activation → TWO objects (per-object
    # largest-face metrado stays honest; one shared id would under-report).
    scene = Scene()
    vp = _Vp(scene)
    scene.active_ifc = dict(WALL)
    _draw_rect(scene, vp, [V(0, 0), V(4, 0), V(4, 0.15), V(0, 0.15)])
    _push(scene, vp, scene.mesh.faces[0], 2.6)
    _draw_rect(scene, vp, [V(0, 5), V(4, 5), V(4, 5.15), V(0, 5.15)])
    base2 = next(f for f in scene.mesh.faces
                 if f.attrs["ifc"]["id"] != scene.mesh.faces[0].attrs["ifc"]["id"])
    _push(scene, vp, base2, 2.6)
    objs = collect_objects(scene)
    assert len(objs) == 2
    assert {o["name"] for o in objs} == {"Muros N1"}
    for o in objs:                                  # each wall metrado exact
        assert abs(o["volume"] - 4.0 * 0.15 * 2.6) < 1e-5


def test_undo_redo_keep_tags_exact():
    scene = Scene()
    vp = _Vp(scene)
    scene.active_ifc = dict(WALL)
    _draw_rect(scene, vp, [V(0, 0), V(2, 0), V(2, 0.15), V(0, 0.15)])
    vp.history.undo()
    assert not scene.mesh.faces                     # draw fully reverted
    vp.history.redo()
    tag = scene.mesh.faces[0].attrs.get("ifc")
    assert tag and tag["class"] == "IfcWall" and tag["name"] == "Muros N1"


def test_no_active_class_means_untagged():
    scene = Scene()
    vp = _Vp(scene)
    _draw_rect(scene, vp, [V(0, 0), V(2, 0), V(2, 1), V(0, 1)])
    assert not scene.mesh.faces[0].attrs.get("ifc")


def test_drawing_inside_untagged_face_tags_only_the_new_face():
    scene = Scene()
    vp = _Vp(scene)
    floor = scene.mesh.add_face([V(0, 0), V(6, 0), V(6, 6), V(0, 6)])
    scene.active_ifc = dict(WALL)
    vp.history.execute(build_add_edges(
        scene, [], detect_faces=False,
        extra=[AddFaceCommand([V(2, 2), V(3, 2), V(3, 3), V(2, 3)])]))
    tagged = [f for f in scene.mesh.faces if f.attrs.get("ifc")]
    assert len(tagged) == 1                         # the drawn rect only
    assert abs(tagged[0].area() - 1.0) < 1e-9
    assert not floor.attrs.get("ifc")               # mother stays untagged


def test_push_extends_base_tag_without_active_mode():
    # Mode-independent: thickening a tagged slab keeps the strips in-object.
    scene = Scene()
    vp = _Vp(scene)
    _draw_rect(scene, vp, [V(0, 0), V(3, 0), V(3, 2), V(0, 2)])
    _push(scene, vp, scene.mesh.faces[0], 0.2)      # untagged solid
    tag = {"id": 1, "class": "IfcSlab", "name": "Losa"}
    tag_faces(scene.mesh.faces, "IfcSlab", "Losa", 1)
    top = next(f for f in scene.mesh.faces
               if abs(f.centroid().z() - 0.2) < 1e-6)
    _push(scene, vp, top, 0.1)                      # thicken to 0.3
    assert all(f.attrs.get("ifc") == tag for f in scene.mesh.faces)
    (obj,) = collect_objects(scene)
    assert abs(obj["volume"] - 3 * 2 * 0.3) < 1e-6


def test_untagged_base_stays_untagged_after_push():
    scene = Scene()
    vp = _Vp(scene)
    _draw_rect(scene, vp, [V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    _push(scene, vp, scene.mesh.faces[0], 1.0)
    assert not any(f.attrs.get("ifc") for f in scene.mesh.faces)
