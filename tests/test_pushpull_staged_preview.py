# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull's staged preview (#434): an attached, non-prism push shows the
REAL result mid-drag — the commit applied once to the model, then its cap
stretched — so the walls a split face shares merge and shorten live, as the
commit will leave them.

The property every test leans on: after any preview frame the model equals a
fresh model where the same face was committed directly at that distance. The
comparison is deliberately strong — face cycles with holes, the edge set, soft
flags and interior marks — because the bug was exactly a preview whose faces
looked right while its edges did not.

The cost side: a release inside the held interval commits the stage itself
(no second pipeline run), one stage per side of the base plane is parked for
the way back, and a slow model stages once per drag.

Headless: stub viewport + direct tool calls, as tests/test_pushpull_ux.py.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.scene import Scene
from tests.test_pushpull_ux import V, _ctx, _cube, _push, _StubViewport
from tools.base import ToolContext
from tools.pushpull import PushPullTool


# ---- Canonical model ---------------------------------------------------------

def _canon(scene, dec=5):
    """Faces as rotation-normalised position cycles (holes included, winding
    kept) with their interior mark; edges as position pairs with their soft
    flag. Rounded to ``dec`` decimals; -0.0 folded into 0.0."""
    def rp(p):
        return tuple(round(c, dec) + 0.0 for c in (p.x(), p.y(), p.z()))

    def cyc(loop):
        pts = [rp(p) for p in loop]
        i = pts.index(min(pts))
        return tuple(pts[i:] + pts[:i])

    faces = sorted((cyc(f.vertices), tuple(sorted(cyc(h) for h in f.holes)),
                    f.interior) for f in scene.faces)
    edges = sorted((tuple(sorted((rp(e.a), rp(e.b)))), e.soft)
                   for e in scene.mesh.edges)
    return faces, edges


# ---- Fixtures: (scene, face to push) builders --------------------------------

def _on_plane(f, axis, value, tol=1e-6):
    return all(abs(getattr(p, axis)() - value) < tol for p in f.vertices)


def _box(scene, hist, footprint, height):
    hist.execute(build_add_edges(
        scene, [(footprint[i], footprint[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(footprint))]))
    _push(scene, scene.faces[-1], height)


def _draw(scene, hist, segments):
    hist.execute(build_add_edges(scene, segments))


def _split_top():
    """A 4×4×3 cube whose top is split by a line at x=2; the x≤2 half."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=4.0, height=3.0)
    _draw(scene, hist, [(V(2, 0, 3), V(2, 4, 3))])
    half = next(f for f in scene.faces if _on_plane(f, "z", 3.0)
                and max(p.x() for p in f.vertices) <= 2.0 + 1e-6)
    return scene, half


def _split_top_stepped():
    """The split top with the far quarter of its x≥2 half already raised by
    1: the x≤2 half's chord backs half onto the low quarter, half onto the
    raised quarter's riser (a T-junction), and pulling it crosses that
    quarter's top."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=4.0, height=3.0)
    _draw(scene, hist, [(V(2, 0, 3), V(2, 4, 3))])
    _draw(scene, hist, [(V(2, 2, 3), V(4, 2, 3))])
    quarter = next(f for f in scene.faces if _on_plane(f, "z", 3.0)
                   and min(p.x() for p in f.vertices) >= 2.0 - 1e-6
                   and min(p.y() for p in f.vertices) >= 2.0 - 1e-6)
    _push(scene, quarter, 1.0)
    half = next(f for f in scene.faces if _on_plane(f, "z", 3.0)
                and max(p.x() for p in f.vertices) <= 2.0 + 1e-6)
    return scene, half


def _ring_top():
    """A cube with a rectangle drawn on its top: the holed ring around it."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=4.0, height=3.0)
    inner = [V(1, 1, 3), V(3, 1, 3), V(3, 3, 3), V(1, 3, 3)]
    _draw(scene, hist, [(inner[i], inner[(i + 1) % 4]) for i in range(4)])
    return scene, next(f for f in scene.faces if f.holes)


def _inner_panel():
    """The same drawing, the inner rectangle pushed instead of the ring."""
    scene, _ring = _ring_top()
    panel = next(f for f in scene.faces if _on_plane(f, "z", 3.0)
                 and not f.holes and abs(f.area() - 4.0) < 1e-6)
    return scene, panel


def _window():
    """A 0.3 m thick wall with a window rectangle drawn on its front."""
    scene = Scene()
    hist = History(scene)
    _box(scene, hist, [V(0, 0), V(4, 0), V(4, 0.3), V(0, 0.3)], 3.0)
    w = [V(1, 0, 1), V(3, 0, 1), V(3, 0, 2), V(1, 0, 2)]
    _draw(scene, hist, [(w[i], w[(i + 1) % 4]) for i in range(4)])
    pane = next(f for f in scene.faces if _on_plane(f, "y", 0.0)
                and not f.holes)
    return scene, pane


def _ramp_notch_top():
    """A 4×4×3 cube whose x≥2, y≥2 top quarter is a ramp rising from z=1 at
    y=2 to the top at y=4, the rest of the top split at y=2; the x≤2, y≥2
    piece. Pushed down, its rim on the cheek x=2 crosses the ramp's edge:
    that corner runs down the ramp, not straight down."""
    scene = Scene()
    hist = History(scene)
    faces = [
        [V(0, 0, 0), V(0, 4, 0), V(4, 4, 0), V(4, 0, 0)],                # bottom
        [V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)],                # front
        [V(0, 0, 0), V(0, 0, 3), V(0, 4, 3), V(0, 4, 0)],                # left
        [V(0, 4, 0), V(0, 4, 3), V(2, 4, 3), V(4, 4, 3), V(4, 4, 0)],    # back
        [V(4, 0, 0), V(4, 4, 0), V(4, 4, 3), V(4, 2, 1), V(4, 2, 3),
         V(4, 0, 3)],                                                    # right
        [V(0, 0, 3), V(4, 0, 3), V(4, 2, 3), V(2, 2, 3), V(2, 4, 3),
         V(0, 4, 3)],                                                    # top L
        [V(2, 2, 3), V(2, 2, 1), V(4, 2, 1), V(4, 2, 3)],                # step
        [V(2, 2, 1), V(2, 2, 3), V(2, 4, 3)],                            # cheek
        [V(2, 2, 1), V(2, 4, 3), V(4, 4, 3), V(4, 2, 1)],                # ramp
    ]
    segs = {tuple(sorted(((a.x(), a.y(), a.z()), (b.x(), b.y(), b.z()))))
            for f in faces for a, b in zip(f, f[1:] + f[:1])}
    hist.execute(build_add_edges(
        scene, [(V(*a), V(*b)) for a, b in sorted(segs)], detect_faces=False,
        extra=[AddFaceCommand(f) for f in faces]))
    _draw(scene, hist, [(V(0, 2, 3), V(2, 2, 3))])
    return scene, next(f for f in scene.faces if _on_plane(f, "z", 3.0)
                       and min(p.y() for p in f.vertices) >= 2.0 - 1e-6)


_ROT = math.radians(30.0)


def _far(x, y, z=0.0):
    """A point of a wall rotated 30° about Z and standing ~140 m from the
    origin, where float32 positions are off by up to ~1e-5."""
    c, s = math.cos(_ROT), math.sin(_ROT)
    return V(100.0 + c * x - s * y, 100.0 + s * x + c * y, z)


def _far_wall():
    """That wall, its top split across the thickness; the half at x≤2."""
    scene = Scene()
    hist = History(scene)
    _box(scene, hist, [_far(0, 0), _far(4, 0), _far(4, 0.3), _far(0, 0.3)],
         3.0)
    _draw(scene, hist, [(_far(2, 0, 3), _far(2, 0.3, 3))])
    tops = [f for f in scene.faces if _on_plane(f, "z", 3.0, 1e-4)]
    half = min(tops, key=lambda f: sum((p - _far(0, 0, 3)).length()
                                       for p in f.vertices))
    return scene, half


# ---- Drivers -----------------------------------------------------------------

def _start(build, viewport_cls=_StubViewport):
    """Build the fixture and start a drag on its face the way a click does
    (orientation, normal, classification, limits)."""
    scene, face = build()
    vp = viewport_cls(scene)
    tool = PushPullTool()
    # Slow mode is tested on purpose below; a slow CI box must not trip it.
    tool._SLOW_STAGE_S = math.inf
    tool.hovered_face = face
    tool.on_click(_ctx(vp))
    assert tool.dragging and tool._attached and not tool._prism_cap
    return scene, vp, tool


def _frame(tool, vp, d):
    tool.extrusion = d
    tool._clamp_extrusion(vp)
    tool._show_staged_preview(vp)


def _direct(build, d, keep_base=False):
    """A fresh fixture with the same face committed at ``d``, no preview."""
    scene, vp, tool = _start(build)
    tool._keep_base = keep_base
    tool.extrusion = d
    tool._clamp_extrusion(vp)
    tool._commit(vp)
    return scene


def _assert_frames_match(build, dists, dec=5):
    scene, vp, tool = _start(build)
    for d in dists:
        _frame(tool, vp, d)
        assert tool._stage_d is not None, f"no stage at {d}"
        assert tool.preview_faces() == [], "the overlay is not the preview here"
        assert _canon(scene, dec) == _canon(_direct(build, d), dec), (
            f"the preview at {d} differs from the commit")
    return scene, vp, tool


# ---- Preview == commit -------------------------------------------------------

def test_half_top_pull_previews_the_committed_shape():
    # The bug (#434): the raised half's riser and the merged side walls only
    # appeared on release; the old chord stayed drawn across the walls.
    scene, _vp, tool = _assert_frames_match(_split_top, [0.5, 1.2, 0.8])
    # One stage for the whole outward drag: the rest were stretches.
    assert tool._stage_d == 0.5 and len(tool._stage_verts) == 4
    chord = [e for e in scene.mesh.edges
             if abs(e.a.x() - 2) < 1e-6 and abs(e.b.x() - 2) < 1e-6
             and abs(e.a.z() - 3) < 1e-6 and abs(e.b.z() - 3) < 1e-6]
    assert len(chord) == 1 and len(chord[0].faces) == 2   # riser + low half


def test_half_top_push_previews_the_committed_shape():
    _assert_frames_match(_split_top, [-0.5, -1.5, -1.0])


def test_direction_reversal_restages_and_still_matches():
    _scene, _vp, tool = _assert_frames_match(_split_top, [0.6, -0.6, 0.9])
    # The first reversal staged the other side; the way back restored the
    # parked outward stage and stretched it.
    assert tool._stage_d == 0.6 and set(tool._stage_cache) == {1.0, -1.0}


def test_crossing_a_neighbours_level_restages_and_still_matches():
    # The raised neighbour's top corner is an event level of the dragged
    # walls: below it the walls notch, above it the riser takes over.
    _assert_frames_match(_split_top_stepped, [0.5, 0.8, 1.0, 1.5, 0.7])


def test_ring_pushed_to_the_clamp_then_dragged_back():
    scene, vp, tool = _start(_ring_top)
    assert tool._limit_in is not None
    for d in [-0.5, -9.0, -1.0, 0.5, 1.5]:
        _frame(tool, vp, d)
        assert tool._stage_d is not None
        assert _canon(scene) == _canon(_direct(_ring_top, d)), d


def test_inner_panel_frames_match():
    _assert_frames_match(_inner_panel, [-0.5, -1.5, 0.7, -3.0, -2.0])


def test_window_through_hole_frames_match():
    # Blind recess, through (the pane gone, a tunnel), deeper still (the
    # punch does not depend on the distance), back to a recess.
    _scene, _vp, tool = _assert_frames_match(_window, [-0.1, -0.5, -4.5, -1.0,
                                                       -0.2])
    assert tool._stage_d == -0.2


def test_rotated_wall_far_from_origin_finds_its_movers():
    # A 1e-6 cap-plane test selected no movers out here and froze the drag.
    scene, vp, tool = _start(_far_wall)
    for d in [0.5, 1.2, -0.5, -1.5]:
        _frame(tool, vp, d)
        assert tool._stage_verts, f"no moving vertices at {d}"
        assert _canon(scene, 4) == _canon(_direct(_far_wall, d), 4), d


# ---- Restore and commit ------------------------------------------------------

def test_esc_after_a_staged_drag_restores_the_model_exactly():
    scene, vp, tool = _start(_split_top)
    half = tool.base_face
    scene.selection.add(half)                  # a preselected base face
    # An interior mark the push's orientation pass recomputes: the restore
    # must bring the flag back too, not just the topology.
    bottom = next(f for f in scene.faces if _on_plane(f, "z", 0.0))
    bottom.interior = True
    before = _canon(scene)
    undo_depth = len(vp.history.undo_stack)

    for d in [0.7, -1.2, 1.4]:
        _frame(tool, vp, d)
    assert _canon(scene) != before
    assert bottom in scene.faces and bottom.interior is False  # re-marked
    tool.on_cancel(vp)

    assert _canon(scene) == before
    assert bottom.interior is True
    assert half in scene.faces and half in scene.selection
    assert len(vp.history.undo_stack) == undo_depth
    assert tool._preview_snapshot is None and not tool.dragging


def test_commit_after_a_staged_drag_equals_a_direct_commit():
    scene, vp, tool = _start(_split_top)
    for d in [0.4, -0.9, 1.1]:
        _frame(tool, vp, d)
    tool._commit(vp)
    assert _canon(scene) == _canon(_direct(_split_top, 1.1))
    # One undo step, back to the clean split cube.
    assert vp.history.undo() is True
    assert _canon(scene) == _canon(_split_top()[0])


def test_staged_drag_through_on_hover_matches_the_commit():
    """End to end through on_hover: the dispatch picks the staged preview
    for a split half, and the inference/revert steps leave it alone."""

    class _TopView(_StubViewport):
        # Front view: screen x = world x, screen y = -world z (10 px/m).
        snap_threshold_px = 9.0
        _hover_edge = None

        def _world_to_pixel(self, w):
            return (w.x() * 10.0, -w.z() * 10.0)

        def _project_to_lock_line(self, start, direction, px, py):
            cursor = QVector3D(px / 10.0, start.y(), -py / 10.0)
            dn = direction.normalized()
            return start + dn * QVector3D.dotProduct(cursor - start, dn)

    scene, vp, tool = _start(_split_top, _TopView)
    for z in [3.6, 4.5, 2.2]:
        tool.on_hover(ToolContext(viewport=vp, world=QVector3D(),
                                  screen=QPointF(10.0, -z * 10.0),
                                  modifiers=Qt.NoModifier, snap=None))
        assert tool._stage_d is not None
        assert abs(tool.extrusion - (z - 3.0)) < 1e-5
        assert _canon(scene) == _canon(_direct(_split_top, tool.extrusion))


def test_near_zero_shows_the_clean_model(monkeypatch):
    scene, vp, tool = _start(_split_top)
    before = _canon(scene)
    _frame(tool, vp, 0.8)
    _frame(tool, vp, 1e-5)
    assert _canon(scene) == before and tool._stage_d is None
    # Parked on the way through, not dropped: coming back needs no pipeline.
    monkeypatch.setattr(tool, "_mutate", None)       # would raise if called
    _frame(tool, vp, 0.9)
    assert tool._stage_d == 0.8
    assert _canon(scene) == _canon(_direct(_split_top, 0.9))


# ---- Failures fall back to the overlay ---------------------------------------

def test_a_pipeline_error_while_staging_falls_back_to_the_overlay(monkeypatch):
    scene, vp, tool = _start(_split_top)
    before = _canon(scene)

    def boom(*_a, **_k):
        raise ValueError("degenerate edge")

    monkeypatch.setattr(tool, "_mutate_inner", boom)
    _frame(tool, vp, 0.8)                      # must not raise

    assert _canon(scene) == before             # the clean model is back
    assert tool._stage_d is None
    assert tool.preview_faces(), "the overlay should take over"
    assert tool._stage_refusal == (1.0, 0.8)


def _spy_mutate(monkeypatch, tool, refuse=lambda d: False):
    """Count the pipeline runs (``_mutate``) of ``tool``, refusing the
    distances ``refuse`` says, the way the guard would."""
    real = tool._mutate
    calls = []

    def spy(scene_, preview=False):
        calls.append(tool.extrusion)
        real(scene_)
        if refuse(tool.extrusion):
            tool._refused = True

    monkeypatch.setattr(tool, "_mutate", spy)
    return calls


def test_a_refused_direction_runs_the_pipeline_once_not_per_frame(monkeypatch):
    scene, vp, tool = _start(_split_top)
    before = _canon(scene)
    calls = _spy_mutate(monkeypatch, tool, refuse=lambda d: d < 0)
    for d in [-0.5, -0.8, -0.9, -0.6]:
        _frame(tool, vp, d)
        assert tool.preview_faces()            # the overlay
        assert _canon(scene) == before
    assert len(calls) == 1
    # Twice as far: one retry, refused again; the bar moves with it.
    _frame(tool, vp, -1.1)
    _frame(tool, vp, -2.0)
    assert len(calls) == 2 and tool._stage_refusal == (-1.0, 1.1)

    _frame(tool, vp, 0.5)                      # the sign flipped: try again
    assert len(calls) == 3 and tool._stage_d == 0.5
    assert tool._stage_refusal is None


def test_a_tiny_refused_first_frame_does_not_cost_the_direction(monkeypatch):
    # A first frame barely past the minimum, refused (float noise): the
    # rest of the pull must still preview the real result, not the overlay.
    scene, vp, tool = _start(_split_top)
    calls = _spy_mutate(monkeypatch, tool, refuse=lambda d: abs(d) < 1e-3)
    _frame(tool, vp, 3e-4)
    assert tool.preview_faces() and tool._stage_refusal == (1.0, 3e-4)
    _frame(tool, vp, 5e-4)                     # not twice as far: no retry
    assert len(calls) == 1 and tool.preview_faces()
    _frame(tool, vp, 0.21)
    assert len(calls) == 2 and tool._stage_d == 0.21
    assert tool.preview_faces() == []
    assert _canon(scene) == _canon(_direct(_split_top, 0.21))


# ---- Outside edits mid-drag --------------------------------------------------

def test_ctrl_z_mid_drag_cancels_the_push():
    scene, vp, tool = _start(_split_top)
    before = _canon(scene)
    undo_depth = len(vp.history.undo_stack)
    _frame(tool, vp, 0.9)

    assert tool.on_undo(vp) is True
    assert _canon(scene) == before
    assert len(vp.history.undo_stack) == undo_depth
    assert not tool.dragging
    assert tool.on_undo(vp) is False           # idle: the ordinary undo runs


def test_redo_mid_drag_ends_the_drag_then_redoes_on_the_clean_model():
    # Redone under the staged preview, the redo landed on the staged push
    # and left it in the model with no undo entry.
    from types import SimpleNamespace
    from views.main_window import MainWindow

    scene, half = _split_top()
    vp = _StubViewport(scene)
    hist = vp.history
    clean = _canon(scene)
    hist.execute(build_add_edges(scene, [(V(10, 10, 0), V(11, 10, 0))]))
    redone = _canon(scene)
    hist.undo()
    tool = PushPullTool()
    tool.hovered_face = half
    tool.on_click(_ctx(vp))
    _frame(tool, vp, 0.9)
    assert _canon(scene) not in (clean, redone)

    # The main window's Redo, as Ctrl+Y / Ctrl+Shift+Z / menu / toolbar run it.
    vp.active_tool = tool
    vp.notify_scene_changed = lambda: None
    MainWindow._on_redo(SimpleNamespace(viewport=vp))

    assert not tool.dragging and tool._preview_snapshot is None
    assert _canon(scene) == redone             # the redo, and no push
    assert len(hist.undo_stack) == 1 and not hist.redo_stack
    assert hist.undo() is True and _canon(scene) == clean
    assert tool.on_redo(vp) is False           # idle: nothing to end


def test_an_outside_edit_mid_drag_abandons_it_without_restoring():
    # File > New, or a redo that bypassed on_redo, under a staged preview:
    # restoring the snapshot would resurrect a model that is not there.
    scene, vp, tool = _start(_split_top)
    _frame(tool, vp, 0.9)
    scene.mesh.add_edge(V(10, 10, 0), V(11, 10, 0))     # someone else's edit
    staged = _canon(scene)
    undo_depth = len(vp.history.undo_stack)

    tool._commit(vp)

    assert not tool.dragging and tool._preview_snapshot is None
    assert _canon(scene) == staged             # left as found, not restored
    assert len(vp.history.undo_stack) == undo_depth


# ---- Inference ignores the staged geometry ------------------------------------

class _InferViewport(_StubViewport):
    """No vertex nearby; the face/edge under the cursor is whatever the test
    says; the cursor ray looks straight down at x=1, y=1."""

    snap_threshold_px = 9.0
    _hover_edge = None

    def _world_to_pixel(self, w):
        return (1e6, 1e6)

    def _pixel_to_ray(self, x, y):
        return QVector3D(1, 1, 50), QVector3D(0, 0, -1)

    def _project_to_lock_line(self, start, direction, px, py):
        return QVector3D(start)


def test_inference_ignores_the_staged_cap_and_edges():
    scene, vp, tool = _start(_split_top, _InferViewport)
    _frame(tool, vp, 1.0)
    cap = next(f for f in scene.faces if _on_plane(f, "z", 4.0))
    new_edge = next(e for e in scene.mesh.edges
                    if abs(e.a.z() - 4) < 1e-6 and abs(e.b.z() - 4) < 1e-6)

    vp._pick = cap
    assert tool._infer_reference_distance(_ctx(vp)) is None
    vp._pick = None
    vp._hover_edge = new_edge
    assert tool._infer_reference_distance(_ctx(vp)) is None

    # A face of the clean model still engages: the bottom reads -3.
    vp._hover_edge = None
    vp._pick = next(f for f in scene.faces if _on_plane(f, "z", 0.0))
    assert tool._infer_reference_distance(_ctx(vp)) == pytest.approx(-3.0)


# ---- Keeping stages: the commit, the way back, slow models ----------------------

def test_a_release_inside_the_held_interval_commits_the_stage(monkeypatch):
    # The release keeps what the last frame showed instead of running the
    # pipeline again (~1 s at 6k faces, ~20 s at 107k).
    def drag(stage_first):
        scene, vp, tool = _start(_split_top)
        bottom = next(f for f in scene.faces if _on_plane(f, "z", 0.0))
        scene.selection.update({tool.base_face, bottom})
        bottom.interior = True               # undo must bring the flag back
        before = _canon(scene)
        if stage_first:
            for d in [0.4, -0.9, 1.3]:
                _frame(tool, vp, d)
        else:
            tool.extrusion = 1.3
        shown = _canon(scene)
        calls = _spy_mutate(monkeypatch, tool)
        tool._commit(vp)
        return scene, vp, bottom, before, shown, calls

    scene, vp, bottom, before, shown, calls = drag(stage_first=True)
    assert calls == [], "the release re-ran the pipeline"
    assert _canon(scene) == shown == _canon(_direct(_split_top, 1.3))
    assert scene.selection == {bottom}       # the base face gone with it
    assert len(vp.history.undo_stack) == 1
    assert vp.history.undo() is True
    assert _canon(scene) == before and bottom.interior is True
    assert scene.selection == {bottom}
    assert vp.history.redo() is True and _canon(scene) == shown

    # The pipeline commit leaves the selection the same way.
    scene, vp, bottom, _before, _shown, calls = drag(stage_first=False)
    assert calls == [1.3] and scene.selection == {bottom}


@pytest.mark.parametrize("keep_base, d", [(True, 0.6), (False, -0.7)])
def test_ctrl_or_a_release_outside_the_interval_runs_the_pipeline(
        monkeypatch, keep_base, d):
    scene, vp, tool = _start(_split_top)
    _frame(tool, vp, 0.6)
    calls = _spy_mutate(monkeypatch, tool)
    tool._keep_base = keep_base              # Ctrl, re-read at the release
    tool.extrusion = d                       # -0.7: the other side of 0
    tool._commit(vp)
    assert calls, "the stage cannot be this commit"
    assert _canon(scene) == _canon(_direct(_split_top, d, keep_base))


def test_a_typed_distance_inside_the_interval_commits_the_stage(monkeypatch):
    scene, vp, tool = _start(_split_top)
    clean = _canon(scene)
    _frame(tool, vp, 0.6)
    calls = _spy_mutate(monkeypatch, tool)
    assert tool.on_value(vp, 1.25) is True
    assert calls == []
    assert _canon(scene) == _canon(_direct(_split_top, 1.25))
    assert len(vp.history.undo_stack) == 1
    assert vp.history.undo() is True and _canon(scene) == clean


def test_back_and_forth_runs_the_pipeline_once_per_side(monkeypatch):
    scene, vp, tool = _start(_split_top)
    calls = _spy_mutate(monkeypatch, tool)
    for d in [0.5, -0.5, 0.6, -0.7, 0.4]:
        _frame(tool, vp, d)
        assert tool._stage_d is not None and tool.preview_faces() == []
        assert _canon(scene) == _canon(_direct(_split_top, d)), d
    assert calls == [0.5, -0.5]


def test_a_slow_model_stages_once_per_drag(monkeypatch):
    scene, vp, tool = _start(_split_top)
    tool._SLOW_STAGE_S = 0.0                 # every stage counts as slow
    before = _canon(scene)
    calls = _spy_mutate(monkeypatch, tool)
    _frame(tool, vp, 0.5)                    # the first stage always runs
    assert tool._stage_d == 0.5 and tool._stage_slow

    _frame(tool, vp, -0.5)                   # no second pause: the overlay
    assert tool.preview_faces() and _canon(scene) == before
    serial = scene.mesh._mut_serial
    _frame(tool, vp, -0.7)                   # and its frames touch no model
    assert tool.preview_faces() and scene.mesh._mut_serial == serial

    _frame(tool, vp, 0.9)                    # back into the parked stage
    assert tool._stage_d == 0.5 and tool.preview_faces() == []
    assert _canon(scene) == _canon(_direct(_split_top, 0.9))
    assert calls == [0.5]

    _frame(tool, vp, -0.6)
    tool._commit(vp)                         # outside every stage: pipeline
    assert calls == [0.5, -0.6]
    assert _canon(scene) == _canon(_direct(_split_top, -0.6))


def test_a_ctrl_tap_mid_drag_keeps_the_stage(monkeypatch):
    """Ctrl shows the overlay; letting go must find the stage again — on a
    slow model a dropped stage meant the overlay (#434) for the rest of the
    drag and a full pipeline run at release."""
    scene, vp, tool = _start(_split_top)
    tool._SLOW_STAGE_S = 0.0
    calls = _spy_mutate(monkeypatch, tool)
    _frame(tool, vp, 0.8)
    tool._keep_base = True                   # Ctrl down: the overlay
    tool._show_light_preview(vp)
    assert tool.preview_faces()
    tool._keep_base = False                  # Ctrl up: the parked stage
    _frame(tool, vp, 1.0)
    assert tool._stage_d == 0.8 and tool.preview_faces() == []
    tool._commit(vp)
    assert calls == [0.8]                    # no restage, no pipeline commit
    assert _canon(scene) == _canon(_direct(_split_top, 1.0))


def test_a_rim_corner_on_a_slope_slides_down_the_slope():
    # The corner where the cap's rim meets a slanted face cannot move straight
    # down without bending that face: it runs down the slope's edge. That
    # case used to fall back to the overlay until the push left the slope.
    _assert_frames_match(_ramp_notch_top, [-0.5, -1.5, -1.0])


# ---- A base out of true: no corner on the cap plane --------------------------

_OUT_OF_TRUE = [5e-4, 1e-3, 2e-3, 5e-3]


def _door(door, tilt):
    from tests.test_pushpull_cases import _plan
    return lambda: _plan(door, tilt=tilt)


def _solid(scene, v0):
    from core.orient import is_closed, signed_volume
    mesh = scene.mesh
    assert is_closed(mesh) and not any(len(e.faces) > 2 for e in mesh.edges)
    return signed_volume(mesh) - v0


@pytest.mark.parametrize("door", "AB")
@pytest.mark.parametrize("tilt,mouse,typed,want", [
    # Into the wall, from either side of it (a minus turns it round)…
    *((t, -0.05, 0.1, -0.1) for t in _OUT_OF_TRUE),
    *((t, 0.15, -0.1, -0.1) for t in _OUT_OF_TRUE),
    # …and out of it: from 2 mm on, the guard refuses that push on any route.
    # Not 1 mm: there the door's corner is 0.0010004 off its plane, a hair
    # past the 1 mm tolerance, and whether the guard takes the whole push
    # comes down to the last bit of QVector3D.length(), which macOS and
    # Linux round differently. Worked out exactly (math.sqrt in double), it
    # refuses, like 2 mm; Linux's rounding happened to let it through.
    *((t, -0.05, -0.1, 0.1) for t in _OUT_OF_TRUE[:1]),
    *((t, 0.15, 0.1, 0.1) for t in _OUT_OF_TRUE[:1]),
])
def test_a_typed_distance_counts_on_a_door_out_of_true(door, tilt, mouse,
                                                       typed, want):
    # Its corners are off the plane by more than the weld tolerance, so a
    # stage finds none to slide. Held anyway, the door stayed where the
    # first frame put it, whatever was typed: no word, one undo step.
    from core.orient import signed_volume
    build = _door(door, tilt)
    scene, vp, tool = _start(build)
    v0, area = signed_volume(scene.mesh), tool.base_face.area()
    _frame(tool, vp, mouse)
    assert tool.on_value(vp, typed) is True
    assert not tool.dragging
    assert _solid(scene, v0) == pytest.approx(area * want, abs=2e-3)
    assert _canon(scene, 4) == _canon(_direct(build, want), 4)


@pytest.mark.parametrize("door", "AB")
@pytest.mark.parametrize("tilt", _OUT_OF_TRUE)
def test_a_click_commits_where_the_mouse_is_on_a_door_out_of_true(door, tilt):
    from core.orient import signed_volume
    build = _door(door, tilt)
    scene, vp, tool = _start(build)
    v0, area = signed_volume(scene.mesh), tool.base_face.area()
    _frame(tool, vp, -0.02)
    _frame(tool, vp, -0.07)                  # the frame that used to be lost
    tool._commit(vp)
    assert _solid(scene, v0) == pytest.approx(-area * 0.07, abs=2e-3)
    assert _canon(scene, 4) == _canon(_direct(build, -0.07), 4)


def test_a_door_out_of_true_previews_the_sweep_and_undoes_clean():
    # Nothing to stretch, so the overlay shows the moving distance instead of
    # a real result frozen at the first frame; the model itself stays clean.
    scene, vp, tool = _start(_door("A", 1e-3))
    before = _canon(scene)
    for d in (-0.05, -0.12):
        _frame(tool, vp, d)
        assert tool._stage_d is None and tool.preview_faces()
        assert _canon(scene) == before
    tool._commit(vp)
    assert _canon(scene) != before
    vp.history.undo()
    assert _canon(scene) == before


def test_a_door_in_true_still_stages_and_commits_without_a_pipeline_run(
        monkeypatch):
    # The other side of the guard: corners found, so nothing changes.
    scene, vp, tool = _start(_door("A", 0.0))
    calls = _spy_mutate(monkeypatch, tool)
    _frame(tool, vp, -0.05)
    assert tool._stage_d is not None and len(tool._stage_verts) == 4
    _frame(tool, vp, -0.07)
    tool._commit(vp)
    assert calls == [-0.05]
    assert _canon(scene) == _canon(_direct(_door("A", 0.0), -0.07))


@pytest.mark.parametrize("door", "AB")
@pytest.mark.parametrize("tilt", [0.0, 1e-3])
def test_a_through_door_still_stages_past_the_far_face(door, tilt):
    # No cap in a tunnel, so no movers, and that is fine: the same punch at
    # any depth past the wall, typed or not.
    from core.orient import signed_volume
    build = _door(door, tilt)
    scene, vp, tool = _start(build)
    v0, area = signed_volume(scene.mesh), tool.base_face.area()
    _frame(tool, vp, -0.6)
    assert tool._stage_d is not None and tool._stage_verts == []
    assert tool.on_value(vp, 0.3) is True
    assert _solid(scene, v0) == pytest.approx(-area * 0.2, abs=2e-3)
