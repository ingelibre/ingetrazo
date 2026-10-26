# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Folders for the sheets — the tree the sheet explorer shows.

A folder is a name and a parent (``None`` at the top), so folders nest as
deep as wanted. A sheet (:class:`~core.composition.Composicion`) names the
folder it sits in with ``folder_id`` (``None`` at the top).

Folders and sheets mix freely inside a folder: a folder's ``pos`` says how
many of its sibling sheets come before it (0: above them all, which is
where every folder of an older file sits). :func:`children` reads a level
in that mixed order.

``scene.compositions`` stays THE order of the sheets — the sheet tabs, the
PDF atlas and ``{hoja}`` all read it — and :func:`sync_order` keeps it equal
to the tree read from top to bottom. Folders keep their order in
``scene.sheet_folders``.

Sheets are compared by identity here, never with ``==``: two sheets with
the same contents are still two sheets.

Nothing here is undoable by itself: the commands in :mod:`core.history`
call these helpers and keep the undo.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


def new_folder_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(eq=False)
class SheetFolder:
    """A folder of the sheet explorer. Identity-equal, like the sheets."""

    name: str = "Folder"
    parent_id: Optional[str] = None
    id: str = field(default_factory=new_folder_id)
    #: Whether the explorer shows it open — saved with the document, so a
    #: file opens the way it was left.
    expanded: bool = True
    #: The folder's own Print switch, on by default. Off leaves out of
    #: Print all and Export all everything inside it — whatever the sheets'
    #: own switches say, which come back when it is on again (as a hidden
    #: group hides what it holds in the Browser). What is moved in or out
    #: never changes it.
    print_in_all: bool = True
    #: Where it sits among its sibling SHEETS: how many of them come before
    #: it (0: above them all). Folders with the same ``pos`` keep their
    #: order in ``scene.sheet_folders``.
    pos: int = 0

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name}
        if self.parent_id is not None:
            d["parent_id"] = self.parent_id
        if not self.expanded:
            d["expanded"] = False
        if not self.print_in_all:
            d["print_in_all"] = False
        if self.pos:
            d["pos"] = int(self.pos)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SheetFolder":
        parent = d.get("parent_id")
        try:
            pos = max(0, int(d.get("pos", 0) or 0))
        except (TypeError, ValueError):
            pos = 0
        return cls(name=str(d.get("name") or "Folder"),
                   parent_id=str(parent) if parent is not None else None,
                   id=str(d.get("id") or new_folder_id()),
                   expanded=bool(d.get("expanded", True)),
                   print_in_all=bool(d.get("print_in_all", True)),
                   pos=pos)


# ---- Reading the tree ------------------------------------------------------

def folders_of(scene) -> list:
    return getattr(scene, "sheet_folders", None) or []


def folder_by_id(scene, folder_id) -> Optional[SheetFolder]:
    if folder_id is None:
        return None
    return next((f for f in folders_of(scene) if f.id == folder_id), None)


def subfolders(scene, parent_id) -> list:
    """The folders directly inside ``parent_id`` (``None``: the top), in
    their order."""
    return [f for f in folders_of(scene) if f.parent_id == parent_id]


def sheets_in(scene, folder_id) -> list:
    """The sheets directly inside ``folder_id`` (``None``: the top), in
    their order. A sheet naming a folder the document does not have counts
    as at the top — it must never drop out of sight."""
    comps = getattr(scene, "compositions", None) or []
    if folder_id is not None:
        return [c for c in comps if getattr(c, "folder_id", None) == folder_id]
    ids = {f.id for f in folders_of(scene)}
    return [c for c in comps
            if getattr(c, "folder_id", None) is None
            or getattr(c, "folder_id", None) not in ids]


def children(scene, parent_id) -> list:
    """What sits directly inside ``parent_id`` (``None``: the top) —
    folders and sheets mixed, in the order the explorer shows them."""
    folders = subfolders(scene, parent_id)
    sheets = sheets_in(scene, parent_id)
    out: list = []
    for k, sheet in enumerate(sheets):
        out.extend(f for f in folders if min(max(f.pos, 0), len(sheets)) == k)
        out.append(sheet)
    out.extend(f for f in folders if min(max(f.pos, 0), len(sheets))
               == len(sheets))
    return out


def descendant_ids(scene, folder_id) -> set:
    """The ids of every folder inside ``folder_id``, at any depth (not
    ``folder_id`` itself)."""
    out: set = set()
    todo = [folder_id]
    while todo:
        fid = todo.pop()
        for f in subfolders(scene, fid):
            if f.id not in out:
                out.add(f.id)
                todo.append(f.id)
    return out


def _walk(scene):
    """Every folder and sheet, top to bottom (folders before what they
    hold)."""
    out: list = []
    seen: set = set()

    def walk(folder_id) -> None:
        for item in children(scene, folder_id):
            if isinstance(item, SheetFolder):
                if item.id in seen:     # a cycle: repair() breaks those
                    continue
                seen.add(item.id)
                out.append(item)
                walk(item.id)
            else:
                out.append(item)
    walk(None)
    return out


def tree_order(scene) -> list:
    """Every sheet, in the order the explorer shows them top to bottom."""
    out = [x for x in _walk(scene) if not isinstance(x, SheetFolder)]
    # Sheets in a folder the walk never reached (a cycle cut off) still
    # count: at the end, in their order.
    listed = {id(c) for c in out}
    out.extend(c for c in getattr(scene, "compositions", None) or []
               if id(c) not in listed)
    return out


def sync_order(scene) -> bool:
    """Re-sort ``scene.compositions`` to the tree. True if it changed."""
    comps = getattr(scene, "compositions", None)
    if comps is None:
        return False
    ordered = tree_order(scene)
    if [id(c) for c in ordered] == [id(c) for c in comps]:
        return False
    comps[:] = ordered
    return True


def folder_printed(scene, folder_id) -> bool:
    """Whether folder ``folder_id`` and every folder around it are switched
    on for printing (``None``, the top, always is)."""
    seen: set = set()
    while folder_id is not None and folder_id not in seen:
        seen.add(folder_id)
        f = folder_by_id(scene, folder_id)
        if f is None:
            return True
        if not f.print_in_all:
            return False
        folder_id = f.parent_id
    return True


def sheet_printed(scene, sheet) -> bool:
    """Whether Print all takes ``sheet``: its own switch on, and every
    folder around it on."""
    return bool(getattr(sheet, "print_in_all", True)) and folder_printed(
        scene, getattr(sheet, "folder_id", None))


def printed_sheets(scene) -> list:
    """The sheets Print all and Export all take — switched on, in folders
    switched on — in tree order."""
    return [c for c in tree_order(scene) if sheet_printed(scene, c)]


# ---- Repairs (a damaged or hand-edited file still opens) --------------------

def repair(scene) -> int:
    """Make the folder tree consistent; returns how many things it fixed.

    * two folders with the same id → the later one gets a new id;
    * a folder whose parent is missing, or that sits inside itself (a
      cycle) → top level;
    * a sheet whose folder is missing → top level;
    * the sheet order re-sorted to the tree."""
    folders = folders_of(scene)
    fixed = 0
    seen: set = set()
    for f in folders:
        if f.id in seen:
            f.id = new_folder_id()
            fixed += 1
        seen.add(f.id)
    ids = {f.id for f in folders}
    for f in folders:
        if f.parent_id is not None and f.parent_id not in ids:
            f.parent_id = None
            fixed += 1
    by_id = {f.id: f for f in folders}
    for f in folders:
        # Walk up; meeting f again means f is inside itself.
        p, steps = f.parent_id, 0
        while p is not None and steps <= len(folders):
            if p == f.id:
                f.parent_id = None
                fixed += 1
                break
            p = by_id[p].parent_id if p in by_id else None
            steps += 1
    for c in getattr(scene, "compositions", None) or []:
        fid = getattr(c, "folder_id", None)
        if fid is not None and fid not in ids:
            c.folder_id = None
            fixed += 1
    sync_order(scene)
    return fixed


# ---- Snapshot (what the undoable commands restore) --------------------------

def capture(scene) -> dict:
    """The whole sheet tree as it stands: which folders, their names,
    parents, places and order, each sheet's folder and Print flag, the
    sheet order. The objects themselves are kept, so undo puts back the
    very same folders and sheets."""
    folders = list(folders_of(scene))
    comps = list(getattr(scene, "compositions", None) or [])
    return {
        "folders": folders,
        "folder_state": [(f.name, f.parent_id, f.expanded, f.print_in_all,
                          f.pos) for f in folders],
        "sheets": comps,
        "sheet_state": [(getattr(c, "folder_id", None),
                         getattr(c, "print_in_all", True)) for c in comps],
    }


def restore(scene, snap: dict) -> None:
    """Put the tree back as :func:`capture` saw it — but never add or take
    away a SHEET: the composer makes and deletes sheets outside this undo
    (the «+» tab, Delete sheet), and putting the old list back undid those
    too, behind the composer's back — a deleted sheet came back, a new one
    vanished while the composer still showed it. So the sheets that exist
    now stay; those the snapshot knows get their folder, Print flag and
    order back, a newer one keeps its place after the sheet it followed."""
    scene.sheet_folders[:] = snap["folders"]
    for f, (name, parent, expanded, printed, pos) in zip(
            snap["folders"], snap["folder_state"]):
        f.name, f.parent_id, f.expanded = name, parent, expanded
        f.print_in_all, f.pos = printed, pos
    known = {id(c): state for c, state in zip(snap["sheets"],
                                               snap["sheet_state"])}
    now = list(scene.compositions)
    present = {id(c) for c in now}
    ordered = [c for c in snap["sheets"] if id(c) in present]
    for i, c in enumerate(now):
        if id(c) in known:
            continue
        # A sheet the snapshot never saw: after the one it follows now.
        placed = {id(x) for x in ordered}
        prev = next((p for p in reversed(now[:i]) if id(p) in placed), None)
        at = (next(k for k, x in enumerate(ordered) if x is prev) + 1
              if prev is not None else 0)
        ordered.insert(at, c)
    for c in ordered:
        if id(c) in known:
            c.folder_id, c.print_in_all = known[id(c)]
    scene.compositions[:] = ordered
    # A newer sheet may sit in a folder the snapshot does not have.
    ids = {f.id for f in snap["folders"]}
    for c in ordered:
        if c.folder_id is not None and c.folder_id not in ids:
            c.folder_id = None
    sync_order(scene)


# ---- Edits (called by the commands) -----------------------------------------

def can_move_folder(scene, folder, target_id) -> bool:
    """A folder may go anywhere but into itself or a folder inside it."""
    if target_id is None:
        return True
    return target_id != folder.id and \
        target_id not in descendant_ids(scene, folder.id)


def _layout(scene) -> dict:
    """``{parent id: [children…]}`` for the top and every folder."""
    lay = {None: children(scene, None)}
    for f in folders_of(scene):
        lay[f.id] = children(scene, f.id)
    return lay


def _apply(scene, lay: dict) -> None:
    """Write a layout back: each child's parent, each folder's place among
    its sibling sheets, and the folder and sheet orders, read from the top
    down."""
    folders: list = []
    sheets: list = []
    seen: set = set()

    def walk(parent_id) -> None:
        before = 0
        for item in lay.get(parent_id, ()):
            if isinstance(item, SheetFolder):
                if item.id in seen:
                    continue
                seen.add(item.id)
                item.parent_id = parent_id
                item.pos = before
                folders.append(item)
                walk(item.id)
            else:
                item.folder_id = parent_id
                sheets.append(item)
                before += 1
    walk(None)
    listed = {id(x) for x in sheets}
    sheets += [c for c in getattr(scene, "compositions", None) or []
               if id(c) not in listed]
    kept = {id(f) for f in folders}
    folders += [f for f in folders_of(scene) if id(f) not in kept]
    scene.sheet_folders[:] = folders
    scene.compositions[:] = sheets


def move_items(scene, sheets, folders, target_id, before=None) -> None:
    """Put ``sheets`` and ``folders`` into folder ``target_id`` (``None``:
    the top), in front of ``before`` (a sheet or a folder there; ``None``:
    at the end), in the order they are shown. A folder that would land
    inside itself stays where it is, and what a moving folder holds travels
    with it."""
    folders = [f for f in folders if can_move_folder(scene, f, target_id)]
    inside: set = set()
    for f in folders:
        inside |= {f.id} | descendant_ids(scene, f.id)
    moving_ids = {id(c) for c in sheets if c.folder_id not in inside}
    moving_ids |= {id(f) for f in folders if f.parent_id not in inside}
    if not moving_ids:
        return
    moving = [x for x in _walk(scene) if id(x) in moving_ids]
    lay = _layout(scene)
    for key in lay:
        lay[key] = [x for x in lay[key] if id(x) not in moving_ids]
    target = lay.setdefault(target_id, [])
    at = next((k for k, x in enumerate(target) if x is before), len(target))
    target[at:at] = moving
    _apply(scene, lay)


def delete_folders(scene, folders) -> None:
    """Remove ``folders``; what they hold — sheets and subfolders — moves one
    level up, in the folder's place, to the nearest folder above that is
    not being removed."""
    gone = {f.id for f in folders}
    lay = _layout(scene)
    changed = True
    while changed:                      # a removed folder inside another
        changed = False
        for key, items in lay.items():
            out: list = []
            for x in items:
                if isinstance(x, SheetFolder) and x.id in gone:
                    out.extend(lay.get(x.id, ()))
                    changed = True
                else:
                    out.append(x)
            lay[key] = out
    for fid in gone:
        lay.pop(fid, None)
    keep = [f for f in folders_of(scene) if f.id not in gone]
    scene.sheet_folders[:] = keep
    _apply(scene, lay)
