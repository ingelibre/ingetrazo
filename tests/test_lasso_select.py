# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lasso Select: an outline drawn round what to take.

The lasso takes what the rubber-band box would take, by the same rules —
drawn clockwise it is a window (wholly inside), anticlockwise a crossing
(anything it touches) — but along any outline. The tests draw an L: the
notch of the L lies inside the L's bounding box yet outside the L, which
is exactly what no box can leave out.

Headless: a stub viewport projects world (x, y) straight to pixels.
"""
from __future__ import annotations

import sys

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence, QVector3D
from PySide6.QtWidgets import QApplication

from core.geometry import Edge, Face
from core.scene import Scene
from tools.select import (LASSO_MAX_POINTS, LassoRegion, LassoSelectTool,
                          SelectTool, _RectRegion, outline_area,
                          simplify_outline)

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _StubViewport:
    def __init__(self, scene):
        self.scene = scene
        self.hover = "unset"

    def _world_to_pixel(self, v):
        return (v.x(), v.y())

    def set_hover(self, entity):
        self.hover = entity

    def update(self):
        pass


# The L, clockwise on the screen (y grows downwards): the arm along the
# top, 0..10 by 0..4, and the arm down the left, 0..4 by 0..10. The notch
# 4..10 by 4..10 is inside its bounding box, outside the L.
L_CW = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
L_CCW = list(reversed(L_CW))


def _scene():
    s = Scene()
    s.edges.append(Edge(V(1, 1), V(8, 2)))      # 0: in the top arm
    s.edges.append(Edge(V(1, 6), V(2, 9)))      # 1: in the left arm
    s.edges.append(Edge(V(6, 6), V(9, 9)))      # 2: in the notch
    s.edges.append(Edge(V(8, 2), V(2, 8)))      # 3: both ends in, crosses the notch
    s.edges.append(Edge(V(6, 6), V(6, 2)))      # 4: from the notch into the L
    s.edges.append(Edge(V(20, 20), V(30, 30)))  # 5: far away
    s.faces.append(Face([V(1, 1), V(3, 1), V(3, 3), V(1, 3)]))   # 0: in the L
    s.faces.append(Face([V(6, 6), V(9, 6), V(9, 9), V(6, 9)]))   # 1: the notch
    return s


# ---- The outline itself ------------------------------------------------------

def test_clockwise_on_screen_has_positive_area():
    assert outline_area(L_CW) > 0
    assert outline_area(L_CCW) < 0
    assert outline_area(L_CW) == pytest.approx(10 * 4 + 4 * 6)


def test_the_l_holds_its_arms_and_not_its_notch():
    lasso = LassoRegion(L_CW)
    assert not lasso.convex
    assert lasso.contains((2, 2)) and lasso.contains((2, 8))
    assert not lasso.contains((7, 7))           # the notch
    assert not lasso.contains((20, 20))
    assert lasso.contains((0, 5))               # on the outline, as on a box border
    assert lasso.encloses((1, 1), (8, 2))
    assert not lasso.encloses((8, 2), (2, 8))   # both ends in, the middle out
    assert lasso.touches((6, 6), (6, 2))
    assert not lasso.touches((6, 6), (9, 9))


def test_a_lasso_needs_three_corners():
    with pytest.raises(ValueError):
        LassoRegion([(0, 0), (5, 5)])


def test_a_freehand_stroke_is_thinned_to_its_bends():
    # A circle traced one point per pixel of travel: about 630 points.
    ts = np.linspace(0, 2 * np.pi, 630, endpoint=False)
    pts = [(100 + 100 * np.cos(t), 100 + 100 * np.sin(t)) for t in ts]
    out = simplify_outline(pts)
    assert 8 <= len(out) <= LASSO_MAX_POINTS
    # Straight runs collapse to their two ends.
    line = [(float(x), 0.0) for x in range(50)] + [(49.0, 30.0)]
    assert simplify_outline(line) == [(0.0, 0.0), (49.0, 0.0), (49.0, 30.0)]
    # However wiggly the stroke, it never keeps more than the limit.
    rng = np.random.default_rng(3)
    noisy = [tuple(p) for p in rng.uniform(0, 500, (3000, 2))]
    assert len(simplify_outline(noisy)) <= LASSO_MAX_POINTS


def test_the_many_at_once_tests_agree_with_the_one_at_a_time_tests():
    rng = np.random.default_rng(7)
    lasso = LassoRegion(L_CW)
    pts = rng.uniform(-2, 12, (400, 2))
    xs, ys = pts[:, 0], pts[:, 1]
    ok = np.ones(len(xs), dtype=bool)
    mask = lasso.inside_mask(xs, ys, ok)
    assert list(mask) == [lasso.contains((x, y)) for x, y in pts]
    a = rng.uniform(-2, 12, (300, 2))
    b = rng.uniform(-2, 12, (300, 2))
    ok = np.ones(len(a), dtype=bool)
    win = lasso.seg_mask(a[:, 0], a[:, 1], b[:, 0], b[:, 1], ok, False)
    cross = lasso.seg_mask(a[:, 0], a[:, 1], b[:, 0], b[:, 1], ok, True)
    assert list(win) == [lasso.encloses(tuple(p), tuple(q)) for p, q in zip(a, b)]
    assert list(cross) == [lasso.touches(tuple(p), tuple(q)) for p, q in zip(a, b)]


def test_a_rectangular_lasso_takes_what_the_box_takes():
    rng = np.random.default_rng(11)
    rect = (2.0, 3.0, 9.0, 7.0)
    box = _RectRegion(rect)
    lasso = LassoRegion([(2, 3), (9, 3), (9, 7), (2, 7)])
    a = rng.uniform(0, 11, (300, 2))
    b = rng.uniform(0, 11, (300, 2))
    ok = np.ones(len(a), dtype=bool)
    for crossing in (False, True):
        assert (list(box.seg_mask(a[:, 0], a[:, 1], b[:, 0], b[:, 1], ok, crossing))
                == list(lasso.seg_mask(a[:, 0], a[:, 1], b[:, 0], b[:, 1], ok,
                                       crossing)))


# ---- What it selects --------------------------------------------------------

def test_a_clockwise_lasso_takes_only_what_lies_wholly_inside():
    scene = _scene()
    SelectTool().on_lasso_select(_StubViewport(scene), L_CW, crossing=False)
    sel = scene.selection
    assert scene.edges[0] in sel and scene.edges[1] in sel
    assert scene.edges[2] not in sel            # the notch: out
    assert scene.edges[3] not in sel            # runs out across the notch
    assert scene.edges[4] not in sel            # starts in the notch
    assert scene.edges[5] not in sel
    assert scene.faces[0] in sel
    assert scene.faces[1] not in sel


def test_the_box_round_the_same_l_would_take_the_notch_too():
    # What the lasso is for: the box spanning the L cannot leave it out.
    scene = _scene()
    SelectTool().on_box_select(_StubViewport(scene), (0, 0, 10, 10),
                               crossing=False)
    assert scene.edges[2] in scene.selection
    assert scene.faces[1] in scene.selection


def test_an_anticlockwise_lasso_takes_whatever_it_touches():
    scene = _scene()
    SelectTool().on_lasso_select(_StubViewport(scene), L_CCW, crossing=True)
    sel = scene.selection
    assert scene.edges[0] in sel and scene.edges[1] in sel
    assert scene.edges[3] in sel                # its ends are inside
    assert scene.edges[4] in sel                # it reaches into the L
    assert scene.edges[2] not in sel            # wholly in the notch
    assert scene.edges[5] not in sel
    assert scene.faces[0] in sel
    assert scene.faces[1] not in sel


def test_the_lasso_reads_the_selection_modes():
    scene = _scene()
    vp = _StubViewport(scene)
    scene.select([scene.edges[5]])
    SelectTool().on_lasso_select(vp, L_CW, False, True, mode="add")
    assert scene.edges[5] in scene.selection and scene.edges[0] in scene.selection
    SelectTool().on_lasso_select(vp, L_CW, False, True, mode="remove")
    assert scene.edges[0] not in scene.selection
    assert scene.edges[5] in scene.selection


def _group(scene, pts):
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(x, y) for x, y in pts])
    g = Group(m)
    scene.groups.append(g)
    return g


def test_groups_inside_the_l_and_in_its_notch():
    scene = Scene()
    vp = _StubViewport(scene)
    in_arm = _group(scene, [(1, 1), (3, 1), (3, 3), (1, 3)])
    in_notch = _group(scene, [(6, 6), (9, 6), (9, 9), (6, 9)])
    # Its corners all in the arms; its sides cut across the notch.
    bridging = _group(scene, [(1, 6), (8, 1), (9, 2), (2, 9)])
    SelectTool().on_lasso_select(vp, L_CW, crossing=False)
    assert in_arm in scene.selection
    assert in_notch not in scene.selection
    assert bridging not in scene.selection
    SelectTool().on_lasso_select(vp, L_CCW, crossing=True)
    assert in_arm in scene.selection and bridging in scene.selection
    assert in_notch not in scene.selection


def test_guides_dimensions_and_points_go_by_the_same_rules():
    from core.guide import Guide
    scene = Scene()
    vp = _StubViewport(scene)
    line = Guide(V(2, 2), V(1, 0, 0))
    point_in = Guide(V(2, 8))
    point_notch = Guide(V(7, 7))
    scene.guides += [line, point_in, point_notch]
    SelectTool().on_lasso_select(vp, L_CW, crossing=False)
    assert line not in scene.selection          # a line is never enclosed
    assert point_in in scene.selection
    assert point_notch not in scene.selection
    SelectTool().on_lasso_select(vp, L_CCW, crossing=True)
    assert line in scene.selection


# ---- The tool: drawing the outline -----------------------------------------

def _drag(tool, vp, pts):
    tool.on_screen_press(vp, QPointF(*pts[0]))
    for p in pts[1:]:
        tool.on_screen_drag(vp, QPointF(*p))
    tool.on_screen_release(vp, QPointF(*pts[-1]))


def _stroke(corners, step=1.0):
    """A hand-drawn trace through ``corners``, a point every ``step`` px."""
    out = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        n = max(1, int(max(abs(bx - ax), abs(by - ay)) / step))
        out += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n)]
    return out + [corners[0]]


def _tool_scene(scale=10.0):
    """The L scene ten times bigger, so a drag is a drag."""
    s = Scene()
    s.edges.append(Edge(V(10, 10), V(80, 20)))     # top arm
    s.edges.append(Edge(V(60, 60), V(90, 90)))     # notch
    return s


L_BIG = [(x * 10.0, y * 10.0) for x, y in L_CW]


def test_one_drag_clockwise_is_a_window_lasso():
    scene = _tool_scene()
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    tool.on_activate(vp)
    _drag(tool, vp, _stroke(L_BIG))
    assert scene.edges[0] in scene.selection
    assert scene.edges[1] not in scene.selection
    assert tool.nodes == [] and tool.outline() == []


def test_one_drag_anticlockwise_is_a_crossing_lasso():
    scene = Scene()
    reach = Edge(V(60, 60), V(60, 20))             # from the notch into the arm
    scene.edges.append(reach)
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    _drag(tool, vp, _stroke(list(reversed(L_BIG))))
    assert reach in scene.selection


def test_clicked_corners_close_with_enter():
    scene = _tool_scene()
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    for p in L_BIG:
        _drag(tool, vp, [p])                       # press and release in place
    assert len(tool.nodes) == len(L_BIG)
    assert scene.selection == set() or not scene.selection
    assert tool.on_key(vp, Qt.Key_Return, Qt.NoModifier) is True
    assert scene.edges[0] in scene.selection
    assert scene.edges[1] not in scene.selection
    assert tool.nodes == []


def test_a_click_on_the_first_corner_closes_it():
    scene = _tool_scene()
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    for p in L_BIG:
        _drag(tool, vp, [p])
    first = L_BIG[0]
    _drag(tool, vp, [(first[0] + 3, first[1] + 2)])
    assert tool.nodes == []
    assert scene.edges[0] in scene.selection


def test_backspace_takes_back_a_corner_and_esc_drops_the_outline():
    scene = _tool_scene()
    scene.select([scene.edges[1]])
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    for p in L_BIG[:3]:
        _drag(tool, vp, [p])
    assert tool.on_key(vp, Qt.Key_Backspace, Qt.NoModifier) is True
    assert len(tool.nodes) == 2
    # Backspace took a corner, not the selection.
    assert scene.edges[1] in scene.selection
    tool.on_cancel(vp)
    assert tool.nodes == [] and tool.outline() == []
    assert scene.edges[1] in scene.selection


def test_esc_cascade_sees_the_lasso_as_an_operation():
    from views.viewport.interaction import InteractionMixin as M
    tool = LassoSelectTool()
    busy = getattr(M, "_tool_busy")
    assert busy(tool) is False
    tool.nodes.append((1.0, 1.0))
    assert busy(tool) is True


def test_a_drag_between_corners_draws_that_stretch_freehand():
    scene = _tool_scene()
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    _drag(tool, vp, [L_BIG[0]])
    _drag(tool, vp, [L_BIG[0], (50.0, 0.0), L_BIG[1]])   # a dragged side
    assert len(tool.nodes) >= 3
    for p in L_BIG[2:]:
        _drag(tool, vp, [p])
    tool.on_key(vp, Qt.Key_Enter, Qt.NoModifier)
    assert scene.edges[0] in scene.selection


def test_a_tiny_outline_selects_nothing_and_keeps_the_selection():
    scene = _tool_scene()
    scene.select([scene.edges[1]])
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    for p in [(10, 10), (11, 10), (12, 10)]:       # a line, no area
        _drag(tool, vp, [p])
    assert tool.finish(vp, Qt.NoModifier) is False
    assert scene.selection == {scene.edges[1]}


def test_modifiers_at_the_close_join_the_catch():
    scene = _tool_scene()
    scene.select([scene.edges[1]])
    vp = _StubViewport(scene)
    tool = LassoSelectTool()
    for p in L_BIG:
        _drag(tool, vp, [p])
    tool.finish(vp, Qt.ControlModifier)
    assert scene.edges[0] in scene.selection
    assert scene.edges[1] in scene.selection       # kept: Ctrl adds


def test_hover_highlights_nothing():
    class _Ctx:
        pass
    vp = _StubViewport(Scene())
    ctx = _Ctx()
    ctx.viewport = vp
    LassoSelectTool().on_hover(ctx)
    assert vp.hover is None


def test_the_overlay_draws_the_outline_in_the_box_colours():
    from PySide6.QtGui import QImage, QPainter
    vp = _StubViewport(Scene())
    tool = LassoSelectTool()
    for p in L_BIG:
        _drag(tool, vp, [p])
    img = QImage(120, 120, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    tool.draw_overlay(vp, painter)
    painter.end()
    # The top side, solid blue: a window outline.
    c = img.pixelColor(50, 0)
    assert c.alpha() > 0 and c.blue() > c.red()


# ---- In the window ---------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_the_lasso_sits_beside_select(win):
    act = win._tool_actions["lasso"]
    assert act.shortcut() == QKeySequence("Shift+Space")
    assert act in win.toolbars["main"].actions()
    acts = win.toolbars["main"].actions()
    assert acts.index(act) == acts.index(win._tool_actions["select"]) + 1
    win._activate_tool("lasso")
    assert isinstance(win.viewport.active_tool, LassoSelectTool)


def test_nobody_else_has_shift_space(win):
    key = QKeySequence("Shift+Space")
    others = [a.text() for a in win.findChildren(QAction)
              if a is not win._tool_actions["lasso"] and key in a.shortcuts()]
    assert others == []


def test_the_status_bar_says_how_to_close_it():
    from views.status_hints import hint_for
    tool = LassoSelectTool()
    idle = hint_for("lasso", tool)
    tool.nodes.append((1.0, 1.0))
    started = hint_for("lasso", tool)
    assert idle and started and idle != started


def test_the_lasso_has_its_own_icon():
    from views.icons import tool_icon
    assert not tool_icon("lasso").isNull()
