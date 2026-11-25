# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
# The per-copy matrix (move, then turn about a centre, the copy keeping
# its own reference point) is adapted from the Array extension by Pesi
# (github.com/PESI3D/ingetrazo-array), GPL-3.0-or-later.
"""Live arrays: an array that remembers how it was made.

``3x`` / ``/3`` typed after a Move- or Rotate-copy of groups or components
used to leave loose copies behind: twelve louvres instead of nine meant
deleting them and starting again. Now the original and its copies go into
one container — the array — whose ``array`` keeps the recipe: how many
copies, the step (a distance or an angle) and whether it repeats or
divides. Change any of them later (Entity Info) and the copies are laid
out again from the original, in one undo step; the recipe is saved in the
``.igz``. Explode gives back the plain copies of before.

The recipe, ``Group.array``::

    {"version": 1, "kind": "move" | "rotate",
     "count": 4,                    # copies, the original not counted
     "mode": "x" | "/",             # repeat the step | divide it
     "step": [x, y, z],             # move: the copy's offset
     "angle": 30.0, "center": [...], "axis": [...],   # rotate
     "frame": [16 floats],          # recipe space → container space
     "source": [uid, ...],          # the originals, laid out again
     "copies": [uid, ...]}          # what a re-layout replaces

The step is written in the space the tool worked in (the world's, for a
top-level array). ``frame`` carries it into the container's own space,
which changes when opening the container pushes its matrix down into the
children (``Scene._bake_container_xform``) — so the recipe stays true
wherever the array has been moved or turned since.
"""
from __future__ import annotations

import copy as _copy
from typing import Optional

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.history import Command

MAX_COPIES = 10000          # a typo («10000x») must not freeze the app


# ---- The recipe -------------------------------------------------------------

def _vec(v) -> QVector3D:
    return QVector3D(float(v[0]), float(v[1]), float(v[2]))


def _list(v: QVector3D) -> list:
    return [float(v.x()), float(v.y()), float(v.z())]


def _matrix_list(m: QMatrix4x4) -> list:
    return [float(x) for x in m.data()]          # column-major, as Qt


def _matrix(values) -> QMatrix4x4:
    if not values or len(values) != 16:
        return QMatrix4x4()
    vals = [float(x) for x in values]
    # QMatrix4x4(*16) takes ROW-major values; ``data()`` gave column-major.
    return QMatrix4x4(*[vals[col * 4 + row] for row in range(4)
                        for col in range(4)])


def move_recipe(step: QVector3D, count: int, mode: str) -> dict:
    return {"version": 1, "kind": "move", "count": int(count),
            "mode": "/" if mode == "/" else "x", "step": _list(step)}


def rotate_recipe(center: QVector3D, axis: QVector3D, angle: float,
                  count: int, mode: str) -> dict:
    return {"version": 1, "kind": "rotate", "count": int(count),
            "mode": "/" if mode == "/" else "x", "angle": float(angle),
            "center": _list(center), "axis": _list(axis),
            "step": [0.0, 0.0, 0.0]}


def is_array(group) -> bool:
    rec = getattr(group, "array", None)
    return isinstance(rec, dict) and bool(rec.get("source"))


FULL_TURN = 360.0


def is_full_turn(rec: dict) -> bool:
    """A polar array dividing the whole circle: the original and its
    copies go evenly all the way round, and the last copy does not land
    back on the original (8 posts around = 7 copies every 45°)."""
    return (rec.get("mode") == "/"
            and abs(abs(float(rec.get("angle") or 0.0)) - FULL_TURN) < 1e-6)


def _fraction(k: int, rec: dict) -> float:
    count = max(1, int(rec.get("count", 1)))
    if is_full_turn(rec):
        return k / float(count + 1)
    return k / float(count) if rec.get("mode") == "/" else float(k)


def copy_matrix(k: int, rec: dict) -> QMatrix4x4:
    """The matrix that takes the original to copy ``k`` (1-based), in the
    container's own space.

    The copy moves by its share of the step, then turns about the centre
    by its share of the angle — both at once is a helix (a spiral stair's
    treads). ``frame`` brings that from the recipe's space."""
    f = _fraction(k, rec)
    m = QMatrix4x4()
    m.translate(_vec(rec.get("step") or (0, 0, 0)) * f)
    angle = float(rec.get("angle") or 0.0) * f
    if abs(angle) > 1e-12:
        axis = _vec(rec.get("axis") or (0, 0, 1))
        if axis.length() > 1e-12:
            c = _vec(rec.get("center") or (0, 0, 0))
            m.translate(c)
            m.rotate(angle, axis.normalized())
            m.translate(-c)
    frame = _matrix(rec.get("frame"))
    if frame != QMatrix4x4():
        inv, ok = frame.inverted()
        if ok:
            m = frame * m * inv
    return m


def placed_copy(source, m: QMatrix4x4):
    """A copy of ``source`` placed by ``m``: an instance stays an instance
    of the same definition (edit one pillar, all of them change), a
    classic group gets its own mesh."""
    from core.group import carry_axes, copy_group, transformed_mesh
    g = copy_group(source)
    if g.xform is not None:
        g.xform = m * g.xform
    else:
        g.mesh = transformed_mesh(g.mesh, m)
        carry_axes(g, m)
    return g


def lay_out(sources, rec: dict) -> list:
    """The copies the recipe asks for, in order: every original, copy 1;
    every original, copy 2; …"""
    count = max(0, min(int(rec.get("count", 0)), MAX_COPIES))
    out = []
    for k in range(1, count + 1):
        m = copy_matrix(k, rec)
        out.extend(placed_copy(s, m) for s in sources)
    return out


def rebase_frame(group, xform: QMatrix4x4) -> None:
    """The container's matrix ``xform`` just went down into its children
    (opening it): the recipe's frame takes it on the left, so the step
    still points where the copies are."""
    rec = getattr(group, "array", None)
    if not isinstance(rec, dict):
        return
    rec["frame"] = _matrix_list(xform * _matrix(rec.get("frame")))


def remap_uids(rec: dict, old_children, new_children) -> dict:
    """A copied array (Copy/Paste, a Move-copy of the array itself): its
    children got new uids, so the recipe names them instead."""
    rec = _copy.deepcopy(rec)
    table = {getattr(o, "uid", None): getattr(n, "uid", None)
             for o, n in zip(old_children or (), new_children or ())}
    for key in ("source", "copies"):
        rec[key] = [table.get(u, u) for u in rec.get(key) or ()]
    return rec


def sources_of(group) -> list:
    rec = getattr(group, "array", None) or {}
    wanted = set(rec.get("source") or ())
    return [c for c in (group.children or ()) if c.uid in wanted]


def copies_of(group) -> list:
    """The array's copies still inside it — the ones deleted by hand
    (open the array, select a copy, Delete) are not."""
    rec = getattr(group, "array", None) or {}
    wanted = set(rec.get("copies") or ())
    return [c for c in (group.children or ()) if c.uid in wanted]


def removed_copies(group) -> int:
    """How many copies the recipe lays out that are no longer there."""
    rec = getattr(group, "array", None) or {}
    return max(0, len(rec.get("copies") or ()) - len(copies_of(group)))


# ---- Commands ---------------------------------------------------------------

def _owner(scene, group) -> list:
    """The list ``group`` lives in: the open container's children, or the
    model's top level."""
    ctx = getattr(scene, "edit_group", None)
    kids = getattr(ctx, "children", None) if ctx is not None else None
    if kids is not None and group in kids:
        return kids
    return scene.groups


class MakeArrayCommand(Command):
    """Wrap ``sources`` and the copies of ``recipe`` into a new array
    container, where the first original stood. The copies are made once:
    redo puts the very same objects back."""


    def __init__(self, sources, recipe: dict, name: str = "Array") -> None:
        self.sources = list(sources)
        self.recipe = dict(recipe)
        self.name = name
        self.container = None
        self._owner: Optional[list] = None
        self._places: list = []
        self._copies: Optional[list] = None

    def do(self, scene) -> None:
        from core.group import Group
        from core.mesh import Mesh
        owner = self._owner = _owner(scene, self.sources[0])
        if self._copies is None:
            rec = dict(self.recipe)
            ctx = getattr(scene, "edit_group", None)
            if (owner is not scene.groups and ctx is not None
                    and ctx.xform is not None):
                # Inside an open container with a matrix of its own: the
                # tool's step is the world's, the children's space is not.
                inv, ok = ctx.xform.inverted()
                if ok:
                    rec["frame"] = _matrix_list(inv)
            self._copies = lay_out(self.sources, rec)
            self.container = Group(Mesh(), name=self.name)
            rec["source"] = [s.uid for s in self.sources]
            rec["copies"] = [c.uid for c in self._copies]
            self.container.array = rec
        self._places = sorted(((owner.index(s), s) for s in self.sources
                               if s in owner), key=lambda p: p[0])
        at = self._places[0][0] if self._places else len(owner)
        for _i, s in self._places:
            owner.remove(s)
            scene.selection.discard(s)
        self.container.adopt(self.sources + self._copies)
        self.container.component = False
        owner.insert(min(at, len(owner)), self.container)
        scene.selection.clear()
        scene.selection.add(self.container)
        scene.version += 1

    def undo(self, scene) -> None:
        owner = self._owner if self._owner is not None else scene.groups
        if self.container in owner:
            owner.remove(self.container)
        self.container.children = []
        self.container.xform = None
        for idx, s in self._places:
            owner.insert(min(idx, len(owner)), s)
        # Back to the originals, selected, as a plain copy's undo leaves them.
        scene.selection.clear()
        scene.selection.update(s for _i, s in self._places)
        scene.version += 1


class EditArrayCommand(Command):
    """Lay an array out again with new numbers: its copies go, the recipe's
    copies come from the originals as they are now. Whatever else was
    put inside the container stays."""


    def __init__(self, container, changes: dict) -> None:
        self.container = container
        self.changes = dict(changes)
        self._old: Optional[tuple] = None
        self._new: Optional[tuple] = None

    def do(self, scene) -> None:
        g = self.container
        if self._new is None:
            self._old = (list(g.children or ()), _copy.deepcopy(g.array))
            rec = _copy.deepcopy(g.array)
            rec.update(self.changes)
            rec["count"] = max(1, min(int(rec.get("count", 1)), MAX_COPIES))
            gone = set(rec.get("copies") or ())
            sources = sources_of(g)
            kept = [c for c in g.children if c.uid not in gone]
            copies = lay_out(sources, rec)
            rec["copies"] = [c.uid for c in copies]
            self._new = (kept + copies, rec)
        g.children = list(self._new[0])
        g.array = _copy.deepcopy(self._new[1])
        for c in self._old[0]:
            if c not in g.children:
                scene.selection.discard(c)
        scene.version += 1

    def undo(self, scene) -> None:
        g = self.container
        for c in self._new[0]:
            if c not in self._old[0]:
                scene.selection.discard(c)
        g.children = list(self._old[0])
        g.array = _copy.deepcopy(self._old[1])
        scene.version += 1


def can_edit(group) -> bool:
    """An array whose originals are still inside it, with at least one of
    its copies: with every copy deleted by hand there is no array left,
    only a group with the original in it (2026-11-25: «si no hay ninguna
    copia no hay matriz»). Undoing the deletion brings it back."""
    return (is_array(group) and bool(sources_of(group))
            and bool(copies_of(group)))


def make_array(viewport, sources, recipe: dict) -> Optional[Command]:
    """The command a tool runs for ``3x`` / ``/3`` on groups, or ``None``
    when it is not a live array (fewer than two copies)."""
    if not sources or int(recipe.get("count", 0)) < 2:
        return None
    from core.i18n import tr
    return MakeArrayCommand(sources, recipe, name=tr("Array"))
