# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pick index's heavy parts start behind a big document as it opens
(#1092): the first move of the pointer, whatever the tool, took 4 s on a model
of 5 M faces. What the threads make is what the hover would have made, is
taken only on the GUI thread, and only if the document has not moved on.
Skipped without the engine."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from tests.test_lazy_native_snap import (  # noqa: E402
    VIEWS, _close, _face_key, _set_view, _window)
from views import viewport as vpmod  # noqa: E402

_app = QApplication.instance() or QApplication([])
mod = _native.native
pytestmark = pytest.mark.skipif(
    mod is None or not hasattr(mod, "InstanceSet"),
    reason="engine off or not built")


@pytest.fixture(autouse=True)
def every_chunk_has_a_grid(monkeypatch):
    # The test's chunks are small: without this no grid would be worked out.
    monkeypatch.setattr(vpmod, "_SPAN_GRID_MIN", 4)
    monkeypatch.setattr(vpmod, "_SPAN_CELL_TRIS", 4, raising=False)


def test_the_warmed_index_answers_as_the_cold_one():
    a, va = _window(lazy=True)
    b, vb = _window(lazy=True)
    try:
        va.start_pick_warmup()
        warm = va._pick_warm
        assert warm is not None
        warm.join()
        assert warm.protos and warm.grids
        seen = 0
        for view in VIEWS:
            _set_view(va, view)
            _set_view(vb, view)
            for x in np.arange(8.3, 900, 41.0):
                for y in np.arange(5.9, 640, 43.0):
                    x, y = float(x), float(y)
                    va._input_serial = vb._input_serial = (x, y)
                    fa = va.pick_face_placement(x, y)
                    fb = vb.pick_face_placement(x, y)
                    assert _face_key(*fa) == _face_key(*fb), (view, x, y)
                    ga, gb = va.pick_group(x, y), vb.pick_group(x, y)
                    assert (getattr(ga, "name", None)
                            == getattr(gb, "name", None)), (view, x, y)
                    seen += fb[0] is not None
        assert seen > 50
        # And they did use what the threads made, not their own.
        assert va._pick_warm is None
        for key, ip in warm.protos.items():
            assert va._inst_proto_cache[key] is ip
        for chunk, snap in warm.grids:
            assert chunk["_span_grid"] is snap["_span_grid"]
    finally:
        _close(a)
        _close(b)


def test_a_grid_of_arrays_that_have_changed_is_left_out():
    a, va = _window(lazy=True)
    try:
        va.start_pick_warmup()
        warm = va._pick_warm
        warm.join()
        assert len(warm.grids) >= 2
        moved, swapped = warm.grids[0][0], warm.grids[1][0]
        moved["rev"] = (moved.get("rev") or 0, "after")
        swapped["v0"] = swapped["v0"].copy()
        vpmod._pick_warm_take(va)
        assert "_span_grid" not in moved
        assert "_span_grid" not in swapped
    finally:
        _close(a)


def test_a_new_document_forgets_the_warmup():
    a, va = _window(lazy=True)
    try:
        va.start_pick_warmup()
        assert va._pick_warm is not None
        va._pick_warm.join()
        va.reset_document_caches()
        assert va._pick_warm is None
    finally:
        _close(a)


def test_a_model_without_lazy_placements_starts_nothing():
    a, va = _window(lazy=False)
    try:
        va.start_pick_warmup()
        assert getattr(va, "_pick_warm", None) is None
    finally:
        _close(a)


def test_it_starts_after_the_first_frame_of_an_opened_document(tmp_path,
                                                                monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer
    from formats import igz
    from views.main_window import MainWindow
    a, va = _window(lazy=True)
    path = tmp_path / "d.igz"
    igz.save_scene(va.scene, path)
    _close(a)
    calls = []
    monkeypatch.setattr(vpmod.Viewport, "start_pick_warmup",
                        lambda self: calls.append(self))
    monkeypatch.setattr(vpmod.Viewport, "_paint_frame",
                        lambda self: calls.append("frame"))
    win = MainWindow()
    try:
        assert win.open_path(path) is not False
        assert calls == []
        vp = win.viewport
        vp.paintGL()
        assert calls == ["frame"], "beside the frame, not after it"

        def run():
            loop = QEventLoop()
            QTimer.singleShot(20, loop.quit)
            loop.exec()
        run()
        assert calls == ["frame", vp]
        vp.paintGL()
        run()
        assert calls == ["frame", vp, "frame"], "once a document"
    finally:
        _close(win)


def test_the_pointer_that_got_there_first_needs_no_warmup():
    a, va = _window(lazy=True)
    try:
        _set_view(va, VIEWS[0])
        va._input_serial = (100.0, 100.0)
        va.pick_group(100.0, 100.0)
        assert va._inst_set_memo is not None
        va.start_pick_warmup()
        assert getattr(va, "_pick_warm", None) is None
    finally:
        _close(a)
