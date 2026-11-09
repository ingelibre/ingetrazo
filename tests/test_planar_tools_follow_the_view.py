# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A planar shape started on a free point follows the camera-selected plane
(Rafael's review of 2026-09-10, B1/B2).

In empty space, the cursor ray and camera select one of the global principal
planes, with XY retaining its floor/ceiling preference. The shape and its
colored preview use that same plane; geometry under the cursor and explicit
plane locks retain priority.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from tools.base import ToolContext


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    return vp


def _eye_level(vp, yaw_deg=20.0):
    """Rafael's camera: 1.6 m up, looking level (horizon mid-screen)."""
    cam = vp.camera
    cam.target = QVector3D(0, 0, 1.6)
    cam.distance = 12.0
    cam.pitch = 0.0
    cam.yaw = math.radians(yaw_deg)


def _ctx(vp, world, px):
    return ToolContext(viewport=vp, world=world, screen=QPointF(*px),
                       modifiers=Qt.NoModifier, snap=None)


def _hover_at(vp, tool, px):
    world = vp._world_from_pixel(int(px[0]), int(px[1]))
    assert world is not None
    tool.on_hover(_ctx(vp, world, px))
    return world


def _start_at_origin(vp, tool):
    vp.active_tool = tool
    o_px = vp._world_to_pixel(QVector3D(0, 0, 0))
    world = vp._world_from_pixel(int(o_px[0]), int(o_px[1]))
    tool.on_click(_ctx(vp, world, o_px))
    return o_px


def _span(points):
    lo = QVector3D(*[min(getattr(p, i)() for p in points) for i in ("x", "y", "z")])
    hi = QVector3D(*[max(getattr(p, i)() for p in points) for i in ("x", "y", "z")])
    return hi - lo


def test_rectangle_at_eye_level_stands_up_with_two_real_sides(viewport):
    from tools.rectangle import RectangleTool
    _eye_level(viewport)
    tool = RectangleTool()
    o_px = _start_at_origin(viewport, tool)
    assert tool.work_plane is None                      # free point: no capture
    horizon_y = viewport._world_to_pixel(QVector3D(0, 0, 1.6))[1]
    _hover_at(viewport, tool, (o_px[0] - 250, horizon_y - 34))   # Rafael's cursor
    text, _mid = tool.value_label()
    w, h = (float(t) for t in text.replace(" m", "").split(" × ")[:2])
    assert w > 1.0 and h > 1.0, text                    # not «5.74 × 0.00»
    corners = tool._corners(tool.start_point, tool.hover_point)
    span = _span(corners)
    assert span.z() > 1.0                               # it stands up
    assert min(span.x(), span.y()) < 1e-6               # in ONE vertical plane


def test_orbiting_after_the_first_click_re_decides_the_plane(viewport):
    from tools.rectangle import RectangleTool
    _eye_level(viewport)
    tool = RectangleTool()
    o_px = _start_at_origin(viewport, tool)
    horizon_y = viewport._world_to_pixel(QVector3D(0, 0, 1.6))[1]
    _hover_at(viewport, tool, (o_px[0] - 250, horizon_y + 40))
    assert _span(tool._corners(tool.start_point, tool.hover_point)).z() > 0.5
    viewport.camera.set_view("iso")                     # orbit up
    o_px = viewport._world_to_pixel(QVector3D(0, 0, 0))
    _hover_at(viewport, tool, (o_px[0] - 120, o_px[1] - 60))
    corners = tool._corners(tool.start_point, tool.hover_point)
    assert _span(corners).z() < 1e-6                    # flat on the ground again
    assert _span(corners).x() > 0.5 and _span(corners).y() > 0.1


def test_circle_at_eye_level_stands_up(viewport):
    from tools.circle import CircleTool
    _eye_level(viewport, yaw_deg=80.0)
    tool = CircleTool()
    o_px = _start_at_origin(viewport, tool)
    horizon_y = viewport._world_to_pixel(QVector3D(0, 0, 1.6))[1]
    _hover_at(viewport, tool, (o_px[0] - 150, horizon_y - 20))
    pts = tool._points(tool.start_point, tool.hover_point)
    span = _span(pts)
    assert span.z() > 1.0 and min(span.x(), span.y()) < 1e-6


def test_a_captured_slab_keeps_a_planar_tool_flat_at_the_horizon(viewport):
    """The near-horizon escape hatch (a horizontal captured plane yields to a
    vertical one so a LINE can rise) must not touch a rectangle's captured
    plane: its corners live in that plane by definition."""
    from tools.rectangle import RectangleTool
    _eye_level(viewport)
    tool = RectangleTool()
    tool.start_point = QVector3D(0, 0, 0)
    tool.work_plane = (QVector3D(0, 0, 0), QVector3D(0, 0, 1))   # clicked a slab
    viewport.active_tool = tool
    _pt, n = viewport._current_work_plane()
    assert abs(n.z()) > 0.99

    class _Line:                                        # a line-like tool
        start_point = QVector3D(0, 0, 0)
        work_plane = (QVector3D(0, 0, 0), QVector3D(0, 0, 1))
    viewport.active_tool = _Line()
    _pt, n = viewport._current_work_plane()
    assert abs(n.z()) < 1e-6                            # still rises for a line


# ---------------------------------------------------------------------------
# The classic tools show the plane on the cursor BEFORE the first click: a
# ring (circle, polygon) or a little square (rectangle) lying on the plane the shape would
# take, drawn in the axis colour while an arrow key locks it. Without it our
# lock was invisible — Rafael: «sí que me cambia de plano, pero no se ve».

def _plane_of(segments):
    return _span([a for a, _b in segments])


@pytest.mark.parametrize(
    ("ray_origin", "ray_direction", "normal_axis"),
    [
        (QVector3D(0, 0, 10), QVector3D(0, 0, -1), "z"),
        (QVector3D(10, 10, 5), QVector3D(-0.8, -0.6, 0), "x"),
        (QVector3D(10, 10, 5), QVector3D(-0.6, -0.8, 0), "y"),
    ],
)
def test_empty_space_selects_camera_and_cursor_aligned_global_plane(
        viewport, monkeypatch, ray_origin, ray_direction, normal_axis):
    from core import axes
    from tools.circle import CircleTool

    viewport.active_tool = CircleTool()
    direction = QVector3D(ray_direction).normalized()
    monkeypatch.setattr(viewport.camera, "eye",
                        lambda: QVector3D(ray_origin))
    monkeypatch.setattr(viewport.camera, "target", ray_origin + direction * 10)
    monkeypatch.setattr(viewport.camera, "perspective", True)
    monkeypatch.setattr(
        viewport, "_pixel_to_ray",
        lambda *_args: (QVector3D(ray_origin), QVector3D(direction)))
    monkeypatch.setattr(viewport, "pick_face_placement",
                        lambda *_args: (None, None))
    monkeypatch.setattr(viewport, "image_plane_at", lambda *_args: None)

    point, normal = viewport._current_work_plane((500, 300))

    assert (point - axes.origin()).length() < 1e-6
    assert abs(QVector3D.dotProduct(normal, axes.axis(normal_axis))) > 0.999


@pytest.mark.parametrize(
    ("ray_origin", "ray_direction", "normal_axis", "tool_name"),
    [
        (QVector3D(0, 0, 10), QVector3D(0, 0, -1), "z", "circle"),
        (QVector3D(10, 10, 5), QVector3D(-0.8, -0.6, 0), "x", "circle"),
        (QVector3D(10, 10, 5), QVector3D(-0.6, -0.8, 0), "y", "rectangle"),
    ],
)
def test_planar_preview_uses_selected_plane_color(
        viewport, monkeypatch, ray_origin, ray_direction, normal_axis,
        tool_name):
    from core.snap import AXIS_COLORS
    from tools.circle import CircleTool
    from tools.rectangle import RectangleTool

    tool = {"circle": CircleTool, "rectangle": RectangleTool}[tool_name]()
    viewport.active_tool = tool
    direction = QVector3D(ray_direction).normalized()
    monkeypatch.setattr(viewport.camera, "eye",
                        lambda: QVector3D(ray_origin))
    monkeypatch.setattr(viewport.camera, "target", ray_origin + direction * 10)
    monkeypatch.setattr(viewport.camera, "perspective", True)
    monkeypatch.setattr(
        viewport, "_pixel_to_ray",
        lambda *_args: (QVector3D(ray_origin), QVector3D(direction)))
    monkeypatch.setattr(viewport, "pick_face_placement",
                        lambda *_args: (None, None))
    monkeypatch.setattr(viewport, "image_plane_at", lambda *_args: None)
    px = (500, 300)
    world = viewport._world_from_pixel(*px)
    assert world is not None

    tool.on_hover(_ctx(viewport, world, px))

    assert tool.wireframe_color[:3] == tuple(AXIS_COLORS[normal_axis][:3])


def test_empty_space_camera_plane_can_be_hit_at_a_near_grazing_angle(
        viewport, monkeypatch):
    from core import axes
    from tools.circle import CircleTool

    viewport.active_tool = CircleTool()
    ray_origin = QVector3D(0, -1, 1000)
    direction = QVector3D(0.01, 0.04, -0.999).normalized()
    monkeypatch.setattr(viewport.camera, "eye",
                        lambda: QVector3D(ray_origin))
    monkeypatch.setattr(viewport.camera, "target", ray_origin + direction * 10)
    monkeypatch.setattr(viewport.camera, "perspective", True)
    monkeypatch.setattr(
        viewport, "_pixel_to_ray",
        lambda *_args: (QVector3D(ray_origin), QVector3D(direction)))
    monkeypatch.setattr(viewport, "pick_face_placement",
                        lambda *_args: (None, None))
    monkeypatch.setattr(viewport, "image_plane_at", lambda *_args: None)

    hit = viewport._world_from_pixel(500, 300)

    assert hit is not None
    assert abs(QVector3D.dotProduct(
        viewport._last_work_plane[1], axes.axis("y"))) > 0.999
    assert abs(hit.y()) < 1e-5


@pytest.mark.parametrize("yaw", [0.0, math.pi])
@pytest.mark.parametrize("tool_name", ["circle", "rectangle"])
def test_planar_preview_stays_bounded_when_cursor_moves_along_x_view(
        viewport, monkeypatch, yaw, tool_name):
    from tools.circle import CircleTool
    from tools.rectangle import RectangleTool

    tool = {"circle": CircleTool, "rectangle": RectangleTool}[tool_name]()
    viewport.camera.target = QVector3D(0, 0, 0)
    viewport.camera.distance = 12.0
    viewport.camera.pitch = math.radians(20.0)
    viewport.camera.yaw = yaw
    viewport.camera.perspective = True
    viewport.active_tool = tool
    monkeypatch.setattr(viewport, "pick_face_placement",
                        lambda *_args: (None, None))
    monkeypatch.setattr(viewport, "image_plane_at", lambda *_args: None)

    for px in ((500, 300), (500, 200), (500, 150), (500, 100)):
        world = viewport._world_from_pixel(*px)
        assert world is not None
        tool.on_hover(_ctx(viewport, world, px))
        projected = [
            viewport._world_to_pixel(point)
            for segment in tool.rubber_band_lines() for point in segment
        ]
        assert projected and all(point is not None for point in projected)
        width = max(point[0] for point in projected) - min(
            point[0] for point in projected)
        height = max(point[1] for point in projected) - min(
            point[1] for point in projected)
        limit = (2 * tool.PREVIEW_PX + 8 if tool_name == "circle"
                 else tool.PREVIEW_PX + 8)
        assert max(width, height) <= limit


def test_circle_shows_a_ring_on_the_cursor_in_the_locked_plane_colour(viewport):
    from tools.base import PLANE_LOCK_KEYS
    from tools.circle import CircleTool
    from core.snap import AXIS_COLORS
    viewport.camera.set_view("iso")
    tool = CircleTool()
    viewport.active_tool = tool
    key = next(k for k, a in PLANE_LOCK_KEYS.items() if a == "y")   # Left = green
    tool.on_key(viewport, key, None)
    px = (500, 300)
    world = viewport._world_from_pixel(*px)
    tool.on_hover(_ctx(viewport, world, px))
    segs = tool.rubber_band_lines()
    assert len(segs) == tool.sides                     # a ring, before any click
    span = _plane_of(segs)
    assert span.y() < 1e-6 and span.x() > 0 and span.z() > 0   # normal to green
    assert tool.wireframe_color[:3] == tuple(AXIS_COLORS["y"][:3])
    r_px = viewport._world_to_pixel(segs[0][0])
    c_px = viewport._world_to_pixel(world)
    assert abs(math.hypot(r_px[0] - c_px[0], r_px[1] - c_px[1]) - tool.PREVIEW_PX) < 4
    tool.on_key(viewport, key, None)                   # the same key frees it
    world = viewport._world_from_pixel(*px)
    assert world is not None
    tool.on_hover(_ctx(viewport, world, px))
    assert tool.wireframe_color[:3] == tuple(AXIS_COLORS["z"][:3])
    assert _plane_of(tool.rubber_band_lines()).z() < 1e-6        # flat on the ground


def test_rectangle_shows_a_square_on_the_cursor_and_keeps_the_colour_while_drawing(viewport):
    from tools.base import PLANE_LOCK_KEYS
    from tools.rectangle import RectangleTool
    viewport.camera.set_view("iso")
    tool = RectangleTool()
    viewport.active_tool = tool
    px = (500, 300)
    world = viewport._world_from_pixel(*px)
    tool.on_hover(_ctx(viewport, world, px))
    segs = tool.rubber_band_lines()
    assert len(segs) == 4 and _plane_of(segs).z() < 1e-6          # flat square glyph
    from core.snap import AXIS_COLORS
    assert tool.wireframe_color[:3] == tuple(AXIS_COLORS["z"][:3])
    key = next(k for k, a in PLANE_LOCK_KEYS.items() if a == "x")   # Right = red
    tool.on_key(viewport, key, None)
    tool.on_hover(_ctx(viewport, world, px))
    assert _plane_of(tool.rubber_band_lines()).x() < 1e-6          # normal to red
    red = tool.wireframe_color
    tool.on_click(_ctx(viewport, world, px))
    tool.on_hover(_ctx(viewport, world + QVector3D(0, 1, 1), px))
    assert tool.wireframe_color == red                 # still red while drawing
    assert _plane_of(tool.rubber_band_lines()).x() < 1e-6
    tool._reset()
    assert tool.wireframe_color is None and tool.plane_lock is None


def test_a_zero_sided_rectangle_is_refused_instead_of_raising(viewport):
    """Marco's log (2026-09-14): «degenerate edge: endpoints weld to one
    vertex» from the history — the second corner sat on the first's row.
    The classic tool draws nothing; we say why."""
    from tools.rectangle import RectangleTool
    viewport.camera.set_view("iso")
    said = []
    viewport.flash_status = lambda text, *a, **k: said.append(text)
    tool = RectangleTool()
    viewport.active_tool = tool
    before = len(viewport.scene.mesh.edges)
    tool.on_click(_ctx(viewport, QVector3D(0, 0, 0), (0, 0)))
    tool.on_click(_ctx(viewport, QVector3D(3, 0, 0), (0, 0)))    # same row: no height
    assert len(viewport.scene.mesh.edges) == before
    assert said and "two sides" in said[-1]
    viewport.flash_status = lambda *a, **k: None


def test_a_first_click_on_a_components_face_captures_its_world_plane(viewport):
    """Marco (2026-09-14): a rectangle on the pergola post's face «se
    atasca». The click captured the face's plane in the component's OWN
    coordinates; the second corner then fell on a plane nowhere near the
    post. The captured plane must be the world one."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    from tools.rectangle import RectangleTool
    viewport.camera.set_view("iso")
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(0, 2, 0), QVector3D(0, 2, 3), QVector3D(0, 0, 3)])  # a post side, x = 0 locally
    g = Group(mesh, "poste")
    xf = QMatrix4x4()
    xf.translate(8, 5, 0)
    g.xform = xf
    viewport.scene.groups.append(g)
    viewport.scene.version += 1
    viewport.camera.target = QVector3D(8, 6, 1.5)
    viewport.camera.distance = 10
    viewport.camera.yaw = math.radians(180)          # looking along -X at the face
    viewport.camera.pitch = math.radians(10)
    tool = RectangleTool()
    viewport.set_active_tool(tool)
    px = viewport._world_to_pixel(QVector3D(8, 6, 1.5))

    class _Ev:
        def position(self):
            return QPointF(*px)

        def modifiers(self):
            return Qt.NoModifier

        def button(self):
            return Qt.LeftButton
    viewport._dispatch_tool_click(_Ev())
    assert tool.start_point is not None
    assert tool.work_plane is not None
    pt, n = tool.work_plane
    assert abs(abs(n.x()) - 1.0) < 1e-6                         # the post's plane
    assert abs(pt.x() - 8.0) < 1e-6                             # …in WORLD space (x = 8, not 0)
    viewport.scene.groups.remove(g)
    viewport.scene.version += 1


def test_a_nested_components_face_plane_comes_through_its_placement(viewport):
    """The pergola's post is a component inside the plaza's container:
    pick_face_any hands back the OWNER (the container, identity matrix),
    so the post's plane read as its prototype's — normal flipped, point in
    local coordinates — and the rectangle drew off the face (Marco's
    video, 2026-09-14). pick_face_placement returns the placement whose
    composed matrix puts the face in the world."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    from core.snap import face_plane_world
    from tools.rectangle import RectangleTool
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(0, 2, 0), QVector3D(0, 2, 3), QVector3D(0, 0, 3)])  # local normal ±X
    child = Group(mesh, "poste")
    m = QMatrix4x4()
    m.translate(20, 10, 0)
    m.rotate(90, 0, 0, 1)                            # local +X → world +Y
    child.xform = m
    container = Group(Mesh(), "plaza")
    container.xform = QMatrix4x4()
    container.children = [child]
    viewport.scene.groups.append(container)
    viewport.scene.version += 1
    try:
        viewport.camera.target = QVector3D(20, 11, 1.5)
        viewport.camera.distance = 10
        viewport.camera.yaw = math.radians(90)          # looking along -Y at the face
        viewport.camera.pitch = math.radians(10)
        tool = RectangleTool()
        viewport.set_active_tool(tool)
        px = viewport._world_to_pixel(QVector3D(20, 11, 1.5))
        face, owner = viewport.pick_face_any(*px)
        assert face is not None and owner is container
        face2, place = viewport.pick_face_placement(*px)
        assert face2 is face and place is not container
        _pt, n = face_plane_world(face2, place.xform)
        assert abs(abs(n.y()) - 1.0) < 1e-6 and abs(n.x()) < 1e-6      # rotated into the world

        class _Ev:
            def position(self):
                return QPointF(*px)

            def modifiers(self):
                return Qt.NoModifier

            def button(self):
                return Qt.LeftButton
        viewport._dispatch_tool_click(_Ev())
        pt, n = tool.work_plane
        assert abs(abs(n.y()) - 1.0) < 1e-6
        assert abs(pt.y() - 10.0) < 1e-6                                 # on the post, in the world
    finally:
        viewport.scene.groups.remove(container)
        viewport.scene.version += 1
        viewport.set_active_tool(None)


def test_opening_a_container_lets_the_pick_resolve_to_its_children(viewport):
    """Marco (2026-09-14): double-clicking into the plaza's container, then
    on the arch inside, kept opening nothing — the pick still answered
    "the plaza" (a stale index: the owner a hit resolves to depends on the
    open context)."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0), QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    child = Group(mesh, "arco")
    m = QMatrix4x4()
    m.translate(30, 30, 0)
    child.xform = m
    container = Group(Mesh(), "plaza")
    container.xform = QMatrix4x4()
    container.children = [child]
    scene = viewport.scene
    scene.groups.append(container)
    scene.version += 1
    try:
        viewport.camera.set_view("top")
        viewport.camera.target = QVector3D(31, 31, 0)
        viewport.camera.distance = 10
        px = viewport._world_to_pixel(QVector3D(31, 31, 0))
        assert viewport.pick_group(*px) is container
        scene.begin_group_edit(container)                 # double-click: open it
        try:
            g = viewport.pick_group(*px)
            assert g is not None and g.name == "arco", getattr(g, "name", g)
        finally:
            scene.end_group_edit()
    finally:
        scene.groups.remove(container)
        scene.version += 1


def test_escape_steps_out_of_the_open_group_from_the_window_action_too(viewport):
    """Marco (2026-09-14): «he hecho Esc varias veces y no salgo». The
    window's «Cancel current tool» action owns the Esc shortcut and fires
    before the viewport's key event; its own cascade never stepped out of
    a group. One cascade now: Viewport.escape()."""
    from core.group import Group
    from core.mesh import Mesh
    from tools.select import SelectTool
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0), QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    child = Group(mesh, "letras")
    container = Group(Mesh(), "arco")
    container.children = [child]
    scene = viewport.scene
    scene.groups.append(container)
    scene.version += 1
    viewport.set_active_tool(SelectTool())
    try:
        scene.begin_group_edit(container)
        scene.begin_group_edit(child)
        assert scene.edit_group is child
        viewport.escape()                                   # what the window action calls
        assert scene.edit_group is container                # one level out…
        viewport.escape()
        assert scene.edit_group is None                     # …and out
    finally:
        while scene.edit_group is not None:
            scene.end_one_group_edit()
        if container in scene.groups:
            scene.groups.remove(container)
        scene.version += 1
        viewport.set_active_tool(None)


def test_paste_places_on_the_plane_through_the_clipboard_reference(viewport):
    """Marco (2026-09-14), inside a bench: a cut slat could only be dropped
    on the bench's faces or fell to the ground elsewhere. The paste's
    cursor point lives on the plane through the clipboard's reference."""
    from tools.paste import PasteTool
    viewport.camera.set_view("iso")
    viewport.camera.target = QVector3D(0, 0, 1)
    viewport.camera.distance = 12
    tool = PasteTool()
    viewport.set_active_tool(tool)
    tool._clip = {"ref": QVector3D(0, 0, 1.0), "faces": [], "edges": [], "groups": []}
    try:
        assert tool.start_point == QVector3D(0, 0, 1.0)
        px = viewport._world_to_pixel(QVector3D(1.0, 0.0, 1.0))
        world = viewport._world_from_pixel(int(px[0]), int(px[1]))
        assert world is not None
        assert abs(world.z() - 1.0) < 1e-6                  # level with the slat, not z = 0
        assert abs(world.x() - 1.0) < 0.05
    finally:
        viewport.set_active_tool(None)


def test_a_group_inserted_while_editing_a_container_becomes_its_child(viewport):
    """Marco (2026-09-14): a roof pasted while editing the pergola landed at
    the top level. Inside an open container, InsertGroupCommand (paste,
    place, import) appends to the container's children; undo removes it
    from there."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.history import InsertGroupCommand
    from core.mesh import Mesh
    scene = viewport.scene
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    child = Group(mesh, "techo")
    child.xform = QMatrix4x4()
    container = Group(Mesh(), "pergola")
    container.xform = QMatrix4x4()
    container.children = [child]
    scene.groups.append(container)
    scene.version += 1
    tops = len(scene.groups)
    try:
        scene.begin_group_edit(container)
        copy = Group(mesh, "techo")
        m = QMatrix4x4()
        m.translate(0, 0, 3)
        copy.xform = m
        viewport.history.execute(InsertGroupCommand(copy))
        assert copy in container.children and copy not in scene.groups
        assert len(scene.groups) == tops
        viewport.history.undo()
        assert copy not in container.children
        viewport.history.redo()
        assert copy in container.children
    finally:
        while scene.edit_group is not None:
            scene.end_one_group_edit()
        if container in scene.groups:
            scene.groups.remove(container)
        scene.version += 1
