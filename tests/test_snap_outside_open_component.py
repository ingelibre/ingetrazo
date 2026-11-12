# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Snapping to what is OUTSIDE the group / component being edited.

The rest of the model is drawn faded while a context is open, and it must
stay a reference: the root loose mesh was nowhere in the pick index (only
``scene.mesh`` was the loose part), so a corner drawn outside the component
— or the face of a neighbouring component — offered no «Endpoint» / «On
face» at all. It still cannot be PICKED: selecting the surroundings from
inside is the one thing the context forbids.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh

_app = QApplication.instance() or QApplication([])


def _box(mesh, s=1.0):
    pts = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
           V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    return [mesh.add_face([pts[i] for i in q]) for q in quads]


def _window():
    """Two component instances side by side, and loose geometry at the root
    to the other side: the scene of «estoy dentro del componente y no me
    snapea a lo de fuera»."""
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(900, 600)
    sc = vp.scene
    sc.clear()
    # Root loose geometry, outside both instances (a floor at 6..8, 0..2).
    sc.mesh.add_face([V(6, 0, 0), V(8, 0, 0), V(8, 2, 0), V(6, 2, 0)])
    proto = Mesh()
    _box(proto)
    a, b = Group(proto, name="A"), Group(proto, name="B")
    a.xform = QMatrix4x4()
    a.component = True
    b.xform = QMatrix4x4()
    b.xform.translate(3.0, 0.0, 0.0)
    b.component = True
    sc.groups += [a, b]
    sc.version += 1
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(35.0), math.radians(35.0)
    cam.target = V(3.0, 1.0, 0.0)
    cam.distance = 14.0
    win._activate_tool("line")
    return win, vp, a, b


def _snap(vp, world):
    px = vp._world_to_pixel(world)
    assert px is not None
    return vp._snap_at(px[0], px[1], Qt.NoModifier)


def test_a_corner_of_the_root_loose_mesh_snaps_from_inside_a_component():
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        corner = V(6.0, 0.0, 0.0)
        snap = _snap(vp, corner)
        assert snap.kind == "endpoint"
        assert (snap.point - corner).length() < 1e-6
        # …and its edge's middle too (the line, not only the corner).
        snap = _snap(vp, V(7.0, 0.0, 0.0))
        assert snap.kind == "midpoint"
        assert (snap.point - V(7.0, 0.0, 0.0)).length() < 1e-6
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_face_of_the_root_loose_mesh_is_on_face_from_inside():
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        floor = V(7.0, 1.0, 0.0)
        snap = _snap(vp, floor)
        assert snap.kind == "on_face"
        assert (snap.point - floor).length() < 1e-4
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_another_components_face_is_on_face_from_inside_a_component():
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        top = V(3.5, 0.5, 1.0)
        snap = _snap(vp, top)
        assert snap.kind == "on_face"
        assert (snap.point - top).length() < 1e-4
        # Its corner and its edge's middle still come first: named points.
        assert _snap(vp, V(3.0, 0.0, 1.0)).kind == "endpoint"
        assert _snap(vp, V(4.0, 0.5, 1.0)).kind == "midpoint"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_rest_of_the_model_is_a_reference_but_not_a_pick():
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        px = vp._world_to_pixel(V(7.0, 1.0, 0.0))
        # The snap engine reads it…
        face, place = vp.pick_face_inference(px[0], px[1])
        assert face is not None and place is not None
        assert place.xform is None and place.mesh is vp.scene.loose_mesh
        # …while a click still answers nothing outside the context.
        assert vp.pick_face_any(px[0], px[1]) == (None, None)
        assert vp.pick_face_placement(px[0], px[1]) == (None, None)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_hide_rest_of_model_takes_the_reference_away():
    win, vp, a, _b = _window()
    before = vp.edit_rest_mode
    try:
        vp.set_edit_rest_mode("hide")
        vp.begin_group_edit(a)
        snap = _snap(vp, V(6.0, 0.0, 0.0))
        assert snap.kind != "endpoint"
        snap = _snap(vp, V(3.5, 0.5, 1.0))
        assert snap.kind != "on_face"
    finally:
        vp.set_edit_rest_mode(before)
        win._saved_version = vp.scene.version
        win.close()


def test_a_root_loose_edge_is_a_linear_reference_but_not_a_pick():
    """The hover edge behind «parallel / perpendicular» reaches it; a click
    still cannot select it."""
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        edge = next(e for e in vp.scene.loose_mesh.edges
                    if {tuple(e.a.toTuple()), tuple(e.b.toTuple())}
                    == {(6.0, 0.0, 0.0), (8.0, 0.0, 0.0)})
        px = vp._world_to_pixel(V(7.0, 0.0, 0.0))
        assert vp.pick_edge_any(px[0], px[1]) is edge
        assert vp.pick_edge(px[0], px[1]) is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_box_does_not_take_the_rest_of_the_model():
    """The box reads the same edge index: the rest's loose edges are there
    as references and must be filtered out, not selected."""
    from tools.select import _box_loose_fast
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        rect = (0.0, 0.0, float(vp.width()), float(vp.height()))
        got = _box_loose_fast(vp, rect, False)
        assert got is not None
        outer = {id(e) for m in vp._outer_loose_meshes() for e in m.edges}
        assert outer
        assert not any(id(e) in outer for e in got[0])
        assert got[0], "the open component's own edges are still boxed"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_tip_says_the_point_is_outside_the_open_component():
    """The ScreenTip's suffix: the rest of the model is not «in component»,
    it is outside the component being edited."""
    from core.i18n import tr
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        assert _snap(vp, V(6.0, 0.0, 0.0)).context == "outside"
        assert _snap(vp, V(7.0, 0.0, 0.0)).context == "outside"
        face = _snap(vp, V(7.0, 1.0, 0.0))
        assert face.kind == "on_face" and face.context == "outside"
        other = _snap(vp, V(3.5, 0.5, 1.0))
        assert other.kind == "on_face" and other.context == "outside"
        # A point of another component: its edge's pseudo-edge is outside
        # too, not the old ambiguous «in component».
        corner = _snap(vp, V(3.0, 0.0, 1.0))
        assert corner.kind == "endpoint" and corner.context == "outside"
        mid = _snap(vp, V(4.0, 0.5, 1.0))
        assert mid.kind == "midpoint" and mid.context == "outside"
        assert vp._snap_context_suffix("outside") == \
            " " + tr("outside the component")
        # The open context's own geometry says nothing: you are already in it.
        px = vp._world_to_pixel(V(0.5, 0.5, 1.0))
        assert vp._face_context_under(px[0], px[1]) is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_outside_a_plain_group_the_tip_names_the_group():
    from core.i18n import tr
    win, vp, _a, _b = _window()
    try:
        gm = Mesh()
        _box(gm)
        g = Group(gm, name="plain")
        vp.scene.groups.append(g)
        vp.scene.version += 1
        vp.begin_group_edit(g)
        assert _snap(vp, V(6.0, 0.0, 0.0)).context == "outside"
        assert vp._snap_context_suffix("outside") == \
            " " + tr("outside the group")
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_at_the_root_a_components_point_still_says_in_component():
    from core.i18n import tr
    win, vp, _a, _b = _window()
    try:
        assert vp.scene.edit_group is None
        assert _snap(vp, V(3.0, 0.0, 1.0)).context == "component"
        assert vp._snap_context_suffix("component") == \
            " " + tr("in component")
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_shape_started_on_the_rest_keeps_the_rests_plane():
    """A rectangle begun over the outer model lies on ITS plane: the point
    under the cursor and the shape's own plane agree (#545 in a context)."""
    win, vp, a, _b = _window()
    try:
        sc = vp.scene
        sc.loose_mesh.add_face([V(6, 3, 2), V(8, 3, 2), V(8, 5, 2),
                                V(6, 5, 2)])
        sc.version += 1
        vp.begin_group_edit(a)
        from PySide6.QtCore import QPointF
        from tools.rectangle import RectangleTool

        tool = RectangleTool()
        vp.set_active_tool(tool)
        px = vp._world_to_pixel(V(7.0, 4.0, 2.0))

        class _Ev:
            def position(self):
                return QPointF(*px)

            def modifiers(self):
                return Qt.NoModifier

            def button(self):
                return Qt.LeftButton
        vp._dispatch_tool_click(_Ev())
        assert tool.start_point is not None
        assert abs(tool.start_point.z() - 2.0) < 1e-4
        assert tool.work_plane is None          # no face of the CONTEXT
        point, normal = tool.hover_plane
        assert abs(point.z() - 2.0) < 1e-4
        assert abs(abs(normal.z()) - 1.0) < 1e-6
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_root_loose_mesh_occludes_from_inside_a_component():
    """It is drawn, so it hides what is behind it: a corner must not snap
    through the floor of the outer model."""
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        sc = vp.scene
        # A slab between the eye (above) and the point, high over the model.
        sc.loose_mesh.add_face([V(-4, -4, 5), V(14, -4, 5), V(14, 14, 5),
                                V(-4, 14, 5)])
        vp.camera.set_view("top")
        vp.camera.target = V(0.0, 0.0, 0.0)
        vp.camera.distance = 40.0
        sc.version += 1
        assert vp._is_occluded(V(0.0, 0.0, 0.0))
    finally:
        win._saved_version = vp.scene.version
        win.close()
