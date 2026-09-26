# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Opening a document forgets every viewport cache keyed by ``id()`` (#75).

@pacaeiro: new drawing, some changes, Open a saved (big) design — «Sumari Man
got transported to the freshly opened design». The viewport caches per-group
data by ``id()``, and CPython hands a dead object's address to the next one:
a group of the opened file could meet the scale figure's entry. Every such
cache has to go at the document boundary."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def test_open_forgets_every_id_keyed_cache(tmp_path):
    from core.scene import Scene
    from formats import igz
    from views.main_window import MainWindow
    path = tmp_path / "other.igz"
    igz.save_scene(Scene(), path)
    win = MainWindow()
    vp = win.viewport
    try:
        for name in vp._DOCUMENT_CACHES:
            setattr(vp, name, {12345: "stale"})
        win._saved_version = vp.scene.version
        assert win.open_path(path)
        for name in vp._DOCUMENT_CACHES:
            assert not getattr(vp, name), name
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_every_cache_filled_by_id_of_a_group_is_a_document_cache():
    """The guard for the next cache: a dict the viewport fills with
    ``cache[id(group)]`` (or a child, or a mesh) must be in the list."""
    from views.viewport import Viewport
    src = (Path(__file__).resolve().parents[1] / "views" / "viewport.py"
           ).read_text(encoding="utf-8")
    listed = set(Viewport._DOCUMENT_CACHES)
    missing = set()
    for m in re.finditer(r"cache = self\.(_\w+) = \{\}", src):
        name = m.group(1)
        body = src[m.end():m.end() + 3000]
        if re.search(r"\[id\((group|g|child|mesh)\)\]", body) \
                and name not in listed:
            missing.add(name)
    assert not missing, missing
