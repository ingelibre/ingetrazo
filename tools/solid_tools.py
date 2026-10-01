# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid Tools: Outer Shell, Union, Subtract, Trim, Intersect,
Split (the operations live in :mod:`core.solids`).

Two ways in:

* **Pre-selection** — select the solids, then pick the tool: Outer Shell,
  Union and Intersect run at once on every solid selected; Split on two.
  Subtract and Trim need to know which solid cuts, and a selection has no
  order, so they fall to the clicks.
* **Clicks** — pick the tool, click solid 1, then solid 2. For Subtract and
  Trim the FIRST one is the cutter. Union and Outer Shell keep going:
  every further click adds another solid to the result.

The pointer says what a click would do: a red circle-and-slash over
anything that is not a solid, a «1» or «2» over a solid.
"""
from __future__ import annotations

from core import solids
from core.i18n import tr
from tools.base import Tool, ToolContext

#: How the user is told why an operation did not run.
_ERRORS = {
    "not a solid": "That is not a solid — a group or component closed all "
                   "round, with nothing nested inside",
    "no overlap": "The two solids do not overlap",
    "empty": "The operation leaves nothing",
    "not manifold": "That solid has a flaw the operation cannot read",
    "two solids": "Pick two solids",
}


class SolidTool(Tool):
    """One Solid Tool; subclasses set ``op``, ``name`` and ``icon``."""

    op = solids.UNION
    uses_snap = False
    #: Union and Outer Shell accept more solids after the first result.
    _CHAINS = (solids.UNION, solids.OUTER_SHELL)

    def __init__(self) -> None:
        self.first = None
        self._badge = "no"
        self._cache: dict = {}
        self._cache_version = None

    # ---- Phase ---------------------------------------------------------------
    @property
    def dragging(self) -> bool:
        """Mid-operation once the first solid is picked: the status bar
        shows the second step and Esc drops the pick (``start_point`` is
        read as a 3-D point elsewhere, so it is not borrowed here)."""
        return self.first is not None

    # ---- Lifecycle ------------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self.first = None
        self._badge = "no"
        scene = viewport.scene
        from core.group import Group
        picked = [g for g in scene.groups if g in scene.selection
                  and isinstance(g, Group)]            # document order
        solid = [g for g in picked if self._is_solid(scene, g)]
        runs_on_selection = (
            (self.op in (solids.UNION, solids.OUTER_SHELL, solids.INTERSECT)
             and len(solid) >= 2)
            or (self.op == solids.SPLIT and len(solid) == 2))
        if runs_on_selection and len(solid) == len(picked):
            if self._execute(viewport, solid):
                win = viewport.window() if hasattr(viewport, "window") else None
                back = getattr(win, "_activate_tool", None)
                if callable(back):
                    back("select")
                return
        if picked and self.op in (solids.SUBTRACT, solids.TRIM):
            viewport.flash_status(tr(
                "Click the solid that cuts, then the one it cuts"), 4000)
        scene.selection.clear()
        scene.bump_view()

    def on_deactivate(self, viewport) -> None:
        self.first = None

    def on_cancel(self, viewport) -> None:
        self.first = None
        viewport.scene.selection.clear()
        viewport.scene.bump_view()
        viewport.update()

    # ---- Input ----------------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        g = vp.pick_group(ctx.screen.x(), ctx.screen.y())
        if g is not None and g is not self.first and self._is_solid(vp.scene, g):
            badge = "1" if self.first is None else "2"
        else:
            badge = "no"
        if badge != self._badge:
            self._badge = badge
            apply = getattr(vp, "_apply_tool_cursor", None)
            if apply is not None:
                apply()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        g = vp.pick_group(ctx.screen.x(), ctx.screen.y())
        if g is None or g is self.first:
            return
        if not self._is_solid(vp.scene, g):
            vp.flash_status(tr(_ERRORS["not a solid"]), 4000)
            return
        if self.first is None:
            self.first = g
            vp.scene.selection = {g}
            vp.scene.version += 1
            vp.update()
            return
        made = self._execute(vp, [self.first, g])
        if made and self.op in self._CHAINS:
            self.first = made[0]           # keep adding solids to it
        else:
            self.first = None
            if not made:
                vp.scene.selection.clear()
                vp.scene.version += 1
        self._badge = "no"
        vp.update()

    # ---- Pointer ----------------------------------------------------------------
    @property
    def qt_cursor(self):
        from views.icons import solid_cursor
        return solid_cursor(self._badge)

    # ---- Internals --------------------------------------------------------------
    def _is_solid(self, scene, group) -> bool:
        """Cached per scene version: the check walks the whole mesh and the
        hover asks on every move."""
        if self._cache_version != scene.version:
            self._cache = {}
            self._cache_version = scene.version
        key = id(group)
        if key not in self._cache:
            self._cache[key] = solids.is_solid(group)
        return self._cache[key]

    def _execute(self, viewport, groups) -> list:
        cmd = solids.SolidOperationCommand(self.op, groups)
        try:
            cmd.prepare()
        except solids.SolidError as err:
            viewport.flash_status(tr(_ERRORS.get(str(err), str(err))), 5000)
            return []
        viewport.history.execute(cmd)
        viewport.update()
        return list(cmd.created or [])


class OuterShellTool(SolidTool):
    name = "Outer Shell"
    description = (
        "Merge the selected solids into one, keeping only their outer "
        "skin.")
    op = solids.OUTER_SHELL


class UnionTool(SolidTool):
    name = "Union"
    description = "Join solids into a single solid."
    op = solids.UNION


class SubtractTool(SolidTool):
    name = "Subtract"
    description = (
        "Cut the first solid clicked out of the second, and remove "
        "the first.")
    op = solids.SUBTRACT


class TrimTool(SolidTool):
    name = "Trim"
    description = (
        "Cut the first solid clicked out of the second, and keep the "
        "first.")
    op = solids.TRIM


class IntersectTool(SolidTool):
    name = "Intersect"
    description = "Keep only the part where the solids overlap."
    op = solids.INTERSECT


class SplitTool(SolidTool):
    name = "Split"
    description = (
        "Split two overlapping solids into their separate parts and "
        "their common part.")
    op = solids.SPLIT


#: Tool key → class, in the classic order (toolbar and menu).
SOLID_TOOLS = (
    ("outer_shell", OuterShellTool), ("solid_union", UnionTool),
    ("solid_subtract", SubtractTool), ("solid_trim", TrimTool),
    ("solid_intersect", IntersectTool), ("solid_split", SplitTool),
)
