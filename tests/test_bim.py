# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""BIM tagging layer: tag → live quantities → CSV takeoff → persistence."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.bim import (
    class_quantities,
    collect_objects,
    face_set_volume,
    next_object_id,
    quantities_csv,
    tag_faces,
    tag_group,
)
from core.edits import build_add_edges
from core.group import Group
from core.mesh import DeferredMesh, Mesh
from core.history import AddFaceCommand, History, MakeGroupCommand
from core.scene import Scene
from formats import igz
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


def _wall(scene, vp, x0=0.0, length=4.0, thick=0.25, height=2.6):
    pts = [V(x0, 0), V(x0 + length, 0), V(x0 + length, thick), V(x0, thick)]
    vp.history.execute(build_add_edges(
        scene, [(pts[i], pts[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(pts))]))
    pp = PushPullTool()
    pp.hovered_face = scene.mesh.faces[-1]
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                            modifiers=Qt.NoModifier, snap=None))
    pp.extrusion = height
    pp._commit(vp)


def test_tag_solid_reports_area_and_exact_volume():
    scene = Scene()
    vp = _Vp(scene)
    _wall(scene, vp)                                # 4.0 × 0.25 × 2.6 wall
    tag_faces(scene.mesh.faces, "IfcWall", "Muro eje A", next_object_id(scene))
    objs = collect_objects(scene)
    assert len(objs) == 1
    obj = objs[0]
    assert obj["class"] == "IfcWall" and obj["name"] == "Muro eje A"
    assert abs(obj["volume"] - 4.0 * 0.25 * 2.6) < 1e-6   # exact takeoff
    assert obj["area"] > 2 * 4.0 * 2.6                     # shell area


def test_open_face_set_has_area_but_no_volume():
    scene = Scene()
    f = scene.mesh.add_face([V(0, 0), V(3, 0), V(3, 2), V(0, 2)])
    tag_faces([f], "IfcSlab", "Losa", 1)
    obj = collect_objects(scene)[0]
    assert abs(obj["area"] - 6.0) < 1e-9
    assert obj["volume"] is None                    # honest: not watertight
    assert face_set_volume([f]) is None


def test_two_objects_and_csv_takeoff():
    scene = Scene()
    vp = _Vp(scene)
    _wall(scene, vp, x0=0.0)
    tag_faces(scene.mesh.faces, "IfcWall", "Muro 1", next_object_id(scene))
    slab = scene.mesh.add_face([V(10, 0), V(12, 0), V(12, 2), V(10, 2)])
    tag_faces([slab], "IfcSlab", "Losa 1", next_object_id(scene))
    objs = collect_objects(scene)
    assert {o["class"] for o in objs} == {"IfcWall", "IfcSlab"}
    csv = quantities_csv(scene)
    lines = csv.strip().splitlines()
    assert lines[0] == "class,name,metrado,unit,area_m2,volume_m3"
    assert len(lines) == 3
    # wall metrado = net side area (4.0 × 2.6), volume = 2.6 m³
    wall = next(ln for ln in lines if "IfcWall" in ln)
    assert ",10.4000,m2," in wall and wall.endswith(",2.6000")
    slab = next(ln for ln in lines if "IfcSlab" in ln)
    assert ",4.0000,m2," in slab                    # 2×2 sheet, net area


def test_group_tag_and_igz_round_trip(tmp_path):
    scene = Scene()
    vp = _Vp(scene)
    _wall(scene, vp)
    vp.history.execute(MakeGroupCommand(list(scene.mesh.faces),
                                        list(scene.mesh.edges)))
    tag_group(scene.groups[0], "IfcColumn", "C-1")
    # loose tagged slab too
    slab = scene.mesh.add_face([V(10, 0), V(12, 0), V(12, 2), V(10, 2)])
    tag_faces([slab], "IfcSlab", "Losa", next_object_id(scene))

    p = tmp_path / "bim.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    objs = collect_objects(scene2)
    classes = {o["class"]: o for o in objs}
    assert classes["IfcColumn"]["name"] == "C-1"
    assert classes["IfcColumn"]["volume"] is not None      # group still solid
    assert classes["IfcSlab"]["volume"] is None


def test_wall_class_quantities_are_the_budget_measures():
    scene = Scene()
    vp = _Vp(scene)
    _wall(scene, vp)                                # 4.0 × 0.25 × 2.6
    qset, entries, (metrado, unit) = class_quantities(
        "IfcWall", scene.mesh.faces)
    assert qset == "Qto_WallBaseQuantities"
    q = {(kind, name): val for kind, name, val in entries}
    assert abs(q[("length", "Height")] - 2.6) < 1e-6
    assert abs(q[("length", "Length")] - 4.0) < 1e-6
    assert abs(q[("length", "Width")] - 0.25) < 1e-6
    assert abs(q[("area", "NetSideArea")] - 10.4) < 1e-6   # 4.0 × 2.6
    assert abs(q[("volume", "GrossVolume")] - 2.6) < 1e-6
    assert unit == "m2" and abs(metrado - 10.4) < 1e-6     # NOT the 24 m²
                                                           # shell area


def test_column_and_pile_quantities():
    scene = Scene()
    vp = _Vp(scene)
    _wall(scene, vp, length=0.3, thick=0.3, height=3.0)    # 0.3×0.3×3.0
    qset, entries, (metrado, unit) = class_quantities(
        "IfcColumn", scene.mesh.faces)
    q = {name: val for _, name, val in entries}
    assert abs(q["Length"] - 3.0) < 1e-6
    assert abs(q["CrossSectionArea"] - 0.09) < 1e-6
    assert unit == "m3" and abs(metrado - 0.27) < 1e-6
    # same solid tagged as pile bills by the metre
    _, _, (metrado, unit) = class_quantities("IfcPile", scene.mesh.faces)
    assert unit == "m" and abs(metrado - 3.0) < 1e-6


def test_door_dimensions_in_rotated_wall_plane():
    import math
    scene = Scene()
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    f = scene.mesh.add_face([V(0, 0, 0), V(0.9 * c, 0.9 * s, 0),
                             V(0.9 * c, 0.9 * s, 2.1), V(0, 0, 2.1)])
    qset, entries, (metrado, unit) = class_quantities("IfcDoor", [f])
    q = {name: val for _, name, val in entries}
    assert abs(q["Width"] - 0.9) < 1e-6            # true leaf width, not bbox
    assert abs(q["Height"] - 2.1) < 1e-6
    assert unit == "und" and metrado == 1.0


def test_slab_net_area_discounts_holes():
    scene = Scene()
    f = scene.mesh.add_face(
        [V(0, 0), V(4, 0), V(4, 3), V(0, 3)],
        hole_loops=[[V(1, 1), V(2, 1), V(2, 2), V(1, 2)]])
    _, entries, (metrado, unit) = class_quantities("IfcSlab", [f])
    q = {name: val for _, name, val in entries}
    assert abs(q["GrossArea"] - 12.0) < 1e-6
    assert abs(q["NetArea"] - 11.0) < 1e-6
    assert abs(metrado - 11.0) < 1e-6 and unit == "m2"


def test_face_net_area_method_agrees_with_bim_helper():
    """#742: the face itself knows its net area, and ``area()`` stays
    gross — the engine (heal thresholds, dominant normal) reads it."""
    from core.bim import face_net_area
    scene = Scene()
    f = scene.mesh.add_face(
        [V(0, 0), V(4, 0), V(4, 3), V(0, 3)],
        hole_loops=[[V(1, 1), V(2, 1), V(2, 2), V(1, 2)]])
    assert abs(f.area() - 12.0) < 1e-6
    assert abs(f.net_area() - 11.0) < 1e-6
    assert abs(face_net_area(f) - f.net_area()) < 1e-9
    plain = scene.mesh.add_face([V(5, 0), V(6, 0), V(6, 1), V(5, 1)])
    assert plain.net_area() == plain.area()


def test_tag_survives_pushpull_churn():
    # The reason tags live in attrs: the engine's rebuilds replace face
    # objects, and the tag must ride the identity-inheritance machinery.
    scene = Scene()
    vp = _Vp(scene)
    f = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    tag_faces([f], "IfcSlab", "Piso", 1)
    pp = PushPullTool()
    pp.hovered_face = f
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                            modifiers=Qt.NoModifier, snap=None))
    pp.extrusion = 0.3
    pp._commit(vp)
    tagged = [g for g in scene.mesh.faces if g.attrs.get("ifc")]
    assert tagged                                   # the tag survived the push


def _quantity_cube():
    mesh = Mesh()
    for loop in (
        [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)],
        [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
        [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],
        [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
        [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)],
        [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)],
    ):
        mesh.add_face([V(*p) for p in loop])
    return mesh


def _assert_quantities(obj, area, volume):
    assert abs(obj["area"] - area) < 1e-6
    if volume is None:
        assert obj["volume"] is None
    else:
        assert abs(obj["volume"] - volume) < 1e-6


def test_collected_quantities_follow_vertex_edits_and_undo():
    scene = Scene(mesh=_quantity_cube())
    tag_faces(scene.mesh.faces, "IfcColumn", "Column", 1)
    before = scene.mesh.capture_state()
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    for vertex in list(scene.mesh.vertices):
        if vertex.position.x() == 1.0:
            scene.mesh.move_vertex(vertex, V(1, 0, 0))
    _assert_quantities(collect_objects(scene)[0], 10.0, 2.0)
    scene.mesh.restore_state(before)
    obj = collect_objects(scene)[0]
    _assert_quantities(obj, 6.0, 1.0)
    assert obj["faces"] == scene.mesh.faces


def test_collected_nested_quantities_follow_shared_geometry_and_placements():
    scene = Scene()
    prototype = _quantity_cube()
    left, right = Group(prototype), Group(prototype)
    left.xform = QMatrix4x4()
    right.xform = QMatrix4x4()
    right.xform.translate(4, 0, 0)
    branch = Group()
    branch.adopt([left, right])
    root = Group()
    root.adopt([branch])
    tag_group(root, "IfcMember", "Assembly")
    scene.groups.append(root)
    _assert_quantities(collect_objects(scene)[0], 12.0, 2.0)
    for vertex in list(prototype.vertices):
        if vertex.position.z() == 1.0:
            prototype.place_vertex(vertex, vertex.position + V(0, 0, 1))
    _assert_quantities(collect_objects(scene)[0], 20.0, 4.0)
    # In-place edits to matrices at either nesting depth must invalidate too.
    left.xform.scale(2, 1, 1)
    _assert_quantities(collect_objects(scene)[0], 26.0, 6.0)
    branch.xform.scale(1, 2, 1)
    _assert_quantities(collect_objects(scene)[0], 40.0, 12.0)
    root.xform.scale(2)
    _assert_quantities(collect_objects(scene)[0], 160.0, 96.0)
    assert root.children == [branch]
    assert branch.children == [left, right]
    assert left.mesh is prototype and right.mesh is prototype


def test_collected_quantities_follow_replacement_and_nested_membership():
    scene = Scene()
    child = Group(_quantity_cube())
    root = Group()
    root.adopt([child])
    tag_group(root, "IfcColumn", "Container")
    scene.groups.append(root)
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    original = child.mesh
    child.mesh = Mesh()
    child.mesh.add_face([V(0, 0), V(3, 0), V(3, 2), V(0, 2)])
    _assert_quantities(collect_objects(scene)[0], 6.0, None)
    child.mesh = original
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    root.children.clear()
    _assert_quantities(collect_objects(scene)[0], 0.0, None)
    root.children.append(child)
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)


def test_collected_quantities_follow_holes_and_direct_winding_changes():
    scene = Scene(mesh=_quantity_cube())
    tag_faces(scene.mesh.faces, "IfcColumn", "Column", 1)
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    top = scene.mesh.faces[1]
    hole = scene.mesh.add_hole(
        top, [V(.25, .25, 1), V(.25, .75, 1),
              V(.75, .75, 1), V(.75, .25, 1)])
    _assert_quantities(collect_objects(scene)[0], 6.0, None)
    scene.mesh.remove_hole(top, hole)
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    # Face-loop edits do not bump the mesh mutation serial.
    top.loop.reverse()
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0 / 3.0)
    top.loop.reverse()
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)


def test_collected_quantities_refresh_tags_face_membership_and_live_results():
    from core.bim import untag_faces, untag_group

    scene = Scene(mesh=_quantity_cube())
    tag_faces(scene.mesh.faces, "IfcColumn", "Original", 1)
    first = collect_objects(scene)[0]
    tag_faces(scene.mesh.faces, "IfcBeam", "Renamed", 1)
    obj = collect_objects(scene)[0]
    assert obj["class"] == "IfcBeam" and obj["name"] == "Renamed"
    _assert_quantities(obj, 6.0, 1.0)
    # Returned dictionaries/lists are live snapshots, not cached containers.
    first["area"] = -1
    first["faces"].clear()
    assert collect_objects(scene)[0]["faces"] == scene.mesh.faces
    face = scene.mesh.faces[-1]
    untag_faces([face])
    obj = collect_objects(scene)[0]
    _assert_quantities(obj, 5.0, None)
    assert face not in obj["faces"]
    tag_faces([face], "IfcSlab", "Separate", 2)
    objs = collect_objects(scene)
    assert [o["key"] for o in objs] == [("faces", 1), ("faces", 2)]
    _assert_quantities(objs[1], 1.0, None)
    scene.mesh.remove_face(face)
    assert len(collect_objects(scene)) == 1
    group = Group(_quantity_cube())
    tag_group(group, "IfcColumn", "Grouped")
    scene.groups.append(group)
    assert collect_objects(scene)[-1]["group"] is group
    tag_group(group, "IfcBeam", "Retagged")
    obj = collect_objects(scene)[-1]
    assert obj["class"] == "IfcBeam" and obj["name"] == "Retagged"
    assert obj["group"] is group
    untag_group(group)
    assert len(collect_objects(scene)) == 1
    untag_faces(scene.mesh.faces)
    assert collect_objects(scene) == []
    tag_group(group, "IfcColumn", "Restored")
    assert collect_objects(scene)[0]["group"] is group
    scene.groups.remove(group)
    assert collect_objects(scene) == []
    scene.groups.append(group)
    assert len(collect_objects(scene)) == 1
    scene.clear()
    assert collect_objects(scene) == []
    replacement = Group(_quantity_cube())
    tag_group(replacement, "IfcFooting", "New document")
    scene.groups.append(replacement)
    obj = collect_objects(scene)[0]
    assert obj["group"] is replacement and obj["name"] == "New document"
    _assert_quantities(obj, 6.0, 1.0)


def test_collected_quantities_ignore_layer_and_object_visibility():
    from core.layers import Layer, assign_layer

    scene = Scene(mesh=_quantity_cube())
    scene.layers.append(Layer("Structure"))
    tag_faces(scene.mesh.faces, "IfcColumn", "Loose", 1)
    for face in scene.mesh.faces:
        assign_layer(face, "Structure")
    child = Group(_quantity_cube())
    root = Group()
    root.adopt([child])
    assign_layer(root, "Structure")
    tag_group(root, "IfcBeam", "Nested")
    scene.groups.append(root)
    for visible in (True, False, True):
        scene.layers[-1].visible = visible
        root.hidden = not visible
        scene.version += 1
        objs = collect_objects(scene)
        assert len(objs) == 2
        for obj in objs:
            _assert_quantities(obj, 6.0, 1.0)
        assert objs[0]["faces"] == scene.mesh.faces
        assert objs[1]["group"] is root


def test_collected_quantities_handle_deferred_prototype_and_later_edits():
    mesh = Mesh()

    def build(target):
        target.restore_state(_quantity_cube().capture_state())

    assert DeferredMesh.defer(mesh, build, 6)
    group = Group(mesh)
    group.xform = QMatrix4x4()
    tag_group(group, "IfcColumn", "Deferred")
    scene = Scene(groups=[group])
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    _assert_quantities(collect_objects(scene)[0], 6.0, 1.0)
    for vertex in list(mesh.vertices):
        if vertex.position.x() == 1.0:
            mesh.move_vertex(vertex, V(1, 0, 0))
    _assert_quantities(collect_objects(scene)[0], 10.0, 2.0)
