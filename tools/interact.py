# SPDX-License-Identifier: GPL-3.0-or-later
"""Pick a dynamic part and run its closest ancestor's OnClick action."""
from PySide6.QtCore import Qt

from core.i18n import tr
from core.dynamic.apply import _merged
from core.dynamic.actions import ActionError
from core.dynamic.document import context_members
from core.dynamic.interaction import Interaction
from tools.base import Tool


def target_path(viewport, placement):
    # The viewport's nested placements are render proxies; recover the
    # actual object by its cache key, never by mesh identity (shared parts).
    wanted = next((key for key, proxy in
                   (getattr(viewport, '_placement_proxies', None) or {}).items()
                   if proxy is placement), id(placement))

    def walk(group, path):
        path = path + [group]
        if id(group) == wanted:
            return path
        for child in group.children:
            found = walk(child, path)
            if found:
                return found
        return None

    for root in context_members(viewport.scene):
        path = walk(root, [])
        if path and not any(getattr(g, 'locked', False) or getattr(g, 'hidden', False)
                            for g in path):
            actor = next((g for g in reversed(path) if _merged(g).get('onclick')), None)
            if actor is not None:
                return root, actor
    return None


class InteractTool(Tool):
    name = "Interact"
    description = "Click a dynamic component to run its action; Esc cancels the animation."
    uses_snap = False

    def __init__(self):
        self.interaction = None

    def on_activate(self, viewport):
        viewport.flash_status(tr("Click a dynamic component to interact"))

    def on_deactivate(self, viewport):
        if self.interaction:
            self.interaction.finish()
        viewport.unsetCursor()
        viewport.set_hover(None)

    def _pick(self, viewport, screen):
        face, placement = viewport.pick_face_placement(screen.x(), screen.y())
        return face, placement, target_path(viewport, placement) if placement else None

    def on_hover(self, ctx):
        face, placement, target = self._pick(ctx.viewport, ctx.screen)
        ctx.viewport.setCursor(Qt.PointingHandCursor if target else Qt.ArrowCursor)
        ctx.viewport.set_hover(face if target else None, placement if target else None)

    def on_click(self, ctx):
        if self.interaction:
            self.interaction.finish()
        face, placement, target = self._pick(ctx.viewport, ctx.screen)
        if target is None:
            ctx.viewport.flash_status(tr("This part has no click action"))
            return
        try:
            self.interaction = Interaction(ctx.viewport, *target)
            self.interaction.start()
        except (ActionError, ValueError) as exc:
            ctx.viewport.flash_status(tr("Component action failed: {error}", error=str(exc)), 6000)

    def on_cancel(self, viewport):
        if self.interaction:
            self.interaction.cancel()
        viewport.set_hover(None)
