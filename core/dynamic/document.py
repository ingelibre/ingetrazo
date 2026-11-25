# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A redraw in the document: the new tree swapped in as ONE undo step.

:func:`.apply.redraw_group` builds a new tree for a component; here it
takes the old one's place — in ``scene.groups`` or in the ``children`` of
the container that holds it, at any depth — and keeps the selection on it.
Undo puts the old tree back whole. The history's own follow-ups run after
it as after any command: an opening the component cut is closed and cut
again at its new size (core/openings.py).
"""
from __future__ import annotations

from core.history import Command, group_owner_list

from . import KEY
from . import apply as _apply
from .messages import Msg


class DynamicError(Exception):
    """A redraw that could not happen; ``msg`` says why (translatable)."""

    def __init__(self, msg: Msg) -> None:
        super().__init__(str(msg))
        self.msg = msg


def is_dynamic(group) -> bool:
    """Whether ``group`` is a dynamic component (carries attributes)."""
    return group is not None and _apply.is_dynamic_root(group)


def context_members(scene) -> list:
    """The containers the user can pick where they are working: the
    top-level ones, or the parts of the open group."""
    ctx = getattr(scene, "edit_group", None)
    if ctx is None:
        return list(getattr(scene, "groups", None) or [])
    return list(getattr(ctx, "children", None) or [])


def selected_one(scene, dynamic_only: bool = True):
    """The ONE container selected in the current context (a dynamic one
    when ``dynamic_only``), else None."""
    sel = getattr(scene, "selection", ()) or ()
    if not sel:
        return None
    members = {id(m) for m in context_members(scene)}
    found = None
    for e in sel:
        g = getattr(e, "owner", None) or e
        if id(g) not in members:
            continue
        if dynamic_only and not is_dynamic(g):
            continue
        if found is not None and found is not g:
            return None
        found = g
    return found


class SwapGroupCommand(Command):
    """Put ``make_new(scene)`` where ``old`` is, keeping its place in its
    list and in the selection; undo puts ``old`` back. The new tree is
    built on the first ``do`` and reused on redo."""

    def __init__(self, old, make_new) -> None:
        self.old = old
        self._make_new = make_new
        self.new = None
        self.owner = None

    def _swap(self, scene, out, into) -> None:
        i = next(k for k, g in enumerate(self.owner) if g is out)
        self.owner[i] = into
        # Inside an open group its parts carry the edit context.
        into.context = getattr(out, "context", None)
        if out in scene.selection:
            scene.selection.discard(out)
            scene.selection.add(into)
        scene.version += 1
        from core.history import _dirty_group_chunks
        _dirty_group_chunks(scene)

    def do(self, scene) -> None:
        if self.new is None:
            owner = group_owner_list(scene, self.old)
            if owner is None:
                raise DynamicError(Msg("The component is not in the document any more"))
            self.owner = owner
            self.new = self._make_new(scene)
        self._swap(scene, self.old, self.new)

    def undo(self, scene) -> None:
        self._swap(scene, self.new, self.old)


def redraw_in_document(viewport, group, options: dict | None = None,
                       edits: dict | None = None):
    """Redraw ``group`` with ``options`` ({attribute: value}, stored units)
    and authoring ``edits`` as ONE undo step. Returns (the new group, the
    formulas that could not be evaluated: [(part, attr, formula, why)])."""
    problems: list = []

    def make_new(scene):
        new, ev = _apply.redraw_group(group, options, scene, edits)
        problems[:] = list(ev.errors)
        return new

    cmd = SwapGroupCommand(group, make_new)
    _run(viewport, cmd)
    return cmd.new, problems


def make_dynamic_in_document(viewport, group, name: str | None = None,
                             units: str = "CENTIMETERS"):
    """Make ``group`` a dynamic component (its axes to its lower corner, its
    first attributes), as ONE undo step. Returns the new group."""
    if is_dynamic(group):
        return group
    cmd = SwapGroupCommand(group, lambda scene: _apply.make_dynamic_tree(
        group, name, units))
    _run(viewport, cmd)
    return cmd.new


def _run(viewport, cmd) -> None:
    history = viewport.history
    ok = history.execute(cmd)
    if not ok or cmd.new is None or not any(g is cmd.new for g in (cmd.owner or ())):
        why = getattr(history, "last_error", None) or getattr(
            history, "last_rejected", None)
        raise DynamicError(Msg("The component could not be redrawn: {error}",
                               error=str(why or "?")))
    notify = getattr(viewport, "notify_scene_changed", None)
    if callable(notify):
        notify()
    viewport.update()


__all__ = ["KEY", "DynamicError", "SwapGroupCommand", "context_members",
           "is_dynamic", "make_dynamic_in_document", "redraw_in_document",
           "selected_one"]
