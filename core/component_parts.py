# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The parts of a component definition — the groups nested in it — while one
of its copies is open for editing.

A definition is shared by identity: every copy holds the same prototype
mesh, and the groups inside each copy hold the same meshes too (#97). What
each copy kept for itself was its LIST of parts and each part's matrix, so
moving, scaling or rotating a part, pasting one in or taking one out stayed
in the copy that was open (#1339, #894, #508).

Opening a copy now records its parts as they stand; the tools work on them
in world coordinates, as on any container. Leaving takes them back into the
definition's own frame and, when they changed, hands every other copy the
same parts: copies of these groups that share their meshes, as Copy makes
them. Nothing in the file format changes — the .igz already stores each
copy's parts; now they agree.
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4


class EditShare(tuple):
    """``(group, proto, xform, state0)`` — the pending share-back of an open
    instance, as it always was — with :attr:`parts`, the record of its parts
    at entry (:class:`PartsAtEntry`)."""

    parts = None
    images = None


def open_instance_images(share) -> None:
    """Put an instance's photos in world coordinates for its edit session.

    Keep the definition's image objects untouched: component copies share
    them, while only the open copy should use the temporary world placement.
    """
    group, _proto, xform, _state = share
    if not group.images:
        return
    originals = list(group.images)
    working = [image.transformed(xform) for image in originals]
    share.images = (originals, [image.to_dict() for image in working])
    group.images = working


def instance_images_changed(share) -> bool:
    if share.images is None:
        return False
    originals, before = share.images
    return (len(share[0].images) != len(originals)
            or [image.to_dict() for image in share[0].images] != before)


def settle_instance_images(share, *, changed: bool) -> None:
    """Return an edited copy's photos to the shared definition's frame."""
    if share.images is None:
        return
    group, _proto, xform, _state = share
    originals, _before = share.images
    if changed:
        inverse, ok = xform.inverted()
        if not ok:
            inverse = QMatrix4x4()
        for original, working in zip(originals, group.images):
            local = working.transformed(inverse)
            original.origin, original.u, original.v = (
                local.origin, local.u, local.v)
    group.images = originals


def _flags(g) -> tuple:
    mat = getattr(g, "material", None)
    return (g.name, g.layer, bool(g.hidden), bool(getattr(g, "locked", False)),
            tuple(sorted((k, repr(v)) for k, v in mat.items())) if mat else None,
            id(g.mesh), bool(getattr(g, "component", True)),
            tuple(id(c) for c in getattr(g, "children", None) or ()))


class PartsAtEntry:
    """A copy's parts when it was opened: which ones, each one's matrix in
    the definition's frame (``local``) and in the world (``world``, what the
    session started from), and the copy's own axes and session matrix."""

    __slots__ = ("group", "session_xform", "xform", "kids", "local", "world",
                 "flags", "axes", "session_axes", "component")

    def __init__(self, group, session_xform, xform, local, world,
                 axes) -> None:
        self.group = group
        self.session_xform = session_xform
        self.xform = QMatrix4x4(xform)
        self.kids = list(group.children or ())
        self.local = list(local)
        self.world = list(world)
        self.flags = [_flags(k) for k in self.kids]
        self.axes = axes
        self.session_axes = axes
        self.component = getattr(group, "component", True)

    # ---- reading -------------------------------------------------------------
    def changed(self) -> bool:
        """Whether the parts are no longer the ones the copy was opened with:
        one added, removed or reordered, moved, renamed, hidden, painted…"""
        kids = list(self.group.children or ())
        if [id(k) for k in kids] != [id(k) for k in self.kids]:
            return True
        for k, world, flags in zip(kids, self.world, self.flags):
            if k.xform != world or _flags(k) != flags:
                return True
        return False

    # ---- the definition's frame ↔ the world -----------------------------------
    def settle(self) -> None:
        """Put the parts back into the definition's frame (the copy has its
        matrix again). A part the session did not move takes its matrix
        exactly as it was — no float drift for opening and leaving."""
        from core.explode import rotate_offsets
        inv, ok = self.xform.inverted()
        if not ok:
            inv = QMatrix4x4()
        at = {id(k): i for i, k in enumerate(self.kids)}
        for k in self.group.children or ():
            i = at.get(id(k))
            if i is not None and k.xform == self.world[i]:
                k.xform = (QMatrix4x4(self.local[i])
                           if self.local[i] is not None else None)
            elif k.xform is not None:
                k.xform = inv * k.xform
            else:
                # A classic group brought in (a paste): its mesh is in world
                # coordinates; it stays a group, placed by the inverse.
                k.xform = QMatrix4x4(inv)
                k.component = False
        rotate_offsets(self.group, inv)
        self.group.axes = self.axes
        # A component stays one, whatever Make Group did to its flag inside.
        self.group.component = self.component

    def to_world(self, kids, world) -> None:
        """The session's frame again, with ``kids`` at ``world``: what undo and
        redo replay the session's own commands against."""
        from core.explode import rotate_offsets
        g = self.group
        g.children = list(kids)
        for k, m in zip(kids, world):
            k.xform = QMatrix4x4(m) if m is not None else None
        rotate_offsets(g, self.xform)
        g.xform = (QMatrix4x4(self.session_xform)
                   if self.session_xform is not None else None)
        g.axes = self.session_axes


def open_definition(group, frame) -> EditShare:
    """Open a component copy that holds groups: its matrix goes down into its
    parts and its own mesh becomes a world copy, for the session only."""
    from core.explode import rotate_offsets
    from core.group import transformed_mesh
    proto, xform = group.mesh, QMatrix4x4(group.xform)
    local = [QMatrix4x4(k.xform) if k.xform is not None else None
             for k in group.children]
    axes = group.axes
    for k in group.children:
        k.xform = xform * (k.xform if k.xform is not None else QMatrix4x4())
    rotate_offsets(group, xform)
    group.mesh = transformed_mesh(proto, xform)
    group.xform = QMatrix4x4()           # a container is always an instance
    if frame is not None:
        group.axes = frame
    share = EditShare((group, proto, xform, group.mesh.capture_state()))
    parts = PartsAtEntry(group, QMatrix4x4(), xform, local,
                         [QMatrix4x4(k.xform) for k in group.children], axes)
    parts.session_axes = group.axes
    share.parts = parts
    return share


def definition_copies(groups, proto, group):
    """The other copies of the definition ``proto`` anywhere in the tree:
    component instances on it, and groups on it inside a component (a group
    that is a part of a definition is shared by its copies)."""
    stack = [(g, False) for g in groups or ()]
    while stack:
        g, inside = stack.pop()
        comp = g.xform is not None and bool(getattr(g, "component", True))
        if (g is not group and g.mesh is proto and g.xform is not None
                and (comp or inside)):
            yield g
        stack.extend((c, inside or comp) for c in g.children or ())


def share_parts(groups, group, proto) -> list:
    """Give every other copy of ``proto`` the parts ``group`` now has — copies
    sharing their meshes (``copy_group`` inside a definition). A part that
    still stands keeps its uid in each copy, so a scene that hides it still
    does. Returns ``[(copy, its old parts)]`` for undo."""
    from core.group import copy_group
    undo = []
    for sib in list(definition_copies(groups, proto, group)):
        old = list(sib.children or ())
        new = [copy_group(c, _in_definition=True)
               for c in group.children or ()]
        pool = list(old)
        for n, c in zip(new, group.children or ()):
            for o in pool:
                if o.mesh is c.mesh:
                    n.uid = o.uid
                    pool.remove(o)
                    break
        sib.children = new
        if new and sib.xform is None:
            sib.xform = QMatrix4x4()
        undo.append((sib, old))
    return undo


def close_definition(scene, share) -> bool:
    """Leave without the undo history (the scene alone: tests, the AI
    bridge): the mesh goes back into the definition, the parts into its
    frame, and the other copies take them when they changed. Returns
    whether anything reached the definition."""
    group, proto, xform, state0 = share
    parts = share.parts
    moved = parts.changed()
    edited = group.mesh.capture_state() != state0
    if edited:
        scene.share_back(group, proto, xform, group.mesh)
    else:
        scene.restore_sharing(group, proto, xform)
    parts.settle()
    if moved:
        share_parts(scene.groups, group, proto)
    return edited or moved
