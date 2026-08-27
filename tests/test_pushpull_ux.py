# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull UX parity with SketchUp: Ctrl = push/pull a copy (keep the base
face as a slab division), double-click = repeat the last distance, VCB accepts
negatives (reverse) and unit suffixes.

Headless: stub viewport + direct tool calls.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.orient import is_closed, signed_volume
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(x, y, z)


class _StubViewport:
    def __init__(self, scene, pick=None):
        self.scene = scene
        self.history = History(scene)
        self._pick = pick

    last_status = None

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.last_status = text

    def set_hover(self, entity):
        pass

    suppressed: set | None = None

    def set_suppressed_faces(self, faces):
        self.suppressed = set(faces)

    def pick_face(self, x, y):
        return self._pick

    def pick_face_any(self, x, y):
        return self._pick, None


def _ctx(vp, modifiers=Qt.NoModifier):
    return ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(0, 0),
                       modifiers=modifiers, snap=None)


def _cube(scene, hist, size=4.0, height=3.0):
    ground = [V(0, 0), V(size, 0), V(size, size), V(0, size)]
    hist.execute(build_add_edges(
        scene, [(ground[i], ground[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(ground))]))
    _push(scene, scene.faces[0], height)


def _push(scene, face, dist, keep_base=False):
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = face
    tool.extrusion = dist
    tool.dragging = True
    tool._anchor = face.centroid()
    tool._normal = face.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(face)
    tool._keep_base = keep_base
    tool._commit(vp)
    return vp


def _top(scene, z):
    return next(
        f for f in scene.faces
        if len(f.vertices) == 4 and all(abs(v.z() - z) < 1e-9 for v in f.vertices)
    )


# ---- Ctrl: push/pull a copy --------------------------------------------------

def test_ctrl_push_keeps_base_as_slab_division():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    top = _top(scene, 3.0)
    vp = _push(scene, top, 2.0, keep_base=True)

    assert top in scene.faces                  # the start face stays
    assert _top(scene, 5.0) is not None        # new cap above it
    # 6 cube faces + 4 stacked strips + the new cap = 11; the walls are NOT
    # merged into tall faces (the belt at z=3 divides them, SketchUp-style).
    assert len(scene.faces) == 11
    belt = [e for e in scene.mesh.edges
            if abs(e.a.z() - 3) < 1e-9 and abs(e.b.z() - 3) < 1e-9]
    assert belt and all(len(e.faces) == 3 for e in belt)  # wall + strip + slab face

    assert vp.history.undo() is True
    assert len(scene.faces) == 6               # back to the plain cube


def test_ctrl_push_overrides_prism_translation():
    # Without Ctrl this cap push is a prism translate (cube just gets taller,
    # 6 faces). With Ctrl it must stack a segment instead.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    _push(scene, _top(scene, 3.0), 2.0, keep_base=False)
    assert len(scene.faces) == 6               # translate path: no division
    scene2 = Scene()
    hist2 = History(scene2)
    _cube(scene2, hist2, height=3.0)
    _push(scene2, _top(scene2, 3.0), 2.0, keep_base=True)
    assert len(scene2.faces) == 11             # copy path: belt + strips


# ---- double-click repeats the last distance -----------------------------------

def test_double_click_repeats_last_distance():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    PushPullTool.last_distance = None

    # First push: normal commit records the distance.
    inner = [V(1, 1, 3), V(2, 1, 3), V(2, 2, 3), V(1, 2, 3)]
    hist.execute(build_add_edges(
        scene, [(inner[i], inner[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(inner))]))
    block = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and max(v.x() for v in f.vertices) <= 2.001
    )
    _push(scene, block, 1.5)
    assert PushPullTool.last_distance == 1.5

    # Second block: double-click pushes it by the same 1.5 without dragging.
    inner2 = [V(2.5, 2.5, 3), V(3.5, 2.5, 3), V(3.5, 3.5, 3), V(2.5, 3.5, 3)]
    hist.execute(build_add_edges(
        scene, [(inner2[i], inner2[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(inner2))]))
    block2 = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and min(v.x() for v in f.vertices) >= 2.499
    )
    vp = _StubViewport(scene, pick=block2)
    tool = PushPullTool()
    tool.on_double_click(_ctx(vp))
    tops = [f for f in scene.faces
            if len(f.vertices) == 4 and all(abs(v.z() - 4.5) < 1e-9 for v in f.vertices)]
    assert len(tops) == 2                      # both blocks now at z=4.5


def test_double_click_without_history_is_plain_click():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    PushPullTool.last_distance = None
    top = _top(scene, 3.0)
    vp = _StubViewport(scene, pick=top)
    tool = PushPullTool()
    tool.hovered_face = top
    tool.on_double_click(_ctx(vp))             # falls back to on_click
    assert tool.dragging is True               # started a drag, no commit
    assert len(scene.faces) == 6


# ---- VCB: negative reverses the direction -------------------------------------

def test_vcb_negative_value_reverses_direction():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    inner = [V(1, 1, 3), V(2, 1, 3), V(2, 2, 3), V(1, 2, 3)]
    hist.execute(build_add_edges(
        scene, [(inner[i], inner[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(inner))]))
    block = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and max(v.x() for v in f.vertices) <= 2.001
    )
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = block
    tool.dragging = True
    tool.extrusion = 0.4   # user is dragging upward (+normal, outward)
    tool._anchor = block.centroid()
    tool._normal = block.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(block)
    assert tool.on_value(vp, -1.0) is True     # typed "-1" → carve down instead
    assert any(
        len(f.vertices) == 4 and all(abs(v.z() - 2.0) < 1e-9 for v in f.vertices)
        for f in scene.faces
    )                                          # recess floor at z=2
    assert signed_volume(scene.mesh) > 0


def test_vcb_zero_rejected():
    tool = PushPullTool()
    tool.dragging = True
    tool.base_face = object()
    assert tool.on_value(None, 0.0) is False


# ---- VCB parser: units + sign --------------------------------------------------

def test_parse_value_buffer_units_and_sign():
    from views.viewport import Viewport
    parse = Viewport._parse_value_buffer
    assert parse("2") == 2.0
    assert parse("-2") == -2.0
    assert parse("30cm") == 0.3
    assert parse("1500mm") == 1.5
    assert parse("2m") == 2.0
    assert parse("2,5") == 2.5
    assert parse("1;2;50cm") == (1.0, 2.0, 0.5)
    assert parse("-30cm") == -0.3
    assert parse("abc") is None
    assert parse("2x") is None


# ---- clamp: "Offset limited to ..." -------------------------------------------

def _locked_tool(scene, face, dist):
    """Build the tool exactly as a real drag-lock click would, then set the
    extrusion (as if dragged/typed) and return it ready to clamp/commit."""
    tool = PushPullTool()
    tool.base_face = face
    tool.dragging = True
    tool._anchor = face.centroid()
    tool._normal = face.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(face)
    tool._compute_inward_limit(scene)
    tool.extrusion = dist
    tool._clamp_extrusion()
    return tool


def test_inward_limit_detected_on_prism_cap():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    tool = _locked_tool(scene, _top(scene, 3.0), -1.0)
    assert tool._limit_in is not None and abs(tool._limit_in - 3.0) < 1e-6


def test_shrink_beyond_height_clamps():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    tool = _locked_tool(scene, _top(scene, 3.0), -99.0)
    assert tool.extrusion == -3.0          # clamped to the solid's extent


def test_shrink_to_exact_limit_collapses_to_single_face():
    # Pushing the top all the way down flattens the box to one face — how
    # SketchUp deletes a volume with Push/Pull.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    tool = _locked_tool(scene, _top(scene, 3.0), -99.0)
    tool._commit(_StubViewport(scene))
    m = scene.mesh
    assert len(m.faces) == 1
    assert all(abs(v.z()) < 1e-9 for v in m.faces[0].vertices)
    assert len(m.edges) == 4 and len(m.vertices) == 4


def test_corner_step_clamped_opens_notch_through_floor():
    # A corner rect pushed deeper than the cube is tall: clamp to the height,
    # landing flush on the floor plane — the notch opens clear through and the
    # result is a watertight L-section solid.
    from core.orient import signed_volume

    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=10.0, height=3.0)
    corner_loop = [V(0, 0, 3), V(4, 0, 3), V(4, 4, 3), V(0, 4, 3)]
    hist.execute(build_add_edges(
        scene, [(corner_loop[i], corner_loop[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(corner_loop))]))
    corner = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and max(v.x() for v in f.vertices) <= 4.001
        and max(v.y() for v in f.vertices) <= 4.001
    )
    tool = _locked_tool(scene, corner, -99.0)
    assert tool.extrusion == -3.0
    tool._commit(_StubViewport(scene))
    m = scene.mesh
    assert all(len(e.faces) == 2 for e in m.edges), "not watertight"
    assert signed_volume(m) > 0
    # The floor lost the corner region: it is an L (6 vertices), not a square.
    floors = [f for f in m.faces if all(abs(v.z()) < 1e-9 for v in f.vertices)]
    assert len(floors) == 1 and len(floors[0].vertices) == 6


def test_through_target_does_not_clamp():
    # A window inside a thin wall: the far face is a punch target, not a
    # blocker — the push past it must stay a through-hole, never a clamp.
    scene = Scene()
    hist = History(scene)
    floor = [V(0, 0, 0), V(4, 0, 0), V(4, 0.3, 0), V(0, 0.3, 0)]
    hist.execute(build_add_edges(
        scene, [(floor[i], floor[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(floor))]))
    _push(scene, scene.faces[0], 3.0)
    window = [V(1, 0, 1), V(3, 0, 1), V(3, 0, 2), V(1, 0, 2)]
    hist.execute(build_add_edges(
        scene, [(window[i], window[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(window))]))
    winface = next(
        f for f in scene.faces if len(f.vertices) == 4
        and all(abs(v.y()) < 1e-9 for v in f.vertices)
        and max(v.x() for v in f.vertices) <= 3.001
        and min(v.x() for v in f.vertices) >= 0.999
    )
    tool = _locked_tool(scene, winface, -0.4)
    assert tool._limit_in is None          # nothing blocks: far face is punchable
    assert tool.extrusion == -0.4
    tool._commit(_StubViewport(scene))
    backs = [f for f in scene.faces
             if all(abs(v.y() - 0.3) < 1e-4 for v in f.vertices) and f.holes]
    assert len(backs) == 1                 # punched clean through


def test_outward_pull_never_clamped():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    tool = _locked_tool(scene, _top(scene, 3.0), 50.0)
    assert tool.extrusion == 50.0


# ---- distance inference (hover a vertex mid-push) ------------------------------

class _InferViewport(_StubViewport):
    """Viewport stub with a trivial top-view projection: world (x, z) → pixel
    (x*10, -z*10), so vertices land at predictable screen spots."""

    snap_threshold_px = 9.0

    def _world_to_pixel(self, world):
        return (world.x() * 10.0, -world.z() * 10.0)


def test_hovering_vertex_infers_distance():
    from PySide6.QtCore import QPointF
    from tools.base import ToolContext

    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)                      # cube A
    other = [V(6, 0, 0), V(8, 0, 0), V(8, 2, 0), V(6, 2, 0)]
    hist.execute(build_add_edges(
        scene, [(other[i], other[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(other))]))
    ref = next(f for f in scene.faces
               if all(abs(v.z()) < 1e-9 for v in f.vertices)
               and min(v.x() for v in f.vertices) >= 5.999)
    # Extrude the block upward regardless of the drawn sheet's winding.
    _push(scene, ref, 5.0 if ref.normal().z() > 0 else -5.0)   # block top z=5

    vp = _InferViewport(scene)
    tool = PushPullTool()
    top = _top(scene, 3.0)
    tool.base_face = top
    tool.dragging = True
    tool._anchor = top.centroid()
    tool._normal = top.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(top)

    # Cursor over the reference block's top corner (6, 0, 5) → pixel (60, -50).
    ctx = ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(60.0, -50.0),
                      modifiers=Qt.NoModifier, snap=None)
    d = tool._infer_reference_distance(ctx)
    # Anchor is the cube top (z=3); the hovered corner is at z=5 → push +2.
    assert d is not None and abs(d - 2.0) < 1e-6

    # Cursor over empty space → no inference.
    ctx2 = ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(500.0, 500.0),
                       modifiers=Qt.NoModifier, snap=None)
    assert tool._infer_reference_distance(ctx2) is None

    # The base face's own corners never pin the drag.
    ctx3 = ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(0.0, -30.0),
                       modifiers=Qt.NoModifier, snap=None)
    assert tool._infer_reference_distance(ctx3) is None


class _FaceInferViewport(_StubViewport):
    """Stub aiming a top-down ray at ``ref_face`` so the face-fallback of the
    distance inference engages (no vertex within threshold)."""

    snap_threshold_px = 9.0

    def __init__(self, scene, ref_face):
        super().__init__(scene)
        self._ref = ref_face

    def _world_to_pixel(self, world):
        return (world.x() * 10.0, -world.z() * 10.0)

    def pick_face_any(self, x, y):
        return self._ref, None

    def _pixel_to_ray(self, x, y):
        # A ray straight down through (x/10, 1, 100): hits any horizontal plane.
        return QVector3D(x / 10.0, 1.0, 100.0), QVector3D(0.0, 0.0, -1.0)


def test_hovering_face_infers_distance_and_marks_it():
    from PySide6.QtCore import QPointF
    from tools.base import ToolContext

    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)                      # cube top at z=3
    # A free-floating reference face high above, away from any vertex.
    ref_loop = [V(20, 20, 7), V(24, 20, 7), V(24, 24, 7), V(20, 24, 7)]
    hist.execute(build_add_edges(
        scene, [(ref_loop[i], ref_loop[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(ref_loop))]))
    ref = next(f for f in scene.faces
               if all(abs(v.z() - 7) < 1e-9 for v in f.vertices))

    tool = PushPullTool()
    top = _top(scene, 3.0)
    tool.base_face = top
    tool.dragging = True
    tool._anchor = top.centroid()
    tool._normal = top.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(top)

    vp = _FaceInferViewport(scene, ref)
    # No vertex near the cursor → falls back to the face plane (z=7). Anchor at
    # z=3 → distance +4, and the engaged hit point is recorded for the marker.
    ctx = ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(220.0, -70.0),
                      modifiers=Qt.NoModifier, snap=None)
    d = tool._infer_reference_distance(ctx)
    assert d is not None and abs(d - 4.0) < 1e-6
    marker = tool.inference_marker()
    assert marker is not None
    pt, kind = marker
    assert kind == "face" and abs(pt.z() - 7.0) < 1e-6


def test_clamp_flashes_status_message():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    tool = PushPullTool()
    top = _top(scene, 3.0)
    tool.base_face = top
    tool.dragging = True
    tool._anchor = top.centroid()
    tool._normal = top.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(top)
    tool._compute_inward_limit(scene)
    tool.extrusion = -99.0
    vp = _StubViewport(scene)
    tool._clamp_extrusion(vp)
    assert tool.extrusion == -3.0
    assert vp.last_status == "Offset limited to 3.00 m"


# ---- BIM-grade refusal guard --------------------------------------------------

def test_push_that_would_break_the_solid_is_refused(monkeypatch):
    # A push whose inner mutation leaves the closed solid non-watertight (an
    # ill-defined push through an interior partition, a detached hole rim) must
    # be refused: the solid is restored untouched rather than committing a
    # broken mesh that would poison volume/IFC export.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    top = _top(scene, 3.0)
    tool = PushPullTool()
    tool.base_face = top
    tool.dragging = True
    tool._anchor = top.centroid()
    tool._normal = top.normal()
    tool.extrusion = 1.0
    before_faces = len(scene.mesh.faces)
    before_vol = signed_volume(scene.mesh)

    # Stand in for any inner op that would crack the solid: drop a face.
    def break_it(s, preview=False):
        m = tool._target_scene(s).mesh
        m.remove_face(m.faces[0])

    monkeypatch.setattr(tool, "_mutate_inner", break_it)
    tool._mutate(scene)

    assert tool._refused
    assert is_closed(scene.mesh)                       # solid kept intact
    assert len(scene.mesh.faces) == before_faces
    assert abs(signed_volume(scene.mesh) - before_vol) < 1e-9


def test_valid_push_is_not_refused():
    # The guard must not fire on a clean push: a normal +2 extrude on a 4×4×3
    # cube commits (volume 48 → 80) and keeps the solid watertight.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    tool = _locked_tool(scene, _top(scene, 3.0), 2.0)
    tool._commit(_StubViewport(scene))
    assert is_closed(scene.mesh)
    assert abs(signed_volume(scene.mesh) - 80.0) < 1e-6   # the push happened
    # The committed distance is remembered (guard did not intercept).
    assert PushPullTool.last_distance == 2.0


# ---- autofold: a move that warps a face splits it into planar pieces ----------

def test_move_lifting_a_corner_autofolds_quad():
    from core.history import MoveVerticesCommand
    from core.topology import is_planar

    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    hist.execute(MoveVerticesCommand([V(2, 2, 0)], QVector3D(0, 0, 1)))

    m = scene.mesh
    assert len(m.faces) == 2                       # quad folded into 2 triangles
    assert all(len(f.vertices) == 3 for f in m.faces)
    assert all(is_planar(list(f.vertices)) for f in m.faces)
    fold = [e for e in m.edges if len(e.faces) == 2]
    assert len(fold) == 1                          # exactly one fold edge

    assert hist.undo() is True                     # snapshot undo: quad restored
    assert len(m.faces) == 1 and len(m.faces[0].vertices) == 4
    assert hist.redo() is True
    assert len(m.faces) == 2


def test_move_in_plane_does_not_fold():
    from core.history import MoveVerticesCommand

    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    hist.execute(MoveVerticesCommand([V(2, 2, 0)], QVector3D(1, 1, 0)))
    assert len(scene.mesh.faces) == 1              # still one planar quad
    assert len(scene.mesh.faces[0].vertices) == 4
    assert hist.undo() is True                     # cheap inverse-translate undo
    assert abs(scene.mesh.faces[0].vertices[2].x() - 2.0) < 1e-6


def test_autofold_pentagon_folds_minimally():
    # Lift one vertex of a planar pentagon: the planar remainder must merge
    # back into one piece — pieces stay minimal, not a full triangle fan.
    from core.history import MoveVerticesCommand
    from core.topology import is_planar

    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face(
        [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(2, 6, 0), V(0, 4, 0)])
    hist.execute(MoveVerticesCommand([V(2, 6, 0)], QVector3D(0, 0, 1.5)))
    m = scene.mesh
    assert all(is_planar(list(f.vertices)) for f in m.faces)
    assert len(m.faces) <= 3                       # folded, not fanned to bits


# ---- push/pull directly on a group's face --------------------------------------

def _boxed_group(scene, x0=0.0):
    """A 2×2×2 closed box living in its own Group, appended to the scene."""
    from core.group import Group
    from core.orient import orient_outward

    g = Group()
    m = g.mesh
    p = [V(x0, 0, 0), V(x0 + 2, 0, 0), V(x0 + 2, 2, 0), V(x0, 2, 0)]
    q = [V(x0, 0, 2), V(x0 + 2, 0, 2), V(x0 + 2, 2, 2), V(x0, 2, 2)]
    m.add_face(p)
    m.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        m.add_face([p[i], p[j], q[j], q[i]])
    orient_outward(m)
    scene.groups.append(g)
    return g


def _push_group(scene, group, face, dist):
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = face
    tool.extrusion = dist
    tool.dragging = True
    tool._group = group
    target = tool._target_scene(scene)
    tool._anchor = face.centroid()
    tool._normal = face.normal()
    tool._attached, tool._prism_cap = tool._classify_base(target)
    tool._cap_positions = tool._cap_loop_positions(face)
    tool._compute_inward_limit(target)
    tool._commit(vp)
    return vp


def test_push_on_group_face_edits_only_the_group():
    from core.orient import signed_volume

    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)                 # loose cube in the scene
    g = _boxed_group(scene, x0=10.0)
    loose_faces = len(scene.mesh.faces)

    top = next(f for f in g.mesh.faces
               if all(abs(v.z() - 2) < 1e-9 for v in f.vertices))
    vp = _push_group(scene, g, top, 1.0)           # raise the group's box to z=3

    assert len(scene.mesh.faces) == loose_faces    # loose mesh untouched
    assert any(all(abs(v.z() - 3) < 1e-9 for v in f.vertices)
               for f in g.mesh.faces)              # group cap moved up
    assert all(len(e.faces) == 2 for e in g.mesh.edges)
    assert signed_volume(g.mesh) > 0

    assert vp.history.undo() is True               # snapshot lands on the group
    assert any(all(abs(v.z() - 2) < 1e-9 for v in f.vertices)
               for f in g.mesh.faces)
    assert not any(v.position.z() > 2.5 for v in g.mesh.vertices)


def test_group_recess_and_clamp_use_group_geometry():
    scene = Scene()
    hist = History(scene)
    g = _boxed_group(scene)

    top = next(f for f in g.mesh.faces
               if all(abs(v.z() - 2) < 1e-9 for v in f.vertices))
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = top
    tool.dragging = True
    tool._group = g
    target = tool._target_scene(scene)
    tool._anchor = top.centroid()
    tool._normal = top.normal()
    tool._attached, tool._prism_cap = tool._classify_base(target)
    tool._cap_positions = tool._cap_loop_positions(top)
    tool._compute_inward_limit(target)
    assert tool._limit_in is not None and abs(tool._limit_in - 2.0) < 1e-6
    tool.extrusion = -99.0
    tool._clamp_extrusion()
    assert tool.extrusion == -2.0                  # clamped by the group's box
    tool._commit(vp)
    assert len(g.mesh.faces) == 1                  # collapsed flat, group-local
    assert scene.mesh.faces == []                  # loose mesh untouched


# ---- floor-plan workflow: raising adjacent rooms --------------------------------

def test_two_room_plan_raises_cleanly():
    """The casita core loop: a plan with two rooms sharing a wall, both raised
    to the same height. The second push must not crash on the already-built
    shared wall (it deduplicates), the roofs stay two faces split by a ridge
    over the divider (SketchUp's crease rule — no slab floating over the
    wall), and nothing is left orphaned."""
    scene = Scene()
    hist = History(scene)

    def draw_rect(loop):
        hist.execute(build_add_edges(
            scene, [(loop[i], loop[(i + 1) % 4]) for i in range(4)],
            detect_faces=False, extra=[AddFaceCommand(list(loop))]))

    draw_rect([V(0, 0), V(3, 0), V(3, 4), V(0, 4)])
    draw_rect([V(3, 0), V(6, 0), V(6, 4), V(3, 4)])
    room_a = min(scene.mesh.faces, key=lambda f: f.centroid().x())
    _push(scene, room_a, 2.7)
    room_b = next(f for f in scene.mesh.faces
                  if all(abs(v.z()) < 1e-9 for v in f.vertices)
                  and f.centroid().x() > 3)
    _push(scene, room_b, 2.7)

    m = scene.mesh
    tops = [f for f in m.faces if all(abs(v.z() - 2.7) < 1e-6 for v in f.vertices)]
    shared = [f for f in m.faces if all(abs(v.x() - 3) < 1e-6 for v in f.vertices)]
    assert len(tops) == 2                      # roofs split by the ridge
    assert len(shared) == 1                    # one shared wall, deduplicated
    ridge = [e for e in m.edges
             if abs(e.a.z() - 2.7) < 1e-6 and abs(e.b.z() - 2.7) < 1e-6
             and abs(e.a.x() - 3) < 1e-6 and abs(e.b.x() - 3) < 1e-6]
    assert len(ridge) == 1 and len(ridge[0].faces) == 3   # 2 roofs + the wall
    assert sum(1 for e in m.edges if not e.faces) == 0
    seams = [e for e in m.edges if len(e.faces) == 2 and
             QVector3D.dotProduct(e.faces[0].normal().normalized(),
                                  e.faces[1].normal().normalized()) > 0.999]
    assert seams == []


# ---- Drag preview: the sweep draws its own edges -----------------------------

def test_drag_preview_draws_the_sweep_wireframe():
    # The drag overlay paints its faces FILLED and nothing else, so without a
    # wireframe the forming solid slid under the cursor as a flat silhouette
    # and only snapped into a box once the drag ended (Marco, 2026-08-27).
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=4.0, height=3.0)
    top = _top(scene, 3.0)

    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = top
    tool._normal = top.normal()
    tool.extrusion = 2.0
    tool.dragging = True
    tool._show_light_preview(vp)

    segs = tool.rubber_band_lines()
    assert segs, "the drag preview drew no edges at all"

    def key(p):
        return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))

    drawn = {frozenset((key(a), key(b))) for a, b in segs}
    # A square cap swept 2 m: 4 base edges + 4 moved edges + 4 risers.
    assert len(drawn) == 12
    base_z = {round(v.z(), 6) for v in top.vertices}
    zs = {z for seg in drawn for _x, _y, z in seg}
    assert base_z == {3.0} and zs == {3.0, 5.0}   # both rings are there
    # Every corner is joined to where it moved to.
    risers = [s for s in drawn if len({z for _x, _y, z in s}) == 2]
    assert len(risers) == 4

    # Nothing left behind once the drag is over.
    tool._commit(vp)
    assert tool.rubber_band_lines() == []


def test_drag_preview_wireframe_carries_holes():
    # A ring push must outline the hole too, not just the outer boundary.
    scene = Scene()
    outer = [V(0, 0), V(6, 0), V(6, 6), V(0, 6)]
    inner = [V(2, 2), V(4, 2), V(4, 4), V(2, 4)]
    ring = scene.mesh.add_face(outer, [inner])
    assert ring.holes

    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = ring
    tool._normal = ring.normal()
    tool.extrusion = 1.0
    tool.dragging = True
    tool._show_light_preview(vp)

    segs = tool.rubber_band_lines()
    assert len(segs) == 24          # 12 for the outer loop, 12 for the hole
    xs = {round(a.x(), 6) for a, _b in segs}
    assert 2.0 in xs and 4.0 in xs  # the hole's own corners are drawn


# ---- The material extrudes with the shape -----------------------------------

def _painted_rect(scene, hist, size=4.0, attrs=None):
    """A rectangle on the ground carrying ``attrs``, ready to be pushed."""
    ring = [V(0, 0), V(size, 0), V(size, size), V(0, size)]
    hist.execute(build_add_edges(
        scene, [(ring[i], ring[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(ring))]))
    face = scene.faces[0]
    face.attrs.update(attrs or {})
    return face


def test_push_carries_the_colour_onto_the_new_sides():
    # SketchUp extrudes the material with the shape: a painted rectangle pulled
    # up is a painted box, not a box with one painted face (Marco, 2026-08-27).
    scene = Scene()
    hist = History(scene)
    rect = _painted_rect(scene, hist,
                         attrs={"color": [0.8, 0.2, 0.1], "mat": "Ladrillo"})
    _push(scene, rect, 3.0)

    assert len(scene.faces) == 6
    assert all(f.attrs.get("mat") == "Ladrillo" for f in scene.faces)
    assert all(f.attrs.get("color") == [0.8, 0.2, 0.1] for f in scene.faces)


def test_push_carries_the_texture_but_re_anchors_it_per_face():
    # The base's uvw is a world->UV map fitted in the GROUND plane; evaluating
    # it on a wall leaves the image constant along the extrusion, so the
    # texture would smear into stripes. The walls must map in their own plane.
    scene = Scene()
    hist = History(scene)
    tex = {"path": "/tmp/piedra.jpg", "sw": 0.5, "sh": 0.5,
           "uvw": [2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0]}
    rect = _painted_rect(scene, hist, attrs={"texture": dict(tex),
                                             "mat": "Piedra"})
    _push(scene, rect, 3.0)

    walls = [f for f in scene.faces
             if abs(f.normal().normalized().z()) < 1e-6]
    assert len(walls) == 4
    for w in walls:
        t = w.attrs.get("texture")
        assert t is not None, "the wall came out bare"
        assert t["path"] == "/tmp/piedra.jpg"
        assert t["sw"] == 0.5 and t["sh"] == 0.5   # same tile size
        assert "uvw" not in t                      # re-anchored, not smeared
        assert t["planar"] is True                 # default projection

    # The moved cap continues the base, so it keeps the exact placement.
    cap = _top(scene, 3.0)
    assert cap.attrs["texture"]["uvw"] == tex["uvw"]


def test_push_leaves_a_face_that_has_its_own_paint_alone():
    # Only bare new geometry inherits; a neighbour the rebuild re-emitted with
    # its own material must not be repainted by the push.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    top = _top(scene, 3.0)
    for f in scene.faces:
        if f is not top:
            f.attrs["mat"] = "Original"
    top.attrs["mat"] = "Nuevo"
    _push(scene, top, 2.0)

    keep = [f for f in scene.faces if f.attrs.get("mat") == "Original"]
    assert keep, "the untouched faces lost their own material"


def test_unpainted_push_stays_unpainted():
    scene = Scene()
    hist = History(scene)
    rect = _painted_rect(scene, hist)
    _push(scene, rect, 3.0)
    assert all(not f.attrs for f in scene.faces)


# ---- The drag wireframe follows the same softening as the commit ------------

def _ngon_face(scene, n, r=2.0):
    """A regular n-gon on the ground, as one face."""
    import math
    ring = [V(r * math.cos(2 * math.pi * k / n),
              r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    return scene.mesh.add_face(ring)


def _preview_segments(scene, face, dist=3.0):
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = face
    tool._normal = face.normal()
    tool.extrusion = dist
    tool.dragging = True
    tool._show_light_preview(vp)
    return tool.rubber_band_lines()


def test_pushing_a_circle_previews_a_smooth_cylinder():
    # Pushing a circle drew every facet seam of the side, so the cylinder came
    # out streaked with lines and only cleaned up on release (Marco). The drag
    # must hide exactly the risers the commit is going to soften.
    scene = Scene()
    circle = _ngon_face(scene, 24)          # 15 deg steps: a curve
    segs = _preview_segments(scene, circle)

    def key(p):
        return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))

    risers = [s for s in segs
              if abs(key(s[0])[2] - key(s[1])[2]) > 1e-6]
    assert risers == [], "the cylinder's side is drawn with facet lines"
    assert len(segs) == 48                  # both circles, nothing else


def test_pushing_a_hexagon_keeps_its_real_edges():
    # A hexagon's sides meet at 60 deg: those are real corners, not a curve,
    # and the commit leaves them visible — so the drag must too.
    scene = Scene()
    hexagon = _ngon_face(scene, 6)
    segs = _preview_segments(scene, hexagon)
    risers = [s for s in segs if abs(s[0].z() - s[1].z()) > 1e-6]
    assert len(risers) == 6
    assert len(segs) == 18


# ---- The base's normal must agree with the surface it belongs to ------------

def _wall_with_door(scene):
    """An OPEN shell (no volume for orient_outward to judge): a wall with a
    door carved out of it, the door wound the OTHER way — Marco's cubo.igz."""
    door_ring = [V(1, 0, 0), V(1, 0, 2), V(2.5, 0, 2), V(2.5, 0, 0)]
    # wall minus the door notch, wound so its normal points -Y (outward)
    outer = [V(0, 0, 0), V(1, 0, 0), V(1, 0, 2), V(2.5, 0, 2),
             V(2.5, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)]
    wall = scene.mesh.add_face(outer)
    if wall.normal().normalized().y() > 0:
        scene.mesh.remove_face(wall)
        wall = scene.mesh.add_face(outer[::-1])
    # A floor, its front boundary split where the door meets it, so every one
    # of the door's edges is shared — what makes the push read as a recess.
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(2.5, 0, 0), V(4, 0, 0),
                         V(4, 3, 0), V(0, 3, 0)])
    # the door, deliberately facing the OTHER way (+Y, into the model)
    door = scene.mesh.add_face(door_ring)
    if door.normal().normalized().y() < 0:
        scene.mesh.remove_face(door)
        door = scene.mesh.add_face(door_ring[::-1])
    return wall, door


def test_a_reversed_face_takes_the_facing_of_its_own_surface():
    # orient_outward can only judge a closed volume; on an open shell a face
    # keeps whatever winding the draw gave it. Push/Pull's whole sign
    # convention rests on the base pointing OUTWARD, so it has to agree with
    # the surface around it.
    scene = Scene()
    wall, door = _wall_with_door(scene)
    assert door.normal().normalized().y() > 0      # wound inward
    assert wall.normal().normalized().y() < 0      # the surface faces out

    n = PushPullTool._surface_normal(door)
    assert n.normalized().y() < 0, "the door still disagrees with its wall"


def test_a_lone_sheet_keeps_its_own_normal():
    # Nothing coplanar to ask: leave it alone.
    scene = Scene()
    sheet = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    n0 = sheet.normal().normalized()
    n = PushPullTool._surface_normal(sheet).normalized()
    assert abs(QVector3D.dotProduct(n, n0) - 1.0) < 1e-9


def test_pushing_a_reversed_door_inward_hides_the_base_face():
    # The bug Marco hit: with the sign inverted the tool read a drag INTO the
    # wall as a drag out of it, never hid the base, and the outer face stood
    # there covering the recess ("la cara de afuera del cubo parece intacto").
    scene = Scene()
    wall, door = _wall_with_door(scene)

    def _drag_into_the_wall(normal):
        vp = _StubViewport(scene)
        tool = PushPullTool()
        tool.base_face = door
        tool._normal = normal
        tool._attached, tool._prism_cap = tool._classify_base(scene)
        tool.dragging = True
        # The SAME drag either way: into the wall, along +Y. Its sign is
        # whatever the normal in hand makes of it.
        tool.extrusion = -0.6 if normal.normalized().y() < 0 else 0.6
        tool._show_light_preview(vp)
        return tool.extrusion, vp.suppressed

    # What the tool used to do: take the face's own normal, which here points
    # the wrong way. The drag reads POSITIVE, so the recess rule never fires.
    dist, hidden = _drag_into_the_wall(door.normal())
    assert dist > 0.0 and not hidden      # the outer face is left covering it

    # With the surface's facing the same drag reads as what it is.
    dist, hidden = _drag_into_the_wall(PushPullTool._surface_normal(door))
    assert dist < 0.0, "a drag into the wall must read as negative"
    assert hidden == {door}, "the base face was left covering the recess"


def test_a_reversed_door_commits_the_push_the_way_it_previewed():
    # The preview and the commit have to agree on which way is in. ``d`` is
    # signed along the normal the DRAG used; the commit took the face's own
    # winding instead, so on an open shell a door previewed going IN and came
    # out going OUT once the command ran (Marco, 2026-08-27).
    scene = Scene()
    wall, door = _wall_with_door(scene)
    inside = 1.0        # the wall faces -Y, so the material is toward +Y
    assert door.normal().normalized().y() > 0        # wound the wrong way

    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = door
    tool._normal = PushPullTool._surface_normal(door)
    tool._anchor = door.centroid()
    tool._drag_pre_oriented = True
    tool.dragging = True
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = tool._cap_loop_positions(door)
    tool.extrusion = -0.6                            # a drag INTO the wall
    tool._commit(vp)

    moved = [f for f in scene.faces
             if abs(f.normal().normalized().y()) > 0.99
             and abs(f.area() - 3.0) < 1e-6
             and abs(f.centroid().y()) > 1e-6]
    assert moved, "the door did not move at all"
    y = moved[0].centroid().y()
    assert y * inside > 0, (
        "the push came out the wrong way: the pocket floor landed at y=%.3f" % y)
