# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Auto-save recovery slots (core/autosave.py).

The invariant under test: a slot exists only between write() and clear() —
its existence IS the "interrupted session" signal. Slots live in the user
data dir (not beside the document: syncing drives have truncated mid-write
files there), one per absolute document path plus an untitled slot.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D

import core.autosave as autosave
from core.edits import build_add_edges
from core.history import History
from core.scene import Scene


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
