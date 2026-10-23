# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull tool: extrude a face along its normal.

UX (the usual push/pull convention):
- Hover a face; the cursor picks the front-most face under it.
- First click: lock onto that face and start a drag along its normal.
- Subsequent mouse motion slides the extrusion preview (wireframe of
  the future box) along the normal axis. Length is shown near the
  midpoint, same overlay as the line tool.
- Second click commits at the current distance.
- Typing a number + Enter (VCB) commits at exactly that distance,
  preserving the current direction's sign; a negative value ("-2")
  reverses it, and unit suffixes ("30cm", "1500mm") are understood.
- **Ctrl** = push/pull a copy: the start face stays in place (a slab
  division) and the extrusion stacks as a new segment — how floors are
  stacked.
- **Double-click** repeats the last committed distance on the face under
  the cursor (with Ctrl, as a copy).
- Esc cancels without committing.

Commit pipeline (the deterministic root-fix, no case tree):
1. Orient the mesh outward (entry invariant; no-op on open sheets).
2. Build the *naive* extrusion: consumed/kept base, moved cap (with holes),
   one wall quad per boundary/hole edge — even where a quad lands on an
   existing face's plane.
3. Stitch connectivity (T-junctions, collinear vertices).
4. On a solid: deterministically rebuild every touched plane (seams, overlaps,
   cracks) from its edges via ``core.cap_rebuild``; on a flat sheet, fall back
   to the seeded coplanar merge (no outward side exists there).
5. Orient outward again — every committed solid upholds the invariant.

A bordered (embedded) base face is consumed either direction — pushing in
carves a recess / step / through-hole (the far face is punched when the push
reaches it); pushing out grows the solid. A free-standing face keeps its base
as the cap of the new box.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.geometry import Face
from core.i18n import tr
from core.mesh import _STITCH_TOL, PAINT_KEYS, Mesh, turn_face_over
# MeshFace is core.mesh's Face — the class scene meshes are built from. The
# geometry.Face imported above is a DIFFERENT legacy class; an isinstance
# against IT is always False, so the preselection arm checks MeshFace.
from core.mesh import Face as MeshFace
from core.history import (
    AddEdgeCommand,
    AddFaceCommand,
    DeleteFaceCommand,
    PruneOrphanEdgesCommand,
    SnapshotMutation,
    run_stitch,
    subtract_loop_from_face,
    translate_points,
)
from core.arrangement import _interior_point, _point_in_polygon, plane_basis
from core.orient import _ray_triangle, is_closed, orient_outward
from core.cap_rebuild import (
    RebuildCache,
    _canon_loop,
    apply_rebuild,
    crack_planes,
    edges_along,
    plane_key,
    prune_plane_debris,
    seam_planes,
)
from core.topology import (
    _faces_coplanar,
    _key,
    _mesh_is_flat,
    classify_push_edge,
    heal_overlapping_faces,
    loop_inside_face,
    _segment_on_face_boundary,
    refine_loop_with_points,
)
from tools.base import Tool, ToolContext, ctrl_clause
from core.units import fmt_len


def _project_loop_2d(loop, normal):
    u, v = plane_basis(normal)
    return [(QVector3D.dotProduct(p, u), QVector3D.dotProduct(p, v)) for p in loop]


def _loops_overlap_2d(a_xy, b_xy) -> bool:
    """Whether two loops projected to the same plane overlap laterally: a
    representative interior point of one inside the other, or any vertex
    strictly inside. Good for the push-clamp candidates (a far cap under the
    whole loop, a floor under a corner notch); exotic offset-cross overlaps
    with no contained vertex are not the clamp's concern. Holes are ignored."""
    if _point_in_polygon(_interior_point(a_xy), b_xy):
        return True
    if _point_in_polygon(_interior_point(b_xy), a_xy):
        return True
    return any(_point_in_polygon(p, b_xy) for p in a_xy) or \
        any(_point_in_polygon(p, a_xy) for p in b_xy)


class _GroupScene:
    """Scene facade aiming the push/pull machinery at a Group's isolated mesh.

    Mirrors the slice of :class:`core.scene.Scene` the commands, the stitch and
    the per-plane rebuild touch — ``mesh`` / ``faces`` / ``edges`` /
    ``selection`` / ``version`` — so the whole pipeline runs unchanged inside
    the group (its geometry is already in world coordinates). The version
    bump lands on the real scene so the viewport re-renders."""

    def __init__(self, scene, group) -> None:
        self._scene = scene
        self.mesh = group.mesh
        self.selection = scene.selection

    @property
    def faces(self):
        return self.mesh.faces

    @property
    def edges(self):
        return self.mesh.edges

    @property
    def version(self):
        return self._scene.version

    @version.setter
    def version(self, value):
        self._scene.version = value


def _component_is_closed(mesh, face) -> bool:
    """Whether ``face``'s edge-connected component is watertight — every edge
    reachable from it borders at least two faces. An open sheet (a flat
    drawing) reaches a boundary edge and reads ``False`` even when a closed
    solid exists elsewhere in the same mesh."""
    seen = {face}
    stack = [face]
    while stack:
        f = stack.pop()
        for lp in (f.loop, *f.hole_loops):
            n = len(lp)
            for i in range(n):
                e = mesh.find_edge(lp[i], lp[(i + 1) % n])
                if e is None:
                    continue
                if len(e.faces) < 2:
                    return False
                for g in e.faces:
                    if g not in seen:
                        seen.add(g)
                        stack.append(g)
    return True


def _swept_by_push(neighbour: Face, push_normal: QVector3D) -> bool:
    """Whether ``neighbour`` is *swept* by a push along ``push_normal`` — it has
    an edge parallel to the push, so translating its shared edge slides the wall
    along its own length (a prism wall getting taller). A cap perpendicular to
    the prism axis (a triangular floor/top) has no such edge, so pushing one of
    *its* edges out would shear it instead — that case must add a coplanar strip
    (a box bump), not translate/extend."""
    n = push_normal.normalized()
    verts = neighbour.vertices
    m = len(verts)
    for i in range(m):
        e = verts[(i + 1) % m] - verts[i]
        if e.length() > 1e-9 and abs(QVector3D.dotProduct(e.normalized(), n)) > 0.999:
            return True
    return False


def _corner_dragged(face: Face, rim: set, push_normal: QVector3D) -> bool:
    """Whether a prism-cap translate moving the ``rim`` positions along
    ``push_normal`` would bend ``face`` at one of them — any of its vertices
    on the rim that isn't a straight-through point of an edge running with
    the push."""
    n = push_normal.normalized()
    for loop in [face.vertices, *face.holes]:
        m = len(loop)
        for i, v in enumerate(loop):
            if _key(v) not in rim:
                continue
            a, b = loop[i - 1] - v, loop[(i + 1) % m] - v
            if (a.length() < 1e-9 or b.length() < 1e-9
                    or abs(QVector3D.dotProduct(a.normalized(), n)) < 0.999
                    or abs(QVector3D.dotProduct(b.normalized(), n)) < 0.999):
                return True
    return False


# The smallest extrusion that still moves geometry: anything below the mesh's
# weld resolution (1e-4, ~0.1 mm) would weld the top loop onto the base loop
# vertex-by-vertex and degenerate the wall quads. Treated as a no-op push.
_MIN_EXTRUDE = 2e-4

#: Below this many pixels between press and release, the "drag" was a
#: jittery click, not a stroke: the release belongs to the click-click
#: rhythm and must not commit. Same release-vs-click disambiguation as
#: Follow Me (tools/followme.py), same threshold.
_DRAG_PX = 6.0




def _paint_of(face) -> dict:
    """The base face's paint, ready to stamp on the geometry a push creates.

    The material extrudes with the shape: pull a textured rectangle
    up and the four sides come out textured too, not bare. Only the moved cap
    inherited it here, so a pushed rectangle gave a box with one painted face
    (Marco, 2026-08-27).

    The texture's per-face ``uvw`` is deliberately NOT carried. It is a
    world→UV map fitted in the BASE's plane, so evaluating it on a wall that
    stands up out of that plane leaves the image constant along the extrusion
    — the texture smears into stripes. Dropped, each new face falls to the
    default planar projection in its OWN plane at the material's tile size,
    which is what a .skp reader draws; ``planar`` says so out loud, so the .skp
    exporter writes the default projection instead of pinning a matrix.

    The cap is not handled here: it is the base's continuation, keeps the full
    attrs (``uvw`` included), and so keeps the exact texture placement — a
    translation along the normal leaves an in-plane map unchanged.
    """
    attrs = face.attrs or {}
    paint = {k: attrs[k] for k in PAINT_KEYS if k in attrs}
    tex = paint.get("texture")
    if tex:
        paint["texture"] = {**{k: v for k, v in tex.items() if k != "uvw"},
                            "planar": True}
    return paint


def _seam_planes_along(mesh, segments) -> list:
    """``(origin, normal)`` of each plane where an edge along ``segments``
    parts two coplanar faces facing the same way with the same paint."""
    out = []
    for e in edges_along(mesh, segments):
        if len(e.faces) != 2:
            continue
        fa, fb = e.faces
        if (fa.interior or fb.interior
                or (fa.attrs or {}) != (fb.attrs or {})
                or QVector3D.dotProduct(fa.normal().normalized(),
                                        fb.normal().normalized()) < 0.9999):
            continue
        out.append((fa.centroid(), fa.normal()))
    return out


def _faces_window(faces):
    """The box around ``faces`` grown by 1 cm (plus a relative term far from
    the origin), or ``None`` for none — every crack then, as before."""
    xs, ys, zs = [], [], []
    for f in faces:
        for lp in (f.loop, *f.hole_loops):
            for v in lp:
                p = v.position
                xs.append(p.x()); ys.append(p.y()); zs.append(p.z())
    if not xs:
        return None
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    m = 0.01 + 1e-6 * max(abs(c) for c in lo + hi)
    return (lo[0] - m, lo[1] - m, lo[2] - m, hi[0] + m, hi[1] + m, hi[2] + m)



def _face_shape(face) -> tuple:
    """Which way round a face is wound does not matter here: whether the
    rebuild handed back the same face, outline and holes."""
    def loop(pts):
        pts = list(pts)
        return min(_canon_loop(pts), _canon_loop(pts[::-1]))
    return (loop(face.vertices), frozenset(loop(h) for h in face.holes),
            face.interior)

class PushPullTool(Tool):
    name = "Push / Pull"
    #: P is the usual key for this tool (Marco, 2026-09-10). U, the one
    #: IngeTrazo used until today, stays as a second
    #: shortcut on this same action — a decade of muscle memory is worth a
    #: line of code, and it costs nothing: P is what the card says.
    shortcut = "P"
    shortcut_alt = "U"
    description = (
        "Push or pull a face to extrude it into a solid or cut it "
        "back.")
    uses_snap = False  # picks a face to extrude; no snap markers
    hover_group_edges = True  # …but its distance infers to a group's edge too
    vcb_label = "Distance"
    # Preview lines in the normal edge colour, not the loose orange rubber band,
    # and depth-tested so the forming box hides its own back edges.
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = True
    # The sweep is an OVERLAY, with no material around it to hide anything: a
    # recess drew all four of its walls, and the ones between the eye and the
    # pocket came out back-side-on, in back-face blue, over the shape the user
    # is forming (Marco, 2026-08-27). Real geometry never shows that because
    # the solid hides them. Culling the faces that point away is the same
    # result, and it costs a dot product each.
    preview_cull_back = True

    # Last committed distance (signed along the base's outward normal), shared
    # across activations: double-click repeats it on another face, as
    # push/pull users expect.
    last_distance: float | None = None

    def __init__(self) -> None:
        self.hovered_face: Face | None = None
        self.base_face: Face | None = None
        self.extrusion: float = 0.0  # signed distance along normal
        self.dragging: bool = False
        # Ctrl held = "push/pull a copy": the base face stays in place (a slab
        # division), the extrusion stacks as a new segment instead of growing
        # the neighbours — the classic way to stack floors.
        self._keep_base: bool = False
        # A Ctrl TAP hands the operation over to the modifier: the starting
        # face stays put on THIS push, which is then spent (the classic
        # one-shot modifier, like Copy in Move). `_ctrl_used` remembers that
        # Ctrl was held when the gesture began, so its release does not
        # toggle the mode on the way out.
        self._keep_mode: bool = False
        self._ctrl_used: bool = False
        # Deepest allowed inward push (positive, along −normal), computed at
        # drag start; None = unbounded. The "Offset limited to" clamp.
        self._limit_in: float | None = None
        # The Group whose face is being pushed (None = the loose mesh). The
        # machinery can run on a group's isolated mesh, but the GESTURE no
        # longer offers it: a face inside a group you have not opened is not
        # pushable. See _refuse_closed_group.
        self._group = None
        self._hover_group = None
        # The preselection arm: activated with EXACTLY one loose-mesh Face
        # selected, the tool locks onto it (the SketchUp workflow) — the
        # hover shade goes up at once, idle hovers do not steal it, and the
        # first click ANYWHERE starts the drag on it. Disarms when a drag
        # starts, on _reset (Esc, deactivate, commit), and when the armed
        # face is no longer in the mesh (undo) — the next idle hover then
        # picks normally again.
        self._selected_arm: bool = False
        # Whether the base face is embedded in a solid (its boundary edges are
        # shared), so an inner face pushed in is a recess (window/door pocket).
        self._attached: bool = False
        # A prism cap is every edge backing onto a perpendicular wall — the push
        # is a clean translation of the cap (walls following through shared
        # vertices) rather than a strip-by-strip extrude.
        self._prism_cap: bool = False
        self._drag_pre_oriented: bool = False
        self._anchor: QVector3D | None = None  # fixed centroid for measuring extrusion
        # Where the face was clicked, on its plane: the drag measures from
        # here (see _grab_point).
        self._grab: QVector3D | None = None
        self._normal: QVector3D | None = None
        self._cap_positions: list[QVector3D] = []  # original cap vertices
        # The clean model under a STAGED preview (see _show_staged_preview):
        # captured before the drag's first stage and kept until the drag ends
        # — restored whenever a staged model goes back to clean (a restage,
        # the overlay, Esc, a tool switch, a pipeline commit), and the undo
        # state of a commit that keeps the stage. The selection rides along:
        # the stage deletes the base face, which drops it from the selection.
        self._preview_snapshot: dict | None = None
        self._preview_selection: set = set()
        # How much of ``extrusion`` the prism preview has already applied to
        # the model, so a frame moves only the delta and the revert knows the
        # total to undo, and the very Vertex OBJECTS it moves.
        self._prism_applied: float = 0.0
        self._prism_verts: list = []
        # ---- Staged preview -------------------------------------------------
        # The distance the staged result was built at (None = the model is
        # NOT staged: the one indicator _revert_preview restores on), where
        # its cap currently sits, the new cap-plane Vertex OBJECTS a frame
        # slides (with their staged positions and slide rates — see
        # _slide_rate), and the open interval of
        # distances the slide stays exact in. Kept apart from the prism fields:
        # the per-frame _revert_prism_preview would otherwise undo them.
        self._stage_d: float | None = None
        self._stage_applied: float = 0.0
        self._stage_verts: list = []
        self._stage_pos: list = []
        self._stage_lo: float = 0.0
        self._stage_hi: float = 0.0
        # The faces/edges the stage created: the distance inference skips
        # them, or the drag would lock onto its own moving cap.
        self._stage_new: set = set()
        # Stages left behind when the cursor leaves their interval, at most
        # one per side of the base plane ({sign: record}, see _park_stage), so
        # dragging back and forth restores one instead of re-running the
        # pipeline; and the record the current stage came from (None = not
        # parked yet).
        self._stage_cache: dict = {}
        self._stage_rec: dict | None = None
        # ``(sign, abs(d))`` of the last refused or failed stage: that
        # direction shows the overlay and retries only once the distance has
        # doubled, so a refusal never re-runs the pipeline per frame, and a
        # tiny first frame refused by float noise does not cost the whole
        # direction its live result.
        self._stage_refusal: tuple | None = None
        # A stage slower than _SLOW_STAGE_S: no more stages this drag.
        self._stage_slow: bool = False
        # Levels (along the normal) of the parallel faces over/under the base,
        # collected at drag start: crossing one changes the topology.
        self._plane_levels: list = []
        # ``(id(mesh), mesh._mut_serial)`` after the tool's own last edit while
        # a snapshot is held: anything else touching the mesh mid-drag (File >
        # New, a redo that bypassed on_redo) makes the snapshots stale, and
        # restoring one would resurrect the model it replaced.
        self._stage_serial: tuple | None = None
        # The model point the distance inference is currently locked onto (a
        # corner or a face hit), drawn as a green marker by the viewport overlay.
        self._inference_point: QVector3D | None = None
        self._inference_kind: str | None = None
        # Set when the last _mutate refused the push to keep the solid valid
        # (the BIM-grade guard); _commit surfaces it in the status bar.
        self._refused: bool = False
        self._topped_out: bool = False
        # One "too small to commit" hint per drag: a click that does nothing
        # with no word reads as a broken tool, but repeating it on every tiny
        # click is its own annoyance. Cleared in _reset, so each drag gets one.
        self._tiny_hint_shown: bool = False
        # ---- Press-drag-release --------------------------------------------
        # Where the press landed and where the cursor is now (screen px):
        # the release compares the two to tell a stroke from a jittery click.
        # Drags armed without a real press — the hot-retype replay, the test
        # harness — leave both None, and on_release copes by doing nothing.
        self._press_screen: tuple | None = None
        self._last_screen: tuple | None = None
        # ---- Drag preview -----------------------------------------------
        # A free face and a Ctrl-copy show the naive sweep as an overlay — cap
        # plus wall quads, nothing touched in the mesh. An attached face is
        # STAGED instead (_show_staged_preview): the real pipeline runs once
        # and frames only slide its cap. Running the pipeline per mouse-move
        # cost ~0.3 s a frame on an imported barbecue.
        self._light_faces: list = []
        # The sweep's rings, ``[(base_ring, moved_ring), …]`` (outer first,
        # then holes) — the wireframe is drawn straight off them.
        self._light_rings: list = []
        # ---- Hot retype ------------------------------------------------------
        # The just-committed push, adjustable by typing (on_value): typing a
        # distance undoes that one command and re-commits the push at the
        # typed TOTAL distance — positive keeps the committed direction,
        # negative reverses it — leaving ONE undo step however many retypes.
        # Holds the drag state _commit consumed (the mesh restore is
        # identity-preserving, so the Face object comes back valid), the
        # command that must sit on the undo stack's top, and the committed
        # direction's sign. Armed only where a push actually landed; a
        # click, Esc, a tool change or the user's own undo closes it — the
        # same window contract Rotate already has (tools/rotate.py).
        self._last: dict | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._keep_mode = False      # the modifier arms ONE operation
        self._ctrl_used = False
        # The SketchUp preselection workflow: activated with EXACTLY one
        # Face of the loose mesh selected, the tool arms on it — the first
        # click anywhere starts the drag there, not on whatever sits under
        # the cursor. Anything else (nothing, several items, an edge, a
        # group) leaves the tool idle, as before.
        sel = viewport.scene.selection
        if len(sel) != 1:
            return
        item = next(iter(sel))
        # MeshFace, not the geometry.Face imported at top: the mesh's Face
        # and the legacy one are different classes, and the loose mesh only
        # ever holds the former.
        if not isinstance(item, MeshFace) or item not in viewport.scene.mesh.faces:
            return
        self.hovered_face = item
        self._hover_group = None
        self._selected_arm = True
        viewport.set_hover(item)

    def on_deactivate(self, viewport) -> None:
        self._revert_preview(viewport)
        viewport.set_hover(None)
        viewport.set_suppressed_faces(set())
        self._reset()

    # ---- Spatial input ------------------------------------------------------
    def drag_plane(self, viewport):
        """Mid-drag, the plane through the anchor that CONTAINS the push
        axis and faces the camera — the cursor ray always hits it, so the
        viewport keeps delivering hovers and clicks wherever the cursor
        goes. The ground it used otherwise stops answering above the
        horizon (or when the ray merely grazes it), and then the box froze
        mid-pull and the click on its top was lost: «hago clic aquí para que
        quede fijado… no me deja, tengo que venirme al lateral» (Rafael,
        2026-09-16, camera at ground level). The distance itself is still
        read off the pixel (``_project_to_lock_line``); the plane only has
        to exist. Looking straight along the axis, where no plane contains
        it face-on, the base plane answers as before."""
        if not self.dragging or self._anchor is None or self._normal is None:
            return None
        cam = getattr(viewport, "camera", None)
        if cam is None:
            return None
        forward = cam.target - cam.eye()
        n = self._normal
        side = forward - n * QVector3D.dotProduct(forward, n)
        if side.length() < 1e-6:
            return None
        return QVector3D(self._anchor), side.normalized()

    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        if not self.dragging:
            self._inference_point = None
            self._inference_kind = None
            # The armed preselection outranks the cursor: an idle frame
            # elsewhere must not steal it. A face gone from the mesh (undo
            # took it) disarms and falls through to a normal pick.
            if self._selected_arm and self.hovered_face is not None:
                if self.hovered_face in viewport.scene.mesh.faces:
                    viewport.set_hover(self.hovered_face)
                    return
                self._selected_arm = False
            self.hovered_face, self._hover_group = viewport.pick_face_any(
                ctx.screen.x(), ctx.screen.y())
            # Shade the face that would be pushed, so the target
            # is unmistakable before clicking. A face inside a group that is not
            # open gets NO shading: it is not going to be pushed, and promising
            # it with a highlight is how the wrong thing gets modified.
            viewport.set_hover(None if self._hover_group is not None
                               else self.hovered_face)
            return

        # Tracked before any guard: the release's "was this a stroke" test
        # must know where the cursor is even when the anchor state is not
        # ready to measure an extrusion yet.
        self._last_screen = (ctx.screen.x(), ctx.screen.y())
        if self.base_face is None or self._anchor is None:
            return
        if self._drop_stale_stage(viewport):
            return
        # Ctrl can be pressed/released mid-drag; the live preview follows.
        self._sync_keep_base(ctx.modifiers)
        # Only the prism translation is undone per frame — arithmetic, so
        # inference never sees the forming solid's moving points. A staged
        # result stays put (restoring it every frame is the snapshot cost the
        # stage exists to avoid); the inference skips its geometry instead.
        self._revert_prism_preview(viewport)
        inferred = self._infer_reference_distance(ctx)
        if inferred is not None:
            self.extrusion = inferred
        else:
            grab = self._grab if self._grab is not None else self._anchor
            projected = viewport._project_to_lock_line(
                grab, self._normal, ctx.screen.x(), ctx.screen.y()
            )
            self.extrusion = QVector3D.dotProduct(
                projected - grab, self._normal)
        self._clamp_extrusion(viewport)
        # A clean prism extend/shrink is previewed by MOVING the cap, so the
        # model itself shows the result and nothing of the old shape is left
        # standing. Any other attached face is STAGED: the real commit applied
        # once, then stretched — walls merging and old edges going live, as
        # the commit will leave them. A free face (nothing to merge with) and
        # a Ctrl-copy show the sweep as an overlay — see _build_light_faces.
        if self._prism_cap and not self._keep_base:
            self._show_prism_preview(viewport)
        elif self._attached and not self._keep_base:
            self._show_staged_preview(viewport)
        else:
            self._show_light_preview(viewport)

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        self._last = None            # a click ends the retype window
        # A CLICK latches Ctrl as the gesture's own (see _sync_keep_base): the
        # first click begins the gesture, the second commits it — and a mouse
        # MOVE must never latch it, or the tap dies whenever the hand moves.
        self._sync_keep_base(ctx.modifiers, latch_ctrl=True)
        if not self.dragging:
            face = self.hovered_face
            if face is None:
                return
            if self._hover_group is not None:
                self._refuse_closed_group(viewport)
                return
            self.base_face = face
            self.extrusion = 0.0
            self.dragging = True
            self._group = self._hover_group
            # The press pixel: a release far enough from it commits
            # (on_release); one on the spot is the click-click rhythm's own
            # second beat, not a stroke.
            self._press_screen = (ctx.screen.x(), ctx.screen.y())
            self._last_screen = self._press_screen
            self._selected_arm = False  # a drag exists; the arm is spent
            target = self._target_scene(viewport.scene)
            # Establish the outward invariant ONCE per drag, before anchor and
            # normal are captured. The preview restores its own snapshot (taken
            # after this), so every frame sees an already-oriented mesh and
            # _mutate_inner skips the per-frame parity pass — the drag on the
            # eye model lagged at ~4 fps re-orienting the same mesh each frame.
            # Scoped to the pushed solid: a group of welded bricks holds many,
            # and the others are not this push's business.
            orient_outward(target.mesh, only=(face,))
            self._drag_pre_oriented = True
            self._anchor = face.centroid()
            self._normal = self._outward_normal(face, target.mesh)
            self._grab = self._grab_point(viewport, ctx)
            self._attached, self._prism_cap = self._classify_base(target)
            self._cap_positions = self._cap_loop_positions(face)
            self._prism_verts = self._cap_vertices(target)
            self._compute_inward_limit(target)
            self._compute_plane_levels(target)
            self._preview_snapshot = None
            # The live preview takes over from the hover shade now.
            viewport.set_hover(None)
            viewport.update()
            return

        # Already dragging — second click commits.
        if abs(self.extrusion) < _MIN_EXTRUDE:
            # No-op extrusion; just stay in drag mode so the user can keep
            # going — but say so once: a click that does nothing with no
            # word reads as a broken tool.
            if not self._tiny_hint_shown:
                viewport.flash_status(tr(
                    "Too small a push — drag further or type a distance"), 4000)
                self._tiny_hint_shown = True
            return
        self._commit(viewport)

    def _grab_point(self, viewport, ctx: ToolContext) -> QVector3D | None:
        """The clicked spot on the face's plane, or ``None`` (the centroid
        then stands in).

        The drag is measured along the line through this point: the cursor
        stays on it. Through the centroid instead, a click near a corner of
        a 12 m slab read -3.39 m for a 0.3 m pull, and a ring's centroid lies
        in its hole -- 1 m of cursor gave 0.13 m walls (tutorial hunt 2,
        A13/B5)."""
        hit = getattr(viewport, "_ray_hit_plane", None)
        if hit is None or self._anchor is None or self._normal is None:
            return None
        return hit((ctx.screen.x(), ctx.screen.y()),
                   (self._anchor, self._normal))

    def on_double_click(self, ctx: ToolContext) -> None:
        """Repeat the last committed distance on the face under the cursor,
        as push/pull users expect. Works both as a fresh double-click (the
        first press
        already locked the face) and right after a commit (the next quick
        click arrives as a double-click)."""
        viewport = ctx.viewport
        last = PushPullTool.last_distance
        if last is None:
            self.on_click(ctx)
            return
        self._sync_keep_base(ctx.modifiers, latch_ctrl=True)
        if not self.dragging:
            face, grp = viewport.pick_face_any(ctx.screen.x(), ctx.screen.y())
            if face is None:
                return
            if grp is not None:
                self._refuse_closed_group(viewport)
                return
            self.base_face = face
            self.dragging = True
            self._group = grp
            target = self._target_scene(viewport.scene)
            orient_outward(target.mesh, only=(face,))
            self._drag_pre_oriented = True
            self._anchor = face.centroid()
            self._normal = self._outward_normal(face, target.mesh)
            self._grab = self._grab_point(viewport, ctx)
            self._attached, self._prism_cap = self._classify_base(target)
            self._cap_positions = self._cap_loop_positions(face)
            self._prism_verts = self._cap_vertices(target)
            self._compute_inward_limit(target)
            self._compute_plane_levels(target)
            self._preview_snapshot = None
            self._selected_arm = False  # never armed once a drag exists
        elif abs(self.extrusion) > _MIN_EXTRUDE:
            # Mid-drag with a real distance: treat as the commit click.
            self._commit(viewport)
            return
        self.extrusion = last
        self._clamp_extrusion(viewport)
        self._commit(viewport)

    def on_release(self, viewport) -> None:
        """Left button up mid-drag: a press-drag-release stroke commits the
        push at the distance the drag built — the way every drag tool ends.

        The contract mirrors Follow Me (tools/followme.py): only a release
        that moved ``_DRAG_PX`` from the press is a stroke. A stationary or
        jittery release is the starting click's own and leaves the drag
        open, so the click-click rhythm still works; a release trailing a
        commit, an Esc or a tool change finds ``dragging`` False and does
        nothing."""
        if not self.dragging:
            return
        a, b = self._press_screen, self._last_screen
        if a is None or b is None:
            return          # drag armed without a real press (retype replay)
        if math.hypot(b[0] - a[0], b[1] - a[1]) < _DRAG_PX:
            return          # jitter, not a stroke: never a commit
        # Ctrl re-read LIVE: the copy decision is the user's at the release,
        # not whatever the press carried. The release is a commit, so it
        # latches like the commit click does — and a tapped keep mode
        # (#322) still holds when no key is down.
        self._sync_keep_base(QApplication.queryKeyboardModifiers(),
                             latch_ctrl=True)
        if abs(self.extrusion) < _MIN_EXTRUDE:
            if not self._tiny_hint_shown:
                viewport.flash_status(tr(
                    "Too small a push — drag further or type a distance"), 4000)
                self._tiny_hint_shown = True
            return
        # The VCB buffer is NOT cleared here, deliberately: typing mid-drag
        # + release + Enter lands as the hot retype (only _dispatch_tool_click
        # clears it).
        self._commit(viewport)

    def on_value(self, viewport, value) -> bool:
        # Push/Pull only takes a single extrusion length; 3D deltas don't apply.
        if isinstance(value, tuple):
            return False
        if self.dragging and self.base_face is not None:
            if value == 0.0:
                return False
            # A positive value goes the way the user is dragging (default
            # +normal); a negative one reverses it.
            sign = -1.0 if self.extrusion < 0.0 else 1.0
            self.extrusion = sign * value
            self._clamp_extrusion(viewport)
            self._commit(viewport)
            return True
        # Idle: the hot retype — adjust the last push by typing. The typed
        # distance is the TOTAL from the base: positive keeps the committed
        # direction, negative reverses it ("sign" * value). Only the command
        # this tool just committed may be replaced; anything else on top
        # means the user's history moved on and the window is gone.
        last = self._last
        if last is None or value == 0.0:
            return False
        stack = getattr(viewport.history, "undo_stack", None)
        if not stack or stack[-1] is not last["cmd"]:
            self._last = None
            return False
        viewport.history.undo()
        # Replay the push as a drag at the typed distance: restore the state
        # _commit cleared, neutralize the preview bookkeeping, then commit.
        # _anchor/_attached/_prism_verts stay cleared — the commit path
        # never reads them.
        self.base_face = last["face"]
        self._group = last["group"]
        self._keep_base = last["keep_base"]
        self._prism_cap = last["prism_cap"]
        self._normal = last["normal"]
        self._cap_positions = last["cap_positions"]
        self._drag_pre_oriented = last["pre_oriented"]
        self._limit_in = last["limit_in"]
        self.dragging = True
        self.extrusion = 0.0
        self._preview_snapshot = None
        self._prism_applied = 0.0
        self._prism_verts = []
        self._light_faces = []
        self._light_rings = []
        self._infer_cache = None
        self._refused = False
        self._topped_out = False
        self.extrusion = last["sign"] * value
        self._clamp_extrusion(viewport)
        # Re-arms the window where the replay landed (success or top-out);
        # a refusal or a too-tiny value leaves it closed.
        self._commit(viewport)
        return True

    def on_cancel(self, viewport) -> None:
        self._light_faces = []
        self._light_rings = []
        self._revert_preview(viewport)
        viewport.set_hover(None)
        viewport.set_suppressed_faces(set())
        self._reset()
        self._spend_keep_mode(viewport)
        viewport.update()

    def on_undo(self, viewport) -> bool:
        """Ctrl+Z mid-drag abandons the push, like Esc. Undoing history
        underneath a staged preview and then restoring its snapshot would
        resurrect the undone geometry. Idle, the ordinary undo runs."""
        if not self.dragging:
            return False
        self.on_cancel(viewport)
        return True

    def on_redo(self, viewport) -> bool:
        """Redo mid-drag abandons the push first, then lets the redo run (False)
        — on the clean model. Run under a staged preview, it would land on the
        staged result and leave that in the model with no undo entry."""
        if self.dragging:
            self.on_cancel(viewport)
        return False

    # ---- Visual preview -----------------------------------------------------
    # A free face and a Ctrl-copy show the naive sweep as overlay faces
    # (``preview_faces``) plus its own wireframe (``rubber_band_lines``); the
    # commit replaces both with the real stitched geometry. A prism or staged
    # preview shows the model itself and leaves both empty.
    def rubber_band_lines(self):
        """The sweep's edges: the base ring, the moved ring, and one riser per
        corner — for the outer loop and every hole.

        The overlay draws its faces FILLED and nothing else, so without this
        the forming solid slid under the cursor as a flat silhouette with no
        edges, and only snapped into a real box once the drag ended (Marco,
        2026-08-27). The mesh-mutating preview it replaced got its edges for
        free, from the mesh; the overlay has to say them out loud.

        A riser that the commit is going to SOFTEN is left out: pushing a
        circle drew every facet seam of the cylinder's side, so the shape
        arrived streaked with lines and only cleaned up on release (Marco,
        2026-08-27). The same dihedral rule ``_soften_curve_facets`` applies
        afterwards decides it here — read off the sweep's own wall normals,
        no mesh needed — so a circle previews as a smooth cylinder while a
        hexagon keeps the edges it will really have. A circle's own segments
        stay visible either way: the Circle tool does not soften them, only
        the sweep's verticals are.

        The BASE ring is not drawn at all. Those edges belong to the base
        face and are already in the mesh, so the model draws them itself —
        saying them again put a seam across the block the drag was forming,
        because the preview's polygon offset let the repeat win the depth
        test against its own faces (Marco, 2026-08-27).

        They cost a handful of points: the rings are the base face's own
        loops, already built for the sweep. Drawn in ``wireframe_color`` and
        depth-tested (class attributes above), so the box hides its own back
        edges and reads like real geometry rather than a loose rubber band."""
        segs = []
        for low, high in self._light_rings:
            n = len(low)
            if n < 2:
                continue
            # Wall i spans low[i]→low[i+1]; its normal is that edge crossed
            # with the sweep. The riser at corner i divides walls i-1 and i.
            off = high[0] - low[0]
            normals = []
            for i in range(n):
                nv = QVector3D.crossProduct(low[(i + 1) % n] - low[i], off)
                normals.append(nv.normalized() if nv.length() > 1e-12 else None)
            for i in range(n):
                j = (i + 1) % n
                segs.append((high[i], high[j]))
                a, b = normals[i - 1], normals[i]
                if a is not None and b is not None:
                    d = QVector3D.dotProduct(a, b)
                    if self._CURVE_FACET_COS < d < 0.99995:
                        continue          # curve facet: soft once committed
                segs.append((low[i], high[i]))
        return segs

    def preview_faces(self):
        return self._light_faces

    # ---- Drag preview ------------------------------------------------------

    def _build_light_faces(self):
        """The naive sweep of the base face as plain preview polygons: the
        moved cap (holes carried) and one quad per boundary and hole edge.

        This is the *shape* the push makes, without any of the work that makes
        it a valid solid — no stitch, no per-plane rebuild, no guard. Those
        decide how the new geometry MERGES with what is already there, which
        is exactly what you cannot see while the shape is still moving."""
        face = self.base_face
        d = self.extrusion
        self._light_rings = []
        if face is None or self._normal is None or abs(d) < _MIN_EXTRUDE:
            return []
        n = self._normal
        off = n * d
        attrs = dict(face.attrs) if face.attrs else None
        # The walls take the base's PAINT, re-anchored to their own planes —
        # the same thing the commit stamps on them, so the drag shows the
        # material the push is about to produce instead of bare cream.
        wall_attrs = _paint_of(face) or None
        rings = [(list(face.vertices), [p + off for p in face.vertices])]
        rings += [(list(h), [p + off for p in h]) for h in face.holes]
        self._light_rings = rings      # the wireframe reads these back
        cap = Face(rings[0][1], [r[1] for r in rings[1:]], attrs=attrs)
        out = [cap]
        for low, high in rings:
            count = len(low)
            for i in range(count):
                j = (i + 1) % count
                out.append(Face([low[i], low[j], high[j], high[i]],
                                attrs=wall_attrs))
        return out

    def _show_light_preview(self, viewport) -> None:
        """Drop any applied preview and show the sweep as an overlay instead.
        The mesh is left untouched, so the scene version does not move and the
        consolidated buffers are not touched either — the frame costs one small
        preview upload. A held stage is parked first (a no-op once parked):
        a Ctrl tap mid-drag must find it again, not pay for a new one."""
        self._park_stage(viewport)
        self._revert_preview(viewport)
        self._light_faces = self._build_light_faces()
        # Hiding the base face is what lets a drag AWAY FROM THE EYE read as
        # a recess opening instead of a cap buried behind the base. Toward
        # the eye, the sweep covers the base anyway and the frame is
        # identical either way — worth distinguishing, because suppression
        # is the one expensive thing left in a drag frame: a group with a
        # hidden face cannot use its cached chunk, so all of its faces are
        # bucketed in Python (measured at 317 ms cold on the 3054-face
        # barbecue, 13 ms once the triangulation memo is warm). A Ctrl-stack
        # keeps its base, so it never hides it.
        #
        # "Away from the eye" is the CAMERA's question, not the normal's.
        # It used to be ``extrusion < 0`` — into the material along the
        # outward normal — which is the same thing only while the normal
        # points at the viewer. Looking at a face's BACK (an inverted face,
        # or a wall seen from inside the room), a push away from the eye is
        # positive, the base stayed, and the pocket formed invisibly behind
        # it while the commit worked («no se ve cuando hago push para
        # adentro cuando tengo la cara invertida», Marco, 2026-09-18).
        recessing = (self._light_faces and self.base_face is not None
                     and self._attached and not self._keep_base
                     and self._sweeps_away_from_eye(viewport))
        viewport.set_suppressed_faces({self.base_face} if recessing else set())
        viewport.update()

    def _sweeps_away_from_eye(self, viewport) -> bool:
        """Does the sweep move the cap away from the camera — behind the
        base face, where the base would hide it? Without a camera to ask
        (tests, the bridge) the normal's sign answers as it always did."""
        cam = getattr(viewport, "camera", None)
        eye_fn = getattr(cam, "eye", None)
        if eye_fn is None or self._anchor is None or self._normal is None:
            return self.extrusion < 0.0
        off = self._normal * self.extrusion
        return QVector3D.dotProduct(off, self._anchor - eye_fn()) > 0.0

    def _refuse_closed_group(self, viewport) -> None:
        """A face inside a group that has not been opened is not pushable.

        The tool used to push it anyway — an instance even opened a short
        editing session behind your back and shared the result to every copy
        (2026-06-10). In a real drawing that reads as
        the model changing where you did not point: a group is a box, and you
        open a box before reaching inside (Marco, 2026-09-10) — the usual
        convention: double-click the group or component to edit it first.

        Refusing has to SPEAK: a tool that does nothing without a word is the
        one that reads as broken.
        """
        viewport.flash_status(tr(
            "That face belongs to a group — double-click to open it first, "
            "then push inside"), 4000)

    def _target_scene(self, scene):
        """The scene the machinery edits: the real one, or a facade over the
        target group's isolated mesh."""
        return scene if self._group is None else _GroupScene(scene, self._group)

    def _target_mesh(self, scene):
        return self._group.mesh if self._group is not None else scene.mesh

    def _show_prism_preview(self, viewport) -> None:
        """Preview a prism extend/shrink by translating the cap in the MODEL,
        the classic way — the walls follow it and the old shape simply
        is not there any more.

        The overlay cannot do that. It can only ADD faces on top, so pushing
        the end of a block left the original cap's edges cutting across the
        block being formed, and pushing in left the whole original block
        standing around the pocket (Marco, 2026-08-27, with a reference
        modeller beside it for comparison).

        Reversible by ARITHMETIC, not by a snapshot: the frame moves the cap
        by the delta since the last one, and the revert moves it back by the
        total. Snapshots are what made the mesh-mutating preview too slow to
        keep — measured on this machine, capture+restore is 11 ms a frame at
        3k faces and 151 ms at 40k, where translating a cap is a handful of
        points. ``_prism_cap`` is exactly the case where a translation IS the
        operation, so the two always agree.
        """
        self._light_faces = []
        self._light_rings = []
        viewport.set_suppressed_faces(set())
        delta = self.extrusion - self._prism_applied
        if abs(delta) > 1e-12:
            self._move_cap(viewport, delta, self.extrusion)
        viewport.update()

    def _cap_vertices(self, scene) -> list:
        """The Vertex OBJECTS the cap loop stands on, resolved once."""
        keys = {_key(p) for p in self._cap_positions}
        mesh = self._group.mesh if self._group is not None else scene.mesh
        return [v for v in mesh.vertices if _key(v.position) in keys]

    def _move_cap(self, viewport, delta: float, applied: float) -> None:
        """Slide the cap's own vertices by ``delta`` along the normal.

        By IDENTITY, never by position. Resolving them by position each frame
        is what warped Marco's cube (2026-08-27): pushed back until the cap
        sat flush against the far face, its key matched that face's vertices
        too, and the next frame dragged them along — the corner came out
        chamfered. ``MoveVerticesCommand`` carries the same lesson in its
        docstring; this is the cheap inverse it warns about, and holding the
        objects is what makes it safe.
        """
        mesh = self._target_mesh(viewport.scene)
        step = self._normal * delta
        for v in self._prism_verts:
            mesh.move_vertex(v, step)
        # Booked as the TARGET, not as a running sum: adding deltas frame by
        # frame drifts, and the revert has to undo exactly what it applied.
        self._prism_applied = applied
        viewport.scene.version += 1

    def _revert_prism_preview(self, viewport) -> None:
        """Put a translated cap back where it started."""
        if self._prism_applied:
            self._move_cap(viewport, -self._prism_applied, 0.0)

    #: A stage (one pipeline run, snapshot work included) slower than this, in
    #: seconds, ends staging for the drag: leaving every parked interval shows
    #: the overlay, and a release outside them runs the pipeline as before.
    #: One pause per drag on a big model instead of one per reversal.
    _SLOW_STAGE_S = 0.25

    def _show_staged_preview(self, viewport) -> None:
        """Preview an attached push by showing the REAL result: the commit's
        own ``_mutate`` applied to the model once ("stage"), then only its new
        cap vertices slid along the normal per frame ("stretch").

        The overlay cannot shorten a wall, merge it with a coplanar riser or
        take an old edge away, so pushing half of a split top previewed a box
        standing on the old shape, and the shape changed on release (#434).
        Running the pipeline every frame did show it, at ~0.3 s a frame.

        The slide is exact while the cap crosses no "event level" (_stage
        works them out): every face holding a moving vertex is the cap or a
        wall containing the push direction, which stays planar as its
        vertices slide — the _swept_by_push argument. Leaving that interval
        parks the stage and restores the one parked on the cursor's side, or
        stages anew (_enter_stage). A refused or failed stage, or any new one
        once staging proved slow, shows the overlay instead."""
        self._light_faces = []
        self._light_rings = []
        d = self.extrusion
        if abs(d) < _MIN_EXTRUDE:
            # Nothing to show, as the overlay. Parked, not dropped: the
            # cursor is on its way to the other side and may come back.
            self._park_stage(viewport)
            self._revert_preview(viewport)
            viewport.set_suppressed_faces(set())
            viewport.update()
            return
        sign = 1.0 if d > 0.0 else -1.0
        if self._stage_refusal is not None and self._stage_refusal[0] != sign:
            self._stage_refusal = None
        if not self._stage_holds(d) and not self._enter_stage(viewport, sign):
            self._show_light_preview(viewport)
            return
        self._slide_stage(viewport, d)
        # The base face is genuinely gone from the staged model.
        viewport.set_suppressed_faces(set())
        viewport.update()

    def _enter_stage(self, viewport, sign: float) -> bool:
        """The cursor is outside the current stage's interval (or nothing is
        staged): park the current stage, then restore the one parked on this
        side if it holds the distance, else stage anew — unless staging
        proved slow, or this direction was refused at a distance not yet
        doubled. False = show the overlay (the model is left as it was; the
        overlay's revert cleans it)."""
        d = self.extrusion
        self._park_stage(viewport)
        rec = self._stage_cache.get(sign)
        if rec is not None and self._interval_holds(d, rec["d"], rec["lo"],
                                                    rec["hi"]):
            self._unpark_stage(viewport, rec)
            return True
        refusal = self._stage_refusal
        if self._stage_slow or (refusal is not None
                                and abs(d) < 2.0 * refusal[1]):
            return False
        if self._stage(viewport):
            return True
        self._stage_refusal = (sign, abs(d))
        return False

    def _slide_stage(self, viewport, d: float) -> None:
        """Slide the stage's moving vertices to distance ``d``. Placed at
        staged position + rate × offset, not moved by deltas: float32 deltas
        drift frame by frame (place_vertex, issue #163)."""
        if not self._stage_verts or abs(d - self._stage_applied) <= 1e-12:
            return
        mesh = self._target_mesh(viewport.scene)
        off = d - self._stage_d
        for v, (p, rate) in zip(self._stage_verts, self._stage_pos):
            mesh.place_vertex(v, p + rate * off)
        self._stage_applied = d
        self._stage_serial = (id(mesh), mesh._mut_serial)
        viewport.scene.version += 1

    @staticmethod
    def _interval_holds(d: float, stage_d, lo: float, hi: float) -> bool:
        """Whether a stage built at ``stage_d`` with interval ``(lo, hi)``
        shows the commit at distance ``d``: its own distance, or strictly
        inside — kept a weld tolerance clear of the levels, where the commit
        welds the cap onto them."""
        if stage_d is None:
            return False
        if abs(d - stage_d) <= 1e-9:
            return True
        return lo + _STITCH_TOL < d < hi - _STITCH_TOL

    def _stage_holds(self, d: float) -> bool:
        return self._interval_holds(d, self._stage_d, self._stage_lo,
                                    self._stage_hi)

    def _stage(self, viewport) -> bool:
        """Apply the commit's mutation at ``extrusion`` to the clean model
        (capturing it on the drag's first stage, restoring it when the model
        is staged) and resolve what a frame may slide. False — with the clean
        model back — when the push is refused, raises, or would not stretch
        cleanly. A stage slower than _SLOW_STAGE_S makes the drag slow."""
        scene = viewport.scene
        mesh = self._target_mesh(scene)
        t0 = time.perf_counter()
        try:
            if self._preview_snapshot is None:
                self._preview_snapshot = mesh.capture_state()
                self._preview_selection = set(scene.selection)
            elif self._stage_d is not None:
                self._restore_clean(viewport)
            self._mutate(scene)
            ok = not self._refused and self._resolve_stage(mesh)
        except Exception:
            # The commit is guarded by History.execute's rollback; the stage
            # is not, and a pipeline error must not escape a mouse move.
            ok = False
        # The whole pause the user sat through, snapshot work included.
        if time.perf_counter() - t0 > self._SLOW_STAGE_S:
            self._stage_slow = True
        self._refused = False          # the commit decides that for itself
        if not ok:
            if self._preview_snapshot is not None:
                self._restore_clean(viewport)
            return False
        self._stage_d = self._stage_applied = self.extrusion
        self._stage_serial = (id(mesh), mesh._mut_serial)
        scene.version += 1
        return True

    def _resolve_stage(self, mesh) -> bool:
        """After a stage: the moving vertices (new, on the cap plane), the
        open interval ``(lo, hi)`` the slide is exact in, and the new
        faces/edges. False when a face holding a moving vertex would bend.

        The interval is bounded by the nearest event levels: the base plane
        (a reversal), the parallel faces over/under the base (a through
        punch, a flush landing, an overhang), the inward limit, and every
        non-moving vertex of a face the cap drags (a wall's bottom, a
        neighbour's top, a ledge). A stage sitting ON a level is exact only
        at its own distance."""
        snap = self._preview_snapshot
        n, anchor, d = self._normal, self._anchor, self.extrusion
        movers = [v for v in mesh.vertices if v not in snap["vpos"]
                  and abs(QVector3D.dotProduct(v.position - anchor, n) - d)
                  < _STITCH_TOL]
        moving = set(movers)
        levels = [0.0, *self._plane_levels]
        if self._limit_in is not None:
            levels.append(-self._limit_in)
        # The faces each mover drags that keep a fixed vertex (the cap and
        # anything else wholly on the cap plane just translate with it).
        anchored: dict = {v: [] for v in movers}
        for f in {f for v in movers for f in v.faces()}:
            rest = [w for lp in (f.loop, *f.hole_loops) for w in lp
                    if w not in moving]
            if not rest:
                continue
            levels.extend(QVector3D.dotProduct(w.position - anchor, n)
                          for w in rest)
            for lp in (f.loop, *f.hole_loops):
                for w in lp:
                    if w in moving:
                        anchored[w].append(f)
        if any(abs(lv - d) <= _STITCH_TOL for lv in levels):
            # On a level: valid at exactly this distance, nothing to slide.
            self._stage_lo = self._stage_hi = d
        else:
            rates = [self._slide_rate(anchored[v], n) for v in movers]
            if any(r is None for r in rates):
                return False              # a face it drags would bend
            self._stage_lo = max((lv for lv in levels if lv < d),
                                 default=-math.inf)
            self._stage_hi = min((lv for lv in levels if lv > d),
                                 default=math.inf)
            self._stage_verts = movers
            self._stage_pos = [(QVector3D(v.position), r)
                               for v, r in zip(movers, rates)]
        self._stage_new = ((set(mesh.faces) - set(snap["faces"]))
                           | (set(mesh.edges) - set(snap["edges"])))
        return True

    @staticmethod
    def _slide_rate(faces, n: QVector3D):
        """How a moving vertex travels per unit of push, keeping every face
        in ``faces`` (the ones it drags that keep a fixed vertex) flat: the
        push normal when they all contain it (a wall), otherwise the line
        the slanted face shares with the others, scaled to keep pace with
        the cap — the crossing of a cap rim with a slope runs down the
        slope's edge (#434 follow-up). None when no such line exists."""
        normals: list = []
        for f in faces:
            m = f.normal().normalized()
            if all(QVector3D.crossProduct(m, o).length() > 1e-3
                   for o in normals):
                normals.append(m)
        nn = n.normalized()
        slanted = [m for m in normals
                   if abs(QVector3D.dotProduct(m, nn)) >= 1e-3]
        if not slanted:
            return QVector3D(n)           # walls only: straight along n
        if len(normals) == 1:
            m = normals[0]
            line = nn - m * QVector3D.dotProduct(nn, m)
        else:
            line = QVector3D.crossProduct(normals[0], normals[1])
        along = QVector3D.dotProduct(line, nn)
        if line.length() < 1e-9 or abs(along) < 1e-3 * line.length():
            return None                   # the line runs in the cap plane
        rate = line * (QVector3D.dotProduct(n, nn) / along)
        if any(abs(QVector3D.dotProduct(m, rate)) > 1e-6 * rate.length()
               for m in normals):
            return None                   # 3+ faces with no common line
        return rate

    def _park_stage(self, viewport) -> None:
        """Keep the current stage for a return trip: its fields plus a
        snapshot of the staged model, captured the first time it is parked —
        its topology never changes, and re-entry re-places the movers
        absolutely. One per side of the base plane (no interval contains 0,
        a level); a newer stage replaces the older one."""
        if self._stage_d is None or self._stage_rec is not None:
            return
        self._stage_rec = {
            "d": self._stage_d, "lo": self._stage_lo, "hi": self._stage_hi,
            "verts": self._stage_verts, "pos": self._stage_pos,
            "new": self._stage_new, "applied": self._stage_applied,
            "state": self._target_mesh(viewport.scene).capture_state(),
            "sel": set(viewport.scene.selection),
        }
        self._stage_cache[1.0 if self._stage_d > 0.0 else -1.0] = self._stage_rec

    def _unpark_stage(self, viewport, rec: dict) -> None:
        """Show a parked stage again: one restore. restore_state resets every
        captured object and the lists, so whatever the model holds now —
        clean, or the other side's stage — needs no clean restore first."""
        scene = viewport.scene
        mesh = self._target_mesh(scene)
        mesh.restore_state(rec["state"])
        scene.selection.clear()
        scene.selection.update(rec["sel"])
        self._stage_d, self._stage_lo, self._stage_hi = (
            rec["d"], rec["lo"], rec["hi"])
        self._stage_verts, self._stage_pos, self._stage_new = (
            rec["verts"], rec["pos"], rec["new"])
        self._stage_applied = rec["applied"]
        self._stage_rec = rec
        self._stage_serial = (id(mesh), mesh._mut_serial)
        scene.version += 1

    def _restore_clean(self, viewport) -> None:
        """Back to the clean model the stages are built on, and its
        selection. The current stage is dropped; a parked copy survives."""
        scene = viewport.scene
        mesh = self._target_mesh(scene)
        mesh.restore_state(self._preview_snapshot)
        scene.selection.clear()
        scene.selection.update(self._preview_selection)
        self._clear_stage()
        self._stage_serial = (id(mesh), mesh._mut_serial)
        scene.version += 1

    def _clear_stage(self) -> None:
        """Forget the current stage (the model's state is the caller's)."""
        self._stage_d = None
        self._stage_applied = 0.0
        self._stage_verts = []
        self._stage_pos = []
        self._stage_new = set()
        self._stage_rec = None

    def _staged_command(self, viewport):
        """The commit of a held stage that already IS the result at
        ``extrusion``: the cap slid there, the staged model captured as the
        command's result and the clean snapshot as its undo state. Two
        snapshots and a restore instead of a pipeline run, and the commit is
        exactly the last frame. None when the pipeline must run: nothing
        staged, Ctrl, outside the interval, a stale snapshot."""
        if (self._stage_d is None or self._keep_base
                or self._drop_stale_stage(viewport)
                or abs(self.extrusion) < _MIN_EXTRUDE
                or not self._stage_holds(self.extrusion)):
            return None
        self._slide_stage(viewport, self.extrusion)
        mesh = self._target_mesh(viewport.scene)
        cmd = SnapshotMutation.from_states(
            self._preview_snapshot, mesh.capture_state(),
            mesh=self._group.mesh if self._group is not None else None)
        # The command owns the snapshots now: nothing is restored.
        self._preview_snapshot = None
        self._preview_selection = set()
        self._stage_cache = {}
        self._clear_stage()
        self._refused = False
        return cmd

    def _drop_stale_stage(self, viewport) -> bool:
        """Something other than this tool edited the mesh while a snapshot is
        held (File > New, a redo that bypassed on_redo): the snapshots no
        longer describe the model, so the drag ends WITHOUT restoring one.
        True when dropped."""
        if self._preview_snapshot is None:
            return False
        mesh = self._target_mesh(viewport.scene)
        if self._stage_serial == (id(mesh), mesh._mut_serial):
            return False
        viewport.set_suppressed_faces(set())
        self._reset()
        viewport.update()
        return True

    def _revert_preview(self, viewport) -> None:
        """Back to the clean model: the prism slid back, a staged model
        restored (its stage dropped, not parked). The overlay calls this every
        frame, so a model that is already clean must cost nothing: only a
        staged one is restored, and the snapshot stays for the drag."""
        self._revert_prism_preview(viewport)
        if self._drop_stale_stage(viewport):
            return
        if self._stage_d is not None:
            self._restore_clean(viewport)

    def inference_marker(self):
        """Return ``(world_point, kind)`` for the marker the viewport draws
        when the distance inference is locked onto model geometry, or
        ``None``. ``kind`` is ``"vertex"``, ``"edge"`` or ``"face"`` — drawn
        and labelled like the endpoint / on-edge / on-face snaps."""
        if not self.dragging or self._inference_point is None:
            return None
        return self._inference_point, self._inference_kind

    def inference_guide_lines(self):
        """The «level with that point» reference segment, from the geometry
        the distance inference locked onto to the moving cap, as
        ``(reference, moved_anchor, kind)`` — ``[]`` while nothing is
        engaged."""
        # The inference point FIRST: the hot-retype replay arms a drag with no
        # anchor, and the hook must stay [] there, never evaluate anchor math.
        if self._inference_point is None or not self.dragging:
            return []
        moved = self._anchor + self._normal * self.extrusion
        return [(self._inference_point, moved, self._inference_kind)]

    def value_label(self):
        """Return ``(text, midpoint_world)`` for the floating distance label.
        Uses the anchor captured at drag start, which stays fixed even while a
        prism cap deforms the real geometry live."""
        if not self.dragging or self._anchor is None:
            return None
        midpoint = self._anchor + self._normal * (self.extrusion * 0.5)
        return (fmt_len(abs(self.extrusion)), midpoint)

    # ---- Internals ----------------------------------------------------------
    def _compute_inward_limit(self, scene) -> None:
        """How far the face can be pushed *into* the solid before the sweep
        would shoot past blocking geometry — the "Offset limited to" rule.

        A blocker is a parallel face on the material side (−normal: solids are
        committed outward) that overlaps the base loop laterally but can't be
        punched (the loop is not strictly inside it — those are through-hole
        targets and stay unbounded; the punch stops at them on its own).
        Pushing exactly *to* the limit is allowed: landing flush dissolves or
        opens the geometry (collapse a box flat, cut a notch through a floor).

        A second, *lateral* bound: the depth at which the swept loop would
        first leave the solid through a **non-parallel** boundary face (push a
        triangular prism's long wall inward and the sweep exits through a
        slanted wall long before any parallel blocker). Beyond that depth the
        result isn't representable without boolean subtraction, so the push
        clamps there — the solid stays a solid.

        Stored in ``self._limit_in``; ``None`` = unbounded."""
        self._limit_in = None
        if not self._attached or self.base_face is None:
            return
        n = (self._normal if self._normal is not None
             else self.base_face.normal()).normalized()
        anchor = (self._anchor if self._anchor is not None
                  else self.base_face.centroid())
        base_xy = _project_loop_2d(self.base_face.vertices, n)
        for g in scene.faces:
            if g is self.base_face:
                continue
            gn = g.normal().normalized()
            if abs(QVector3D.dotProduct(gn, n)) < 0.999:
                continue  # not parallel
            dist = QVector3D.dotProduct(anchor - g.centroid(), n)
            if dist <= 1e-6:
                continue  # coplanar or on the outward side
            back_loop = [v - n * dist for v in self.base_face.vertices]
            if loop_inside_face(g, back_loop):
                continue  # a through-hole target, not a blocker
            if not _loops_overlap_2d(base_xy, _project_loop_2d(g.vertices, n)):
                continue  # laterally elsewhere (another building's wall)
            if self._limit_in is None or dist < self._limit_in:
                self._limit_in = dist

        # Immediate lateral exit: a backing wall that leans *away* from the
        # push (−n has a component out of it) overflows at any depth — the
        # long wall of a triangular prism can't move inward at all without
        # boolean subtraction. Limit 0 (the push becomes a no-op).
        # The lean is judged in metres, not as a bare cosine: how far the
        # wall's far end strays from square. Coordinates saved in single
        # precision tilt a narrow wall's normal by ~2e-5 — the 15 mm top of a
        # board read as leaning away and its corner could not be cut through
        # (#710) — while the strayed distance is a fraction of a micron.
        direction = -n
        mesh = scene.mesh
        for loop in [self.base_face.loop] + self.base_face.hole_loops:
            cnt = len(loop)
            for i in range(cnt):
                ed = mesh.find_edge(loop[i], loop[(i + 1) % cnt])
                if ed is None:
                    continue
                for g in ed.faces:
                    if g is self.base_face or g.interior:
                        continue
                    gn = g.normal().normalized()
                    if abs(QVector3D.dotProduct(gn, n)) > 0.999:
                        continue  # parallel/coplanar: not a lateral wall
                    lean = QVector3D.dotProduct(direction, gn)
                    if lean <= 1e-6:
                        continue
                    root = loop[i].position
                    depth = max(QVector3D.dotProduct(v - root, direction)
                                for v in g.vertices)
                    if lean * depth > _STITCH_TOL:
                        self._limit_in = 0.0
                        return

        # Lateral exit bound: march inward (−n) from points just inside the
        # base loop and take the first crossing of any non-parallel boundary
        # face. Parallel faces are the blocker/through logic above; interior
        # partitions are not boundary and don't end the solid.
        loop3 = self.base_face.vertices
        u, w = plane_basis(n)
        origin3 = loop3[0]
        loop_xy = [(QVector3D.dotProduct(p - origin3, u),
                    QVector3D.dotProduct(p - origin3, w)) for p in loop3]
        ip_xy = _interior_point(loop_xy)
        ip3 = origin3 + u * ip_xy[0] + w * ip_xy[1]
        samples = [ip3]
        for i, p in enumerate(loop3):
            samples.append(p + (ip3 - p) * 1e-3)
            mid = (p + loop3[(i + 1) % len(loop3)]) * 0.5
            samples.append(mid + (ip3 - mid) * 1e-3)
        lateral = None
        for g in scene.faces:
            if g is self.base_face or g.interior:
                continue
            if abs(QVector3D.dotProduct(g.normal().normalized(), n)) > 0.999:
                continue  # parallel: blocker/through logic owns it
            for tri in g.triangulate():
                for q in samples:
                    t = _ray_triangle(q, direction, tri)
                    if t is not None and t > 1e-4 and (
                            lateral is None or t < lateral):
                        lateral = t
        if lateral is not None:
            # Unlike a parallel blocker (face lands flush on face and
            # dissolves), the lateral contact is an edge-on graze — landing
            # exactly there degenerates the swept walls. Stop a hair short.
            lateral = max(lateral - 1e-3, 0.0)
            if self._limit_in is None or lateral < self._limit_in:
                self._limit_in = lateral

    def _compute_plane_levels(self, scene) -> None:
        """The levels (along the normal, both sides) of every face parallel to
        the base that overlaps it laterally — where a staged preview's
        topology changes: the far face a push punches through, a floor it
        lands flush on, an overhang a pull runs into. Stored in
        ``self._plane_levels``; see _resolve_stage."""
        self._plane_levels = []
        if (not self._attached or self._prism_cap or self.base_face is None
                or self._normal is None):
            return                # never staged: the overlay or the prism
        n = self._normal
        nn = n.normalized()
        base_xy = _project_loop_2d(self.base_face.vertices, nn)
        for g in scene.faces:
            if g is self.base_face:
                continue
            if abs(QVector3D.dotProduct(g.normal().normalized(), nn)) <= 0.999:
                continue  # not parallel
            level = QVector3D.dotProduct(g.centroid() - self._anchor, n)
            if abs(level) <= _STITCH_TOL:
                continue  # the base's own plane: level 0 is always an event
            if _loops_overlap_2d(base_xy, _project_loop_2d(g.vertices, nn)):
                self._plane_levels.append(level)

    def _clamp_extrusion(self, viewport=None) -> None:
        if self._limit_in is not None and self.extrusion < -self._limit_in:
            self.extrusion = -self._limit_in
            if viewport is not None:
                # The usual name is "Offset limited to", where *offset* is
                # the push distance — but here Offset is another tool (F), and
                # in Spanish the message named it: «Equidistancia limitada a
                # 0.02 m» in the middle of a push, with no reason given. A
                # correct limit that reads as a broken tool is a bug of its own
                # (Marco, 2026-09-10: «quiero hacer push para abajo y no me
                # deja»; the limit was 2 cm of material under one corner).
                viewport.flash_status(
                    tr("Push limited to {value} — deeper would leave the "
                       "solid", value=fmt_len(self._limit_in)), 5000)

    def _reference_hidden(self, vp, world) -> bool:
        """Whether ``world`` is a reference the user cannot see: on the
        hidden side of the active section cut, or behind other geometry.

        The snap engine runs both rules over its candidates (the viewport's
        snap scene drops cut-hidden edges; ``_is_occluded`` raycasts the
        rest), but Push/Pull sets ``uses_snap = False`` and its mid-drag
        inference read vertices and edges the eye cannot reach — the extrusion
        lunged to an invisible corner as the cursor crossed it (the "jumpy
        push" reports, #270). X-ray and wireframe show everything:
        ``_is_occluded`` is already False there, and the cut hides its side
        in every style — the same rule the snaps follow."""
        from views.viewport import _active_cut
        sp = _active_cut(vp.scene)
        if sp is not None and sp.side(world) > 1e-6:
            return True
        occluded = getattr(vp, "_is_occluded", None)   # stub viewports in tests
        return occluded is not None and occluded(world)

    def _infer_reference_distance(self, ctx: ToolContext):
        """Distance making the moved face level with the model geometry under the
        cursor — the classic mid-push inference ("push until even with that
        corner / that face"). Reads the *clean* mesh (the caller reverts a prism
        preview first, the vertex cache predates any stage, and a staged
        preview's own faces/edges are skipped), so the forming solid's moving
        points never feed back. A model **vertex** within the snap threshold
        wins first (a precise corner); otherwise the **face** under the cursor
        is used, projecting the ray∩plane hit onto the push axis (level with
        where you point on it).
        Records the engaged point in ``self._inference_point`` for the overlay
        marker. Returns ``None`` when nothing engages."""
        vp = ctx.viewport
        sx, sy = ctx.screen.x(), ctx.screen.y()
        thr = getattr(vp, "snap_threshold_px", 9.0)
        exclude = {_key(p) for p in self._cap_positions}
        best = None
        # Batch-project the candidate vertices ONCE per mesh (positions
        # cached for the whole drag — the clean mesh is constant between
        # reverts). The per-vertex ``_world_to_pixel`` walk projected the
        # WHOLE scene (~250k QMatrix4x4.map calls) on EVERY drag move —
        # 1.3 s per move, the "push sticks" report; paints starved until
        # the hand paused.
        import numpy as np
        cache = getattr(self, "_infer_cache", None)
        if cache is None:
            cache = []
            meshes = ([vp.scene.mesh]
                      + [g.mesh for g in getattr(vp.scene, "groups", [])])
            seen = set()
            for mesh in meshes:
                if id(mesh) in seen:      # shared prototypes: project once
                    continue
                seen.add(id(mesh))
                from core.lazy_mesh import plan_of, PlannedVertices
                plan = plan_of(mesh)
                if plan is not None:
                    # A lazy mesh (experimental engine): its planned
                    # positions, the same vertices in the same order —
                    # pushing beside a plant no longer builds all of it.
                    if len(plan.pos):
                        cache.append((PlannedVertices(plan.pos),
                                      plan.pos.copy()))
                    continue
                # A COPY: a staged preview edits the live list in place, and
                # the rows of ``arr`` must keep naming the same vertices.
                verts = list(mesh.vertices)
                if not verts:
                    continue
                arr = np.array(
                    [[v.position.x(), v.position.y(), v.position.z()]
                     for v in verts])
                cache.append((verts, arr))
            self._infer_cache = cache
        proj = getattr(vp, "_project_px", None)
        for verts, arr in cache:
            if proj is not None:
                px, py, ok = proj(arr)
                d2 = (px - sx) ** 2 + (py - sy) ** 2
                cand = [(int(i), float(d2[i]))
                        for i in np.flatnonzero(ok & (d2 <= thr * thr))]
            else:
                # Stub viewports (tests) expose only the scalar projector.
                cand = []
                for i, vtx in enumerate(verts):
                    pix = vp._world_to_pixel(vtx.position)
                    if pix is None:
                        continue
                    dd = (pix[0] - sx) ** 2 + (pix[1] - sy) ** 2
                    if dd <= thr * thr:
                        cand.append((i, dd))
            for i, dd in cand:
                p = verts[i].position
                if _key(p) in exclude:
                    continue  # the base's own corners would pin the drag to 0
                if (best is None or dd < best[0]) \
                        and not self._reference_hidden(vp, p):
                    best = (dd, QVector3D.dotProduct(
                        p - self._anchor, self._normal),
                        QVector3D(p), "vertex")
        # Tape Measure guides (issue #165): a guide POINT is a corner like
        # any vertex -- the nearest one on screen wins -- and a guide LINE
        # is tried right after, like an edge. They live in ``scene.guides``,
        # outside the mesh, so the vertex scan above never saw them.
        guides = getattr(vp.scene, "guides", None) or []
        for g in guides:
            if getattr(g, "direction", None) is not None:
                continue
            pix = vp._world_to_pixel(g.point)
            if pix is None:
                continue
            dd = (pix[0] - sx) ** 2 + (pix[1] - sy) ** 2
            if dd <= thr * thr and (best is None or dd < best[0]):
                best = (dd, QVector3D.dotProduct(
                    g.point - self._anchor, self._normal),
                    QVector3D(g.point), "guide_point")
        # The origin is a point like a corner (#407): every other tool snaps
        # to it, and pushing "level with the origin" is the usual way back
        # to the ground plane.
        origin = QVector3D(0.0, 0.0, 0.0)
        pix = vp._world_to_pixel(origin)
        if pix is not None:
            dd = (pix[0] - sx) ** 2 + (pix[1] - sy) ** 2
            if dd <= thr * thr and (best is None or dd < best[0]):
                best = (dd, QVector3D.dotProduct(
                    origin - self._anchor, self._normal), origin, "origin")
        if best is not None:
            self._inference_point = best[2]
            self._inference_kind = best[3]
            return best[1]

        line_hit = self._infer_guide_line(vp, guides, sx, sy, thr)
        if line_hit is not None:
            on, dist = line_hit
            self._inference_point = on
            self._inference_kind = "guide_line"
            return dist

        # No corner nearby: the EDGE under the cursor — the usual "On edge"
        # while pushing (Marco's capture, 2026-09-14: the half cylinder
        # pushed until level with the slab's far edge). The point on the
        # edge nearest the cursor ray sets the distance; the base's own
        # edges are not references, nor the ones a staged preview created.
        edge = getattr(vp, "_hover_edge", None)
        project = getattr(vp, "_project_to_lock_line", None)
        if edge is not None and project is not None and edge not in self._stage_new:
            a, b = QVector3D(edge.a), QVector3D(edge.b)
            ab = b - a
            # An edge along the push axis says nothing about how far to push
            # (the guide-line rule): its nearest point clamps to an end, and
            # a box's own vertical edge snapped an inward push back to the
            # top (#839).
            along = (ab.length() > 1e-9 and abs(QVector3D.dotProduct(
                ab.normalized(), self._normal)) > 0.999)
            if (_key(a) not in exclude or _key(b) not in exclude) \
                    and ab.length() > 1e-9 and not along:
                on = project(a, ab, sx, sy)
                t = QVector3D.dotProduct(on - a, ab) / QVector3D.dotProduct(ab, ab)
                on = a + ab * max(0.0, min(1.0, t))
                dist = QVector3D.dotProduct(on - self._anchor, self._normal)
                if abs(dist) >= _MIN_EXTRUDE \
                        and not self._reference_hidden(vp, on):
                    self._inference_point = on
                    self._inference_kind = "edge"
                    return dist

        # No edge either: align to the face under the cursor (its plane).
        # Project the ray∩plane hit onto the push axis. The base face (and
        # anything coplanar with it) reads ~0 distance — guarded out so the
        # push doesn't pin to its own plane; a face the staged preview
        # created (its moving cap, a riser) would pin it to itself.
        pick = getattr(vp, "pick_face_placement", None) or vp.pick_face_any
        face, _grp = pick(sx, sy)
        if (face is not None and face is not self.base_face
                and face not in self._stage_new
                and not (_grp is None and self._borders_base(face, exclude))):
            origin, direction = vp._pixel_to_ray(sx, sy)
            if origin is not None and direction is not None:
                # In world space — a placed component's face lives in its
                # prototype's frame.
                from core.snap import face_plane_world
                fpt, fn = face_plane_world(face, getattr(_grp, "xform", None))
                fn = fn.normalized()
                denom = QVector3D.dotProduct(fn, direction)
                if abs(denom) >= 1e-6:
                    t = QVector3D.dotProduct(fn, fpt - origin) / denom
                    if t > 0:
                        hit = origin + direction * t
                        dist = QVector3D.dotProduct(
                            hit - self._anchor, self._normal)
                        if abs(dist) >= _MIN_EXTRUDE:
                            self._inference_point = hit
                            self._inference_kind = "face"
                            return dist
        self._inference_point = None
        self._inference_kind = None
        return None

    @staticmethod
    def _borders_base(face, base_keys) -> bool:
        """Whether *face* shares an edge with the face being pushed: its
        walls stretch or shrink with the push, so they are part of the
        operation, not a level to push to (#839, @hamzah1985: pushing a
        box's top inward, the cursor crossing the front wall snapped the
        cap back up to where the wall was). Other faces, however far,
        still engage — the classic "push until level with that face"."""
        for lp in (face.loop, *face.hole_loops):
            n = len(lp)
            for i in range(n):
                if (_key(lp[i].position) in base_keys
                        and _key(lp[(i + 1) % n].position) in base_keys):
                    return True
        return False

    def _infer_guide_line(self, vp, guides, sx, sy, thr):
        """The guide LINE under the cursor, as (point on it, push distance):
        the point of the guide nearest the cursor's ray, taken when it lands
        within the snap threshold on screen. A guide parallel to the push
        axis says nothing about how far to push, so it is skipped."""
        lines = [g for g in guides if getattr(g, "direction", None) is not None]
        to_ray = getattr(vp, "_pixel_to_ray", None)
        if not lines or to_ray is None:
            return None
        origin, direction = to_ray(sx, sy)
        if origin is None or direction is None:
            return None
        best = None
        for g in lines:
            gd = getattr(g, "direction", None)
            if gd is None:
                continue
            if abs(QVector3D.dotProduct(gd, self._normal)) > 0.999:
                continue
            # closest points between the guide line and the cursor ray
            w0 = g.point - origin
            a = QVector3D.dotProduct(gd, gd)
            b = QVector3D.dotProduct(gd, direction)
            c = QVector3D.dotProduct(direction, direction)
            d = QVector3D.dotProduct(gd, w0)
            e = QVector3D.dotProduct(direction, w0)
            den = a * c - b * b
            if abs(den) < 1e-12:
                continue
            s_ = (b * e - c * d) / den
            on = g.point + gd * s_
            pix = vp._world_to_pixel(on)
            if pix is None:
                continue
            dd = (pix[0] - sx) ** 2 + (pix[1] - sy) ** 2
            if dd > thr * thr:
                continue
            dist = QVector3D.dotProduct(on - self._anchor, self._normal)
            if abs(dist) < _MIN_EXTRUDE:
                continue
            if best is None or dd < best[0]:
                best = (dd, QVector3D(on), dist)
        return None if best is None else (best[1], best[2])

    @staticmethod
    def _cap_loop_positions(face) -> list[QVector3D]:
        """Every boundary position of ``face`` — outer loop *and* hole rims.
        The prism-translate path moves all of them (a hole rim left behind
        warps the cap into a non-planar holed face), and reference inference
        excludes all of them from snapping."""
        pts = [QVector3D(v) for v in face.vertices]
        for hole in face.holes:
            pts.extend(QVector3D(v) for v in hole)
        return pts

    @classmethod
    def _outward_normal(cls, face, mesh) -> QVector3D:
        """The normal this drag signs ``extrusion`` along: ``face``'s own, or
        the surface's when the face disagrees with it and nothing else can say.

        The tool's whole sign convention rests on the base pointing OUTWARD —
        the recess rule reads "negative = into the material, so hide the base
        and show an opening". ``orient_outward`` establishes that at drag
        start and is the authority whenever it HAS a volume to test parity
        against, so a closed mesh is left to it untouched. A flat sheet has no
        outward at all, and is left alone too.

        What is left is the OPEN shell, where orient_outward has nothing to
        count and leaves every winding as the draw made it. A face that came
        out wound the other way then points INTO the model, a drag into the
        wall reads as positive, the base is never hidden, and the outer face
        stands there covering the pocket forming behind it: pushing a door
        into Marco's cube looked like nothing was happening while the push
        itself worked (cubo.igz, 2026-08-27 — a door disagreeing with all
        five of its coplanar neighbours).

        There, the coplanar faces across the boundary ARE the surface this
        face was cut out of, so they are what it has to agree with; a majority
        settles it, and no coplanar neighbour at all leaves the normal alone.
        """
        if is_closed(mesh) or _mesh_is_flat(mesh):
            return face.normal()
        return cls._surface_normal(face)

    @staticmethod
    def _surface_normal(face) -> QVector3D:
        """``face``'s normal, turned to agree with its coplanar neighbours —
        the surface it was cut out of. See :meth:`_outward_normal` for when
        this is the right question to ask."""
        n = face.normal().normalized()
        on_loop = {id(v) for v in face.loop}
        agree = disagree = 0
        for v in face.loop:
            for edge in v.edges:
                if id(edge.v0) not in on_loop or id(edge.v1) not in on_loop:
                    continue                      # not a boundary edge
                for other in edge.faces:
                    if other is face:
                        continue
                    d = QVector3D.dotProduct(other.normal().normalized(), n)
                    if abs(d) > 0.999:            # the same plane
                        if d > 0:
                            agree += 1
                        else:
                            disagree += 1
        return -n if disagree > agree else n

    def _classify_base(self, scene) -> tuple[bool, bool]:
        """Classify the base face for previewing.

        Returns ``(attached, prism_cap)``:
        - ``attached`` — every edge is shared (embedded in a surface/solid), so
          an inner face pushed in is a recess (hidden so the pocket shows).
        - ``prism_cap`` — every edge backs onto a *perpendicular* wall, so the
          push is a clean prism extend/shrink and can be previewed by live
          translation (walls deform with the cap, clean both ways).

        Hole rims count as edges of the cap too: a hole edge backing onto a
        coplanar inner panel (a rectangle drawn on a wall) breaks prism_cap —
        translating the cap would leave the panel and rim behind. A hole whose
        rim backs onto perpendicular swept walls (a window tube through the
        slab) keeps the clean translate.
        """
        faces = scene.faces
        kinds = []
        for loop in [self.base_face.vertices] + self.base_face.holes:
            n = len(loop)
            kinds.extend(
                classify_push_edge(self.base_face, loop[i], loop[(i + 1) % n],
                                   faces)
                for i in range(n)
            )
        normal = self.base_face.normal()
        attached = all(kind != "free" for kind, _ in kinds)
        # A clean prism-cap translate only applies when every backing wall is
        # *swept* by the push (has an edge along the normal). Otherwise the push
        # is into a cap that would shear — handle that via the extrude path so it
        # adds a box bump instead of dragging the whole cross-section.
        prism_cap = bool(kinds) and all(
            kind == "perp" and nb is not None and _swept_by_push(nb, normal)
            for kind, nb in kinds
        )
        if prism_cap:
            # The translate moves every face carrying a rim position. A face
            # that only touches the rim at a vertex — the next room's corner
            # landing on a wall's edge — shares no edge with the cap, so it
            # isn't a wall the push stretches: dragging its corner skews it.
            # Unless the position only slides along a straight edge of it that
            # runs with the push (a T-point on the host wall's top edge).
            walls = {id(nb) for _, nb in kinds}
            rim = {_key(p) for loop in [self.base_face.vertices]
                   + self.base_face.holes for p in loop}
            prism_cap = not any(
                _corner_dragged(g, rim, normal)
                for g in faces
                if g is not self.base_face and id(g) not in walls)
        return attached, prism_cap

    def _commit(self, viewport) -> None:
        viewport.set_hover(None)  # the hovered face is about to be replaced
        self._light_faces = []
        self._light_rings = []
        viewport.set_suppressed_faces(set())
        # A held stage showing this very distance is kept as the result;
        # otherwise drop the live preview and redo it for real.
        cmd = self._staged_command(viewport)
        if cmd is None:
            self._revert_preview(viewport)
        if self.base_face is None or abs(self.extrusion) < _MIN_EXTRUDE:
            self._reset()
            self._spend_keep_mode(viewport)
            viewport.update()
            return
        # One snapshot wraps the edit *and* the watertight stitch: undo is exact,
        # and it is the identical mutation the live preview just showed. A push
        # aimed at a group snapshots that group's mesh instead.
        self._topped_out = False
        if cmd is None:
            cmd = SnapshotMutation(
                self._mutate_or_top_out,
                mesh=self._group.mesh if self._group is not None else None)
        viewport.history.execute(cmd)
        # The retype window's payload, captured BEFORE _reset clears the drag
        # state (the sign is the direction actually committed — the reduced
        # distance on a top-out). Armed only where a push landed: a refusal
        # left the mesh untouched, so there is nothing to retype.
        last = None
        if self._topped_out:
            viewport.flash_status(tr(
                "Push stopped at {d}: going further would break the "
                "solid", d=fmt_len(abs(self.extrusion))), 4000)
            PushPullTool.last_distance = self.extrusion
            last = self._retype_state(cmd)
        elif self._refused:
            # The guard rolled the push back to keep the solid watertight; tell
            # the user so the no-op isn't silent — long timeout, it's easy to
            # miss and the tool otherwise looks broken.
            viewport.flash_status(
                tr("Push refused: would break the solid (left it unchanged)"),
                6000)
        else:
            PushPullTool.last_distance = self.extrusion  # double-click repeats it
            last = self._retype_state(cmd)
        self._reset()
        self._spend_keep_mode(viewport)
        self._last = last             # arms the retype window, if one opened
        viewport.update()

    def _retype_state(self, cmd) -> dict:
        """The ``_last`` payload: everything a hot retype (on_value, tool
        idle) needs to replay the push _commit is about to finish — the drag
        state _reset clears next line, plus the command to beat on the undo
        stack's top. See the ``_last`` declaration for the window contract."""
        return {
            "cmd": cmd,
            "face": self.base_face,
            "group": self._group,
            "keep_base": self._keep_base,
            "prism_cap": self._prism_cap,
            # _normal can be None on a directly-driven commit (tests); the
            # replay falls back to the face's own, exactly as the original.
            "normal": (None if self._normal is None
                       else QVector3D(self._normal)),
            "cap_positions": list(self._cap_positions),
            "pre_oriented": self._drag_pre_oriented,
            "limit_in": self._limit_in,
            "sign": 1.0 if self.extrusion >= 0.0 else -1.0,
        }

    #: How many halvings the commit tries when the guard refuses the distance
    #: the user dragged to. Each costs a full pipeline run, so this buys a
    #: reachable height for about a second in the worst case — only ever spent
    #: on a push that would otherwise do nothing at all.
    _CLAMP_TRIES = 6

    def _mutate_or_top_out(self, scene) -> None:
        """Commit the push; if the guard refuses the dragged distance, commit
        the furthest one it accepts instead.

        A flush landing the rebuild digests — an annulus pushed exactly level
        with an already-raised neighbour — is refused, and refusing outright
        would leave the user's drag doing nothing. The live preview used to
        carry this: it re-ran the pipeline per mouse-move and remembered the
        last distance that worked. Now that the drag no longer re-runs the
        pipeline per frame there is no such record, so the search happens
        here, where it is paid once and only on a push that was going to be a
        no-op. Bisection finds a closer height than the old sampling did — it
        converges on the true limit rather than on wherever the cursor
        happened to be."""
        self._mutate(scene)
        if not self._refused:
            return
        target = self._target_mesh(scene)
        wanted = self.extrusion
        lo, hi = 0.0, 1.0          # fractions of the dragged distance
        best = None
        for _ in range(self._CLAMP_TRIES):
            mid = (lo + hi) / 2.0
            snap = target.capture_state()
            self.extrusion = wanted * mid
            self._mutate(scene)
            if self._refused or abs(self.extrusion) < _MIN_EXTRUDE:
                target.restore_state(snap)
                hi = mid
            else:
                best = self.extrusion
                target.restore_state(snap)
                lo = mid
        if best is None:
            self.extrusion = wanted
            self._refused = True
            return
        self.extrusion = best
        self._mutate(scene)
        self._topped_out = True

    def _mutate(self, scene, preview: bool = False) -> None:
        """Apply the push and stitch watertight, with a **BIM-grade refusal
        guard**: a push on a closed solid must leave a closed solid (or collapse
        it flat). If the operation would leave the mesh cracked — an ill-defined
        push *through* an interior partition, a hole rim detached from a column
        anchored to it, a degenerate collapse — the result is **refused**: the
        solid is restored untouched rather than committing a non-watertight mesh
        that would poison volume/area takeoff and IFC/STL export. A surface
        modeler commits the mess; a solid modeler feeding a quantity engine
        must not.

        The guard only fires on a mesh that *was* a valid closed solid; a flat
        sheet (a recess in a surface, the first flat→solid extrude) legitimately
        opens, so it is never guarded."""
        self._refused = False
        target = self._target_scene(scene)
        mesh = target.mesh
        before_edges = set(mesh.edges)
        # Pushing a tagged face EXTENDS its BIM object: the walls and cap the
        # extrusion creates join the base's tag (thickening a tagged slab, or
        # raising a wall from a rect the active class stamped, yields a fully
        # tagged solid). Capture before the mutation — the base is consumed.
        base_tag = None
        base_paint = None
        if self.base_face is not None:
            t = self.base_face.attrs.get("ifc")
            if t:
                base_tag = dict(t)
            base_paint = _paint_of(self.base_face)
        before_verts = ({id(v) for v in mesh.vertices}
                        if base_tag is not None or base_paint else None)
        curve_runs = (self._curve_runs(mesh, self.base_face)
                      if self.base_face is not None else [])
        guard = (mesh.capture_state()
                 if is_closed(mesh) and not _mesh_is_flat(mesh) else None)
        fp_before = self._mesh_fingerprint(mesh) if guard is not None else None
        self._mutate_inner(scene, preview)
        if guard is not None and not (is_closed(mesh) or _mesh_is_flat(mesh)):
            mesh.restore_state(guard)
            self._refused = True
            return
        if (fp_before is not None and abs(self.extrusion) >= _MIN_EXTRUDE
                and self._mesh_fingerprint(mesh) == fp_before):
            # The rebuild digested the push back to the starting state (the
            # known holed-face-between-levels class): geometrically a no-op.
            # Flag it so the commit tells the user instead of failing silently.
            self._refused = True
            return
        self._soften_curve_facets(mesh, before_edges)
        self._tag_moved_curves(mesh, curve_runs)
        if base_tag is not None or base_paint:
            # Only faces carrying at least one vertex this push created — the
            # extrusion's own walls/cap. Rebuilt neighbours (an untagged floor
            # plane re-emitted over its OLD vertices) are never touched, and a
            # face that already carries a tag (or its own paint) keeps it. Runs
            # inside the commit's SnapshotMutation (and the reverted preview),
            # so undo is exact.
            #
            # Reached FROM the new vertices instead of by scanning the model:
            # a face is fresh exactly when it holds one, so the pass costs the
            # push rather than the mesh.
            fresh: set = set()
            for v in mesh.vertices:
                if id(v) not in before_verts:
                    fresh.update(v.faces())
            for f in fresh:
                if base_tag is not None and not f.attrs.get("ifc"):
                    f.attrs["ifc"] = dict(base_tag)
                if base_paint and not any(k in f.attrs for k in PAINT_KEYS):
                    f.attrs.update(base_paint)

    @staticmethod
    def _curve_runs(mesh, face) -> list:
        """The base's curves as runs of positions: each stretch of its loops
        whose edges share one curve id (a circle is one closed run, a
        rounded rectangle four open ones). Read before the push."""
        runs = []
        for loop in (face.loop, *face.hole_loops):
            n = len(loop)
            if n < 2:
                continue
            ids = []
            for i in range(n):
                e = mesh.find_edge(loop[i], loop[(i + 1) % n])
                ids.append(getattr(e, "curve", None) if e is not None else None)
            if ids[0] is not None and all(c == ids[0] for c in ids):
                runs.append(([QVector3D(v.position) for v in loop], True))
                continue
            start = next((i for i in range(n) if ids[i] != ids[i - 1]), None)
            if start is None:
                continue
            i = start
            for _ in range(n):
                if ids[i] is not None and ids[i] != ids[i - 1]:
                    pts = [QVector3D(loop[i].position)]
                    j = i
                    while ids[j] == ids[i] and len(pts) <= n:
                        j = (j + 1) % n
                        pts.append(QVector3D(loop[j].position))
                    runs.append((pts, False))
                i = (i + 1) % n
        return runs

    def _tag_moved_curves(self, mesh, runs) -> None:
        """The base's curves, carried to the moved cap: the ring a pushed
        circle leaves on top is a curve again, one click selects it all
        (#626). Only the cap's own edges are looked up -- the cost is the
        curve's, not the model's."""
        if not runs or self._normal is None:
            return
        shift = self._normal * self.extrusion
        for pts, closed in runs:
            moved = [mesh.vertex_at(p + shift) for p in pts]
            if any(v is None for v in moved):
                continue
            pairs = list(zip(moved, moved[1:]))
            if closed:
                pairs.append((moved[-1], moved[0]))
            edges = [mesh.find_edge(a, b) for a, b in pairs]
            if any(e is None or e.curve is not None for e in edges):
                continue
            cid = Mesh.next_curve_id()
            for e in edges:
                e.curve = cid

    @staticmethod
    def _mesh_fingerprint(mesh):
        """Cheap canonical state: counts + the sorted vertex grid keys. Enough
        to detect 'the push dissolved itself back to the original solid'."""
        return (len(mesh.faces), len(mesh.edges),
                tuple(sorted(_key(v.position) for v in mesh.vertices)))

    # The dihedral above which a swept seam reads as a *curve* facet (a
    # cylinder's side) rather than a real corner. cos(31.8°): a 24-side circle
    # (15° steps) softens, a hexagon/octagon (≥45°) keeps its visible edges.
    _CURVE_FACET_COS = 0.85

    def _soften_curve_facets(self, mesh, before_edges) -> None:
        """Hide the *new* edges between two faces that meet at a shallow dihedral
        — the vertical facet seams of a swept curve — so a pushed circle reads as
        a smooth cylinder while its circle outline (and a polygon's flat sides,
        which meet at a real angle) stay visible. Topology-free: only the render
        flag changes."""
        for e in mesh.edges:
            if e in before_edges or e.soft or len(e.faces) != 2:
                continue
            d = QVector3D.dotProduct(e.faces[0].normal().normalized(),
                                     e.faces[1].normal().normalized())
            if self._CURVE_FACET_COS < d < 0.99995:
                e.soft = True

    def _mutate_inner(self, scene, preview: bool = False) -> None:
        """Apply the push to the target mesh (the scene's, or the locked
        group's) and stitch it watertight. Shared by the committed edit
        (wrapped in :class:`SnapshotMutation`) and the live preview, so the
        drag renders exactly what will commit."""
        scene = self._target_scene(scene)
        face = self.base_face
        d = self.extrusion
        # Keep the moved face's outline as a selectable division when it
        # becomes flush with a neighbour. Snapshot positions before either
        # translation or extrusion replaces the face and its vertices.
        normal = self._normal if self._normal is not None else face.normal()
        shift = normal * d
        cap_rim = []
        for loop in (face.loop, *face.hole_loops):
            for i in range(len(loop)):
                cap_rim.append((loop[i].position + shift,
                                loop[(i + 1) % len(loop)].position + shift))

        # A prism cap is exactly a translation of the cap along its normal; the
        # walls follow through shared vertices. Then repair connectivity
        # (welds, T-junctions, collinear) — no coplanar-merge, nothing new is
        # added. Ctrl ("push/pull a copy") must not translate: it stacks a new
        # segment, so it takes the extrude path below with the base kept.
        if (self._prism_cap and not self._keep_base
                and not self._cap_passes_a_wall_vertex(scene, face, d)):
            normal = self._normal if self._normal is not None else face.normal()
            translate_points(scene, {_key(p) for p in self._cap_positions},
                             normal * d)
            seed = list(self._cap_positions) + [p + normal * d
                                                for p in self._cap_positions]
            seedkeys = {_key(p) for p in seed}
            run_stitch(scene.mesh, seedkeys, set(), coplanar_merge=False)
            # A shrink can land the cap flush on a coplanar neighbour — a bump
            # pushed back level with its host wall, or a side flank pushed
            # clear across the bump onto the opposite flank. The weld may then
            # consume the pushed face itself (the coincident pair must vanish,
            # not survive as a zero-thickness fin), so the cleanup can't hinge
            # on it: run the same fixpoint plane rebuild as the extrude path
            # over every face the translation touched.
            if not _mesh_is_flat(scene.mesh):
                fresh = {f for f in scene.mesh.faces
                         if any(_key(v) in seedkeys for v in f.vertices)}
                self._rebuild_planes_fixpoint(scene.mesh, fresh, seedkeys,
                                              removing=d < 0,
                                              keep_edges=cap_rim)
            else:
                # A full collapse flattened the solid. The cap may have landed
                # on a *subdivided* base (hole-bearing cycles never dedupe as
                # identical): it is now a redundant mother over the
                # subdivision — exactly what the flat-drawing heal removes.
                heal_overlapping_faces(scene.mesh)
            # Deferred during drag PREVIEW frames, same as the extrude path
            # below: the state is discarded next frame and the shading is
            # winding-proof, so a parity pass per mouse move only added lag
            # (~10 s/frame on an imported 3k-face barbecue). The commit runs
            # it for real.
            if not preview:
                orient_outward(scene.mesh, only=self._touched_faces(
                    scene.mesh, seedkeys))
            return

        # Establish the outward invariant *up front* instead of trusting history:
        # hand-built or loaded meshes can arrive with mixed winding, and every
        # downstream decision (the wall quads' deterministic winding, the
        # per-plane rebuild's material-side classification) reads face normals.
        # If the base face flips, the drag distance flips with it so the push
        # still goes where the user dragged.
        #
        # PERF: on an OPEN mesh orient never flips a face — it only marks
        # interior partitions for the volumetric rebuild's parity queries — so
        # for open meshes the (expensive) pass is deferred until we know the
        # push takes the solid path at all; a pure sheet push skips it. The
        # per-drag flag skips repeating it every preview frame (the preview
        # snapshot preserves the oriented state). Re-orienting the eye model
        # each frame made the drag lag at ~4 fps.
        entry_closed = is_closed(scene.mesh)
        # ``d`` is signed along the normal the DRAG used, which is the base's
        # surface normal (see _surface_normal) — not necessarily the winding
        # the face carries. Reconcile the two, the same way this already
        # reconciles a face orient_outward flips underneath it: on an open
        # shell the two disagree, and taking the face's word for it swept the
        # push the wrong way, so a door previewed going IN and came out going
        # OUT at the commit (Marco, 2026-08-27).
        pre_normal = (self._normal if self._normal is not None
                      else face.normal())
        if entry_closed and not self._drag_pre_oriented:
            orient_outward(scene.mesh, only=(face,))
        normal = face.normal()
        if QVector3D.dotProduct(normal, pre_normal) < 0:
            d = -d
        allverts = [v.position for v in scene.mesh.vertices]
        # Split the base loop at any existing vertex sitting on one of its edges
        # (a T-junction where the host wall ends and an earlier overhang's floor
        # begins) so each sub-edge is carried by one face and classifies right.
        base = refine_loop_with_points(face.vertices, allverts)
        top = [v + normal * d for v in base]
        # A face with holes (an offset ring — the wall footprint) extrudes its
        # holes too: the inner walls rise and the cap keeps the opening, so a
        # ring lifts as walls-with-thickness, not the whole footprint.
        base_holes = [refine_loop_with_points(h, allverts) for h in face.holes]
        top_holes = [[v + normal * d for v in h] for h in base_holes]
        count = len(base)
        faces = scene.faces
        kinds = [
            classify_push_edge(face, base[i], base[(i + 1) % count], faces)
            for i in range(count)
        ]
        # Ctrl ("push/pull a copy") forces the free-extrusion semantics: the
        # base face stays in place as a slab division and no through-hole is
        # punched — the stacked segment and its belt of edges are the point,
        # the classic behaviour. The solid rebuild still runs: the kept base /
        # inward cap are interior partitions the rebuild preserves, the belt
        # survives as crease boundaries (``keep_keys``), and an inward stack's
        # tube quads dissolve into the boundary faces they overlap instead of
        # festering as opposite-winding coincident pairs that corrupt later
        # parity queries.
        attached_any = all(kind != "free" for kind, _ in kinds)
        attached = attached_any and not self._keep_base
        through = self._find_through_face(face, d, faces) if attached else None
        # "Solid" must be a property of the REGION being pushed, not just the
        # whole mesh: a flat drawing with a box standing elsewhere is 'not
        # flat', but pushing one of the drawing's sheet regions must take the
        # sheet path — the volumetric plane rebuild reads an open sheet's
        # regions as phantoms and deletes the neighbours (xc.igz: pushing a
        # circle∩square lens made the rest of the drawing disappear). A base
        # whose rim (outer + hole loops) backs onto ONLY coplanar faces and
        # whose connected component has open edges is pure sheet; any
        # perpendicular backing (a room raised from the plan, a corner step's
        # walls — matched even across unsplit T-junction edges, which is why
        # this reads ``kinds`` and not raw edge sharing) keeps the solid
        # pipeline.
        sheet_fast = (not entry_closed
                      and all(kind == "coplanar" for kind, _ in kinds))
        if sheet_fast:
            for h in base_holes:
                m = len(h)
                if any(classify_push_edge(face, h[i], h[(i + 1) % m],
                                          faces)[0] != "coplanar"
                       for i in range(m)):
                    sheet_fast = False
                    break
        if sheet_fast and _component_is_closed(scene.mesh, face):
            sheet_fast = False
        was_solid = not _mesh_is_flat(scene.mesh) and not sheet_fast
        if was_solid and not entry_closed and not self._drag_pre_oriented:
            # Open mixed mesh taking the solid path: mark interior partitions
            # for the rebuild's parity (orient never flips faces here).
            orient_outward(scene.mesh, only=(face,))

        before = set(scene.mesh.faces)
        self._cap_cmd = None
        base_attrs = dict(face.attrs)
        if through is None and not attached_any and self._sweeps_a_free_sheet(
                face, base, base_holes, faces):
            # A sheet swept free has no outside to orient against until it is
            # a block, and when it shares an edge with another sheet the block
            # is part of an open piece the orientation pass leaves alone: the
            # base stayed facing into the new block (#550). Wound outward by
            # construction instead — the base faces away from the sweep, the
            # cap and the sides along it.
            if d > 0:
                turn_face_over(face)
            else:
                base.reverse()
                top.reverse()
                for lp in (*base_holes, *top_holes):
                    lp.reverse()
        if through is not None:
            commands = self._through_commands(face, base, through)
        else:
            commands = self._extrude_commands(
                face, base, top, base_holes, top_holes, count, attached
            )
        for cmd in commands:
            cmd.do(scene)
        if (base_attrs and self._cap_cmd is not None
                and self._cap_cmd.face in scene.mesh.faces):
            # The moved cap continues the (consumed) base: same attrs.
            self._cap_cmd.face.attrs = dict(base_attrs)
        far = getattr(self, "_far_cmd", None)
        self._far_cmd = None
        if far is not None and far[1] and far[0].face in scene.mesh.faces:
            far[0].face.attrs = dict(far[1])
        new_faces = set(scene.mesh.faces) - before
        if self._keep_base and attached_any and d < 0:
            # The Ctrl-stack grows *into* the solid: its cap is a deliberate
            # interior division (the inward counterpart of the kept base), not
            # a boundary declaration — mark it so the rebuild preserves it.
            for f in new_faces:
                fn = f.normal().normalized()
                if (abs(QVector3D.dotProduct(fn, normal)) > 0.999
                        and abs(QVector3D.dotProduct(
                            f.centroid() - top[0], normal)) < 1e-4):
                    f.interior = True
        seed = list(base) + list(top)
        for hb, ht in zip(base_holes, top_holes):
            seed += list(hb) + list(ht)
        seedkeys = {_key(p) for p in seed}
        # On a solid, the naive extrude's seams and overlaps are dissolved by the
        # deterministic per-plane rebuild below, so the winding-tolerant coplanar
        # merge (phase 3) stays off. On raw/open geometry (a flat sheet) there is
        # no "outside" to classify against, so the merge still applies there.
        solid = attached_any and was_solid
        # On solids the identical-cycle dedupe waits for the rebuild: a flush
        # collapse's sweep quad lands identical to the face it annihilates
        # with, and only the volumetric classification can tell "keep one"
        # (shared wall) from "drop both" (emptied region).
        run_stitch(scene.mesh, seedkeys, new_faces,
                   coplanar_merge=not solid and not self._keep_base,
                   dedupe=not solid)
        if solid:
            self._rebuild_planes_fixpoint(scene.mesh, set(new_faces), seedkeys,
                                          keep_mode=self._keep_base,
                                          removing=d < 0,
                                          keep_edges=cap_rim)
        # Give any closed solid a consistent outward orientation — every face's
        # normal pointing out. The extrude can otherwise commit a closed solid
        # wound inconsistently (a flipped cap, or the base of a first flat→solid
        # extrude), invisible until you push that face and it extrudes *inward*.
        # PERF: deferred during drag PREVIEW frames — the state is discarded
        # next frame and the face shading is winding-proof (abs), so paying a
        # parity pass per mouse move only made the drag lag; the commit runs
        # it for real. A sheet-path push whose result is still open has
        # nothing to orient either way (open meshes never flip; interior
        # marking is recomputed by the next solid op). What counts is the
        # pushed solid, not the whole mesh: an open piece elsewhere left a
        # new box with its base reversed (#230).
        if not preview:
            touched = self._touched_faces(scene.mesh, seedkeys)
            if (not sheet_fast or is_closed(scene.mesh)
                    or (touched and _component_is_closed(scene.mesh,
                                                         touched[0]))):
                orient_outward(scene.mesh, only=touched)

    def _cap_passes_a_wall_vertex(self, scene, face, d: float) -> bool:
        """Whether shrinking the prism cap by ``d`` carries it past a vertex
        partway up one of its walls — the next room's corner sitting on the
        wall. The translate leaves that vertex where it is, so the wall would
        fold into a spike around it (or a zero-area sliver at a full
        collapse); the extrude path cuts the wall instead."""
        if d >= 0:
            return False
        normal = self._normal if self._normal is not None else face.normal()
        rim = {_key(p) for p in self._cap_positions}
        origin = self._cap_positions[0] if self._cap_positions else None
        if origin is None:
            return False
        walls = []
        for g in scene.mesh.faces:
            if g is face or not any(_key(v) in rim for v in g.vertices):
                continue
            walls.append([QVector3D.dotProduct(origin - v, normal)
                          for v in g.vertices if _key(v) not in rim])
        depths = [t for w in walls for t in w]
        if not depths:
            return False
        far = max(depths)
        if any(1e-6 < t < far - 1e-6 and t < -d + 1e-6 for t in depths):
            return True
        # A full collapse folds each wall onto its far edge. A wall whose far
        # edge carries a third vertex (that corner again) folds into a
        # zero-area sliver instead of vanishing.
        return -d > far - 1e-6 and any(
            sum(1 for t in w if t > far - 1e-6) > 2 for w in walls)

    @staticmethod
    def _sweeps_a_free_sheet(face, base, base_holes, faces) -> bool:
        """Whether ``face`` is a sheet whose whole rim — outline and holes —
        borders only other sheets on its plane or nothing at all: no face off
        its plane (a room's wall beside it) stands on any rim edge."""
        normal = face.normal()
        off_plane = [g for g in faces if g is not face
                     and not _faces_coplanar(normal, g.normal())]
        for lp in (base, *base_holes):
            m = len(lp)
            for i in range(m):
                a, b = lp[i], lp[(i + 1) % m]
                if any(_segment_on_face_boundary(a, b, g) for g in off_plane):
                    return False
        return True

    @staticmethod
    def _touched_faces(mesh, seedkeys: set):
        """The faces carrying one of the operation's seed positions — the
        entry point into the solid(s) it edited, for scoping the orientation
        pass to those components. ``None`` (meaning "the whole mesh") when the
        op left none, so a collapse can never silently skip orientation."""
        from core.topology import KeyMemo
        key = KeyMemo()
        hit = [f for f in mesh.faces
               if any(key(v) in seedkeys for v in f.vertices)]
        return hit or None

    @staticmethod
    def _rebuild_planes_fixpoint(mesh, fresh: set, seedkeys: set,
                                 keep_mode: bool = False,
                                 removing: bool = True,
                                 keep_edges=()) -> None:
        """Deterministic root-fix (path C): recompute each touched plane's
        faces from its edges — the planar arrangement finds every region,
        winding-classification keeps the ones inside the solid and drops
        phantoms outside, and the union dissolves coplanar seams. Seam planes
        (a fresh face coplanar-adjacent to another) cover the strip stacked on
        a wall and the quad overlapping a wall to be notched; crack planes
        cover anything a nested push left unfaced. Shared by the extrude path
        and the prism-translate path (whose flush landings need the same
        volumetric resolution).

        Rebuilt to a **fixpoint**: a plane's classification reads the current
        mesh, so a plane rebuilt while a neighbour still carries its dirty
        phantom can come out wrong — which made the result depend on iteration
        order (set order = the Python hash seed). Treating the faces a rebuild
        adds as fresh re-flags the affected planes next round, and
        ``apply_rebuild`` returning False on a stable plane makes the loop
        terminate. Plane keys are sorted, so the whole pass is
        order-deterministic. No case tree."""
        # The push's own rims, captured by *position* before any rebuild (the
        # objects die as rounds consolidate them): plane edges lying on none
        # of these are the user's hand-drawn subdivisions and survive the
        # union (A.4); edges on them are the op's seams and may dissolve.
        op_rims: list = []
        for f in fresh:
            for lp in (f.loop, *f.hole_loops):
                cnt = len(lp)
                for i in range(cnt):
                    op_rims.append((QVector3D(lp[i].position),
                                    QVector3D(lp[(i + 1) % cnt].position)))
        # Per-face memos (normal, centroid, triangles) and the packed parity
        # set, shared across every plane and round: faces are never mutated in
        # place inside this loop (rebuilds remove + add), so identity-keyed
        # entries stay valid. Without it each plane visit re-ran Newell over
        # the whole mesh — 76k normals per drag frame on the barbecue.
        cache = RebuildCache()
        for _ in range(4):  # converges in 1-2 rounds; hard cap for safety
            # The op's own faces name the solids it may touch, so the plane
            # scans narrow to them instead of walking the whole group.
            cache.seed_faces = set(fresh)
            planes: dict = {}
            for origin, plane_n in seam_planes(mesh, fresh):
                planes.setdefault(plane_key(origin, plane_n)[0],
                                  (origin, plane_n))
            for origin, plane_n in crack_planes(mesh, _faces_window(fresh)):
                planes.setdefault(plane_key(origin, plane_n)[0],
                                  (origin, plane_n))
            # A strip the last round dropped as inside the solid (#94) leaves
            # its rim as a crease in the plane beside it, rebuilt before the
            # strip went: two faces now coplanar, same way, same paint (fuzz
            # prism seed 80). Only a plane with such a seam is looked at again
            # — re-rebuilding every plane along the rim misread the rings'
            # open sheets as material and capped a hole.
            for origin, plane_n in _seam_planes_along(mesh, cache.dropped):
                planes.setdefault(plane_key(origin, plane_n)[0],
                                  (origin, plane_n))
            cache.dropped = []
            changed = False
            for key in sorted(planes):
                origin, plane_n = planes[key]
                before_faces = set(mesh.faces)
                if apply_rebuild(mesh, origin, plane_n, fresh, keep_mode,
                                 removing, op=op_rims, cache=cache,
                                 keep_edges=keep_edges):
                    changed = True
                    # A rebuild replaces every face of the plane, so the
                    # user's own faces there come back as new objects. One
                    # that comes back unchanged is still the user's, not the
                    # op's: counted as fresh, the next round read a free
                    # sheet (a triangle drawn on the ground beside the
                    # solid) as op debris and deleted it (#552).
                    kept = {_face_shape(f) for f in before_faces - fresh}
                    fresh |= {f for f in set(mesh.faces) - before_faces
                              if _face_shape(f) not in kept}
            if not changed:
                break
            fresh = {f for f in fresh if f in mesh.faces}
        # The dissolved seams can leave redundant collinear vertices on the
        # rebuilt faces' borders (the old cap ring's corners); one more
        # connectivity pass collapses them. No merge — rebuild already did.
        run_stitch(mesh, seedkeys, None, coplanar_merge=False)

    def _extrude_commands(self, face, base, top, base_holes, top_holes,
                          count, attached) -> list:
        """Build the naive extrusion of ``face`` to ``top``: a consumed/kept
        base, the moved cap (carrying any holes), one wall quad per boundary
        edge, and an inner wall per hole edge — no special cases. Where a quad
        lands on an existing face's plane (a strip on a wall, a phantom over a
        region being carved away) the per-plane rebuild dissolves it.

        Winding is deterministic: with the base wound outward (the commit
        invariant on solids), ``[a, b, b2, a2]`` is outward for *both* push
        directions — flipping the push flips the quad's geometric normal and
        which side holds material together — and the cap keeps the base's
        winding (+n faces out of an added box and out of a carved pocket
        alike). That is what lets the rebuild trust fresh faces' normals."""
        commands: list = []
        if attached:
            commands.append(DeleteFaceCommand(face))  # base consumed into the solid
        for i in range(count):
            commands.append(AddEdgeCommand(top[i], top[(i + 1) % count]))
        for i in range(count):
            commands.append(AddEdgeCommand(base[i], top[i]))
        cap_cmd = AddFaceCommand(
            list(top), auto=not attached,
            holes=[list(th) for th in top_holes] or None)
        commands.append(cap_cmd)
        # The moved cap is the base's continuation: it inherits its attrs
        # (material, future BIM tag). Remembered so _mutate can stamp the face
        # the command creates when it runs.
        self._cap_cmd = cap_cmd

        # Inner walls: each hole edge raises a wall to the moved cap's opening.
        for hb, ht in zip(base_holes, top_holes):
            hn = len(hb)
            for i in range(hn):
                commands.append(AddEdgeCommand(ht[i], ht[(i + 1) % hn]))
            for i in range(hn):
                commands.append(AddEdgeCommand(hb[i], ht[i]))
            for i in range(hn):
                j = (i + 1) % hn
                commands.append(AddFaceCommand([hb[i], hb[j], ht[j], ht[i]], auto=False))

        for i in range(count):
            j = (i + 1) % count
            commands.append(AddFaceCommand(
                [base[i], base[j], top[j], top[i]], auto=False))

        if attached:
            commands.append(PruneOrphanEdgesCommand(list(base)))
        return commands

    # ---- Through-hole -------------------------------------------------------
    def _find_through_face(self, face, d: float, faces):
        """If pushing ``face`` by ``d`` along its normal reaches a face parallel
        to it on the far side of the solid (the opposite wall), return
        ``(far_face, back_loop)`` — the face to punch and the opening projected
        onto it. Otherwise ``None`` (a blind recess)."""
        fn = face.normal().normalized()
        push = fn if d > 0 else -fn
        origin = face.centroid()
        best = None
        # The far face must overlap the box the push sweeps (the face and its
        # copy |d| along the push): only those reach the normal and the
        # containment tests — every face's Newell normal was computed before,
        # on every push (09-10). Grown far beyond the 1e-4 tolerances.
        swept = list(face.vertices) + [v + push * abs(d) for v in face.vertices]
        sx = [p.x() for p in swept]; sy = [p.y() for p in swept]
        sz = [p.z() for p in swept]
        mg = 0.01 + 1e-6 * max(map(abs, sx + sy + sz))
        w0 = (min(sx) - mg, min(sy) - mg, min(sz) - mg)
        w1 = (max(sx) + mg, max(sy) + mg, max(sz) + mg)
        for g in faces:
            if g is face:
                continue
            gv = g.vertices
            if (max(p.x() for p in gv) < w0[0] or min(p.x() for p in gv) > w1[0]
                    or max(p.y() for p in gv) < w0[1]
                    or min(p.y() for p in gv) > w1[1]
                    or max(p.z() for p in gv) < w0[2]
                    or min(p.z() for p in gv) > w1[2]):
                continue  # nowhere near what the push sweeps
            if abs(QVector3D.dotProduct(fn, g.normal().normalized())) < 0.999:
                continue  # not parallel
            dist = QVector3D.dotProduct(g.centroid() - origin, push)
            if dist <= 1e-4 or dist > abs(d) + 1e-4:
                continue  # coplanar / behind / farther than the push reaches
            back_loop = [v + push * dist for v in face.vertices]
            if loop_inside_face(g, back_loop):
                if best is None or dist < best[0]:
                    best = (dist, g, back_loop, None)
                continue
            # Landing FLUSH on the far face with the opening on its rim — the
            # corner piece left by a rounding arc pushed right through
            # (Marco, 2026-09-15: «debería eliminarme ese triángulo»). Not a
            # hole: the far face is trimmed to what
            # is left of it (the arc becomes its outline) and the cap goes.
            if abs(dist - abs(d)) <= 1e-4:
                remainder = subtract_loop_from_face(g, back_loop)
                if remainder is not None and (best is None or dist < best[0]):
                    best = (dist, g, back_loop, remainder)
        if best is None:
            return None
        return best[1], best[2], best[3]

    def _through_commands(self, face, base, through) -> list:
        """Build the commands for a through-hole: punch the far face, join it to
        the front opening with a tunnel, and sweep the dangling base edges."""
        far_face, back_loop, remainder = through
        count = len(base)
        commands: list = [
            DeleteFaceCommand(face),       # remove the pushed cap (window pane)
            DeleteFaceCommand(far_face),   # re-add the far face with a new hole
        ]
        if remainder is None:
            far_cmd = AddFaceCommand(
                list(far_face.vertices), auto=False,
                holes=[list(h) for h in far_face.holes] + [list(back_loop)],
            )
            commands.append(far_cmd)
            for i in range(count):         # back opening boundary
                commands.append(AddEdgeCommand(back_loop[i], back_loop[(i + 1) % count]))
        else:
            # A notch on the rim: the far face becomes what is left of it;
            # the opening's outline that ran along the old rim is nobody's
            # edge any more and the prune below sweeps it.
            far_cmd = AddFaceCommand(
                list(remainder), auto=False,
                holes=[list(h) for h in far_face.holes])
            commands.append(far_cmd)
        # The rebuilt far face is the same face with a bite out of it: it
        # keeps its paint (test_attrs_survive_corner_notch_through_floor).
        self._far_cmd = (far_cmd, dict(far_face.attrs))
        for i in range(count):             # tunnel verticals
            commands.append(AddEdgeCommand(base[i], back_loop[i]))
        for i in range(count):             # tunnel walls
            j = (i + 1) % count
            commands.append(AddFaceCommand(
                [base[i], base[j], back_loop[j], back_loop[i]], auto=False))
        commands.append(PruneOrphanEdgesCommand(list(base) + list(back_loop)))
        return commands

    def _reset(self) -> None:
        self.hovered_face = None
        self.base_face = None
        self.extrusion = 0.0
        self.dragging = False
        self._attached = False
        self._prism_cap = False
        self._prism_applied = 0.0
        self._prism_verts = []
        self._keep_base = False
        self._limit_in = None
        self._group = None
        self._hover_group = None
        self._selected_arm = False
        self._anchor = None
        self._grab = None
        self._normal = None
        self._cap_positions = []
        self._preview_snapshot = None
        self._preview_selection = set()
        self._clear_stage()
        self._stage_cache = {}
        self._stage_refusal = None
        self._stage_slow = False
        self._plane_levels = []
        self._stage_serial = None
        self._drag_pre_oriented = False
        self._inference_point = None
        self._inference_kind = None
        self._infer_cache = None       # per-drag projected-vertex candidates
        self._refused = False
        self._tiny_hint_shown = False
        self._press_screen = None
        self._last_screen = None
        self._light_faces = []
        self._light_rings = []
        self._last = None             # the retype window closes with the drag

    # ---- Modifier: Ctrl keeps the starting face -----------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        """Swallow the Ctrl press — the tap acts on the RELEASE, where
        ``ctrl_tapped`` tells a tap from the Ctrl of a shortcut (#183) and
        Ctrl+P (Push/Pull's own key) never arms the mode in passing."""
        if key == Qt.Key_Control:
            return True
        return super().on_key(viewport, key, modifiers)

    def on_key_release(self, viewport, key: int) -> bool:
        if key != Qt.Key_Control:
            return False
        if self._ctrl_used:
            self._ctrl_used = False
            return True                  # the gesture's own Ctrl, not a tap
        if not self.ctrl_tapped(viewport):
            return False                 # Ctrl was part of a shortcut
        self._keep_mode = not self._keep_mode
        self._keep_base = self._keep_mode
        viewport.flash_status(tr("Keep the base: on") if self._keep_mode
                              else tr("Keep the base: off"))
        self.refresh_hint(viewport)
        viewport.update()
        return True

    def status_clause(self) -> str:
        # Short on purpose: the clause rides the same line as the hint, and
        # the classic bar spends a whole one on «Ctrl = Crear un nuevo punto
        # de partida». "Keep the base" / "move the base" is the same idea in
        # the tool's own words (base_face, _keep_base).
        return ctrl_clause(self._keep_mode, "keep the base", "move the base")

    def _sync_keep_base(self, modifiers, latch_ctrl: bool = False) -> None:
        """Read Ctrl where it is HELD: it keeps the base face for THIS push
        only, so a gesture begun while Ctrl was down never latches the mode
        (its release finds ``_ctrl_used`` and stops there). A Ctrl tapped on
        its own arms ``_keep_mode`` instead, and that mode stands by itself.

        ``latch_ctrl`` is True only where a CLICK happens — the gesture's
        start and its commit. Whether Ctrl was a TAP is a question about keys,
        and latching on every mouse MOVE answered it with the hand's position
        instead: mid-drag, the first hover after the press claimed that Ctrl
        as the gesture's own, so the mode only toggled with the cursor parked
        — the one case where no hover came in between the press and the release (@pacaeiro, 2026-10-01: «si estoy moviendo
        el ratón mientras hago Ctrl, el Ctrl no altera el estado»). The live follow is unchanged:
        Ctrl held mid-drag still keeps the base for the push in progress."""
        held = bool(modifiers & Qt.ControlModifier)
        if latch_ctrl:
            self._ctrl_used = held
        self._keep_base = held or self._keep_mode

    def _spend_keep_mode(self, viewport) -> None:
        """The Ctrl mode is spent by the push it armed, like Copy in Move
        and Rotate: the bar stops advertising it the moment the push lands
        (or Esc drops it), so the modifier never leaks into the next face."""
        if not self._keep_mode:
            return
        self._keep_mode = False
        self._keep_base = False
        self.refresh_hint(viewport)
