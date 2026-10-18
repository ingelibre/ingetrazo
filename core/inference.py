# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The viewport's snapping inference, in one place.

``Viewport`` had grown a small state machine -- the edge and centre under the
cursor, the reference edge/corner acquired while drawing, the encouraged
points the cursor paused on, the axis and reference locks, the snap search
itself -- threaded through a dozen private attributes and half a dozen
methods. Keeping it beside the widget made every one of those methods read as
part of the drawing surface.

This collaborator owns that state and its rules. The viewport still hands it
the cursor (``_process_hover`` reads the picks through :meth:`acquire`, and
``_build_ctx`` / ``_refresh_snap`` ask :meth:`snap`) and renders what it
decides (``_snap_scene``, ``_draw_overlay``), but the "which point is the
reference, what is encouraged, which axis is locked" bookkeeping lives here.
The dialogue is one-way -- the engine reaches back to the viewport for the
picks, the projections and a repaint, never the other way -- and the viewport
exposes thin delegating properties so the rest of the class, tools,
extensions, the probe and the tests keep reading ``vp._acquired_point``,
``vp.axis_lock`` and friends unchanged.

The two post-processors that used to run on the viewport at the end of
the search -- the axis-source cue (the Tape hovering a model axis) and
the extension hooks -- now run at the end of :meth:`snap`, so what the
viewport draws is what the engine decided, with no second pass.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QVector3D

from core.snap import SnapResult, compute_snap


def _no_snap_fast() -> bool:
    """The viewport's ``INGETRAZO_NO_SNAP_FAST`` switch (batched occlusion
    off, for A/B timing), read at call time to avoid a circular import."""
    from views import viewport as _viewport
    return bool(getattr(_viewport, "_NO_SNAP_FAST", False))


def _magnet_may_leave_plane(tool) -> bool:
    """Whether ``tool``'s axis magnet may infer OFF its drawing plane.

    Only the tools that carry a magnet have an opinion
    (``tools.base.AxisMagnet.magnet_off_plane``: a shape that lives in one
    plane says no, a Line and the free placements say yes); a tool with no
    magnet never runs the detector, so the default leaves the rules exactly
    as they were."""
    rule = getattr(tool, "magnet_off_plane", None)
    return bool(rule()) if callable(rule) else True


class InferenceEngine:
    """Snap-target state the viewport keeps between moves.

    The reference state -- the edge and centre under the cursor, the
    'from point' reference and the soft references held while a segment is
    drawn, the two encouraged points behind it, the axis / reference locks
    and the last snap result -- plus the search that reads them. The dwell
    timer is the one live Qt object here: it turns a pause over a point into
    an encouraged point, so it is parented to the viewport and dies with it.
    """

    def __init__(self, viewport) -> None:
        self.viewport = viewport
        # Arrow-key axis lock: None | "x" | "y" | "z".
        self.axis_lock: Optional[str] = None
        # The snap engine's last answer, kept for the marker and readouts.
        self.last_snap: Optional[SnapResult] = None
        # Reference edge (Down arrow -- parallel / perpendicular): the edge
        # and the mode it was taken in.
        self.reference_edge = None
        self.reference_mode: Optional[str] = None
        # Sticky inference lock (Shift): (direction, color) captured from the
        # active inference, held until Shift is released.
        self._shift_lock: Optional[tuple] = None
        # Last edge under the cursor (candidate for capture) and the centre of
        # the last circle or arc the cursor visited (its edge, or a face it
        # bounds), kept as a reference until another circle takes its place or
        # the tool changes.
        self._hover_edge = None
        self._hover_center = None
        # ``(centre, radius, key, version, source, mesh, group)``.
        self._center_ref = None
        # Edge/face hovered while drawing, held as soft references
        # ("through point" / "perpendicular to face" acquisition). Cleared
        # when no segment is in progress.
        self._acquired_edge = None
        self._acquired_face_normal = None
        # Corner hovered while drawing, held as a soft reference ("from
        # point" / the axis lines that run off it). Cleared when no segment is
        # in progress.
        self._acquired_point: Optional[QVector3D] = None
        # Encouraged points: the last two points the cursor PAUSED on (a
        # corner, a circle's centre). The 'from point' dotted line runs from
        # them -- from both at once where their axis lines cross. Pausing, not
        # merely crossing: sweeping over a vertex on the way somewhere else
        # must not steal the reference.
        self._encouraged: list = []
        self._dwell_point: Optional[QVector3D] = None
        self._dwell_timer = QTimer(viewport)
        self._dwell_timer.setSingleShot(True)
        self._dwell_timer.setInterval(viewport.ENCOURAGE_MS)
        self._dwell_timer.timeout.connect(self._encourage_dwelt)

    # ---- Picking the cursor's neighbourhood ---------------------------------
    def acquire(self, px: float, py: float) -> None:
        """Refresh the hover state :meth:`snap` reads: the edge under the
        cursor, the centre it may encourage, and the soft references held
        while a segment is being drawn.

        Called on every hover, before the tools see it. A tool that does not
        snap (Select, Push/Pull) still gets its hover edge (the highlight),
        but never pays for the centre fit; the drawing references are only
        refreshed while a segment is in progress, so they cannot go stale
        across separate draws."""
        vp = self.viewport
        tool = vp.active_tool
        if tool is not None and (tool.uses_snap
                                 or getattr(tool, "hover_group_edges", False)):
            self._hover_edge = vp.pick_edge_any(px, py)
        else:
            self._hover_edge = vp.pick_edge(px, py)
        if tool is not None and tool.uses_snap:
            # Only the tools that snap can use a centre; Select and Push/Pull
            # never pay for the fit. Hovering the rim ENCOURAGES the centre
            # like a corner: the dotted axis line then runs from it (Marco's
            # capture, 2026-09-14 -- a circle placed in line with another's
            # centre).
            self._hover_center = vp._update_center_ref(px, py)
        drawing = (tool is not None
                   and getattr(tool, "start_point", None) is not None)
        if drawing and tool.uses_snap:
            # Mid-segment: the corner under the cursor is a soft, instant
            # reference (through point / from point), as always.
            corner = vp.pick_vertex(px, py)
            if corner is not None:
                self._acquired_point = corner
        if not drawing:
            self._acquired_edge = None
            self._acquired_face_normal = None
        else:
            if self._hover_edge is not None:
                self._acquired_edge = self._hover_edge
            face, _g = vp.pick_face_placement(px, py)
            if face is not None:
                from core.snap import face_plane_world
                self._acquired_face_normal = face_plane_world(
                    face, getattr(_g, "xform", None))[1]

    # ---- The snap search -----------------------------------------------------
    def snap(self, px_x: float, px_y: float,
             modifiers) -> Optional[SnapResult]:
        """The snap engine's answer for the cursor at ``(px_x, px_y)``.

        THE one code path: both ``_build_ctx`` (mouse motion and clicks) and
        ``_refresh_snap`` (a modifier changing with the hand still) go through
        here, so the :func:`compute_snap` argument list lives in exactly one
        place. Returns ``None`` when the pixel casts no world point (the ray
        misses the plane / the point is behind the camera). A tool that does
        not snap (Select, Push/Pull) gets a ``"none"`` result instead - no
        snap engine, no occlusion raycasts, no marker."""
        vp = self.viewport
        world_raw = vp._world_from_pixel(px_x, px_y)
        if world_raw is None:
            return None
        tool = vp.active_tool
        if tool is not None and not tool.uses_snap:
            return SnapResult(world_raw, "none")
        chain_first = None
        start_pt = None
        if tool is not None:
            chain_first = getattr(tool, "chain_first_point", None)
            start_pt = getattr(tool, "start_point", None)
        snap = compute_snap(
            candidate_world=world_raw,
            candidate_pixel=(px_x, px_y),
            scene=vp._snap_scene(px_x, px_y),
            world_to_pixel=vp._world_to_pixel,
            threshold_px=vp.snap_threshold_px,
            project_onto_line=lambda s, d: vp._project_to_lock_line(
                s, d, px_x, px_y),
            chain_first_point=chain_first,
            start_point=start_pt,
            axis_lock=self.axis_lock,
            shift_held=bool(modifiers & Qt.ShiftModifier),
            reference_edge=self.reference_edge,
            reference_mode=self.reference_mode,
            inference_angle_deg=vp.inference_angle_deg,
            is_occluded=vp._is_occluded,
            are_occluded=None if _no_snap_fast() else vp._occluded_many,
            face_under_cursor=vp._still_face_under(px_x, px_y),
            edge_threshold_px=vp.edge_snap_threshold_px,
            magnetic_axis_deg=getattr(tool, "magnetic_axis_deg", None),
            screen_axis_px=getattr(tool, "screen_axis_px", None),
            acquired_edge=self._acquired_edge,
            acquired_point=self._acquired_point,
            acquired_face_normal=self._acquired_face_normal,
            acquired_points=self._encouraged,
            shift_lock_dir=self._shift_lock[0] if self._shift_lock else None,
            shift_lock_color=self._shift_lock[1] if self._shift_lock else None,
            linear_mode=vp.linear_inference_mode,
            work_plane_normal=vp._work_plane_normal(),
            radial_arm=bool(getattr(tool, "radial_arm", False)),
            axis_in_plane=not _magnet_may_leave_plane(tool),
        )
        snap = self._axis_source_cue(snap, px_x, px_y)
        snap = self._extension_snap(snap, px_x, px_y)
        return snap

    # ---- Post-processors (axis-source cue, extensions) ----------------------

    #: Built-in inferences an extension's may not override: a point with a
    #: name is the user's target, and the snap engine already ranked it.
    _NAMED_SNAPS = frozenset((
        "endpoint", "midpoint", "arc_midpoint", "center", "origin",
        "component_origin", "intersection", "close", "on_edge"))

    def _axis_source_cue(self, snap, px_x: float, px_y: float):
        """Before its first click, a tool that reads the model axes as a
        source (the Tape: ``axis_source``) shows the cursor is ON the red,
        green or blue axis — the classic small square on the axis line.
        Without the cue the axis looked ungrabbable (Marco, testing
        Rafael's guide from an axis, 2026-09-21): the pick worked, nothing
        said so. Only where the engine found nothing better.

        The pick itself stays on the viewport (``pick_axis`` is a general
        pick, the Tape reads it too): the engine calls it, the same shape as
        ``_snap_scene`` / ``pick_face_any``."""
        vp = self.viewport
        tool = vp.active_tool
        empty_space_only = bool(
            getattr(tool, "axis_source_empty_only", False))
        allowed_kinds = (("none",) if empty_space_only
                         else ("none", "on_face"))
        if (snap is None or not getattr(tool, "axis_source", False)
                or getattr(tool, "start_point", None) is not None
                or snap.kind not in allowed_kinds):
            return snap
        name = vp.pick_axis(px_x, px_y)
        if name is None:
            return snap
        from core.snap import AXIS_COLORS
        from core import axes as _axes
        axis = _axes.axis(name)
        o = _axes.origin()
        if empty_space_only:
            foot = vp._project_to_lock_line(o, axis, px_x, px_y)
            if (not vp._axis_source_visible(name, foot)
                    or vp._is_occluded(foot)):
                return snap
        else:
            foot = o + axis * QVector3D.dotProduct(snap.point - o, axis)
        return SnapResult(foot, "on_axis", AXIS_COLORS[name], axis=name)

    def _extension_snap(self, snap, px_x: float, px_y: float):
        """Offer the snap engine's answer to each extension's provider
        (``ExtensionApp.add_snap_provider``); the first that returns a
        :class:`SnapResult` wins. A named point is never overridden, and a
        provider that raises is skipped — it cannot take the cursor away.

        The provider signature is unchanged: ``fn(viewport, snap, px, py)``.
        It is handed the viewport, not this engine, so no plugin has to know
        the snap search moved.

        Careful with the homonym: ``core.snap._extension_snap`` is the
        *geometric* extension inference inside ``compute_snap`` (step 5 of the
        search — an edge's dashed continuation, green connection points);
        this one is the *extension-API* provider hook."""
        vp = self.viewport
        providers = getattr(vp, "_ext_snap_providers", None)
        if not providers or snap is None or snap.kind in self._NAMED_SNAPS:
            return snap
        for fn in list(providers):
            try:
                got = fn(vp, snap, px_x, px_y)
            except Exception:  # noqa: BLE001 — a plugin never breaks input
                import logging
                logging.getLogger("ingetrazo.plugins").exception(
                    "extension snap provider failed")
                continue
            if got is not None:
                return got
        return snap

    # ---- Encouraged points --------------------------------------------------
    def _dwell_on(self, point: Optional[QVector3D]) -> None:
        """The cursor is over ``point`` (or nothing): (re)start the pause
        that turns it into an encouraged point."""
        if point is None:
            self._dwell_point = None
            self._dwell_timer.stop()
            return
        if (self._dwell_point is not None
                and (self._dwell_point - point).length() < 1e-6):
            return                                  # still resting on it
        self._dwell_point = QVector3D(point)
        self._dwell_timer.start()

    def _encourage_dwelt(self) -> None:
        if self._dwell_point is not None:
            self.encourage_point(self._dwell_point)

    def encourage_point(self, point: QVector3D) -> None:
        """Make ``point`` the newest encouraged point (two are kept, the
        older one drops), and the 'from point' reference."""
        pt = QVector3D(point)
        self._encouraged = [p for p in self._encouraged if (p - pt).length() > 1e-6]
        self._encouraged.append(pt)
        del self._encouraged[:-2]
        self._acquired_point = pt
        self.viewport.update()

    def clear_references(self) -> None:
        """Drop cursor-acquired and encouraged model references."""
        self._dwell_timer.stop()
        self._dwell_point = None
        self._hover_edge = None
        self._hover_center = None
        self._center_ref = None
        self._acquired_edge = None
        self._acquired_face_normal = None
        self._acquired_point = None
        self._encouraged = []
        self.last_snap = None

    def reset(self) -> None:
        """Forget every inference state tied to the current document."""
        self.clear_references()
        self.axis_lock = None
        self.reference_edge = None
        self.reference_mode = None
        self._shift_lock = None
