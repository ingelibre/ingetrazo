# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Scale tool's grip box, against the classic documented behaviour: 26
grips on a 3D selection (8 corners scale uniformly, 12 edge midpoints scale
two axes, 6 face centres scale one), 8 on a flat one; the anchor is the
opposite side or — About Center — the middle; typed values read as factors,
per-axis factors, absolute sizes with a unit, and negatives mirror."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History, ScaleVerticesCommand
from core.scene import Scene
from tools.scale import ScaleTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Stub:
    """Vista mínima: escena + historial + los callbacks que el tool toca."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashed = []

    def flash_status(self, msg, *a):
        self.flashed.append(msg)

    def update(self):
        pass


def _tool_with_box(w=4.0, d=3.0, h=2.0):
    """A selected box face-set spanning w×d×h and the tool boxed around it."""
    scene = Scene()
    vp = _Stub(scene)
    f1 = scene.mesh.add_face([V(0, 0, 0), V(w, 0, 0), V(w, d, 0), V(0, d, 0)])
    f2 = scene.mesh.add_face([V(0, 0, h), V(w, 0, h), V(w, d, h), V(0, d, h)])
    scene.selection.update([f1, f2])
    tool = ScaleTool()
    tool.on_activate(vp)
    return tool, vp


# ---- Grips ------------------------------------------------------------------
def test_a_3d_selection_gets_the_classic_26_grips():
    tool, _ = _tool_with_box()
    kinds = {}
    for g in tool._grips:
        kinds[g.kind(3)] = kinds.get(g.kind(3), 0) + 1
    assert len(tool._grips) == 26
    assert kinds == {"corner": 8, "edge": 12, "face": 6}


def test_a_flat_selection_gets_the_2d_box_of_8_grips():
    scene = Scene()
    vp = _Stub(scene)
    f = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 3), V(0, 3)])
    scene.selection.add(f)
    tool = ScaleTool()
    tool.on_activate(vp)
    assert len(tool._grips) == 8
    kinds = [g.kind(2) for g in tool._grips]
    assert kinds.count("corner") == 4        # uniform in the plane
    assert kinds.count("face") == 4          # one axis each


def test_a_single_edge_gets_two_end_grips():
    scene = Scene()
    vp = _Stub(scene)
    e = scene.mesh.add_edge(V(0, 0), V(5, 0))
    scene.selection.add(e)
    tool = ScaleTool()
    tool.on_activate(vp)
    assert len(tool._grips) == 2
    assert all(g.mask == (0,) for g in tool._grips)


def test_face_grips_scale_one_axis_edge_grips_two_corner_grips_all():
    tool, _ = _tool_with_box()
    for g in tool._grips:
        halves = sum(1 for t in g.params if t == 0.5)
        assert len(g.mask) == 3 - halves     # official mapping


# ---- Anchors ----------------------------------------------------------------
def test_the_anchor_is_the_opposite_side():
    tool, _ = _tool_with_box(4, 3, 2)
    corner = next(g for g in tool._grips if g.params == (1.0, 1.0, 1.0))
    a = tool._anchor_for(corner)
    assert (a.x(), a.y(), a.z()) == (0.0, 0.0, 0.0)
    face = next(g for g in tool._grips if g.params == (1.0, 0.5, 0.5))
    a = tool._anchor_for(face)
    assert (a.x(), a.y(), a.z()) == (0.0, 1.5, 1.0)   # opposite face centre


def test_about_center_moveses_the_anchor_to_the_middle():
    tool, _ = _tool_with_box(4, 3, 2)
    tool.about_center = True
    corner = next(g for g in tool._grips if g.params == (1.0, 1.0, 1.0))
    a = tool._anchor_for(corner)
    assert (a.x(), a.y(), a.z()) == (2.0, 1.5, 1.0)


# ---- Typed values (the Measurements box) ------------------------------------
def _armed_tool():
    tool, vp = _tool_with_box(4, 3, 2)
    grip = next(g for g in tool._grips if g.params == (1.0, 0.5, 0.5))
    tool._grip = grip                        # Red-axis face grip
    tool._anchor = tool._anchor_for(grip)
    return tool, vp


def test_a_plain_number_is_a_factor_on_the_grips_axes():
    tool, _ = _armed_tool()
    assert tool._typed_factors(2.0, absolute=False) == (2.0, 1.0, 1.0)


def test_a_number_with_units_is_the_new_absolute_size():
    tool, _ = _armed_tool()                  # red extent = 4 m
    assert tool._typed_factors(2.0, absolute=True) == (0.5, 1.0, 1.0)


def test_a_negative_factor_mirrors():
    tool, _ = _armed_tool()
    assert tool._typed_factors(-1.0, absolute=False) == (-1.0, 1.0, 1.0)


def test_zero_flattens_one_axis_but_never_all_of_them():
    """A 0 on a face grip flattens that axis (#688); on every axis at once
    it is still refused, as is anything else under 0.0001."""
    tool, _ = _armed_tool()
    assert tool._typed_factors(0.0, absolute=False) == (0.0, 1.0, 1.0)
    assert tool._typed_factors(0.00001, absolute=False) is None
    tool.uniform = True
    assert tool._typed_factors(0.0, absolute=False) is None


def test_per_axis_factors_on_an_edge_grip():
    tool, vp = _tool_with_box(4, 3, 2)
    grip = next(g for g in tool._grips if g.params == (1.0, 1.0, 0.5))
    tool._grip = grip                        # Red, Green edge grip
    tool._anchor = tool._anchor_for(grip)
    assert tool._typed_factors((2.0, 3.0), absolute=False) == (2.0, 3.0, 1.0)
    # Absolute pair: 8 m on red (=×2 of 4), 6 m on green (=×2 of 3).
    assert tool._typed_factors((8.0, 6.0), absolute=True) == (2.0, 2.0, 1.0)
    # Arity mismatch is refused, not guessed.
    assert tool._typed_factors((2.0, 3.0, 4.0), absolute=False) is None


def test_uniform_toggle_makes_any_grip_proportional():
    tool, _ = _armed_tool()
    tool.uniform = True
    assert tool._typed_factors(2.0, absolute=False) == (2.0, 2.0, 2.0)


# ---- The scale itself -------------------------------------------------------
def test_committed_scale_is_per_axis_and_undoable():
    scene = Scene()
    hist = History(scene)
    f = scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 3), V(0, 3)])
    hist.execute(ScaleVerticesCommand(
        [V(0, 0), V(4, 0), V(4, 3), V(0, 3)], V(0, 0), (2.0, 0.5, 1.0)))
    xs = sorted(round(v.x(), 6) for v in f.vertices)
    ys = sorted(round(v.y(), 6) for v in f.vertices)
    assert xs == [0.0, 0.0, 8.0, 8.0]
    assert ys == [0.0, 0.0, 1.5, 1.5]
    hist.undo()
    assert sorted(round(v.x(), 6) for v in f.vertices) == [0, 0, 4, 4]


def test_dragging_a_face_grip_live_then_cancel_restores_geometry():
    tool, vp = _tool_with_box(4, 3, 2)
    grip = next(g for g in tool._grips if g.params == (1.0, 0.5, 0.5))
    tool._grab(vp, grip, (0.0, 0.0))
    tool._apply_preview(vp, (2.0, 1.0, 1.0))
    assert max(v.position.x() for v in vp.scene.mesh.vertices) == 8.0
    tool.on_cancel(vp)
    assert max(v.position.x() for v in vp.scene.mesh.vertices) == 4.0
    assert not vp.history.undo_stack          # nothing landed on the history


def test_mirror_by_preview_through_the_anchor():
    tool, vp = _tool_with_box(4, 3, 2)
    grip = next(g for g in tool._grips if g.params == (1.0, 0.5, 0.5))
    tool._grab(vp, grip, (0.0, 0.0))
    tool._apply_preview(vp, (-1.0, 1.0, 1.0))
    assert min(v.position.x() for v in vp.scene.mesh.vertices) == -4.0
    tool.on_cancel(vp)
    assert min(v.position.x() for v in vp.scene.mesh.vertices) == 0.0


def test_scaling_a_selection_with_an_image_carries_it_undistorted():
    from core.image_plane import ImagePlane

    scene = Scene()
    vp = _Stub(scene)
    im = ImagePlane("s.png", V(0, 0), V(4, 0), V(0, 3), aspect=0.75)
    scene.image_planes.append(im)
    scene.selection.add(im)
    tool = ScaleTool()
    tool.on_activate(vp)
    assert len(tool._grips) == 8              # a flat image = the 2D box
    corner = next(g for g in tool._grips if len(g.mask) == 2)
    tool._grab(vp, corner, (0.0, 0.0))
    tool._commit(vp, (2.0, 2.0, 1.0))
    assert (im.width(), im.height()) == (8.0, 6.0)
    vp.history.undo()
    assert (im.width(), im.height()) == (4.0, 3.0)


def test_hot_retype_redoes_the_last_scale_at_the_new_factor():
    tool, vp = _tool_with_box(4, 3, 2)
    grip = next(g for g in tool._grips if g.params == (1.0, 0.5, 0.5))
    tool._grab(vp, grip, (0.0, 0.0))
    tool._commit(vp, (2.0, 1.0, 1.0))
    assert max(v.position.x() for v in vp.scene.mesh.vertices) == 8.0
    assert tool.on_value(vp, 3.0) is True     # retype: ×3 instead of ×2
    assert max(v.position.x() for v in vp.scene.mesh.vertices) == 12.0
    assert len(vp.history.undo_stack) == 1    # still ONE undoable step


# ---- Captions ---------------------------------------------------------------
def test_vcb_captions_follow_the_axes():
    tool, _ = _tool_with_box()
    assert tool.vcb_caption() == "Scale"
    tool._grip = next(g for g in tool._grips if g.params == (1.0, 0.5, 0.5))
    assert tool.vcb_caption() == "Red Scale"
    tool._grip = next(g for g in tool._grips if g.params == (1.0, 1.0, 0.5))
    assert tool.vcb_caption() == "Red, Green Scale"
    tool._grip = next(g for g in tool._grips if g.params == (1.0, 1.0, 1.0))
    assert tool.vcb_caption() == "Scale"      # corners scale uniformly


def test_a_long_drag_down_and_back_scales_every_vertex():
    """A user's video (25-09): a rounded box scaled by dragging a corner
    down near 0.04 and back, over and over, came out torn on release. The
    preview chained relative steps in float32; undoing them left some
    vertices a hair off the cell the commit looks them up by, so those were
    never scaled. The preview now always starts from the originals."""
    import random
    scene = Scene()
    vp = _Stub(scene)
    # a fine strip of faces, away from the origin, like a fillet
    faces = []
    for i in range(30):
        x0 = 3.1234 + i * 0.0137
        faces.append(scene.mesh.add_face([
            V(x0, 1.777, 0.7), V(x0 + 0.0137, 1.777, 0.7),
            V(x0 + 0.0137, 1.9, 0.9), V(x0, 1.9, 0.9)]))
    scene.selection.update(faces)
    tool = ScaleTool()
    tool.on_activate(vp)
    grip = max(tool._grips, key=lambda g: g.params)          # a corner
    before = {id(v): QVector3D(v.position) for v in scene.mesh.vertices}
    anchor = None
    tool._grab(vp, grip, (0.0, 0.0))
    anchor = QVector3D(tool._anchor)
    rnd = random.Random(1)
    for _ in range(300):
        f = rnd.choice([0.04, 0.09, 0.2, 0.56, 0.93, 1.11, 1.2, 0.15])
        tool._apply_preview(vp, (f, f, f))
    tool._apply_preview(vp, (0.5, 0.5, 0.5))
    tool._commit(vp, (0.5, 0.5, 0.5))
    for v in scene.mesh.vertices:
        want = anchor + (before[id(v)] - anchor) * 0.5
        assert (v.position - want).length() < 1e-5
    assert len(scene.mesh.vertices) == len(before)
