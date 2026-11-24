# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The section box (#729, #646): an axis-aligned box that keeps only what
lies inside it — six cuts at once, beside the active section plane.

The model (core.section.SectionBox, cut_planes, CutSet), the document (.igz,
undo, scenes), what the cut hides from snaps and picks, the Section Box
tool's drag, and — where a GL context renders — the pixels."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.history import (section_box_added,  # noqa: E402
                          section_box_changed, section_boxes_removed)
from core.section import (CutSet, MIN_BOX_SIZE, SectionBox,  # noqa: E402
                          SectionPlane, box_face_hit, box_face_quad,
                          cut_planes)
from core.snap import SnapResult, compute_snap  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from views.viewport import Viewport, _active_cut  # noqa: E402


def _put(scene, box):
    """Make ``box`` the model's only section box (``None``: no box)."""
    scene.section_boxes[:] = [box] if box is not None else []
    return box


def _box(scene):
    """The model's first section box, or ``None``."""
    return scene.section_boxes[0] if scene.section_boxes else None


def _cube(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in idx])


# ---- The box itself -----------------------------------------------------------

def test_the_box_orders_its_corners_and_keeps_its_inside():
    box = SectionBox(V(2, 3, 4), V(0, 0, 0))            # corners any way round
    assert (box.lo, box.hi) == (V(0, 0, 0), V(2, 3, 4))
    assert box.side(V(1, 1, 1)) < 0                      # inside: kept
    assert box.side(V(1, 1, 5)) == pytest.approx(1.0)    # above: hidden
    assert box.side(V(-0.5, 1, 1)) == pytest.approx(0.5)
    hidden = CutSet(box.faces()).hidden([[1, 1, 1], [3, 1, 1], [1, -.1, 1]])
    assert hidden.tolist() == [False, True, True]


def test_around_leaves_a_margin_so_nothing_starts_cut():
    box = SectionBox.around(V(0, 0, 0), V(10, 4, 3))
    assert box.lo == V(-0.5, -0.5, -0.5) and box.hi == V(10.5, 4.5, 3.5)
    tiny = SectionBox.around(V(1, 1, 1), V(1, 1, 1))     # a point: 1 cm
    assert tiny.hi.x() - tiny.lo.x() == pytest.approx(0.02)


def test_a_dragged_face_stops_short_of_the_opposite_one():
    box = SectionBox(V(0, 0, 0), V(2, 2, 2))
    assert box.with_face(1, 5).hi.x() == pytest.approx(5)     # +X out
    assert box.with_face(1, -3).hi.x() == pytest.approx(MIN_BOX_SIZE)
    assert box.with_face(4, 9).lo.z() == pytest.approx(2 - MIN_BOX_SIZE)
    assert box.hi.x() == 2                                    # a copy


def test_the_face_a_ray_meets_first():
    box = SectionBox(V(0, 0, 0), V(2, 3, 4))
    assert box_face_hit(box, V(-5, 1, 1), V(1, 0, 0)) == (0, 5.0)
    assert box_face_hit(box, V(9, 1, 1), V(-1, 0, 0))[0] == 1
    assert box_face_hit(box, V(1, 1, 1), V(0, 0, 1))[0] == 5   # from inside
    assert box_face_hit(box, V(-5, 9, 1), V(1, 0, 0)) is None  # misses
    quad = box_face_quad(box, 5)
    assert all(abs(q.z() - 4) < 1e-9 for q in quad)
    assert {(q.x(), q.y()) for q in quad} == {(0, 0), (2, 0), (2, 3), (0, 3)}


def test_what_cuts_is_the_active_plane_then_the_box_faces():
    vp = Viewport(None)
    sc = vp.scene
    assert cut_planes(sc) == [] and _active_cut(sc) is None
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1), active=True)
    sc.section_planes.append(sp)
    _put(sc, SectionBox(V(0, 0, 0), V(2, 2, 2)))
    planes = cut_planes(sc)
    assert planes[0] is sp and len(planes) == 7
    assert [f.index for f in planes[1:]] == list(range(6))
    _box(sc).active = False                       # switched off
    assert cut_planes(sc) == [sp]
    _box(sc).active = True
    sc.show_section_cuts = False                        # Section Cuts off
    assert cut_planes(sc) == [] and _active_cut(sc) is None


# ---- The document -------------------------------------------------------------

def test_the_box_is_saved_and_opened(tmp_path):
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    sc = Scene()
    _cube(sc.mesh, 0, 0, 0, 1, 1, 1)
    _put(sc, SectionBox(V(-1, -2, -3), V(1, 2, 3), active=False))
    path = tmp_path / "box.igz"
    save_scene(sc, path)
    back = Scene()
    load_into(back, path)
    box = _box(back)
    assert box is not None and not box.active
    assert (box.lo, box.hi) == (V(-1, -2, -3), V(1, 2, 3))
    _put(sc, None)                              # no box: none back
    save_scene(sc, path)
    load_into(back, path)
    assert _box(back) is None


def test_placing_moving_and_removing_the_box_undo_one_step_each():
    vp = Viewport(None)
    sc = vp.scene
    first = SectionBox(V(0, 0, 0), V(1, 1, 1))
    vp.history.execute(section_box_added(sc, first))
    assert sc.section_boxes == [first]
    vp.history.execute(section_box_changed(sc, first, first.with_face(1, 4)))
    assert first.hi.x() == pytest.approx(4)
    vp.history.execute(section_boxes_removed(sc, [first]))
    assert sc.section_boxes == []
    vp.history.undo()
    assert sc.section_boxes == [first] and first.hi.x() == pytest.approx(4)
    vp.history.undo()
    assert first.hi.x() == pytest.approx(1)              # the same object
    vp.history.undo()
    assert sc.section_boxes == []


def test_several_boxes_one_cutting_at_a_time():
    vp = Viewport(None)
    sc = vp.scene
    a = SectionBox(V(0, 0, 0), V(1, 1, 1), name="A")
    b = SectionBox(V(5, 5, 5), V(6, 6, 6), name="B")
    vp.history.execute(section_box_added(sc, a))
    vp.history.execute(section_box_added(sc, b))        # a new one cuts
    assert sc.section_boxes == [a, b]
    assert sc.active_section_box() is b and not a.active
    on = a.copy()
    on.active = True
    vp.history.execute(section_box_changed(sc, a, on))   # A cuts again
    assert sc.active_section_box() is a and not b.active
    cut = cut_planes(sc)
    assert len(cut) == 6 and all(f.box is a for f in cut)
    vp.history.undo()
    assert sc.active_section_box() is b
    assert a.uid != b.uid


def test_a_scene_brings_its_box_back_and_one_without_switches_it_off():
    from core.saved_views import SavedView
    vp = Viewport(None)
    sc, cam = vp.scene, vp.camera
    bare = SavedView.capture("Bare", sc, cam)
    assert "box" not in bare.section                    # as scenes were
    room_box = SectionBox(V(0, 0, 0), V(5, 5, 3), name="Room")
    detail = SectionBox(V(-9, -9, -9), V(9, 9, 9), active=False,
                        name="Detail")
    sc.section_boxes[:] = [room_box, detail]
    room = SavedView.capture("Room", sc, cam)
    assert room.section["box"] == room_box.uid
    sc.set_active_section_box(detail)
    room.apply(sc, cam)
    assert sc.active_section_box() is room_box          # by its uid
    bare.apply(sc, cam)
    assert sc.section_boxes == [room_box, detail]       # kept, never deleted
    assert sc.active_section_box() is None              # but none cutting
    back = SavedView.from_dict(room.to_dict())          # through the file
    back.apply(sc, cam)
    assert sc.active_section_box() is room_box


# ---- What the box hides --------------------------------------------------------

def _w2p(p):
    return (p.x() * 100.0, -p.z() * 100.0)       # side view, 100 px a metre


def _snap(vp, p):
    cand = V(p.x(), p.y(), p.z() + 0.03)
    return compute_snap(cand, _w2p(cand), vp._snap_scene(), _w2p,
                        threshold_px=9.0, edge_threshold_px=14.0,
                        is_occluded=vp._is_occluded,
                        are_occluded=vp._occluded_many)


def test_what_lies_outside_the_box_does_not_snap():
    """A 3 m vertical edge; the box keeps z 0..1.5 of it."""
    vp = Viewport(None)
    vp.scene.mesh.add_edge(V(2, 2, 0), V(2, 2, 3))
    _put(vp.scene, SectionBox(V(0, 0, -1), V(4, 4, 1.5)))
    vp.scene.version += 1
    top = _snap(vp, V(2, 2, 3.0))
    assert top is None or top.kind in (None, "none") \
        or top.point.z() <= 1.5 + 1e-6
    bottom = _snap(vp, V(2, 2, 0.0))
    assert bottom.kind == "endpoint" and abs(bottom.point.z()) < 1e-6
    assert vp._occluded_many([V(2, 2, 3), V(2, 2, 0)]) == [True, False]
    _box(vp.scene).active = False                  # off: all back
    assert vp._occluded_many([V(2, 2, 3), V(2, 2, 0)]) == [False, False]


def test_the_box_and_the_plane_cut_together():
    vp = Viewport(None)
    sc = vp.scene
    _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 4)))
    sp = SectionPlane(V(0, 0, 2), V(0, 0, 1), active=True)
    sc.section_planes.append(sp)
    cut = _active_cut(sc)
    assert cut.hidden([[2, 2, 1], [2, 2, 3], [5, 2, 1]]).tolist() == \
        [False, True, True]                  # kept / above the plane / out


# ---- The tool ------------------------------------------------------------------

@pytest.fixture
def boxed():
    from views.main_window import MainWindow
    w = MainWindow()
    vp = w.viewport
    vp.resize(800, 600)
    sc = vp.scene
    _cube(sc.mesh, 0, 0, 0, 4, 4, 2)
    sc.version += 1
    # From +X, −Y and above: the −Y, +X and top faces of a box face us.
    vp.camera.set_view("iso")
    vp.camera.perspective = False
    vp.camera.fit_to(V(-2, -2, -1), V(6, 6, 4))
    yield w
    w._saved_version = sc.version
    w.close()


def _ctx(vp, world, snap_kind="none"):
    px = vp._world_to_pixel(world)
    return ToolContext(vp, world, QPointF(*px), Qt.NoModifier,
                       SnapResult(world, snap_kind))


def test_the_tool_makes_a_new_box_unless_a_box_is_selected(boxed):
    """The button's one rule. Nothing selected: a new box round the model,
    whatever other boxes there are, cutting or not. A box selected: that
    one. A new box comes selected, so a second press goes on with it."""
    vp = boxed.viewport
    sc = vp.scene
    boxed._activate_tool("section_box")
    first = _box(sc)
    assert first is not None and first.active
    assert first.lo.x() < 0 and first.hi.x() > 4        # the model, plus
    assert first in sc.selection                        # with its grips
    boxed._activate_tool("select")
    boxed._activate_tool("section_box")                 # still selected
    assert sc.section_boxes == [first]
    boxed._activate_tool("select")
    sc.clear_selection()
    boxed._activate_tool("section_box")                 # one cuts: a new one
    assert len(sc.section_boxes) == 2
    second = sc.active_section_box()
    assert second is not first and not first.active
    assert second.name != first.name
    boxed._act_section_box.setChecked(False)            # the switch: off
    assert sc.active_section_box() is None
    boxed._activate_tool("select")
    sc.clear_selection()
    boxed._activate_tool("section_box")                 # none cuts: new too
    assert len(sc.section_boxes) == 3
    third = sc.active_section_box()
    boxed._activate_tool("select")
    sc.select([first])                                  # picked: that one
    boxed._activate_tool("section_box")
    assert len(sc.section_boxes) == 3
    assert sc.active_section_box() is first and not third.active
    boxed._on_remove_section_box(first)
    assert first not in sc.section_boxes
    assert vp.active_tool is boxed._tools["select"]


def test_dragging_a_face_is_one_undo_step_and_esc_puts_it_back(boxed):
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([_box(sc)])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    depth = len(vp.history.undo_stack)
    right = V(4, 2, 1)                                   # the +X face
    tool.on_hover(_ctx(vp, right))
    assert tool.hover_face == 1
    tool.on_click(_ctx(vp, right))
    tool.on_hover(_ctx(vp, V(3, 2, 1)))                  # drag 1 m in
    assert _box(sc).hi.x() == pytest.approx(3, abs=1e-3)
    assert len(vp.history.undo_stack) == depth           # live, no step yet
    tool.on_cancel(vp)                                   # Esc
    assert _box(sc).hi.x() == pytest.approx(4)
    tool.on_click(_ctx(vp, right))
    tool.on_hover(_ctx(vp, V(2.5, 2, 1)))
    tool.on_release(vp)                                  # a stroke commits
    assert _box(sc).hi.x() == pytest.approx(2.5, abs=1e-3)
    assert len(vp.history.undo_stack) == depth + 1
    vp.history.undo()
    assert _box(sc).hi.x() == pytest.approx(4)


def test_a_typed_distance_moves_the_face_out_by_that_much(boxed):
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([_box(sc)])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    front = V(2, 0, 1)                                   # the −Y face
    tool.on_click(_ctx(vp, front))
    assert tool.drag_face == 2
    assert tool.on_value(vp, 0.5)                        # out: lo goes −0.5
    assert _box(sc).lo.y() == pytest.approx(-0.5)
    assert tool.drag_face is None
    tool.on_click(_ctx(vp, V(4, 2, 1)))                  # the +X face
    assert tool.on_value(vp, -1.0)                       # in: hi goes 3
    assert _box(sc).hi.x() == pytest.approx(3)


def test_a_model_point_pulls_the_face_level_only_from_near(boxed):
    """A corner of the model pulls the dragged face level with it when the
    face passes close by on screen — a magnet — and never from afar: a
    corner of the floor seen past the face used to throw it down there."""
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 3)))
    sc.select([_box(sc)])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    tool.on_click(_ctx(vp, V(2, 2, 3)))                  # the top face
    assert tool.drag_face == 5
    near = V(2, 2, 2.03)                                 # the face nearly at 2
    px = vp._world_to_pixel(near)
    tool.on_hover(ToolContext(vp, V(1, 4, 2), QPointF(*px), Qt.NoModifier,
                              SnapResult(V(1, 4, 2), "endpoint")))
    assert _box(sc).hi.z() == pytest.approx(2)     # pulled level
    far = vp._world_to_pixel(V(2, 2, 2.6))
    tool.on_hover(ToolContext(vp, V(0, 0, 0), QPointF(*far), Qt.NoModifier,
                              SnapResult(V(0, 0, 0), "endpoint")))
    assert _box(sc).hi.z() == pytest.approx(2.6, abs=0.02)   # free
    tool.on_hover(ToolContext(vp, V(1, 4, 2.6), QPointF(*far),
                              Qt.NoModifier, SnapResult(V(9, 9, 0),
                                                        "on_line")))
    assert _box(sc).hi.z() == pytest.approx(2.6, abs=0.02)   # a line
    tool.on_release(vp)
    assert _box(sc).hi.z() == pytest.approx(2.6, abs=0.02)


# ---- The pixels -----------------------------------------------------------------

@pytest.fixture
def shown(boxed):
    boxed.show()
    for _ in range(10):
        _app.processEvents()
    vp = boxed.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    st = vp.scene.display_style
    st.sky, st.profiles = False, False
    yield boxed


def _pixel(vp, world):
    img = vp.grabFramebuffer()
    dpr = img.width() / max(vp.width(), 1)
    x, y = vp._world_to_pixel(world)
    return img.pixelColor(int(x * dpr), int(y * dpr))


def test_the_box_cuts_the_view_and_fills_its_face(shown):
    vp = shown.viewport
    sc = vp.scene
    vp.camera.set_view("front")                          # looking toward +Y
    vp.camera.fit_to(V(-2, -2, -1), V(6, 6, 4))
    vp.repaint()
    _app.processEvents()
    outside = V(3, 0, 1)
    before = _pixel(vp, outside)
    _put(sc, SectionBox(V(-1, -1, -1), V(2, 5, 3)))  # keeps x < 2
    sc.version += 1
    vp.repaint()
    _app.processEvents()
    bg = sc.display_style.background
    out = _pixel(vp, outside)
    assert abs(out.redF() - bg[0]) < 0.05 and abs(out.greenF() - bg[1]) < 0.05
    assert out != before                                 # it was the cube
    # The cut face of the cube at x = 2, seen from the front, is behind
    # its front face; from the side it is the fill's colour.
    vp.camera.set_view("right")
    vp.camera.fit_to(V(-1, -1, -1), V(5, 5, 3))
    vp.repaint()
    _app.processEvents()
    fill = sc.display_style.section_fill_color
    c = _pixel(vp, V(2, 2, 1))
    assert abs(c.redF() - fill[0]) < 0.08 and abs(c.blueF() - fill[2]) < 0.08


def test_a_removed_box_gives_the_whole_model_back_on_screen(shown):
    """#1552 in pixels: the box cuts, is removed, and the model shows whole
    again — not still cut by the planes the frame before left set."""
    vp = shown.viewport
    sc = vp.scene
    vp.camera.set_view("front")
    vp.camera.fit_to(V(-2, -2, -1), V(6, 6, 4))
    vp.repaint()
    _app.processEvents()
    outside = V(3, 0, 1)
    whole = _pixel(vp, outside)
    box = _put(sc, SectionBox(V(-1, -1, -1), V(2, 5, 3)))  # keeps x < 2
    sc.version += 1
    vp.repaint()
    _app.processEvents()
    assert _pixel(vp, outside) != whole                  # cut away
    shown._on_remove_section_box(box)
    for _ in range(2):                                   # and the next one
        vp.repaint()
        _app.processEvents()
        assert _pixel(vp, outside) == whole


# ---- Round 2: the way the typed distance goes, arrows, the box as an object

def test_a_typed_distance_goes_the_way_the_drag_goes(boxed):
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([_box(sc)])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    right = V(4, 2, 1)                                   # the +X face
    tool.on_click(_ctx(vp, right))
    tool.on_hover(_ctx(vp, V(3, 2, 1)))                  # pushed in
    assert tool.on_value(vp, 0.5)
    assert _box(sc).hi.x() == pytest.approx(3.5)   # in by 0.5
    tool.on_click(_ctx(vp, V(3.5, 2, 1)))
    tool.on_hover(_ctx(vp, V(4.5, 2, 1)))                # pulled out
    assert tool.on_value(vp, 0.5)
    assert _box(sc).hi.x() == pytest.approx(4.0)   # out by 0.5
    tool.on_click(_ctx(vp, V(4, 2, 1)))
    tool.on_hover(_ctx(vp, V(4.5, 2, 1)))                # out, but typed −
    assert tool.on_value(vp, -1.0)
    assert _box(sc).hi.x() == pytest.approx(3.0)


def test_each_face_has_an_arrow_to_pull_without_a_jump(boxed):
    from tools.section_box import arrow_pixels, pick_arrow
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([_box(sc)])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    arrows = {i: (b, t) for i, b, t in arrow_pixels(vp, _box(sc))}
    assert 1 in arrows and 5 in arrows                   # +X and top
    b, t = arrows[1]
    tip = ((b[0] + 3 * t[0]) / 4, (b[1] + 3 * t[1]) / 4)
    assert pick_arrow(vp, _box(sc), *tip) == 1
    ctx = ToolContext(vp, V(0, 0, 0), QPointF(*tip), Qt.NoModifier,
                      SnapResult(V(0, 0, 0), "none"))
    tool.on_click(ctx)
    assert tool.drag_face == 1
    tool.on_hover(ctx)                                   # not moved yet
    assert _box(sc).hi.x() == pytest.approx(4, abs=1e-6)
    tool.on_cancel(vp)


def test_the_box_selects_shows_arrows_and_select_hands_them_on(boxed):
    from tools.section_box import arrow_pixels
    vp = boxed.viewport
    sc = vp.scene
    box = _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.version += 1
    boxed._activate_tool("select")
    a = vp._world_to_pixel(V(0, 0, 0))
    b = vp._world_to_pixel(V(4, 0, 0))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)          # on an edge
    assert vp.pick_section_box(*mid) is box
    sc.select([box])
    arrows = {i: (p, q) for i, p, q in arrow_pixels(vp, box)}
    p, q = arrows[5]
    on_arrow = ((p[0] + 3 * q[0]) / 4, (p[1] + 3 * q[1]) / 4)
    ctx = ToolContext(vp, V(0, 0, 0), QPointF(*on_arrow), Qt.NoModifier,
                      SnapResult(V(0, 0, 0), "none"))
    assert vp.active_tool.on_press_grab(ctx)
    assert vp.active_tool is boxed._tools["section_box"]
    assert vp.active_tool.drag_face == 5
    assert _box(sc) is box                         # not replaced


def test_delete_takes_the_box_away_and_undo_brings_the_same_one(boxed):
    from tools.select import erase_entities
    vp = boxed.viewport
    sc = vp.scene
    box = _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([box])
    assert erase_entities(vp, [box])
    assert _box(sc) is None and box not in sc.selection
    vp.history.undo()
    assert _box(sc) is box


def test_the_box_fill_is_its_own_saved_and_kept_through_undo(tmp_path):
    from core.history import SetSectionFillCommand
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    vp = Viewport(None)
    sc = vp.scene
    box = SectionBox(V(0, 0, 0), V(2, 2, 2))
    vp.history.execute(section_box_added(sc, box))
    vp.history.execute(SetSectionFillCommand(box, {"pattern": "hatch",
                                                   "spacing": 0.1}))
    vp.history.execute(section_box_changed(sc, box, box.with_face(1, 5)))
    assert _box(sc) is box and box.fill["pattern"] == "hatch"
    vp.history.undo()                                    # the drag
    assert _box(sc) is box and box.hi.x() == pytest.approx(2)
    vp.history.undo()                                    # the fill
    assert _box(sc) is box and box.fill is None
    vp.history.redo()
    _cube(sc.mesh, 0, 0, 0, 1, 1, 1)
    path = tmp_path / "fill.igz"
    save_scene(sc, path)
    back = Scene()
    load_into(back, path)
    assert _box(back).fill == {"pattern": "hatch", "spacing": 0.1}


def test_the_browser_lists_the_box_with_its_cut_and_frame(boxed):
    vp = boxed.viewport
    sc = vp.scene
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1), active=True)
    sc.section_planes.append(sp)
    box = _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.version += 1
    panel = boxed.project_browser.outliner
    panel.refresh()
    rows = [panel._box_root.child(i)
            for i in range(panel._box_root.childCount())]
    item = next(r for r in rows if panel._box_of(r) is box)
    assert not panel._box_root.isHidden()
    panel._on_item_clicked(item, 1)                      # the eye: no frame
    assert box.hidden and box.active
    panel._on_item_clicked(item, 1)
    assert not box.hidden
    panel._on_item_clicked(item, 2)                      # the slice: off
    assert _box(sc) is box and not box.active
    assert sp.active                                     # the plane cuts on
    panel._on_item_clicked(item, 1)                      # off: no eye to use
    assert not box.hidden
    panel._on_item_clicked(item, 2)                      # and on again
    assert box.active and not box.hidden
    vp.history.undo()
    assert not box.active


# ---- Sheets: the hidden-line drawing follows the box ------------------------

def test_the_sheet_drawing_cuts_and_fills_at_the_box():
    from core.camera import OrbitCamera
    from core.hlr import hlr_drawing
    from core.scene import Scene
    sc = Scene()
    _cube(sc.mesh, 0, 0, 0, 4, 4, 2)
    sc.version += 1
    cam = OrbitCamera()
    cam.set_view("right")                                # looking along −X
    cam.perspective = False
    cam.fit_to(V(-1, -1, -1), V(5, 5, 3))
    whole = hlr_drawing(sc, cam)
    assert whole.loops == []
    _put(sc, SectionBox(V(-1, 1, -1), V(2, 3, 3)))  # x < 2, 1<y<3
    cut = hlr_drawing(sc, cam)
    assert all(max(w[0][0], w[1][0]) <= 2 + 1e-6 for w in cut.world)
    assert all(1 - 1e-6 <= min(w[0][1], w[1][1]) for w in cut.world)
    # The fill at the x = 2 face: the cube's section, 2 m wide (the box's
    # y range) by 2 m high, clipped by the box's other faces.
    import numpy as np
    area = 0.0
    for ring in cut.loops:
        r = np.asarray(ring)
        x, y = r[:, 0], r[:, 1]
        area += 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    assert area == pytest.approx(4.0, rel=1e-3)
    # From the other side the x = 2 cut faces away, behind the material:
    # no poché painted over the drawing.
    cam.set_view("left")
    cam.fit_to(V(-1, -1, -1), V(5, 5, 3))
    assert hlr_drawing(sc, cam).loops == []


def test_a_sheet_frame_leaves_the_live_box_as_it_was():
    """A frame bound to a scene applies the scene's box while it renders;
    the live box comes back the same object, as it was."""
    from core.saved_views import SavedView
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    from core.composition import MarcoVista
    win = MainWindow()
    comp = None
    try:
        sc = win.viewport.scene
        _cube(sc.mesh, 0, 0, 0, 4, 4, 2)
        live = SectionBox(V(-5, -5, -5), V(9, 9, 9), name="Live")
        detail = SectionBox(V(0, 0, 0), V(1, 1, 1), active=False,
                            name="Detail")
        sc.section_boxes[:] = [live, detail]
        sc.version += 1
        view = SavedView("Detalle", target=(2, 2, 1), distance=10.0)
        view.section = {"active": None, "planes_shown": True,
                        "cuts_shown": True, "box": detail.uid}
        sc.saved_views.append(view)
        comp = ComposerWindow(win)
        frame = MarcoVista(view_key="scene:Detalle", style="vectorial")
        seen = comp._with_frame_camera(frame, sc.active_section_box)
        assert seen is detail                          # the scene's box
        assert sc.active_section_box() is live         # and back
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- Round 3: the fill comes back, the model's right-click, the grips -----

def test_the_fill_comes_once_the_cut_rests_even_with_frames_coming(boxed):
    """Frames that keep coming with the cut still (shadows or ambient
    occlusion refining) must not hold the fill back: it used to wait for
    a pause between FRAMES, and never came until the fill was switched off
    and on."""
    import time
    from core.section import cut_planes
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(-1, -1, -1), V(5, 5, 1.0)))   # cuts at z=1
    sc.version += 1
    top = cut_planes(sc)[-1]
    assert vp._section_fill_tris(top) is not None              # cached
    _box(sc).hi = V(5, 5, 1.5)                            # dragged
    top = cut_planes(sc)[-1]
    got = None
    end = time.monotonic() + 0.8
    while got is None and time.monotonic() < end:
        got = vp._section_fill_tris(top)                        # a frame
        time.sleep(0.05)                                        # 20 fps
    assert got is not None and len(got)


def test_a_right_click_over_the_selected_box_is_the_box_s(boxed):
    vp = boxed.viewport
    sc = vp.scene
    box = _put(sc, SectionBox(V(-1, -1, -1), V(5, 5, 3)))
    sc.version += 1
    x, y = vp._world_to_pixel(V(2, 0, 1))          # the cube's front face
    assert vp._context_pick(x, y) is not box       # not selected: the wall
    sc.select([box])
    assert vp._context_pick(x, y) is box           # selected: the box
    assert sc.selection == {box}


def test_the_model_menu_of_the_box_has_its_cut_frame_and_fill(boxed):
    from PySide6.QtWidgets import QMenu
    from core.i18n import tr
    box = _put(boxed.viewport.scene, SectionBox(V(0, 0, 0),
                                                        V(1, 1, 1)))
    menu = QMenu()
    boxed._section_box_menu(menu, box)
    texts = [a.text() for a in menu.actions()]
    for wanted in ("Show the whole model", "Edit Section Box",
                   "Show the frame", "Remove Section Box"):
        assert tr(wanted) in texts, wanted
    assert any(a.menu() is not None for a in menu.actions())   # the fill
    box.active = False                                   # off: turn it on
    menu = QMenu()
    boxed._section_box_menu(menu, box)
    texts = [a.text() for a in menu.actions()]
    assert tr("Cut with this box") in texts
    assert tr("Show the whole model") not in texts
    assert tr("Show the frame") not in texts             # no frame to switch


def test_a_grip_takes_its_face_by_the_dot_and_both_arrow_heads(boxed):
    from tools.section_box import arrow_pixels, pick_arrow
    vp = boxed.viewport
    box = _put(vp.scene, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    grips = {i: (c, t) for i, c, t in arrow_pixels(vp, box)}
    c, t = grips[1]
    inner = (2 * c[0] - t[0], 2 * c[1] - t[1])
    assert pick_arrow(vp, box, *c) == 1                  # the dot
    assert pick_arrow(vp, box, *t) == 1                  # pull out
    assert pick_arrow(vp, box, *inner) == 1              # push in


def test_the_dot_drags_with_the_mouse_from_select(boxed):
    """The real gesture: Select, the box selected, press on the top grip's
    dot, move a little, release — the face follows the mouse a little, one
    undo step, and the Section Box tool is out to go on."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    from tools.section_box import arrow_pixels
    vp = boxed.viewport
    sc = vp.scene
    box = _put(sc, SectionBox(V(-1, -1, -1), V(5, 5, 3)))
    sc.version += 1
    boxed._activate_tool("select")
    sc.select([box])
    depth = len(vp.history.undo_stack)
    c = {i: c for i, c, _t in arrow_pixels(vp, box)}[5]

    def send(kind, x, y, buttons, button=Qt.LeftButton):
        p = QPointF(x, y)
        QApplication.sendEvent(vp, QMouseEvent(
            kind, p, vp.mapToGlobal(p.toPoint()).toPointF(), button,
            buttons, Qt.NoModifier))
        _app.processEvents()

    send(QEvent.MouseButtonPress, c[0], c[1], Qt.LeftButton)
    for k in range(1, 7):
        send(QEvent.MouseMove, c[0], c[1] + 2 * k, Qt.LeftButton,
             Qt.NoButton)
        vp._run_pending_hover()
    send(QEvent.MouseButtonRelease, c[0], c[1] + 12, Qt.NoButton)
    assert vp.active_tool is boxed._tools["section_box"]
    assert 1.0 < _box(sc).hi.z() < 3.0            # down, a little
    assert len(vp.history.undo_stack) == depth + 1


# ---- Round 5: several boxes, one cutting --------------------------------------

def test_several_boxes_are_saved_with_their_names_and_the_one_cutting(
        tmp_path):
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    sc = Scene()
    _cube(sc.mesh, 0, 0, 0, 1, 1, 1)
    a = SectionBox(V(0, 0, 0), V(1, 1, 1), active=False, name="Planta")
    b = SectionBox(V(2, 2, 2), V(3, 3, 3), name="Detalle")
    b.fill = {"pattern": "cross"}
    sc.section_boxes[:] = [a, b]
    path = tmp_path / "boxes.igz"
    save_scene(sc, path)
    back = Scene()
    load_into(back, path)
    assert [x.name for x in back.section_boxes] == ["Planta", "Detalle"]
    assert back.active_section_box().name == "Detalle"
    assert back.section_boxes[1].fill == {"pattern": "cross"}
    assert [x.uid for x in back.section_boxes] == [a.uid, b.uid]


def test_the_tool_makes_a_new_box_around_a_selection_and_keeps_the_first(
        boxed):
    """Geometry selected, the tool puts a NEW box around it: several boxes
    in a model, each showing its part, one cutting at a time."""
    vp = boxed.viewport
    sc = vp.scene
    boxed._activate_tool("section_box")                  # the whole model
    first = sc.active_section_box()
    assert sc.section_boxes == [first] and first.name
    boxed._activate_tool("select")
    sc.select(list(sc.mesh.faces)[:1])                   # the floor, z = 0
    boxed._activate_tool("section_box")                  # a NEW box
    second = sc.active_section_box()
    assert sc.section_boxes == [first, second]
    assert second.hi.z() < 1 and first.hi.z() > 2        # each its own
    assert not first.active and second.name != first.name
    assert second in sc.selection                        # its grips out
    boxed._activate_tool("select")
    sc.select([first])
    boxed._activate_tool("section_box")                  # edit the picked
    assert sc.section_boxes == [first, second]
    assert sc.active_section_box() is first


def test_the_browser_lists_every_box_by_name_and_renames_it(boxed):
    vp = boxed.viewport
    sc = vp.scene
    a = SectionBox(V(0, 0, 0), V(1, 1, 1), name="Planta")
    b = SectionBox(V(0, 0, 0), V(2, 2, 2), active=False, name="Detalle")
    sc.section_boxes[:] = [a, b]
    sc.version += 1
    panel = boxed.project_browser.outliner
    panel.refresh()
    rows = [panel._box_root.child(i)
            for i in range(panel._box_root.childCount())]
    names = [r.text(0) for r in rows if panel._box_of(r) is not None]
    assert names == ["Planta", "Detalle"]
    panel.set_section_mode(b, "both")                    # Detalle cuts
    assert sc.active_section_box() is b and not a.active
    from views import prompts
    old = prompts.get_text
    prompts.get_text = lambda *a_, **k: ("Encuentro", True)
    try:
        assert panel.rename_box(b)
    finally:
        prompts.get_text = old
    assert b.name == "Encuentro"
    vp.history.undo()
    assert b.name == "Detalle"


def test_an_exported_picture_gets_its_fill_at_once(boxed):
    """A sheet frame renders once, right after its scene switched another
    box on: the fill must not wait for the cut to rest."""
    from core.section import cut_planes
    vp = boxed.viewport
    sc = vp.scene
    _put(sc, SectionBox(V(-1, -1, -1), V(5, 5, 1.0)))
    sc.version += 1
    assert vp._section_fill_tris(cut_planes(sc)[-1]) is not None
    _box(sc).hi = V(5, 5, 1.5)                           # another cut
    vp._export_size = (100, 100)
    try:
        got = vp._section_fill_tris(cut_planes(sc)[-1])
    finally:
        vp._export_size = None
    assert got is not None and len(got)


def test_the_boxes_have_a_folder_of_their_own_in_the_browser(boxed):
    """Section boxes fold into their own «Section boxes» folder, beside the
    planes' — its eye shows or hides every box's frame, its slice turns
    the boxes' cut on (the last box) or off."""
    vp = boxed.viewport
    sc = vp.scene
    panel = boxed.project_browser.outliner
    panel.refresh()
    assert panel._box_root.isHidden()                    # no boxes yet
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    sc.section_planes.append(sp)
    a = SectionBox(V(0, 0, 0), V(1, 1, 1), active=False, name="A")
    b = SectionBox(V(0, 0, 0), V(2, 2, 2), active=False, name="B")
    sc.section_boxes[:] = [a, b]
    sc.version += 1
    panel.refresh()
    assert not panel._box_root.isHidden()
    assert panel._box_root is not panel._sec_root
    assert [panel._plane_of(panel._sec_root.child(i))
            for i in range(panel._sec_root.childCount())] == [sp]
    assert [panel._box_of(panel._box_root.child(i))
            for i in range(panel._box_root.childCount())] == [a, b]
    panel._on_item_clicked(panel._box_root, 2)           # the slice: on
    assert sc.active_section_box() is b
    panel._on_item_clicked(panel._box_root, 2)           # and off
    assert sc.active_section_box() is None
    panel._on_item_clicked(panel._box_root, 1)           # no eye on it
    assert not a.hidden and not b.hidden


# ---- Round 7: annotations outside the box go with it ---------------------------

def test_annotations_outside_the_box_go_with_the_geometry():
    """Dimensions, texts, guide points and survey points standing outside
    the box that cuts are off the screen, out of the pick and the snap —
    the sheets ask the same question; a guide LINE stays (the clip cuts
    it); with the box off, everything is back."""
    from core.dimension import Dimension
    from core.guide import Guide
    from core.textlabel import TextLabel
    from georef.points import GeoPoint
    vp = Viewport(None)
    sc = vp.scene
    inside_dim = Dimension(V(0, 0, 0), V(2, 0, 0), V(0, -1, 0))
    tall_dim = Dimension(V(0, 0, 0), V(0, 0, 6), V(-1, 0, 0))   # leaves
    inside_txt = TextLabel(V(1, 1, 0.5), V(0, 0, 1), "Salón")
    upper_txt = TextLabel(V(1, 1, 4.5), V(0, 0, 1), "Dormitorio")
    low_point = Guide(V(1, 1, 1))
    high_point = Guide(V(1, 1, 5))
    line = Guide(V(0, 0, 9), V(1, 0, 0))
    survey = GeoPoint(V(9, 9, 9), "P1")
    sc.dimensions += [inside_dim, tall_dim]
    sc.text_labels += [inside_txt, upper_txt]
    sc.guides += [low_point, high_point, line]
    sc.geo_points.append(survey)
    everything = [inside_dim, tall_dim, inside_txt, upper_txt, low_point,
                  high_point, line, survey]
    assert all(sc.entity_visible(e) for e in everything)
    _put(sc, SectionBox(V(-1, -1, -1), V(4, 4, 3)))      # the ground floor
    sc.version += 1
    shown = [e for e in everything if sc.entity_visible(e)]
    assert shown == [inside_dim, inside_txt, low_point, line]
    assert not sc.entity_selectable(upper_txt)
    assert sc.entity_selectable(inside_txt)
    from views.viewport import shown_guides
    assert shown_guides(sc) == [low_point, line]
    _box(sc).active = False                              # off: all back
    assert all(sc.entity_visible(e) for e in everything)
    _box(sc).active = True
    sc.show_section_cuts = False                         # cuts off: too
    assert all(sc.entity_visible(e) for e in everything)


# ---- Round 8: a box that does nothing shows nothing; one click back --------

def test_a_box_that_is_off_draws_nothing_and_cannot_be_picked(boxed):
    vp = boxed.viewport
    sc = vp.scene
    on = SectionBox(V(0, 0, 0), V(4, 4, 2), name="On")
    off = SectionBox(V(-3, -3, -3), V(9, 9, 9), active=False, name="Off")
    sc.section_boxes[:] = [on, off]
    sc.version += 1
    assert vp._section_boxes_shown() == [on]
    a = vp._world_to_pixel(V(-3, -3, -3))
    b = vp._world_to_pixel(V(9, -3, -3))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    assert vp.pick_section_box(*mid) is None             # its edge: nothing
    sc.select([off])                                     # picked in the list
    assert vp._section_boxes_shown() == [on, off]        # shown, to see it
    sc.clear_selection()
    on.active = False
    assert vp._section_boxes_shown() == []               # the model, alone
    on.active = True
    sc.show_section_cuts = False                         # no cuts: same
    assert vp._section_boxes_shown() == []


def test_the_notice_is_short_in_the_corner_and_goes_back_to_the_whole_model(boxed):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    vp = boxed.viewport
    sc = vp.scene
    assert vp._section_box_chip() is None                # no box: no notice
    box = SectionBox(V(0, 0, 0), V(4, 4, 2), name="Planta")
    sc.section_boxes[:] = [box]
    sc.version += 1
    sc.select([box])
    boxed._activate_tool("section_box")
    rect, text = vp._section_box_chip()
    # Short, in the bottom-right corner, off the model (#1552).
    from core.i18n import tr
    assert text == tr("Section Box") + "  ✕"
    assert rect.right() <= vp.width() and rect.bottom() <= vp.height()
    assert rect.left() > vp.width() * 0.5 and rect.top() > vp.height() * 0.5
    c = rect.center()
    depth = len(vp.history.undo_stack)
    QApplication.sendEvent(vp, QMouseEvent(
        QEvent.MouseButtonPress, c, vp.mapToGlobal(c.toPoint()).toPointF(),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert sc.active_section_box() is None               # the whole model
    assert sc.section_boxes == [box]                     # the box stays
    assert vp.active_tool is boxed._tools["select"]
    assert vp._section_box_chip() is None
    assert not boxed._act_section_box.isChecked()
    assert len(vp.history.undo_stack) == depth + 1
    vp.history.undo()
    assert sc.active_section_box() is box
    boxed._sync_section_box_actions()
    assert boxed._act_section_box.isChecked()            # the button follows


def test_the_toolbar_button_switches_the_box_on_and_off(boxed):
    vp = boxed.viewport
    sc = vp.scene
    act = boxed._act_section_box
    assert act in boxed.toolbars["sections"].actions()
    box = SectionBox(V(0, 0, 0), V(4, 4, 2), active=False, name="Planta")
    sc.section_boxes[:] = [box]
    act.setChecked(True)
    assert sc.active_section_box() is box
    act.setChecked(False)
    assert sc.active_section_box() is None and sc.section_boxes == [box]


# ---- #1552: a removed box leaves no cut behind ----------------------------------

class _FakeGL:
    """What ``_set_section_clip`` asks of GL, written down."""

    def __init__(self):
        self.enabled = set()

    def glEnable(self, cap):
        self.enabled.add(cap)

    def glDisable(self, cap):
        self.enabled.discard(cap)


class _FakeProgram:
    def __init__(self):
        self.values = {}

    def setUniformValue(self, loc, value):
        self.values[loc] = value


def _fake_clip_state(vp):
    """``vp`` drawing into a fake GL and program — no context needed."""
    vp._gl, vp._program = _FakeGL(), _FakeProgram()
    vp._loc_clip_planes = [f"plane{i}" for i in range(7)]
    vp._loc_clip_count = "count"
    return vp._gl, vp._program


def test_switching_the_cut_off_clears_it_once_the_box_is_gone(boxed):
    """The program keeps its uniforms and GL its enables between frames:
    the box's six planes set while it cut must go when the cut is
    switched off with no box left — they cut the model on until the file
    was opened again (#1552)."""
    from views.viewport._support import GL_CLIP_DISTANCE0
    vp = boxed.viewport
    gl, prog = _fake_clip_state(vp)
    box = SectionBox(V(0, 0, 0), V(4, 4, 1))
    vp._clip_vecs = [object()] * len(box.faces())        # the box cuts
    vp._set_section_clip(True)
    assert prog.values["count"] == 6 and len(gl.enabled) == 6
    vp._clip_vecs = []                                   # removed: no cut
    vp._set_section_clip(False)
    assert prog.values["count"] == 0
    assert not gl.enabled & {GL_CLIP_DISTANCE0 + i for i in range(7)}
    vp._set_section_clip(True)                           # nothing to cut
    assert prog.values["count"] == 0 and not gl.enabled


def test_the_drag_previews_leave_the_cut_off_for_what_comes_after(boxed):
    """The cursor's cues, the rubber band and the axes come after the
    drag's previews: they are not the model and the cut must be off for
    them. It was left on, every frame (the axes and the sky cut by the box
    while it cut, and its planes kept once it was gone)."""
    vp = boxed.viewport
    gl, prog = _fake_clip_state(vp)
    vp._clip_vecs = [object()] * 6
    vp._set_section_clip(True)
    vp._draw_preview_faces = lambda: None
    vp._draw_groups_preview = lambda mvp: None
    vp._draw_previews_after(None)
    assert prog.values["count"] == 0 and not gl.enabled


def test_the_toolbar_button_makes_no_box_when_there_is_none(boxed):
    """The button is a switch (its label: «Cut with a section box»). With
    no box it springs back off and makes none: the one it made, round the
    whole model and with the removed box's name, read as the removed box
    coming back (#1552). The Section Box tool still places one."""
    vp = boxed.viewport
    sc = vp.scene
    act = boxed._act_section_box
    act.setChecked(True)
    assert sc.section_boxes == [] and not act.isChecked()
    assert cut_planes(sc) == []
    boxed._activate_tool("section_box")                  # the tool: a box
    box = sc.active_section_box()
    assert box is not None and act.isChecked()
    boxed._on_remove_section_box(box)
    assert sc.section_boxes == [] and not act.isChecked()
    assert cut_planes(sc) == []
    act.setChecked(True)                                 # nothing comes back
    assert sc.section_boxes == [] and not act.isChecked()


def test_the_frame_button_hides_and_shows_the_cutting_box_frame(boxed):
    """Sections ▸ «Show the section box frame»: the frame of the box that
    cuts goes and comes back, one undo step each; the cut stays. Greyed
    out with no box cutting; it follows undo and the box's own menu."""
    vp = boxed.viewport
    sc = vp.scene
    frame = boxed._act_section_box_frame
    assert frame in boxed.toolbars["sections"].actions()
    boxed._sync_section_box_actions()
    assert not frame.isEnabled()                          # nothing cuts
    box = _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 1)))
    sc.version += 1
    boxed._act_section_box.setChecked(True)               # it cuts
    assert frame.isEnabled() and frame.isChecked()
    assert vp._section_boxes_shown() == [box]
    depth = len(vp.history.undo_stack)
    frame.setChecked(False)                               # hide the frame
    assert box.hidden and box.active and len(cut_planes(sc)) == 6
    assert vp._section_boxes_shown() == []
    assert len(vp.history.undo_stack) == depth + 1
    vp.history.undo()                                     # back: the button too
    vp.notify_scene_changed()                             # as Edit ▸ Undo does
    assert not box.hidden and frame.isChecked()
    boxed._set_section_box(box, hidden=True)              # its right-click
    assert not frame.isChecked()
    frame.setChecked(True)                                # show it again
    assert not box.hidden and vp._section_boxes_shown() == [box]
    boxed._act_section_box.setChecked(False)              # no cut: greyed
    assert not frame.isEnabled() and not frame.isChecked()


def test_the_frame_button_brings_the_planes_view_back_and_puts_the_tool_away(
        boxed):
    vp = boxed.viewport
    sc = vp.scene
    frame = boxed._act_section_box_frame
    boxed._activate_tool("section_box")                   # a box, editing
    box = sc.active_section_box()
    frame.setChecked(False)                               # no frame to drag
    assert vp.active_tool is boxed._tools["select"] and box.hidden
    boxed._set_section_visibility("show_section_planes", False)
    boxed._sync_section_box_actions()
    frame.setChecked(True)                                # every frame was off
    assert sc.show_section_planes and not box.hidden
    assert boxed._act_show_splanes.isChecked()
    boxed._set_section_box(box, hidden=True)
    sc.select([box])
    boxed._activate_tool("section_box")                   # Edit Section Box
    assert not box.hidden and frame.isChecked()


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab])
def test_enter_or_tab_ends_the_editing_and_the_box_keeps_cutting(boxed, key):
    """Enter or Tab: done with the box. It keeps cutting as it stands, its
    grips go (deselected) and Select comes back. Tab reaches the tool
    before Qt moves the focus with it."""
    from PySide6.QtTest import QTest
    vp = boxed.viewport
    sc = vp.scene
    boxed._activate_tool("section_box")
    box = sc.active_section_box()
    assert box in sc.selection
    QTest.keyClick(vp, key)
    assert vp.active_tool is boxed._tools["select"]
    assert box not in sc.selection
    assert sc.active_section_box() is box and len(cut_planes(sc)) == 6


def test_tab_mid_drag_keeps_the_face_where_it_is_in_one_step(boxed):
    from PySide6.QtTest import QTest
    vp = boxed.viewport
    sc = vp.scene
    box = _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([box])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    depth = len(vp.history.undo_stack)
    tool.on_click(_ctx(vp, V(4, 2, 1)))                  # the +X face
    tool.on_hover(_ctx(vp, V(3, 2, 1)))                  # 1 m in
    QTest.keyClick(vp, Qt.Key_Tab)
    assert vp.active_tool is boxed._tools["select"]
    assert box.hi.x() == pytest.approx(3, abs=1e-3) and box.active
    assert len(vp.history.undo_stack) == depth + 1


def test_enter_after_a_typed_distance_sets_it_and_goes_on_editing(boxed):
    """Enter first reads a distance typed while dragging: the face moves by
    it and the tool stays out. A second Enter, nothing typed, is done."""
    from PySide6.QtTest import QTest
    vp = boxed.viewport
    sc = vp.scene
    box = _put(sc, SectionBox(V(0, 0, 0), V(4, 4, 2)))
    sc.select([box])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    tool.on_click(_ctx(vp, V(4, 2, 1)))                  # the +X face
    QTest.keyClicks(vp, "0.5")
    QTest.keyClick(vp, Qt.Key_Return)
    assert box.hi.x() == pytest.approx(4.5)
    assert vp.active_tool is tool
    QTest.keyClick(vp, Qt.Key_Return)
    assert vp.active_tool is boxed._tools["select"]
    assert box.hi.x() == pytest.approx(4.5) and box.active


def test_the_browser_adds_a_box_and_fit_keeps_the_same_box(boxed):
    """The Browser's New Section Box: another box round the whole model —
    or the selection — the others kept, switched off. «Fit the box to the
    whole model» grows the SAME box instead: name, fill and uid stay, one
    undo step."""
    vp = boxed.viewport
    sc = vp.scene
    small = SectionBox(V(0, 0, 0), V(1, 1, 1), name="Detalle")
    small.fill = {"pattern": "cross"}
    sc.section_boxes[:] = [small]
    sc.version += 1
    panel = boxed.project_browser.outliner
    panel.new_section_box()                              # another, bigger
    big = sc.active_section_box()
    assert sc.section_boxes == [small, big] and not small.active
    assert big.hi.x() > 4 and big.lo.x() < 0             # the whole cube
    assert big.name != small.name
    assert vp.active_tool is boxed._tools["section_box"]
    boxed._activate_tool("select")
    sc.select(list(sc.mesh.faces)[:1])                   # the floor
    panel.new_section_box()                              # round the floor
    floor = sc.active_section_box()
    assert sc.section_boxes == [small, big, floor] and floor.hi.z() < 1
    uid = small.uid
    depth = len(vp.history.undo_stack)
    boxed.project_browser.outliner._fit_box_to_model(small)
    assert sc.section_boxes == [small, big, floor]       # no new box
    assert small.hi.x() > 4 and sc.active_section_box() is small
    assert (small.name, small.uid, small.fill) == ("Detalle", uid,
                                                   {"pattern": "cross"})
    assert len(vp.history.undo_stack) == depth + 1
    vp.history.undo()
    assert small.hi.x() == pytest.approx(1)


def test_a_double_click_on_a_grey_box_makes_it_cut(boxed):
    """With every box shown, a double click on a grey one makes it the box
    that cuts — with Select, and with the Section Box tool out (a new box
    just made): there the click used to look at the cutting box only."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    vp = boxed.viewport
    sc = vp.scene
    vp.resize(800, 600)
    cut = SectionBox(V(0, 0, 0), V(4, 4, 1), name="Planta")
    big = SectionBox(V(-1, -1, -1), V(5, 5, 3), active=False, name="Todo")
    sc.section_boxes[:] = [cut, big]
    sc.version += 1
    boxed._act_show_all_section_boxes.setChecked(True)
    px = vp._world_to_pixel(V(5, 2, 3))                  # an edge of «Todo»
    at = QPoint(int(round(px[0])), int(round(px[1])))
    assert vp.pick_section_box(px[0], px[1]) is big
    QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, at)   # with Select
    assert sc.active_section_box() is big and not cut.active
    boxed._activate_tool("select")
    sc.select([cut])
    boxed._activate_tool("section_box")                  # «Planta» edited
    assert sc.active_section_box() is cut
    tool = vp.active_tool
    depth = len(vp.history.undo_stack)
    tool.on_click(_ctx(vp, V(5, 2, 3)))                  # the grey one
    tool.on_double_click(_ctx(vp, V(5, 2, 3)))
    assert sc.active_section_box() is big and big in sc.selection
    assert vp.active_tool is tool and tool.drag_face is None
    assert len(vp.history.undo_stack) == depth + 1       # one step
    assert sc.section_boxes == [cut, big]                # no new box


def test_a_box_inside_the_cutting_one_is_reached_by_its_edge_or_enter(boxed):
    """Boxes inside boxes: with the big one cutting and its tool out, the
    grey box inside lies all over its faces — a click on the inner box's
    EDGE takes that one up (the big box's grips still drag the big box).
    With Select, the inner box picked and Enter: it cuts, the tool out;
    Enter again is done, the cut stays."""
    from PySide6.QtTest import QTest
    vp = boxed.viewport
    sc = vp.scene
    big = SectionBox(V(-1, -1, -1), V(5, 5, 3), name="Todo")
    inner = SectionBox(V(1, 1, 0), V(3, 3, 1.5), active=False,
                       name="Detalle")
    sc.section_boxes[:] = [big, inner]
    sc.version += 1
    boxed._act_show_all_section_boxes.setChecked(True)
    sc.select([big])
    boxed._activate_tool("section_box")
    tool = vp.active_tool
    edge = V(3, 2, 1.5)                                  # inner's top edge
    tool.on_click(_ctx(vp, edge))
    assert sc.active_section_box() is inner and tool.drag_face is None
    tool.on_cancel(vp)
    boxed._activate_tool("select")
    sc.select([big])                                     # back to the big one
    boxed._activate_tool("section_box")
    assert sc.active_section_box() is big
    boxed._activate_tool("select")
    sc.select([inner])                                   # e.g. in the Browser
    QTest.keyClick(vp, Qt.Key_Return)
    assert sc.active_section_box() is inner and not big.active
    assert vp.active_tool is boxed._tools["section_box"]
    QTest.keyClick(vp, Qt.Key_Return)                    # done
    assert vp.active_tool is boxed._tools["select"]
    assert sc.active_section_box() is inner
    assert sc.section_boxes == [big, inner]              # no new box


def test_the_sections_bar_is_in_three_groups(boxed):
    """Sections: the tools | what every cut shares (cut, fill, frames) |
    the section box's own (cut with it, its frame, all boxes)."""
    acts = boxed.toolbars["sections"].actions()
    tools = boxed._tool_actions
    order = []
    for a in acts:
        if a.isSeparator():
            if order and order[-1] != "|":
                order.append("|")
            continue
        for key, name in ((tools["section"], "plane"),
                          (tools["section_box"], "box"),
                          (boxed._act_show_scuts, "cuts"),
                          (boxed._act_section_fill, "fill"),
                          (boxed._act_show_splanes, "frames"),
                          (boxed._act_section_box, "box_cut"),
                          (boxed._act_section_box_frame, "box_frame"),
                          (boxed._act_show_all_section_boxes, "all")):
            if a is key:
                order.append(name)
    assert order == ["plane", "box", "|", "cuts", "fill", "frames", "|",
                     "box_cut", "box_frame", "all"]


def test_show_all_draws_the_other_boxes_in_grey_to_pick_one(boxed):
    """Sections ▸ «Show all section boxes»: every box of the model on
    screen, the ones that do not cut in grey, and a click on one picks it —
    without the Browser. A way of looking: no undo step, and an exported
    picture leaves the grey ones out."""
    vp = boxed.viewport
    sc = vp.scene
    act = boxed._act_show_all_section_boxes
    assert act in boxed.toolbars["sections"].actions()
    cut = SectionBox(V(0, 0, 0), V(4, 4, 1), name="Planta")
    off = SectionBox(V(-1, -1, -1), V(5, 5, 3), active=False, name="Todo")
    sc.section_boxes[:] = [cut, off]
    sc.version += 1
    assert vp._section_boxes_shown() == [cut]            # only the one
    depth = len(vp.history.undo_stack)
    act.setChecked(True)
    assert vp._section_boxes_shown() == [cut, off]       # the other, grey
    assert vp._section_boxes_shown(show_all=False) == [cut]  # a picture
    assert len(vp.history.undo_stack) == depth
    corner = vp._world_to_pixel(V(5, -1, 3))             # an edge of «Todo»
    edge = vp._world_to_pixel(V(5, 2, 3))
    assert vp.pick_section_box(*edge) is off
    assert corner is not None
    sc.select([off])
    boxed._activate_tool("section_box")                  # edit the grey one
    assert sc.active_section_box() is off and not cut.active
    assert sc.section_boxes == [cut, off]
    boxed._activate_tool("select")
    boxed._sync_section_box_actions()
    assert act.isChecked()                               # the view stays
    boxed._set_section_visibility("show_section_planes", False)
    act.setChecked(False)
    act.setChecked(True)                                 # brings them back
    assert sc.show_section_planes
    act.setChecked(False)
    sc.clear_selection()
    assert vp._section_boxes_shown() == [off]            # the one cutting


def test_the_planes_frames_step_aside_while_a_box_cuts(boxed):
    """While a box cuts, a section plane's frame neither draws nor picks;
    its own cut stays, and one selected in the Browser shows."""
    vp = boxed.viewport
    sc = vp.scene
    plane = SectionPlane(V(2, 0, 0), V(1, 0, 0), name="A", symbol="A",
                         active=True)
    sc.section_planes.append(plane)
    sc.version += 1
    corner = vp.section_plane_frame(plane)[0]
    next_c = vp.section_plane_frame(plane)[1]
    a, b = vp._world_to_pixel(corner), vp._world_to_pixel(next_c)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    assert vp.pick_section_plane(*mid) is plane          # no box: as ever
    assert not vp._box_covers_plane(plane)
    box = _put(sc, SectionBox(V(-9, -9, -9), V(9, 9, 9)))
    assert vp._box_covers_plane(plane)
    assert vp.pick_section_plane(*mid) is None           # the frame is gone
    assert plane in cut_planes(sc)                       # the cut is not
    sc.select([plane])
    assert not vp._box_covers_plane(plane)               # picked: it shows
    sc.clear_selection()
    box.active = False
    assert not vp._box_covers_plane(plane)               # box off: back
    assert vp.pick_section_plane(*mid) is plane


# ---- Round 10: the line where two cuts meet, and one thickness ------------------

def _cut_of(*boxes):
    """Triangles (v0, e1, e2) of closed cubes, as cut_chords takes them."""
    import numpy as np
    from core.mesh import Mesh
    m = Mesh()
    for b in boxes:
        _cube(m, *b)
    tris = []
    for f in m.faces:
        vs = [(v.x(), v.y(), v.z()) for v in f.vertices]
        for k in range(1, len(vs) - 1):
            tris.append((vs[0], vs[k], vs[k + 1]))
    t = np.array(tris, dtype=np.float64)
    return t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]


def test_two_cuts_meet_in_a_line_only_inside_the_material():
    from core.section import cut_chords, plane_pair_line
    box = SectionBox(V(-1, -1, -1), V(2, 2, 3))
    faces = box.faces()
    east, north = faces[1], faces[3]                     # x = 2 and y = 2
    v0, e1, e2 = _cut_of((0, 0, 0, 4, 4, 2))
    chords = cut_chords(v0, e1, e2, east.normal, east.point)
    segs = plane_pair_line(east, north, chords)
    assert len(segs) == 1                                # the solid's height
    low, high = sorted(segs[0].tolist(), key=lambda p: p[2])
    assert low == pytest.approx([2, 2, 0], abs=1e-5)
    assert high == pytest.approx([2, 2, 2], abs=1e-5)
    # Parallel faces never meet; a corner in the air draws nothing.
    assert plane_pair_line(east, faces[0], chords) is None
    far = SectionBox(V(-1, -1, -1), V(2, 9, 3)).faces()[3]
    assert plane_pair_line(east, far, chords) is None
    # Two solids on the line: two stretches, the gap left out.
    v0, e1, e2 = _cut_of((0, 0, 0, 4, 4, 1), (0, 0, 1.5, 4, 4, 2))
    chords = cut_chords(v0, e1, e2, east.normal, east.point)
    assert len(plane_pair_line(east, north, chords)) == 2


def test_a_straight_cut_line_keeps_one_thickness_across_its_chords(boxed):
    """Two chords of one straight line, one much longer than the other, in
    perspective: at the vertex they share, their quads have the same width.
    Each used to take its width at its own middle, and the line stepped."""
    import numpy as np
    vp = boxed.viewport
    vp.camera.perspective = True
    segs = np.array([[[0, 0, 0], [12, 0, 0]],
                     [[12, 0, 0], [13, 0, 0]]], dtype=np.float32)
    tris = vp._cut_line_tris(segs, np.array([0.0, 0.0, 1.0]))
    # q1, q2 of the first quad (its far end); q0, q3 of the second (near):
    # the same width across where they meet.
    first = tris[0, 6:9] - tris[0, 3:6]
    second = tris[3, 6:9] - tris[2, 0:3]
    assert first == pytest.approx(second, abs=1e-4)


def test_the_sheet_inks_the_line_where_two_box_faces_meet():
    import math
    from core.camera import OrbitCamera
    from core.hlr import KIND_CUT, hlr_drawing
    from core.scene import Scene
    sc = Scene()
    _cube(sc.mesh, 0, 0, 0, 4, 4, 2)
    sc.version += 1
    _put(sc, SectionBox(V(-1, -1, -1), V(2, 2, 3)))
    cam = OrbitCamera()
    cam.perspective = False
    cam.yaw, cam.pitch = math.radians(45), math.radians(30)   # both faces
    cam.fit_to(V(-1, -1, -1), V(5, 5, 3))
    d = hlr_drawing(sc, cam)
    corner = [w for w, k in zip(d.world, d.kinds) if k == KIND_CUT
              and all(abs(p[0] - 2) < 1e-5 and abs(p[1] - 2) < 1e-5
                      for p in w)]
    assert corner
    assert sum(abs(w[1][2] - w[0][2]) for w in corner) == pytest.approx(
        2.0, abs=1e-5)


# ---- Round 11: a cut exactly through vertices ----------------------------------

@pytest.mark.parametrize("y", [1.0, 0.1, 3.3])
def test_a_cut_through_the_vertices_keeps_its_lines_and_its_fill(y):
    """A box face level with a corner of the model: the plane goes through
    vertices (and, at 0.1 and 3.3, values a float only comes near). The
    cut's ring must close and fill. Solid A ends exactly on the plane; the
    material of A is on the hidden side, so A's section is what shows."""
    from core.section import cut_chords, fill_triangles
    box = SectionBox(V(-1, y, -1), V(5, 9, 3))
    face = box.faces()[2]                                # y = lo, normal −Y
    v0, e1, e2 = _cut_of((0, y - 1.0, 0, 4, y, 2), (0, y, 0, 4, y + 3.0, 2))
    chords = cut_chords(v0, e1, e2, face.normal, face.point)
    assert chords is not None and len(chords) >= 4
    fill = fill_triangles(chords, face.normal)
    assert fill is not None
    import numpy as np
    a = fill[:, 1].astype(np.float64) - fill[:, 0]
    b = fill[:, 2].astype(np.float64) - fill[:, 0]
    area = 0.5 * np.linalg.norm(np.cross(a, b), axis=1).sum()
    assert area == pytest.approx(8.0, rel=1e-3)          # 4 m by 2 m


def test_a_plane_only_touching_a_solid_cuts_nothing():
    from core.section import cut_chords
    box = SectionBox(V(-1, 2, -1), V(5, 9, 3))           # keeps y > 2
    face = box.faces()[2]
    v0, e1, e2 = _cut_of((0, 2, 0, 4, 4, 2))             # all on the kept side
    assert cut_chords(v0, e1, e2, face.normal, face.point) is None


def test_the_tool_and_the_switch_do_not_share_a_name(boxed):
    from core.i18n import tr
    assert boxed._tools["section_box"].name == "Section Box"
    assert boxed._act_section_box.text() == tr("Cut with a section box")
    assert boxed._act_section_box.text() != tr("Section Box")


# ---- Round 13: one thickness round the whole contour ----------------------------

def _across_px(vp, tris):
    """How wide each quad of ``_cut_line_tris`` is on screen, in pixels."""
    import math
    out = []
    for i in range(0, len(tris), 2):
        q0 = V(*[float(c) for c in tris[i, 0:3]])
        q1 = V(*[float(c) for c in tris[i, 3:6]])
        q3 = V(*[float(c) for c in tris[i + 1, 6:9]])
        a, b, c = (vp._world_to_pixel(q) for q in (q0, q1, q3))
        dx, dy = b[0] - a[0], b[1] - a[1]
        out.append(abs(dx * (c[1] - a[1]) - dy * (c[0] - a[0]))
                   / (math.hypot(dx, dy) or 1.0))
    return out


@pytest.mark.parametrize("perspective", [False, True])
def test_a_cut_line_is_as_thick_on_screen_all_round_its_contour(boxed,
                                                                perspective):
    """A rectangle cut on a plane seen at an angle: the sides that run across
    the view and those that run into it must read the same. Measured in
    the plane, the plane's tilt thinned one pair and not the other."""
    import numpy as np
    vp = boxed.viewport
    vp.camera.perspective = perspective
    # Not on screen here, so nothing has told the camera the window's shape.
    vp.camera.aspect = vp.width() / max(vp.height(), 1)
    segs = np.array([[[0, 0, 0], [4, 0, 0]], [[4, 0, 0], [4, 0, 2]],
                     [[4, 0, 2], [0, 0, 2]], [[0, 0, 2], [0, 0, 0]]],
                    dtype=np.float32)
    tris = vp._cut_line_tris(segs, np.array([0.0, -1.0, 0.0]))
    widths = _across_px(vp, tris)
    assert max(widths) - min(widths) < 0.25, widths
    assert sum(widths) / len(widths) == pytest.approx(2.5, abs=0.4)
