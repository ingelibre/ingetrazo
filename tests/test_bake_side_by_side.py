# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A big document opens with its meshes baked side by side (#1092): every
bake is the one made alone, field for field, the numbers still given in the
placements' order. Skipped without the engine."""
from __future__ import annotations

import os
import random
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core import mesh as M  # noqa: E402
from formats import igz  # noqa: E402
from tests.test_deferred_mesh import _random_scene  # noqa: E402
from views import array_bake  # noqa: E402

_app = QApplication.instance() or QApplication([])
nat = _native.native
pytestmark = pytest.mark.skipif(
    nat is None or _native.qt_hypot() is None,
    reason="engine off or not built")

SKIP = {"fp", "mesh", "faces", "vkey", "flags_gen"}


def _plain(v):
    if isinstance(v, np.ndarray):
        return (v.dtype.str, v.shape, v.tobytes())
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _entries(vp):
    from views.viewport import _paint_of
    out = []
    for g in vp._placements():
        paint = _paint_of(vp, g)
        c = (vp._proto_base_chunk(g.mesh, paint)
             if getattr(g, "xform", None) is not None else vp._group_chunk(g))
        out.append({k: _plain(v) for k, v in c.items() if k not in SKIP})
    return out


def _doc(tmp_path, seed):
    scene = _random_scene(random.Random(seed))
    placed = [g for g in scene.groups if g.xform is not None]
    placed[0].material = {"color": [0.1, 0.8, 0.3]}
    placed[1].material = {"color": [0.7, 0.2, 0.6]}
    path = tmp_path / f"d{seed}.igz"
    igz.save_scene(scene, path)
    return path


def _window(path):
    from views.main_window import MainWindow
    win = MainWindow()
    assert win.open_path(path) is not False
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


@pytest.mark.parametrize("seed", range(4))
def test_each_bake_is_the_one_made_alone(tmp_path, monkeypatch, seed):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    path = _doc(tmp_path, seed)
    together = _window(path)
    with monkeypatch.context() as m:
        m.setattr(array_bake, "prebake", lambda vp, jobs: None)
        alone = _window(path)
    try:
        assert any(type(g.mesh) is M.DeferredMesh
                   for g in together.viewport._placements())
        a, b = _entries(together.viewport), _entries(alone.viewport)
        for k, (x, y) in enumerate(zip(a, b)):
            # Numbered per process, the same order in both.
            x["uid"] = y["uid"] = None
            assert x.keys() == y.keys()
            for field in x:
                assert x[field] == y[field], (k, field)
        # The test tells the two paints apart, or the first assert says little.
        assert a[0]["vcol"] != a[1]["vcol"]
    finally:
        _close(together)
        _close(alone)


def test_the_threads_did_the_baking_and_nothing_is_left(tmp_path, monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    path = _doc(tmp_path, 1)
    where = []
    real = array_bake._bake

    def spy(vp, mesh, paint, msig):
        where.append(threading.current_thread() is threading.main_thread())
        return real(vp, mesh, paint, msig)
    monkeypatch.setattr(array_bake, "_bake", spy)
    win = _window(path)
    try:
        assert where and not any(where)
        assert win.viewport._prebaked is None
        n = len(where)
        _entries(win.viewport)
        assert len(where) == n, "a prebaked mesh baked again"
    finally:
        _close(win)
