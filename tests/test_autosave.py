# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Auto-save recovery slots (core/autosave.py).

The invariant under test: a slot exists only between write() and clear() —
its existence IS the "interrupted session" signal. Slots live in the user
data dir (not beside the document: syncing drives have truncated mid-write
files there), one per absolute document path plus an untitled slot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D

import core.autosave as autosave
from core.edits import build_add_edges
from core.history import History
from core.scene import Scene

#: The genuine ``autosave_dir``, captured at import — the fixture below
#: replaces it on the module for every test, and the APPDATA test needs
#: the real one.
_real_autosave_dir = autosave.autosave_dir


@pytest.fixture(autouse=True)
def slot_dir(tmp_path, monkeypatch):
    """Every test gets its own slot directory — never the real user one."""
    d = tmp_path / "autosave"
    d.mkdir()
    monkeypatch.setattr(autosave, "autosave_dir", lambda: d)
    return d


def _scene_with_square():
    scene = Scene()
    hist = History(scene)
    sq = [QVector3D(0, 0, 0), QVector3D(2, 0, 0),
          QVector3D(2, 2, 0), QVector3D(0, 2, 0)]
    hist.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)],
        detect_faces=True))
    return scene


def test_slots_are_per_absolute_path():
    a = autosave.slot_for(Path("/proyectos/casa.igz"))
    b = autosave.slot_for(Path("/otro/casa.igz"))
    assert a != b                       # same stem, different folder
    assert a == autosave.slot_for(Path("/proyectos/casa.igz"))
    assert a.name.startswith("casa-") and a.suffix == ".igz"
    assert autosave.slot_for(None).name == "untitled.igz"


def test_write_pending_clear_round_trip():
    scene = _scene_with_square()
    doc = Path("/proyectos/piscina.igz")
    assert autosave.pending(doc) is None

    slot = autosave.write(scene, doc)
    assert autosave.pending(doc) == slot
    assert autosave.pending(None) is None   # the untitled slot is separate

    # The slot is a loadable .igz with the drawing in it.
    from formats import igz
    restored = Scene()
    igz.load_into(restored, slot)
    assert len(restored.mesh.faces) == 1
    assert len(restored.mesh.edges) == 4

    autosave.clear(doc)
    assert autosave.pending(doc) is None
    autosave.clear(doc)                     # clearing twice is a no-op


def test_clear_retires_the_slot_instead_of_deleting_it(slot_dir, monkeypatch):
    """"Quit without saving" answered by mistake must not erase the only
    copy of a session: the slot moves to descartados/ and the newest
    KEEP_DISCARDED stay there."""
    scene = _scene_with_square()
    doc = Path("/tmp/proyecto/banca.igz")
    slot = autosave.write(scene, doc)
    assert autosave.pending(doc) == slot
    data = slot.read_bytes()
    autosave.clear(doc)
    assert autosave.pending(doc) is None                 # clean goodbye
    kept = list(autosave.discarded_dir().glob("*.igz"))
    assert len(kept) == 1 and kept[0].read_bytes() == data
    assert kept[0].name.startswith("banca-")
    # pruning: only the newest KEEP_DISCARDED survive
    monkeypatch.setattr(autosave, "KEEP_DISCARDED", 3)
    import os, time
    for i in range(5):
        autosave.write(scene, doc)
        autosave.clear(doc)
        for j, f in enumerate(sorted(autosave.discarded_dir().glob("*.igz"))):
            os.utime(f, (time.time() - 100 + j, time.time() - 100 + j))
    assert len(list(autosave.discarded_dir().glob("*.igz"))) <= 3
    # clearing a document without a slot is a no-op
    autosave.clear(Path("/tmp/proyecto/otro.igz"))


def test_autosave_dir_follows_process_appdata_on_windows(tmp_path,
                                                          monkeypatch):
    """#1180: QStandardPaths resolves the roaming folder through the OS
    and never reads the process's APPDATA, so a test run that pointed
    APPDATA at a sandbox (conftest does) still wrote its slots into the
    developer's real profile. On win32 the dir must be built from the
    variable, keeping the org/app suffix Qt appends."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    d = _real_autosave_dir()
    assert d == (tmp_path / "Roaming" / "IngeTrazo" / "IngeTrazo"
                 / "autosave")
    assert d.is_dir()
