# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Folders of the Scenes tab (#1158) — the way the Layers tab files layers.

A folder is a name; ``scene.scene_folders`` lists them in order, empty ones
included, and ``scene.scene_folder_parents`` says which folder each one
sits in (absent: at the top), so folders nest as deep as wanted. A scene
names its folder in ``SavedView.folder`` (``None``: at the top; a folder
the document does not have counts as the top, so a scene never drops out
of sight).

Within a folder the subfolders come first, then the scenes, as in Layers.
``scene.saved_views`` stays THE order of the scenes — the scene tabs, the
sheets' list and every menu read it — and :func:`sync_order` keeps it equal
to the tree read from top to bottom, so the order is the same everywhere.

Nothing here is undoable by itself: :class:`core.history.SceneTreeCommand`
runs these helpers and keeps the undo.
"""
from __future__ import annotations


def folders_of(scene) -> list[str]:
    """The folder names, in order: the ones the document lists, then any a
    scene names that is missing there."""
    out = [f for f in getattr(scene, "scene_folders", None) or ()
           if isinstance(f, str) and f]
    out = list(dict.fromkeys(out))
    for v in getattr(scene, "saved_views", None) or ():
        if v.folder and v.folder not in out:
            out.append(v.folder)
    return out


def folder_parent(scene, name: str) -> str | None:
    """The folder ``name`` sits in, or ``None`` at the top. A parent that
    is gone, or one that would close a loop, counts as the top."""
    parents = getattr(scene, "scene_folder_parents", None) or {}
    known = set(folders_of(scene))
    parent = parents.get(name)
    if not parent or parent not in known or parent == name:
        return None
    seen = {name}
    up = parent
    while up is not None:
        if up in seen:
            return None
        seen.add(up)
        up = parents.get(up) if parents.get(up) in known else None
    return parent


def folder_of(scene, view) -> str | None:
    """The folder ``view`` is shown in (``None``: at the top)."""
    return view.folder if view.folder in folders_of(scene) else None


def subfolders(scene, name: str | None, deep: bool = False) -> list[str]:
    """The folders directly in ``name`` (``None``: the top) — or, ``deep``,
    at any depth."""
    out = [f for f in folders_of(scene) if folder_parent(scene, f) == name]
    if deep:
        for f in list(out):
            out += subfolders(scene, f, deep=True)
    return out


def scenes_in(scene, name: str | None) -> list:
    """The scenes directly in ``name`` (``None``: the top), in order."""
    return [v for v in scene.saved_views if folder_of(scene, v) == name]


def tree_order(scene) -> list:
    """Every scene, read from top to bottom: in each level the subfolders
    first (with all they hold), then its scenes."""
    out: list = []

    def level(name) -> None:
        for f in subfolders(scene, name):
            level(f)
        out.extend(scenes_in(scene, name))
    level(None)
    return out


def sync_order(scene) -> None:
    """``scene.saved_views`` in the tree's order (the same list object)."""
    order = tree_order(scene)
    if [id(v) for v in order] != [id(v) for v in scene.saved_views]:
        scene.saved_views[:] = order


def unique_name(taken, base: str) -> str:
    taken = set(taken)
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def add_folder(scene, base: str, parent: str | None = None) -> str:
    """A new, empty folder at the end of ``parent`` (``None``: the top);
    its name, made unique."""
    name = unique_name(folders_of(scene), base)
    scene.scene_folders = folders_of(scene) + [name]
    if parent and parent in folders_of(scene):
        scene.scene_folder_parents = {
            **(getattr(scene, "scene_folder_parents", None) or {}),
            name: parent}
    return name


def rename_folder(scene, old: str, new: str) -> bool:
    """Rename a folder, carrying its scenes and subfolders along. False
    (nothing changed) when ``new`` is empty, the same, or taken."""
    new = (new or "").strip()
    folders = folders_of(scene)
    if not new or new == old or old not in folders or new in folders:
        return False
    scene.scene_folders = [new if f == old else f for f in folders]
    parents = dict(getattr(scene, "scene_folder_parents", None) or {})
    parents = {(new if f == old else f): (new if p == old else p)
               for f, p in parents.items()}
    scene.scene_folder_parents = parents
    for v in scene.saved_views:
        if v.folder == old:
            v.folder = new
    return True


def delete_folder(scene, name: str) -> bool:
    """Take a folder away; what it held goes to the folder it sat in."""
    folders = folders_of(scene)
    if name not in folders:
        return False
    up = folder_parent(scene, name)
    parents = dict(getattr(scene, "scene_folder_parents", None) or {})
    for f in folders:
        if parents.get(f) == name:
            if up is None:
                parents.pop(f, None)
            else:
                parents[f] = up
    parents.pop(name, None)
    for v in scene.saved_views:
        if v.folder == name:
            v.folder = up
    scene.scene_folders = [f for f in folders if f != name]
    scene.scene_folder_parents = parents
    sync_order(scene)
    return True


def move_folder(scene, name: str, parent: str | None) -> bool:
    """Put folder ``name`` inside ``parent`` (``None``: at the top). Never
    into itself or into a folder it holds."""
    folders = folders_of(scene)
    if name not in folders or (parent is not None and parent not in folders):
        return False
    if parent == name or parent in subfolders(scene, name, deep=True):
        return False
    parents = dict(getattr(scene, "scene_folder_parents", None) or {})
    if parent is None:
        parents.pop(name, None)
    else:
        parents[name] = parent
    scene.scene_folders = folders
    scene.scene_folder_parents = parents
    return True


def move_rows(scene, views, folders, folder: str | None,
              before=None) -> None:
    """A drop: ``views`` (scenes) and ``folders`` go into ``folder``
    (``None``: the top); the scenes right before scene ``before`` when one
    is given, else at the end of that folder. Then the scenes in the tree's
    order."""
    for f in folders:
        move_folder(scene, f, folder)
    moving = [v for v in scene.saved_views if any(v is m for m in views)]
    for v in moving:
        v.folder = folder
    if moving:
        rest = [v for v in scene.saved_views
                if not any(v is m for m in moving)]
        at = len(rest)
        if before is not None and any(v is before for v in rest):
            at = next(i for i, v in enumerate(rest) if v is before)
        else:
            mine = [i for i, v in enumerate(rest)
                    if folder_of(scene, v) == folder]
            at = mine[-1] + 1 if mine else len(rest)
        rest[at:at] = moving
        scene.saved_views[:] = rest
    sync_order(scene)


def state(scene) -> tuple:
    """Everything a folder change touches, to put back on undo."""
    return (list(scene.saved_views),
            [(v, v.folder) for v in scene.saved_views],
            list(getattr(scene, "scene_folders", None) or ()),
            dict(getattr(scene, "scene_folder_parents", None) or {}))


def signature(scene) -> tuple:
    """What the tree shows, comparable: whether a change changed anything."""
    return (tuple((id(v), v.folder) for v in scene.saved_views),
            tuple(getattr(scene, "scene_folders", None) or ()),
            tuple(sorted((getattr(scene, "scene_folder_parents", None)
                          or {}).items())))


def restore(scene, saved: tuple) -> None:
    views, folders_of_views, folders, parents = saved
    scene.saved_views[:] = views
    for v, f in folders_of_views:
        v.folder = f
    scene.scene_folders = list(folders)
    scene.scene_folder_parents = dict(parents)
