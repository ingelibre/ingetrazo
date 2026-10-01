# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Eraser tool (E): erase by clicking or by dragging over geometry.

The classic behaviour: press marks the edge under the cursor, dragging keeps
marking everything the cursor sweeps over (shown highlighted red), and release
erases the whole stroke as ONE undo step. Erasing an edge takes its faces with
it (and rubbing out a divider between coplanar faces merges them back — the
EraseSelectionCommand semantics). A segment of a drawn curve (circle/arc)
erases its whole contour, curves being single entities. Guides, dimensions,
leader texts and georef paths are erased too (texts: @pacaeiro, issue #66).
Esc cancels the in-progress stroke.

Shift held at press starts a HIDE stroke instead (the classic Shift+eraser):
the swept edges are hidden, not erased — still one undo step. Only edges and
objects can hide, so a hide stroke ignores guides/dimensions/paths rather
than deleting what the gesture promised to keep.

A group or component under the cursor is erased WHOLE, as users expect
(@pacaeiro, issue #46: «ERASE tool cannot erase Groups nor Components,
only raw edges and faces»); its box marks the stroke, and Shift hides it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from core.dimension import Dimension
from core.group import Group
from core.guide import Guide
from core.history import (
    CompoundCommand,
    DeleteDimensionsCommand,
    DeleteGeoPathsCommand,
    DeleteGroupCommand,
    DeleteGuidesCommand,
    DeleteTextLabelsCommand,
    EraseSelectionCommand,
    HideCommand,
    HideEdgesCommand,
)
from core.mesh import Edge
from core.textlabel import TextLabel
from georef.geopath import GeoPath
from tools.base import Tool, ToolContext


class EraserTool(Tool):
    name = "Eraser"
    shortcut = "E"
    description = (
        "Click or drag over edges to erase them, together with the "
        "faces they bound.")
    uses_snap = False
    wireframe_color = (0.90, 0.20, 0.15, 1.0)   # stroke marks show red

    def __init__(self) -> None:
        self._stroke = False
        self._hide = False       # Shift at press: hide the stroke, don't erase
        self.marked: set = set()

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        """Press: start a stroke and mark whatever is under the cursor. The
        modifier latches here — a whole stroke is one gesture, erase or hide."""
        self._stroke = True
        self._hide = bool(ctx.modifiers & Qt.ShiftModifier)
        self._mark(ctx.viewport, ctx.screen.x(), ctx.screen.y())
        ctx.viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        if self._stroke:
            self._mark(viewport, ctx.screen.x(), ctx.screen.y())
        else:
            # Preview what a click would take (curve segments show as their
            # whole contour, like Select); a text's glyphs first, as the
            # click takes them first.
            pick_label = getattr(viewport, "pick_text_label", None)
            label = (pick_label(ctx.screen.x(), ctx.screen.y(),
                                rect_only=True)
                     if pick_label is not None else None)
            viewport.set_hover(label if label is not None else
                               viewport.pick_edge(ctx.screen.x(),
                                                  ctx.screen.y()))
        viewport.update()

    def on_release(self, viewport) -> None:
        """Release: erase everything the stroke marked, as one undo step."""
        if not self._stroke:
            return
        marked, self.marked = self.marked, set()
        self._stroke = False
        if not marked:
            viewport.update()
            return
        edges = [m for m in marked if isinstance(m, Edge)]
        groups = [m for m in marked if isinstance(m, Group)]
        if self._hide:
            edges = [e for e in edges if not getattr(e, "hidden", False)]
            groups = [g for g in groups if not getattr(g, "hidden", False)]
            cmds = []
            if edges:
                cmds.append(HideEdgesCommand(edges, hidden=True))
            if groups:
                cmds.append(HideCommand(groups, hidden=True))
            if cmds:
                viewport.history.execute(
                    cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
            viewport.update()
            return
        guides = [m for m in marked if isinstance(m, Guide)]
        dims = [m for m in marked if isinstance(m, Dimension)]
        paths = [m for m in marked if isinstance(m, GeoPath)]
        labels = [m for m in marked if isinstance(m, TextLabel)]
        cmds = []
        if edges:
            cmds.append(EraseSelectionCommand(edges, []))
        cmds.extend(DeleteGroupCommand(g) for g in groups)
        if guides:
            cmds.append(DeleteGuidesCommand(guides))
        if dims:
            cmds.append(DeleteDimensionsCommand(dims))
        if paths:
            cmds.append(DeleteGeoPathsCommand(paths))
        if labels:
            cmds.append(DeleteTextLabelsCommand(labels))
        if cmds:
            viewport.history.execute(
                cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
        viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        """The marked stroke, drawn in the tool's red wireframe colour."""
        segs = []
        for m in self.marked:
            if isinstance(m, Edge):
                segs.append((m.a, m.b))
            elif isinstance(m, Group):
                segs.extend(self._group_box_segments(m))
            elif isinstance(m, Guide):
                segs.append(m.segment())
            elif isinstance(m, Dimension):
                segs.append(m.line_points())
            elif isinstance(m, GeoPath):
                segs.extend(m.segments())
            elif isinstance(m, TextLabel):
                segs.append((m.anchor, m.position()))
        return segs

    # ---- Internals ----------------------------------------------------------
    def _group_box_segments(self, group) -> list:
        """The twelve edges of the group's oriented box — its stroke mark,
        the same box Select draws around it."""
        vp = getattr(self, "_viewport", None)
        obb = getattr(vp, "_group_obb", None)
        if obb is None:
            return []
        from core.group import oriented_box_corners
        try:
            c = oriented_box_corners(*obb(group))
        except Exception:  # noqa: BLE001 — a box that cannot be built
            return []
        if len(c) != 8:
            return []
        pairs = ((0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6),
                 (6, 4), (0, 4), (1, 5), (2, 6), (3, 7))
        return [(c[i], c[j]) for i, j in pairs]

    def _mark(self, viewport, sx: float, sy: float) -> None:
        self._viewport = viewport
        pick_label = getattr(viewport, "pick_text_label", None)
        if pick_label is not None and not self._hide:
            # The text block overdraws all geometry, so the glyphs outrank
            # every 3D pick — the same order as Select.
            label = pick_label(sx, sy, rect_only=True)
            if label is not None:
                self.marked.add(label)
                return
        edge = viewport.pick_edge(sx, sy)
        if edge is not None:
            # A curve is one entity: marking a segment marks its contour.
            for e in viewport.scene.mesh.curve_edges(edge):
                self.marked.add(e)
            return
        # A group or component is one entity too: the eraser takes it whole
        # (issue #46). From inside a group, its own content is the loose
        # part and pick_group answers None, so nothing changes there.
        pick_group = getattr(viewport, "pick_group", None)
        group = pick_group(sx, sy) if pick_group is not None else None
        if group is not None:
            self.marked.add(group)
            return
        if self._hide:
            return          # only edges and objects can hide
        guide = viewport.pick_guide(sx, sy)
        if guide is not None:
            self.marked.add(guide)
            return
        dim = viewport.pick_dimension(sx, sy)
        if dim is not None:
            self.marked.add(dim)
            return
        # The label's thin leader keeps the normal, post-edge priority.
        label = pick_label(sx, sy) if pick_label is not None else None
        if label is not None:
            self.marked.add(label)
            return
        path = viewport.pick_geopath(sx, sy)
        if path is not None:
            self.marked.add(path)

    def _reset(self) -> None:
        self._stroke = False
        self._hide = False
        self.marked = set()
        self._viewport = None
