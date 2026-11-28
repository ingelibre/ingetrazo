# SPDX-License-Identifier: GPL-3.0-or-later
"""Transient animation followed by one ordinary, undoable tree swap."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from .actions import ActionError, prepare
from .apply import redraw_group
from .document import SwapGroupCommand, _run
from core.history import group_owner_list, _dirty_group_chunks


class Interaction:
    def __init__(self, viewport, root, clicked):
        self.viewport = viewport
        self.scene = viewport.scene
        self.root = root
        self.plan = prepare(root, clicked, self.scene)
        self.owner = group_owner_list(self.scene, root)
        if self.owner is None:
            raise ActionError("The component is no longer in the document")
        self.final, ev = redraw_group(root, scene=self.scene, edits=self.plan.edits())
        if ev.errors:
            raise ActionError(str(ev.errors[0][3]))
        self.current = root
        self.version_before = self.scene.version
        self.running = False
        self.timer = QTimer(viewport if hasattr(viewport, 'thread') else None)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    def _swap(self, into):
        index = next((i for i, g in enumerate(self.owner) if g is self.current), None)
        if index is None:
            raise ActionError("The animated component was removed")
        out = self.current
        into.context = getattr(out, 'context', None)
        self.owner[index] = into
        if out in self.scene.selection:
            self.scene.selection.discard(out)
            self.scene.selection.add(into)
        self.current = into
        self.scene.version += 1
        _dirty_group_chunks(self.scene)
        self.viewport.update()

    def start(self):
        settle(self.scene)
        self.running = True
        self.scene._finish_dynamic_preview = self.finish
        if not self.plan.duration:
            self.finish()
            return
        self.started = time.monotonic()
        self.timer.start()

    def tick(self, elapsed=None):
        if not self.running:
            return
        elapsed = time.monotonic() - self.started if elapsed is None else elapsed
        if elapsed >= self.plan.duration:
            self.finish()
            return
        try:
            frame, ev = redraw_group(self.root, scene=self.scene,
                                     edits=self.plan.edits(elapsed))
            if ev.errors:
                raise ActionError(str(ev.errors[0][3]))
            self._swap(frame)
        except Exception as exc:
            self.cancel()
            from core.i18n import tr
            self.viewport.flash_status(tr("Component action failed: {error}", error=str(exc)), 6000)

    def _stop(self):
        self.timer.stop()
        self.timer.deleteLater()
        self.running = False
        if getattr(self.scene, '_finish_dynamic_preview', None) == self.finish:
            del self.scene._finish_dynamic_preview
        if self.current is not self.root:
            self._swap(self.root)
        # The frames are a preview, not edits. Cancel leaves the document's
        # dirty state as it was; finish commits one new version below.
        self.scene.version = self.version_before

    def finish(self):
        if not self.running:
            return
        self._stop()
        command = SwapGroupCommand(self.root, lambda _scene: self.final)
        _run(self.viewport, command)
        self.current = self.final

    def cancel(self):
        if self.running:
            self._stop()
            self.viewport.notify_scene_changed()


def settle(scene):
    """Finish a visual preview before a command, undo, redo or save reads it."""
    callback = getattr(scene, '_finish_dynamic_preview', None)
    if callback is not None:
        callback()
