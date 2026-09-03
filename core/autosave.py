# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Auto-save recovery slots — SketchUp's General ▸ Auto-save, our way.

One ``.igz`` slot per document in the user data dir (NOT beside the
document: the project folder may live in a syncing drive — pCloud has
truncated mid-write files there before — and recovery files are session
state, not project files). The slot's name is the document's stem plus a
hash of its absolute path, so two ``casa.igz`` in different folders never
share a slot; a document with no path yet uses the ``untitled`` slot.

The invariant that makes recovery detection trivial: **a slot exists only
between a change and the next clean save/close.** The main window clears it
on save, on close, and when a document is discarded — so a slot found on
disk means a session that never got to say goodbye (crash, power cut), and
its mere existence is the "offer to recover" signal.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def autosave_dir() -> Path:
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.AppDataLocation) or str(Path.home() / ".ingetrazo")
    d = Path(base) / "autosave"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slot_for(path: Path | None) -> Path:
    """The recovery slot for a document (``None`` = the unsaved document)."""
    if path is None:
        return autosave_dir() / "untitled.igz"
    p = Path(path).absolute()
    digest = hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:8]
    return autosave_dir() / f"{p.stem}-{digest}.igz"


def write(scene, path: Path | None) -> Path:
    """Save ``scene`` into the document's slot; returns the slot path."""
    from formats import igz
    slot = slot_for(path)
    igz.save_scene(scene, slot)
    return slot


def pending(path: Path | None) -> Path | None:
    """The slot file, if an interrupted session left one."""
    slot = slot_for(path)
    return slot if slot.is_file() else None


#: How many retired slots to keep in ``autosave_dir()/descartados``.
KEEP_DISCARDED = 20


def discarded_dir() -> Path:
    d = autosave_dir() / "descartados"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear(path: Path | None) -> None:
    """Retire the document's slot (clean save / clean close / discarded).

    The slot is MOVED into ``descartados/`` with a timestamp, never deleted:
    "Quit without saving" answered by mistake used to erase the only copy
    of a whole afternoon (Marco, 2026-09-03 — five hours of a bench model
    gone at the close dialog). The invariant that drives recovery stays —
    no slot in the live folder means a clean goodbye — while the retired
    copy waits in the folder Archivo ▸ Recover a discarded auto-save… opens.
    Only the newest :data:`KEEP_DISCARDED` are kept."""
    import datetime
    slot = slot_for(path)
    if not slot.is_file():
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = discarded_dir() / f"{slot.stem}-{stamp}.igz"
    try:
        slot.replace(target)
    except OSError:
        slot.unlink(missing_ok=True)
        return
    kept = sorted(discarded_dir().glob("*.igz"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in kept[KEEP_DISCARDED:]:
        try:
            old.unlink()
        except OSError:
            pass
