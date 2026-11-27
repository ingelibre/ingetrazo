# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move of a face inside a big group (a vertex preview, which freezes the
version) keeps the placements' epoch without walking every placement
again on each hover (19-11): the epoch it keeps is the one a fresh walk
makes, frame after frame, and anything the walk reads that moves (a layer,
a group's matrix, a hidden flag) still makes it walk."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from tests.test_move_verts_preview import _block, _ctx, _drag, _grid_group  # noqa: E402

_app = QApplication.instance() or QApplication([])

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())
    from views import array_bake
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 0)
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    if getattr(w.viewport, "_gl", None) is None or not w.viewport.isValid():
        # The preview draws from GL buffers: with no context (the
        # offscreen platform on macOS) it never starts.
        w._saved_version = w.viewport.scene.version
        w.close()
        pytest.skip("no OpenGL context on this platform")
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _fresh(vp):
    """The epoch a walk makes now, with every shortcut forgotten."""
    keep = (getattr(vp, "_epoch_memo", None), getattr(vp, "_epoch_same", None),
            getattr(vp, "_epoch_frozen_base", None))
    vp._epoch_memo = vp._epoch_same = vp._epoch_frozen_base = None
    try:
        return vp._placements_epoch()
    finally:
        vp._epoch_memo, vp._epoch_same, vp._epoch_frozen_base = keep


def _others(vp, n=40):
    from core.group import Group
    from core.mesh import Mesh
    out = []
    for k in range(n):
        m = Mesh()
        m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
        g = Group(m, f"g{k}")
        xf = QMatrix4x4()
        xf.translate(50 + 2 * k, 0, 0)
        g.xform = xf
        vp.scene.groups.append(g)
        out.append(g)
    vp.scene.version += 1
    return out


def test_a_vertex_drag_keeps_the_epoch_a_walk_makes(win, monkeypatch):
    vp = _grid_group(win)
    others = _others(vp)
    mesh = vp.scene.mesh
    block = _block(mesh, 2, 4)
    tool, ctx = _drag(win, vp, block)
    assert tool._vp_preview and vp._verts_preview is not None
    walks = []
    real = type(vp)._epoch_remember
    monkeypatch.setattr(type(vp), "_epoch_remember",
                        lambda self, *a, **k: (walks.append(1), real(self, *a, **k)))
    vp._placements_epoch()                   # the drag's first: may walk
    walks.clear()
    for k in range(1, 6):
        vp._tick = getattr(vp, "_tick", 0) + 1
        tool.on_hover(_ctx(vp, ctx.world + V(0.1 * k, 0, 0.2 * k), 10 + k))
        _app.processEvents()
        vp._tick += 1
        got = vp._placements_epoch()
        n = len(walks)
        assert got == _fresh(vp)
        del walks[n:]                        # (the check's own walk)
    assert walks == [], "a hover of the vertex drag walked the placements"
    # What the walk reads still re-keys it: a layer turned off, a group
    # hidden and moved by commands (they bump the scene's version).
    before = vp._placements_epoch()
    vp.scene.layers[0].visible = not vp.scene.layers[0].visible
    vp._tick += 1
    assert vp._placements_epoch() == _fresh(vp) != before
    vp.scene.layers[0].visible = not vp.scene.layers[0].visible
    g = others[3]
    g.hidden = True
    xf = QMatrix4x4()
    xf.translate(0, 9, 0)
    g.xform = xf
    vp.scene.version += 1
    vp._tick += 1
    assert vp._placements_epoch() == _fresh(vp) != before
    tool.on_cancel(vp)
    _app.processEvents()
    assert vp._verts_preview is None
    vp._tick += 1
    assert vp._placements_epoch() == _fresh(vp)


def test_a_groups_preview_still_walks_its_movers(win):
    """A drag of whole groups (their matrices move with no version bump)
    keeps its own frozen path."""
    vp = _grid_group(win)
    vp.end_group_edit()
    others = _others(vp, 10)
    vp._placements_epoch()
    vp.begin_groups_preview(others[:2])
    try:
        assert getattr(vp, "_verts_preview", None) is None
        e0 = vp._placements_epoch()
        xf = QMatrix4x4()
        xf.translate(0, 3, 0)
        others[0].xform = xf
        vp._tick = getattr(vp, "_tick", 0) + 1
        e1 = vp._placements_epoch()
        assert e1 != e0 and e1 == _fresh(vp)
        for k in range(2, 5):                # every frame of the drag
            xf = QMatrix4x4()
            xf.translate(0, 3 * k, 0)
            others[0].xform = xf
            vp._tick += 1
            e2 = vp._placements_epoch()
            assert e2 != e1 and e2 == _fresh(vp)
            e1 = e2
    finally:
        vp.end_groups_preview()
