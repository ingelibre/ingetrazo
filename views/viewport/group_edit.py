# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Group-edit context: entering and leaving a group and how the rest of the model draws."""
from __future__ import annotations

from core.i18n import tr
from views.viewport._support import EDIT_REST_MODES


class GroupEditMixin:
    """Group-edit context: entering and leaving a group and how the rest of the model draws."""

    # ---- Group-edit context (Groups v2) --------------------------------------
    def begin_group_edit(self, group) -> None:
        """Enter a group for editing (double-click-into-group). A
        component instance opens on a world copy of its definition; the
        session's commands are remembered so leaving can fold them into ONE
        undoable share-back.

        A locked group (the Browser's padlock), or one inside a locked
        group, does not open — whichever road asks: a double-click, the
        right-click's Edit Group or a part clicked in the Parts tab."""
        from core.outliner import locked_on_path
        if locked_on_path(self.scene.groups, group):
            self.flash_status(tr("Unlock it first"), 3000)
            return
        parent = self.scene.edit_group
        in_definition = (parent is not None
                         and group in (getattr(parent, "children", None) or ())
                         and bool(getattr(parent, "component", True)))
        if (getattr(group, "xform", None) is not None
                and not getattr(group, "component", True)
                and not getattr(group, "children", None)
                and not in_definition
                and self._mesh_shared_elsewhere(group)):
            # A copied GROUP shares its geometry with the other copies only
            # until it is edited: opening it makes it its own, one undo
            # step, instead of editing every copy like a component
            # (issue #90 — the classic behaviour of groups).
            from core.history import MakeUniqueCommand
            self.history.execute(MakeUniqueCommand(group))
        was_instance = (getattr(group, "xform", None) is not None
                        and not getattr(group, "children", None))
        self.scene.begin_group_edit(group)
        self._edit_undo_mark = len(self.history.undo_stack)
        self._hover_entity = None
        self._edges_version = -1     # the rest may fade out or leave the VBOs
        share = getattr(self.scene, "_edit_share", None)
        if was_instance and share is not None:
            copies = sum(1 for g in self.scene.groups if g.mesh is share[1]) + 1
            self.flash_status(tr(
                "Editing component '{name}' — the change reaches its {n} "
                "copies when you leave (Esc); Make Unique first to edit "
                "one copy only", name=group.name, n=copies), 6000)
        else:
            self.flash_status(tr(
                "Editing {path} — Esc or click outside goes up one level",
                path=self.edit_path_text()), 5000)
        self.update()

    def _mesh_shared_elsewhere(self, group) -> bool:
        """Whether another placement — top level or nested at any depth —
        draws ``group``'s mesh. A group exploded out of a component copy
        shares its mesh with the group still inside the other copies
        (issue #97), and the top-level scan alone did not see it."""
        from core.group import iter_placements
        mesh = group.mesh
        for top in self.scene.groups:
            for g, _m in iter_placements(top):
                if g is not group and g.mesh is mesh:
                    return True
        return False

    def edit_path_text(self) -> str:
        """Where you are, as a path: ``Plaza ▸ Jardinera ▸ Banca``.

        Nesting without this reads as a broken program: you click outside,
        the program correctly steps up ONE level into a parent that is also
        a container, everything is still faded, and nothing seems to have
        happened («hago clic en ese grupo que me sale atenuado y sigue así»,
        Marco, 2026-09-11 — he was two levels deep and had no way to know).
        """
        pila = getattr(self.scene, "_edit_stack", None) or ()
        nombres = [n["group"].name for n in pila]
        return " ▸ ".join(nombres) if nombres else ""

    def end_one_group_edit(self) -> None:
        """Step out ONE level — Esc, which leaves you inside the
        parent when the group you were editing lived in another group."""
        self._leave_group_edit(todos=False)

    def end_group_edit(self) -> None:
        """Leave every open group, back to the model. What the menus and the
        save/export paths call."""
        self._leave_group_edit(todos=True)

    def _leave_group_edit(self, todos: bool) -> None:
        if self.scene.edit_group is None:
            return
        share = self.scene.take_edit_share()
        if todos:
            self.scene.end_group_edit()
        else:
            self.scene.end_one_group_edit()
        self._hover_entity = None
        self._edges_version = -1     # the rest comes back
        if share is not None:
            group, proto, xform, state0 = share
            edited = group.mesh
            if edited.capture_state() == state0:
                self.scene.restore_sharing(group, proto, xform)
                self.flash_status(tr("Left the group"), 2000)
            else:
                from core.history import ReshareInstanceCommand
                mark = getattr(self, "_edit_undo_mark",
                               len(self.history.undo_stack))
                inner = self.history.undo_stack[mark:]
                del self.history.undo_stack[mark:]
                self.history.execute(ReshareInstanceCommand(
                    group, proto, xform, edited, inner))
                copies = sum(1 for g in self.scene.groups if g.mesh is proto)
                self.flash_status(tr(
                    "Component '{name}' updated on its {n} copies",
                    name=group.name, n=copies), 4000)
        elif self.scene.edit_group is not None:
            # Stepping up into another container: say so, or it reads as a
            # click that did nothing (everything around is still faded).
            self.flash_status(tr(
                "Up one level — now in {path}",
                path=self.edit_path_text()), 4000)
        else:
            self.flash_status(tr("Left the group"), 2000)
        # Leaving re-shares a component: the trays (Components' «In the
        # model» list, Entity Info) must hear it now, not at the next edit —
        # the list read «no components yet» with the house on screen
        # (Rafael, revision 4, 06:18).
        self.notify_scene_changed()

    # ---- Rest-of-model context while editing a group -------------------------
    @property
    def edit_rest_mode(self) -> str:
        """``normal`` / ``fade`` / ``hide`` — how the model outside the group
        being edited reads. See :data:`EDIT_REST_MODES`."""
        return self._edit_rest_mode

    def set_edit_rest_mode(self, mode: str) -> None:
        if mode not in EDIT_REST_MODES or mode == self._edit_rest_mode:
            return
        self._edit_rest_mode = mode
        from PySide6.QtCore import QSettings
        QSettings().setValue("display/edit_rest_mode", mode)
        # "hide" keeps the rest out of the VBOs entirely, so switching to or
        # from it changes what is uploaded, not just how it is drawn.
        self._edges_version = -1
        self.update()

    def set_hide_similar_components(self, on: bool) -> None:
        """Hide Similar Components: the other instances of the
        component being edited leave the frame. Persisted like the rest
        mode; the version bump re-keys the pick index."""
        on = bool(on)
        from PySide6.QtCore import QSettings
        QSettings().setValue("display/hide_similar_components",
                             "1" if on else "0")
        if bool(getattr(self.scene, "hide_similar_components", False)) == on:
            return
        self.scene.hide_similar_components = on
        if on:
            for ent in list(self.scene.selection):
                if self.scene.similar_hidden(ent):
                    self.scene.selection.discard(ent)
        self.scene.version += 1
        self._edges_version = -1
        self.update()

    def _rest_is_hidden(self) -> bool:
        """Whether the model outside the edited group is out of this frame."""
        return (self.scene.edit_group is not None
                and self._edit_rest_mode == "hide")

    def _context_placements(self):
        """The placements the CURRENT context lets you touch.

        At the root that is the whole scene. Inside a group it is its
        children and their subtrees — never the model around it, which is
        exactly why you cannot grab the rest of the drawing while you are
        inside a group.
        """
        ctx = self.scene.edit_group
        todo = self._placements()
        if ctx is None:
            return todo
        return [g for g in todo
                if getattr(g, "context", None) is ctx
                and getattr(g, "owner", None) is not ctx]

    def _owner_of(self, group):
        """The object a click on ``group`` must select: a nested placement
        proxy stands for the top-level group that owns it."""
        return getattr(group, "owner", None) or group

    def _draws_in_edit_context(self, group) -> bool:
        """Whether ``group`` is part of the surroundings of the group being
        edited (so it fades or hides), rather than the subject itself."""
        ctx = self.scene.edit_group
        if ctx is None:
            return False
        if group is ctx or getattr(group, "context", None) is ctx:
            return False          # the container and what lives inside it
        return self._owner_of(group) is not ctx
