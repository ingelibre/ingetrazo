"""Select tool: pick edges and faces and delete them.

Behavior:
- Left click on / near an edge: select that edge. Click on a face interior
  (when no edge is closer): select the face. Edges win ties because they sit
  on top of faces, matching SketchUp.
- Shift-click adds to the current selection; plain click replaces it.
- Left click on empty space: clear the selection.
- Hover highlights whatever the click would pick, so the user sees the target
  before committing.
- Delete / Backspace: remove the selected edges and faces from the scene.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from core.geometry import Edge, Face
from core.history import (
    CompoundCommand,
    DeleteEdgesCommand,
    DeleteFaceCommand,
)
from tools.base import Tool, ToolContext


class SelectTool(Tool):
    name = "Select"
    shortcut = "S"

    def on_activate(self, viewport) -> None:
        pass

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)

    def _pick(self, viewport, screen_x: float, screen_y: float):
        """Edge under the cursor (screen-space priority), else the front face."""
        edge = viewport.pick_edge(screen_x, screen_y)
        if edge is not None:
            return edge
        return viewport.pick_face(screen_x, screen_y)

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        additive = bool(ctx.modifiers & Qt.ShiftModifier)
        if entity is None:
            if not additive:
                viewport.scene.clear_selection()
        else:
            viewport.scene.select([entity], additive=additive)
        viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        viewport.set_hover(self._pick(viewport, ctx.screen.x(), ctx.screen.y()))

    def on_key(self, viewport, key: int, modifiers: Qt.KeyboardModifiers) -> bool:
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            selection = viewport.scene.selection
            if selection:
                edges = [e for e in selection if isinstance(e, Edge)]
                faces = [f for f in selection if isinstance(f, Face)]
                commands = []
                if edges:
                    commands.append(DeleteEdgesCommand(edges))
                commands.extend(DeleteFaceCommand(f) for f in faces)
                if commands:
                    cmd = commands[0] if len(commands) == 1 else CompoundCommand(commands)
                    viewport.history.execute(cmd)
                    viewport.update()
            return True
        return False
