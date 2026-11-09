# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A click changes the view, not the model (#158, «sin lag»).

On the plant of #158 each selection click rebuilt the pick index, the
silhouettes and every edge buffer, and rescanned the side panels — over a
second a click. A view-only bump (``Scene.bump_view``) now leaves what the
model IS alone and refreshes only what shows the selection."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _window():
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(800, 600)
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    vp = win.viewport
    for i in range(3):
        g = Group(m, name=f"G{i}")
        x = QMatrix4x4()
        x.translate(2.0 * i, 0.0, 0.0)
        g.xform = x
        vp.scene.groups.append(g)
    vp.scene.mesh.add_face([V(0, 3, 0), V(1, 3, 0), V(1, 4, 0)])
    vp.scene.version += 1
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_selection_keeps_the_pick_index():
    win = _window()
    try:
        vp = win.viewport
        idx = vp._pick_index()
        cv = vp.scene.content_version
        vp.scene.select([vp.scene.groups[1]])
        assert vp.scene.content_version == cv
        assert vp._pick_index() is idx
        vp.scene.version += 1                       # an edit: a new one
        assert vp._pick_index() is not idx
    finally:
        _close(win)


def _fake_gl(vp):
    """Record what the edge sync uploads, per slot — no GL here."""
    import re
    import views.viewport as vpmod
    sent: dict = {}

    def fake_upload(_vbo, slot, parts, empty=24):
        sent[slot] = len(b"".join(parts))
        return sent[slot]
    vp._upload_vbo = fake_upload
    src = open(vpmod.__file__, encoding="utf-8").read()
    for name in set(re.findall(r"self\.(_\w+_vbo)\b", src)):
        if not hasattr(vp, name):
            setattr(vp, name, None)
    return sent


def test_a_selection_refreshes_only_the_selection_buffers():
    win = _window()
    try:
        vp = win.viewport
        sent = _fake_gl(vp)
        vp._sync_edges()
        assert "edges" in sent and vp._selected_count == 0
        sent.clear()
        vp.scene.select(list(vp.scene.edges)[:2])
        vp._sync_edges()
        assert "edges" not in sent                  # the model's: kept
        assert vp._selected_count == 4              # two edges' ends
        assert vp._edges_version == vp.scene.version
        vp.scene.clear_selection()
        vp._sync_edges()
        assert vp._selected_count == 0
        vp.scene.version += 1                       # an edit: all again
        vp._sync_edges()
        assert "edges" in sent
    finally:
        _close(win)
