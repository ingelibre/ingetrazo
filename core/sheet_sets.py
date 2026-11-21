# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet sets (plan sets, #1519) — named, ordered selections of the sheets.

The same model feeds several audiences — the permit, the roofer, the
carpenter, the client — and each wants its own sheets in its own order. A
:class:`SheetSet` is a name and an ordered list of sheet references; a
sheet may be in no set, one, or several. Sets live in ``scene.sheet_sets``.

* A set names its sheets by their ``uid`` (see
  :attr:`core.composition.Composicion.uid`), never by name or position: a
  sheet renamed or moved in the explorer stays in its sets. A sheet gets
  its uid the first time it joins a set (:func:`sheet_uid`), so documents
  without sets save exactly as before.
* "All sheets" is implicit — it is no :class:`SheetSet` and is never
  stored: it is what Print all takes (:func:`core.sheet_folders.printed_sheets`).
* The explorer's Print flag filters every set too: a set prints those of
  its members whose own switch and every folder around them are on
  (:func:`export_list`).
* A sheet deleted leaves every set (:func:`prune`); a set deleted never
  deletes a sheet.

Nothing here is undoable by itself: the commands in :mod:`core.history`
call these helpers and keep the undo (:func:`capture` / :func:`restore`).
"""
from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Optional


class SheetSetError(ValueError):
    """A set that does not exist, or a name already taken."""


def new_set_id() -> str:
    return uuid.uuid4().hex[:12]


def new_sheet_uid() -> str:
    return uuid.uuid4().hex


@dataclass(eq=False)
class SheetSet:
    """A named, ordered selection of sheets. Identity-equal."""

    name: str = "Set"
    #: The member sheets' uids, in the set's own order.
    sheet_uids: list = field(default_factory=list)
    id: str = field(default_factory=new_set_id)
    #: An optional cover / index sheet: printed first, whether or not it
    #: is also in ``sheet_uids``. "" = none.
    cover_uid: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name,
             "sheets": list(self.sheet_uids)}
        if self.cover_uid:
            d["cover"] = self.cover_uid
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SheetSet":
        uids = d.get("sheets") or []
        if not isinstance(uids, list):
            uids = []
        return cls(name=str(d.get("name") or "Set"),
                   sheet_uids=[str(u) for u in uids if u],
                   id=str(d.get("id") or new_set_id()),
                   cover_uid=str(d.get("cover") or ""),
                   description=str(d.get("description") or ""))


# ---- Reading -------------------------------------------------------------------

def sets_of(scene) -> list:
    return getattr(scene, "sheet_sets", None) or []


def _comps(scene) -> list:
    return list(getattr(scene, "compositions", None) or [])


def _norm(name) -> str:
    return unicodedata.normalize("NFC", str(name or "")).strip().casefold()


def sheet_uid(sheet) -> str:
    """``sheet``'s uid, given one now if it has none yet."""
    if not getattr(sheet, "uid", ""):
        sheet.uid = new_sheet_uid()
    return sheet.uid


def sheet_by_uid(scene, uid) -> Optional[object]:
    if not uid:
        return None
    return next((c for c in _comps(scene) if getattr(c, "uid", "") == uid),
                None)


def set_by_id(scene, set_id) -> Optional[SheetSet]:
    return next((s for s in sets_of(scene) if s.id == set_id), None)


def find_set(scene, ref) -> Optional[SheetSet]:
    """The set ``ref`` names — the object, its id or its name (any case);
    ``None``, "" or "All sheets" mean the implicit all-sheets set and give
    ``None``. Unknown: :class:`SheetSetError`."""
    if ref is None or isinstance(ref, SheetSet) and ref in sets_of(scene):
        return ref
    if isinstance(ref, SheetSet):
        raise SheetSetError(f"the set {ref.name!r} is not in this document")
    key = str(ref).strip()
    if not key or _norm(key) in ("all sheets", "*", "all"):
        return None
    hit = set_by_id(scene, key)
    if hit is not None:
        return hit
    for s in sets_of(scene):
        if _norm(s.name) == _norm(key):
            return s
    raise SheetSetError(f"no sheet set {ref!r}; sets: " + (", ".join(
        repr(s.name) for s in sets_of(scene)) or "none"))


def members(scene, s: SheetSet) -> list:
    """The sheets of ``s`` that exist, in the set's order — its cover
    first. Each sheet once."""
    out: list = []
    seen: set = set()
    for uid in ([s.cover_uid] if s.cover_uid else []) + list(s.sheet_uids):
        c = sheet_by_uid(scene, uid)
        if c is not None and id(c) not in seen:
            seen.add(id(c))
            out.append(c)
    return out


def export_list(scene, ref=None) -> list:
    """What printing or exporting set ``ref`` takes: All sheets (``None``)
    is Print all; a set is its members whose Print flag and every folder
    around them are on, in the set's order."""
    from core.sheet_folders import printed_sheets, sheet_printed
    s = find_set(scene, ref)
    if s is None:
        return printed_sheets(scene)
    return [c for c in members(scene, s) if sheet_printed(scene, c)]


def sets_of_sheet(scene, sheet) -> list:
    """The sets ``sheet`` is in (as a member or as their cover)."""
    uid = getattr(sheet, "uid", "")
    if not uid:
        return []
    return [s for s in sets_of(scene)
            if uid in s.sheet_uids or s.cover_uid == uid]


def unique_name(scene, wanted: str, ignore: Optional[SheetSet] = None) -> str:
    """``wanted``, or ``wanted (2)``, ``(3)``… if a set has it already."""
    taken = {_norm(s.name) for s in sets_of(scene) if s is not ignore}
    base = str(wanted or "").strip() or "Set"
    name, n = base, 2
    while _norm(name) in taken:
        name, n = f"{base} ({n})", n + 1
    return name


# ---- Edits (called by the commands) --------------------------------------------

def add_to_set(scene, s: SheetSet, sheet) -> None:
    """Put ``sheet`` into ``s`` — where the explorer's order puts it among
    the members, so a set made by ticking sheets reads like the tree."""
    uid = sheet_uid(sheet)
    if uid in s.sheet_uids:
        return
    order = {id(c): i for i, c in enumerate(_comps(scene))}
    mine = order.get(id(sheet), len(order))
    at = len(s.sheet_uids)
    for k, u in enumerate(s.sheet_uids):
        other = sheet_by_uid(scene, u)
        if other is not None and order.get(id(other), -1) > mine:
            at = k
            break
    s.sheet_uids.insert(at, uid)


def remove_from_set(s: SheetSet, sheet) -> None:
    uid = getattr(sheet, "uid", "")
    s.sheet_uids[:] = [u for u in s.sheet_uids if u != uid]
    if uid and s.cover_uid == uid:
        s.cover_uid = ""


def set_sheet_sets(scene, sheet, wanted) -> None:
    """Make ``sheet`` a member of exactly the sets in ``wanted``."""
    want = {id(s) for s in wanted}
    for s in sets_of(scene):
        if id(s) in want:
            add_to_set(scene, s, sheet)
        else:
            remove_from_set(s, sheet)


def set_members(scene, s: SheetSet, sheets) -> None:
    """Replace ``s``'s members with ``sheets``, in that order."""
    uids: list = []
    for c in sheets:
        u = sheet_uid(c)
        if u not in uids:
            uids.append(u)
    s.sheet_uids[:] = uids


def prune(scene) -> int:
    """Drop from every set the sheets the document no longer has; how many
    references went."""
    have = {getattr(c, "uid", "") for c in _comps(scene)} - {""}
    gone = 0
    for s in sets_of(scene):
        keep = [u for u in s.sheet_uids if u in have]
        gone += len(s.sheet_uids) - len(keep)
        s.sheet_uids[:] = keep
        if s.cover_uid and s.cover_uid not in have:
            s.cover_uid = ""
            gone += 1
    return gone


def repair(scene) -> int:
    """Make the sets consistent after opening a file; how many things it
    fixed: two sheets with one uid (the later one gets a new uid, the sets
    keep the first), two sets with one id or one name, a sheet listed
    twice in a set, references to sheets the document does not have."""
    fixed = 0
    seen_uids: set = set()
    for c in _comps(scene):
        u = getattr(c, "uid", "")
        if u and u in seen_uids:
            c.uid = new_sheet_uid()
            fixed += 1
        elif u:
            seen_uids.add(u)
    seen_ids: set = set()
    seen_names: set = set()
    for s in sets_of(scene):
        if s.id in seen_ids:
            s.id = new_set_id()
            fixed += 1
        seen_ids.add(s.id)
        # The first set keeps its name; a later twin gets "(2)", "(3)"…
        base = str(s.name or "").strip() or "Set"
        name, n = base, 2
        while _norm(name) in seen_names:
            name, n = f"{base} ({n})", n + 1
        if name != s.name:
            s.name = name
            fixed += 1
        seen_names.add(_norm(name))
        once: list = []
        for u in s.sheet_uids:
            if u not in once:
                once.append(u)
        fixed += len(s.sheet_uids) - len(once)
        s.sheet_uids[:] = once
    return fixed + prune(scene)


# ---- Undo -----------------------------------------------------------------------

def capture(scene) -> dict:
    """The sets as they stand: which sets, in which order, each one's
    name, members, cover and description; and which sheets have a uid (a
    sheet given one by the edit gets it taken back on undo)."""
    sets = list(sets_of(scene))
    return {"sets": sets,
            "state": [(s.name, list(s.sheet_uids), s.cover_uid,
                       s.description) for s in sets],
            "uids": [(c, getattr(c, "uid", "")) for c in _comps(scene)]}


def restore(scene, snap: dict) -> None:
    """Put the sets back as :func:`capture` saw them. Sheets are never
    added or removed here; a sheet deleted since simply drops out."""
    scene.sheet_sets[:] = snap["sets"]
    for s, (name, uids, cover, desc) in zip(snap["sets"], snap["state"]):
        s.name, s.cover_uid, s.description = name, cover, desc
        s.sheet_uids[:] = uids
    present = {id(c) for c in _comps(scene)}
    for c, uid in snap["uids"]:
        if id(c) in present:
            c.uid = uid
