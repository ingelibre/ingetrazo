# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Line tool: click points to draw edges; auto-close polygons.

Behavior follows the classic convention:
- First click sets the start point of a fresh chain.
- Each next click finalises a segment and chains into the next one.
- Snapping to the chain's first point (snap kind ``"close"``) finishes the
  polygon and resets the chain.
- Esc cancels the chain without committing the pending segment.

The tool exposes ``start_point``, ``hover_point`` and ``chain_first_point``
so the viewport can:
  * draw the rubber-band preview during ``paintGL``,
  * feed those into the snap engine for close-polygon detection.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge
from core.history import Command
from tools.base import Tool, ToolContext


class LineTool(Tool):
    name = "Line"
    shortcut = "L"
    description = "Draw edges point by point; closing a loop makes a face."
    vcb_label = "Length"

    #: The axis inference MAGNETISES, it does not merely light up.
    #:
    #: @pacaeiro (issue #31): «The Soft inference of Axis shows the message
    #: "In Red Axis (hold Shift to lock)", but only when we hit Shift the
    #: Vector gets aligned with the X. It should magnetically align with
    #: the axis (like other snap point). That allows to write a distance
    #: and press Enter, finishing the line in the vector X.»
    #:
    #: He is right, and measured it is worse than "not aligned": the label
    #: was a promise the engine did not keep. Within the inference angle
    #: the point came back RAW — 2, 5, 8 cm off the axis at a 2 m reach —
    #: while the status bar said you were on it. Shift is for pinning a
    #: direction while you go hunting for a snap point elsewhere, not for
    #: the everyday case of drawing something straight.
    #:
    #: The value is the soft inference angle, not Move's generous 15°, so
    #: WHEN the cue appears is exactly as before and only WHAT it returns
    #: changes. Drawing deliberately off-axis by a couple of degrees stays
    #: possible; the toggle Alt still switches it off entirely.
    magnetic_axis_deg = 3.0

    #: …and the axes that the one above CANNOT reach, found in pixels.
    #:
    #: @pacaeiro (issue #31, second point): «in certain viewport positions,
    #: is impossible to get Inference of the 3 axis (X, Y, Z)». Measured
    #: over the whole camera grid, every camera reaches exactly TWO and
    #: never three — x/y from the top, x/z from the front, y/z from the
    #: side — because the cursor becomes a world point by landing on the
    #: work plane, and a plane holds at most two of the three axes. Drawing
    #: in plan, blue does not exist; from the front, green does not.
    #:
    #: The engine consults this only where the world detector found
    #: nothing, so the two axes that already worked keep coming from where
    #: they always did. The threshold is the one point snaps already use
    #: rather than a new constant of its own.
    screen_axis_px = 9.0

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self.chain_first_point: QVector3D | None = None
        # Ordered list of vertices in the current chain. Populated as the
        # user clicks; consumed to build a Face when the chain auto-closes.
        self.chain_vertices: list[QVector3D] = []
        # (point, normal) of the face the chain was started on, if any.
        # The viewport reads this to keep subsequent points coplanar.
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        clicked = ctx.world
        if self.start_point is None:
            self.start_point = clicked
            self.chain_first_point = clicked
            self.chain_vertices = [clicked]
            return

        if (clicked - self.start_point).length() < 1e-9:
            # The start itself: nothing to draw. Reachable on purpose since
            # issue #34 — under a lock, a reference level with the start
            # shows its guide and lands here — and it used to go to the
            # history as a degenerate edge and come back as a noisy
            # rollback.
            return
        cmd = self._commit_edge(ctx.viewport, self.start_point, clicked)
        ctx.viewport.history.execute(cmd)
        if ctx.snap.kind == "close":
            self._reset()
        else:
            self.chain_vertices.append(clicked)
            self.start_point = clicked
        ctx.viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def on_undo(self, viewport) -> bool:
        """Ctrl+Z in the middle of a chain (@pacaeiro, #175: «the last
        picked point is not freed»). The segment just drawn is undone and
        the chain steps back to its previous vertex, so the rubber band
        leaves from where the line now really ends. With only the first
        point placed there is nothing of this chain to undo: the point is
        let go. Idle, the ordinary undo runs."""
        if self.start_point is None:
            return False
        if len(self.chain_vertices) > 1:
            if not viewport.history.undo():
                self._reset()
                viewport.update()
                return True
            self.chain_vertices.pop()
            self.start_point = self.chain_vertices[-1]
            if len(self.chain_vertices) == 1:
                self.chain_first_point = self.start_point
        else:
            self._reset()
        viewport.update()
        return True

    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        return [(self.start_point, self.hover_point)]

    def on_value(self, viewport, value) -> bool:
        """Commit a segment from the VCB input.

        ``value`` is either:
        - ``float``  → length along the current rubber-band direction
                        (negative = the opposite way, the usual convention).
        - 3-tuple    → ``(dx, dy, dz)`` delta added to the start point,
                        which makes inclined / elevated lines trivial to
                        construct numerically (start, then type "3;4;5"
                        for a +3 X, +4 Y, +5 Z delta).
        """
        if self.start_point is None:
            return False

        if isinstance(value, tuple):
            if len(value) != 3:
                return False  # 2-tuple is a rectangle's W×H, not a line delta
            dx, dy, dz = value
            new_endpoint = QVector3D(
                self.start_point.x() + dx,
                self.start_point.y() + dy,
                self.start_point.z() + dz,
            )
        else:
            # A negative length runs AWAY from the cursor, as Move/Copy
            # already do (issue #58, @pacaeiro: «Command LINE do not accept
            # negative values»). Only zero has nowhere to go.
            if self.hover_point is None or abs(value) < 1e-9:
                return False
            delta = self.hover_point - self.start_point
            if delta.length() < 1e-9:
                return False
            direction = delta.normalized()
            new_endpoint = self.start_point + direction * value

        viewport.history.execute(self._commit_edge(viewport, self.start_point, new_endpoint))
        self.chain_vertices.append(new_endpoint)
        self.start_point = new_endpoint
        self.hover_point = new_endpoint
        viewport.update()
        return True

    # ---- Internals ----------------------------------------------------------
    def _commit_edge(self, viewport, start: QVector3D, end: QVector3D) -> Command:
        """Build the command for a new edge. ``build_add_edge`` welds
        coincident edges, splits any existing edge the new one crosses
        (introducing a shared vertex), and attaches a face when the new edge
        closes a planar cycle — the classic "any planar loop becomes a
        face" behaviour, now correct even when the loop relies on a crossing."""
        cam = getattr(viewport, "camera", None)
        eye = cam.eye() if cam is not None and hasattr(cam, "eye") else None
        return build_add_edge(viewport.scene, start, end, detect_faces=True,
                              eye=eye)

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.chain_vertices = []
        self.work_plane = None
