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
from tools.base import Tool, ToolContext, retype_open


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
    axis_source = True
    axis_source_empty_only = True

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
        #: The segment just drawn, for the hot retype (#414): a length
        #: typed while the cursor still sits on its end redraws it.
        self._last: dict | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._last = None

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self._last = None
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        clicked = ctx.world
        self._last = None            # a click ends the retype window
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
        faces_before = len(ctx.viewport.scene.faces)
        last = self._retype_state(self.start_point, clicked)
        ctx.viewport.history.execute(cmd)
        ended = (ctx.snap is not None and ctx.snap.kind == "close"
                 or len(ctx.viewport.scene.faces) > faces_before)
        self._arm_retype(ctx.viewport, last, cmd, ended)
        if ended:
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
        self._last = None
        viewport.update()

    def on_undo(self, viewport) -> bool:
        """Ctrl+Z in the middle of a chain (@pacaeiro, #175: «the last
        picked point is not freed»). The segment just drawn is undone and
        the chain steps back to its previous vertex, so the rubber band
        leaves from where the line now really ends. With only the first
        point placed there is nothing of this chain to undo: the point is
        let go. Idle, the ordinary undo runs."""
        self._last = None            # the segment it would retype is gone
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

        Right after a segment is drawn — while the cursor still sits on its
        end, or once the line has closed — the value redraws THAT segment
        from the same start instead: the hot retype of #414. Move the
        cursor away and the value is the next segment again.
        """
        if self._retype_ready(viewport):
            return self._retype(viewport, value)
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

        self._draw_segment(viewport, self.start_point, new_endpoint,
                           self._retype_state(self.start_point, new_endpoint))
        return True

    def _draw_segment(self, viewport, start: QVector3D, end: QVector3D,
                      last: dict, ended: bool = False) -> bool:
        """Commit the segment ``start``–``end`` and move the chain on: it
        ends when the segment makes a face (or ``ended`` says it already
        had), else it continues from ``end``. False if the history
        refused the segment."""
        faces_before = len(viewport.scene.faces)
        cmd = self._commit_edge(viewport, start, end)
        viewport.history.execute(cmd)
        if not retype_open(viewport, cmd):
            return False
        ended = ended or len(viewport.scene.faces) > faces_before
        self._arm_retype(viewport, last, cmd, ended)
        if ended:
            self._reset()
        else:
            self.chain_vertices.append(end)
            self.start_point = end
            self.hover_point = end
        viewport.update()
        return True

    # ---- Hot retype (#414) ----------------------------------------------
    def _retype_state(self, start: QVector3D, end: QVector3D) -> dict:
        """What a retype of the segment about to be drawn needs: where it
        starts, which way it runs and the chain as it was before it."""
        return {"start": QVector3D(start), "end": QVector3D(end),
                "chain": list(self.chain_vertices),
                "first": self.chain_first_point,
                "work_plane": self.work_plane}

    def _arm_retype(self, viewport, last: dict, cmd, ended: bool) -> None:
        last["cmd"] = cmd
        last["ended"] = ended
        self._last = last if retype_open(viewport, cmd) else None

    def _retype_ready(self, viewport) -> bool:
        """Whether a typed value retypes the segment just drawn: it is
        still the last thing done, and — if the chain goes on — the cursor
        has not left its end (once it has, the rubber band shows the next
        segment, and that is what the number is for)."""
        last = self._last
        if last is None:
            return False
        if not retype_open(viewport, last["cmd"]):
            self._last = None
            return False
        if last["ended"]:
            return self.start_point is None
        end = last["end"]
        return (self.start_point is not None
                and (self.start_point - end).length() < 1e-9
                and (self.hover_point is None
                     or (self.hover_point - end).length() < 1e-9))

    def _retype(self, viewport, value) -> bool:
        """Undo the segment just drawn and draw it again from the same
        start: a length along the same direction (negative, the other
        way), or a ``dx;dy;dz`` delta. One undo step however many times."""
        last = self._last
        start = last["start"]
        if isinstance(value, tuple):
            if len(value) != 3:
                return False
            dx, dy, dz = value
            end = QVector3D(start.x() + dx, start.y() + dy, start.z() + dz)
        else:
            delta = last["end"] - start
            if abs(value) < 1e-9 or delta.length() < 1e-9:
                return False
            end = start + delta.normalized() * value
        if (end - start).length() < 1e-9:
            return False
        viewport.history.undo()
        self.start_point = start
        self.chain_vertices = list(last["chain"])
        self.chain_first_point = last["first"]
        self.work_plane = last["work_plane"]
        if not self._draw_segment(viewport, start, end,
                                  dict(last, end=QVector3D(end)),
                                  ended=last["ended"]):
            # Refused: the segment already drawn comes back instead of
            # vanishing with the undo above, and the window stays open.
            viewport.history.redo()
            if last["ended"]:
                self._reset()
            else:
                self.chain_vertices.append(last["end"])
                self.start_point = last["end"]
                self.hover_point = last["end"]
            self._last = last
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

    # A segment that makes a face — closing a loop, or cutting an existing
    # face in two — finishes the chain: the next click starts a new line
    # instead of leaving from the end of the one that just did its job (#496).

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.chain_vertices = []
        self.work_plane = None
